import json
from django.shortcuts import render, redirect
from django.http import JsonResponse
from .forms import FuncionarioForm
from .models import Funcionario, RegistroPonto
from django.db import IntegrityError
from datetime import date
import calendar


def home(request):
    return render(request, 'core/home.html')

def cadastrar_funcionario(request):
    if request.method == 'POST':
        form = FuncionarioForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('listar_funcionarios') # Agora volta para a lista após salvar
    else:
        form = FuncionarioForm()
    return render(request, 'core/cadastrar.html', {'form': form})

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
                    'cpf': func.cpf
                })
            return JsonResponse({'funcionarios': dados})
        else:
            return JsonResponse({'funcionarios': []})

    # Se não for uma busca, apenas carrega a página vazia
    return render(request, 'core/listar.html')

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
            'registro': registros_dict.get(dia) # Pode ser None se não tiver batida
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
                }
            )
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)})

    return JsonResponse({'status': 'invalido'})
