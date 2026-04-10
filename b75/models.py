from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import random

# ==========================================
# SISTEMA DE LICENCIAMENTO (SAAS)
# ==========================================

class LicencaUsuario(models.Model):
    # Relacionamento 1 para 1: Cada usuário tem exatamente 1 licença
    # ADICIONADO db_constraint=False AQUI ↓
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='licenca', db_constraint=False)
    inicio = models.DateTimeField(default=timezone.now, verbose_name="Início da Licença")
    fim = models.DateTimeField(null=True, blank=True, verbose_name="Fim da Licença")
    ilimitado = models.BooleanField(default=False, verbose_name="Acesso Ilimitado / Vitalício")

    def is_ativa(self):
        # 1. Se for o Super Usuário (adminvm), passa direto!
        if self.usuario.is_superuser:
            return True
        # 2. Se a flag de ilimitado estiver marcada, passa direto!
        if self.ilimitado:
            return True
        # 3. Se tiver data de início e fim, confere com o relógio do servidor
        if self.inicio and self.fim:
            agora = timezone.now()
            return self.inicio <= agora <= self.fim
        
        # Se não cair em nenhuma regra acima, está bloqueado
        return False

    def __str__(self):
        status = "Ativa" if self.is_ativa() else "Inativa/Expirada"
        return f"Licença de {self.usuario.username} - {status}"

# Gatilho automático: Criou um usuário, cria a licença junto
@receiver(post_save, sender=User)
def criar_licenca_usuario(sender, instance, created, **kwargs):
    if created:
        LicencaUsuario.objects.create(usuario=instance)


# ==========================================
# MODELOS DO BINGO E PDV (Com isolamento de Usuário)
# ==========================================

class Cliente(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    nome = models.CharField(max_length=100)
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Contato")
    email = models.EmailField(blank=True, null=True)
    comanda = models.CharField(max_length=50, blank=True, null=True, verbose_name="Comanda")
    observacoes = models.TextField(blank=True, null=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

    class Meta:
        ordering = ['nome']

class Sorteio(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
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
    lote_nome = models.CharField(max_length=50, blank=True, null=True)
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
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    nome = models.CharField(max_length=150)
    preco = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço de Venda")
    estoque = models.IntegerField(default=0, verbose_name="Quantidade em Estoque")
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome} - R$ {self.preco}"

    class Meta:
        ordering = ['nome']

class Pedido(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos')
    comanda = models.CharField(max_length=50, blank=True, null=True, verbose_name="Número da Comanda")
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    pago = models.BooleanField(default=False, verbose_name="Pedido Pago?")
    data_pedido = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.cliente:
            return f"Pedido #{self.id} - {self.cliente.nome} (R$ {self.total})"
        return f"Pedido #{self.id} - Comanda {self.comanda} (R$ {self.total})"

    class Meta:
        ordering = ['-data_pedido']

class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT) 
    quantidade = models.PositiveIntegerField(default=1)
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantidade}x {self.produto.nome} (Pedido #{self.pedido.id})"