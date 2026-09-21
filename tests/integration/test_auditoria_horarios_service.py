from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.horarios import AuditoriaHorarioSnapshot
from app.services import auditoria_horarios_service


class FakeSoftGuardClient:
    """Fake no formato cru do portal: `listar_horarios` devolve as linhas
    de horário da conta, e lista vazia é conta SEM horário."""

    def __init__(self, contas=None, horarios=None):
        self.contas = contas or []
        self.horarios = horarios or {}  # cue_iid -> list | Exception
        self.consultadas = []

    def listar_todas_contas(self, **kwargs):
        if isinstance(self.contas, Exception):
            raise self.contas
        return self.contas

    def listar_horarios(self, cue_iid, **kwargs):
        self.consultadas.append(str(cue_iid))
        resultado = self.horarios.get(str(cue_iid), [])
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


def _conta(cue_iid, numero, nome):
    return {"cue_iid": cue_iid, "cue_ncuenta": numero, "cue_cnombre": nome}


FAIXA = [{"hor_choraapertura": "06:00", "hor_choracierre": "18:00"}]


def test_conta_sem_linhas_cai_em_sem_horario(app):
    client = FakeSoftGuardClient(
        contas=[_conta("10", "95", "LOJA A"), _conta("11", "96", "LOJA B")],
        horarios={"10": FAIXA, "11": []},
    )

    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    assert [i.conta for i in resultado["sem"]] == ["96"]
    assert [i.conta for i in resultado["com"]] == ["95"]
    assert resultado["total"] == 2
    assert resultado["erros"] == 0


def test_resumo_da_faixa_acompanha_a_conta_com_horario(app):
    client = FakeSoftGuardClient(
        contas=[_conta("10", "95", "LOJA A")], horarios={"10": FAIXA}
    )

    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    assert resultado["com"][0].resumo == "1 faixa(s) 06:00–18:00"


def test_varre_a_base_inteira_sem_recorte(app):
    """Sem filtro nenhum: toda conta com `cue_iid` é consultada, seja ela
    comércio ou residência. Foi o pedido de quem opera a base."""
    client = FakeSoftGuardClient(
        contas=[
            _conta("10", "95", "LOJA"),
            _conta("11", "96", "CASA"),
            _conta("12", "97", "SÍTIO"),
        ],
        horarios={"10": FAIXA, "11": [], "12": []},
    )

    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    assert client.consultadas == ["10", "11", "12"]
    assert [i.conta for i in resultado["sem"]] == ["96", "97"]
    assert resultado["total"] == 3


def test_falha_numa_conta_nao_derruba_a_varredura(app):
    client = FakeSoftGuardClient(
        contas=[
            _conta("10", "95", "LOJA A"),
            _conta("11", "96", "LOJA B"),
            _conta("12", "97", "LOJA C"),
        ],
        horarios={"10": [], "11": SoftGuardError("portal recusou"), "12": FAIXA},
    )

    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    assert [i.conta for i in resultado["sem"]] == ["95"]
    assert [i.conta for i in resultado["com"]] == ["97"]
    assert resultado["erros"] == 1
    assert client.consultadas == ["10", "11", "12"]


def test_falha_ao_listar_contas_aborta_com_erro_proprio(app):
    client = FakeSoftGuardClient(contas=SoftGuardError("portal fora"))

    try:
        auditoria_horarios_service.auditar(config=app.config, softguard_client=client)
    except auditoria_horarios_service.AuditoriaHorariosError as exc:
        assert "portal fora" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("deveria ter levantado AuditoriaHorariosError")


def test_conta_sem_id_interno_e_ignorada(app):
    """Sem `cue_iid` não há como consultar horário — melhor pular do que
    contar como auditada."""
    client = FakeSoftGuardClient(
        contas=[{"cue_ncuenta": "95", "cue_cnombre": "SEM ID"}, _conta("10", "96", "LOJA")],
        horarios={"10": []},
    )

    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    assert resultado["total"] == 1
    assert [i.conta for i in resultado["sem"]] == ["96"]


def test_busca_recorta_sem_varrer_a_base_toda(app):
    """O filtro por nome existe para reconferir um cliente — e tem que
    evitar a consulta, não só esconder o resultado depois."""
    client = FakeSoftGuardClient(
        contas=[_conta("10", "95", "VILLEFORT TROPICAL"), _conta("11", "96", "PADARIA")],
        horarios={"10": [], "11": []},
    )

    resultado = auditoria_horarios_service.auditar(
        config=app.config, busca="villefort", softguard_client=client
    )

    assert client.consultadas == ["10"]
    assert [i.conta for i in resultado["sem"]] == ["95"]


def test_snapshot_guarda_contadores_e_itens(app):
    client = FakeSoftGuardClient(
        contas=[_conta("10", "95", "LOJA A"), _conta("11", "96", "LOJA B")],
        horarios={"10": [], "11": FAIXA},
    )
    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    auditoria_horarios_service.salvar_snapshot(resultado)
    db.session.commit()

    snapshot = auditoria_horarios_service.ultimo_snapshot()
    assert snapshot.sem == 1
    assert snapshot.com == 1
    assert snapshot.total == 2

    recarregado = auditoria_horarios_service.resultado_do_snapshot(snapshot)
    assert [i.conta for i in recarregado["sem"]] == ["95"]
    assert recarregado["com"][0].resumo == "1 faixa(s) 06:00–18:00"


def test_sem_snapshot_o_resultado_e_nulo(app):
    assert AuditoriaHorarioSnapshot.query.count() == 0
    assert auditoria_horarios_service.resultado_do_snapshot(None) is None


def test_auditoria_registra_so_contadores(app, admin_user):
    from app.models.audit import AuditLog

    client = FakeSoftGuardClient(
        contas=[_conta("10", "95", "LOJA SIGILOSA")], horarios={"10": []}
    )
    resultado = auditoria_horarios_service.auditar(config=app.config, softguard_client=client)

    auditoria_horarios_service.registrar_auditoria(resultado, user=admin_user)
    db.session.commit()

    entrada = AuditLog.query.filter_by(action="auditoria_horarios").one()
    assert len(entrada.action) <= 48
    assert entrada.details == {"total": 1, "sem": 1, "com": 0, "erros": 0}
    assert "LOJA SIGILOSA" not in str(entrada.details)
