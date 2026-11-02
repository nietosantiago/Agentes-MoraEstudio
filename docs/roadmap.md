# Roadmap

## Fase 0 — Diseño + runtime offline ✅ (este commit)
- Contratos, Tool Registry + Policy, workers, supervisor, consolidador, crítico.
- Grafo LangGraph con fan-out/fan-in, HITL (`interrupt`), checkpoints SQLite, ledger idempotente, memoria y Skills.
- CLI operativa y 35 tests (modo determinístico, sin API key).

## Fase 1 — Gemini real + evaluación (C2, C4, C6)
- Correr `MORA_LLM=gemini` sobre un dataset de 30–50 solicitudes reales anonimizadas (`data/eval/`).
- Medir routing accuracy, aprobación sin edición, latencia y tokens. Comparar contra el **baseline de agente único**.
- Benchmark de un modelo local (Ollama) para el triage: privacidad y costo (C4).

## Fase 2 — Documentos reales (C5–C8)
- Ingesta desde la carpeta de proyectos de Google Drive (memorias, informes, contratos), con `proyecto_id` en la metadata.
- Embeddings + Qdrant local detrás de `Retriever`; hybrid BM25 + vectorial con RRF; re-ranking.
- Dataset de relevancia y métricas Precision@k, Recall@k y MRR.

## Fase 3 — Integraciones vía MCP (C13)
- `enviar_respuesta` → Gmail (borrador primero, envío después de aprobar) / WhatsApp Business.
- `crear_evento_agenda` → Google Calendar.
- `registrar_presupuesto` → Google Sheets/CRM.
- Exponer el sistema como **servidor MCP** (`start_run`, `get_run`, `decide`) para operarlo desde Claude.

## Fase 4 — Producción
- API FastAPI + UI de bandeja de aprobaciones para el equipo.
- Checkpointer Postgres, colas por canal, observabilidad (traces por `run_id`) y alertas de vencimientos (job diario).
- Reporte semanal automático por proyecto (agente de reportes, con aprobación).
