import pytest
from pydantic import ValidationError

from mora.contracts import AccionPendiente, Operacion
from mora.tools import PolicyError


def test_agente_no_puede_usar_tools_de_otro(deps):
    with pytest.raises(PolicyError):
        deps.policy.call("proyectos", "cobros_pendientes", deps.tool_ctx, {})
    with pytest.raises(PolicyError):
        deps.policy.call("contenidos", "calcular_presupuesto", deps.tool_ctx, {"items": []})


def test_agente_no_puede_ejecutar_efectos_directo(deps):
    with pytest.raises(PolicyError):
        deps.policy.call("administrativo", "emitir_factura", deps.tool_ctx,
                         {"cliente_id": "CLI-02", "concepto": "x", "monto": 1})


def test_no_puede_proponer_tool_ajena_ni_nivel_4(deps):
    with pytest.raises(PolicyError):
        deps.policy.validar_operacion("comercial", Operacion(tool="emitir_factura", descripcion="x",
                                      args={"cliente_id": "CLI-02", "concepto": "xxx", "monto": 1}))
    with pytest.raises(PolicyError, match="no es delegable"):
        deps.policy.validar_operacion("administrativo", Operacion(tool="aplicar_descuento", descripcion="x",
                                      args={"presupuesto_id": "P", "porcentaje": 0.1}))


def test_presupuesto_usa_tabla_y_minimos(deps):
    r = deps.policy.call("administrativo", "calcular_presupuesto", deps.tool_ctx,
                         {"items": [{"servicio": "PRY-AMB", "cantidad": 2}, {"servicio": "REN-ADI", "cantidad": 3}]})
    assert r["total"] == 2 * 380000 + 3 * 45000 and r["sena_50"] == r["total"] / 2
    r2 = deps.policy.call("administrativo", "calcular_presupuesto", deps.tool_ctx,
                          {"items": [{"servicio": "PRY-INT", "cantidad": 30}]})
    assert r2["total"] == 1200000 and r2["lineas"][0]["aplica_minimo"]


def test_args_invalidos_y_servicio_inexistente(deps):
    with pytest.raises(ValidationError):
        deps.policy.call("administrativo", "calcular_presupuesto", deps.tool_ctx, {"items": [{"servicio": "X", "cantidad": -1}]})
    with pytest.raises(ValueError, match="inexistente"):
        deps.policy.call("administrativo", "calcular_presupuesto", deps.tool_ctx, {"items": [{"servicio": "NOPE", "cantidad": 1}]})


def _accion(op):
    return AccionPendiente(accion_id="t1-administrativo", agente="administrativo", resumen="x", operaciones=[op],
                           riesgo="alto", efecto_externo=True)


def test_precondicion_no_factura_dos_veces_el_mismo_cobro(deps):
    op = Operacion(tool="emitir_factura", descripcion="x",
                   args={"cliente_id": "CLI-03", "concepto": "Saldo", "monto": 450000, "cobro_id": "COB-03"})
    with pytest.raises(PolicyError, match="ya tiene factura"):
        deps.policy.autorizar(_accion(op), op, deps.tool_ctx, aprobada=True)


def test_precondicion_no_factura_de_mas(deps):
    op = Operacion(tool="emitir_factura", descripcion="x",
                   args={"cliente_id": "CLI-02", "concepto": "Saldo", "monto": 9_000_000, "cobro_id": "COB-02"})
    with pytest.raises(PolicyError, match="supera"):
        deps.policy.autorizar(_accion(op), op, deps.tool_ctx, aprobada=True)


def test_efecto_requiere_aprobacion(deps):
    op = Operacion(tool="emitir_factura", descripcion="x",
                   args={"cliente_id": "CLI-02", "concepto": "Saldo", "monto": 100, "cobro_id": "COB-02"})
    with pytest.raises(PolicyError, match="aprobación"):
        deps.policy.autorizar(_accion(op), op, deps.tool_ctx, aprobada=False)


def test_recordatorio_respeta_7_dias(deps):
    deps.db.execute("UPDATE cobros SET ultimo_recordatorio='2026-10-30' WHERE id='COB-02'")
    op = Operacion(tool="enviar_recordatorio_cobro", descripcion="x",
                   args={"cobro_id": "COB-02", "destinatario": "a@b.c", "canal": "email", "cuerpo": "x" * 30})
    with pytest.raises(PolicyError, match="7 días"):
        deps.policy.autorizar(_accion(op), op, deps.tool_ctx, aprobada=True)


def test_riesgo_y_efecto_los_define_el_registry(deps):
    riesgo, externo = deps.policy.clasificar("proyectos", [
        Operacion(tool="actualizar_hito", descripcion="x", args={"hito_id": "HIT-03", "estado": "cumplido"})])
    assert (riesgo, externo) == ("bajo", False)
    riesgo, externo = deps.policy.clasificar("administrativo", [
        Operacion(tool="emitir_factura", descripcion="x", args={"cliente_id": "CLI-02", "concepto": "xxx", "monto": 1})])
    assert (riesgo, externo) == ("alto", True)
