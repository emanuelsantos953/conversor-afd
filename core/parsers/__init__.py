import os
from typing import List, Dict, Tuple, Optional
from .afd_parser import parse_afd_file
from .excel_parser import parse_excel_or_csv

def parse_ponto_file(file_path: str, data_inicio: Optional[str] = None, data_fim: Optional[str] = None) -> Tuple[List[Dict], str, str]:
    """
    Função unificada de processamento de arquivos de ponto.
    
    Retorna:
      (lista_de_batidas, tipo_do_arquivo, tipo_identificador_predominante)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".txt":
        batidas = parse_afd_file(file_path, data_inicio=data_inicio, data_fim=data_fim)
        return batidas, "AFD_TXT", "PIS/CPF"
    elif ext in [".xlsx", ".xls", ".csv"]:
        batidas, id_type = parse_excel_or_csv(file_path, data_inicio=data_inicio, data_fim=data_fim)
        tipo_arq = "EXCEL_XLSX" if ext in [".xlsx", ".xls"] else "CSV"
        return batidas, tipo_arq, id_type
    else:
        raise ValueError(f"Extensão de arquivo não suportada: '{ext}'. Formatos válidos: .txt, .xlsx, .xls, .csv")
