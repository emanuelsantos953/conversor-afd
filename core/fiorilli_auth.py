import base64
import logging
import urllib.request
import urllib.error
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User, Group
from django.conf import settings

logger = logging.getLogger(__name__)

class FiorilliBackend(BaseBackend):
    """
    Backend de autenticação integrado com a API SIPWebservices da Fiorilli Software.
    Valida as credenciais (login e senha) via HTTP Basic Authentication.
    
    Regras:
      1. Se a API Fiorilli validar com sucesso (HTTP 200):
         - Localiza ou cria o usuário correspondente no Django;
         - Concede acesso ao grupo 'Conversor';
         - Se for o administrador ('emanuel.santos'), concede is_staff e is_superuser;
         - Atualiza a senha local (hash seguro) para fallback de contingência;
         - Registra dados da sessão do operador para envio de batidas de ponto.
      2. Se as credenciais forem inválidas (HTTP 401):
         - Retorna None, passando para o próximo backend ou rejeitando o acesso.
      3. Se a API estiver inacessível (offline/timeout):
         - Retorna None, permitindo que o ModelBackend autentique usuários locais.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        username_clean = str(username).strip().lower()
        password_str = str(password)

        base_url = getattr(
            settings,
            'FIORILLI_API_BASE_URL',
            'http://taquaritubasp4.dcfiorilli.com.br:8080/sipwebservices/api'
        ).rstrip('/')
        entidade = str(getattr(settings, 'FIORILLI_ENTIDADE_CODIGO', '001')).zfill(3)
        timeout = getattr(settings, 'FIORILLI_API_TIMEOUT', 8)

        # Monta a requisição com HTTP Basic Authentication
        auth_string = f"{username_clean}:{password_str}"
        token = base64.b64encode(auth_string.encode('utf-8')).decode('ascii')
        url = f"{base_url}/trabalhadores/ativos/entidade/{entidade}?start=0&max=1"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Basic {token}")
        req.add_header("User-Agent", "ConversorAFD/1.0 (SIP-Auth)")

        fiorilli_ok = False
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.getcode() == 200:
                    fiorilli_ok = True
        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.info(f"[Fiorilli Auth] Falha 401 para o usuario '{username_clean}' (credencial invalida na Fiorilli).")
            else:
                logger.warning(f"[Fiorilli Auth] Erro HTTP {e.code} ao autenticar '{username_clean}': {e.reason}")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            logger.warning(f"[Fiorilli Auth] Conexão com API Fiorilli falhou ({e}). Tentando fallback local...")
            return None
        except Exception as e:
            logger.error(f"[Fiorilli Auth] Erro inesperado ao consultar API Fiorilli: {e}")
            return None

        if not fiorilli_ok:
            return None

        # Autenticação confirmada pela Fiorilli!
        try:
            user, created = User.objects.get_or_create(username=username_clean)
            
            # Sincroniza hash local para contingência caso a rede da Fiorilli oscile no futuro
            user.set_password(password_str)
            user.is_active = True

            # Garante grupo 'Conversor' para permissão no sistema
            grupo_conv, _ = Group.objects.get_or_create(name='Conversor')
            user.groups.add(grupo_conv)

            # Privilégios de Administrador Geral
            if username_clean == 'emanuel.santos':
                user.is_staff = True
                user.is_superuser = True

            user.save()

            # Vincula dados do operador autenticado na sessão HTTP (para envio futuro de ponto)
            if request and hasattr(request, 'session'):
                request.session['fiorilli_autenticado'] = True
                request.session['fiorilli_usuario'] = username_clean
                request.session['fiorilli_auth_token'] = token
                request.session['fiorilli_entidade'] = entidade

            logger.info(f"[Fiorilli Auth] Usuário '{username_clean}' autenticado com sucesso via API Fiorilli!")
            return user
        except Exception as e:
            logger.error(f"[Fiorilli Auth] Erro ao sincronizar usuario Django para '{username_clean}': {e}")
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
