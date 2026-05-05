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
