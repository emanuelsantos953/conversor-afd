import random
import json
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Cliente, Sorteio, Cartela, NumeroSorteado, Produto
from .forms import ClienteForm, ProdutoForm
from .bingo_logic import gerar_numeros_cartela, gerar_hash_unico, calcular_numeros_faltantes, conferir_vitoria

@login_required
def home_bingo(request):
    return render(request, 'b75/home_bingo.html')

@login_required
def gerenciar_clientes(request):
    search_query = request.GET.get('q', '')
    
    # Lógica de Busca igual ao React
    if search_query:
        clientes = Cliente.objects.filter(
            Q(nome__icontains=search_query) | 
            Q(telefone__icontains=search_query)
        )
    else:
        clientes = Cliente.objects.all()

    # Formulário de Adição
    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cliente adicionado com sucesso!')
            return redirect('gerenciar_clientes')
    else:
        form = ClienteForm()

    return render(request, 'b75/clientes.html', {
        'clientes': clientes, 
        'form': form,
        'search_query': search_query,
        'total_clientes': clientes.count()
    })

@login_required
def detalhes_cliente(request, cliente_id):
    # Esta view substitui o Modal de "Ver Detalhes" do React
    cliente = get_object_or_404(Cliente, id=cliente_id)
    
    # PLACEHOLDER: Futuramente buscaremos as vendas reais aqui
    # Por enquanto, vamos mandar listas vazias para o template não quebrar
    vendas = [] 
    total_gasto = 0
    total_pedidos = 0

    return render(request, 'b75/detalhes_cliente.html', {
        'cliente': cliente,
        'vendas': vendas,
        'total_gasto': total_gasto,
        'total_pedidos': total_pedidos
    })

@login_required
def excluir_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    cliente.delete()
    messages.success(request, 'Cliente removido.')
    return redirect('gerenciar_clientes')

@login_required
def listar_sorteios(request):
    sorteios = Sorteio.objects.all()
    
    if request.method == 'POST':
        nome = request.POST.get('nome')
        preco = request.POST.get('preco', '2.50').replace(',', '.')
        
        if nome:
            Sorteio.objects.create(nome=nome, preco_cartela=preco)
            messages.success(request, f'Sorteio "{nome}" criado com sucesso!')
            return redirect('listar_sorteios')

    return render(request, 'b75/sorteios.html', {'sorteios': sorteios})

@login_required
def excluir_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    nome = sorteio.nome
    sorteio.delete()
    messages.error(request, f'Sorteio "{nome}" excluído.')
    return redirect('listar_sorteios')

@login_required
def gerar_cartelas_view(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    
    # NOVA TRAVA DE SEGURANÇA
    if sorteio.status != 'pending':
        messages.error(request, 'Ação bloqueada: Não é possível gerar cartelas para um sorteio em andamento ou encerrado.')
        return redirect('visualizar_cartelas', sorteio_id=sorteio.id)
    
    cliente_id = request.POST.get('cliente_id')
    cliente = get_object_or_404(Cliente, id=cliente_id)
    quantidade = int(request.POST.get('quantidade', 1))
    
    for _ in range(quantidade):
        Cartela.objects.create(
            sorteio=sorteio,
            cliente=cliente,
            dados_json=gerar_numeros_cartela(),
            hash_verificacao=gerar_hash_unico()
        )
    
    messages.success(request, f"{quantidade} cartelas geradas para {cliente.nome}!")
    return redirect('visualizar_cartelas', sorteio_id=sorteio.id)

@login_required
def gerenciar_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    sorteados = NumeroSorteado.objects.filter(sorteio=sorteio).order_by('ordem').values_list('numero', flat=True)
    
    # --- NOVA LÓGICA DE SORTEIO (AJAX) ---
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and sorteio.status == 'active':
        acao = request.GET.get('action', 'draw_one')
        
        sorteados_list = list(sorteados)
        numeros_possiveis = [n for n in range(1, 76) if n not in sorteados_list]
        cartelas_participantes = list(Cartela.objects.filter(sorteio=sorteio)) # Carrega uma vez só para ficar rápido
        
        def checar_vencedores(lista_bolas):
            ganhadores = []
            for c in cartelas_participantes:
                if conferir_vitoria(c.dados_json, lista_bolas):
                    ganhadores.append({'nome': c.cliente.nome if c.cliente else c.lote_nome, 'hash': c.hash_verificacao})
            return ganhadores

        # 1. SORTEIO NORMAL (1 Bola Aleatória)
        if acao == 'draw_one' and numeros_possiveis:
            novo_numero = random.choice(numeros_possiveis)
            NumeroSorteado.objects.create(sorteio=sorteio, numero=novo_numero, ordem=len(sorteados_list) + 1)
            sorteados_list.append(novo_numero)
            return JsonResponse({'numero': novo_numero, 'numeros_turbo': [novo_numero], 'ganhadores': checar_vencedores(sorteados_list)})
            
        # 2. SORTEIO MANUAL (Bola digitada)
        elif acao == 'manual':
            try:
                num = int(request.GET.get('number', 0))
                if num in numeros_possiveis:
                    NumeroSorteado.objects.create(sorteio=sorteio, numero=num, ordem=len(sorteados_list) + 1)
                    sorteados_list.append(num)
                    return JsonResponse({'numero': num, 'numeros_turbo': [num], 'ganhadores': checar_vencedores(sorteados_list)})
                else:
                    return JsonResponse({'error': 'Número já sorteado ou inválido (deve ser de 1 a 75).'}, status=400)
            except ValueError:
                return JsonResponse({'error': 'Número inválido.'}, status=400)

        # 3. SORTEIO TURBO (Vai sorteando até alguém ganhar)
        elif acao == 'turbo' and numeros_possiveis:
            bolas_do_turbo = []
            vencedores = []
            
            while numeros_possiveis and not vencedores:
                novo_numero = random.choice(numeros_possiveis)
                numeros_possiveis.remove(novo_numero)
                NumeroSorteado.objects.create(sorteio=sorteio, numero=novo_numero, ordem=len(sorteados_list) + 1)
                sorteados_list.append(novo_numero)
                bolas_do_turbo.append(novo_numero)
                
                vencedores = checar_vencedores(sorteados_list)
                if vencedores:
                    break
                    
            return JsonResponse({
                'numero': bolas_do_turbo[-1] if bolas_do_turbo else None, 
                'numeros_turbo': bolas_do_turbo, 
                'ganhadores': vencedores
            })

    # --- FIM DA LÓGICA DE SORTEIO ---

    # Preparar Ranking (Top 5 mais próximos)
    ranking = []
    todas_cartelas = Cartela.objects.filter(sorteio=sorteio)
    for c in todas_cartelas:
        faltam = calcular_numeros_faltantes(c.dados_json, sorteados)
        ranking.append({
            'cliente': c.cliente.nome if c.cliente else c.lote_nome,
            'faltam': faltam,
            'cartela_id': c.id
        })
    ranking = sorted(ranking, key=lambda x: x['faltam'])[:5]

    return render(request, 'b75/painel_sorteio.html', {
        'sorteio': sorteio,
        'sorteados': sorteados,
        'ranking': ranking,
        'range_1_76': range(1, 76),
    })

@login_required
def gerar_cartelas_avulsas(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    
    # NOVA TRAVA DE SEGURANÇA
    if sorteio.status != 'pending':
        messages.error(request, 'Ação bloqueada: Não é possível gerar cartelas para um sorteio em andamento ou encerrado.')
        return redirect('visualizar_cartelas', sorteio_id=sorteio.id)
        
    lote = request.POST.get('lote_nome')
    quantidade = int(request.POST.get('quantidade', 1))
    
    for _ in range(quantidade):
        Cartela.objects.create(
            sorteio=sorteio,
            cliente=None, 
            lote_nome=lote,
            dados_json=gerar_numeros_cartela(),
            hash_verificacao=gerar_hash_unico()
        )
    
    messages.success(request, f"Lote '{lote}' com {quantidade} cartelas gerado com sucesso!")
    return redirect('visualizar_cartelas', sorteio_id=sorteio.id)

@login_required
def visualizar_cartelas(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    query = request.GET.get('q', '')
    
    # 1. BUSCA AS BOLAS QUE JÁ SAÍRAM NESTE SORTEIO (Corrigindo Inteiro vs String)
    sorteados_db = NumeroSorteado.objects.filter(sorteio=sorteio).values_list('numero', flat=True)
    sorteados = []
    for num in sorteados_db:
        sorteados.append(num)       # Adiciona como Número (Ex: 15)
        sorteados.append(str(num))  # Adiciona como Texto (Ex: "15")

    cartelas = Cartela.objects.filter(sorteio=sorteio)
    
    if query:
        cartelas = cartelas.filter(
            Q(cliente__nome__icontains=query) |
            Q(lote_nome__icontains=query) |
            Q(hash_verificacao__icontains=query) |
            Q(id__icontains=query)
        )
        
    cartelas_formatadas = []
    for c in cartelas:
        linhas = []
        dados = c.dados_json
        
        # GARANTIA: Se o banco devolver como Texto, converte para Dicionário
        if isinstance(dados, str):
            try:
                dados = json.loads(dados)
            except:
                dados = {}
                
        if isinstance(dados, dict) and all(k in dados for k in ['B', 'I', 'N', 'G', 'O']):
            for i in range(5):
                n_valor = dados['N'][i]
                if i == 2: 
                    n_valor = "LIVRE"
                linhas.append([dados['B'][i], dados['I'][i], n_valor, dados['G'][i], dados['O'][i]])
                
        cartelas_formatadas.append({
            'id': c.id,
            'proprietario': c.cliente.nome if c.cliente else c.lote_nome,
            'hash': c.hash_verificacao,
            'linhas': linhas
        })
        
    todos_clientes = Cliente.objects.all()

    return render(request, 'b75/visualizar_cartelas.html', {
        'sorteio': sorteio,
        'cartelas': cartelas_formatadas,
        'query': query,
        'todos_clientes': todos_clientes,
        'sorteados': sorteados,
    })

@login_required
def excluir_cartela(request, sorteio_id, cartela_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    cartela = get_object_or_404(Cartela, id=cartela_id, sorteio=sorteio)
    
    # Regra: Só pode excluir se o sorteio ainda não começou ('pending')
    if request.method == 'POST':
        if sorteio.status == 'pending':
            cartela.delete()
            messages.success(request, f'Cartela #{cartela_id} excluída com sucesso!')
        else:
            messages.error(request, 'Ação bloqueada: O sorteio já está em andamento ou foi finalizado.')
            
    return redirect('visualizar_cartelas', sorteio_id=sorteio.id)

@login_required
def iniciar_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    if sorteio.status == 'pending':
        sorteio.status = 'active'
        sorteio.save()
        messages.success(request, 'Sorteio iniciado! As cartelas foram travadas e o globo está liberado.')
    return redirect('gerenciar_sorteio', sorteio_id=sorteio.id)

@login_required
def encerrar_sorteio(request, sorteio_id):
    sorteio = get_object_or_404(Sorteio, id=sorteio_id)
    
    # Só encerra se a requisição for POST (por segurança) e se estiver ativo
    if request.method == 'POST' and sorteio.status == 'active':
        sorteio.status = 'finished'  # Muda o status para encerrado/finalizado
        sorteio.save()
        messages.success(request, 'Sorteio encerrado com sucesso! Nenhuma nova bola poderá ser sorteada.')
        
    return redirect('gerenciar_sorteio', sorteio_id=sorteio.id)

def gerenciar_produtos(request):
    # Processa o formulário se o usuário estiver adicionando um produto
    if request.method == 'POST':
        form = ProdutoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Produto cadastrado com sucesso!')
            return redirect('gerenciar_produtos')
    else:
        form = ProdutoForm()

    # Sistema de busca de produtos
    search_query = request.GET.get('q', '')
    if search_query:
        produtos = Produto.objects.filter(nome__icontains=search_query)
    else:
        produtos = Produto.objects.all()

    return render(request, 'b75/produtos.html', {
        'produtos': produtos,
        'form': form,
        'search_query': search_query
    })