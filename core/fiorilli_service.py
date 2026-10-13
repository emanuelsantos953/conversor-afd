import base64
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple, Any
from django.conf import settings

logger = logging.getLogger(__name__)

class FiorilliService:
    """
    Serviço de comunicação com a API SIPWebservices da Fiorilli Software.
    Permite:
      - Validar credenciais de operadores;
      - Consultar servidores ativos cadastrados no RH;
      - Enviar batidas individuais ou em lote para o endpoint POST /batidas.
    """

    def __init__(self, auth_token: Optional[str] = None, usuario: Optional[str] = None, senha: Optional[str] = None):
        self.base_url = getattr(
            settings,
            'FIORILLI_API_BASE_URL',
            'http://taquaritubasp4.dcfiorilli.com.br:8080/sipwebservices/api'
        ).rstrip('/')
        self.entidade = str(getattr(settings, 'FIORILLI_ENTIDADE_CODIGO', '001')).zfill(3)
        self.timeout = getattr(settings, 'FIORILLI_API_TIMEOUT', 10)

        if auth_token:
            self.auth_token = auth_token
        elif usuario and senha:
            self.auth_token = base64.b64encode(f"{usuario}:{senha}".encode('utf-8')).decode('ascii')
        else:
            self.auth_token = None

    @classmethod
    def from_request(cls, request) -> 'FiorilliService':
        """Instancia o serviço a partir da sessão ativa do operador logado."""
        token = None
        if request and hasattr(request, 'session'):
            token = request.session.get('fiorilli_auth_token')
        return cls(auth_token=token)

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ConversorAFD/1.0 (Fiorilli-Integrator)",
            "Connection": "close"
        }
        if self.auth_token:
            headers["Authorization"] = f"Basic {self.auth_token}"
        return headers

    def testar_conexao(self) -> Tuple[bool, str]:
        """Testa se as credenciais e conexão com a API da Fiorilli estão ativas."""
        if not self.auth_token:
            return False, "Nenhum token de autenticação disponível na sessão."
        url = f"{self.base_url}/trabalhadores/ativos/entidade/{self.entidade}?start=0&max=1"
        req = urllib.request.Request(url, headers=self._get_headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.getcode() == 200:
                    return True, "Conexão com a API Fiorilli ativa e autenticada."
                return False, f"Resposta HTTP {resp.getcode()} da Fiorilli."
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "Sessão expirada ou credenciais inválidas na Fiorilli (401 Unauthorized)."
            return False, f"Erro HTTP {e.code}: {e.reason}"
        except Exception as e:
            return False, f"Falha de conexão com a Fiorilli: {str(e)}"

    def obter_mapa_trabalhadores(self) -> Dict[str, str]:
        """
        Busca todos os trabalhadores ativos da entidade no SIP Fiorilli e cria
        um mapa de correlação: CPF / PIS / Matrícula -> Código de Registro Oficial SIP (6 dígitos).
        """
        if hasattr(self, '_mapa_trabalhadores') and self._mapa_trabalhadores:
            return self._mapa_trabalhadores

        mapa = {}
        if not self.auth_token:
            return mapa

        start = 0
        max_page = 200

        try:
            while True:
                ok, itens, _ = self.consultar_trabalhadores_ativos(max_registros=max_page, start=start)
                if not ok or not itens:
                    break

                for t in itens:
                    reg = str(t.get("registro", "")).strip().zfill(6)
                    if not reg or reg == "000000":
                        continue

                    cpf = ''.join(c for c in str(t.get("cpf", "")) if c.isdigit())
                    pis = ''.join(c for c in str(t.get("pis", "")) if c.isdigit())
                    matr = ''.join(c for c in str(t.get("matricula", "")) if c.isdigit())
                    nome = str(t.get("nome", "")).strip().upper()

                    if cpf:
                        mapa[cpf] = reg
                    if pis:
                        mapa[pis] = reg
                    if matr:
                        mapa[matr] = reg
                    if nome:
                        mapa[nome] = reg

                if len(itens) < max_page:
                    break
                start += max_page
        except Exception as e:
            logger.error(f"[FiorilliService] Erro ao carregar mapa de servidores SIP: {e}")

        self._mapa_trabalhadores = mapa
        return mapa

    def resolver_registro_sip(self, identificador: str = "", matricula: str = "", nome: str = "") -> Optional[str]:
        """
        Resolve o código de registro de 6 dígitos exigido pela API SIP Fiorilli a partir
        de qualquer dado disponível (CPF, PIS, Matrícula ou Nome).
        """
        id_limpo = ''.join(c for c in str(identificador) if c.isdigit())
        matr_limpa = ''.join(c for c in str(matricula) if c.isdigit())
        nome_up = str(nome).strip().upper()

        mapa = self.obter_mapa_trabalhadores()

        if id_limpo and id_limpo in mapa:
            return mapa[id_limpo]
        if matr_limpa and matr_limpa in mapa:
            return mapa[matr_limpa]
        if nome_up and nome_up in mapa:
            return mapa[nome_up]

        # Se já for um código com 6 dígitos
        if len(id_limpo) == 6:
            return id_limpo
        if len(matr_limpa) == 6:
            return matr_limpa

        return None

    def enviar_batida(
        self,
        registro: str,
        data_referencia: str,
        data_hora: str,
        tipo_batida: int = 1,
        tipo_coletor: str = "DISPOSITIVO_ELETRONICO",
        identificador_alternativo: str = "",
        nome_alternativo: str = ""
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Envia uma batida de ponto para o endpoint POST /batidas da Fiorilli.
        Resolve automaticamente o código de registro de 6 dígitos se necessário.
        Retorna (sucesso, mensagem, id_criado_ou_none).
        """
        if not self.auth_token:
            return False, "Operador não autenticado no SIP Fiorilli.", None

        # Resolve o registro de 6 dígitos oficial do SIP Fiorilli
        reg_efetivo = self.resolver_registro_sip(
            identificador=identificador_alternativo or registro,
            matricula=registro,
            nome=nome_alternativo
        )

        if not reg_efetivo:
            reg_efetivo = str(registro).zfill(6)

        # NORMALIZAÇÃO DO FORMATO DE DATA E HORA PARA A API JAVA DA FIORILLI
        # O backend Java do SIPWebservices utiliza SimpleDateFormat no padrão brasileiro ('dd-MM-yyyy').
        # Se enviado no padrão ISO 'yyyy-MM-dd', os dois primeiros dígitos são lidos como dia,
        # e o mês vira ano 0036! Portanto, convertemos estritamente para 'dd-MM-yyyy'.
        d_ref_str = str(data_referencia).strip()
        d_hora_str = str(data_hora).strip()

        # Normaliza data_referencia (esperado: dd-MM-yyyy)
        if len(d_ref_str) >= 10 and d_ref_str[4] == '-' and d_ref_str[7] == '-':
            partes_d = d_ref_str[:10].split('-')
            d_ref_str = f"{partes_d[2]}-{partes_d[1]}-{partes_d[0]}"
        elif '/' in d_ref_str:
            partes_d = d_ref_str[:10].split('/')
            if len(partes_d) == 3:
                if len(partes_d[0]) == 4:
                    d_ref_str = f"{partes_d[2]}-{partes_d[1]}-{partes_d[0]}"
                else:
                    d_ref_str = f"{partes_d[0]}-{partes_d[1]}-{partes_d[2]}"

        # Normaliza data_hora (esperado: dd-MM-yyyy HH:mm:ss)
        if len(d_hora_str) >= 10 and d_hora_str[4] == '-' and d_hora_str[7] == '-':
            partes_data = d_hora_str[:10].split('-')
            resto_hora = d_hora_str[10:].strip()
            if resto_hora and len(resto_hora) == 5:
                resto_hora = f"{resto_hora}:00"
            d_hora_str = f"{partes_data[2]}-{partes_data[1]}-{partes_data[0]} {resto_hora}".strip()
        elif '/' in d_hora_str:
            partes_dt = d_hora_str.split()
            partes_data = partes_dt[0].split('/')
            resto_hora = partes_dt[1] if len(partes_dt) > 1 else ""
            if resto_hora and len(resto_hora) == 5:
                resto_hora = f"{resto_hora}:00"
            if len(partes_data) == 3:
                if len(partes_data[0]) == 4:
                    d_hora_str = f"{partes_data[2]}-{partes_data[1]}-{partes_data[0]} {resto_hora}".strip()
                else:
                    d_hora_str = f"{partes_data[0]}-{partes_data[1]}-{partes_data[2]} {resto_hora}".strip()

        url = f"{self.base_url}/batidas"
        payload = {
            "entidadeCodigo": self.entidade,
            "registro": str(reg_efetivo).zfill(6),
            "dataHora": d_hora_str,
            "dataReferencia": d_ref_str,
            "tipoBatida": tipo_batida,
            "tipoColetor": tipo_coletor,
            "ip": "127.0.0.1",
            "latitude": 0.0,
            "longitude": 0.0
        }

        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data_bytes, headers=self._get_headers(), method='POST')

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode('utf-8')
                if status in (200, 201):
                    res_id = None
                    try:
                        res_id = int(body.strip())
                    except Exception:
                        pass
                    return True, "Batida registrada com sucesso no SIP Fiorilli.", res_id
                return False, f"HTTP {status}: {body[:150]}", None
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode('utf-8')
            except Exception:
                err_body = str(e.reason)

            # Tratamento de batida já existente
            if "já cadastrada" in err_body.lower() or "duplicad" in err_body.lower():
                return True, "Marcação já cadastrada no sistema da Fiorilli (ignorado duplicata).", None
            return False, f"Erro HTTP {e.code}: {err_body[:150]}", None
        except Exception as e:
            return False, f"Falha de comunicação: {str(e)}", None

    def consultar_trabalhadores_ativos(self, max_registros: int = 200, start: int = 0) -> Tuple[bool, List[Dict[str, Any]], str]:
        """Consulta os trabalhadores ativos da entidade no SIP Fiorilli."""
        url = f"{self.base_url}/trabalhadores/ativos/entidade/{self.entidade}?start={start}&max={max_registros}"
        req = urllib.request.Request(url, headers=self._get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.getcode() == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    itens = data.get("trabalhadores", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    return True, itens, "OK"
                elif resp.getcode() == 204:
                    return True, [], "Sem registros adicionais."
                return False, [], f"HTTP {resp.getcode()}"
        except Exception as e:
            return False, [], str(e)
