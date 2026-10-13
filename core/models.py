from django.db import models

class Grupo(models.Model):
    nome = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nome

class Funcionario(models.Model):
    matricula = models.CharField(max_length=20, unique=True)
    nome_completo = models.CharField(max_length=255)
    pis = models.CharField(max_length=11, unique=True)
    cpf = models.CharField(max_length=11, unique=True)
    grupos = models.ManyToManyField(Grupo, blank=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.matricula} - {self.nome_completo}"

class RegistroPonto(models.Model):
    # Relaciona o ponto ao funcionário (Se o funcionário for apagado, os pontos dele também são)
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE)

    # Data e Dia da Semana
    data = models.DateField()
    dia_semana = models.CharField(max_length=15) # Ex: 'seg', 'ter', 'qua'

    # Batidas (null=True e blank=True permitem que o campo fique vazio caso ele não bata o ponto)
    entrada_1 = models.TimeField(null=True, blank=True)
    saida_1 = models.TimeField(null=True, blank=True)
    entrada_2 = models.TimeField(null=True, blank=True)
    saida_2 = models.TimeField(null=True, blank=True)
    entrada_3 = models.TimeField(null=True, blank=True)
    saida_3 = models.TimeField(null=True, blank=True)
    editado_manualmente = models.BooleanField(default=False)

    class Meta:
        # Garante que um funcionário não tenha duas linhas da mesma data
        unique_together = ('funcionario', 'data')

    def __str__(self):
        return f"{self.funcionario.nome_completo} - {self.data}"

class PisIgnorado(models.Model):
    pis = models.CharField(max_length=11, unique=True)
    data_adicionado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PIS Ignorado: {self.pis}"

class MatriculaIgnorada(models.Model):
    matricula = models.CharField(max_length=20, unique=True)
    data_adicionado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Matrícula Ignorada: {self.matricula}"

class CpfIgnorado(models.Model):
    cpf = models.CharField(max_length=11, unique=True)
    data_adicionado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CPF Ignorado: {self.cpf}"

class LogRelogio(models.Model):
    TIPO_CHOICES = [
        ('conexao', '🟢 Conexão'),
        ('desconexao', '🔴 Desconexão'),
        ('batida', '✅ Batida Salva'),
        ('desconhecido', '⚠️ Desconhecido'),
        ('erro', '❌ Erro'),
        ('mensagem', '📩 Mensagem'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    numero_serie = models.CharField(max_length=50, blank=True, default='')
    mensagem = models.TextField()
    data_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_hora']

    def __str__(self):
        return f"[{self.tipo}] {self.numero_serie} - {self.data_hora.strftime('%d/%m/%Y %H:%M:%S')}"


class BatidaStandby(models.Model):
    STATUS_CHOICES = [
        ('PENDENTE', '⏳ Pendente / Standby'),
        ('VINCULADO_ENVIADO', '✅ Vinculado e Enviado'),
        ('IGNORADO', '🚫 Ignorado'),
        ('DESCARTADO', '🗑️ Descartado'),
    ]

    identificador_valor = models.CharField(max_length=50, db_index=True)
    tipo_identificador = models.CharField(max_length=20, default='DESCONHECIDO') # CPF, PIS, MATRICULA, DESCONHECIDO
    nome_original = models.CharField(max_length=255, blank=True, default='')
    motivo_inconsistencia = models.CharField(max_length=255)
    data_referencia = models.DateField(null=True, blank=True)
    data_hora = models.DateTimeField(db_index=True)
    numero_serie_relogio = models.CharField(max_length=50, blank=True, default='')
    origem_arquivo = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', db_index=True)

    servidor_vinculado = models.ForeignKey(Funcionario, null=True, blank=True, on_delete=models.SET_NULL, related_name='batidas_standby_resolvidas')
    registro_sip_usado = models.CharField(max_length=20, blank=True, default='')
    observacao_resolucao = models.TextField(blank=True, default='')
    fiorilli_batida_id = models.IntegerField(null=True, blank=True)

    data_criacao = models.DateTimeField(auto_now_add=True)
    data_resolucao = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-data_hora']
        unique_together = ('identificador_valor', 'data_hora')

    def __str__(self):
        return f"[{self.status}] {self.identificador_valor} ({self.data_hora.strftime('%d/%m/%Y %H:%M:%S')}) - {self.motivo_inconsistencia}"

