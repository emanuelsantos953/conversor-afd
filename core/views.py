from django.shortcuts import render, redirect
from .forms import FuncionarioForm
from .models import Funcionario  # <- Adicionado aqui!

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

# Nova função para listar!
def listar_funcionarios(request):
    funcionarios = Funcionario.objects.all() # Busca todos no banco de dados
    return render(request, 'core/listar.html', {'funcionarios': funcionarios})
