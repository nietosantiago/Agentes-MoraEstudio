"""CLI de operación para el equipo de Mora Estudio.

  mora run data/solicitudes/01_lead_presupuesto.json   # corre hasta la aprobación humana
  mora show <run_id>                                     # ver propuesta pendiente / resultado
  mora decide <run_id> approve --actor sofia             # aprueba (también: reject, edit --cuerpo archivo.txt)
  mora events <run_id>                                   # event log del run
  mora demo                                              # corre todas las solicitudes de ejemplo

Cada comando es un proceso nuevo: el run se recupera desde el checkpointer SQLite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ROOT
from .service import MoraSystem, RunView


def _print_view(v: RunView) -> None:
    print(f"\nrun_id: {v.run_id}   status: {v.status}")
    c = v.state.get("clasificacion") or {}
    if c:
        print(f"intención: {c.get('intencion')} · urgencia: {c.get('urgencia')} · cliente: {c.get('cliente_id')} "
              f"· proyecto: {c.get('proyecto_id')} · plan: {v.state.get('plan_source')}")
    ar = v.approval_request
    if ar:
        r = ar["respuesta"]
        print(f"\n— PROPUESTA v{ar['version']} (hash {ar['proposal_hash']}) · estado {r['status']}"
              f"{' · ⚠ ESCALAR A HUMANO' if ar['escalar_a_humano'] else ''}")
        print(f"asunto: {r['asunto']}\n")
        print(r["answer"])
        print("\nfuentes:", ", ".join(r["sources"]) or "—")
        if r["missing_information"]:
            print("faltantes:", "; ".join(r["missing_information"]))
        if r["contradictions"]:
            print("contradicciones:", "; ".join(r["contradictions"]))
        crit = ar.get("critica") or {}
        print(f"revisor: {'OK' if crit.get('passed') else 'OBSERVACIONES'} {crit.get('critical_issues') or ''}")
        print("\nacciones propuestas:")
        for a in ar["acciones"]:
            args = {k: v for k, v in a["args"].items() if k not in ("cuerpo", "calculo")}
            print(f"  [{a['action_id']}] {a['tool']} (riesgo {a['risk_level']}) {args}")
        print(f"\n→ mora decide {v.run_id} approve|reject|edit --actor <nombre>")
    if v.resultados:
        print("\nresultados:")
        for r in v.resultados:
            print(f"  {r['action_id']}: {r['status']} {r['detail']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="mora", description="Sistema multiagente de Mora Estudio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run"); p.add_argument("archivo", type=Path)
    p = sub.add_parser("show"); p.add_argument("run_id")
    p = sub.add_parser("events"); p.add_argument("run_id")
    p = sub.add_parser("decide")
    p.add_argument("run_id"); p.add_argument("decision", choices=["approve", "reject", "edit"])
    p.add_argument("--actor", default="equipo"); p.add_argument("--comment", default="")
    p.add_argument("--cuerpo", type=Path, help="archivo con el texto editado de la respuesta (para edit)")
    p.add_argument("--solo", nargs="*", help="aprobar solo estos action_id")
    sub.add_parser("demo")
    a = ap.parse_args(argv)

    system = MoraSystem()
    if a.cmd == "run":
        _print_view(system.start(json.loads(a.archivo.read_text(encoding="utf-8"))))
    elif a.cmd == "show":
        _print_view(system.get(a.run_id))
    elif a.cmd == "events":
        for e in system.deps.ledger.events(a.run_id):
            print(json.dumps(e, ensure_ascii=False))
    elif a.cmd == "decide":
        v = system.get(a.run_id)
        if not v.approval_request:
            raise SystemExit(f"El run {a.run_id} no tiene una aprobación pendiente (status={v.status}).")
        _print_view(system.decide(a.run_id, {
            "decision": a.decision, "actor": a.actor, "comment": a.comment,
            "proposal_hash": v.approval_request["proposal_hash"],
            "edited_answer": a.cuerpo.read_text(encoding="utf-8") if a.cuerpo else None,
            "approved_action_ids": a.solo,
        }))
    elif a.cmd == "demo":
        for f in sorted((ROOT / "data" / "solicitudes").glob("*.json")):
            print("\n" + "=" * 80 + f"\n{f.name}")
            _print_view(system.start(json.loads(f.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
