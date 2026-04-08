from django import forms
from .models import Cliente, Produto

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        # Adicionamos a 'comanda' na lista de campos a serem exibidos:
        fields = ['nome', 'comanda', 'telefone', 'email', 'observacoes']
        
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome Completo'}),
            
            # NOVO CAMPO ADICIONADO AQUI:
            'comanda': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 42 ou Mesa 10'}),
            
            'telefone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(XX) 9XXXX-XXXX'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Anotações...'}),
        }

class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = ['nome', 'preco', 'estoque']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Cerveja, Refrigerante, Porção...'}),
            'preco': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'estoque': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 50'}),
        }