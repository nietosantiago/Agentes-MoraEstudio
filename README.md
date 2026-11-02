# Mora Estudio — sistema multiagente para un estudio de interiorismo

Proyecto real para una diseñadora de interiores que trabaja sola (Santa Fe) y **Trabajo Final Integrador** del curso *Python Profesional, LLMs y APIs*. Un router interpreta el pedido en lenguaje natural y lo deriva a uno de cuatro agentes especializados. **Ninguna acción con efecto externo se ejecuta sin la aprobación de la diseñadora.**

```
carga de contexto → router ─┬─ comercial       (leads)
   (marca + cliente)   │    ├─ contenidos      (redes)
                       │    ├─ administrativo  (PLATA: presupuestos, facturas, cobros)
            confianza baja  └─ proyectos       (TIEMPO: hitos, entregables, plazos)
                       ↓              ↓ ¿acción con efecto?  no → fin
                  aclaración    revisión humana (interrupt) ── modificado → vuelve al agente
                                      ↓ aprobado          └─ rechazado → fin
                                  ejecutor (policy + idempotencia)
```

Stack: Python · LangGraph · Pydantic · Gemini (opcional) · FastAPI · PostgreSQL/Supabase (o SQLite en desarrollo).

## Inicio rápido (sin API key)

Requiere **Python 3.11 a 3.14** (probado con 3.13). Con 3.15 algunas dependencias todavía no tienen versión precompilada y en Windows piden Visual C++. En Windows, creá el entorno con `py -3.13 -m venv .venv` y activalo con `.venv\Scripts\Activate.ps1`.


```bash
python -m venv .venv && source .venv/bin/activate
```
```bash
pip install -e ".[dev]"
```
```bash
cp .env.example .env
```
```bash
pytest -q
```
```bash
MORA_HOY=2026-11-02 mora serve
```

Abrí http://localhost:8000, elegí un cliente y probá:
- "¿Qué entregas tengo esta semana?" (informativo: no pide aprobación)
- "Facturale el saldo a Martín Gómez" (riesgo alto: Aprobar / Modificar / Rechazar)
- "Se atrasaron los muebles de cocina de Gómez, pasalo al 25/11 y avisale"
- "Armame el calendario de posts de diciembre"
- "¿Cuándo?" (confianza baja: pide aclaración)

También por terminal:
```bash
mora chat --cliente CLI-02
```

`MORA_HOY` fija la fecha de los datos de ejemplo. `mora reset-db` vuelve la base al estado inicial.

## Con Gemini
En `.env`: `MORA_LLM=gemini` y `GEMINI_API_KEY=...`. El router usa structured output y los agentes, un agent loop con sus tools. Si el LLM falla, todo cae al modo local y queda registrado en la traza.

## Con Postgres / Supabase
En `.env`: `MORA_DATABASE_URL=postgresql://...`. El esquema y los checkpoints (`PostgresSaver`) se crean solos. Con Docker:
```bash
docker compose up --build
```

## Evaluación
```bash
mora eval-router
```
Genera `eval/reports/router_<modo>_<fecha>.md` con accuracy, aclaraciones, **errores con confianza**, limítrofes, matriz de confusión, latencia, tokens y costo. Ver [`docs/evaluacion.md`](docs/evaluacion.md).

## Cobertura de la rúbrica

| # | Requisito | Dónde |
|---|---|---|
| 1 | Capacidad agéntica (≥2 tools, maneja errores) | Router + 4 agentes con 2–6 tools cada uno; errores como observación; loop LLM con límite de pasos (`agents/base.py`) |
| 2 | Skill reutilizable | `skills/identidad-marca/` (todos los agentes; referencias a demanda) |
| 3 | Estado y memoria | `EstadoEstudio` + checkpointing en Postgres/SQLite, varios turnos por conversación (`graph.py`, `service.py`) |
| 4 | Human-in-the-Loop | `interrupt()` en `revision` y `aclaracion`; aprobar, modificar (con nueva versión) o rechazar; hash de versión |
| 5 | Integración externa | Facturación (`integrations/facturacion.py`, mock por ahora), Postgres/Supabase, Gemini |
| 6 | Interfaz accesible | FastAPI + UI (`api.py`, `static/index.html`) |
| 7 | Ejecución reproducible | `pyproject.toml`, `.env.example`, `Dockerfile`, `docker-compose.yml`, seed de datos, modo local sin API key |
| 8 | Evidencia de calidad | `eval/` + `mora eval-router`; trazas de tokens, costo y latencia por nodo; 43 tests |

## Documentación
- [`docs/contexto_tfi.md`](docs/contexto_tfi.md): contexto, alcance y rúbrica (fuente de verdad)
- [`docs/arquitectura.md`](docs/arquitectura.md): capas, grafo, estado, decisiones, efecto externo, ejecución segura
- [`docs/agentes.md`](docs/agentes.md): agentes, tools, niveles y riesgos
- [`docs/evaluacion.md`](docs/evaluacion.md): dataset, métricas y resultado actual
- [`docs/plan.md`](docs/plan.md): cronograma, estado y pendientes

> Los datos de `data/seed/` (clientes, obras, precios) y los valores de la Skill de marca son **de ejemplo**. Hay que reemplazarlos por el material real de la clienta.
