import random
import uuid

def gerar_numeros_cartela():
    """
    Gera uma matriz 5x5 seguindo as regras oficiais do Bingo 75.
    Intervalos: B(1-15), I(16-30), N(31-45), G(46-60), O(61-75).
    """
    intervalos = {
        'B': list(range(1, 16)),   # 1 a 15
        'I': list(range(16, 31)),  # 16 a 30
        'N': list(range(31, 46)),  # 31 a 45
        'G': list(range(46, 61)),  # 46 a 60
        'O': list(range(61, 76))   # 61 a 75
    }
    
    cartela = {}
    for letra, numeros_possiveis in intervalos.items():
        # Sorteia 5 números únicos para cada coluna
        selecionados = random.sample(numeros_possiveis, 5)
        
        # O centro da coluna 'N' (índice 2) é o espaço "FREE"
        if letra == 'N':
            selecionados[2] = "X"
            
        cartela[letra] = selecionados
        
    return cartela

def gerar_hash_unico():
    """Gera um identificador único para cada cartela para evitar fraudes."""
    return uuid.uuid4().hex[:12].upper()

def conferir_vitoria(cartela_json, bolas_sorteadas):
    sorteadas = set(bolas_sorteadas)
    colunas = ['B', 'I', 'N', 'G', 'O']
    
    # 1. Monta um "mapa de acertos" 5x5 (True para marcado, False para vazio)
    acertos = []
    for i in range(5):
        linha = []
        for j, letra in enumerate(colunas):
            if i == 2 and j == 2:
                linha.append(True)  # O espaço do meio (N3) é sempre LIVRE
            else:
                numero = cartela_json[letra][i]
                linha.append(numero in sorteadas)
        acertos.append(linha)
        
    # 2. Verifica Linhas Horizontais
    for linha in acertos:
        if all(linha): return True
        
    # 3. Verifica Colunas Verticais
    for j in range(5):
        if all(acertos[i][j] for i in range(5)): return True
        
    # 4. Verifica Diagonais
    if all(acertos[i][i] for i in range(5)): return True
    if all(acertos[i][4-i] for i in range(5)): return True
    
    return False

def calcular_numeros_faltantes(cartela_json, bolas_sorteadas):
    sorteadas = set(bolas_sorteadas)
    colunas = ['B', 'I', 'N', 'G', 'O']
    
    # Monta o mesmo mapa de acertos
    acertos = []
    for i in range(5):
        linha = []
        for j, letra in enumerate(colunas):
            if i == 2 and j == 2:
                linha.append(True)
            else:
                numero = cartela_json[letra][i]
                linha.append(numero in sorteadas)
        acertos.append(linha)
        
    # Inicia assumindo que faltam 5 (cartela zerada)
    faltam_minimo = 5
    
    # Procura a linha horizontal mais próxima de bater
    for linha in acertos:
        faltam_minimo = min(faltam_minimo, 5 - sum(linha))
        
    # Procura a coluna vertical mais próxima de bater
    for j in range(5):
        acertos_coluna = sum(acertos[i][j] for i in range(5))
        faltam_minimo = min(faltam_minimo, 5 - acertos_coluna)
        
    # Verifica a diagonal principal (\)
    acertos_diag1 = sum(acertos[i][i] for i in range(5))
    faltam_minimo = min(faltam_minimo, 5 - acertos_diag1)
    
    # Verifica a diagonal secundária (/)
    acertos_diag2 = sum(acertos[i][4-i] for i in range(5))
    faltam_minimo = min(faltam_minimo, 5 - acertos_diag2)
    
    return faltam_minimo