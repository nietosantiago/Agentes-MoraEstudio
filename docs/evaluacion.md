# Evaluación y trazabilidad (20% de la nota)

## Qué se evalúa
1. **Router**: si deriva bien, sobre todo en la frontera administrativo/proyectos. Es el punto de falla más probable.
2. **Costo y latencia** por corrida y por nodo (trazas).
3. **End-to-end**: los tests de `tests/test_grafo.py` y `tests/test_api.py` cubren cada camino del grafo.

## Dataset del router — `eval/dataset_router.jsonl`
40 casos: 7 comercial, 7 contenidos, 11 administrativo, 8 proyectos, 3 que deberían pedir aclaración y 4 **multi-intención** (`esperado: "multi"` + `agentes_esperados`). 18 están marcados como `limitrofe`, con una `nota` que explica por qué.

> ⚠️ **Es un dataset semilla escrito por nosotros**, con las mismas personas que escribieron las reglas. Sirve para armar la herramienta, no como resultado final. El objetivo de la semana 3 es reemplazarlo o ampliarlo con **30–40 consultas reales de la clienta**, etiquetadas a mano.

## Métricas — `mora eval-router`
Cada caso termina en **correcto**, **aclaración** (preguntó) o **error con confianza** (derivó mal sin preguntar, el peor caso).

- accuracy, tasa de aclaración y tasa de error con confianza (suman 100%)
- accuracy en limítrofes y cantidad de confusiones administrativo ↔ proyectos
- multi-intención: si delegó exactamente al conjunto esperado, y cuántos pedidos simples se partieron por error
- precision y recall por clase, matriz de confusión
- latencia p50/p95, tokens in/out, costo total y por consulta
- tabla de casos no correctos con la **justificación del router**, para revisión manual

Se guarda en `eval/reports/router_<modo>_<fecha>.{md,json}`.

## Resultado actual (baseline por reglas, dataset semilla)
Ver [`eval/reports/router_reglas_2026-11-02.md`](../eval/reports/router_reglas_2026-11-02.md):

| Métrica | Valor |
|---|---|
| Accuracy | 92,5% |
| Aclaración | 7,5% |
| **Error con confianza** | **0%** |
| Accuracy en limítrofes | 86,7% |
| Confusiones admin ↔ proyectos | 0 |
| Multi-intención correcta | 4/4 |
| Pedidos simples partidos por error | 0 |

Los 4 casos multi-intención se escribieron junto con el detector, así que su 4/4 también es optimista. Los 3 casos no correctos son aclaraciones (el router dudó y preguntó), no errores. Por ejemplo, R13 "Quiero mostrar en Instagram la obra…": las reglas no tienen la palabra `instagram` como señal de contenidos. **No se corrigió a propósito**, para no sobreajustar las reglas al dataset que se usa para medir.

## Experimento propuesto para la defensa
Correr el mismo dataset (real) con `MORA_LLM=local` y con `MORA_LLM=gemini` y comparar accuracy, error con confianza, latencia y costo por consulta. Probar también 2 o 3 umbrales (0,5 / 0,6 / 0,7) para mostrar el *trade-off* entre preguntar de más y equivocarse.

```bash
MORA_LLM=gemini mora eval-router
```
