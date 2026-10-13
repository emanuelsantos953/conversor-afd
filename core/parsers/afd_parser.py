import re
from datetime import datetime
from typing import List, Dict, Optional
from .validator import clean_digits, detect_identifier_type

def parse_afd_file(file_path: str, data_inicio: Optional[str] = None, data_fim: Optional[str] = None) -> List[Dict]:
    """
    Processa arquivo texto AFD (Portaria 1510 / Portaria 671 do MTE).
    Extrai as batidas (tipo 3) contendo PIS/CPF, data e hora.
    Se data_inicio e/ou data_fim forem informados (formato 'YYYY-MM-DD'),
    apenas as batidas dentro do período serão extraídas.
    """
    batidas = []

    # Tenta abrir com diferentes encodings usuais no Windows (latin-1, utf-8, cp1252)
    content = None
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.readlines()
            break
        except Exception:
            continue

    if content is None:
        raise ValueError(f"Não foi possível ler o arquivo {file_path}. Formato de texto incompatível.")

    # Regex para Portaria 671 (Posicional):
    # Exemplo: 00000000132025-09-09T15:08:52-030034832239830 D789
    # [0:9] NSR (9 dig)
    # [9] Tipo '3' (1 dig)
    # [10:34] Data/hora ISO 8601 (24 caracteres: AAAA-MM-DDTHH:MM:SS-HHMM ou similar)
    # [34:45] CPF (11 dig)
    pattern_671_pos = re.compile(
        r"^(\d{9})3(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)\s*(\d{11,12})"
    )

    for line_num, line in enumerate(content, start=1):
        line_clean = line.strip().lstrip("\ufeff")
        if not line_clean:
            continue

        # 1. Padrão Portaria 671 - Registro Tipo 3 (Posicional)
        # Exemplo: 00000000132025-09-09T15:08:52-030034832239830 D789
        m_671 = pattern_671_pos.match(line_clean)
        if m_671:
            try:
                nsr, dt_raw, ident = m_671.groups()
                try:
                    dt_obj = datetime.fromisoformat(dt_raw)
                except Exception:
                    dt_obj = datetime.strptime(dt_raw[:19], "%Y-%m-%dT%H:%M:%S")

                data_ref = dt_obj.strftime("%Y-%m-%d")
                if data_inicio and data_ref < data_inicio:
                    continue
                if data_fim and data_ref > data_fim:
                    continue

                data_hora = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                tipo_id = detect_identifier_type(ident)

                batidas.append({
                    "identificador": ident,
                    "tipo_identificador": tipo_id if tipo_id != "DESCONHECIDO" else "CPF",
                    "data_referencia": data_ref,
                    "data_hora": data_hora,
                    "tipo_batida": 1,
                    "nsr": nsr,
                    "linha": line_num
                })
                continue
            except Exception:
                pass

        # 2. Padrão Oficial Portaria 1510 - Registro Tipo 3 (Posicional)
        # Exemplo: 000000001302092026143012345678901
        # [0:9] NSR (9 dig)
        # [9] Tipo '3' (1 dig)
        # [10:18] Data DDMMAAAA (8 dig)
        # [18:22] Hora HHMM (4 dig)
        # [22:34] PIS (11 ou 12 dig)
        if len(line_clean) >= 33 and line_clean[9:10] == "3" and line_clean[:9].isdigit() and line_clean[10:18].isdigit() and line_clean[18:22].isdigit():
            try:
                nsr = line_clean[:9]
                dt_str = line_clean[10:18]  # DDMMAAAA
                hr_str = line_clean[18:22]  # HHMM
                pis_cpf = clean_digits(line_clean[22:34])

                dia = int(dt_str[0:2])
                mes = int(dt_str[2:4])
                ano = int(dt_str[4:8])
                hora = int(hr_str[0:2])
                minuto = int(hr_str[2:4])

                dt_obj = datetime(ano, mes, dia, hora, minuto, 0)
                data_ref = dt_obj.strftime("%Y-%m-%d")
                if data_inicio and data_ref < data_inicio:
                    continue
                if data_fim and data_ref > data_fim:
                    continue

                data_hora = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                tipo_id = detect_identifier_type(pis_cpf)

                batidas.append({
                    "identificador": pis_cpf,
                    "tipo_identificador": tipo_id if tipo_id != "DESCONHECIDO" else "PIS",
                    "data_referencia": data_ref,
                    "data_hora": data_hora,
                    "tipo_batida": 1,
                    "nsr": nsr,
                    "linha": line_num
                })
                continue
            except Exception:
                pass

        # 3. Padrão Portaria 671 / Relógios com separadores
        # Ex: NSR;3;02/09/2026;14:30;12345678901 ou NSR;3;2026-09-02T14:30:00-0300;12345678901
        if ";" in line_clean or "\t" in line_clean or "," in line_clean:
            sep = ";" if ";" in line_clean else ("\t" if "\t" in line_clean else ",")
            parts = [p.strip() for p in line_clean.split(sep)]
            if len(parts) >= 3:
                # Procura data, hora e PIS/CPF nas colunas
                found_dt = None
                found_hr = None
                found_id = None
                nsr = ""
                if parts[0].isdigit() and len(parts[0]) <= 9:
                    nsr = parts[0]

                for p in parts:
                    clean_p = clean_digits(p)
                    # Verifica se tem formato ISO completo
                    if "T" in p and not found_dt:
                        for iso_candidate in [p, p[:19]]:
                            try:
                                dt_cand = datetime.fromisoformat(iso_candidate)
                                found_dt = dt_cand.date()
                                found_hr = dt_cand.time()
                                break
                            except Exception:
                                pass
                    # Verifica se é data
                    elif ("/" in p or "-" in p) and not found_dt:
                        for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                            try:
                                dt_candidate = datetime.strptime(p, fmt)
                                found_dt = dt_candidate.date()
                                break
                            except ValueError:
                                pass
                    # Verifica se é hora
                    elif ":" in p and len(p) in (5, 8) and not found_hr:
                        try:
                            hr_candidate = datetime.strptime(p, "%H:%M:%S" if len(p) == 8 else "%H:%M").time()
                            found_hr = hr_candidate
                        except ValueError:
                            pass
                    # Verifica se é PIS/CPF
                    elif len(clean_p) in (11, 12, 14) and not found_id:
                        found_id = clean_p[:11]

                if found_dt and found_hr and found_id:
                    dt_full = datetime.combine(found_dt, found_hr)
                    data_ref = dt_full.strftime("%Y-%m-%d")
                    if data_inicio and data_ref < data_inicio:
                        continue
                    if data_fim and data_ref > data_fim:
                        continue

                    tipo_id = detect_identifier_type(found_id)
                    batidas.append({
                        "identificador": found_id,
                        "tipo_identificador": tipo_id if tipo_id != "DESCONHECIDO" else "PIS",
                        "data_referencia": data_ref,
                        "data_hora": dt_full.strftime("%Y-%m-%d %H:%M:%S"),
                        "tipo_batida": 1,
                        "nsr": nsr,
                        "linha": line_num
                    })

    return batidas
