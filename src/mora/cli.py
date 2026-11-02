"""CLI.

  mora serve                     # API + UI en http://localhost:8000
  mora chat [--cliente CLI-02]   # conversación por terminal con aprobación interactiva
  mora eval-router               # evalúa el router sobre eval/dataset_router.jsonl
  mora reset-db                  # vuelve la base a los datos de ejemplo
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ROOT, load_settings


def _chat(cliente: str | None) -> None:
    from .service import MoraService

    svc = MoraService()
    th = svc.nueva_conversacion(cliente)
    print(f"Conversación {th}. Escribí tu pedido (vacío para salir).")
    while True:
        texto = input("\n> ").strip()
        if not texto:
            return
        v = svc.enviar(th, texto)
        while True:
            print(f"\n[{v['router']['agente']} · conf {v['router']['confianza']}] {v['mensajes'][-1]['texto']}")
            p = v["pendiente"]
            if not p:
                break
            if p["tipo"] == "aclaracion":
                print(p["pregunta"], "Opciones:", ", ".join(p["opciones"]))
                v = svc.aclarar(th, input("agente> ").strip() or None)
                continue
            a = p["accion"]
            print(f"\n== {a['resumen']} · riesgo {a['riesgo']} · {'EXTERNO' if a['efecto_externo'] else 'interno'} · v{a['version']}")
            for i, o in enumerate(a["operaciones"]):
                print(f"  {i}. {o['descripcion']}\n     {json.dumps(o['args'], ensure_ascii=False)[:400]}")
            op = input("[a]probar / [m]odificar / [r]echazar > ").strip().lower()[:1]
            d = {"a": "aprobado", "m": "modificado", "r": "rechazado"}.get(op, "rechazado")
            corr = input("corrección> ") if d == "modificado" else ""
            v = svc.decidir(th, {"decision": d, "accion_hash": p["accion_hash"], "correccion": corr})
        r = v["resumen_turno"]
        print(f"   (traza: {' → '.join(r['nodos'])} · {r['latencia_ms']} ms · {r['tokens_in']}/{r['tokens_out']} tok · US$ {r['costo_usd']})")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="mora")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8000)
    p = sub.add_parser("chat"); p.add_argument("--cliente")
    p = sub.add_parser("eval-router")
    p.add_argument("--dataset", type=Path, default=ROOT / "eval" / "dataset_router.jsonl")
    p.add_argument("--out", type=Path, default=ROOT / "eval" / "reports")
    sub.add_parser("reset-db")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("mora.api:app", host=a.host, port=a.port)
    elif a.cmd == "chat":
        _chat(a.cliente)
    elif a.cmd == "eval-router":
        from .evaluation.router_eval import cargar_dataset, evaluar, guardar, reporte_markdown
        from .llm import get_provider

        s = load_settings()
        r = evaluar(cargar_dataset(a.dataset), s, get_provider(s))
        pj, pm = guardar(r, a.out)
        print(reporte_markdown(r))
        print(f"\nGuardado: {pm} y {pj}")
    elif a.cmd == "reset-db":
        from .db import Database

        s = load_settings()
        db = Database(s)
        db.init_schema()
        db.reset()
        db.seed(s.seed_dir)
        print(f"Base reiniciada ({db.kind}).")


if __name__ == "__main__":
    main()
