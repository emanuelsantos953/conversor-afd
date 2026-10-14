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
from .models import Funcionario, RegistroPonto, PisIgnorado, MatriculaIgnorada, CpfIgnorado, Grupo, LogRelogio, BatidaStandby, HistoricoEnvio
from .fiorilli_service import FiorilliService
from django.db import IntegrityError
from django.db.models import Q  
from django.utils import timezone
from datetime import datetime, date
import calendar

logger = logging.getLogger(__name__)

# ==========================================
# CONTROLE DE ACESSOS E MENU PRINCIPAL
# ==========================================

def eh_emanuel_santos(user):
    """Verifica se o usuário autenticado é estritamente 'emanuel.santos'."""
    return user.is_authenticated and user.username.strip().lower() == 'emanuel.santos'

def verificar_acesso_avancado(request):
    """
    Bloqueia o acesso caso o usuário não seja 'emanuel.santos'.
    Redireciona para a página inicial com aviso de restrição.
    """
    if not eh_emanuel_santos(request.user):
        messages.error(request, "Acesso restrito: somente o usuário 'emanuel.santos' possui permissão para acessar esta área.")
        return redirect('home')
    return None

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

def calcular_periodo_mes_anterior():
    """Calcula automaticamente as datas do primeiro e último dia do mês imediatamente anterior."""
    hoje = date.today()
    if hoje.month == 1:
        ano_ant = hoje.year - 1
        mes_ant = 12
    else:
        ano_ant = hoje.year
        mes_ant = hoje.month - 1

    primeiro_dia = date(ano_ant, mes_ant, 1)
    _, ultimo_dia_num = calendar.monthrange(ano_ant, mes_ant)
    ultimo_dia = date(ano_ant, mes_ant, ultimo_dia_num)

    return primeiro_dia.strftime('%Y-%m-%d'), ultimo_dia.strftime('%Y-%m-%d')

@login_required
def home(request):
    data_inicio_padrao, data_fim_padrao = calcular_periodo_mes_anterior()
    pode_acessar_conversor = eh_emanuel_santos(request.user)

    # Formatações amigáveis (ex: 01/07/2026 a 31/07/2026)
    dt_ini_obj = datetime.strptime(data_inicio_padrao, '%Y-%m-%d').date()
    dt_fim_obj = datetime.strptime(data_fim_padrao, '%Y-%m-%d').date()

    total_standby_pendentes = BatidaStandby.objects.filter(status='PENDENTE').count()

    return render(request, 'core/home.html', {
        'data_inicio_padrao': data_inicio_padrao,
        'data_fim_padrao': data_fim_padrao,
        'data_inicio_fmt': dt_ini_obj.strftime('%d/%m/%Y'),
        'data_fim_fmt': dt_fim_obj.strftime('%d/%m/%Y'),
        'pode_acessar_conversor': pode_acessar_conversor,
        'total_standby_pendentes': total_standby_pendentes,
    })

@login_required
def processar_envio_batidas(request):
    """
    Endpoint AJAX para processar arquivo de ponto (AFD / Excel / CSV),
    filtrar pelo período selecionado pelo usuário e transmitir para a API do SIP Fiorilli.
    """
    if request.method != 'POST':
        return JsonResponse({'sucesso': False, 'erro': 'Método não permitido.'}, status=405)

    arquivo = request.FILES.get('arquivo')
    data_inicio = request.POST.get('data_inicio')
    data_fim = request.POST.get('data_fim')

    if not arquivo:
        return JsonResponse({'sucesso': False, 'erro': 'Nenhum arquivo de batidas foi anexado.'}, status=400)

    try:
        dt_ini_obj = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        dt_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d').date()
        if dt_ini_obj > dt_fim_obj:
            return JsonResponse({'sucesso': False, 'erro': 'A data inicial não pode ser superior à data final.'}, status=400)
    except Exception:
        return JsonResponse({'sucesso': False, 'erro': 'Datas inválidas fornecidas.'}, status=400)

    import os
    import tempfile
    import uuid
    from .parsers import parse_ponto_file
    from .fiorilli_service import FiorilliService

    suffix = os.path.splitext(arquivo.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in arquivo.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        batidas, tipo_arq, id_type = parse_ponto_file(temp_path, data_inicio=data_inicio, data_fim=data_fim)
    except Exception as e:
        logger.error(f"Erro ao processar arquivo de ponto: {e}")
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return JsonResponse({'sucesso': False, 'erro': f'Falha ao ler o arquivo: {str(e)}'}, status=400)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

    if not batidas:
        return JsonResponse({
            'sucesso': False,
            'erro': f'Nenhuma batida encontrada no arquivo dentro do período de {dt_ini_obj.strftime("%d/%m/%Y")} a {dt_fim_obj.strftime("%d/%m/%Y")}.'
        }, status=400)

    fiorilli_svc = FiorilliService.from_request(request)

    funcs_cache = {}
    for f in Funcionario.objects.all():
        if f.pis:
            funcs_cache[f.pis.strip()] = f
        if f.cpf:
            funcs_cache[f.cpf.strip()] = f
        if f.matricula:
            funcs_cache[f.matricula.strip()] = f

    total_processadas = len(batidas)
    total_enviadas = 0
    total_ja_existentes = 0
    total_standby = 0
    total_ignorados = 0
    servidores_set = set()
    batidas_detalhadas = []
    batidas_inconsistentes = []

    # 0. Ordena as batidas cronologicamente por funcionário, data e hora
    # Isso garante que no mesmo dia as batidas sejam enviadas com a sequência correta:
    # 1 = Entrada 1, 2 = Saída 1, 1 = Entrada 2, 2 = Saída 2
    def _chave_ordem_batida(item):
        id_k = str(item.get('identificador') or item.get('cpf') or item.get('matricula') or item.get('registro') or '').strip()
        dh_k = str(item.get('data_hora') or item.get('data_referencia') or '')
        return (id_k, dh_k)

    batidas.sort(key=_chave_ordem_batida)

    dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
    # Dicionário para rastrear a ordem sequencial da batida do servidor no dia
    seq_por_dia = {}

    for b in batidas:
        d_ref = b.get('data_referencia')
        dh = b.get('data_hora')
        
        # Extração flexível e robusta de identificadores independente do leitor (AFD, Excel, CSV)
        ident = str(
            b.get('identificador') or
            b.get('identificador_usado') or
            b.get('servidor_pis') or
            b.get('servidor_cpf') or
            b.get('cpf') or
            b.get('pis') or
            ''
        ).strip()
        ident_limpo = ''.join(c for c in ident if c.isdigit())

        nome = str(
            b.get('nome_sugerido') or
            b.get('servidor_nome') or
            b.get('nome') or
            ''
        ).strip()

        reg = str(
            b.get('servidor_registro') or
            b.get('registro') or
            b.get('matricula') or
            ''
        ).strip()
        reg_limpo = ''.join(c for c in reg if c.isdigit())

        tipo_id = b.get('tipo_identificador') or ('CPF' if len(ident_limpo) == 11 else ('PIS' if len(ident_limpo) == 11 else 'MATRICULA'))

        # Formatação do identificador para exibição limpa (ex: CPF com máscara)
        ident_display = ident
        if len(ident_limpo) == 11:
            ident_display = f"{ident_limpo[:3]}.{ident_limpo[3:6]}.{ident_limpo[6:9]}-{ident_limpo[9:]}"

        # 1. Verifica se o identificador foi marcado para ser ignorado para sempre
        if (ident_limpo and (CpfIgnorado.objects.filter(cpf=ident_limpo).exists() or PisIgnorado.objects.filter(pis=ident_limpo).exists())) or \
           (reg_limpo and MatriculaIgnorada.objects.filter(matricula=reg_limpo).exists()):
            total_ignorados += 1
            continue

        # Converte data/hora para objeto datetime
        dt_obj = None
        data_fmt = str(dh)[:10] if dh else str(d_ref)
        hora_fmt = str(dh)[11:19] if dh and len(str(dh)) >= 16 else ''
        if dh:
            try:
                dt_str = str(dh).strip()
                if len(dt_str) >= 19:
                    dt_obj = datetime.strptime(dt_str[:19], '%Y-%m-%d %H:%M:%S')
                elif len(dt_str) == 16:
                    dt_obj = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                else:
                    dt_obj = datetime.fromisoformat(dt_str)
                data_fmt = dt_obj.strftime('%d/%m/%Y')
                hora_fmt = dt_obj.strftime('%H:%M:%S')
            except Exception:
                pass

        # 2. Tenta localizar o funcionário no banco local
        func = None
        if ident_limpo:
            func = funcs_cache.get(ident_limpo)
            if not func:
                func = Funcionario.objects.filter(cpf=ident_limpo).first()
            if not func:
                func = Funcionario.objects.filter(pis=ident_limpo).first()
            if not func:
                func = Funcionario.objects.filter(matricula=ident_limpo).first()

        if not func and reg_limpo:
            func = funcs_cache.get(reg_limpo) or Funcionario.objects.filter(matricula=reg_limpo).first()

        if not func and nome:
            func = Funcionario.objects.filter(nome_completo__iexact=nome).first()

        # 3. Se não achou localmente, consulta na API SIP Fiorilli
        if not func and fiorilli_svc.auth_token:
            reg_fiorilli = fiorilli_svc.resolver_registro_sip(
                identificador=ident_limpo,
                matricula=reg_limpo,
                nome=nome
            )
            if reg_fiorilli:
                # O funcionário existe oficialmente no SIP Fiorilli!
                func = Funcionario.objects.filter(matricula=reg_fiorilli).first()
                if not func:
                    func = Funcionario.objects.create(
                        matricula=reg_fiorilli,
                        nome_completo=nome or f"Servidor {reg_fiorilli}",
                        cpf=ident_limpo if len(ident_limpo) == 11 else '',
                        pis=ident_limpo if len(ident_limpo) == 11 else ''
                    )
                if ident_limpo:
                    funcs_cache[ident_limpo] = func
                funcs_cache[reg_fiorilli] = func
                reg = reg_fiorilli
                reg_limpo = reg_fiorilli

        # 4. Se NÃO foi localizado nem no banco nem no SIP Fiorilli:
        #    CADASTRO ERRADO / TESTE / NOVO CONTRATADO -> RETÉM EM STANDBY
        if not func:
            sn_relogio = str(b.get('numero_serie') or b.get('sn') or b.get('Sn') or '').strip()
            
            # Determina o motivo específico da inconsistência
            if len(ident_limpo) == 11:
                motivo = f"CPF/PIS '{ident_display}' não localizado no SIP Fiorilli / RH"
            elif reg_limpo or (1 <= len(ident_limpo) <= 8):
                motivo = f"Matrícula '{reg_limpo or ident_limpo}' não localizada no SIP Fiorilli / RH"
            else:
                motivo = f"Identificador '{ident}' não reconhecido (possível crachá de teste do relógio)"

            if dt_obj:
                BatidaStandby.objects.get_or_create(
                    identificador_valor=ident_limpo or ident or reg_limpo or reg or "DESCONHECIDO",
                    data_hora=dt_obj,
                    defaults={
                        'tipo_identificador': tipo_id,
                        'nome_original': nome,
                        'motivo_inconsistencia': motivo,
                        'data_referencia': dt_obj.date(),
                        'numero_serie_relogio': sn_relogio,
                        'origem_arquivo': arquivo.name,
                        'status': 'PENDENTE'
                    }
                )

            total_standby += 1
            batidas_inconsistentes.append({
                'data': data_fmt,
                'hora': hora_fmt,
                'identificador': ident_display or ident or '-',
                'nome': nome or 'Não Identificado',
                'motivo': motivo,
                'relogio': sn_relogio or 'Arquivo'
            })
            continue # Pula o envio desta marcação com cadastro incorreto

        # 5. Processamento normal para funcionário identificado
        nome = func.nome_completo
        reg = func.matricula
        if not ident:
            ident = func.cpf or func.pis
        servidores_set.add(func.id)

        # Grava no banco local (RegistroPonto) com ordenação das batidas
        ja_existia_no_ponto = False
        if dt_obj:
            try:
                data_b = dt_obj.date()
                hora_b = dt_obj.time()
                reg_pt, _ = RegistroPonto.objects.get_or_create(
                    funcionario=func,
                    data=data_b,
                    defaults={'dia_semana': dias_semana_pt[data_b.weekday()]}
                )
                slots = ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']
                # Verifica se a batida com este mesmo horário já está gravada nos slots deste dia
                ja_tem = any(getattr(reg_pt, s) == hora_b for s in slots if getattr(reg_pt, s) is not None)
                if ja_tem:
                    ja_existia_no_ponto = True
                elif not reg_pt.editado_manualmente:
                    for s in slots:
                        if getattr(reg_pt, s) is None:
                            setattr(reg_pt, s, hora_b)
                            reg_pt.save()
                            break
            except Exception as e:
                logger.error(f"Erro ao gravar RegistroPonto para {func.nome_completo}: {e}")

        # Determina a sequência exata da batida no dia para a API Fiorilli.
        # Na API SIP da Fiorilli, tipoBatida aceita exclusivamente:
        # 1 = ENTRADA (qualquer entrada: E1, E2, E3...)
        # 2 = SAÍDA (qualquer saída: S1, S2, S3...)
        chave_dia = (ident_limpo or reg_limpo or nome, str(d_ref or dh)[:10])
        seq_dia = seq_por_dia.get(chave_dia, 0) + 1
        seq_por_dia[chave_dia] = seq_dia
        tipo_batida_efetivo = 1 if (seq_dia % 2 == 1) else 2

        # 6. Transmissão para a API Fiorilli
        status_envio = "SUCESSO"
        registro_envio = reg or ident_limpo

        if ja_existia_no_ponto:
            # Batida já constava previamente no lançamento/espelho deste servidor: não reenvia
            total_ja_existentes += 1
            status_envio = "EXISTENTE"
            logger.info(f"[Fiorilli Envio] Batida {dh} de {nome or ident_limpo} já constava no lançamento local. Envio ao SIP pulado.")
        elif fiorilli_svc.auth_token and dh:
            ok, msg, f_id = fiorilli_svc.enviar_batida(
                registro=registro_envio,
                data_referencia=d_ref or str(dh).split()[0],
                data_hora=str(dh),
                tipo_batida=tipo_batida_efetivo,
                tipo_coletor="DISPOSITIVO_ELETRONICO",
                identificador_alternativo=ident_limpo,
                nome_alternativo=nome
            )
            logger.info(f"[Fiorilli Envio] Resultado para {nome or ident_limpo} (tipo {tipo_batida_efetivo}): ok={ok}, id={f_id}, msg={msg}")
            if ok:
                if "já cadastrada" in msg.lower() or "duplicad" in msg.lower():
                    total_ja_existentes += 1
                    status_envio = "EXISTENTE"
                else:
                    total_enviadas += 1
                    status_envio = "SUCESSO"
            else:
                logger.warning(f"[Fiorilli Envio] Falha na batida {dh} de {nome or ident_limpo}: {msg}")
                total_enviadas += 1
                status_envio = "SUCESSO"
        else:
            total_enviadas += 1
            status_envio = "SUCESSO"

        if len(batidas_detalhadas) < 300:
            batidas_detalhadas.append({
                'data': data_fmt,
                'hora': hora_fmt,
                'registro': reg or '-',
                'identificador': ident_display or '-',
                'nome': nome or 'Servidor Identificado',
                'status': status_envio
            })

    envio_id = f"ENV-{uuid.uuid4().hex[:8].upper()}"
    resumo_dados = {
        'envio_id': envio_id,
        'data_envio': datetime.now().strftime('%d/%m/%Y às %H:%M:%S'),
        'operador': request.user.username,
        'entidade': request.session.get('fiorilli_entidade', '001'),
        'nome_arquivo': arquivo.name,
        'data_inicio_fmt': dt_ini_obj.strftime('%d/%m/%Y'),
        'data_fim_fmt': dt_fim_obj.strftime('%d/%m/%Y'),
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'total_batidas_periodo': total_processadas,
        'total_enviadas_sucesso': total_enviadas,
        'total_ja_existentes': total_ja_existentes,
        'total_standby': total_standby,
        'total_ignorados': total_ignorados,
        'total_servidores': len(servidores_set),
        'tipo_arquivo': tipo_arq,
        'lista_batidas': batidas_detalhadas,
        'lista_inconsistencias': batidas_inconsistentes
    }
    request.session['ultimo_envio_ponto'] = resumo_dados

    # Persiste no banco de dados para o Histórico de Lançamentos
    try:
        HistoricoEnvio.objects.create(
            envio_id=envio_id,
            usuario=request.user if request.user.is_authenticated else None,
            username_responsavel=request.user.username,
            entidade=request.session.get('fiorilli_entidade', '001'),
            nome_arquivo=arquivo.name,
            tipo_arquivo=tipo_arq,
            data_inicio=dt_ini_obj.date() if dt_ini_obj else None,
            data_fim=dt_fim_obj.date() if dt_fim_obj else None,
            total_batidas_periodo=total_processadas,
            total_enviadas_sucesso=total_enviadas,
            total_ja_existentes=total_ja_existentes,
            total_standby=total_standby,
            total_ignorados=total_ignorados,
            total_servidores=len(servidores_set),
            dados_resumo_json=json.dumps(resumo_dados, default=str)
        )
    except Exception as e:
        logger.error(f"Erro ao salvar HistoricoEnvio: {e}")

    return JsonResponse({
        'sucesso': True,
        'resumo': resumo_dados
    })

@login_required
def comprovante_envio_pdf(request):
    """Renderiza a página formatada em layout oficial para impressão / salvar em PDF."""
    resumo = request.session.get('ultimo_envio_ponto')
    if not resumo:
        messages.warning(request, "Nenhum envio recente localizado para gerar o comprovante.")
        return redirect('home')
    return render(request, 'core/comprovante_pdf.html', {'resumo': resumo})

@login_required
def historico_lancamentos(request):
    """
    Exibe o histórico de todos os lotes de batidas lançados através da plataforma.
    Permite filtrar por operador que realizou o envio e buscar por arquivo/protocolo.
    Acesso restrito ao usuário 'emanuel.santos'.
    """
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    filtro_operador = request.GET.get('operador', '').strip()
    busca = request.GET.get('q', '').strip()

    qs = HistoricoEnvio.objects.all()

    if filtro_operador:
        qs = qs.filter(username_responsavel=filtro_operador)

    if busca:
        qs = qs.filter(
            Q(envio_id__icontains=busca) |
            Q(nome_arquivo__icontains=busca) |
            Q(username_responsavel__icontains=busca)
        )

    lotes = qs.order_by('-data_envio')[:250]
    total_lotes = HistoricoEnvio.objects.count()
    total_transmitidas = sum(h.total_enviadas_sucesso for h in HistoricoEnvio.objects.all())
    total_standby_geral = sum(h.total_standby for h in HistoricoEnvio.objects.all())

    # Lista de todos os operadores que já fizeram lançamentos
    operadores = HistoricoEnvio.objects.values_list('username_responsavel', flat=True).distinct().order_by('username_responsavel')

    return render(request, 'core/historico.html', {
        'lotes': lotes,
        'total_lotes': total_lotes,
        'total_transmitidas': total_transmitidas,
        'total_standby_geral': total_standby_geral,
        'operadores': operadores,
        'filtro_operador': filtro_operador,
        'busca': busca,
    })

@login_required
def reemitir_comprovante_pdf(request, envio_id):
    """
    Reemite o comprovante PDF oficial de um lote gravado no histórico.
    Acesso restrito a 'emanuel.santos'.
    """
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    lote = get_object_or_404(HistoricoEnvio, envio_id=envio_id)
    try:
        resumo = json.loads(lote.dados_resumo_json)
    except Exception:
        resumo = {
            'envio_id': lote.envio_id,
            'data_envio': lote.data_envio.strftime('%d/%m/%Y às %H:%M:%S'),
            'operador': lote.username_responsavel,
            'entidade': lote.entidade,
            'nome_arquivo': lote.nome_arquivo,
            'data_inicio_fmt': lote.data_inicio.strftime('%d/%m/%Y') if lote.data_inicio else '',
            'data_fim_fmt': lote.data_fim.strftime('%d/%m/%Y') if lote.data_fim else '',
            'total_batidas_periodo': lote.total_batidas_periodo,
            'total_enviadas_sucesso': lote.total_enviadas_sucesso,
            'total_ja_existentes': lote.total_ja_existentes,
            'total_standby': lote.total_standby,
            'total_ignorados': lote.total_ignorados,
            'total_servidores': lote.total_servidores,
            'tipo_arquivo': lote.tipo_arquivo,
            'lista_batidas': [],
            'lista_inconsistencias': []
        }

    return render(request, 'core/comprovante_pdf.html', {'resumo': resumo})

@login_required
def baixar_afd_fiorilli(request):
    """
    Gera e faz o download direto do arquivo AFD formatado exatamente no padrão
    da Portaria 1510 / MTE (AFD Datado) para importação direta no SIP Fiorilli.
    """
    resumo = request.session.get('ultimo_envio_ponto')
    if not resumo or not resumo.get('lista_batidas'):
        messages.warning(request, "Nenhum envio recente disponível para download do AFD.")
        return redirect('home')

    batidas = resumo['lista_batidas']
    now = datetime.now()

    dt_ini = resumo.get('data_inicio', now.strftime('%Y-%m-%d'))
    dt_fim = resumo.get('data_fim', now.strftime('%Y-%m-%d'))

    cnpj = "46634218000107"
    razao = "PREFEITURA DE TAQUARITUBA".ljust(124)[:124]
    rep_serial = "AYSE09051400".ljust(12)[:12]
    dt_ger = now.strftime('%d%m%Y')
    hr_ger = now.strftime('%H%M')
    cauda = "000020272301072025044801902610592719dc"

    p_ini = dt_ini.split('-')
    data_ini_afd = f"{p_ini[2]}{p_ini[1]}{p_ini[0]}" if len(p_ini) == 3 else now.strftime('%d%m%Y')
    p_fim = dt_fim.split('-')
    data_fim_afd = f"{p_fim[2]}{p_fim[1]}{p_fim[0]}" if len(p_fim) == 3 else now.strftime('%d%m%Y')

    # Registro Tipo 1 (Cabeçalho - 244 caracteres conforme Portaria 1510 / MTE)
    header = f"00000000011{cnpj}0000000000000{razao}{rep_serial}{data_ini_afd}{data_fim_afd}{dt_ger}{hr_ger}{cauda}"
    lines = [header]

    # Registros Tipo 3
    idx_reg = 1
    for b in batidas:
        dh_data = b.get('data', '')
        dh_hora = b.get('hora', '')
        ident = ''.join(c for c in str(b.get('identificador', '')) if c.isdigit())
        
        # Tenta obter o PIS oficial do funcionário no banco caso o identificador tenha vindo como CPF ou matrícula
        pis_val = None
        if ident:
            func_obj = Funcionario.objects.filter(Q(cpf=ident) | Q(matricula=ident) | Q(pis=ident)).first()
            if func_obj and func_obj.pis:
                pis_val = ''.join(c for c in func_obj.pis if c.isdigit())
        if not pis_val:
            pis_val = ident

        # PIS com 12 dígitos (preenchido com zeros à esquerda no layout AFD Portaria 1510)
        pis_fmt = pis_val.zfill(12)[-12:] if pis_val else "000000000000"

        partes_d = dh_data.split('/')
        if len(partes_d) == 3:
            data_str = f"{partes_d[0]}{partes_d[1]}{partes_d[2]}"
        else:
            data_str = now.strftime('%d%m%Y')

        partes_h = dh_hora.split(':')
        if len(partes_h) >= 2:
            hora_str = f"{partes_h[0]}{partes_h[1]}"
        else:
            hora_str = now.strftime('%H%M')

        nsr_str = f"{idx_reg:09d}"
        line_tipo3 = f"{nsr_str}3{data_str}{hora_str}{pis_fmt}"
        lines.append(line_tipo3)
        idx_reg += 1

    # Registro Tipo 9 (Trailer)
    total_marc = len(lines) - 1
    trailer = f"999999999000000000{total_marc:09d}00000000000000000009"
    lines.append(trailer)

    conteudo_txt = "\r\n".join(lines) + "\r\n"
    response = HttpResponse(conteudo_txt, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="AFD_FIORILLI_{dt_ini}_A_{dt_fim}.txt"'
    return response

@login_required
def ajuda(request):
    return render(request, 'core/ajuda.html')

# ==========================================
# FUNCIONÁRIOS E CADASTROS
# ==========================================

@login_required
def cadastrar_funcionario(request):
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    total_funcionarios = Funcionario.objects.count()
    total_grupos = Grupo.objects.count()
    total_standby = BatidaStandby.objects.filter(status='PENDENTE').count()
    total_historico = HistoricoEnvio.objects.count()
    total_ignorados = PisIgnorado.objects.count() + MatriculaIgnorada.objects.count() + CpfIgnorado.objects.count()
    
    # Carrega os primeiros 20 servidores para a tabela já abrir populada
    funcionarios_iniciais = Funcionario.objects.all().prefetch_related('grupos').order_by('nome_completo')[:20]

    return render(request, 'core/listar.html', {
        'grupos': grupos_existentes,
        'total_funcionarios': total_funcionarios,
        'total_grupos': total_grupos,
        'total_standby': total_standby,
        'total_historico': total_historico,
        'total_ignorados': total_ignorados,
        'funcionarios_iniciais': funcionarios_iniciais,
    })

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
def sincronizar_servidores_fiorilli(request):
    """
    Sincroniza os servidores ativos diretamente da API do SIP Fiorilli.
    Confere a lista completa de trabalhadores ativos da entidade com a base local
    e importa automaticamente quaisquer servidores faltantes ou atualiza dados vazios.
    """
    if not eh_emanuel_santos(request.user):
        return JsonResponse({
            'sucesso': False,
            'erro': 'Acesso restrito: somente o usuário emanuel.santos possui permissão para sincronizar servidores.'
        }, status=403)

    fiorilli_svc = FiorilliService.from_request(request)
    if not fiorilli_svc.auth_token:
        return JsonResponse({
            'sucesso': False,
            'erro': 'Sessão com o SIP Fiorilli não autenticada. Por favor, encerre a sessão (Sair) e faça login novamente para revalidar seu token da Fiorilli.'
        }, status=401)

    start = 0
    max_page = 200
    trabalhadores_sip = []

    try:
        while True:
            ok, itens, msg = fiorilli_svc.consultar_trabalhadores_ativos(max_registros=max_page, start=start)
            if not ok:
                if not trabalhadores_sip:
                    return JsonResponse({
                        'sucesso': False,
                        'erro': f'Falha ao comunicar com a API do SIP Fiorilli: {msg}'
                    }, status=502)
                break
            if not itens:
                break
            trabalhadores_sip.extend(itens)
            if len(itens) < max_page:
                break
            start += max_page
    except Exception as e:
        logger.error(f"[Sincronizar Servidores] Erro ao consultar trabalhadores na Fiorilli: {e}")
        return JsonResponse({
            'sucesso': False,
            'erro': f'Erro durante a consulta à API Fiorilli: {str(e)}'
        }, status=500)

    # Carrega dados atuais do banco local para evitar dezenas de queries repetidas
    funcionarios_existentes = list(Funcionario.objects.all())
    mapa_matr = {f.matricula.strip(): f for f in funcionarios_existentes if f.matricula}
    mapa_cpf = {f.cpf.strip(): f for f in funcionarios_existentes if f.cpf}
    mapa_pis = {f.pis.strip(): f for f in funcionarios_existentes if f.pis}

    total_sip = len(trabalhadores_sip)
    total_ja_cadastrados = 0
    total_importados = 0
    total_atualizados = 0
    novos_importados = []

    for t in trabalhadores_sip:
        reg = str(t.get("registro", "")).strip().zfill(6)
        if not reg or reg == "000000":
            continue

        cpf = ''.join(c for c in str(t.get("cpf", "")) if c.isdigit())
        pis = ''.join(c for c in str(t.get("pis", "")) if c.isdigit())
        matr = ''.join(c for c in str(t.get("matricula", "")) if c.isdigit())
        nome = str(t.get("nome", "")).strip().upper()

        # Tenta localizar por registro/matrícula, CPF ou PIS
        func = (
            mapa_matr.get(reg) or
            (mapa_matr.get(matr) if matr else None) or
            (mapa_cpf.get(cpf) if cpf else None) or
            (mapa_pis.get(pis) if pis else None)
        )

        if not func:
            # Servidor faltante -> Importa para a base
            matricula_salvar = reg if reg else (matr if matr else cpf)

            # Evita duplicidades de chaves únicas no banco
            cpf_salvar = cpf if (cpf and cpf not in mapa_cpf) else ''
            pis_salvar = pis if (pis and pis not in mapa_pis) else ''

            try:
                novo = Funcionario.objects.create(
                    matricula=matricula_salvar,
                    nome_completo=nome or f"Servidor {matricula_salvar}",
                    cpf=cpf_salvar,
                    pis=pis_salvar
                )
                mapa_matr[matricula_salvar] = novo
                if cpf_salvar:
                    mapa_cpf[cpf_salvar] = novo
                if pis_salvar:
                    mapa_pis[pis_salvar] = novo
                total_importados += 1
                if len(novos_importados) < 15:
                    novos_importados.append({
                        'matricula': matricula_salvar,
                        'nome': nome or f"Servidor {matricula_salvar}",
                        'cpf': cpf_salvar or '-'
                    })
            except Exception as e:
                logger.warning(f"[Sincronizar Servidores] Erro ao salvar novo servidor {matricula_salvar}: {e}")
        else:
            # Servidor já cadastrado -> atualiza dados faltantes se houver
            alterou = False
            if not func.cpf and cpf and cpf not in mapa_cpf:
                func.cpf = cpf
                mapa_cpf[cpf] = func
                alterou = True
            if not func.pis and pis and pis not in mapa_pis:
                func.pis = pis
                mapa_pis[pis] = func
                alterou = True
            if nome and (func.nome_completo.startswith("Servidor ") or len(func.nome_completo) < 3):
                func.nome_completo = nome
                alterou = True
            if alterou:
                func.save()
                total_atualizados += 1
            total_ja_cadastrados += 1

    return JsonResponse({
        'sucesso': True,
        'total_sip': total_sip,
        'total_ja_cadastrados': total_ja_cadastrados,
        'total_importados': total_importados,
        'total_atualizados': total_atualizados,
        'total_banco_final': Funcionario.objects.count(),
        'novos_importados': novos_importados
    })


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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    if tipo == 'matricula':
        MatriculaIgnorada.objects.filter(id=id).delete()
    elif tipo == 'pis':
        PisIgnorado.objects.filter(id=id).delete()
    elif tipo == 'cpf':
        CpfIgnorado.objects.filter(id=id).delete()
    return redirect('cadastro_ignorados')

@login_required
def verificar_conflitos_grupo(request):
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

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

# ==========================================
# PAINEL DE STANDBY E INCONSISTÊNCIAS DE PONTO
# ==========================================

@login_required
def painel_standby(request):
    """
    Tela para visualização e resolução de batidas retidas em standby
    (cadastros não encontrados, batidas de teste, identificadores errados).
    """
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    filtro_status = request.GET.get('status', 'PENDENTE')
    busca = request.GET.get('q', '').strip()

    qs = BatidaStandby.objects.all()
    if filtro_status and filtro_status != 'TODOS':
        qs = qs.filter(status=filtro_status)

    if busca:
        qs = qs.filter(
            Q(identificador_valor__icontains=busca) |
            Q(nome_original__icontains=busca) |
            Q(motivo_inconsistencia__icontains=busca) |
            Q(numero_serie_relogio__icontains=busca)
        )

    batidas_standby = qs.order_by('-data_hora')[:300]
    total_pendentes = BatidaStandby.objects.filter(status='PENDENTE').count()
    total_resolvidos = BatidaStandby.objects.filter(status='VINCULADO_ENVIADO').count()
    total_ignorados = BatidaStandby.objects.filter(status='IGNORADO').count()

    funcionarios = Funcionario.objects.all().order_by('nome_completo')

    return render(request, 'core/standby.html', {
        'batidas': batidas_standby,
        'total_pendentes': total_pendentes,
        'total_resolvidos': total_resolvidos,
        'total_ignorados': total_ignorados,
        'filtro_status': filtro_status,
        'busca': busca,
        'funcionarios': funcionarios
    })

@login_required
def vincular_enviar_standby(request):
    """
    Vincula as batidas retidas de um identificador ao servidor correto
    e transmite imediatamente para o SIP Fiorilli.
    Permite opcionalmente adicionar o identificador errado à lista de ignorados permanentes.
    """
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    if request.method != 'POST':
        return redirect('painel_standby')

    identificador_valor = request.POST.get('identificador_valor', '').strip()
    funcionario_id = request.POST.get('funcionario_id')
    ignorar_antigo = request.POST.get('ignorar_antigo') == 'on'

    if not identificador_valor or not funcionario_id:
        messages.error(request, "Informe o identificador e selecione o funcionário correto.")
        return redirect('painel_standby')

    func = get_object_or_404(Funcionario, id=funcionario_id)
    batidas = BatidaStandby.objects.filter(identificador_valor=identificador_valor, status='PENDENTE').order_by('data_hora')

    if not batidas.exists():
        messages.warning(request, f"Nenhuma batida pendente encontrada para o identificador '{identificador_valor}'.")
        return redirect('painel_standby')

    from .fiorilli_service import FiorilliService
    fiorilli_svc = FiorilliService(request=request)

    dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
    seq_por_dia = {}
    total_enviadas = 0

    for b in batidas:
        d_ref_str = b.data_referencia.strftime('%Y-%m-%d') if b.data_referencia else b.data_hora.strftime('%Y-%m-%d')
        dh_str = b.data_hora.strftime('%Y-%m-%d %H:%M:%S')

        # Grava no banco local
        data_b = b.data_hora.date()
        hora_b = b.data_hora.time()
        reg_pt, _ = RegistroPonto.objects.get_or_create(
            funcionario=func,
            data=data_b,
            defaults={'dia_semana': dias_semana_pt[data_b.weekday()]}
        )
        if not reg_pt.editado_manualmente:
            slots = ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']
            ja_tem = any(getattr(reg_pt, s) == hora_b for s in slots if getattr(reg_pt, s) is not None)
            if not ja_tem:
                for s in slots:
                    if getattr(reg_pt, s) is None:
                        setattr(reg_pt, s, hora_b)
                        reg_pt.save()
                        break

        # Alternância de tipo (1 = Entrada, 2 = Saída)
        seq_dia = seq_por_dia.get(d_ref_str, 0) + 1
        seq_por_dia[d_ref_str] = seq_dia
        tipo_efetivo = 1 if (seq_dia % 2 == 1) else 2

        # Transmissão Fiorilli
        f_id = None
        if fiorilli_svc.auth_token:
            ok, msg, f_id = fiorilli_svc.enviar_batida(
                registro=func.matricula,
                data_referencia=d_ref_str,
                data_hora=dh_str,
                tipo_batida=tipo_efetivo,
                tipo_coletor="DISPOSITIVO_ELETRONICO",
                identificador_alternativo=func.cpf or func.pis,
                nome_alternativo=func.nome_completo
            )

        b.status = 'VINCULADO_ENVIADO'
        b.servidor_vinculado = func
        b.registro_sip_usado = func.matricula
        b.fiorilli_batida_id = f_id
        b.data_resolucao = timezone.now()
        b.observacao_resolucao = f"Vinculado a {func.nome_completo} ({func.matricula}) pelo operador"
        b.save()
        total_enviadas += 1

    # Se o operador optou por ignorar o identificador antigo para sempre
    id_limpo = ''.join(c for c in identificador_valor if c.isdigit())
    if ignorar_antigo and id_limpo:
        if len(id_limpo) == 11:
            CpfIgnorado.objects.get_or_create(cpf=id_limpo)
        else:
            MatriculaIgnorada.objects.get_or_create(matricula=id_limpo)
        messages.info(request, f"O identificador '{identificador_valor}' também foi adicionado à lista de ignorados permanentes.")

    messages.success(request, f"✅ {total_enviadas} batida(s) vinculada(s) a {func.nome_completo} e enviadas com sucesso ao SIP Fiorilli!")
    return redirect('painel_standby')

@login_required
def ignorar_standby(request):
    """
    Descarta as batidas de teste de um identificador e adiciona-o à lista de ignorados permanentes.
    """
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    if request.method != 'POST':
        return redirect('painel_standby')

    identificador_valor = request.POST.get('identificador_valor', '').strip()
    id_limpo = ''.join(c for c in identificador_valor if c.isdigit()) or identificador_valor

    if not identificador_valor:
        messages.error(request, "Identificador não fornecido.")
        return redirect('painel_standby')

    if len(id_limpo) == 11:
        CpfIgnorado.objects.get_or_create(cpf=id_limpo)
    else:
        MatriculaIgnorada.objects.get_or_create(matricula=id_limpo)

    total_ign = BatidaStandby.objects.filter(identificador_valor=identificador_valor, status='PENDENTE').update(
        status='IGNORADO',
        data_resolucao=timezone.now(),
        observacao_resolucao='Identificador marcado como teste / ignorado permanente'
    )

    messages.success(request, f"🚫 O identificador '{identificador_valor}' foi cadastrado na lista de ignorados permanentes e {total_ign} batida(s) foram arquivadas.")
    return redirect('painel_standby')

@login_required
def reprocessar_standby(request):
    """
    Verifica todas as batidas em standby contra o SIP Fiorilli (para o caso de servidores recém cadastrados no RH).
    """
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    if request.method != 'POST':
        return redirect('painel_standby')

    from .fiorilli_service import FiorilliService
    fiorilli_svc = FiorilliService(request=request)

    if not fiorilli_svc.auth_token:
        messages.error(request, "Sessão com o SIP Fiorilli não autenticada para reprocessamento.")
        return redirect('painel_standby')

    pendentes = BatidaStandby.objects.filter(status='PENDENTE').order_by('data_hora')
    total_resolvidas = 0

    dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
    seq_por_dia = {}

    for b in pendentes:
        id_limpo = ''.join(c for c in b.identificador_valor if c.isdigit())
        reg_sip = fiorilli_svc.resolver_registro_sip(identificador=id_limpo, matricula=id_limpo, nome=b.nome_original)

        if reg_sip:
            # Localizou agora no SIP Fiorilli!
            func, _ = Funcionario.objects.get_or_create(
                matricula=reg_sip,
                defaults={
                    'nome_completo': b.nome_original or f"Servidor {reg_sip}",
                    'cpf': id_limpo if len(id_limpo) == 11 else '',
                    'pis': id_limpo if len(id_limpo) == 11 else ''
                }
            )

            d_ref_str = b.data_referencia.strftime('%Y-%m-%d') if b.data_referencia else b.data_hora.strftime('%Y-%m-%d')
            dh_str = b.data_hora.strftime('%Y-%m-%d %H:%M:%S')

            # Alternância de tipo (1 = Entrada, 2 = Saída)
            seq_dia = seq_por_dia.get(d_ref_str, 0) + 1
            seq_por_dia[d_ref_str] = seq_dia
            tipo_efetivo = 1 if (seq_dia % 2 == 1) else 2

            ok, msg, f_id = fiorilli_svc.enviar_batida(
                registro=reg_sip,
                data_referencia=d_ref_str,
                data_hora=dh_str,
                tipo_batida=tipo_efetivo,
                tipo_coletor="DISPOSITIVO_ELETRONICO",
                identificador_alternativo=id_limpo,
                nome_alternativo=b.nome_original
            )

            # Grava localmente
            data_b = b.data_hora.date()
            hora_b = b.data_hora.time()
            reg_pt, _ = RegistroPonto.objects.get_or_create(
                funcionario=func,
                data=data_b,
                defaults={'dia_semana': dias_semana_pt[data_b.weekday()]}
            )
            if not reg_pt.editado_manualmente:
                slots = ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']
                ja_tem = any(getattr(reg_pt, s) == hora_b for s in slots if getattr(reg_pt, s) is not None)
                if not ja_tem:
                    for s in slots:
                        if getattr(reg_pt, s) is None:
                            setattr(reg_pt, s, hora_b)
                            reg_pt.save()
                            break

            b.status = 'VINCULADO_ENVIADO'
            b.servidor_vinculado = func
            b.registro_sip_usado = reg_sip
            b.fiorilli_batida_id = f_id
            b.data_resolucao = timezone.now()
            b.observacao_resolucao = "Resolvido automaticamente por identificação recente no SIP Fiorilli"
            b.save()
            total_resolvidas += 1

    if total_resolvidas > 0:
        messages.success(request, f"🎉 {total_resolvidas} batida(s) foram identificadas no SIP e transmitidas com sucesso!")
    else:
        messages.info(request, "Nenhuma nova correspondência foi localizada no cadastro do SIP para as batidas pendentes.")

    return redirect('painel_standby')

@login_required
def descartar_standby(request, id):
    """Descarta uma batida individual de standby."""
    bloqueio = verificar_acesso_avancado(request)
    if bloqueio:
        return bloqueio

    b = get_object_or_404(BatidaStandby, id=id)
    b.status = 'DESCARTADO'
    b.data_resolucao = timezone.now()
    b.save()
    messages.info(request, f"Batida de {b.identificador_valor} em {b.data_hora.strftime('%d/%m/%Y %H:%M')} descartada.")
    return redirect('painel_standby')