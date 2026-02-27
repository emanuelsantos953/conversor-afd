from django import forms
from .models import Funcionario

class FuncionarioForm(forms.ModelForm):
    class Meta:
        model = Funcionario
        # ADICIONAMOS O 'grupo_ponto' NA LISTA DE CAMPOS
        fields = ['matricula', 'nome_completo', 'pis', 'cpf', 'grupo_ponto']
        
        # Aqui configuramos o visual (HTML) de cada campo diretamente pelo Python
        widgets = {
            'matricula': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 123456', 'style': 'width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'}),
            'nome_completo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome completo do funcionário', 'style': 'width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'}),
            'pis': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apenas números (11 dígitos)', 'style': 'width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apenas números (11 dígitos)', 'style': 'width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'}),
            'grupo_ponto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Operacional, Escritório (Opcional)', 'style': 'width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'}),
        }
        
        labels = {
            'matricula': 'Matrícula',
            'nome_completo': 'Nome Completo',
            'pis': 'Número do PIS',
            'cpf': 'Número do CPF',
            'grupo_ponto': 'Grupo de Ponto (Opcional)',
        }
