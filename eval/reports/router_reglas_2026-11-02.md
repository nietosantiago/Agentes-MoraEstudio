# Evaluación del router — modo reglas (2026-11-02T15:21:40)

Dataset: 36 casos · umbral de confianza 0.6

| Métrica | Valor |
|---|---|
| Accuracy | 91.7% |
| Tasa de aclaración (preguntó) | 8.3% |
| **Error con confianza** (derivó mal sin preguntar) | **0.0%** |
| Accuracy en casos limítrofes | 84.6% |
| Confusiones administrativo ↔ proyectos | 0 |
| Latencia p50 / p95 | 0.35 / 0.41 ms |
| Tokens in / out | 0 / 0 |
| Costo total / por consulta | US$ 0.0 / 0.0 |

## Por clase

| Clase | Soporte | Precision | Recall |
|---|---|---|---|
| comercial | 7 | 1.0 | 0.857 |
| contenidos | 7 | 1.0 | 0.857 |
| administrativo | 11 | 1.0 | 0.909 |
| proyectos | 8 | 1.0 | 1.0 |
| aclaracion | 3 | 0.5 | 1.0 |

## Matriz de confusión (filas = esperado, columnas = predicho)

| | comercial | contenidos | administrativo | proyectos | aclaracion |
|---|---|---|---|---|---|
| **comercial** | 6 | 0 | 0 | 0 | 1 |
| **contenidos** | 0 | 6 | 0 | 0 | 1 |
| **administrativo** | 0 | 0 | 10 | 0 | 1 |
| **proyectos** | 0 | 0 | 0 | 8 | 0 |
| **aclaracion** | 0 | 0 | 0 | 0 | 3 |

## Casos no correctos (para revisión manual con la justificación del router)

| id | texto | esperado | predicho | conf. | resultado | justificación |
|---|---|---|---|---|---|---|
| R06 | ¿Cuántos leads nuevos entraron esta semana? | comercial | aclaracion | 0.581 | aclaracion | señales comercial=2.5 vs proyectos=1 |
| R13 | Quiero mostrar en Instagram la obra de las oficinas Ríos | contenidos | aclaracion | 0.556 | aclaracion | señales proyectos=1 |
| R24 | La obra de Gómez se termina en diciembre, ¿cuánto falta cobrarle? | administrativo | aclaracion | 0.581 | aclaracion | señales administrativo=2.5 vs proyectos=1 |