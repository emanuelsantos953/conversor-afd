from django.shortcuts import render, redirect
from .forms import FuncionarioForm

# Lógica da página inicial (Home)
def home(request):
    return render(request, 'core/home.html')

# Lógica da página de cadastro
def cadastrar_funcionario(request):
    if request.method == 'POST':
        form = FuncionarioForm(request.POST)
        if form.is_valid():
            form.save() # Salva no banco de dados!
            return redirect('home') # Volta para a home após salvar
    else:
        form = FuncionarioForm()

    return render(request, 'core/cadastrar.html', {'form': form})
