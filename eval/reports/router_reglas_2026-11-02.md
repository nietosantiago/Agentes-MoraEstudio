# Evaluación del router — modo reglas (2026-11-02T16:41:16)

Dataset: 40 casos · umbral de confianza 0.6

| Métrica | Valor |
|---|---|
| Accuracy | 92.5% |
| Tasa de aclaración (preguntó) | 7.5% |
| **Error con confianza** (derivó mal sin preguntar) | **0.0%** |
| Accuracy en casos limítrofes | 86.7% |
| Confusiones administrativo ↔ proyectos | 0 |
| Multi-intención: delegó al conjunto correcto | 100.0% |
| Pedidos simples partidos por error | 0 |
| Latencia p50 / p95 | 0.21 / 0.83 ms |
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
| multi | 4 | 1.0 | 1.0 |

## Matriz de confusión (filas = esperado, columnas = predicho)

| | comercial | contenidos | administrativo | proyectos | aclaracion | multi |
|---|---|---|---|---|---|---|
| **comercial** | 6 | 0 | 0 | 0 | 1 | 0 |
| **contenidos** | 0 | 6 | 0 | 0 | 1 | 0 |
| **administrativo** | 0 | 0 | 10 | 0 | 1 | 0 |
| **proyectos** | 0 | 0 | 0 | 8 | 0 | 0 |
| **aclaracion** | 0 | 0 | 0 | 0 | 3 | 0 |
| **multi** | 0 | 0 | 0 | 0 | 0 | 4 |

## Casos no correctos (para revisión manual con la justificación del router)

| id | texto | esperado | predicho | conf. | resultado | justificación |
|---|---|---|---|---|---|---|
| R06 | ¿Cuántos leads nuevos entraron esta semana? | comercial | aclaracion | 0.581 | aclaracion | señales comercial=2.5 vs proyectos=1 |
| R13 | Quiero mostrar en Instagram la obra de las oficinas Ríos | contenidos | aclaracion | 0.556 | aclaracion | señales proyectos=1 |
| R24 | La obra de Gómez se termina en diciembre, ¿cuánto falta cobrarle? | administrativo | aclaracion | 0.581 | aclaracion | señales administrativo=2.5 vs proyectos=1 |