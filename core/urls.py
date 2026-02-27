from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('cadastrar/', views.cadastrar_funcionario, name='cadastrar_funcionario'),
    path('gerenciar/', views.listar_funcionarios, name='listar_funcionarios'),
    path('importar/', views.importar_funcionarios, name='importar_funcionarios'),
    path('ponto/<int:funcionario_id>/', views.ver_ponto, name='ver_ponto'),
    path('ponto/salvar/', views.salvar_ponto, name='salvar_ponto'),
    path('importar-afd/', views.importar_afd, name='importar_afd'),
]
