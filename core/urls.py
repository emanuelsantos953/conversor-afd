from django.urls import path, include
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('', views.home, name='home'),
    
    # Rota do Gerenciador de Usuários (Acesso exclusivo do Admin)
    path('usuarios/', views.gerenciar_usuarios, name='gerenciar_usuarios'),
    
    path('cadastrar/', views.cadastrar_funcionario, name='cadastrar_funcionario'),
    path('gerenciar/', views.listar_funcionarios, name='listar_funcionarios'),
    path('importar/', views.importar_funcionarios, name='importar_funcionarios'),
    path('ponto/<int:funcionario_id>/', views.ver_ponto, name='ver_ponto'),
    path('ponto/salvar/', views.salvar_ponto, name='salvar_ponto'),
    path('ponto/salvar-grupo/', views.salvar_grupo, name='salvar_grupo'),
    path('ponto/ignorar-pis/', views.ignorar_pis, name='ignorar_pis'),
    path('ponto/ignorar-matricula/', views.ignorar_matricula, name='ignorar_matricula'),
    path('importar-planilha/', views.importar_planilha, name='importar_planilha'),
    path('importar-afd/', views.importar_afd, name='importar_afd'),
    path('exportar-afd/', views.exportar_afd, name='exportar_afd'),
]