import threading

# Espaço na memória para guardar quem é o usuário da requisição atual
_local_storage = threading.local()

class UsuarioMiddleware:
    """ Espião que anota qual usuário está acessando a página agora """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local_storage.user = getattr(request, 'user', None)
        response = self.get_response(request)
        return response


class RoteadorApresentacao:
    """ Roteador que desvia os dados se o usuário for de teste """
    
    # Coloque aqui o login exato do usuário que você vai usar para testes
    USUARIO_TESTE = 'apresentacao'

    def db_for_read(self, model, **hints):
        # 1º - Se não for uma tabela do app 'core' (ex: tabela de usuários/login), ignora.
        if model._meta.app_label != 'core':
            return None
            
        # 2º - Como é uma tabela do Core, agora sim vemos quem é o usuário
        usuario = getattr(_local_storage, 'user', None)
        if usuario and usuario.is_authenticated and getattr(usuario, 'username', '') == self.USUARIO_TESTE:
            return 'banco_teste'
            
        return None

    def db_for_write(self, model, **hints):
        # Mesma regra para a gravação
        if model._meta.app_label != 'core':
            return None
            
        usuario = getattr(_local_storage, 'user', None)
        if usuario and usuario.is_authenticated and getattr(usuario, 'username', '') == self.USUARIO_TESTE:
            return 'banco_teste'
            
        return None

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == 'banco_teste':
            return app_label == 'core'
        return None