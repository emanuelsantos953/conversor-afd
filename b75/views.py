import random
import json
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.core.exceptions import PermissionDenied
from functools import wraps

from .models import Cliente, Sorteio, Cartela, NumeroSorteado, Produto, Pedido, ItemPedido
from .forms import ClienteForm, ProdutoForm
from .bingo_logic import gerar_numeros_cartela, gerar_hash_unico, calcular_numeros_faltantes, conferir_vitoria

# ==========================================
# CATRACA DE SEGURANÇA (LICENÇA)
# ==========================================
def licenca_obrigatoria(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        if hasattr(request.user, 'licenca') and request.user.licenca.is_ativa():
            return view_func(request, *args, **kwargs)
        return render(request, 'b75/licenca_expirada.html')
    return _wrapped_view

# ==========================================
# HOME BINGO
# ==========================================
@login_required
@licenca_obrigatoria
def home_bingo(request):
    return render(request, 'b75/home_bingo.html')

# ==========================================
# GERENCIAMENTO DE CLIENTES
# ==========================================
@login_required
@licenca_obrigatoria
def gerenciar_clientes(request):
    search_query = request.GET.get('q', '')
    if search_query:
        clientes = Cliente.objects.filter(usuario=request.user).filter(
            Q(nome__icontains=search_query) | 
            Q(telefone__icontains=search_query) |
            Q(comanda__icontains=search_query)
        )
    else:
        clientes = Cliente.objects.filter(usuario=request.user)

    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save(commit=False)
            cliente.usuario = request.user
            # Garante a captura da comanda no cadastro inicial
            cliente.comanda = request.POST.get('comanda')
            cliente.save()
            messages.success(request, 'Cliente adicionado com sucesso!')
            return redirect('gerenciar_clientes')
    else:
        form = ClienteForm()

    return render(request, 'b75/clientes.html', {
        'clientes': clientes, 'form': form, 'search_query': search_query
    })

@login_required
@licenca_obrigatoria
def detalhes_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id, usuario=request.user)
    
    if request.method == 'POST':
        # Atualização manual dos campos para garantir persistência (incluindo comanda)
        cliente.nome = request.POST.get('nome')
        cliente.telefone = request.POST.get('telefone')
        cliente.email = request.POST.get('email')
        cliente.comanda = request.POST.get('comanda')
        cliente.save()
        messages.success(request, 'Dados do cliente atualizados com sucesso!')
        return redirect('detalhes_cliente', cliente_id=cliente.id)

    pedidos = Pedido.objects.filter(cliente=cliente, usuario=request.user).order_by('-data_pedido')
    total_gasto = pedidos.aggregate(Sum('total'))['total__sum'] or 0
    
    return render(request, 'b75/detalhes_cliente.html', {
        'cliente': cliente, 
        'pedidos': pedidos,
        'total_gasto': total_gasto,
        'total_pedidos': pedidos.count()
    })

@login_required
@licenca_obrigatoria
def excluir_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id, usuario=request.user)
    cliente.delete()
    messages.success(request, 'Cliente removido.')
    return redirect('gerenciar_clientes')

# ==========================================
# GERENCIAMENTO DE SORTEIOS E BINGO
# ==========================================
@login_required
@licenca_obrigatoria
def listar_sorteios(request):
    sorteios = Sorteio.objects.filter(usuario=request.user)
    if request.method == 'POST':
        nome = request.POST.get('nome')
        preco = request.POST.get('preco', '2.50').replace(',', '.')
        if nome:
            Sorteio.objects.create(nome=nome, preco_cartela=preco, usuario=request.user)
            messages.success(request, f'Sorteio "{nome}" criado.')
            return redirect('listar_sorteios')
    return render(request, 'b75/sorteios.html', {'sorteios': sorteios})

@login_required
@licenca_obrigatoria
def excluir_sorteio(request, sorteio_id):
    get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user).delete()
    return redirect('listar_sorteios')

@login_required
@licenca_obrigatoria
def gerar_cartelas_view(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    cliente_id = request.POST.get('cliente_id')
    cliente = get_object_or_404(Cliente, id=cliente_id, usuario=request.user)
    quantidade = int(request.POST.get('quantidade', 1))
    for _ in range(quantidade):
        Cartela.objects.create(sorteio=sorteio, cliente=cliente, dados_json=gerar_numbers_cartela(), hash_verificacao=gerar_hash_unico())
    return redirect('visualizar_cartelas', sorteio_id=sorteio.id)

@login_required
@licenca_obrigatoria
def gerar_cartelas_avulsas(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    lote = request.POST.get('lote_nome')
    quantidade = int(request.POST.get('quantidade', 1))
    for _ in range(quantidade):
        Cartela.objects.create(sorteio=sorteio, cliente=None, lote_nome=lote, dados_json=gerar_numeros_cartela(), hash_verificacao=gerar_hash_unico())
    return redirect('visualizar_cartelas', sorteio_id=sorteio.id)

@login_required
@licenca_obrigatoria
def gerenciar_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    sorteados = NumeroSorteado.objects.filter(sorteio=sorteio).order_by('ordem').values_list('numero', flat=True)
    return render(request, 'b75/painel_sorteio.html', {'sorteio': sorteio, 'sorteados': sorteados})

@login_required
@licenca_obrigatoria
def visualizar_cartelas(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    cartelas = Cartela.objects.filter(sorteio=sorteio)
    todos_clientes = Cliente.objects.filter(usuario=request.user)
    return render(request, 'b75/visualizar_cartelas.html', {'sorteio': sorteio, 'cartelas': cartelas, 'todos_clientes': todos_clientes})

@login_required
@licenca_obrigatoria
def iniciar_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    sorteio.status = 'active'
    sorteio.save()
    return redirect('gerenciar_sorteio', sorteio_id=sorteio.id)

@login_required
@licenca_obrigatoria
def encerrar_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    sorteio.status = 'finished'
    sorteio.save()
    return redirect('gerenciar_sorteio', sorteio_id=sorteio.id)

@login_required
@licenca_obrigatoria
def excluir_cartela(request, sorteio_id, cartela_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id, usuario=request.user)
    get_object_or_404(Cartela, id=cartela_id, sorteio=sorteio).delete()
    return redirect('visualizar_cartelas', sorteio_id=sorteio.id)

# ==========================================
# LOJINHA E PRODUTOS
# ==========================================
@login_required
@licenca_obrigatoria
def gerenciar_produtos(request):
    if request.method == 'POST':
        form = ProdutoForm(request.POST)
        if form.is_valid():
            produto = form.save(commit=False)
            produto.usuario = request.user
            produto.save()
            return redirect('gerenciar_produtos')
    else:
        form = ProdutoForm()
    produtos = Produto.objects.filter(usuario=request.user)
    return render(request, 'b75/produtos.html', {'produtos': produtos, 'form': form})

@login_required
@licenca_obrigatoria
def editar_produto(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id, usuario=request.user)
    if request.method == 'POST':
        produto.nome = request.POST.get('nome')
        produto.preco = request.POST.get('preco', '0').replace(',', '.')
        produto.estoque = request.POST.get('estoque', 0)
        produto.save()
    return redirect('gerenciar_produtos')

# ==========================================
# CAIXA / PDV E RECIBO
# ==========================================
@login_required
@licenca_obrigatoria
def pdv(request):
    produtos = Produto.objects.filter(usuario=request.user, estoque__gt=0).order_by('nome')
    clientes = Cliente.objects.filter(usuario=request.user).order_by('nome')
    return render(request, 'b75/pdv.html', {'produtos': produtos, 'clientes': clientes})

@login_required
@licenca_obrigatoria
def salvar_venda(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            itens = dados.get('itens', [])
            cliente_id = dados.get('cliente_id')
            cliente_obj = Cliente.objects.get(id=cliente_id, usuario=request.user) if cliente_id else None
            
            metodo_inicial = 'Espécie' if dados.get('pago', False) else ''
            
            novo_pedido = Pedido.objects.create(
                usuario=request.user, 
                cliente=cliente_obj, 
                total=dados.get('total_venda', 0), 
                pago=dados.get('pago', False),
                metodo_pagamento=metodo_inicial
            )
            for item in itens:
                prod = Produto.objects.get(id=item['produto_id'], usuario=request.user)
                ItemPedido.objects.create(pedido=novo_pedido, produto=prod, quantidade=item['quantidade'], preco_unitario=prod.preco)
                prod.estoque -= int(item['quantidade'])
                prod.save()
            return JsonResponse({'status': 'sucesso', 'pedido_id': novo_pedido.id})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)})
    return JsonResponse({'status': 'invalido'})

@login_required
@licenca_obrigatoria
def imprimir_recibo(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)
    return render(request, 'b75/recibo.html', {'pedido': pedido, 'senha': str(pedido.id).zfill(4), 'data': pedido.data_pedido})

# ==========================================
# GESTÃO DE COBRANÇA E HISTÓRICO
# ==========================================
@login_required
@licenca_obrigatoria
def cobranca(request):
    clientes = Cliente.objects.filter(usuario=request.user).order_by('nome')
    cliente_id = request.GET.get('cliente_id')
    cliente_sel = get_object_or_404(Cliente, id=cliente_id, usuario=request.user) if cliente_id else None
    pedidos = Pedido.objects.filter(cliente=cliente_sel, usuario=request.user, pago=False) if cliente_sel else []
    total = pedidos.aggregate(Sum('total'))['total__sum'] or 0
    return render(request, 'b75/cobranca.html', {'clientes': clientes, 'cliente_selecionado': cliente_sel, 'pedidos': pedidos, 'total_pendente': total})

@login_required
@licenca_obrigatoria
def registrar_pagamento(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            metodo = dados.get('metodo_pagamento', 'Indefinido')
            Pedido.objects.filter(id__in=dados.get('pedido_ids', []), usuario=request.user).update(pago=True, metodo_pagamento=metodo)
            return JsonResponse({'status': 'sucesso', 'mensagem': 'Pagamento registrado!'})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)})
    return JsonResponse({'status': 'invalido'})

@login_required
@licenca_obrigatoria
def historico_pagamentos(request):
    search_query = request.GET.get('q', '')
    metodo_filtro = request.GET.get('metodo', '')
    
    pedidos = Pedido.objects.filter(usuario=request.user, pago=True).order_by('-data_pedido')
    
    if search_query:
        pedidos = pedidos.filter(
            Q(cliente__nome__icontains=search_query) | 
            Q(cliente__comanda__icontains=search_query) |
            Q(id__icontains=search_query)
        )
    
    if metodo_filtro:
        pedidos = pedidos.filter(metodo_pagamento=metodo_filtro)
    
    total_recebido = pedidos.aggregate(Sum('total'))['total__sum'] or 0
    metodos_disponiveis = ['Espécie', 'PIX', 'Cartão', 'Lançamento em Conta Corrente']

    return render(request, 'b75/historico.html', {
        'pedidos': pedidos,
        'search_query': search_query,
        'metodo_filtro': metodo_filtro,
        'metodos': metodos_disponiveis,
        'total_recebido': total_recebido
    })