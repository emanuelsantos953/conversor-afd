import pandas as pd
import csv
import io
import json
import time 
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from .forms import FuncionarioForm
from .models import Funcionario, RegistroPonto, PisIgnorado, MatriculaIgnorada, CpfIgnorado, Grupo
from django.db import IntegrityError
from django.db.models import Q  
from datetime import datetime, date
import calendar

# ==========================================
# CONTROLE DE ACESSOS E MENU PRINCIPAL
# ==========================================

# Regra de segurança: Só superusuários (como o adminvm) podem acessar
def is_admin(user):
    return user.is_superuser

@user_passes_test(is_admin)
def gerenciar_usuarios(request):
    if request.method == 'POST':
        acao = request.POST.get('acao', 'novo')
        username = request.POST.get('username')
        senha = request.POST.get('senha')
        acesso_conversor = request.POST.get('acesso_conversor') == 'on'

        # ==========================================
        # MODO EDIÇÃO DE USUÁRIO
        # ==========================================
        if acao == 'editar':
            user_id = request.POST.get('user_id')
            usuario_edit = get_object_or_404(User, id=user_id)
            
            grupo_conv, _ = Group.objects.get_or_create(name='Conversor')
            
            # Atualiza os acessos ao conversor
            if acesso_conversor: 
                usuario_edit.groups.add(grupo_conv)
            else: 
                usuario_edit.groups.remove(grupo_conv)
            
            # Atualiza a senha APENAS se o campo não estiver em branco
            if senha:
                usuario_edit.set_password(senha)
            
            usuario_edit.save()
                
            messages.success(request, f'Dados de {usuario_edit.username} atualizados!')
            return redirect('gerenciar_usuarios')

        # ==========================================
        # MODO CRIAÇÃO DE USUÁRIO NOVO
        # ==========================================
        elif acao == 'novo':
            if User.objects.filter(username=username).exists():
                messages.error(request, f'O usuário {username} já existe!')
            else:
                user = User.objects.create_user(username=username, password=senha)
                
                if acesso_conversor:
                    grupo_conv, _ = Group.objects.get_or_create(name='Conversor')
                    user.groups.add(grupo_conv)
                    
                messages.success(request, f'Usuário {username} criado com sucesso!')
                return redirect('gerenciar_usuarios')

    usuarios = list(User.objects.all().prefetch_related('groups'))

    return render(request, 'core/gerenciar_usuarios.html', {'usuarios': usuarios})

@login_required
def home(request):
    pode_acessar_conversor = request.user.is_superuser or request.user.groups.filter(name='Conversor').exists()

    return render(request, 'core/home.html', {
        'pode_acessar_conversor': pode_acessar_conversor,
    })


# ==========================================
# FUNCIONÁRIOS E CADASTROS
# ==========================================

@login_required
def cadastrar_funcionario(request):
    if request.method == 'POST':
        form = FuncionarioForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('listar_funcionarios')
    else:
        pis_pre = request.GET.get('pis', '')
        matricula_pre = request.GET.get('matricula', '')
        form = FuncionarioForm(initial={'pis': pis_pre, 'matricula': matricula_pre})

    return render(request, 'core/cadastrar.html', {'form': form})

@login_required
def listar_funcionarios(request):
    if 'q' in request.GET or 'grupo' in request.GET:
        query = request.GET.get('q', '').strip()
        grupo = request.GET.get('grupo', '').strip()

        resultados = Funcionario.objects.all()

        if len(query) >= 3:
            resultados = resultados.filter(
                Q(nome_completo__icontains=query) |
                Q(matricula__icontains=query) |
                Q(pis__icontains=query) |
                Q(cpf__icontains=query)
            )

        if grupo:
            resultados = resultados.filter(grupos__nome=grupo)

        if len(query) < 3 and not grupo:
            return JsonResponse({'funcionarios': []})

        dados = []
        for func in resultados[:100]:
            dados.append({
                'id': func.id,
                'matricula': func.matricula,
                'nome_completo': func.nome_completo,
                'pis': func.pis,
                'cpf': func.cpf,
                'grupo': ", ".join([g.nome for g in func.grupos.all()]) if func.grupos.exists() else 'Sem Grupo'
            })
        return JsonResponse({'funcionarios': dados})

    grupos_existentes = Grupo.objects.all().values_list('nome', flat=True)
    
    return render(request, 'core/listar.html', {'grupos': grupos_existentes})

@login_required
def atualizar_funcionario(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            funcionario_id = dados.get('funcionario_id')
            
            funcionario = Funcionario.objects.get(id=funcionario_id)
            funcionario.matricula = dados.get('matricula')
            funcionario.nome_completo = dados.get('nome')
            funcionario.pis = dados.get('pis')
            funcionario.cpf = dados.get('cpf')
            
            # Atualiza os grupos
            nomes_grupos = [g.strip() for g in dados.get('grupo', '').split(',') if g.strip()]
            grupos_objs = []
            for nome in nomes_grupos:
                g, _ = Grupo.objects.get_or_create(nome=nome)
                grupos_objs.append(g)
            
            funcionario.grupos.set(grupos_objs)
            funcionario.save()
            
            return JsonResponse({'status': 'sucesso'})
        except IntegrityError as e:
            return JsonResponse({'status': 'erro', 'mensagem': 'Matrícula, PIS ou CPF já cadastrados para outro funcionário.'})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)})
            
    return JsonResponse({'status': 'invalido'})


# ==========================================
# GESTÃO DE PONTO E REGISTROS
# ==========================================

@login_required
def ver_ponto(request, funcionario_id):
    funcionario = Funcionario.objects.get(id=funcionario_id)

    hoje = date.today()
    ano = int(request.GET.get('ano', hoje.year))
    mes = int(request.GET.get('mes', hoje.month))

    _, num_dias = calendar.monthrange(ano, mes)

    registros = RegistroPonto.objects.filter(
        funcionario=funcionario, 
        data__year=ano, 
        data__month=mes
    )
    registros_dict = {reg.data.day: reg for reg in registros}

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
        'anos': range(2020, 2031), 
        'meses': range(1, 13),
        'dias_do_mes': dias_do_mes,
    }
    return render(request, 'core/ponto.html', contexto)

@login_required
def salvar_ponto(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            funcionario_id = dados.get('funcionario_id')
            data_iso = dados.get('data')

            def limpar_hora(hora):
                return hora if hora else None

            funcionario = Funcionario.objects.get(id=funcionario_id)

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


# ==========================================
# IMPORTAÇÃO / EXPORTAÇÃO AFD (TXT)
# ==========================================

@login_required
def importar_afd(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        grupo_nome = request.POST.get('grupo_ponto')
        conflito_grupo = request.POST.get('conflito_grupo', 'adicionar')
        
        if arquivo:
            conteudo = arquivo.read().decode('utf-8', errors='ignore')
            linhas = conteudo.splitlines()

            def stream_processamento():
                yield """
                <html>
                <head>
                    <style>
                        body { background-color: #ffffff; color: #000000; font-family: 'Cascadia Mono', monospace; padding: 20px; margin: 0; }
                        .log-line { margin: 2px 0; border-bottom: 1px solid #eee; }
                        .success { color: #155724; }
                        .warning { color: #856404; }
                        .error { color: #721c24; }
                        .info { color: #0c5460; }
                        .summary { margin-top: 20px; font-size: 1.2em; border-top: 2px solid #000; padding-top: 10px; }
                        .btn { display: inline-block; padding: 10px 20px; background: #e0e0e0; color: black; text-decoration: none; border-radius: 5px; margin-top: 20px; font-weight: bold; border: 1px solid #ccc;}
                    </style>
                </head>
                <body>
                <h2>Iniciando Processamento do Arquivo AFD...</h2>
                <div id="terminal">
                """
                
                pis_desconhecidos = set()
                dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
                funcionarios_atualizados = []

                for i, linha in enumerate(linhas):
                    linha = linha.strip()
                    if not linha:
                        continue
                    
                    if linha.startswith('000000000') or len(linha) < 34:
                        continue

                    if linha[9] == '3':
                        msg_log = ""
                        status_css = "info"
                        
                        try:
                            if linha[14] == '-': 
                                data_txt = linha[10:20]
                                hora_txt = linha[21:26]
                                identificador_txt = linha[34:45]
                                data_batida = datetime.strptime(data_txt, '%Y-%m-%d').date()
                                hora_batida = datetime.strptime(hora_txt, '%H:%M').time()
                            else:
                                data_txt = linha[10:18]
                                hora_txt = linha[18:22]
                                identificador_txt = linha[23:34]
                                data_batida = datetime.strptime(data_txt, '%d%m%Y').date()
                                hora_batida = datetime.strptime(hora_txt, '%H%M').time()

                            if PisIgnorado.objects.filter(pis=identificador_txt).exists() or CpfIgnorado.objects.filter(cpf=identificador_txt).exists():
                                yield f"<div class='log-line warning'>[IGNORADO] PIS/CPF {identificador_txt} está na lista negra.</div>"
                                continue

                            funcionario = Funcionario.objects.filter(pis=identificador_txt).first()
                            if not funcionario:
                                funcionario = Funcionario.objects.filter(cpf=identificador_txt).first()

                            if funcionario:
                                msg_log = f"[SUCESSO] {funcionario.nome_completo} - {data_batida} às {hora_batida}"
                                status_css = "success"

                                if grupo_nome:
                                    g_obj, _ = Grupo.objects.get_or_create(nome=grupo_nome)
                                    if conflito_grupo == 'substituir':
                                        funcionario.grupos.set([g_obj])
                                    else:
                                        funcionario.grupos.add(g_obj)
                                    
                                    msg_log += f" (Grupo {grupo_nome} atualizado)"

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

                        yield f"<div class='log-line {status_css}'>{msg_log}</div>"
                        yield "<script>window.scrollTo(0, document.body.scrollHeight);</script>"

                yield "</div>" 
                
                if pis_desconhecidos:
                    yield "<div class='summary error'>⚠️ Foram encontrados PIS/CPFs desconhecidos!</div>"
                    yield "<ul>"
                    for pis in pis_desconhecidos:
                        yield f"<li>{pis}</li>"
                    yield "</ul>"
                    yield "<p>Copie os números acima e cadastre-os.</p>"
                else:
                    yield "<div class='summary success'>✅ Importação concluída com sucesso total!</div>"

                yield "</body></html>"

            return StreamingHttpResponse(stream_processamento())

    return render(request, 'core/importar_afd.html')

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
def exportar_afd(request):
    if request.method == 'POST':
        data_inicio = request.POST.get('data_inicio')
        data_fim = request.POST.get('data_fim')
        tipo = request.POST.get('tipo_exportacao')
        
        filtros = {}
        if data_inicio:
            filtros['data__gte'] = data_inicio
        if data_fim:
            filtros['data__lte'] = data_fim

        if tipo == 'grupo':
            grupo = request.POST.get('grupo')
            if grupo:
                filtros['funcionario__grupos__nome'] = grupo
        elif tipo == 'funcionario':
            func_id = request.POST.get('funcionario_id')
            if func_id:
                filtros['funcionario__id'] = func_id

        registros = RegistroPonto.objects.filter(**filtros)

        batidas = []
        for reg in registros:
            pis = reg.funcionario.pis
            data_batida = reg.data
            for campo in ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']:
                hora = getattr(reg, campo)
                if hora:
                    batidas.append((data_batida, hora, pis))
        
        batidas.sort(key=lambda x: (x[0], x[1]))

        linhas_arquivo = []
        linhas_arquivo.append("00000000011466342180001070000000000000PREFEITURA DE TAQUARITUBA                                                                                                   AYSE090514002025-04-102025-08-01010820250721000020272301072025044801902610592719dc")
        
        nsr = 1 
        for b in batidas:
            data_str = b[0].strftime('%d%m%Y')
            hora_str = b[1].strftime('%H%M')
            pis_str = str(b[2]).zfill(11) 
            nsr_str = str(nsr).zfill(9)   
            
            linha = f"{nsr_str}3{data_str}{hora_str}0{pis_str}"
            linhas_arquivo.append(linha)
            nsr += 1
        
        linhas_arquivo.append("99999999900000000000000110300000000000000000009")

        conteudo = '\r\n'.join(linhas_arquivo) 
        
        response = HttpResponse(conteudo, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="AFD_Exportado_{data_inicio}_a_{data_fim}.txt"'
        
        return response

    grupos = Grupo.objects.all().values_list('nome', flat=True)
    funcionarios = Funcionario.objects.all().order_by('nome_completo')
    
    return render(request, 'core/exportar_afd.html', {'grupos': grupos, 'funcionarios': funcionarios})


# ==========================================
# IMPORTAÇÃO DE PLANILHAS (EXCEL/CSV)
# ==========================================

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
                    
                    if not Funcionario.objects.filter(matricula=matricula_txt).exists():
                        try:
                            Funcionario.objects.create(
                                matricula=matricula_txt,
                                nome_completo=nome_txt,
                                pis=pis_txt,
                                cpf=cpf_txt
                            )
                        except IntegrityError:
                            pass
            
            return redirect('listar_funcionarios')

    return render(request, 'core/importar.html')

@login_required
def importar_planilha(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        grupo_nome = request.POST.get('grupo_ponto')
        conflito_grupo = request.POST.get('conflito_grupo', 'adicionar')
        
        if arquivo:
            try:
                df = pd.read_excel(arquivo, dtype=str)
            except Exception as e:
                print(f"Tentando ler como CSV... Erro anterior: {e}")
                arquivo.seek(0)
                df = pd.read_csv(arquivo, sep=None, engine='python', dtype=str)

            df.columns = df.columns.str.strip()
            linhas = df.to_dict('records')

            def stream_planilha():
                yield """
                <html>
                <head>
                    <style>
                        body { background-color: #ffffff; color: #000000; font-family: 'Cascadia Mono', monospace; padding: 20px; margin: 0; }
                        .log-line { margin: 2px 0; border-bottom: 1px solid #eee; }
                        .success { color: #155724; }
                        .warning { color: #856404; }
                        .error { color: #721c24; }
                        .info { color: #0c5460; }
                        .summary { margin-top: 20px; font-size: 1.2em; border-top: 2px solid #000; padding-top: 10px; }
                        .btn { display: inline-block; padding: 10px 20px; background: #e0e0e0; color: black; text-decoration: none; border-radius: 5px; margin-top: 20px; font-weight: bold; border: 1px solid #ccc;}
                    </style>
                </head>
                <body>
                <h2>Iniciando Processamento da Planilha...</h2>
                <div id="terminal">
                """

                dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
                funcionarios_atualizados = []
                matriculas_desconhecidas = set()

                for linha in linhas:
                    matricula_txt = str(linha.get('ID', '')).strip()
                    hora_completa_txt = str(linha.get('Hora', '')).strip()

                    msg_log = ""
                    status_css = "info"

                    if not matricula_txt or matricula_txt == 'nan' or not hora_completa_txt or hora_completa_txt == 'nan':
                        continue
                        
                    if MatriculaIgnorada.objects.filter(matricula=matricula_txt).exists():
                        yield f"<div class='log-line warning'>[IGNORADO] Matrícula {matricula_txt} está na lista negra.</div>"
                        continue
                        
                    try:
                        dt_obj = datetime.strptime(hora_completa_txt, '%d/%m/%Y %H:%M:%S')
                    except ValueError:
                        try:
                            dt_obj = datetime.strptime(hora_completa_txt, '%d/%m/%Y %H:%M')
                        except ValueError:
                            try:
                                dt_obj = datetime.strptime(hora_completa_txt, '%Y/%m/%d %H:%M:%S')
                            except ValueError:
                                try:
                                    dt_obj = datetime.strptime(hora_completa_txt, '%Y/%m/%d %H:%M')
                                except ValueError:
                                    continue
                            
                    data_batida = dt_obj.date()
                    hora_batida = dt_obj.time()
                    
                    funcionario = Funcionario.objects.filter(matricula=matricula_txt).first()
                    
                    if funcionario:
                        msg_log = f"[SUCESSO] {funcionario.nome_completo} - {data_batida} às {hora_batida}"
                        status_css = "success"

                        if grupo_nome:
                            g_obj, _ = Grupo.objects.get_or_create(nome=grupo_nome)
                            if conflito_grupo == 'substituir':
                                funcionario.grupos.set([g_obj])
                            else:
                                funcionario.grupos.add(g_obj)
                            
                            msg_log += f" (Grupo {grupo_nome} atualizado)"
                            
                        registro, created = RegistroPonto.objects.get_or_create(
                            funcionario=funcionario,
                            data=data_batida,
                            defaults={'dia_semana': dias_semana_pt[data_batida.weekday()]}
                        )

                        if registro.editado_manualmente:
                            msg_log += " (Ignorado - Edição Manual)"
                        else:
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
                                msg_log += " (Dia Cheio ou Duplicada)"
                    else:
                        msg_log = f"[DESCONHECIDO] Matrícula {matricula_txt} não encontrada no banco."
                        status_css = "error"
                        matriculas_desconhecidas.add(matricula_txt)

                    yield f"<div class='log-line {status_css}'>{msg_log}</div>"
                    yield "<script>window.scrollTo(0, document.body.scrollHeight);</script>"

                yield "</div>"

                if matriculas_desconhecidas:
                    yield "<div class='summary error'>⚠️ Foram encontradas Matrículas desconhecidas!</div>"
                    yield "<ul>"
                    for mat in matriculas_desconhecidas:
                        yield f"<li>{mat}</li>"
                    yield "</ul>"
                    yield "<p>Copie os números acima e cadastre-os.</p>"
                else:
                    yield "<div class='summary success'>✅ Importação concluída com sucesso total!</div>"

                yield "</body></html>"

            return StreamingHttpResponse(stream_planilha())

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

@login_required
def cadastro_ignorados(request):
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        valor = request.POST.get('valor', '').strip()
        
        if valor:
            if tipo == 'matricula':
                MatriculaIgnorada.objects.get_or_create(matricula=valor)
            elif tipo == 'pis':
                PisIgnorado.objects.get_or_create(pis=valor)
            elif tipo == 'cpf':
                CpfIgnorado.objects.get_or_create(cpf=valor)
                
        return redirect('cadastro_ignorados')
        
    matriculas = MatriculaIgnorada.objects.all().order_by('-data_adicionado')
    pis = PisIgnorado.objects.all().order_by('-data_adicionado')
    cpfs = CpfIgnorado.objects.all().order_by('-data_adicionado')
    
    return render(request, 'core/cadastro_ignorados.html', {
        'matriculas': matriculas,
        'pis': pis,
        'cpfs': cpfs
    })

@login_required
def gerenciar_grupos(request):
    if request.method == 'POST':
        acao = request.POST.get('acao')
        grupo_id = request.POST.get('grupo_id')
        
        if acao == 'novo':
            nome = request.POST.get('nome', '').strip()
            if nome:
                if Grupo.objects.filter(nome=nome).exists():
                    messages.error(request, f"O grupo '{nome}' já existe.")
                else:
                    Grupo.objects.create(nome=nome)
                    messages.success(request, f"Grupo '{nome}' criado com sucesso.")
            return redirect('gerenciar_grupos')

        grupo = get_object_or_404(Grupo, id=grupo_id)
        
        if acao == 'renomear':
            novo_nome = request.POST.get('novo_nome', '').strip()
            if novo_nome:
                grupo.nome = novo_nome
                grupo.save()
                messages.success(request, f"Grupo renomeado para '{novo_nome}' com sucesso.")
        
        elif acao == 'excluir':
            nome_antigo = grupo.nome
            grupo.delete()
            messages.success(request, f"Grupo '{nome_antigo}' excluído. Todos os funcionários foram desvinculados dele.")
            
        return redirect('gerenciar_grupos')
        
    grupos = Grupo.objects.all().order_by('nome')
    return render(request, 'core/gerenciar_grupos.html', {'grupos': grupos})

@login_required
def remover_ignorado(request, tipo, id):
    if tipo == 'matricula':
        MatriculaIgnorada.objects.filter(id=id).delete()
    elif tipo == 'pis':
        PisIgnorado.objects.filter(id=id).delete()
    elif tipo == 'cpf':
        CpfIgnorado.objects.filter(id=id).delete()
    return redirect('cadastro_ignorados')

@login_required
def verificar_conflitos_grupo(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            return JsonResponse({'conflitos': []})

        ids_identificados = set()
        
        # Se for AFD
        if arquivo.name.endswith('.txt'):
            conteudo = arquivo.read().decode('utf-8', errors='ignore')
            linhas = conteudo.splitlines()
            for linha in linhas:
                linha = linha.strip()
                if linha.startswith('000000000') or len(linha) < 34: continue
                if linha[9] == '3':
                    if linha[14] == '-': identificador = linha[34:45]
                    else: identificador = linha[23:34]
                    ids_identificados.add(identificador)
        # Se for Excel/CSV
        else:
            try:
                df = pd.read_excel(arquivo, dtype=str)
            except:
                arquivo.seek(0)
                df = pd.read_csv(arquivo, sep=None, engine='python', dtype=str)
            
            if 'ID' in df.columns:
                ids_identificados.update(df['ID'].dropna().unique())

        # Verifica quais desses funcionários já têm grupos
        conflitos = []
        funcionarios = Funcionario.objects.filter(
            Q(pis__in=ids_identificados) | Q(cpf__in=ids_identificados) | Q(matricula__in=ids_identificados)
        ).prefetch_related('grupos')

        for f in funcionarios:
            if f.grupos.exists():
                conflitos.append({
                    'id': f.id,
                    'nome': f.nome_completo,
                    'grupos': [g.nome for g in f.grupos.all()]
                })

        return JsonResponse({'conflitos': conflitos})

    return JsonResponse({'status': 'erro'})