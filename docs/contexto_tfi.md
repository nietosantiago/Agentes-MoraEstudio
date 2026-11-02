# Sistema multiagente — Estudio de diseño de interiores

Documento de contexto del proyecto. Sirve como base para trabajar en Claude Code.

---

## 1. Contexto y doble propósito

El proyecto nace como una solución real para una clienta diseñadora de interiores que trabaja sola y pierde buena parte de su semana en tareas administrativas y comerciales que le restan horas de diseño (que es lo que factura).

Al mismo tiempo se usa como **Trabajo Final Integrador** del curso "Python Profesional, LLMs y APIs".

- **Usuaria final:** diseñadora de interiores con estudio en funcionamiento (Santa Fe)
- **Entrega final TFI:** miércoles 16 de diciembre de 2026
- **Framework:** LangGraph

El caso es real, no un ejemplo de laboratorio. Eso es una ventaja fuerte frente a otros TFI.

---

## 2. Alcance del TFI (versión recortada)

> La rúbrica dice explícitamente: *una solución acotada, estable y bien evaluada vale más que una arquitectura ambiciosa incompleta*. El 30% de la nota es funcionamiento end-to-end.

### Agentes incluidos (4)

| Agente | Responsabilidad |
|---|---|
| **Comercial** | Calificación y seguimiento de leads |
| **Contenidos** | Calendario y borradores para redes |
| **Administrativo** | Presupuestos, facturación y seguimiento de cobros |
| **Gestión de proyectos** | Plazos, hitos y entregables por obra |

> **Riesgo a vigilar:** administrativo y gestión de proyectos se tocan — los dos operan sobre una obra concreta. Hay que trazar la línea y dejarla escrita en los prompts de sistema: **administrativo = plata** (presupuesto, factura, cobro), **proyectos = tiempo** (fecha, hito, entregable). Si el router confunde estos dos, es la frontera más probable de error. Conviene que el dataset de evaluación tenga varios casos limítrofes.

### Agentes planificados pero FUERA del TFI

Quedan como extensión posterior para la implementación real con la clienta:

- **Diseño visual** — se alimentaría de una biblioteca con las piezas de la hermana (diseñadora gráfica) para mantener identidad. Excluido: generar imágenes es caro, difícil de evaluar objetivamente y se superpone con el trabajo de la hermana. Si se incluye, que devuelva un *brief de diseño en texto*, no imágenes.
- **Atención al cliente** — responde consultas iniciales y filtra

---

## 3. Arquitectura

### Capas

```
┌─────────────────────────────────────────┐
│  Interfaz: FastAPI + UI mínima          │
├─────────────────────────────────────────┤
│  Grafo LangGraph: router + 3 agentes    │
├─────────────────────────────────────────┤
│  Tools externas: facturación, calendario│
├─────────────────────────────────────────┤
│  Base de conocimiento + estado (Postgres)│
└─────────────────────────────────────────┘
```

### Justificación de la arquitectura multiagente (B)

Requerida por la consigna. El argumento:

> Los tres roles tienen **herramientas distintas, permisos distintos y niveles de riesgo distintos**. Emitir una factura no es lo mismo que sugerir un post. Esa separación de responsabilidades es lo que justifica el multiagente frente a un agente único con muchas tools.

---

## 4. El grafo

### Nodos

```
            Carga de contexto        (marca y cliente)
                    ↓
                 Router              (clasifica intención)
       ┌──────────┬┴─────────┬──────────┐
   Comercial  Contenidos  Administr.  Proyectos
       └──────────┴┬─────────┴──────────┘
                    ↓
             Revisión humana          (interrupt())
                    ↓
                 Ejecutor             (ejecuta lo aprobado)
```

### Estado compartido

Define todo lo demás. Empezar por acá.

```python
class EstadoEstudio(TypedDict):
    messages: Annotated[list, add_messages]
    cliente_activo: str | None
    agente_destino: str | None
    confianza_router: float
    accion_pendiente: dict | None   # qué se va a ejecutar, esperando el OK
    decision_humana: str | None     # aprobado / modificado / rechazado
    trazas: list[dict]              # tokens, costo, latencia por nodo
```

`accion_pendiente` es el corazón del human-in-the-loop. **Los agentes no ejecutan nada**: arman el dict con la acción propuesta y lo dejan en el estado. Quien ejecuta es el nodo ejecutor, y solo después de la aprobación.

### Aristas condicionales (son 3)

**1. Salida del router** — según `agente_destino`, va a uno de los cuatro. Más una salida extra: si `confianza_router` está por debajo del umbral, va a un nodo de aclaración que pregunta en vez de adivinar. Un router que deriva mal con seguridad es peor que uno que pregunta. Con cuatro agentes y dos que se rozan, este umbral pasa a ser importante de verdad.

**2. Salida de cada agente** — ¿la acción tiene efecto externo?
- Sí → revisión humana
- No (solo informativa, ej. "cuánto facturé el mes pasado") → END, sin molestar a nadie

**3. Salida de revisión humana**
- Aprobado → ejecutor
- Modificado → vuelve al agente con la corrección en el estado *(único ciclo del grafo)*
- Rechazado → END

---

## 5. Decisiones técnicas

### Checkpointing: obligatorio, no opcional

`interrupt()` de LangGraph **no funciona sin checkpointer**. El grafo necesita poder congelarse y retomarse, y eso vive en la persistencia.

- `PostgresSaver`
- `thread_id` por conversación y cliente

### Router con structured output

Devolver un modelo Pydantic con: **agente + confianza + justificación corta**.

La justificación no la usa el sistema, pero es exactamente lo que se necesita para el dataset de evaluación: permite revisar a mano por qué clasificó mal cada caso que falla.

### Base de conocimiento

Vector store con identidad de marca, precios, piezas de la hermana y proyectos pasados. Supabase con pgvector (da base de datos y almacenamiento juntos).

**Clave:** los agentes comparten la base. Si no, cada uno inventa por su lado.

### RAG: evaluado y descartado

La consigna lo marca como opcional, a usar solo si aporta valor real. Se evaluó aplicarlo sobre los presupuestos históricos y el historial de consultas de clientes, y se decidió dejarlo fuera del alcance para no ampliar la superficie del proyecto.

Vale dejar escrito el razonamiento porque suma a "arquitectura y decisiones técnicas":

- La **identidad de marca** no iría nunca a un vector store: es poco contenido, estable, y tiene que estar presente en todas las llamadas. Va como skill.
- La **lista de precios** tampoco: los precios necesitan exactitud, no similitud semántica. Eso es una tool que consulta una tabla.

Si más adelante se retoma, el candidato natural son los presupuestos históricos, con `PGVector` sobre el mismo Postgres del checkpointing.

### Interfaz: FastAPI, no WhatsApp

WhatsApp es lo mejor para la clienta, pero la aprobación de Meta puede comer semanas y no suma a la nota. Para el TFI: FastAPI + UI mínima. WhatsApp queda como extensión para la implementación real.

---

## 6. Cobertura de la rúbrica

| # | Requisito | Cómo se cubre |
|---|---|---|
| 1 | Capacidad agéntica (≥2 tools, maneja errores) | El router decide a qué agente derivar; cada agente usa sus propias tools |
| 2 | Skill reutilizable | **Identidad de marca del estudio**: tono, paleta, precios, criterios de presupuesto. Cualquier agente la carga |
| 3 | Estado y memoria | State de LangGraph + checkpointing en Postgres |
| 4 | Human-in-the-Loop | **El punto más fuerte del caso.** Nada sale hacia afuera sin aprobación: ni factura, ni mensaje a lead, ni post. Con `interrupt()` y justificación de negocio real |
| 5 | Integración externa | API de facturación, Supabase, calendario |
| 6 | Interfaz accesible | FastAPI + UI mínima |
| 7 | Ejecución reproducible | Repo + README + `.env.example` + Docker |
| 8 | Evidencia de calidad | Dataset de 30-40 consultas reales etiquetadas con el agente correcto; evaluar el router. Logging de tokens, costo y latencia por corrida |

**Peso de la rúbrica:** funcionamiento end-to-end 30% · diseño agéntico 25% · evaluación y trazabilidad 20% · arquitectura y decisiones 15% · presentación y documentación 10%.

> El punto 8 (20%) es el que todos subestiman. No dejarlo para el final.

---

## 7. Respuestas del Parcial 1

### Idea / problema

Las diseñadoras de interiores que trabajan solas pierden buena parte de la semana en tareas administrativas y comerciales —seguimiento de presupuestos y cobros, respuesta a consultas de posibles clientes, presencia en redes— que les restan horas de diseño, que es lo que realmente factura. La idea es un sistema multiagente que centralice esas tareas: un orquestador interpreta el pedido en lenguaje natural y lo deriva al agente especializado, todos apoyados sobre una base común con la identidad de marca y el historial de proyectos del estudio. Ninguna acción con efecto externo se ejecuta sin la aprobación previa de la diseñadora. El caso es real: la usuaria final es una clienta con un estudio en funcionamiento.

### Alcance

Sistema multiagente en LangGraph con un router y tres agentes especializados: comercial (calificación y seguimiento de leads), contenidos (calendario y borradores para redes) y administrativo (presupuestos, facturación y seguimiento de cobros). Estado persistido en Postgres, integración con API externa de facturación y base de conocimiento del estudio, y aprobación humana obligatoria antes de cualquier salida hacia afuera. Interfaz web mínima sobre FastAPI, evaluada con un dataset propio de consultas reales del estudio.

---

## 8. Cronograma

**Al 2 de noviembre de 2026:** Clase 10, entrega final el 16 de diciembre → ~6 semanas.

El margen alcanza para los tres agentes. El orden importa igual: construir en profundidad antes que en ancho, para que en cualquier momento haya algo que funcione de punta a punta.

| Semana | Foco |
|---|---|
| 1 | Material del estudio + base de conocimiento cargada + skill de identidad de marca |
| 2 | Grafo mínimo: router + 1 agente + revisión humana + ejecutor, con checkpointing |
| 3 | Dataset de evaluación del router + logging de costo/latencia |
| 4 | Agentes 2, 3 y 4 + integración de facturación |
| 5 | Interfaz FastAPI + Docker + README |
| 6 | Ajuste fino, documentación y preparación de la defensa |

**Punto de control:** si al terminar la semana 3 el camino end-to-end no está cerrado, sumar un solo agente más y volcar el resto del tiempo en evaluación y documentación. Un sistema con dos agentes bien evaluados saca mejor nota que cuatro a medio terminar. El orden de descarte, si hay que recortar: primero contenidos, después gestión de proyectos.

Referencia del curso: el Parcial 2 (arquitectura + demo funcional) se sugiere después de la Clase 14.

---

## 9. Pendientes

- [ ] Juntar material real del estudio: identidad de marca, lista de precios, presupuestos viejos, consultas típicas de clientes *(depende de la clienta, es lo que más tiempo lleva conseguir — arrancar ya)*
- [ ] Armar el dataset de evaluación del router (30-40 consultas etiquetadas, con casos limítrofes entre administrativo y proyectos)
- [ ] Definir dónde vive el estado de cada obra (hitos, fechas, responsables) y con qué tool lo consulta el agente de proyectos
- [ ] Definir el skill de identidad de marca
- [ ] Elegir API de facturación
- [ ] Definir qué acciones cuentan como "efecto externo"
