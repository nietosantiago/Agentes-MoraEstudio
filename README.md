# Agentes Mora Estudio

Sistema multiagente para **Mora Estudio** (diseño y arquitectura). Atiende consultas de clientes, busca en la documentación del estudio, gestiona agenda y vencimientos y prepara presupuestos de honorarios. **Nada sale del estudio sin aprobación humana.**

Stack: Python · LangGraph · Pydantic · Gemini (opcional) · SQLite. El diseño sigue los patrones del curso ITBA *AI Agent Developer* (ver [`docs/arquitectura.md`](docs/arquitectura.md)).

```
solicitud ─► triage (Router) ─► supervisor ─┬─► documental ──┐
                                            ├─► agenda ──────┼─► atención (Skill) ⇄ crítico ─► 👤 aprobación ─► policy ─► ejecutar (idempotente) ─► memoria
                                            └─► presupuestos ┘
```

## Inicio rápido

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

### Operar un caso (modo local, sin API key)

```bash
mora run data/solicitudes/01_lead_presupuesto.json
```

Muestra el borrador, las fuentes, la crítica y las acciones propuestas, más el `run_id`. Después, desde **otro proceso**:

```bash
mora decide <run_id> approve --actor sofia
```

Otras opciones: `reject`, `edit --cuerpo nuevo.txt` (genera la versión 2 y pide aprobarla de nuevo) y `--solo enviar-respuesta-1` (aprobación parcial). `mora events <run_id>` muestra el event log y `mora demo` corre los 4 casos de ejemplo.

Los efectos se simulan en `data/runtime/` (`outbox.jsonl`, `agenda_nuevos_eventos.jsonl`, `presupuestos.jsonl`) hasta conectar Gmail/Calendar vía MCP (Fase 3).

### Con Gemini
En `.env`: `MORA_LLM=gemini` y `GEMINI_API_KEY=...`. Si el LLM falla, triage, supervisor y redactor vuelven al modo determinístico.

## Estructura

| Ruta | Contenido |
|---|---|
| `src/mora/contracts.py` | Contratos Pydantic entre agentes, runtime y humanos |
| `src/mora/graph.py` | Orquestación LangGraph (fan-out/fan-in, crítico, HITL, policy, ejecución) |
| `src/mora/service.py` | Fachada `start / get / decide` con checkpointer SQLite |
| `src/mora/agents/` | triage, supervisor, workers, atención, crítico |
| `src/mora/tools/` | Registry, Policy Gate, niveles de autonomía, handlers |
| `src/mora/runtime/ledger.py` | Idempotencia de efectos + event log |
| `src/mora/memory/` | Memoria por cliente con provenance y TTL |
| `skills/` | Agent Skills (`SKILL.md`) del estudio |
| `data/` | Datos de ejemplo: clientes/proyectos, tarifario, agenda, documentos, solicitudes |
| `docs/` | [Arquitectura](docs/arquitectura.md) · [Agentes](docs/agentes.md) · [Roadmap](docs/roadmap.md) |
