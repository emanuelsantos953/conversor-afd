import logging
from django.core.management.base import BaseCommand
from core.models import Funcionario, Grupo
from core.fiorilli_service import FiorilliService

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Sincroniza e substitui os grupos dos funcionários com os locais/grupos de ponto do SIP Fiorilli"

    def add_arguments(self, parser):
        parser.add_argument('--usuario', type=str, default='emanuel.santos', help='Usuário do SIP Fiorilli')
        parser.add_argument('--senha', type=str, default='xj3xxyr4cj', help='Senha do SIP Fiorilli')
        parser.add_argument('--limpar-vazios', action='store_true', help='Remove grupos antigos sem nenhum funcionário vinculado')

    def handle(self, *args, **options):
        usuario = options['usuario']
        senha = options['senha']
        limpar_vazios = options['limpar_vazios']

        self.stdout.write(self.style.NOTICE(f"Iniciando conexão com SIP Fiorilli via operador '{usuario}'..."))
        svc = FiorilliService(usuario=usuario, senha=senha)
        ok, msg = svc.testar_conexao()
        if not ok:
            self.stdout.write(self.style.ERROR(f"Falha na conexão com Fiorilli: {msg}"))
            return

        self.stdout.write(self.style.SUCCESS("Conexão com SIP Fiorilli estabelecida com sucesso!"))
        self.stdout.write("Buscando trabalhadores ativos do SIP...")

        start = 0
        max_page = 200
        trabalhadores_sip = []

        while True:
            ok, itens, err = svc.consultar_trabalhadores_ativos(max_registros=max_page, start=start)
            if not ok:
                self.stdout.write(self.style.WARNING(f"Aviso durante consulta: {err}"))
                break
            if not itens:
                break
            trabalhadores_sip.extend(itens)
            self.stdout.write(f"  > Carregados {len(trabalhadores_sip)} trabalhadores...")
            if len(itens) < max_page:
                break
            start += max_page

        self.stdout.write(self.style.SUCCESS(f"Total de trabalhadores ativos recuperados do SIP: {len(trabalhadores_sip)}"))

        # Carrega dados do banco
        funcionarios = list(Funcionario.objects.prefetch_related('grupos').all())
        mapa_matr = {f.matricula.strip(): f for f in funcionarios if f.matricula}
        mapa_cpf = {f.cpf.strip(): f for f in funcionarios if f.cpf}
        mapa_pis = {f.pis.strip(): f for f in funcionarios if f.pis}
        mapa_grupos = {g.nome: g for g in Grupo.objects.all()}

        total_atualizados = 0
        total_ja_certos = 0
        novos_grupos_criados = 0

        for t in trabalhadores_sip:
            reg = str(t.get("registro", "")).strip().zfill(6)
            if not reg or reg == "000000":
                continue

            cpf = ''.join(c for c in str(t.get("cpf", "")) if c.isdigit())
            pis = ''.join(c for c in str(t.get("pis", "")) if c.isdigit())
            matr = ''.join(c for c in str(t.get("matricula", "")) if c.isdigit())

            # Grupo vindo do SIP: Local de Trabalho (com fallback para Subdivisão)
            nome_grupo = (t.get("localTrabalhoNome") or t.get("subdivisaoNome") or "").strip()[:150]
            if not nome_grupo:
                continue

            if nome_grupo not in mapa_grupos:
                grupo_obj, criado = Grupo.objects.get_or_create(nome=nome_grupo)
                mapa_grupos[nome_grupo] = grupo_obj
                if criado:
                    novos_grupos_criados += 1
            else:
                grupo_obj = mapa_grupos[nome_grupo]

            func = (
                mapa_matr.get(reg) or
                (mapa_matr.get(matr) if matr else None) or
                (mapa_cpf.get(cpf) if cpf else None) or
                (mapa_pis.get(pis) if pis else None)
            )

            if func:
                grupos_atuais_ids = {g.id for g in func.grupos.all()}
                if grupos_atuais_ids != {grupo_obj.id}:
                    func.grupos.set([grupo_obj])
                    total_atualizados += 1
                else:
                    total_ja_certos += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Resultado da Sincronização de Grupos ---\n"
            f"Funcionários com grupos substituídos/atualizados: {total_atualizados}\n"
            f"Funcionários que já estavam no grupo correto: {total_ja_certos}\n"
            f"Novos grupos criados do SIP: {novos_grupos_criados}\n"
            f"Total de grupos existentes no sistema: {Grupo.objects.count()}"
        ))

        if limpar_vazios:
            removidos, _ = Grupo.objects.filter(funcionario__isnull=True).delete()
            self.stdout.write(self.style.NOTICE(f"Grupos órfãos/vazios removidos: {removidos}"))
