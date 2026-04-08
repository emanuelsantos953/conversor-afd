class B75Router:
    """
    Um roteador para controlar todas as operações de banco de dados
    para o aplicativo B75 (Bingo).
    """
    route_app_labels = {'b75'}

    def db_for_read(self, model, **hints):
        """Tudo do app 'b75' lê do banco 'b75_db'."""
        if model._meta.app_label in self.route_app_labels:
            return 'b75_db'
        return None

    def db_for_write(self, model, **hints):
        """Tudo do app 'b75' grava no banco 'b75_db'."""
        if model._meta.app_label in self.route_app_labels:
            return 'b75_db'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """Permite relações se ambos forem do b75 ou ambos não forem."""
        if (
            obj1._meta.app_label in self.route_app_labels or
            obj2._meta.app_label in self.route_app_labels
        ):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Garante que as tabelas do b75 só sejam criadas no banco b75_db.
        """
        if app_label in self.route_app_labels:
            return db == 'b75_db'
        return None