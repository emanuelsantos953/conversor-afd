from django.db import models

class Funcionario(models.Model):
    matricula = models.CharField(max_length=20, unique=True)
    nome_completo = models.CharField(max_length=255)
    pis = models.CharField(max_length=11, unique=True)
    cpf = models.CharField(max_length=11, unique=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.matricula} - {self.nome_completo}"
