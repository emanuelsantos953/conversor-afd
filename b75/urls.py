from django.urls import path
from . import views

urlpatterns = [
    # Página Inicial do Bingo
    path('', views.home_bingo, name='home_bingo'),

    # Gerenciamento de Clientes
    path('clientes/', views.gerenciar_clientes, name='gerenciar_clientes'),
    path('clientes/excluir/<int:cliente_id>/', views.excluir_cliente, name='excluir_cliente'),
    path('clientes/detalhes/<int:cliente_id>/', views.detalhes_cliente, name='detalhes_cliente'),
    
    # Gerenciamento de Sorteios
    path('sorteios/', views.listar_sorteios, name='listar_sorteios'),
    path('sorteios/excluir/<int:sorteio_id>/', views.excluir_sorteio, name='excluir_sorteio'),
    
    # Painel do Globo e Ações do Jogo
    path('sorteio/<int:sorteio_id>/painel/', views.gerenciar_sorteio, name='gerenciar_sorteio'),
    path('sorteio/<int:sorteio_id>/iniciar/', views.iniciar_sorteio, name='iniciar_sorteio'),
    path('sorteio/<int:sorteio_id>/encerrar/', views.encerrar_sorteio, name='encerrar_sorteio'),
    
    # Gerenciador de Cartelas
    path('sorteio/<int:sorteio_id>/cartelas/', views.visualizar_cartelas, name='visualizar_cartelas'),
    path('sorteio/<int:sorteio_id>/gerar/', views.gerar_cartelas_view, name='gerar_cartelas'),
    path('sorteio/<int:sorteio_id>/gerar-avulsas/', views.gerar_cartelas_avulsas, name='gerar_cartelas_avulsas'),
    path('sorteio/<int:sorteio_id>/cartelas/<int:cartela_id>/excluir/', views.excluir_cartela, name='excluir_cartela'),
    
    # Gerenciamento da Lojinha (Produtos e Vendas)
    path('vendas/', views.gerenciar_produtos, name='gerenciar_produtos'),
    path('produtos/editar/<int:produto_id>/', views.editar_produto, name='editar_produto'),
    
    # CAIXA / PONTO DE VENDA (PDV)
    path('pdv/', views.pdv, name='pdv'),
    path('pdv/salvar/', views.salvar_venda, name='salvar_venda'),
    path('pdv/imprimir/<int:pedido_id>/', views.imprimir_recibo, name='imprimir_recibo'),
    
    # GESTÃO DE COBRANÇA E ACERTOS
    path('cobranca/', views.cobranca, name='cobranca'),
    path('cobranca/registrar/', views.registrar_pagamento, name='registrar_pagamento'),

    # NOVO: HISTÓRICO DE PAGAMENTOS
    path('historico/', views.historico_pagamentos, name='historico_pagamentos'),
]