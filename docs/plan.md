# Plan de trabajo y pendientes

Al **2/11/2026** (Clase 10), con entrega el **16/12/2026**. Regla: profundidad antes que ancho, siempre con algo que funcione de punta a punta.

## Estado del cronograma

| Semana | Foco | Estado |
|---|---|---|
| 1 | Material del estudio + base cargada + skill de marca | 🟡 Estructura lista (esquema, seed de ejemplo, Skill con valores **provisorios**). **Falta el material real de la clienta** |
| 2 | Grafo mínimo + 1 agente + revisión humana + ejecutor + checkpointing | ✅ Hecho, con los 4 agentes (modo local) |
| 3 | Dataset de evaluación del router + logging de costo y latencia | 🟡 Herramienta y trazas listas; **falta el dataset real** |
| 4 | Agentes 2, 3 y 4 + integración de facturación | 🟡 Agentes hechos (local). Facturación con mock: **falta elegir la API** |
| 5 | Interfaz FastAPI + Docker + README | 🟡 API, UI y README hechos. Docker escrito pero **no probado** (no había daemon de Docker en el entorno) |
| 6 | Ajuste fino, documentación, defensa | ⏳ |

Como el código va adelantado, conviene usar el margen en lo que pesa en la nota y depende de la clienta: **material real, dataset real y prueba con Gemini**.

**Punto de control (fin de la semana 3):** si el modo Gemini o la facturación real se complican, se presenta en modo local con la evaluación completa. El orden de descarte sigue siendo: primero contenidos, después proyectos.

## Pendientes del contexto (§9)

| Pendiente | Estado |
|---|---|
| Juntar material real: marca, precios, presupuestos viejos, consultas típicas | ⏳ **Depende de la clienta, arrancar ya.** Dónde va cada cosa: `skills/identidad-marca/` (marca, pilares, criterios), `data/seed/servicios.json` (precios), `eval/dataset_router.jsonl` (consultas) |
| Dataset de evaluación (30–40 consultas reales, con limítrofes admin/proyectos) | 🟡 Formato y evaluador listos; dataset semilla de 36 casos |
| Dónde vive el estado de cada obra y con qué tool se consulta | ✅ Tablas `obras`, `hitos`, `eventos`; tools `consultar_obra`, `proximos_hitos`, `actualizar_hito` |
| Definir la skill de identidad de marca | 🟡 Estructura y valores provisorios marcados `[COMPLETAR]` |
| Elegir API de facturación | ⏳ Interfaz `FacturacionProvider` lista. Candidatas: AFIP SDK (homologación), TusFacturasAPP, Facturante |
| Definir qué acciones cuentan como "efecto externo" | ✅ Propuesta en [`arquitectura.md` §5](arquitectura.md#5-qué-cuenta-como-efecto-externo-resuelve-el-pendiente-9). Validar con la clienta |

## Próximos pasos concretos
1. Pedirle a la clienta: lista de precios real, 30–40 mensajes reales (de leads, de clientes y pedidos que ella misma se hace), tono y paleta, y 3 presupuestos viejos.
2. Cargar ese material, etiquetar el dataset y correr `mora eval-router` en los modos local y gemini.
3. Probar los 4 agentes con Gemini sobre los pedidos reales y ajustar los prompts de frontera.
4. Elegir la API de facturación e implementar `FacturacionProvider` en homologación.
5. Probar `docker compose up` en una máquina con Docker y desplegar Postgres en Supabase.
