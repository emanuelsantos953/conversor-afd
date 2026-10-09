import pandas as pd
import csv
import io
import json
import time 
import unicodedata
import logging
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from .forms import FuncionarioForm
from .models import Funcionario, RegistroPonto, PisIgnorado, MatriculaIgnorada, CpfIgnorado, Grupo, LogRelogio
from django.db import IntegrityError
from django.db.models import Q  
from datetime import datetime, date
import calendar

logger = logging.getLogger(__name__)

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
                try:
                    validate_password(senha, usuario_edit)
                    usuario_edit.set_password(senha)
                except ValidationError as e:
                    for error in e.messages:
                        messages.error(request, f'Erro na senha: {error}')
                    return redirect('gerenciar_usuarios')
            
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
                user = User(username=username)
                try:
                    validate_password(senha, user)
                    user.set_password(senha)
                    user.save()
                    
                    if acesso_conversor:
                        grupo_conv, _ = Group.objects.get_or_create(name='Conversor')
                        user.groups.add(grupo_conv)
                        
                    messages.success(request, f'Usuário {username} criado com sucesso!')
                except ValidationError as e:
                    for error in e.messages:
                        messages.error(request, f'Erro na senha: {error}')
                        
                return redirect('gerenciar_usuarios')

    usuarios = list(User.objects.all().prefetch_related('groups'))

    return render(request, 'core/gerenciar_usuarios.html', {'usuarios': usuarios})

@login_required
def home(request):
    pode_acessar_conversor = request.user.is_superuser or request.user.groups.filter(name='Conversor').exists()

    return render(request, 'core/home.html', {
        'pode_acessar_conversor': pode_acessar_conversor,
    })

@login_required
def ajuda(request):
    return render(request, 'core/ajuda.html')

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


def eh_batida_duplicada(nova_hora, batidas_existentes, tolerancia_segundos=120):
    """
    Retorna True se 'nova_hora' for considerada duplicada de alguma batida já existente
    (mesma hora e minuto, ou diferença de segundos <= tolerancia_segundos).
    """
    if not nova_hora or not batidas_existentes:
        return False
    nova_seg = nova_hora.hour * 3600 + nova_hora.minute * 60 + nova_hora.second
    for b in batidas_existentes:
        b_seg = b.hour * 3600 + b.minute * 60 + b.second
        if abs(nova_seg - b_seg) <= tolerancia_segundos or (nova_hora.hour == b.hour and nova_hora.minute == b.minute):
            return True
    return False

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

                                    if not eh_batida_duplicada(hora_batida, batidas_existentes) and len(batidas_existentes) < 6:
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

def normalizar_texto(texto):
    if not texto: return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('ASCII').lower().strip()

def carregar_dataframe_planilha(arquivo):
    """
    Lê com segurança o arquivo enviado em qualquer formato comum:
    - Excel moderno (.xlsx) com openpyxl
    - Excel antigo (.xls) com xlrd
    - CSV com múltiplos encodings (utf-8-sig, latin-1, cp1252, iso-8859-1, utf-8)
      e delimitadores (automático, ;, ,, \t, |)
    - Tabela HTML salva como .xls / .xlsx
    """
    conteudo = arquivo.read()
    arquivo.seek(0)
    
    if not conteudo:
        raise ValueError("O arquivo enviado está vazio.")
        
    df = None
    erros = []

    # 1. Tentar ler como Excel moderno (.xlsx)
    try:
        df = pd.read_excel(io.BytesIO(conteudo), engine='openpyxl', dtype=str)
    except Exception as e:
        erros.append(f"openpyxl: {e}")

    # 2. Tentar ler como Excel antigo (.xls)
    if df is None:
        try:
            df = pd.read_excel(io.BytesIO(conteudo), engine='xlrd', dtype=str)
        except Exception as e:
            erros.append(f"xlrd: {e}")

    # 3. Tentar como CSV com múltiplos encodings e delimitadores
    if df is None:
        encodings = ['utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-8']
        delimitadores = [None, ';', ',', '\t', '|']
        for enc in encodings:
            for sep in delimitadores:
                try:
                    if sep is None:
                        df_temp = pd.read_csv(
                            io.BytesIO(conteudo),
                            encoding=enc,
                            sep=None,
                            engine='python',
                            dtype=str
                        )
                    else:
                        df_temp = pd.read_csv(
                            io.BytesIO(conteudo),
                            encoding=enc,
                            sep=sep,
                            dtype=str
                        )
                    if df_temp is not None and len(df_temp.columns) > 0:
                        df = df_temp
                        break
                except Exception:
                    pass
            if df is not None:
                break

    # 4. Tentar como HTML se for tabela exportada
    if df is None:
        for enc in ['utf-8', 'latin-1', 'cp1252']:
            try:
                tabelas = pd.read_html(io.BytesIO(conteudo), encoding=enc)
                if tabelas:
                    df = tabelas[0].astype(str)
                    break
            except Exception:
                pass

    if df is None:
        raise ValueError("Não foi possível processar o arquivo. Verifique se o formato é .csv, .xlsx ou .xls válido.")

    # Limpar espaços e remover caracteres ocultos como BOM (\ufeff)
    df.columns = [str(c).replace('\ufeff', '').strip() for c in df.columns]
    return df

def detectar_colunas(df_columns):
    col_id = None
    for col in df_columns:
        norm = normalizar_texto(col)
        if norm in ['id', 'matricula', 'pis', 'cpf', 'codigo', 'cracha', 'cartao', 'usuario']:
            col_id = col
            break
    if not col_id:
        for col in df_columns:
            norm = normalizar_texto(col)
            if any(term in norm for term in ['matricula', 'pis', 'cpf', 'codigo', 'cracha', 'cartao', 'id']):
                col_id = col
                break
    if not col_id and len(df_columns) > 0:
        col_id = df_columns[0]

    col_data_hora = None
    col_data = None
    col_hora = None

    for col in df_columns:
        norm = normalizar_texto(col)
        if norm in ['data/hora', 'data e hora', 'data_hora', 'datahora', 'marcacao', 'horario', 'data/horario', 'datetime']:
            col_data_hora = col
            break

    if not col_data_hora:
        for col in df_columns:
            norm = normalizar_texto(col)
            if norm == 'data':
                col_data = col
            elif norm in ['hora', 'horario']:
                col_hora = col

    if not col_data_hora and not (col_data and col_hora):
        for col in df_columns:
            norm = normalizar_texto(col)
            if 'hora' in norm or 'marcacao' in norm:
                col_data_hora = col
                break

    return col_id, col_data_hora, col_data, col_hora

def parse_data_hora(texto):
    if not texto or str(texto).strip().lower() in ['nan', 'none', '']:
        return None
    texto = str(texto).strip()
    formatos = [
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d-%m-%Y %H:%M:%S',
        '%d-%m-%Y %H:%M',
        '%Y/%m/%d %H:%M:%S',
        '%Y/%m/%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%d/%m/%y %H:%M:%S',
        '%d/%m/%y %H:%M',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
    ]
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            pass
    return None

@login_required
def importar_planilha(request):
    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        grupo_nome = request.POST.get('grupo_ponto')
        conflito_grupo = request.POST.get('conflito_grupo', 'adicionar')
        
        if arquivo:
            try:
                df = carregar_dataframe_planilha(arquivo)
            except Exception as e:
                msg_erro = str(e)
                logger.error(f"Erro ao carregar planilha no importar_planilha: {msg_erro}")
                def stream_erro():
                    yield f"""
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <style>
                            body {{ background-color: #ffffff; color: #721c24; font-family: 'Cascadia Mono', monospace; padding: 20px; }}
                            .error-box {{ background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 6px; padding: 20px; max-width: 650px; margin: 20px auto; }}
                        </style>
                    </head>
                    <body>
                        <div class="error-box">
                            <h3>❌ Erro ao ler a planilha</h3>
                            <p><strong>Detalhes:</strong> {msg_erro}</p>
                            <p>Por favor, certifique-se de que o arquivo é uma planilha (.csv, .xlsx ou .xls) válida e tente novamente.</p>
                        </div>
                    </body>
                    </html>
                    """
                return StreamingHttpResponse(stream_erro())

            col_id, col_data_hora, col_data, col_hora = detectar_colunas(df.columns)
            linhas = df.to_dict('records')

            def stream_planilha():
                yield """
                <html>
                <head>
                    <meta charset="UTF-8">
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
                matriculas_desconhecidas = set()
                total_processados = 0

                for linha in linhas:
                    try:
                        # Extrai identificador
                        matricula_txt = ""
                        if col_id and col_id in linha:
                            matricula_txt = str(linha.get(col_id, '')).strip()
                        elif 'ID' in linha:
                            matricula_txt = str(linha.get('ID', '')).strip()

                        # Extrai data e hora
                        hora_completa_txt = ""
                        if col_data_hora and col_data_hora in linha:
                            hora_completa_txt = str(linha.get(col_data_hora, '')).strip()
                        elif col_data and col_hora and col_data in linha and col_hora in linha:
                            d_val = str(linha.get(col_data, '')).strip()
                            h_val = str(linha.get(col_hora, '')).strip()
                            if d_val and h_val and d_val.lower() != 'nan' and h_val.lower() != 'nan':
                                hora_completa_txt = f"{d_val} {h_val}"
                        elif 'Hora' in linha:
                            hora_completa_txt = str(linha.get('Hora', '')).strip()

                        if not matricula_txt or matricula_txt.lower() == 'nan' or not hora_completa_txt or hora_completa_txt.lower() == 'nan':
                            continue

                        # Se a matrícula for float (ex: 123.0), converte para inteiro
                        if matricula_txt.endswith('.0'):
                            matricula_txt = matricula_txt[:-2]

                        if MatriculaIgnorada.objects.filter(matricula=matricula_txt).exists() or CpfIgnorado.objects.filter(cpf=matricula_txt).exists() or PisIgnorado.objects.filter(pis=matricula_txt).exists():
                            yield f"<div class='log-line warning'>[IGNORADO] ID {matricula_txt} está na lista negra.</div>"
                            continue

                        dt_obj = parse_data_hora(hora_completa_txt)
                        if not dt_obj:
                            yield f"<div class='log-line warning'>[AVISO] ID {matricula_txt}: Data/Hora '{hora_completa_txt}' não reconhecida. Linha ignorada.</div>"
                            continue

                        data_batida = dt_obj.date()
                        hora_batida = dt_obj.time()

                        funcionario = Funcionario.objects.filter(matricula=matricula_txt).first()
                        if not funcionario:
                            funcionario = Funcionario.objects.filter(cpf=matricula_txt).first()
                        if not funcionario:
                            funcionario = Funcionario.objects.filter(pis=matricula_txt).first()

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

                                if not eh_batida_duplicada(hora_batida, batidas_existentes) and len(batidas_existentes) < 6:
                                    batidas_existentes.append(hora_batida)
                                    batidas_existentes.sort()

                                    registro.entrada_1 = batidas_existentes[0] if len(batidas_existentes) > 0 else None
                                    registro.saida_1 = batidas_existentes[1] if len(batidas_existentes) > 1 else None
                                    registro.entrada_2 = batidas_existentes[2] if len(batidas_existentes) > 2 else None
                                    registro.saida_2 = batidas_existentes[3] if len(batidas_existentes) > 3 else None
                                    registro.entrada_3 = batidas_existentes[4] if len(batidas_existentes) > 4 else None
                                    registro.saida_3 = batidas_existentes[5] if len(batidas_existentes) > 5 else None
                                    registro.save()
                                    total_processados += 1
                                else:
                                    msg_log += " (Dia Cheio ou Duplicada)"
                        else:
                            msg_log = f"[DESCONHECIDO] ID/CPF {matricula_txt} não encontrado no banco."
                            status_css = "error"
                            matriculas_desconhecidas.add(matricula_txt)

                        yield f"<div class='log-line {status_css}'>{msg_log}</div>"
                        yield "<script>window.scrollTo(0, document.body.scrollHeight);</script>"

                    except Exception as err_linha:
                        yield f"<div class='log-line error'>[ERRO NA LINHA] {str(err_linha)}</div>"

                yield "</div>"

                if matriculas_desconhecidas:
                    yield "<div class='summary error'>⚠️ Foram encontrados IDs/CPFs desconhecidos!</div>"
                    yield "<ul>"
                    for mat in matriculas_desconhecidas:
                        yield f"<li>{mat}</li>"
                    yield "</ul>"
                    yield "<p>Copie os números acima e cadastre-os.</p>"
                else:
                    yield f"<div class='summary success'>✅ Importação concluída com sucesso! ({total_processados} batidas registradas/atualizadas)</div>"

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
                df = carregar_dataframe_planilha(arquivo)
                col_id, _, _, _ = detectar_colunas(df.columns)
                if col_id and col_id in df.columns:
                    for val in df[col_id].dropna().unique():
                        v_str = str(val).strip()
                        if v_str.endswith('.0'):
                            v_str = v_str[:-2]
                        if v_str and v_str.lower() != 'nan':
                            ids_identificados.add(v_str)
            except Exception as e:
                logger.error(f"Erro em verificar_conflitos_grupo ao ler arquivo: {e}")
                return JsonResponse({'conflitos': [], 'aviso': str(e)})

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

@login_required
def monitor_relogio(request):
    if request.GET.get('format') == 'json':
        logs = LogRelogio.objects.all()[:100]
        dados = [{
            'tipo': log.tipo,
            'tipo_display': log.get_tipo_display(),
            'numero_serie': log.numero_serie,
            'mensagem': log.mensagem,
            'data_hora': log.data_hora.strftime('%d/%m/%Y %H:%M:%S'),
        } for log in logs]
        return JsonResponse({'logs': dados})

    logs = LogRelogio.objects.all()[:100]
    return render(request, 'core/monitor_relogio.html', {'logs': logs})

@login_required
def limpar_logs_relogio(request):
    if request.method == 'POST':
        LogRelogio.objects.all().delete()
    return redirect('monitor_relogio')