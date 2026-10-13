import re

def clean_digits(value) -> str:
    """Remove todos os caracteres não numéricos de uma string."""
    if value is None:
        return ""
    return re.sub(r'\D', '', str(value).strip())

def validate_cpf(cpf_raw: str) -> bool:
    """Valida se uma string é um CPF matematicamente válido."""
    cpf = clean_digits(cpf_raw)
    if len(cpf) != 11:
        return False
    # CPFs com todos os dígitos iguais são inválidos
    if cpf == cpf[0] * 11:
        return False
    
    # Validação do primeiro dígito
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    d1 = 0 if resto == 10 else resto
    if d1 != int(cpf[9]):
        return False

    # Validação do segundo dígito
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    d2 = 0 if resto == 10 else resto
    if d2 != int(cpf[10]):
        return False

    return True

def validate_pis(pis_raw: str) -> bool:
    """Valida se uma string é um PIS/PASEP matematicamente válido."""
    pis = clean_digits(pis_raw)
    if len(pis) == 12 and pis.startswith("0"):
        pis = pis[1:]
    if len(pis) != 11:
        return False
    if pis == pis[0] * 11:
        return False

    pesos = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(pis[i]) * pesos[i] for i in range(10))
    resto = soma % 11
    dv = 0 if resto in (0, 1) else (11 - resto)
    return dv == int(pis[10])

def is_matricula_candidate(val_raw: str) -> bool:
    """Verifica se o valor tem características de matrícula (1 a 7 dígitos inteiros ou contrato com hífen)."""
    val = str(val_raw).strip()
    if not val:
        return False
    
    # Formato com hífen (ex: 123-1, 00123-2)
    if re.match(r'^\d{1,7}[-/]\d{1,2}$', val):
        return True
    
    # Apenas dígitos com até 7 caracteres
    digits = clean_digits(val)
    if 1 <= len(digits) <= 7 and int(digits) > 0:
        return True
    
    return False

def detect_identifier_type(value, col_header: str = "") -> str:
    """
    Identifica de forma inteligente se um valor/coluna representa:
    'CPF', 'PIS', 'MATRICULA' ou 'DESCONHECIDO'.
    """
    if value is None:
        return "DESCONHECIDO"
    
    val_str = str(value).strip()
    digits = clean_digits(val_str)
    header_lower = str(col_header).strip().lower()

    # 1. Dica forte pelo cabeçalho da coluna
    if any(k in header_lower for k in ["cpf", "doc", "documento"]):
        if validate_cpf(val_str) or len(digits) == 11:
            return "CPF"
    elif any(k in header_lower for k in ["pis", "pasep", "nis"]):
        if validate_pis(val_str) or len(digits) == 11:
            return "PIS"
    elif any(k in header_lower for k in ["matricula", "matrícula", "mat", "cracha", "crachá", "re", "codigo", "código", "id_func"]):
        if is_matricula_candidate(val_str):
            return "MATRICULA"

    # 2. Análise do conteúdo da célula
    # Se tiver máscara de CPF (000.000.000-00) ou validar matematicamente
    if ("." in val_str and "-" in val_str and len(digits) == 11) or validate_cpf(val_str):
        return "CPF"

    # Se validar como PIS ou for PIS posicional de 12 dígitos (com zero à esquerda)
    if validate_pis(val_str) or (len(digits) == 12 and digits.startswith("0")):
        return "PIS"

    # Se for 11 dígitos, mas não validou CPF matemático, ainda pode ser CPF ou PIS sem dígito estrito
    if len(digits) == 11:
        return "CPF"

    # Se for número curto (1 a 7 dígitos) ou formato contrato (123-1)
    if is_matricula_candidate(val_str):
        return "MATRICULA"

    return "DESCONHECIDO"
