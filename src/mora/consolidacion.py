"""Consolidación de resultados de varios agentes (arquitectura multiagente, C12).

Consolidar no es concatenar:
1. Una sola respuesta, con una sección por área.
2. Una sola acción pendiente → una sola aprobación de la diseñadora.
3. Se eliminan operaciones idénticas propuestas dos veces.
4. Se avisa si dos agentes le escriben a la misma persona.
5. Cruce PLATA × TIEMPO: si se cobra/factura a un cliente cuya obra se atrasa en el mismo pedido, se avisa
   (el saldo suele ser "contra entrega").
6. Las fallas parciales quedan visibles: si un agente tuvo errores, el resto sigue.
"""
from __future__ import annotations

import json

from .contracts import AccionPendiente, Operacion, ResultadoAgente

AREA = {"comercial": "Comercial", "contenidos": "Contenidos", "administrativo": "Administración",
        "proyectos": "Proyectos"}
TOOLS_MENSAJE = {"enviar_mensaje", "enviar_recordatorio_cobro", "enviar_presupuesto"}
TOOLS_PLATA = {"emitir_factura", "enviar_recordatorio_cobro", "registrar_cobro"}
NIVEL = {"bajo": 0, "medio": 1, "alto": 2}


def _cliente_de_op(db, op: Operacion) -> str | None:
    a = op.args
    if a.get("cliente_id"):
        return a["cliente_id"]
    if a.get("cobro_id"):
        r = db.one("SELECT cliente_id FROM cobros WHERE id=?", (a["cobro_id"],))
        return r["cliente_id"] if r else None
    if a.get("hito_id"):
        r = db.one("SELECT o.cliente_id FROM hitos h JOIN obras o ON o.id=h.obra_id WHERE h.id=?", (a["hito_id"],))
        return r["cliente_id"] if r else None
    if a.get("obra_id"):
        r = db.one("SELECT cliente_id FROM obras WHERE id=?", (a["obra_id"],))
        return r["cliente_id"] if r else None
    return None


def _atrasa(db, op: Operacion) -> bool:
    if op.tool != "actualizar_hito":
        return False
    if op.args.get("estado") == "atrasado":
        return True
    h = db.one("SELECT fecha FROM hitos WHERE id=?", (op.args.get("hito_id"),))
    return bool(h and op.args.get("fecha") and str(op.args["fecha"]) > h["fecha"])


def consolidar(resultados: list[tuple[str, ResultadoAgente]], *, turno: int, version: int, db,
               cambios: dict[str, dict] | None = None) -> tuple[str, AccionPendiente | None, dict]:
    """Devuelve (respuesta, accion consolidada o None, metadatos para la traza)."""
    if len(resultados) == 1:
        agente, r = resultados[0]
        accion = r.accion
        if accion:
            accion = _aplicar_cambios(accion.model_copy(update={"version": version, "agentes": [agente]}), cambios)
        return r.respuesta, accion, {"agentes": [agente], "observaciones": 0}

    secciones, ops, observaciones, agentes_con_accion, resumenes = [], [], [], [], []
    vistos: set[str] = set()
    for agente, r in resultados:
        secciones.append(f"**{AREA[agente]}**\n{r.respuesta}")
        if r.errores:
            observaciones.append(f"{AREA[agente]} tuvo problemas: " + "; ".join(r.errores[:2]))
        if not r.accion:
            continue
        agentes_con_accion.append(agente)
        resumenes.append(r.accion.resumen)
        for op in r.accion.operaciones:
            clave = json.dumps([op.tool, op.args], sort_keys=True, default=str)
            if clave in vistos:
                observaciones.append(f"Se eliminó una operación duplicada ({op.tool}).")
                continue
            vistos.add(clave)
            ops.append(op.model_copy(update={"agente": op.agente or agente}))

    destinos: dict[str, int] = {}
    for op in ops:
        if op.tool in TOOLS_MENSAJE:
            destinos[op.args.get("destinatario", "")] = destinos.get(op.args.get("destinatario", ""), 0) + 1
    for dest, n in destinos.items():
        if n > 1:
            observaciones.append(f"Se enviarían {n} mensajes a {dest}: revisá si conviene unificarlos "
                                 "(podés editar los textos o modificar la propuesta).")

    plata = {_cliente_de_op(db, o) for o in ops if o.tool in TOOLS_PLATA} - {None}
    atrasos = {_cliente_de_op(db, o) for o in ops if _atrasa(db, o)} - {None}
    for cli in plata & atrasos:
        nombre = (db.one("SELECT nombre FROM clientes WHERE id=?", (cli,)) or {}).get("nombre", cli)
        observaciones.append(f"Ojo: en el mismo pedido se cobra/factura a {nombre} y se atrasa un hito de su "
                             "obra. Si el saldo es contra entrega, quizás convenga esperar.")

    respuesta = "\n\n".join(secciones)
    if observaciones:
        respuesta += "\n\n**Para revisar**\n" + "\n".join(f"- {o}" for o in observaciones)
    meta = {"agentes": [a for a, _ in resultados], "observaciones": len(observaciones), "operaciones": len(ops)}
    if not ops:
        return respuesta, None, meta

    specs_riesgo = []
    for _, r in resultados:
        if r.accion:
            specs_riesgo.append(r.accion.riesgo)
    accion = AccionPendiente(
        accion_id=f"t{turno}-multiagente" if len(agentes_con_accion) > 1 else f"t{turno}-{agentes_con_accion[0]}",
        agente="multiagente" if len(agentes_con_accion) > 1 else agentes_con_accion[0],
        resumen=" + ".join(resumenes), justificacion="Propuesta consolidada de: " + ", ".join(agentes_con_accion),
        operaciones=ops, riesgo=max(specs_riesgo, key=NIVEL.__getitem__),
        efecto_externo=any(r.accion.efecto_externo for _, r in resultados if r.accion),
        version=version, agentes=agentes_con_accion, observaciones=observaciones)
    return respuesta, _aplicar_cambios(accion, cambios), meta


def _aplicar_cambios(accion: AccionPendiente, cambios: dict[str, dict] | None) -> AccionPendiente:
    """Modificación estructurada de la diseñadora sobre la propuesta (índice global de operación)."""
    if not cambios:
        return accion
    ops = list(accion.operaciones)
    for idx, c in cambios.items():
        i = int(idx)
        if 0 <= i < len(ops):
            ops[i] = ops[i].model_copy(update={"args": {**ops[i].args, **c}})
    return accion.model_copy(update={"operaciones": ops})
