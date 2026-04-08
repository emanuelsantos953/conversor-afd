from django.db import models
import random

class Cliente(models.Model):
    nome = models.CharField(max_length=100)
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Contato")
    email = models.EmailField(blank=True, null=True)
    
    # NOVO CAMPO ADICIONADO:
    comanda = models.CharField(max_length=50, blank=True, null=True, verbose_name="Comanda")
    
    observacoes = models.TextField(blank=True, null=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

    class Meta:
        ordering = ['nome']

class Sorteio(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('active', 'Em Andamento'),
        ('completed', 'Concluído'),
    ]

    nome = models.CharField(max_length=150)
    preco_cartela = models.DecimalField(max_digits=10, decimal_places=2, default=2.50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

    class Meta:
        ordering = ['-data_criacao']

class Cartela(models.Model):
    sorteio = models.ForeignKey(Sorteio, on_delete=models.CASCADE, related_name='cartelas')
    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True)
    lote_nome = models.CharField(max_length=50, blank=True, null=True) # Para vendas avulsas
    # Armazenamos os números como JSON para facilitar a leitura no template
    dados_json = models.JSONField() 
    hash_verificacao = models.CharField(max_length=32, unique=True)
    data_geracao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cartela {self.id} - {self.sorteio.nome}"

class NumeroSorteado(models.Model):
    sorteio = models.ForeignKey(Sorteio, on_delete=models.CASCADE, related_name='numeros_globais')
    numero = models.PositiveSmallIntegerField()
    ordem = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ('sorteio', 'numero')
        ordering = ['ordem']

class Produto(models.Model):
    nome = models.CharField(max_length=150)
    preco = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço de Venda")
    estoque = models.IntegerField(default=0, verbose_name="Quantidade em Estoque")
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome} - R$ {self.preco}"

    class Meta:
        ordering = ['nome']