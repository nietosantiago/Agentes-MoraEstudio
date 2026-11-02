# Agentes y tools

Un agente = instrucciones (frontera + identidad de marca) + **sus** tools + contrato `ResultadoAgente` + límites. Todos leen la misma base y la misma Skill de marca.

## Router — `agents/router.py`
- Salida: `DecisionRouter{agente, confianza, justificacion, metodo}`.
- Modo LLM: prompt con la frontera explícita y ejemplos limítrofes ("¿Cuándo me paga Gómez?" → administrativo; "¿Cuándo entrego los renders de Gómez?" → proyectos).
- Modo reglas: señales ponderadas por dominio; `confianza = s1 / (s1 + s2 + 0,8)`, así que si dos dominios compiten la confianza baja y se pregunta.

## Frontera crítica: administrativo = PLATA, proyectos = TIEMPO
Está escrita en el prompt del router y en la `frontera` de cada agente, y el código la refuerza: proyectos **no tiene** tools de cobros y administrativo **no tiene** tools de hitos. El dataset de evaluación incluye 7 casos limítrofes entre estos dos agentes.

## Comercial — `agents/comercial.py`
Calificación y seguimiento de leads. No da precios (eso es de administrativo).

| Tool | Tipo | Nivel | Riesgo |
|---|---|---|---|
| `buscar_contacto` | lectura | 1 | bajo |
| `listar_leads` | lectura | 1 | bajo |
| `calificar_lead` (A/B/C: zona, presupuesto, tipo de proyecto) | lectura | 1 | bajo |
| `consultar_servicios` (sin precios) | lectura | 1 | bajo |
| `registrar_lead` | interna | 2 | bajo |
| `enviar_mensaje` | **externa** | 3 | medio |

Pedidos típicos: "Me escribió Carla por Instagram: '…'" → califica, registra y redacta la respuesta. "Haceme el seguimiento de los leads que no contestaron" → lista los leads con más de 5 días sin contacto y prepara un mensaje para cada uno.

## Contenidos — `agents/contenidos.py`
Calendario editorial y borradores (copy, hashtags y **brief visual en texto**; no genera imágenes). Solo usa obras marcadas como `publicable`.

| Tool | Tipo | Nivel | Riesgo |
|---|---|---|---|
| `calendario_contenidos`, `pilares_contenido`, `obras_publicables`, `consultar_servicios` | lectura | 1 | bajo |
| `programar_posts` | **externa** | 3 | medio |

Pedidos típicos: "Armame el calendario de posts de diciembre" (martes y viernes, rotando pilares) o "Un reel con tips de iluminación".

## Administrativo — `agents/administrativo.py` (PLATA)

| Tool | Tipo | Nivel | Riesgo |
|---|---|---|---|
| `consultar_precios`, `calcular_presupuesto`, `resumen_facturacion`, `cobros_pendientes`, `buscar_contacto` | lectura | 1 | bajo |
| `registrar_cobro` | interna | 2 | bajo |
| `enviar_presupuesto` | **externa** | 3 | medio |
| `enviar_recordatorio_cobro` (precondición: 7 días) | **externa** | 3 | medio |
| `emitir_factura` (precondiciones: no duplicar, no exceder) | **externa** | 3 | **alto** |
| `aplicar_descuento` | — | **4** | no delegable |

Pedidos típicos: "¿Cuánto facturé en octubre?" (informativo), "¿Quién me debe plata?", "Facturale el saldo a Martín Gómez", "Presupuesto para Sofía: 2 ambientes y 3 renders", "Mandale un recordatorio de pago a Gómez".

## Gestión de proyectos — `agents/proyectos.py` (TIEMPO)

| Tool | Tipo | Nivel | Riesgo |
|---|---|---|---|
| `listar_obras`, `consultar_obra`, `proximos_hitos`, `buscar_contacto` | lectura | 1 | bajo |
| `actualizar_hito` | interna | 2 | bajo |
| `enviar_mensaje` (aviso al cliente) | **externa** | 3 | medio |
| `agendar_evento` (invita al cliente) | **externa** | 3 | medio |

Pedidos típicos: "¿Qué entregas tengo esta semana?", "¿Cómo va la obra de Valentina?", "Se atrasaron los muebles de Gómez, pasalo al 25/11 y avisale", "Marcá como cumplida la planta de equipamiento".

## Dónde vive el estado de cada obra (resuelve el pendiente §9)
En las tablas `obras` (etapa, fechas, `publicable`), `hitos` (tipo `hito` o `entregable`, fecha, estado, responsable) y `eventos`, del mismo Postgres. El agente de proyectos las consulta con `consultar_obra` y `proximos_hitos`, y las modifica solo proponiendo `actualizar_hito` o `agendar_evento`.

## Modo LLM (agent loop)
`AgenteBase._loop_llm`: el modelo devuelve un `PasoAgente` estructurado (`tool` con `args_json`, o `final` con `operaciones`). El runtime valida el JSON, aplica la policy y ejecuta **solo lecturas**; los errores vuelven al modelo como observación. El loop tiene un límite de 5 pasos. Si el LLM falla, se usa el modo local y queda registrado en la traza (`modo = llm_fallback_local`).
