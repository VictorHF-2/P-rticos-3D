# Edifício de 3 pavimentos — Pórticos × programas isolados

Modelo: 54 nós, 96 barras, 27 lajes. Avisos da geração: nenhum

Análise com 2ª ordem: 13 combinações (2 s)

## Vigas

Comparação 1 — **mesma entrada**: Pórticos com as vigas armadas pelo motor (`fonte_vigas = "motor"`) contra o Vigas R04 isolado, com a entrada montada à mão.

| Viga | M+ máx (kN·m) | M− mín (kN·m) | V máx (kN) | posições de armadura | resultado |
|---|---|---|---|---|---|
| V8.1PAV | 28.84 / 28.84 | -0.00 / -0.00 | 20.9 / 20.9 | 5 / 5 | iguais |
| V1.1PAV | 25.54 / 25.00 | -39.37 / -39.37 | 38.6 / 39.0 | 17 / 17 | DIFEREM |
| V2.1PAV | 45.72 / 44.25 | -69.47 / -68.45 | 68.4 / 68.9 | 19 / 19 | DIFEREM |
| V3.1PAV | 40.00 / 38.85 | -64.27 / -63.09 | 68.9 / 69.2 | 15 / 15 | DIFEREM |
| V4.1PAV | 23.89 / 23.25 | -36.53 / -36.17 | 30.8 / 30.7 | 13 / 13 | DIFEREM |
| V5.1PAV | 59.86 / 59.86 | -76.67 / -76.67 | 58.5 / 58.5 | 11 / 11 | DIFEREM |
| V6.1PAV | 57.86 / 57.86 | -74.93 / -74.93 | 57.9 / 57.9 | 11 / 11 | DIFEREM |
| V7.1PAV | 33.43 / 32.41 | -49.56 / -48.83 | 44.2 / 43.9 | 10 / 10 | DIFEREM |
| V8.2PAV | 28.84 / 28.84 | -0.00 / -0.00 | 20.9 / 20.9 | 5 / 5 | iguais |
| V1.2PAV | 25.54 / 25.00 | -39.37 / -39.37 | 38.6 / 39.0 | 17 / 17 | DIFEREM |
| V2.2PAV | 45.72 / 44.25 | -69.47 / -68.45 | 68.4 / 68.9 | 19 / 19 | DIFEREM |
| V3.2PAV | 40.00 / 38.85 | -64.27 / -63.09 | 68.9 / 69.2 | 15 / 15 | DIFEREM |
| V4.2PAV | 23.89 / 23.25 | -36.53 / -36.17 | 30.8 / 30.7 | 13 / 13 | DIFEREM |
| V5.2PAV | 59.86 / 59.86 | -76.67 / -76.67 | 58.5 / 58.5 | 11 / 11 | DIFEREM |
| V6.2PAV | 57.86 / 57.86 | -74.93 / -74.93 | 57.9 / 57.9 | 11 / 11 | DIFEREM |
| V7.2PAV | 33.43 / 32.41 | -49.56 / -48.83 | 44.2 / 43.9 | 10 / 10 | DIFEREM |
| V8.COB | 28.84 / 28.84 | -0.00 / -0.00 | 20.9 / 20.9 | 5 / 5 | iguais |
| V1.COB | 27.21 / 26.65 | -39.37 / -39.37 | 39.4 / 39.7 | 17 / 17 | DIFEREM |
| V2.COB | 48.31 / 46.78 | -69.81 / -68.84 | 69.3 / 69.8 | 19 / 19 | DIFEREM |
| V3.COB | 42.03 / 40.81 | -64.65 / -63.50 | 69.6 / 69.9 | 15 / 15 | DIFEREM |
| V4.COB | 26.40 / 25.71 | -37.83 / -37.43 | 29.6 / 29.5 | 13 / 13 | DIFEREM |
| V5.COB | 63.97 / 63.97 | -77.09 / -77.09 | 60.3 / 60.3 | 11 / 11 | DIFEREM |
| V6.COB | 61.85 / 61.85 | -75.39 / -75.39 | 59.7 / 59.7 | 11 / 11 | DIFEREM |
| V7.COB | 37.48 / 36.37 | -50.23 / -49.47 | 42.6 / 42.4 | 10 / 10 | DIFEREM |
- V1.1PAV: M_max: 25.54 × 25.00
- V1.1PAV: V_max: 38.65 × 39.00
- V1.1PAV: regiões: [('Vão 1', 16.44, 2.356, '3Ø10'), ('Vão 2', 25.54, 2.356, '3Ø10'), ('Vão 3', 2.88, 2.011, '4Ø8'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -3.72, 2.454, '2Ø12.5'), ('Apoio 2', -34.34, 2.454, '2Ø12.5'), ('Apoio 3', -28.89, 2.454, '2Ø12.5'), ('Apoio 4', -38.01, 2.356, '3Ø10')] × [('Vão 1', 16.14, 2.356, '3Ø10'), ('Vão 2', 25.0, 2.356, '3Ø10'), ('Vão 3', 2.82, 2.011, '4Ø8'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -3.65, 2.454, '2Ø12.5'), ('Apoio 2', -33.88, 2.454, '2Ø12.5'), ('Apoio 3', -28.43, 2.454, '2Ø12.5'), ('Apoio 4', -38.02, 2.356, '3Ø10')]
- V1.1PAV: posições só no Pórticos: [('longitudinal', 'inferior', 1, 10.0, 0.66, 2.69, 0.0), ('longitudinal', 'inferior', 1, 10.0, 4.91, 8.21, 0.0)]; só no isolado: [('longitudinal', 'inferior', 1, 10.0, 0.74, 2.66, 0.0), ('longitudinal', 'inferior', 1, 10.0, 4.94, 8.19, 0.0)]
- V1.1PAV: veredito: True × False
- V2.1PAV: M_max: 45.72 × 44.25
- V2.1PAV: M_min: -69.47 × -68.45
- V2.1PAV: V_max: 68.35 × 68.85
- V2.1PAV: regiões: [('Vão 1', 31.4, 3.142, '4Ø10'), ('Vão 2', 45.72, 3.142, '4Ø10'), ('Vão 3', 10.57, 3.142, '4Ø10'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -4.55, 4.021, '2Ø16'), ('Apoio 2', -60.12, 4.021, '2Ø16'), ('Apoio 3', -53.0, 4.021, '2Ø16'), ('Apoio 4', -38.57, 3.682, '3Ø12.5')] × [('Vão 1', 30.65, 3.142, '4Ø10'), ('Vão 2', 44.25, 3.142, '4Ø10'), ('Vão 3', 10.24, 3.142, '4Ø10'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -4.45, 4.021, '2Ø16'), ('Apoio 2', -58.94, 4.021, '2Ø16'), ('Apoio 3', -51.84, 4.021, '2Ø16'), ('Apoio 4', -38.58, 3.682, '3Ø12.5')]
- V2.1PAV: posições só no Pórticos: [('longitudinal', 'inferior', 2, 10.0, 5.12, 7.98, 0.0)]; só no isolado: [('longitudinal', 'inferior', 2, 10.0, 5.14, 7.93, 0.0)]
- V2.1PAV: veredito: True × False
- V3.1PAV: M_max: 40.00 × 38.85
- V3.1PAV: M_min: -64.27 × -63.09
- V3.1PAV: regiões: [('Vão 1', 30.51, 3.142, '4Ø10'), ('Vão 2', 40.0, 3.142, '4Ø10'), ('Vão 3', 9.83, 2.356, '3Ø10'), ('Apoio 1', -4.77, 3.682, '3Ø12.5'), ('Apoio 2', -56.13, 3.682, '3Ø12.5'), ('Apoio 3', -46.85, 3.682, '3Ø12.5'), ('Apoio 4', -1.4, 2.454, '2Ø12.5')] × [('Vão 1', 30.0, 3.142, '4Ø10'), ('Vão 2', 38.85, 3.142, '4Ø10'), ('Vão 3', 9.68, 2.356, '3Ø10'), ('Apoio 1', -4.7, 3.682, '3Ø12.5'), ('Apoio 2', -54.87, 3.682, '3Ø12.5'), ('Apoio 3', -45.79, 3.682, '3Ø12.5'), ('Apoio 4', -1.39, 2.454, '2Ø12.5')]
- V3.1PAV: posições só no Pórticos: [('longitudinal', 'inferior', 2, 10.0, 5.22, 7.87, 0.0), ('longitudinal', 'superior', 1, 12.5, 2.39, 5.66, 0.0), ('longitudinal', 'superior', 1, 12.5, 7.49, 10.29, 0.0)]; só no isolado: [('longitudinal', 'inferior', 2, 10.0, 5.26, 7.84, 0.0), ('longitudinal', 'superior', 1, 12.5, 2.41, 5.64, 0.0), ('longitudinal', 'superior', 1, 12.5, 7.51, 10.29, 0.0)]
- V3.1PAV: veredito: True × False
- V4.1PAV: M_max: 23.89 × 23.25
- V4.1PAV: M_min: -36.53 × -36.17
- V4.1PAV: regiões: [('Vão 1', 23.89, 2.356, '3Ø10'), ('Vão 2', 12.61, 1.571, '2Ø10'), ('Apoio 1', -23.23, 2.356, '3Ø10'), ('Apoio 2', -32.68, 2.356, '3Ø10'), ('Apoio 3', -10.95, 2.356, '3Ø10')] × [('Vão 1', 23.25, 2.356, '3Ø10'), ('Vão 2', 12.27, 1.571, '2Ø10'), ('Apoio 1', -22.8, 2.356, '3Ø10'), ('Apoio 2', -32.25, 2.356, '3Ø10'), ('Apoio 3', -10.72, 2.356, '3Ø10')]
- V4.1PAV: posições só no Pórticos: [('longitudinal', 'inferior', 1, 10.0, 0.76, 3.97, 0.0), ('longitudinal', 'superior', 1, 10.0, 3.52, 6.28, 0.0)]; só no isolado: [('longitudinal', 'inferior', 1, 10.0, 0.79, 3.96, 0.0), ('longitudinal', 'superior', 1, 10.0, 3.52, 6.26, 0.0)]
- V5.1PAV: veredito: True × False
- V6.1PAV: veredito: True × False
- V7.1PAV: M_max: 33.43 × 32.41
- V7.1PAV: M_min: -49.56 × -48.83
- V7.1PAV: V_max: 44.19 × 43.93
- V7.1PAV: regiões: [('Vão 1', 33.43, 2.454, '2Ø12.5'), ('Vão 2', 11.85, 1.571, '2Ø10'), ('Apoio 1', -31.15, 4.021, '2Ø16'), ('Apoio 2', -44.73, 4.021, '2Ø16'), ('Apoio 3', -10.12, 2.356, '3Ø10')] × [('Vão 1', 32.41, 2.454, '2Ø12.5'), ('Vão 2', 11.48, 1.571, '2Ø10'), ('Apoio 1', -30.45, 4.021, '2Ø16'), ('Apoio 2', -43.92, 4.021, '2Ø16'), ('Apoio 3', -9.89, 2.356, '3Ø10')]
- V7.1PAV: veredito: True × False
- V1.2PAV: M_max: 25.54 × 25.00
- V1.2PAV: V_max: 38.65 × 39.00
- V1.2PAV: regiões: [('Vão 1', 16.44, 2.356, '3Ø10'), ('Vão 2', 25.54, 2.356, '3Ø10'), ('Vão 3', 2.88, 2.011, '4Ø8'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -3.72, 2.454, '2Ø12.5'), ('Apoio 2', -34.34, 2.454, '2Ø12.5'), ('Apoio 3', -28.89, 2.454, '2Ø12.5'), ('Apoio 4', -38.01, 2.356, '3Ø10')] × [('Vão 1', 16.14, 2.356, '3Ø10'), ('Vão 2', 25.0, 2.356, '3Ø10'), ('Vão 3', 2.82, 2.011, '4Ø8'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -3.65, 2.454, '2Ø12.5'), ('Apoio 2', -33.88, 2.454, '2Ø12.5'), ('Apoio 3', -28.43, 2.454, '2Ø12.5'), ('Apoio 4', -38.02, 2.356, '3Ø10')]
- V1.2PAV: posições só no Pórticos: [('longitudinal', 'inferior', 1, 10.0, 0.66, 2.69, 0.0), ('longitudinal', 'inferior', 1, 10.0, 4.91, 8.21, 0.0)]; só no isolado: [('longitudinal', 'inferior', 1, 10.0, 0.74, 2.66, 0.0), ('longitudinal', 'inferior', 1, 10.0, 4.94, 8.19, 0.0)]
- V1.2PAV: veredito: True × False
- V2.2PAV: M_max: 45.72 × 44.25
- V2.2PAV: M_min: -69.47 × -68.45
- V2.2PAV: V_max: 68.35 × 68.85
- V2.2PAV: regiões: [('Vão 1', 31.4, 3.142, '4Ø10'), ('Vão 2', 45.72, 3.142, '4Ø10'), ('Vão 3', 10.57, 3.142, '4Ø10'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -4.55, 4.021, '2Ø16'), ('Apoio 2', -60.12, 4.021, '2Ø16'), ('Apoio 3', -53.0, 4.021, '2Ø16'), ('Apoio 4', -38.57, 3.682, '3Ø12.5')] × [('Vão 1', 30.65, 3.142, '4Ø10'), ('Vão 2', 44.25, 3.142, '4Ø10'), ('Vão 3', 10.24, 3.142, '4Ø10'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -4.45, 4.021, '2Ø16'), ('Apoio 2', -58.94, 4.021, '2Ø16'), ('Apoio 3', -51.84, 4.021, '2Ø16'), ('Apoio 4', -38.58, 3.682, '3Ø12.5')]
- V2.2PAV: posições só no Pórticos: [('longitudinal', 'inferior', 2, 10.0, 5.12, 7.98, 0.0)]; só no isolado: [('longitudinal', 'inferior', 2, 10.0, 5.14, 7.93, 0.0)]
- V2.2PAV: veredito: True × False
- V3.2PAV: M_max: 40.00 × 38.85
- V3.2PAV: M_min: -64.27 × -63.09
- V3.2PAV: regiões: [('Vão 1', 30.51, 3.142, '4Ø10'), ('Vão 2', 40.0, 3.142, '4Ø10'), ('Vão 3', 9.83, 2.356, '3Ø10'), ('Apoio 1', -4.77, 3.682, '3Ø12.5'), ('Apoio 2', -56.13, 3.682, '3Ø12.5'), ('Apoio 3', -46.85, 3.682, '3Ø12.5'), ('Apoio 4', -1.4, 2.454, '2Ø12.5')] × [('Vão 1', 30.0, 3.142, '4Ø10'), ('Vão 2', 38.85, 3.142, '4Ø10'), ('Vão 3', 9.68, 2.356, '3Ø10'), ('Apoio 1', -4.7, 3.682, '3Ø12.5'), ('Apoio 2', -54.87, 3.682, '3Ø12.5'), ('Apoio 3', -45.79, 3.682, '3Ø12.5'), ('Apoio 4', -1.39, 2.454, '2Ø12.5')]
- V3.2PAV: posições só no Pórticos: [('longitudinal', 'inferior', 2, 10.0, 5.22, 7.87, 0.0), ('longitudinal', 'superior', 1, 12.5, 2.39, 5.66, 0.0), ('longitudinal', 'superior', 1, 12.5, 7.49, 10.29, 0.0)]; só no isolado: [('longitudinal', 'inferior', 2, 10.0, 5.26, 7.84, 0.0), ('longitudinal', 'superior', 1, 12.5, 2.41, 5.64, 0.0), ('longitudinal', 'superior', 1, 12.5, 7.51, 10.29, 0.0)]
- V3.2PAV: veredito: True × False
- V4.2PAV: M_max: 23.89 × 23.25
- V4.2PAV: M_min: -36.53 × -36.17
- V4.2PAV: regiões: [('Vão 1', 23.89, 2.356, '3Ø10'), ('Vão 2', 12.61, 1.571, '2Ø10'), ('Apoio 1', -23.23, 2.356, '3Ø10'), ('Apoio 2', -32.68, 2.356, '3Ø10'), ('Apoio 3', -10.95, 2.356, '3Ø10')] × [('Vão 1', 23.25, 2.356, '3Ø10'), ('Vão 2', 12.27, 1.571, '2Ø10'), ('Apoio 1', -22.8, 2.356, '3Ø10'), ('Apoio 2', -32.25, 2.356, '3Ø10'), ('Apoio 3', -10.72, 2.356, '3Ø10')]
- V4.2PAV: posições só no Pórticos: [('longitudinal', 'inferior', 1, 10.0, 0.76, 3.97, 0.0), ('longitudinal', 'superior', 1, 10.0, 3.52, 6.28, 0.0)]; só no isolado: [('longitudinal', 'inferior', 1, 10.0, 0.79, 3.96, 0.0), ('longitudinal', 'superior', 1, 10.0, 3.52, 6.26, 0.0)]
- V5.2PAV: veredito: True × False
- V6.2PAV: veredito: True × False
- V7.2PAV: M_max: 33.43 × 32.41
- V7.2PAV: M_min: -49.56 × -48.83
- V7.2PAV: V_max: 44.19 × 43.93
- V7.2PAV: regiões: [('Vão 1', 33.43, 2.454, '2Ø12.5'), ('Vão 2', 11.85, 1.571, '2Ø10'), ('Apoio 1', -31.15, 4.021, '2Ø16'), ('Apoio 2', -44.73, 4.021, '2Ø16'), ('Apoio 3', -10.12, 2.356, '3Ø10')] × [('Vão 1', 32.41, 2.454, '2Ø12.5'), ('Vão 2', 11.48, 1.571, '2Ø10'), ('Apoio 1', -30.45, 4.021, '2Ø16'), ('Apoio 2', -43.92, 4.021, '2Ø16'), ('Apoio 3', -9.89, 2.356, '3Ø10')]
- V7.2PAV: veredito: True × False
- V1.COB: M_max: 27.21 × 26.65
- V1.COB: V_max: 39.38 × 39.72
- V1.COB: regiões: [('Vão 1', 16.97, 2.356, '3Ø10'), ('Vão 2', 27.21, 2.356, '3Ø10'), ('Vão 3', 2.02, 2.011, '4Ø8'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -2.03, 2.454, '2Ø12.5'), ('Apoio 2', -34.64, 2.454, '2Ø12.5'), ('Apoio 3', -26.63, 2.454, '2Ø12.5'), ('Apoio 4', -38.01, 2.356, '3Ø10')] × [('Vão 1', 16.66, 2.356, '3Ø10'), ('Vão 2', 26.65, 2.356, '3Ø10'), ('Vão 3', 1.97, 2.011, '4Ø8'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -2.0, 2.454, '2Ø12.5'), ('Apoio 2', -34.2, 2.454, '2Ø12.5'), ('Apoio 3', -26.19, 2.454, '2Ø12.5'), ('Apoio 4', -38.02, 2.356, '3Ø10')]
- V1.COB: posições só no Pórticos: [('longitudinal', 'inferior', 1, 10.0, 0.54, 2.74, 0.0), ('longitudinal', 'inferior', 1, 10.0, 4.86, 8.31, 0.0)]; só no isolado: [('longitudinal', 'inferior', 1, 10.0, 0.59, 2.71, 0.0), ('longitudinal', 'inferior', 1, 10.0, 4.89, 8.29, 0.0)]
- V1.COB: veredito: True × False
- V2.COB: M_max: 48.31 × 46.78
- V2.COB: M_min: -69.81 × -68.84
- V2.COB: V_max: 69.34 × 69.84
- V2.COB: regiões: [('Vão 1', 32.15, 3.142, '4Ø10'), ('Vão 2', 48.31, 3.142, '4Ø10'), ('Vão 3', 9.3, 3.142, '4Ø10'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -2.42, 4.021, '2Ø16'), ('Apoio 2', -60.28, 4.021, '2Ø16'), ('Apoio 3', -49.85, 4.021, '2Ø16'), ('Apoio 4', -38.6, 3.682, '3Ø12.5')] × [('Vão 1', 31.4, 3.142, '4Ø10'), ('Vão 2', 46.78, 3.142, '4Ø10'), ('Vão 3', 8.98, 3.142, '4Ø10'), ('Vão 4', 0.0, 0.623, '2Ø6.3'), ('Apoio 1', -2.37, 4.021, '2Ø16'), ('Apoio 2', -59.16, 4.021, '2Ø16'), ('Apoio 3', -48.75, 4.021, '2Ø16'), ('Apoio 4', -38.61, 3.682, '3Ø12.5')]
- V2.COB: posições só no Pórticos: [('longitudinal', 'inferior', 2, 10.0, 5.04, 8.08, 0.0), ('longitudinal', 'superior', 1, 12.5, 11.14, 13.89, 0.0)]; só no isolado: [('longitudinal', 'inferior', 2, 10.0, 5.07, 8.06, 0.0), ('longitudinal', 'superior', 1, 12.5, 11.13, 13.89, 0.0)]
- V2.COB: veredito: True × False
- V3.COB: M_max: 42.03 × 40.81
- V3.COB: M_min: -64.65 × -63.50
- V3.COB: regiões: [('Vão 1', 31.54, 3.142, '4Ø10'), ('Vão 2', 42.03, 3.142, '4Ø10'), ('Vão 3', 9.59, 2.356, '3Ø10'), ('Apoio 1', -2.57, 3.682, '3Ø12.5'), ('Apoio 2', -56.39, 3.682, '3Ø12.5'), ('Apoio 3', -43.99, 3.682, '3Ø12.5'), ('Apoio 4', -0.68, 2.454, '2Ø12.5')] × [('Vão 1', 31.03, 3.142, '4Ø10'), ('Vão 2', 40.81, 3.142, '4Ø10'), ('Vão 3', 9.45, 2.356, '3Ø10'), ('Apoio 1', -2.53, 3.682, '3Ø12.5'), ('Apoio 2', -55.16, 3.682, '3Ø12.5'), ('Apoio 3', -43.01, 3.682, '3Ø12.5'), ('Apoio 4', -0.68, 2.454, '2Ø12.5')]
- V3.COB: posições só no Pórticos: [('longitudinal', 'inferior', 2, 10.0, 5.13, 8.0, 0.0), ('longitudinal', 'superior', 1, 12.5, 2.36, 5.66, 0.0), ('longitudinal', 'superior', 1, 12.5, 7.54, 10.41, 0.0)]; só no isolado: [('longitudinal', 'inferior', 2, 10.0, 5.19, 7.96, 0.0), ('longitudinal', 'superior', 1, 12.5, 2.36, 5.64, 0.0), ('longitudinal', 'superior', 1, 12.5, 7.56, 10.42, 0.0)]
- V3.COB: veredito: True × False
- V4.COB: M_max: 26.40 × 25.71
- V4.COB: M_min: -37.83 × -37.43
- V4.COB: regiões: [('Vão 1', 26.4, 2.356, '3Ø10'), ('Vão 2', 13.36, 1.571, '2Ø10'), ('Apoio 1', -17.8, 2.356, '3Ø10'), ('Apoio 2', -33.79, 2.356, '3Ø10'), ('Apoio 3', -7.68, 2.356, '3Ø10')] × [('Vão 1', 25.71, 2.356, '3Ø10'), ('Vão 2', 13.0, 1.571, '2Ø10'), ('Apoio 1', -17.47, 2.356, '3Ø10'), ('Apoio 2', -33.33, 2.356, '3Ø10'), ('Apoio 3', -7.51, 2.356, '3Ø10')]
- V4.COB: posições só no Pórticos: [('longitudinal', 'inferior', 1, 10.0, 0.56, 4.04, 0.0), ('longitudinal', 'superior', 1, 10.0, 3.5, 6.38, 0.0)]; só no isolado: [('longitudinal', 'inferior', 1, 10.0, 0.59, 4.04, 0.0), ('longitudinal', 'superior', 1, 10.0, 3.52, 6.36, 0.0)]
- V5.COB: veredito: True × False
- V6.COB: veredito: True × False
- V7.COB: M_max: 37.48 × 36.37
- V7.COB: M_min: -50.23 × -49.47
- V7.COB: V_max: 42.63 × 42.41
- V7.COB: regiões: [('Vão 1', 37.48, 2.454, '2Ø12.5'), ('Vão 2', 12.26, 1.571, '2Ø10'), ('Apoio 1', -23.46, 4.021, '2Ø16'), ('Apoio 2', -45.16, 4.021, '2Ø16'), ('Apoio 3', -6.79, 2.356, '3Ø10')] × [('Vão 1', 36.37, 2.454, '2Ø12.5'), ('Vão 2', 11.88, 1.571, '2Ø10'), ('Apoio 1', -22.93, 4.021, '2Ø16'), ('Apoio 2', -44.33, 4.021, '2Ø16'), ('Apoio 3', -6.64, 2.356, '3Ø10')]
- V7.COB: veredito: True × False

Comparação 1b — **a viga que o Pórticos montou**, gravada no formato do Vigas R04 e aberta no programa original: 24 de 24 idênticas (momentos, regiões e posições de armadura).

Por que o isolado reprova (o Pórticos aprova):

- V1.1PAV: Apoio 1: a armadura negativa (Apoio 1, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 58 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V2.1PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza 
- V3.1PAV: Apoio 1: a armadura negativa (Apoio 1, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 59 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz | Apoio 4: a armadura negativa (Apoio 4, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 59 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V5.1PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza  | Apoio 3: a armadura negativa (Apoio 3, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 55 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V6.1PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza  | Apoio 3: a armadura negativa (Apoio 3, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 55 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V7.1PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 61 cm a partir da face e há 37 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza 
- V1.2PAV: Apoio 1: a armadura negativa (Apoio 1, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 58 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V2.2PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza 
- V3.2PAV: Apoio 1: a armadura negativa (Apoio 1, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 59 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz | Apoio 4: a armadura negativa (Apoio 4, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 59 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V5.2PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza  | Apoio 3: a armadura negativa (Apoio 3, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 55 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V6.2PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza  | Apoio 3: a armadura negativa (Apoio 3, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 55 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V7.2PAV: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 61 cm a partir da face e há 37 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza 
- V1.COB: Apoio 1: a armadura negativa (Apoio 1, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 58 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V2.COB: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza 
- V3.COB: Apoio 1: a armadura negativa (Apoio 1, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 59 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz | Apoio 4: a armadura negativa (Apoio 4, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 59 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V5.COB: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza  | Apoio 3: a armadura negativa (Apoio 3, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 55 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V6.COB: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 74 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza  | Apoio 3: a armadura negativa (Apoio 3, Ø12.5) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 55 cm a partir da face e há 17 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduz
- V7.COB: Apoio 1: a armadura negativa (Apoio 1, Ø16) não ancora no apoio de extremidade (18.3.2.4-d e 18.3.2.4.1): exige 61 cm a partir da face e há 37 cm retos; o apoio não é engaste, e não há onde a barra descer. Alargue o apoio, reduza 

Comparação 2 — **o que o pórtico muda**: momentos de projeto com a envoltória do pórtico (vento, 2ª ordem, rigidez real dos pilares, trecho rígido) contra a viga contínua.

| Viga | região | M viga contínua | M pórtico | As contínua | As pórtico |
|---|---|---|---|---|---|
| V8.1PAV | Vão 1 | 28.84 | 20.90 | 3Ø10 | 3Ø10 |
| V1.1PAV | Vão 1 | 16.44 | 14.83 | 3Ø10 | 3Ø10 |
| V1.1PAV | Vão 2 | 25.54 | 22.48 | 3Ø10 | 3Ø10 |
| V1.1PAV | Vão 3 | 2.88 | 2.93 | 4Ø8 | 4Ø8 |
| V1.1PAV | Vão 4 | 0.00 | 0.29 | 2Ø6.3 | 3Ø10 |
| V1.1PAV | Apoio 1 | -3.72 | -8.93 | 2Ø12.5 | 2Ø12.5 |
| V1.1PAV | Apoio 2 | -34.34 | -38.51 | 2Ø12.5 | 2Ø12.5 |
| V1.1PAV | Apoio 3 | -28.89 | -35.52 | 2Ø12.5 | 2Ø12.5 |
| V1.1PAV | Apoio 4 | -38.01 | -38.56 | 3Ø10 | 3Ø10 |
| V2.1PAV | Vão 1 | 31.40 | 28.39 | 4Ø10 | 4Ø10 |
| V2.1PAV | Vão 2 | 45.72 | 39.68 | 4Ø10 | 4Ø10 |
| V2.1PAV | Vão 3 | 10.57 | 7.50 | 4Ø10 | 4Ø10 |
| V2.1PAV | Vão 4 | 0.00 | 0.00 | 2Ø6.3 | 2Ø6.3 |
| V2.1PAV | Apoio 1 | -4.55 | -11.99 | 2Ø16 | 2Ø16 |
| V2.1PAV | Apoio 2 | -60.12 | -68.37 | 2Ø16 | 2Ø16 |
| V2.1PAV | Apoio 3 | -53.00 | -62.27 | 2Ø16 | 2Ø16 |
| V2.1PAV | Apoio 4 | -38.57 | -42.35 | 3Ø12.5 | 3Ø12.5 |
| V3.1PAV | Vão 1 | 30.51 | 26.98 | 4Ø10 | 4Ø10 |
| V3.1PAV | Vão 2 | 40.00 | 35.18 | 4Ø10 | 4Ø10 |
| V3.1PAV | Vão 3 | 9.83 | 8.34 | 3Ø10 | 3Ø10 |
| V3.1PAV | Apoio 1 | -4.77 | -12.22 | 3Ø12.5 | 3Ø12.5 |
| V3.1PAV | Apoio 2 | -56.13 | -62.71 | 3Ø12.5 | 3Ø12.5 |
| V3.1PAV | Apoio 3 | -46.85 | -54.03 | 3Ø12.5 | 3Ø12.5 |
| V3.1PAV | Apoio 4 | -1.40 | -5.56 | 2Ø12.5 | 2Ø12.5 |
| V4.1PAV | Vão 1 | 23.89 | 20.95 | 3Ø10 | 3Ø10 |
| V4.1PAV | Vão 2 | 12.61 | 11.40 | 2Ø10 | 2Ø10 |
| V4.1PAV | Apoio 1 | -23.23 | -30.79 | 3Ø10 | 3Ø10 |
| V4.1PAV | Apoio 2 | -32.68 | -38.65 | 3Ø10 | 3Ø10 |
| V4.1PAV | Apoio 3 | -10.95 | -21.10 | 3Ø10 | 3Ø10 |
| V5.1PAV | Vão 1 | 59.86 | 51.41 | 4Ø10 | 4Ø10 |
| V5.1PAV | Vão 2 | 26.75 | 24.35 | 4Ø10 | 4Ø10 |
| V5.1PAV | Apoio 1 | -16.94 | -34.90 | 2Ø16 | 2Ø16 |
| V5.1PAV | Apoio 2 | -72.45 | -77.57 | 2Ø16 | 4Ø12.5 |
| V5.1PAV | Apoio 3 | -6.02 | -18.79 | 3Ø12.5 | 3Ø12.5 |
| V6.1PAV | Vão 1 | 57.86 | 50.05 | 4Ø10 | 4Ø10 |
| V6.1PAV | Vão 2 | 26.65 | 24.33 | 4Ø10 | 4Ø10 |
| V6.1PAV | Apoio 1 | -16.45 | -34.71 | 2Ø16 | 2Ø16 |
| V6.1PAV | Apoio 2 | -70.78 | -75.75 | 2Ø16 | 4Ø12.5 |
| V6.1PAV | Apoio 3 | -6.02 | -19.81 | 3Ø12.5 | 3Ø12.5 |
| V7.1PAV | Vão 1 | 33.43 | 28.95 | 2Ø12.5 | 2Ø12.5 |
| V7.1PAV | Vão 2 | 11.85 | 11.65 | 2Ø10 | 2Ø10 |
| V7.1PAV | Apoio 1 | -31.15 | -42.74 | 2Ø16 | 2Ø16 |
| V7.1PAV | Apoio 2 | -44.73 | -52.32 | 2Ø16 | 2Ø16 |
| V7.1PAV | Apoio 3 | -10.12 | -26.44 | 3Ø10 | 3Ø10 |
| V8.2PAV | Vão 1 | 28.84 | 20.39 | 3Ø10 | 3Ø10 |
| V1.2PAV | Vão 1 | 16.44 | 14.88 | 3Ø10 | 3Ø10 |
| V1.2PAV | Vão 2 | 25.54 | 21.93 | 3Ø10 | 3Ø10 |
| V1.2PAV | Vão 3 | 2.88 | 2.75 | 4Ø8 | 4Ø8 |
| V1.2PAV | Vão 4 | 0.00 | 0.29 | 2Ø6.3 | 3Ø10 |
| V1.2PAV | Apoio 1 | -3.72 | -9.37 | 2Ø12.5 | 2Ø12.5 |
| V1.2PAV | Apoio 2 | -34.34 | -35.50 | 2Ø12.5 | 2Ø12.5 |
| V1.2PAV | Apoio 3 | -28.89 | -36.27 | 2Ø12.5 | 2Ø12.5 |
| V1.2PAV | Apoio 4 | -38.01 | -38.55 | 3Ø10 | 3Ø10 |
| V2.2PAV | Vão 1 | 31.40 | 29.01 | 4Ø10 | 4Ø10 |
| V2.2PAV | Vão 2 | 45.72 | 38.98 | 4Ø10 | 4Ø10 |
| V2.2PAV | Vão 3 | 10.57 | 8.27 | 4Ø10 | 4Ø10 |
| V2.2PAV | Vão 4 | 0.00 | 0.00 | 2Ø6.3 | 2Ø6.3 |
| V2.2PAV | Apoio 1 | -4.55 | -14.50 | 2Ø16 | 2Ø16 |
| V2.2PAV | Apoio 2 | -60.12 | -65.16 | 2Ø16 | 2Ø16 |
| V2.2PAV | Apoio 3 | -53.00 | -62.96 | 2Ø16 | 2Ø16 |
| V2.2PAV | Apoio 4 | -38.57 | -41.85 | 3Ø12.5 | 3Ø12.5 |
| V3.2PAV | Vão 1 | 30.51 | 27.14 | 4Ø10 | 4Ø10 |
| V3.2PAV | Vão 2 | 40.00 | 34.87 | 4Ø10 | 4Ø10 |
| V3.2PAV | Vão 3 | 9.83 | 9.06 | 3Ø10 | 3Ø10 |
| V3.2PAV | Apoio 1 | -4.77 | -15.11 | 3Ø12.5 | 3Ø12.5 |
| V3.2PAV | Apoio 2 | -56.13 | -60.93 | 3Ø12.5 | 3Ø12.5 |
| V3.2PAV | Apoio 3 | -46.85 | -53.47 | 3Ø12.5 | 3Ø12.5 |
| V3.2PAV | Apoio 4 | -1.40 | -5.65 | 2Ø12.5 | 2Ø12.5 |
| V4.2PAV | Vão 1 | 23.89 | 19.95 | 3Ø10 | 3Ø10 |
| V4.2PAV | Vão 2 | 12.61 | 10.77 | 2Ø10 | 2Ø10 |
| V4.2PAV | Apoio 1 | -23.23 | -31.51 | 3Ø10 | 3Ø10 |
| V4.2PAV | Apoio 2 | -32.68 | -35.88 | 3Ø10 | 3Ø10 |
| V4.2PAV | Apoio 3 | -10.95 | -19.50 | 3Ø10 | 3Ø10 |
| V5.2PAV | Vão 1 | 59.86 | 49.50 | 4Ø10 | 4Ø10 |
| V5.2PAV | Vão 2 | 26.75 | 24.08 | 4Ø10 | 4Ø10 |
| V5.2PAV | Apoio 1 | -16.94 | -37.42 | 2Ø16 | 2Ø16 |
| V5.2PAV | Apoio 2 | -72.45 | -74.07 | 2Ø16 | 2Ø16 |
| V5.2PAV | Apoio 3 | -6.02 | -16.72 | 3Ø12.5 | 3Ø12.5 |
| V6.2PAV | Vão 1 | 57.86 | 47.93 | 4Ø10 | 4Ø10 |
| V6.2PAV | Vão 2 | 26.65 | 24.10 | 4Ø10 | 4Ø10 |
| V6.2PAV | Apoio 1 | -16.45 | -37.54 | 2Ø16 | 2Ø16 |
| V6.2PAV | Apoio 2 | -70.78 | -71.88 | 2Ø16 | 2Ø16 |
| V6.2PAV | Apoio 3 | -6.02 | -17.66 | 3Ø12.5 | 3Ø12.5 |
| V7.2PAV | Vão 1 | 33.43 | 27.34 | 2Ø12.5 | 2Ø12.5 |
| V7.2PAV | Vão 2 | 11.85 | 10.13 | 2Ø10 | 2Ø10 |
| V7.2PAV | Apoio 1 | -31.15 | -44.41 | 2Ø16 | 2Ø16 |
| V7.2PAV | Apoio 2 | -44.73 | -48.05 | 2Ø16 | 2Ø16 |
| V7.2PAV | Apoio 3 | -10.12 | -23.37 | 3Ø10 | 3Ø10 |
| V8.COB | Vão 1 | 28.84 | 21.88 | 3Ø10 | 3Ø10 |
| V1.COB | Vão 1 | 16.97 | 15.42 | 3Ø10 | 3Ø10 |
| V1.COB | Vão 2 | 27.21 | 23.67 | 3Ø10 | 3Ø10 |
| V1.COB | Vão 3 | 2.02 | 0.00 | 4Ø8 | 2Ø6.3 |
| V1.COB | Vão 4 | 0.00 | 0.31 | 2Ø6.3 | 3Ø10 |
| V1.COB | Apoio 1 | -2.03 | -4.86 | 2Ø12.5 | 2Ø12.5 |
| V1.COB | Apoio 2 | -34.64 | -34.11 | 2Ø12.5 | 2Ø12.5 |
| V1.COB | Apoio 3 | -26.63 | -31.25 | 2Ø12.5 | 2Ø12.5 |
| V1.COB | Apoio 4 | -38.01 | -37.77 | 3Ø10 | 3Ø10 |
| V2.COB | Vão 1 | 32.15 | 29.68 | 4Ø10 | 4Ø10 |
| V2.COB | Vão 2 | 48.31 | 41.77 | 4Ø10 | 4Ø10 |
| V2.COB | Vão 3 | 9.30 | 3.28 | 4Ø10 | 4Ø10 |
| V2.COB | Vão 4 | 0.00 | 0.00 | 2Ø6.3 | 2Ø6.3 |
| V2.COB | Apoio 1 | -2.42 | -7.60 | 2Ø16 | 2Ø16 |
| V2.COB | Apoio 2 | -60.28 | -62.27 | 2Ø16 | 2Ø16 |
| V2.COB | Apoio 3 | -49.85 | -56.32 | 2Ø16 | 2Ø16 |
| V2.COB | Apoio 4 | -38.60 | -42.08 | 3Ø12.5 | 3Ø12.5 |
| V3.COB | Vão 1 | 31.54 | 28.57 | 4Ø10 | 4Ø10 |
| V3.COB | Vão 2 | 42.03 | 37.48 | 4Ø10 | 4Ø10 |
| V3.COB | Vão 3 | 9.59 | 7.50 | 3Ø10 | 3Ø10 |
| V3.COB | Apoio 1 | -2.57 | -8.20 | 3Ø12.5 | 3Ø12.5 |
| V3.COB | Apoio 2 | -56.39 | -58.83 | 3Ø12.5 | 3Ø12.5 |
| V3.COB | Apoio 3 | -43.99 | -47.79 | 3Ø12.5 | 3Ø12.5 |
| V3.COB | Apoio 4 | -0.68 | -2.82 | 2Ø12.5 | 2Ø12.5 |
| V4.COB | Vão 1 | 26.40 | 22.77 | 3Ø10 | 3Ø10 |
| V4.COB | Vão 2 | 13.36 | 11.15 | 2Ø10 | 2Ø10 |
| V4.COB | Apoio 1 | -17.80 | -21.89 | 3Ø10 | 3Ø10 |
| V4.COB | Apoio 2 | -33.79 | -35.66 | 3Ø10 | 3Ø10 |
| V4.COB | Apoio 3 | -7.68 | -11.01 | 3Ø10 | 3Ø10 |
| V5.COB | Vão 1 | 63.97 | 55.38 | 3Ø12.5 | 4Ø10 |
| V5.COB | Vão 2 | 27.22 | 23.86 | 4Ø10 | 4Ø10 |
| V5.COB | Apoio 1 | -9.85 | -22.05 | 2Ø16 | 2Ø16 |
| V5.COB | Apoio 2 | -72.76 | -73.58 | 2Ø16 | 2Ø16 |
| V5.COB | Apoio 3 | -3.23 | -7.91 | 3Ø12.5 | 3Ø12.5 |
| V6.COB | Vão 1 | 61.85 | 54.05 | 4Ø10 | 4Ø10 |
| V6.COB | Vão 2 | 27.16 | 23.84 | 4Ø10 | 4Ø10 |
| V6.COB | Apoio 1 | -9.57 | -21.64 | 2Ø16 | 2Ø16 |
| V6.COB | Apoio 2 | -71.14 | -71.15 | 2Ø16 | 2Ø16 |
| V6.COB | Apoio 3 | -3.24 | -8.31 | 3Ø12.5 | 3Ø12.5 |
| V7.COB | Vão 1 | 37.48 | 32.02 | 2Ø12.5 | 2Ø12.5 |
| V7.COB | Vão 2 | 12.26 | 9.79 | 2Ø10 | 2Ø10 |
| V7.COB | Apoio 1 | -23.46 | -31.47 | 2Ø16 | 2Ø16 |
| V7.COB | Apoio 2 | -45.16 | -45.57 | 2Ø16 | 2Ø16 |
| V7.COB | Apoio 3 | -6.79 | -11.92 | 3Ø10 | 3Ø10 |

## Lajes

### 1PAV (cota 3 m)

- posições: Pórticos 36, isolado 37 — DIFEREM
- vínculos: DIFEREM; larguras de apoio: DIFEREM
- aprovado: Pórticos True (0 erros), isolado True (0 erros)
  - L8.1PAV: isolado ('livre', 'engastado', 'engastado', 'livre') × Pórticos ('livre', 'engastado', 'livre', 'livre')
  - L9.1PAV: isolado ('engastado', 'engastado', 'livre', 'livre') × Pórticos ('livre', 'engastado', 'livre', 'livre')
  - L8.1PAV: t isolado (15.0, 20.0, 20.0, 20.0) × Pórticos (20.0, 20.0, 20.0, 20.0)
  - só no Pórticos: ('L8.1PAV', 'inferior', 'X', 4.2, 15.0, 9, 10.0, 387.5)
  - só no Pórticos: ('L9.1PAV', 'inferior', 'X', 4.2, 15.0, 9, 412.5, 887.5)
  - só no isolado:  ('L8.1PAV', 'inferior', 'X', 4.2, 15.0, 9, 10.0, 397.5)
  - só no isolado:  ('L8.1PAV / L9.1PAV', 'superior', 'X', 6.3, 17.0, 8, -87.5, 867.5)
  - só no isolado:  ('L9.1PAV', 'inferior', 'X', 4.2, 15.0, 9, 402.5, 887.5)
### 2PAV (cota 6 m)

- posições: Pórticos 36, isolado 37 — DIFEREM
- vínculos: DIFEREM; larguras de apoio: DIFEREM
- aprovado: Pórticos True (0 erros), isolado True (0 erros)
  - L8.2PAV: isolado ('livre', 'engastado', 'engastado', 'livre') × Pórticos ('livre', 'engastado', 'livre', 'livre')
  - L9.2PAV: isolado ('engastado', 'engastado', 'livre', 'livre') × Pórticos ('livre', 'engastado', 'livre', 'livre')
  - L8.2PAV: t isolado (15.0, 20.0, 20.0, 20.0) × Pórticos (20.0, 20.0, 20.0, 20.0)
  - só no Pórticos: ('L8.2PAV', 'inferior', 'X', 4.2, 15.0, 9, 10.0, 387.5)
  - só no Pórticos: ('L9.2PAV', 'inferior', 'X', 4.2, 15.0, 9, 412.5, 887.5)
  - só no isolado:  ('L8.2PAV', 'inferior', 'X', 4.2, 15.0, 9, 10.0, 397.5)
  - só no isolado:  ('L8.2PAV / L9.2PAV', 'superior', 'X', 6.3, 17.0, 8, -87.5, 867.5)
  - só no isolado:  ('L9.2PAV', 'inferior', 'X', 4.2, 15.0, 9, 402.5, 887.5)
### COB (cota 9 m)

- posições: Pórticos 36, isolado 37 — DIFEREM
- vínculos: DIFEREM; larguras de apoio: DIFEREM
- aprovado: Pórticos True (0 erros), isolado True (0 erros)
  - L8.COB: isolado ('livre', 'engastado', 'engastado', 'livre') × Pórticos ('livre', 'engastado', 'livre', 'livre')
  - L9.COB: isolado ('engastado', 'engastado', 'livre', 'livre') × Pórticos ('livre', 'engastado', 'livre', 'livre')
  - L8.COB: t isolado (15.0, 20.0, 20.0, 20.0) × Pórticos (20.0, 20.0, 20.0, 20.0)
  - só no Pórticos: ('L8.COB', 'inferior', 'X', 4.2, 15.0, 9, 10.0, 387.5)
  - só no Pórticos: ('L9.COB', 'inferior', 'X', 4.2, 15.0, 9, 412.5, 887.5)
  - só no isolado:  ('L8.COB', 'inferior', 'X', 4.2, 15.0, 9, 10.0, 397.5)
  - só no isolado:  ('L8.COB / L9.COB', 'superior', 'X', 6.3, 17.0, 8, -87.5, 867.5)
  - só no isolado:  ('L9.COB', 'inferior', 'X', 4.2, 15.0, 9, 402.5, 887.5)

## Pilares

Pórticos: 214 verificações de lance (1181 s)

| Lance | combinação | Nd (kN) | Mx base/topo (kN·cm) | My base/topo (kN·cm) | arranjo Pórticos | arranjo isolado | resultado |
|---|---|---|---|---|---|---|---|
| P1.1PAV | ELU 05 | 183.7 / 183.7 | 148/-276 × -148/276 | -1236/1599 × 1236/-1599 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.1PAV | ELU 06 | 138.1 / 138.1 | -83/-21 × 83/21 | -476/934 × 476/-934 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.1PAV | ELU 09 | 164.6 / 164.6 | 300/-408 × -300/408 | -540/1091 × 540/-1091 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.1PAV | ELU 10 | 134.5 / 134.5 | 74/-173 × -74/173 | 538/370 × -538/-370 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.1PAV | ELU 11 | 153.0 / 153.0 | 90/-204 × -90/204 | 454/537 × -454/-537 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.1PAV | ELU 12 | 149.8 / 149.8 | 128/-224 × -128/224 | -1471/1488 × 1471/-1488 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.1PAV | ELU 13 | 168.3 / 168.3 | 143/-255 × -143/255 | -1554/1655 × 1554/-1655 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.2PAV | ELU 05 | 121.7 / 121.7 | 395/-405 × -395/405 | -1868/1752 × 1868/-1752 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.2PAV | ELU 06 | 93.0 / 93.0 | 134/-142 × -134/142 | -1210/1056 × 1210/-1056 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.2PAV | ELU 09 | 108.9 / 108.9 | 491/-499 × -491/499 | -1414/1231 × 1414/-1231 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.2PAV | ELU 10 | 91.1 / 91.1 | 266/-274 × -266/274 | -814/504 × 814/-504 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.2PAV | ELU 11 | 103.5 / 103.5 | 311/-321 × -311/321 | -1029/692 × 1029/-692 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.2PAV | ELU 12 | 98.4 / 98.4 | 314/-321 × -314/321 | -1595/1595 × 1595/-1595 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.COB | ELU 03 | 58.2 / 58.2 | 459/-492 × -459/492 | -1763/2432 × 1763/-2432 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.COB | ELU 05 | 58.5 / 58.5 | 430/-461 × -430/461 | -1810/2583 × 1810/-2583 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.COB | ELU 06 | 45.6 / 45.6 | 265/-285 × -265/285 | -1303/1798 × 1303/-1798 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.COB | ELU 10 | 45.0 / 45.0 | 314/-337 × -314/337 | -1225/1545 × 1225/-1545 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P1.COB | ELU 13 | 53.0 / 53.0 | 383/-411 × -383/411 | -1609/2363 × 1609/-2363 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 04 | 508.6 / 508.6 | -567/725 × -417/564 | 417/-564 × -567/725 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 06 | 370.7 / 370.7 | -146/292 × 665/-319 | -665/319 × -146/292 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 09 | 438.2 / 438.2 | -175/345 × -1188/1106 | 1188/-1106 × -175/345 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 10 | 380.5 / 380.5 | -760/843 × -365/449 | 365/-449 × -760/843 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 11 | 446.3 / 446.3 | -786/894 × -417/526 | 417/-526 × -786/894 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 12 | 362.6 / 362.6 | 465/-257 × -105/262 | 105/-262 × 465/-257 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.1PAV | ELU 13 | 428.5 / 428.5 | 440/-206 × -158/338 | 158/-338 × 440/-206 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.2PAV | ELU 04 | 337.1 / 337.1 | -828/839 × -939/875 | 939/-875 × -828/839 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.2PAV | ELU 06 | 246.9 / 246.9 | -446/444 × -214/70 | 214/-70 × -446/444 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.2PAV | ELU 09 | 291.4 / 291.4 | -527/524 × -1170/1209 | 1170/-1209 × -527/524 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.2PAV | ELU 11 | 294.8 / 294.8 | -899/920 × -832/784 | 832/-784 × -899/920 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.2PAV | ELU 12 | 243.5 / 243.5 | -75/47 × -553/495 | 553/-495 × -75/47 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.COB | ELU 02 | 167.3 / 167.3 | -633/659 × -1051/1215 | 1051/-1215 × -633/659 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.COB | ELU 03 | 167.5 / 167.5 | -634/660 × -1180/1447 | 1180/-1447 × -634/660 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.COB | ELU 04 | 167.9 / 167.9 | -705/746 × -1131/1354 | 1131/-1354 × -705/746 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.COB | ELU 06 | 123.5 / 123.5 | -469/489 × -670/734 | 670/-734 × -469/489 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.COB | ELU 08 | 123.7 / 123.7 | -470/491 × -885/1120 | 885/-1120 × -470/491 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P10.COB | ELU 12 | 122.7 / 122.7 | -351/347 × -752/888 | 752/-888 × -351/347 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.1PAV | ELU 04 | 405.7 / 405.7 | -578/740 × 458/-1154 | -458/1154 × -578/740 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.1PAV | ELU 07 | 351.4 / 351.4 | -168/345 × 1362/-1714 | -1362/1714 × -168/345 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.1PAV | ELU 08 | 302.6 / 302.6 | -143/294 × -538/-143 | 538/143 × -143/294 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.1PAV | ELU 11 | 361.3 / 361.3 | -809/916 × 320/-921 | -320/921 × -809/916 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.1PAV | ELU 12 | 292.8 / 292.8 | 498/-278 × 504/-936 | -504/936 × 498/-278 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 02 | 266.1 / 266.1 | -602/605 × 1810/-1862 | -1810/1862 × -602/605 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 04 | 268.7 / 268.7 | -849/867 × 1501/-1491 | -1501/1491 × -849/867 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 08 | 201.5 / 201.5 | -443/445 × 640/-546 | -640/546 × -443/445 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 10 | 206.0 / 206.0 | -854/882 × 980/-967 | -980/967 × -854/882 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 11 | 238.2 / 238.2 | -934/962 × 1223/-1209 | -1223/1209 × -934/962 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 12 | 197.1 / 197.1 | -32/8 × 1155/-1165 | -1155/1165 × -32/8 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.2PAV | ELU 13 | 229.4 / 229.4 | -111/88 × 1398/-1407 | -1398/1407 × -111/88 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.COB | ELU 02 | 132.1 / 132.1 | -638/667 × 1796/-2259 | -1796/2259 × -638/667 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.COB | ELU 04 | 132.7 / 132.7 | -726/772 × 1700/-2104 | -1700/2104 × -726/772 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.COB | ELU 08 | 100.0 / 100.0 | -469/492 × 1077/-1279 | -1077/1279 × -469/492 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.COB | ELU 10 | 101.2 / 101.2 | -617/667 × 1144/-1412 | -1144/1412 × -617/667 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.COB | ELU 12 | 99.0 / 99.0 | -322/317 × 1237/-1537 | -1237/1537 × -322/317 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P11.COB | ELU 13 | 115.0 / 115.0 | -406/404 × 1506/-1871 | -1506/1871 × -406/404 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 04 | 135.4 / 135.4 | -36/102 × 36/-102 | 1268/-1216 × -1268/1216 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 07 | 120.0 / 120.0 | -189/248 × 189/-248 | 283/-551 × -283/551 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 08 | 100.7 / 100.7 | 103/-50 × -103/50 | 221/-458 × -221/458 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 10 | 119.1 / 119.1 | -18/69 × 18/-69 | 1825/-1456 × -1825/1456 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 11 | 130.1 / 130.1 | -23/81 × 23/-81 | 1865/-1534 × -1865/1534 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 12 | 90.6 / 90.6 | -63/117 × 63/-117 | -1361/525 × 1361/-525 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.1PAV | ELU 13 | 101.6 / 101.6 | -68/129 × 68/-129 | -1321/447 × 1321/-447 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 04 | 88.8 / 88.8 | -155/186 × 155/-186 | 1229/-1394 × -1229/1394 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 07 | 79.3 / 79.3 | -277/302 × 277/-302 | 714/-745 × -714/745 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 08 | 68.3 / 68.3 | -15/38 × 15/-38 | 598/-620 × -598/620 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 10 | 76.6 / 76.6 | -112/133 × 112/-133 | 1305/-1542 × -1305/1542 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 11 | 84.0 / 84.0 | -128/154 × 128/-154 | 1407/-1651 × -1407/1651 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 12 | 63.7 / 63.7 | -163/185 × 163/-185 | -94/286 × 94/-286 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.2PAV | ELU 13 | 71.1 / 71.1 | -180/207 × 180/-207 | 8/177 × -8/-177 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.COB | ELU 02 | 39.6 / 39.6 | -231/233 × 231/-233 | 912/-1117 × -912/1117 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.COB | ELU 04 | 40.4 / 40.4 | -194/195 × 194/-195 | 999/-1345 × -999/1345 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.COB | ELU 08 | 32.5 / 32.5 | -117/118 × 117/-118 | 678/-833 × -678/833 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.COB | ELU 10 | 34.5 / 34.5 | -146/148 × 146/-148 | 830/-1224 × -830/1224 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.COB | ELU 12 | 31.2 / 31.2 | -179/182 × 179/-182 | 532/-453 × -532/453 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P12.COB | ELU 13 | 34.4 / 34.4 | -200/202 × 200/-202 | 646/-591 × -646/591 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.1PAV | ELU 05 | 402.8 / 402.8 | 935/-1460 × -332/510 | 332/-510 × 935/-1460 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.1PAV | ELU 06 | 307.5 / 307.5 | 419/-834 × 962/-473 | -962/473 × 419/-834 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.1PAV | ELU 09 | 354.3 / 354.3 | 496/-989 × -1330/1172 | 1330/-1172 × 496/-989 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.1PAV | ELU 10 | 301.7 / 301.7 | -180/-312 × -1/204 | 1/-204 × -180/-312 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.1PAV | ELU 13 | 360.0 / 360.0 | 1095/-1511 × -367/496 | 367/-496 × 1095/-1511 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.2PAV | ELU 05 | 267.0 / 267.0 | 1826/-1781 × -539/533 | 539/-533 × 1826/-1781 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.2PAV | ELU 06 | 204.7 / 204.7 | 1181/-1134 × 120/-277 | -120/277 × 1181/-1134 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.2PAV | ELU 09 | 235.5 / 235.5 | 1401/-1345 × -899/1029 | 899/-1029 × 1401/-1345 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.2PAV | ELU 10 | 202.3 / 202.3 | 843/-762 × -275/245 | 275/-245 × 843/-762 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.2PAV | ELU 11 | 232.5 / 232.5 | 1064/-975 × -343/310 | 343/-310 × 1064/-975 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.2PAV | ELU 12 | 207.7 / 207.7 | 1517/-1503 × -436/442 | 436/-442 × 1517/-1503 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.COB | ELU 03 | 132.5 / 132.5 | 1696/-1923 × -643/888 | 643/-888 × 1696/-1923 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.COB | ELU 05 | 132.8 / 132.8 | 1760/-2005 × -591/772 | 591/-772 × 1760/-2005 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.COB | ELU 06 | 102.2 / 102.2 | 1234/-1399 × -311/306 | 311/-306 × 1234/-1399 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.COB | ELU 09 | 117.5 / 117.5 | 1465/-1660 × -609/881 | 609/-881 × 1465/-1660 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P2.COB | ELU 10 | 101.7 / 101.7 | 1129/-1262 × -397/500 | 397/-500 × 1129/-1262 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 05 | 352.7 / 352.7 | 951/-1457 × 337/-813 | -337/813 × 951/-1457 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 07 | 309.5 / 309.5 | 497/-979 × 1523/-1581 | -1523/1581 × 497/-979 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 08 | 270.7 / 270.7 | 418/-823 × -820/163 | 820/-163 × 418/-823 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 10 | 263.9 / 263.9 | -207/-283 × 489/-763 | -489/763 × -207/-283 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 11 | 303.0 / 303.0 | -128/-438 × 545/-877 | -545/877 × -128/-438 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 12 | 277.2 / 277.2 | 1043/-1363 × 158/-541 | -158/541 × 1043/-1363 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.1PAV | ELU 13 | 316.3 / 316.3 | 1122/-1518 × 214/-655 | -214/655 × 1122/-1518 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.2PAV | ELU 05 | 234.6 / 234.6 | 1839/-1791 × 1245/-1078 | -1245/1078 × 1839/-1791 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.2PAV | ELU 07 | 206.6 / 206.6 | 1394/-1336 × 1623/-1629 | -1623/1629 × 1394/-1336 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.2PAV | ELU 08 | 180.6 / 180.6 | 1173/-1123 × 458/-206 | -458/206 × 1173/-1123 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.2PAV | ELU 10 | 177.6 / 177.6 | 799/-716 × 1034/-943 | -1034/943 × 799/-716 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.2PAV | ELU 13 | 209.6 / 209.6 | 1768/-1743 × 1047/-891 | -1047/891 × 1768/-1743 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.COB | ELU 02 | 114.6 / 114.6 | 1696/-1928 × 1431/-1890 | -1431/1890 × 1696/-1928 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.COB | ELU 05 | 115.0 / 115.0 | 1776/-2028 × 1342/-1713 | -1342/1713 × 1776/-2028 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.COB | ELU 08 | 88.9 / 88.9 | 1232/-1400 × 891/-1053 | -891/1053 × 1232/-1400 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.COB | ELU 10 | 88.2 / 88.2 | 1099/-1232 × 1039/-1348 | -1039/1348 × 1099/-1232 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P3.COB | ELU 13 | 102.5 / 102.5 | 1597/-1832 × 1153/-1465 | -1153/1465 × 1597/-1832 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 05 | 334.8 / 334.8 | 188/-357 × -188/357 | -1926/2487 × 1926/-2487 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 06 | 255.5 / 255.5 | -64/-61 × 64/61 | -688/1361 × 688/-1361 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 09 | 284.6 / 284.6 | 331/-471 × -331/471 | -853/1653 × 853/-1653 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 10 | 239.7 / 239.7 | 87/-202 × -87/202 | 873/429 × -873/-429 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 11 | 278.5 / 278.5 | 109/-245 × -109/245 | 732/707 × -732/-707 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 12 | 261.6 / 261.6 | 158/-287 × -158/287 | -2273/2308 × 2273/-2308 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.1PAV | ELU 13 | 300.4 / 300.4 | 180/-331 × -180/331 | -2414/2585 × 2414/-2585 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.2PAV | ELU 05 | 221.8 / 221.8 | 496/-484 × -496/484 | -2989/2767 × 2989/-2767 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.2PAV | ELU 06 | 169.2 / 169.2 | 184/-177 × -184/177 | -1853/1593 × 1853/-1593 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.2PAV | ELU 09 | 190.9 / 190.9 | 568/-556 × -568/556 | -2243/1933 × 2243/-1933 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.2PAV | ELU 10 | 162.1 / 162.1 | 299/-293 × -299/293 | -1230/737 × 1230/-737 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.2PAV | ELU 13 | 197.9 / 197.9 | 453/-441 × -453/441 | -2865/2789 × 2865/-2789 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.COB | ELU 03 | 107.8 / 107.8 | 538/-596 × -538/596 | -2868/3843 × 2868/-3843 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.COB | ELU 05 | 108.9 / 108.9 | 518/-574 × -518/574 | -2939/4061 × 2939/-4061 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.COB | ELU 06 | 83.1 / 83.1 | 310/-349 × -310/349 | -2039/2730 × 2039/-2730 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.COB | ELU 10 | 81.3 / 81.3 | 344/-387 × -344/387 | -1921/2367 × 1921/-2367 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.COB | ELU 11 | 94.0 / 94.0 | 410/-461 × -410/461 | -2333/2920 × 2333/-2920 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P4.COB | ELU 12 | 83.9 / 83.9 | 396/-436 × -396/436 | -2163/3102 × 2163/-3102 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.1PAV | ELU 03 | 322.2 / 322.2 | 304/-495 × -304/495 | 321/-593 × -321/593 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.1PAV | ELU 06 | 242.2 / 242.2 | -1/-137 × 1/137 | 206/-419 × -206/419 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.1PAV | ELU 09 | 287.9 / 287.9 | 338/-505 × -338/505 | 286/-519 × -286/519 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.1PAV | ELU 11 | 279.8 / 279.8 | 187/-352 × -187/352 | 2276/-1701 × -2276/1701 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.1PAV | ELU 12 | 250.3 / 250.3 | 151/-290 × -151/290 | -1784/763 × 1784/-763 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.2PAV | ELU 03 | 214.8 / 214.8 | 707/-726 × -707/726 | 780/-632 × -780/632 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.2PAV | ELU 06 | 162.8 / 162.8 | 294/-312 × -294/312 | 551/-443 × -551/443 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.2PAV | ELU 11 | 187.7 / 187.7 | 536/-554 × -536/554 | 1554/-1698 × -1554/1698 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.2PAV | ELU 12 | 166.6 / 166.6 | 447/-461 × -447/461 | -324/703 × 324/-703 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.COB | ELU 03 | 107.8 / 107.8 | 728/-766 × -728/766 | 888/-1240 × -888/1240 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.COB | ELU 05 | 107.7 / 107.7 | 685/-723 × -685/723 | 762/-918 × -762/918 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.COB | ELU 06 | 82.6 / 82.6 | 435/-462 × -435/462 | 639/-891 × -639/891 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.COB | ELU 10 | 82.7 / 82.7 | 506/-534 × -506/534 | 849/-1427 × -849/1427 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.COB | ELU 11 | 94.9 / 94.9 | 597/-630 × -597/630 | 970/-1595 × -970/1595 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P5.COB | ELU 12 | 83.5 / 83.5 | 502/-530 × -502/530 | 439/-372 × -439/372 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P6.1PAV | ELU 05 | 794.5 / 794.5 | 495/-44 × -531/825 | 531/-825 × 495/-44 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.1PAV | ELU 06 | 596.6 / 596.6 | -240/482 × 1118/-365 | -1118/365 × -240/482 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.1PAV | ELU 09 | 697.5 / 697.5 | -292/579 × -1983/1683 | 1983/-1683 × -292/579 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.1PAV | ELU 10 | 595.9 / 595.9 | -1628/1673 × -430/626 | 430/-626 × -1628/1673 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.1PAV | ELU 11 | 693.3 / 693.3 | -1675/1766 × -512/748 | 512/-748 × -1675/1766 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.1PAV | ELU 12 | 600.8 / 600.8 | 1143/-704 × -353/570 | 353/-570 × 1143/-704 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.2PAV | ELU 05 | 529.0 / 529.0 | -519/386 × -1117/1038 | 1117/-1038 × -519/386 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.2PAV | ELU 06 | 397.8 / 397.8 | -698/640 × -160/-99 | 160/99 × -698/640 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.2PAV | ELU 09 | 464.3 / 464.3 | -838/769 × -1599/1742 | 1599/-1742 × -838/769 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.2PAV | ELU 10 | 397.6 / 397.6 | -1454/1483 × -812/765 | 812/-765 × -1454/1483 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.2PAV | ELU 11 | 462.4 / 462.4 | -1589/1606 × -976/918 | 976/-918 × -1589/1606 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.2PAV | ELU 12 | 399.7 / 399.7 | 54/-197 × -784/724 | 784/-724 × 54/-197 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.COB | ELU 03 | 269.5 / 269.5 | -1031/1221 × -1426/1955 | 1426/-1955 × -1031/1221 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.COB | ELU 04 | 269.2 / 269.2 | -1168/1404 × -1331/1738 | 1331/-1738 × -1168/1404 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.COB | ELU 06 | 202.8 / 202.8 | -741/879 × -789/867 | 789/-867 × -741/879 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P6.COB | ELU 12 | 203.3 / 203.3 | -512/575 × -948/1229 | 948/-1229 × -512/575 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 05 | 719.1 / 719.1 | 562/-98 × 660/-1499 | -660/1499 × 562/-98 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 07 | 630.5 / 630.5 | -264/554 × 2086/-2286 | -2086/2286 × -264/554 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 08 | 541.7 / 541.7 | -222/465 × -1058/-92 | 1058/92 × -222/465 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 10 | 539.0 / 539.0 | -1672/1702 × 439/-1076 | -439/1076 × -1672/1702 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 11 | 626.3 / 626.3 | -1715/1792 × 524/-1278 | -524/1278 × -1715/1792 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 12 | 545.9 / 545.9 | 1229/-773 × 504/-1100 | -504/1100 × 1229/-773 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.1PAV | ELU 13 | 633.2 / 633.2 | 1186/-683 × 588/-1302 | -588/1302 × 1186/-683 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 05 | 479.7 / 479.7 | -405/281 × 1997/-1804 | -1997/1804 × -405/281 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 07 | 420.8 / 420.8 | -783/720 × 2401/-2428 | -2401/2428 × -783/720 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 08 | 361.9 / 361.9 | -655/604 × 792/-447 | -792/447 × -655/604 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 10 | 360.7 / 360.7 | -1497/1531 × 1470/-1313 | -1470/1313 × -1497/1531 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 11 | 419.0 / 419.0 | -1625/1648 × 1741/-1557 | -1741/1557 × -1625/1648 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 12 | 363.7 / 363.7 | 187/-325 × 1453/-1318 | -1453/1318 × 187/-325 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.2PAV | ELU 13 | 422.0 / 422.0 | 60/-208 × 1723/-1561 | -1723/1561 × 60/-208 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 02 | 242.9 / 242.9 | -968/1163 × 2253/-3079 | -2253/3079 × -968/1163 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 04 | 242.6 / 242.6 | -1144/1390 × 2159/-2860 | -2159/2860 × -1144/1390 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 05 | 243.0 / 243.0 | -791/937 × 2143/-2849 | -2143/2849 × -791/937 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 08 | 183.4 / 183.4 | -696/837 × 1395/-1704 | -1395/1704 × -696/837 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 10 | 183.2 / 183.2 | -990/1215 × 1579/-2087 | -1579/2087 × -990/1215 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 12 | 183.9 / 183.9 | -403/460 × 1551/-2068 | -1551/2068 × -403/460 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P7.COB | ELU 13 | 213.5 / 213.5 | -538/623 × 1844/-2457 | -1844/2457 × -538/623 | 8 ø10 mm (6,28 cm²) | 8 ø10 mm (6,28 cm²) | iguais |
| P8.1PAV | ELU 02 | 471.0 / 471.0 | 20/-116 × -20/116 | 799/-1595 × -799/1595 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.1PAV | ELU 06 | 361.7 / 361.7 | -72/1 × 72/-1 | 568/-1120 × -568/1120 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.1PAV | ELU 08 | 350.0 / 350.0 | 243/-321 × -243/321 | 522/-1092 × -522/1092 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.1PAV | ELU 09 | 405.9 / 405.9 | 258/-347 × -258/347 | 642/-1332 × -642/1332 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.1PAV | ELU 11 | 408.4 / 408.4 | 109/-200 × -109/200 | 3773/-3266 × -3773/3266 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.1PAV | ELU 12 | 359.1 / 359.1 | 77/-146 × -77/146 | -2563/814 × 2563/-814 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 02 | 312.9 / 312.9 | 207/-193 × -207/193 | 1918/-1725 × -1918/1725 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 06 | 239.6 / 239.6 | 70/-61 × -70/61 | 1341/-1211 × -1341/1211 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 08 | 234.2 / 234.2 | 389/-373 × -389/373 | 1313/-1178 × -1313/1178 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 09 | 271.4 / 271.4 | 425/-407 × -425/407 | 1604/-1439 × -1604/1439 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 10 | 235.5 / 235.5 | 244/-230 × -244/230 | 2672/-2966 × -2672/2966 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 11 | 272.6 / 272.6 | 281/-265 × -281/265 | 2963/-3226 × -2963/3226 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 12 | 238.4 / 238.4 | 214/-204 × -214/204 | -18/577 × 18/-577 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.2PAV | ELU 13 | 275.5 / 275.5 | 251/-238 × -251/238 | 274/316 × -274/-316 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 02 | 158.6 / 158.6 | 281/-324 × -281/324 | 2083/-2937 × -2083/2937 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 03 | 157.8 / 157.8 | 364/-406 × -364/406 | 2075/-2924 × -2075/2924 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 04 | 158.0 / 158.0 | 326/-368 × -326/368 | 2251/-3383 × -2251/3383 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 06 | 121.0 / 121.0 | 175/-207 × -175/207 | 1453/-2050 × -1453/2050 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 08 | 119.7 / 119.7 | 314/-345 × -314/345 | 1440/-2029 × -1440/2029 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 11 | 138.9 / 138.9 | 290/-325 × -290/325 | 2049/-3239 × -2049/3239 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P8.COB | ELU 12 | 120.6 / 120.6 | 238/-271 × -238/271 | 1160/-1286 × -1160/1286 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.1PAV | ELU 04 | 214.9 / 214.9 | 227/-418 × -227/418 | 931/-967 × -931/967 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.1PAV | ELU 06 | 155.2 / 155.2 | 10/-148 × -10/148 | 217/-431 × -217/431 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.1PAV | ELU 09 | 187.0 / 187.0 | 327/-490 × -327/490 | 276/-516 × -276/516 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.1PAV | ELU 11 | 194.5 / 194.5 | 204/-368 × -204/368 | 1310/-1150 × -1310/1150 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.1PAV | ELU 12 | 147.7 / 147.7 | 132/-270 × -132/270 | -817/203 × 817/-203 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.2PAV | ELU 03 | 140.3 / 140.3 | 721/-736 × -721/736 | 819/-755 × -819/755 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.2PAV | ELU 04 | 142.5 / 142.5 | 660/-675 × -660/675 | 1107/-1122 × -1107/1122 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.2PAV | ELU 06 | 104.7 / 104.7 | 340/-353 × -340/353 | 602/-554 × -602/554 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.2PAV | ELU 11 | 128.0 / 128.0 | 573/-586 × -573/586 | 1198/-1275 × -1198/1275 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.2PAV | ELU 12 | 101.0 / 101.0 | 443/-454 × -443/454 | 122/58 × -122/-58 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.COB | ELU 03 | 67.2 / 67.2 | 765/-807 × -765/807 | 903/-1119 × -903/1119 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.COB | ELU 04 | 67.8 / 67.8 | 742/-784 × -742/784 | 973/-1283 × -973/1283 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.COB | ELU 06 | 50.8 / 50.8 | 478/-506 × -478/506 | 670/-830 × -670/830 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.COB | ELU 10 | 52.5 / 52.5 | 531/-561 × -531/561 | 792/-1114 × -792/1114 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.COB | ELU 12 | 49.7 / 49.7 | 516/-546 × -516/546 | 555/-556 × -555/556 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |
| P9.COB | ELU 13 | 57.7 / 57.7 | 624/-659 × -624/659 | 669/-696 × -669/696 | 6 ø10 mm (4,71 cm²) | 6 ø10 mm (4,71 cm²) | iguais |

## Armadura em 3D

- cota 3 m: {'pilar longitudinal': 76, 'pilar estribo': 300, 'viga longitudinal': 1079, 'viga estribo': 1070, 'laje positiva': 510, 'laje negativa': 497}; avisos: nenhum; pontos de barra fora do concreto: nenhum
- cota 6 m: {'pilar longitudinal': 76, 'pilar estribo': 300, 'viga longitudinal': 1022, 'viga estribo': 1028, 'laje positiva': 510, 'laje negativa': 497}; avisos: nenhum; pontos de barra fora do concreto: nenhum
- cota 9 m: {'pilar longitudinal': 76, 'pilar estribo': 300, 'viga longitudinal': 988, 'viga estribo': 1028, 'laje positiva': 510, 'laje negativa': 497}; avisos: nenhum; pontos de barra fora do concreto: nenhum

## Resumo

Vigas com diferença: 21; pavimentos de laje com diferença: 3; verificações de pilar com diferença: 0. Tempo: 3779 s.