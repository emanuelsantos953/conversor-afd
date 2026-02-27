from django.shortcuts import render, redirect
from django.http import JsonResponse
from .forms import FuncionarioForm
from .models import Funcionario  # <- Adicionado aqui!
from django.db import IntegrityError


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
