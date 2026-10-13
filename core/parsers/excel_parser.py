import os
import re
from datetime import datetime, date, time
from typing import List, Dict, Tuple, Optional
import pandas as pd
from .validator import clean_digits, detect_identifier_type, is_matricula_candidate, validate_cpf

def _extract_datetime(val) -> Tuple[Optional[date], Optional[time]]:
    """
    Extrai data e/ou hora de uma célula, suportando objetos Timestamp, strings combinadas
    (ex: '31/08/2026 17:31:15') ou formatos separados.
    """
    if pd.isna(val) or val is None or str(val).strip() == "":
        return None, None

    # Se for Timestamp do pandas / datetime do Python
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date(), val.time()

    s = str(val).strip()

    # 1. Tenta formato Data + Hora combinados (ex: '31/08/2026 17:31:15' ou '2026-08-31 17:31:15')
    match_dt = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)', s)
    if match_dt:
        d_str, t_str = match_dt.groups()
        d_obj = _parse_date_str(d_str)
        t_obj = _parse_time_str(t_str)
        return d_obj, t_obj

    # 2. Tenta apenas Data
    d_obj = _parse_date_str(s)
    # 3. Tenta apenas Hora
    t_obj = _parse_time_str(s)

    return d_obj, t_obj

def _parse_date_str(s: str) -> Optional[date]:
    """Converte string de data em objeto date."""
    if not s:
        return None
    s = s.strip()
    for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d", "%d/%m"]:
        try:
            d = datetime.strptime(s.split()[0], fmt).date()
            if fmt == "%d/%m":
                d = d.replace(year=datetime.now().year)
            return d
        except ValueError:
            pass
    return None

def _parse_time_str(s: str) -> Optional[time]:
    """Converte string de hora em objeto time."""
    if not s:
        return None
    s = s.strip()
    match = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', s)
    if match:
        h, m, sec = match.groups()
        return time(int(h), int(m), int(sec) if sec else 0)
    
    clean_num = clean_digits(s)
    if len(clean_num) == 4:
        h, m = int(clean_num[:2]), int(clean_num[2:])
        if 0 <= h < 24 and 0 <= m < 60:
            return time(h, m, 0)
    return None

def _load_dataframe(file_path: str) -> pd.DataFrame:
    """Carrega o DataFrame suportando .xlsx, .xls (incluindo HTML/.xls) e .csv."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".xlsx", ".xls"]:
        try:
            return pd.read_excel(file_path, dtype=str)
        except Exception:
            try:
                tables = pd.read_html(file_path)
                if tables:
                    return tables[0].astype(str)
            except Exception:
                pass
            try:
                return pd.read_csv(file_path, sep=None, engine='python', dtype=str, on_bad_lines='skip')
            except Exception:
                return pd.read_excel(file_path, engine="xlrd" if ext == ".xls" else "openpyxl", dtype=str)

    elif ext == ".csv":
        sep = ";"
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                first_lines = "".join([f.readline() for _ in range(5)])
                if first_lines.count(";") < first_lines.count(","):
                    sep = ","
                elif first_lines.count("\t") > first_lines.count(";"):
                    sep = "\t"
        except Exception:
            sep = ";"
        return pd.read_csv(file_path, sep=sep, dtype=str, encoding="utf-8", on_bad_lines="skip")
    else:
        raise ValueError(f"Formato de arquivo não suportado: {ext}")

def parse_excel_or_csv(file_path: str, data_inicio: Optional[str] = None, data_fim: Optional[str] = None) -> Tuple[List[Dict], str]:
    """
    Processa arquivo Excel (.xlsx, .xls) ou CSV (.csv).
    Detecta automaticamente as colunas de Identificação (CPF vs Matrícula vs PIS),
    Data e Horários (mesmo quando data e hora estão na mesma coluna como '31/08/2026 17:31:15').
    Se data_inicio e/ou data_fim forem informados (formato 'YYYY-MM-DD'),
    apenas as batidas dentro do período serão extraídas.
    """
    df = _load_dataframe(file_path)

    if df.empty:
        return [], "DESCONHECIDO"

    df = df.dropna(how="all", axis=1)
    cols = list(df.columns)

    # 1. Identificar coluna do Colaborador (CPF, Matrícula, PIS, ID)
    # 1. Identificar coluna do Colaborador (CPF, Matrícula, PIS, ID)
    id_col = None
    predominant_type = "DESCONHECIDO"

    # 1.1 Procura colunas candidatas por cabeçalho
    candidate_cols = []
    for c in cols:
        c_str = str(c).strip().lower()
        if any(k in c_str for k in ["cpf", "doc", "documento"]):
            candidate_cols.insert(0, (c, "CPF"))
        elif any(k in c_str for k in ["pis", "pasep", "nis"]):
            candidate_cols.insert(0, (c, "PIS"))
        elif any(k in c_str for k in ["matricula", "matrícula", "mat", "cracha", "crachá", "re"]):
            candidate_cols.append((c, "MATRICULA"))
        elif any(k in c_str for k in ["codigo", "código", "id_func", "id", "registro", "identificador"]):
            candidate_cols.append((c, "AUTO"))

    # 1.2 Analisa o conteúdo real das células dos candidatos
    for c, hint in candidate_cols:
        sample_values = df[c].dropna().head(30).tolist()
        if not sample_values:
            continue
        total_s = len(sample_values)
        cpf_count = sum(1 for v in sample_values if detect_identifier_type(v, str(c)) == "CPF")
        mat_count = sum(1 for v in sample_values if detect_identifier_type(v, str(c)) == "MATRICULA")
        pis_count = sum(1 for v in sample_values if detect_identifier_type(v, str(c)) == "PIS")

        if cpf_count > 0 and cpf_count >= total_s * 0.4:
            id_col = c
            predominant_type = "CPF"
            break
        elif pis_count > 0 and pis_count >= total_s * 0.4:
            id_col = c
            predominant_type = "PIS"
            break
        elif mat_count > 0 and mat_count >= total_s * 0.4:
            id_col = c
            predominant_type = "MATRICULA"
            break
        elif hint in ("CPF", "MATRICULA", "PIS"):
            id_col = c
            predominant_type = hint
            break
        elif not id_col:
            id_col = c

    # 1.3 Se ainda não definiu com certeza, analisa todas as colunas
    if not id_col or predominant_type == "DESCONHECIDO":
        for c in cols:
            sample_values = df[c].dropna().head(30).tolist()
            if not sample_values:
                continue
            total_s = len(sample_values)
            cpf_count = sum(1 for v in sample_values if detect_identifier_type(v, str(c)) == "CPF")
            mat_count = sum(1 for v in sample_values if detect_identifier_type(v, str(c)) == "MATRICULA")
            pis_count = sum(1 for v in sample_values if detect_identifier_type(v, str(c)) == "PIS")

            if cpf_count >= total_s * 0.5 and cpf_count > 0:
                id_col = c
                predominant_type = "CPF"
                break
            elif mat_count >= total_s * 0.5 and mat_count > 0:
                id_col = c
                predominant_type = "MATRICULA"
                break
            elif pis_count >= total_s * 0.5 and pis_count > 0:
                id_col = c
                predominant_type = "PIS"
                break

    if not id_col and len(cols) > 0:
        id_col = cols[0]

    # 2. Identificar coluna de Nome (se houver)
    nome_col = None
    for c in cols:
        if c == id_col:
            continue
        c_str = str(c).strip().lower()
        if any(k in c_str for k in ["nome", "funcionario", "funcionário", "servidor", "colaborador", "empregado"]):
            nome_col = c
            break

    # 3. Identificar coluna separada de Data (se houver)
    date_col = None
    for c in cols:
        if c in (id_col, nome_col):
            continue
        c_str = str(c).strip().lower()
        if any(k in c_str for k in ["data", "dt_", "dia", "date"]) and not any(k in c_str for k in ["hora", "hr", "time"]):
            date_col = c
            break

    # 4. Identificar colunas de Horários / Batidas
    time_cols = []
    for c in cols:
        if c in (id_col, nome_col, date_col):
            continue
        c_str = str(c).strip().lower()
        if any(k in c_str for k in ["hora", "hr", "time", "entrada", "saida", "saída", "e1", "s1", "e2", "s2", "e3", "s3", "batida", "marcacao", "marcação", "horario", "horário"]):
            time_cols.append(c)

    if not time_cols:
        for c in cols:
            if c in (id_col, nome_col, date_col):
                continue
            sample = df[c].dropna().head(10).astype(str).tolist()
            if any(":" in s for s in sample):
                time_cols.append(c)

    batidas = []

    # Iteração sobre cada linha
    for idx, row in df.iterrows():
        id_val = row[id_col]
        if pd.isna(id_val) or str(id_val).strip() == "":
            continue

        raw_id_str = str(id_val).strip()
        tipo_linha = detect_identifier_type(raw_id_str, str(id_col))
        if tipo_linha == "DESCONHECIDO":
            tipo_linha = predominant_type if predominant_type != "DESCONHECIDO" else "MATRICULA"

        id_clean = clean_digits(raw_id_str)
        if not id_clean and not raw_id_str:
            continue

        if tipo_linha == "CPF" and len(id_clean) == 10:
            id_clean = id_clean.zfill(11)

        nome_func = str(row[nome_col]).strip() if nome_col and not pd.isna(row[nome_col]) else ""

        # Data padrão da linha (se houver coluna dedicada de data)
        d_from_date_col, _ = _extract_datetime(row[date_col]) if date_col else (None, None)

        if time_cols:
            seq_tipo = 1
            for t_col in time_cols:
                raw_time_val = row[t_col]
                d_from_time_col, t_obj = _extract_datetime(raw_time_val)
                
                # Se a própria célula de hora trouxe a data (ex: '31/08/2026 17:31:15'), usa ela prioritariamente!
                dt_final_date = d_from_time_col or d_from_date_col or date.today()

                if t_obj:
                    data_ref_str = dt_final_date.strftime("%Y-%m-%d")
                    if data_inicio and data_ref_str < data_inicio:
                        continue
                    if data_fim and data_ref_str > data_fim:
                        continue

                    dt_full = datetime.combine(dt_final_date, t_obj)
                    batidas.append({
                        "identificador": id_clean if tipo_linha in ("CPF", "PIS") else raw_id_str,
                        "tipo_identificador": tipo_linha,
                        "nome_sugerido": nome_func,
                        "data_referencia": data_ref_str,
                        "data_hora": dt_full.strftime("%Y-%m-%d %H:%M:%S"),
                        "tipo_batida": seq_tipo,
                        "coluna_origem": str(t_col),
                        "linha": idx + 2
                    })
                    seq_tipo += 1
        else:
            # Fallback para outras colunas
            for c in cols:
                if c in (id_col, nome_col, date_col):
                    continue
                d_cell, t_cell = _extract_datetime(row[c])
                if t_cell:
                    dt_final_date = d_cell or d_from_date_col or date.today()
                    data_ref_str = dt_final_date.strftime("%Y-%m-%d")
                    if data_inicio and data_ref_str < data_inicio:
                        continue
                    if data_fim and data_ref_str > data_fim:
                        continue

                    dt_full = datetime.combine(dt_final_date, t_cell)
                    batidas.append({
                        "identificador": id_clean if tipo_linha in ("CPF", "PIS") else raw_id_str,
                        "tipo_identificador": tipo_linha,
                        "nome_sugerido": nome_func,
                        "data_referencia": data_ref_str,
                        "data_hora": dt_full.strftime("%Y-%m-%d %H:%M:%S"),
                        "tipo_batida": 1,
                        "coluna_origem": str(c),
                        "linha": idx + 2
                    })

    return batidas, predominant_type
