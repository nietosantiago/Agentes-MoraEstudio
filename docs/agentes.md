# Fichas de agentes

Cada agente se define como `modelo + instrucciones + contexto + tools + contrato + límites + trazas` (C12). Los nombres sirven para expresar responsabilidades: no son personas.

## Recepción / Triage (Router) — `agents/triage.py`
- **Hace**: clasifica la intención (7 clases) y la urgencia, identifica al cliente y al proyecto en el repo, y extrae tipo de proyecto, m² y etapas.
- **No hace**: responder, ni decidir la identidad del cliente desde el texto del LLM.
- **Contexto**: solo la solicitud (delimitada como dato no confiable).
- **Salida**: `Clasificacion`.

## Supervisor — `agents/supervisor.py`
- **Hace**: descompone en ≤3 `WorkerTask`, define criterios de éxito y valida el plan (roles conocidos, ids únicos, dependencias sin ciclos, presupuesto).
- **No hace**: investigar, redactar ni ampliar su propio `RunBudget`.

| Intención | Workers |
|---|---|
| nuevo_lead | documental (servicios/proceso) + agenda (horarios) |
| consulta_proyecto | documental (informe + ficha) + agenda (hitos) |
| presupuesto | presupuestos (cálculo) + documental (condiciones) |
| agenda | agenda (horarios + propone evento) |
| documentacion | documental |
| reclamo | documental (desvíos) + agenda (próxima visita) → escalar |
| otro | documental (FAQ) |

## Documental (researcher) — `agents/workers.py::documental`
- **Tools**: `buscar_documentos`, `consultar_proyecto` (solo lectura).
- **Hace**: recupera evidencia con fuente y sección; si no alcanza, devuelve `partial` y no inventa.
- **Límite**: nunca devuelve documentos de otro proyecto.

## Agenda y vencimientos — `agents/workers.py::agenda`
- **Tools**: `listar_vencimientos`, `consultar_proyecto`. **Propone**: `crear_evento_agenda`.
- **Hace**: muestra los hitos del proyecto en los próximos 30 días y hasta 3 horarios libres (martes y jueves, 10 y 15 h).

## Presupuestos y reportes — `agents/workers.py::presupuestos`
- **Tools**: `calcular_honorarios` (determinístico, según el tarifario). **Propone**: `registrar_presupuesto`.
- **Hace**: arma el detalle por etapa, subtotal, IVA y total. Si faltan datos, devuelve `partial` con preguntas.
- **Límite**: no ofrece descuentos (`comprometer_descuento` es nivel 4).

## Atención (consolidador/redactor) — `agents/atencion.py`
- **Skill**: la selecciona según la intención (progressive disclosure).
- **Hace**: deduplica por `task_id`, cita fuentes, declara faltantes y contradicciones (por ejemplo, hitos vencidos sin cumplir) y marca `escalar_a_humano` en los reclamos. **Propone**: `enviar_respuesta`.
- **No hace**: consultar fuentes por su cuenta, ocultar fallas de los workers ni enviar.

## Revisor (critic) — `agents/critic.py`
- **Rúbrica**: firma, políticas (descuentos, garantías), montos iguales al cálculo, faltantes declarados, escalamiento de reclamos y longitud.
- **Límite**: `max_revisiones` (1 por defecto). Después pasa a revisión humana con las observaciones visibles.

## Humano del estudio (HITL)
- Ve la propuesta versionada (respuesta, fuentes, faltantes, crítica y acciones con riesgo).
- Decide **approve** (todo o algunas `approved_action_ids`), **edit** (genera una nueva versión que hay que volver a aprobar) o **reject**.
