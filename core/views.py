import pandas as pd
import csv
import io
import json
import time # Para dar um efeito visual (opcional)
from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from .forms import FuncionarioForm
from .models import Funcionario, RegistroPonto, PisIgnorado, MatriculaIgnorada
from django.db import IntegrityError
from datetime import datetime, date
import calendar


@login_required
def home(request):
    return render(request, 'core/home.html')

@login_required
def cadastrar_funcionario(request):
    if request.method == 'POST':
        form = FuncionarioForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('listar_funcionarios')
    else:
        # Agora ele preenche automático se vier PIS ou Matrícula na URL!
        pis_pre = request.GET.get('pis', '')
        matricula_pre = request.GET.get('matricula', '')
        form = FuncionarioForm(initial={'pis': pis_pre, 'matricula': matricula_pre})

    return render(request, 'core/cadastrar.html', {'form': form})

@login_required
def listar_funcionarios(request):
    # Se a requisição tiver um parâmetro 'q' (que será enviado pelo JavaScript)
    if 'q' in request.GET:
        query = request.GET.get('q')

        # Só busca se tiver 3 ou mais letras
        if len(query) >= 3:
            # __icontains faz a busca ignorando maiúsculas/minúsculas. 
            # O MySQL cuida de ignorar os acentos automaticamente!
            resultados = Funcionario.objects.filter(nome_completo__icontains=query)

            # Monta uma lista de dicionários para enviar ao JavaScript
            dados = []
            for func in resultados:
                dados.append({
                    'id': func.id,
                    'matricula': func.matricula,
                    'nome_completo': func.nome_completo,
                    'pis': func.pis,
                    'cpf': func.cpf,
                    'grupo': func.grupo_ponto if func.grupo_ponto else 'Sem Grupo'
                })
            return JsonResponse({'funcionarios': dados})
        else:
            return JsonResponse({'funcionarios': []})

    # Se não for uma busca, apenas carrega a página vazia
    return render(request, 'core/listar.html')

@login_required
def importar_funcionarios(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        
        if arquivo:
            linhas = arquivo.read().decode('utf-8').splitlines()
            linhas_limpas = [linha.strip() for linha in linhas if linha.strip()]
            
            for i in range(0, len(linhas_limpas), 4):
                if i + 3 < len(linhas_limpas):
                    matricula_txt = linhas_limpas[i]
                    nome_txt = linhas_limpas[i+1]
                    pis_txt = linhas_limpas[i+2]
                    cpf_txt = linhas_limpas[i+3]
                    
                    # 1. Verifica se a matrícula já existe
                    if not Funcionario.objects.filter(matricula=matricula_txt).exists():
                        # 2. Tenta salvar. Se esbarrar em um PIS ou CPF repetido, ele cai no "except"
                        try:
                            Funcionario.objects.create(
                                matricula=matricula_txt,
                                nome_completo=nome_txt,
                                pis=pis_txt,
                                cpf=cpf_txt
                            )
                        except IntegrityError:
                            # Se der erro de banco de dados (dado duplicado), apenas ignora e continua o loop
                            pass
            
            return redirect('listar_funcionarios')

    return render(request, 'core/importar.html')

@login_required
def ver_ponto(request, funcionario_id):
    funcionario = Funcionario.objects.get(id=funcionario_id)

    # Pega o ano e mês da URL (se não tiver, usa o mês atual)
    hoje = date.today()
    ano = int(request.GET.get('ano', hoje.year))
    mes = int(request.GET.get('mes', hoje.month))

    # Descobre quantos dias tem o mês selecionado
    _, num_dias = calendar.monthrange(ano, mes)

    # Busca se já tem batidas salvas no banco para esse mês
    registros = RegistroPonto.objects.filter(
        funcionario=funcionario, 
        data__year=ano, 
        data__month=mes
    )
    # Cria um dicionário para achar rápido: {1: registro_do_dia_1, ...}
    registros_dict = {reg.data.day: reg for reg in registros}

    # Monta a lista completa com todos os dias do mês
    dias_do_mes = []
    dias_semana = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']

    for dia in range(1, num_dias + 1):
        data_atual = date(ano, mes, dia)
        dia_semana_str = dias_semana[data_atual.weekday()]

        dias_do_mes.append({
            'data_formatada': data_atual.strftime('%d/%m/%Y'),
            'data_iso': data_atual.strftime('%Y-%m-%d'),
            'dia_semana': dia_semana_str,
            'registro': registros_dict.get(dia),
            'editado_manualmente': registros_dict.get(dia).editado_manualmente if registros_dict.get(dia) else False
        })

    contexto = {
        'funcionario': funcionario,
        'ano_selecionado': ano,
        'mes_selecionado': mes,
        'anos': range(2020, 2031), # Opções da caixa de seleção
        'meses': range(1, 13),
        'dias_do_mes': dias_do_mes,
    }
    return render(request, 'core/ponto.html', contexto)

@login_required
def salvar_ponto(request):
    if request.method == 'POST':
        try:
            # Lê os dados enviados pelo JavaScript
            dados = json.loads(request.body)
            funcionario_id = dados.get('funcionario_id')
            data_iso = dados.get('data')

            # Função auxiliar para transformar vazio ("") em Nulo (None)
            def limpar_hora(hora):
                return hora if hora else None

            funcionario = Funcionario.objects.get(id=funcionario_id)

            # O 'update_or_create' é mágico: Se não existir ponto no dia, ele cria. Se existir, ele atualiza!
            RegistroPonto.objects.update_or_create(
                funcionario=funcionario,
                data=data_iso,
                defaults={
                    'dia_semana': dados.get('dia_semana'),
                    'entrada_1': limpar_hora(dados.get('e1')),
                    'saida_1': limpar_hora(dados.get('s1')),
                    'entrada_2': limpar_hora(dados.get('e2')),
                    'saida_2': limpar_hora(dados.get('s2')),
                    'entrada_3': limpar_hora(dados.get('e3')),
                    'saida_3': limpar_hora(dados.get('s3')),
                    'editado_manualmente': True,
                }
            )
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)})

    return JsonResponse({'status': 'invalido'})

@login_required
def importar_afd(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        grupo_ponto = request.POST.get('grupo_ponto')
        
        if arquivo:
            # Precisamos ler o arquivo todo para a memória antes de iniciar o stream
            conteudo = arquivo.read().decode('utf-8', errors='ignore')
            linhas = conteudo.splitlines()

            # Esta é a função geradora que vai "cuspir" as linhas para o navegador
            def stream_processamento():
                # 1. Envia o Cabeçalho HTML e Estilo (Tela Preta estilo Terminal)
                yield """
                <html>
                <head>
                    <style>
                        body { background-color: #1e1e1e; color: #00ff00; font-family: 'Courier New', monospace; padding: 20px; }
                        .log-line { margin: 2px 0; border-bottom: 1px solid #333; }
                        .success { color: #00ff00; }
                        .warning { color: #ffeb3b; }
                        .error { color: #ff5252; }
                        .info { color: #00bcd4; }
                        .summary { margin-top: 20px; font-size: 1.2em; border-top: 2px solid white; padding-top: 10px; }
                        .btn { display: inline-block; padding: 10px 20px; background: white; color: black; text-decoration: none; border-radius: 5px; margin-top: 20px; font-weight: bold;}
                    </style>
                </head>
                <body>
                <h2>Iniciando Processamento do Arquivo AFD...</h2>
                <div id="terminal">
                """
                
                pis_desconhecidos = set()
                total_linhas = len(linhas)
                processados = 0
                
                dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
                funcionarios_atualizados = []

                for i, linha in enumerate(linhas):
                    linha = linha.strip()
                    if not linha:
                        continue
                    
                    if linha.startswith('000000000') or len(linha) < 34:
                        continue

                    # Apenas processa registros de ponto (Tipo 3)
                    if linha[9] == '3':
                        msg_log = ""
                        status_css = "info"
                        
                        try:
                            # === DETECTOR DE FORMATO ===
                            if linha[14] == '-': 
                                # NOVO
                                data_txt = linha[10:20]
                                hora_txt = linha[21:26]
                                identificador_txt = linha[34:45]
                                data_batida = datetime.strptime(data_txt, '%Y-%m-%d').date()
                                hora_batida = datetime.strptime(hora_txt, '%H:%M').time()
                            else:
                                # LEGADO
                                data_txt = linha[10:18]
                                hora_txt = linha[18:22]
                                identificador_txt = linha[23:34]
                                data_batida = datetime.strptime(data_txt, '%d%m%Y').date()
                                hora_batida = datetime.strptime(hora_txt, '%H%M').time()

                            # Verifica se está na lista negra
                            if PisIgnorado.objects.filter(pis=identificador_txt).exists():
                                yield f"<div class='log-line warning'>[IGNORADO] PIS/CPF {identificador_txt} está na lista negra.</div>"
                                continue

                            # Busca Funcionário
                            funcionario = Funcionario.objects.filter(pis=identificador_txt).first()
                            if not funcionario:
                                funcionario = Funcionario.objects.filter(cpf=identificador_txt).first()

                            if funcionario:
                                msg_log = f"[SUCESSO] {funcionario.nome_completo} - {data_batida} às {hora_batida}"
                                status_css = "success"

                                # Atualiza Grupo
                                if grupo_ponto and funcionario.id not in funcionarios_atualizados:
                                    funcionario.grupo_ponto = grupo_ponto
                                    funcionario.save()
                                    funcionarios_atualizados.append(funcionario.id)
                                    msg_log += " (Grupo Atualizado)"

                                # Salva Ponto
                                registro, created = RegistroPonto.objects.get_or_create(
                                    funcionario=funcionario,
                                    data=data_batida,
                                    defaults={'dia_semana': dias_semana_pt[data_batida.weekday()]}
                                )

                                if not registro.editado_manualmente:
                                    batidas_existentes = []
                                    for campo in ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']:
                                        hora_salva = getattr(registro, campo)
                                        if hora_salva:
                                            batidas_existentes.append(hora_salva)

                                    if hora_batida not in batidas_existentes and len(batidas_existentes) < 6:
                                        batidas_existentes.append(hora_batida)
                                        batidas_existentes.sort()
                                        
                                        # Reorganiza
                                        registro.entrada_1 = batidas_existentes[0] if len(batidas_existentes) > 0 else None
                                        registro.saida_1 = batidas_existentes[1] if len(batidas_existentes) > 1 else None
                                        registro.entrada_2 = batidas_existentes[2] if len(batidas_existentes) > 2 else None
                                        registro.saida_2 = batidas_existentes[3] if len(batidas_existentes) > 3 else None
                                        registro.entrada_3 = batidas_existentes[4] if len(batidas_existentes) > 4 else None
                                        registro.saida_3 = batidas_existentes[5] if len(batidas_existentes) > 5 else None
                                        registro.save()
                                    else:
                                        msg_log += " (Dia Cheio ou Batida Duplicada)"
                            else:
                                msg_log = f"[DESCONHECIDO] PIS/CPF {identificador_txt} não encontrado no banco."
                                status_css = "error"
                                pis_desconhecidos.add(identificador_txt)

                        except Exception as e:
                            msg_log = f"[ERRO DE LEITURA] Linha {i}: {str(e)}"
                            status_css = "error"

                        # ENVIA A LINHA PROCESSADA PARA A TELA IMEDIATAMENTE
                        yield f"<div class='log-line {status_css}'>{msg_log}</div>"
                        
                        # Auto-scroll para baixo via Javascript injetado
                        yield "<script>window.scrollTo(0, document.body.scrollHeight);</script>"

                # FIM DO PROCESSO
                yield "</div>" # fecha div terminal
                
                if pis_desconhecidos:
                    yield "<div class='summary error'>⚠️ Foram encontrados PIS/CPFs desconhecidos!</div>"
                    yield "<ul>"
                    for pis in pis_desconhecidos:
                        yield f"<li>{pis}</li>"
                    yield "</ul>"
                    yield "<p>Copie os números acima e cadastre-os.</p>"
                else:
                    yield "<div class='summary success'>✅ Importação concluída com sucesso total!</div>"

                yield f"<br><a href='/gerenciar/' class='btn'>Voltar para Funcionários</a>"
                yield "</body></html>"

            # Retorna o Stream em vez de uma página estática
            return StreamingHttpResponse(stream_processamento())

    return render(request, 'core/importar_afd.html')

@login_required
def exportar_afd(request):
    if request.method == 'POST':
        data_inicio = request.POST.get('data_inicio')
        data_fim = request.POST.get('data_fim')
        tipo = request.POST.get('tipo_exportacao')
        
        # 1. Filtra os registros com base nas datas escolhidas
        filtros = {}
        if data_inicio:
            filtros['data__gte'] = data_inicio
        if data_fim:
            filtros['data__lte'] = data_fim

        # 2. Aplica o filtro de Grupo ou Funcionário, se selecionado
        if tipo == 'grupo':
            grupo = request.POST.get('grupo')
            if grupo:
                filtros['funcionario__grupo_ponto'] = grupo
        elif tipo == 'funcionario':
            func_id = request.POST.get('funcionario_id')
            if func_id:
                filtros['funcionario__id'] = func_id

        # Faz a busca no banco de dados
        registros = RegistroPonto.objects.filter(**filtros)

        # 3. Desmonta as batidas diárias em batidas individuais
        # Cria uma lista de tuplas: (data, hora, pis)
        batidas = []
        for reg in registros:
            pis = reg.funcionario.pis
            data_batida = reg.data
            for campo in ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']:
                hora = getattr(reg, campo)
                if hora:
                    batidas.append((data_batida, hora, pis))
        
        # 4. Ordena tudo cronologicamente (Primeiro por Data, depois por Hora)
        batidas.sort(key=lambda x: (x[0], x[1]))

        # 5. Monta o arquivo texto
        linhas_arquivo = []
        
        # Cabeçalho Fixo (exatamente como você mandou)
        linhas_arquivo.append("00000000011466342180001070000000000000PREFEITURA DE TAQUARITUBA                                                                                                   AYSE090514002025-04-102025-08-01010820250721000020272301072025044801902610592719dc")
        
        nsr = 1 # Número Sequencial de Registro
        for b in batidas:
            data_str = b[0].strftime('%d%m%Y')
            hora_str = b[1].strftime('%H%M')
            pis_str = str(b[2]).zfill(11) # Garante que o PIS tenha 11 dígitos
            nsr_str = str(nsr).zfill(9)   # Garante que o NSR tenha 9 dígitos
            
            # Formata a linha conforme o mapeamento que você fez: NSR + '3' + DATA + HORA + '0' + PIS
            linha = f"{nsr_str}3{data_str}{hora_str}0{pis_str}"
            linhas_arquivo.append(linha)
            nsr += 1
        
        # Rodapé Fixo (conforme você mandou)
        linhas_arquivo.append("99999999900000000000000110300000000000000000009")

        # 6. Prepara a resposta para Download
        # Usa \r\n para pular linha mantendo a compatibilidade do Bloco de Notas (Windows)
        conteudo = '\r\n'.join(linhas_arquivo) 
        
        response = HttpResponse(conteudo, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="AFD_Exportado_{data_inicio}_a_{data_fim}.txt"'
        
        return response

    # Se for GET (Apenas abrindo a página), pega os dados para o formulário
    # Busca apenas os grupos que não estão vazios
    grupos = Funcionario.objects.exclude(grupo_ponto__isnull=True).exclude(grupo_ponto__exact='').values_list('grupo_ponto', flat=True).distinct()
    funcionarios = Funcionario.objects.all().order_by('nome_completo')
    
    return render(request, 'core/exportar_afd.html', {'grupos': grupos, 'funcionarios': funcionarios})

@login_required
def salvar_grupo(request):
    if request.method == 'POST':
        try:
            # Lê os dados enviados pelo JavaScript
            dados = json.loads(request.body)
            funcionario_id = dados.get('funcionario_id')
            novo_grupo = dados.get('grupo')
            
            # Busca o funcionário e atualiza o grupo
            funcionario = Funcionario.objects.get(id=funcionario_id)
            
            # Se a pessoa apagar o texto, salva como None (vazio no banco)
            funcionario.grupo_ponto = novo_grupo if novo_grupo.strip() else None
            funcionario.save()
            
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)})
            
    return JsonResponse({'status': 'invalido'})

@login_required
def ignorar_pis(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            pis = dados.get('pis')
            PisIgnorado.objects.get_or_create(pis=pis)
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'status': 'erro'})
    return JsonResponse({'status': 'invalido'})

@login_required
def importar_planilha(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        grupo_ponto = request.POST.get('grupo_ponto')
        
        if arquivo:
            try:
                # O Pandas é mágico! Ele lê o arquivo direto da memória.
                # dtype=str garante que ele não apague os zeros à esquerda das matrículas
                df = pd.read_excel(arquivo, dtype=str)
                
            except Exception as e:
                # Se der erro no Excel, pode ser que o usuário mandou um CSV mesmo. O Pandas lê também!
                print(f"Tentando ler como CSV... Erro anterior: {e}")
                arquivo.seek(0)
                df = pd.read_csv(arquivo, sep=None, engine='python', dtype=str)

            # Limpa espaços em branco dos nomes das colunas
            df.columns = df.columns.str.strip()
            
            # Converte a tabela perfeita em uma lista de dicionários para lermos
            linhas = df.to_dict('records')

            dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
            funcionarios_atualizados = []
            matriculas_desconhecidas = set()

            print(f"\n--- INICIANDO IMPORTAÇÃO EXCEL/CSV (Colunas: {list(df.columns)}) ---")

            for linha in linhas:
                # Pega a Matrícula e Hora e garante que são textos limpos
                matricula_txt = str(linha.get('ID', '')).strip()
                hora_completa_txt = str(linha.get('Hora', '')).strip()

                # O Pandas preenche células vazias com a palavra 'nan' (Not a Number), então pulamos elas
                if not matricula_txt or matricula_txt == 'nan' or not hora_completa_txt or hora_completa_txt == 'nan':
                    continue
                    
                if MatriculaIgnorada.objects.filter(matricula=matricula_txt).exists():
                    continue
                    
                try:
                    dt_obj = datetime.strptime(hora_completa_txt, '%d/%m/%Y %H:%M:%S')
                except ValueError:
                    try:
                        dt_obj = datetime.strptime(hora_completa_txt, '%d/%m/%Y %H:%M')
                    except ValueError:
                        print(f"Formato de data inválido ignorado: {hora_completa_txt}")
                        continue
                        
                data_batida = dt_obj.date()
                hora_batida = dt_obj.time()
                
                funcionario = Funcionario.objects.filter(matricula=matricula_txt).first()
                
                if funcionario:
                    print(f"Salvo: {funcionario.nome_completo} - {data_batida} às {hora_batida}")
                    
                    if grupo_ponto and funcionario.id not in funcionarios_atualizados:
                        funcionario.grupo_ponto = grupo_ponto
                        funcionario.save()
                        funcionarios_atualizados.append(funcionario.id)
                        
                    registro, created = RegistroPonto.objects.get_or_create(
                        funcionario=funcionario,
                        data=data_batida,
                        defaults={'dia_semana': dias_semana_pt[data_batida.weekday()]}
                    )

                    if registro.editado_manualmente:
                        continue

                    batidas_existentes = []
                    for campo in ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']:
                        hora_salva = getattr(registro, campo)
                        if hora_salva:
                            batidas_existentes.append(hora_salva)

                    if hora_batida not in batidas_existentes and len(batidas_existentes) < 6:
                        batidas_existentes.append(hora_batida)
                        batidas_existentes.sort()

                        registro.entrada_1 = batidas_existentes[0] if len(batidas_existentes) > 0 else None
                        registro.saida_1 = batidas_existentes[1] if len(batidas_existentes) > 1 else None
                        registro.entrada_2 = batidas_existentes[2] if len(batidas_existentes) > 2 else None
                        registro.saida_2 = batidas_existentes[3] if len(batidas_existentes) > 3 else None
                        registro.entrada_3 = batidas_existentes[4] if len(batidas_existentes) > 4 else None
                        registro.saida_3 = batidas_existentes[5] if len(batidas_existentes) > 5 else None
                        registro.save()
                else:
                    matriculas_desconhecidas.add(matricula_txt)

            print("--- FIM DA IMPORTAÇÃO ---\n")
            
            if matriculas_desconhecidas:
                return render(request, 'core/importar_planilha.html', {
                    'alerta_matricula': True,
                    'matriculas_desconhecidas': list(matriculas_desconhecidas)
                })

            return redirect('listar_funcionarios')

    return render(request, 'core/importar_planilha.html')

@login_required
def ignorar_matricula(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            matricula = dados.get('matricula')
            MatriculaIgnorada.objects.get_or_create(matricula=matricula)
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'status': 'erro'})
    return JsonResponse({'status': 'invalido'})
