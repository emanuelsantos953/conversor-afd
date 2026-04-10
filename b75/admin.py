from django.contrib import admin
from .models import Cliente, Sorteio, Cartela, NumeroSorteado, Produto, Pedido, ItemPedido, LicencaUsuario

# ==========================================
# PAINEL DE LICENÇAS (SAAS)
# ==========================================
@admin.register(LicencaUsuario)
class LicencaUsuarioAdmin(admin.ModelAdmin):
    # Quais colunas vão aparecer na lista
    list_display = ('usuario', 'inicio', 'fim', 'ilimitado', 'status_licenca')
    # Filtros laterais
    list_filter = ('ilimitado',)
    # Barra de pesquisa
    search_fields = ('usuario__username', 'usuario__email')

    # Cria uma coluna visual bonitinha dizendo se está ativa ou não
    def status_licenca(self, obj):
        if obj.is_ativa():
            return "✅ ATIVA"
        return "❌ EXPIRADA"
    
    status_licenca.short_description = "Status Atual"

# ==========================================
# REGISTRO DOS OUTROS MODELOS NO PAINEL
# ==========================================
admin.site.register(Cliente)
admin.site.register(Sorteio)
admin.site.register(Cartela)
admin.site.register(NumeroSorteado)
admin.site.register(Produto)
admin.site.register(Pedido)
admin.site.register(ItemPedido)