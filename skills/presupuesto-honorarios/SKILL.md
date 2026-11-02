---
name: presupuesto-honorarios
description: Preparar una propuesta de honorarios a partir del cálculo del tarifario vigente, con alcance, condiciones y validez.
mora-intents: presupuesto
mora-version: 1.0
---
# Propuesta de honorarios

## Procedimiento
1. Usar SOLO los montos devueltos por `calcular_honorarios` (no recalcular a mano).
2. Detallar por etapa: nombre, porcentaje y monto. Luego subtotal, IVA y total.
3. Aclarar qué NO incluye: costo de obra, materiales, tasas municipales, sellados.
4. Forma de pago: 30% de anticipo a la firma y saldo por etapa.
5. Validez: la indicada por el tarifario.
6. Si faltan datos (m² o tipo de proyecto), no estimar: pedirlos.
7. Proponer una primera reunión sin cargo para ajustar alcance.

## Reglas
- Prohibido ofrecer o insinuar descuentos (ver references/politica_descuentos.md).
- Los montos del texto deben coincidir exactamente con el cálculo.
