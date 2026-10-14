from django.urls import path, include
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('', views.home, name='home'),
    path('processar-envio-batidas/', views.processar_envio_batidas, name='processar_envio_batidas'),
    path('comprovante-envio-pdf/', views.comprovante_envio_pdf, name='comprovante_envio_pdf'),
    path('baixar-afd-fiorilli/', views.baixar_afd_fiorilli, name='baixar_afd_fiorilli'),
    path('ajuda/', views.ajuda, name='ajuda'),
    
    # Rota do Gerenciador de Usuários (Acesso exclusivo do Admin)
    path('usuarios/', views.gerenciar_usuarios, name='gerenciar_usuarios'),
    
    path('cadastrar/', views.cadastrar_funcionario, name='cadastrar_funcionario'),
    path('gerenciar/', views.listar_funcionarios, name='listar_funcionarios'),
    path('sincronizar-servidores/', views.sincronizar_servidores_fiorilli, name='sincronizar_servidores_fiorilli'),
    path('importar/', views.importar_funcionarios, name='importar_funcionarios'),
    path('ponto/<int:funcionario_id>/', views.ver_ponto, name='ver_ponto'),
    path('ponto/salvar/', views.salvar_ponto, name='salvar_ponto'),
    path('ponto/atualizar-funcionario/', views.atualizar_funcionario, name='atualizar_funcionario'),
    path('ponto/ignorar-pis/', views.ignorar_pis, name='ignorar_pis'),
    path('ponto/ignorar-matricula/', views.ignorar_matricula, name='ignorar_matricula'),
    path('importar-planilha/', views.importar_planilha, name='importar_planilha'),
    path('importar-afd/', views.importar_afd, name='importar_afd'),
    path('exportar-afd/', views.exportar_afd, name='exportar_afd'),
    path('cadastro-ignorados/', views.cadastro_ignorados, name='cadastro_ignorados'),
    path('gerenciar-grupos/', views.gerenciar_grupos, name='gerenciar_grupos'),
    path('remover-ignorado/<str:tipo>/<int:id>/', views.remover_ignorado, name='remover_ignorado'),
    path('verificar-conflitos-grupo/', views.verificar_conflitos_grupo, name='verificar_conflitos_grupo'),
    path('monitor-relogio/', views.monitor_relogio, name='monitor_relogio'),
    path('monitor-relogio/limpar/', views.limpar_logs_relogio, name='limpar_logs_relogio'),
    
    # Rotas do Painel de Standby / Inconsistências
    path('standby/', views.painel_standby, name='painel_standby'),
    path('standby/vincular/', views.vincular_enviar_standby, name='vincular_enviar_standby'),
    path('standby/ignorar/', views.ignorar_standby, name='ignorar_standby'),
    path('standby/reprocessar/', views.reprocessar_standby, name='reprocessar_standby'),
    path('standby/descartar/<int:id>/', views.descartar_standby, name='descartar_standby'),

    # Rotas de Histórico e Reemissão de Comprovante
    path('historico/', views.historico_lancamentos, name='historico_lancamentos'),
    path('comprovante/<str:envio_id>/', views.reemitir_comprovante_pdf, name='reemitir_comprovante_pdf'),
]