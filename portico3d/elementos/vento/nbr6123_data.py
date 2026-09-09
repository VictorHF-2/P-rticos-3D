# -*- coding: utf-8 -*-
"""
nbr6123_data.py
Tabelas e dados tabulados da ABNT NBR 6123:2023
(Seções 4, 5 e 6 - núcleo + edificações correntes).

Todos os valores foram transcritos das tabelas e figuras da norma.
Os ábacos de coeficiente de arrasto (Figuras 4 e 5) são GRÁFICOS; os
valores aqui armazenados são uma DIGITALIZAÇÃO APROXIMADA lida do gráfico
e devem ser conferidos no ábaco correspondente (ver assets/fig4_*, fig5_*).
"""
import math

# ---------------------------------------------------------------------------
# Seção 4 - constantes
# ---------------------------------------------------------------------------
RHO_AR = 1.226          # massa específica do ar de referência (kg/m3)
Q_COEF = 0.613          # q = 0,613 * Vk^2  (N/m2)

# ---------------------------------------------------------------------------
# 5.3 - Fator S2
# Tabela 1 - Parâmetros meteorológicos (bm, p) por categoria e classe
# Tabela 5 - zg (altura da camada limite) e z0 (comprimento de rugosidade)
# ---------------------------------------------------------------------------
# categoria -> {"zg":..., "z0":..., "A":(bm,p), "B":(bm,p), "C":(bm,p)}
TAB1_PARAMETROS = {
    "I":   {"zg": 250, "z0": 0.005, "A": (1.10, 0.06),  "B": (1.11, 0.065), "C": (1.12, 0.07)},
    "II":  {"zg": 300, "z0": 0.07,  "A": (1.00, 0.085), "B": (1.00, 0.09),  "C": (1.00, 0.10)},
    "III": {"zg": 350, "z0": 0.30,  "A": (0.94, 0.10),  "B": (0.94, 0.105), "C": (0.93, 0.115)},
    "IV":  {"zg": 420, "z0": 1.0,   "A": (0.86, 0.12),  "B": (0.85, 0.125), "C": (0.84, 0.135)},
    "V":   {"zg": 500, "z0": 2.5,   "A": (0.74, 0.15),  "B": (0.73, 0.16),  "C": (0.71, 0.175)},
}

# Tabela 2 - Fator de rajada Fr (sempre da Categoria II) por classe
TAB2_FR = {"A": 1.00, "B": 0.98, "C": 0.95}

CATEGORIAS = ["I", "II", "III", "IV", "V"]
CLASSES = ["A", "B", "C"]

CATEGORIA_DESC = {
    "I":   "Superfícies lisas de grandes dimensões (>5 km): mar calmo, lagos, rios, pântanos sem vegetação.",
    "II":  "Terrenos abertos em nível, poucos obstáculos isolados (árvores, edif. baixas). Cota média ≤ 1,0 m.",
    "III": "Terrenos planos/ondulados com obstáculos (sebes, muros, edif. baixas esparsas). Cota média 3,0 m.",
    "IV":  "Terrenos com obstáculos numerosos e pouco espaçados (zona urbana, industrial). Cota média 10 m.",
    "V":   "Terrenos com obstáculos numerosos, grandes e altos (centros de grandes cidades). Cota média ≥ 25 m.",
}

CLASSE_DESC = {
    "A": "Classe A: maior dimensão (vertical ou horizontal) ≤ 20 m. (rajada 3 s)",
    "B": "Classe B: maior dimensão entre 20 m e 50 m. (rajada 5 s)",
    "C": "Classe C: maior dimensão > 50 m. (rajada 10 s)",
}

# ---------------------------------------------------------------------------
# 5.4 - Fator estatístico S3 - Tabela 4
# ---------------------------------------------------------------------------
# grupo -> (S3, Tp_anos, descrição curta)
TAB4_S3 = {
    "1": (1.11, 100, "Ruína afeta socorro após tempestade (hospitais, quartéis, centrais); "
                     "pontes rod./ferrov.; estruturas com substâncias perigosas."),
    "2": (1.06, 75,  "Ruína com risco substancial à vida: aglomerações >300 pessoas, "
                     "creches >150, escolas >250."),
    "3": (1.00, 50,  "Residências, hotéis, comércio, indústrias; estruturas desmontáveis reutilizáveis."),
    "4": (0.95, 37,  "Edificações sem ocupação humana (depósitos, silos) sem circulação de pessoas no entorno."),
    "5": (0.83, 15,  "Edificações temporárias não reutilizáveis; estruturas dos grupos 1-4 durante a construção "
                     "(máx. 2 anos)."),
}
# Nota Tabela 4: para vedações, permite-se usar 0,92*S3 em vez de S3.
S3_VEDACAO_FATOR = 0.92

# ---------------------------------------------------------------------------
# 5.2 - Fator topográfico S1
# ---------------------------------------------------------------------------
S1_TIPOS = {
    "plano":  "Terreno plano ou fracamente acidentado (S1 = 1,0)",
    "talude": "Talude ou morro alongado (escoamento bidimensional) - ponto B",
    "vale":   "Vales profundos, protegidos de ventos de qualquer direção (S1 = 0,9)",
}

# ---------------------------------------------------------------------------
# 6.1.1 / Tabela 6 - Coef. de pressão e forma externos para PAREDES
# Planta retangular a x b (b = menor dimensão).
# Cada linha: chave (banda h/b, banda a/b) -> valores das zonas.
# alpha=0°:  A1B1, A2B2, C, D
# alpha=90°: A, B, C1D1, C2D2
# cpe_medio: aplicado à zona de barlavento (área hachurada), largura 0,2b ou h
# ---------------------------------------------------------------------------
# bandas h/b: "hb<=0.5", "hb_0.5_1.5", "hb_1.5_6"
# bandas a/b: "ab_1_1.5" (1<=a/b<=3/2) e "ab_2_4" (2<=a/b<=4); interpolar entre 3/2 e 2
TAB6_PAREDES = {
    ("hb<=0.5", "ab_1_1.5"): dict(A1B1=-0.8, A2B2=-0.5, C=+0.7, D=-0.4,
                                  A=+0.7, B=-0.4, C1D1=-0.8, C2D2=-0.4, cpe=-0.9),
    ("hb<=0.5", "ab_2_4"):   dict(A1B1=-0.8, A2B2=-0.4, C=+0.7, D=-0.3,
                                  A=+0.7, B=-0.5, C1D1=-0.9, C2D2=-0.5, cpe=-1.0),
    ("hb_0.5_1.5", "ab_1_1.5"): dict(A1B1=-0.9, A2B2=-0.5, C=+0.7, D=-0.5,
                                     A=+0.7, B=-0.5, C1D1=-0.9, C2D2=-0.5, cpe=-1.1),
    ("hb_0.5_1.5", "ab_2_4"):   dict(A1B1=-0.9, A2B2=-0.4, C=+0.7, D=-0.3,
                                     A=+0.7, B=-0.6, C1D1=-0.9, C2D2=-0.5, cpe=-1.1),
    ("hb_1.5_6", "ab_1_1.5"): dict(A1B1=-1.0, A2B2=-0.6, C=+0.8, D=-0.6,
                                   A=+0.8, B=-0.6, C1D1=-1.0, C2D2=-0.6, cpe=-1.2),
    ("hb_1.5_6", "ab_2_4"):   dict(A1B1=-1.0, A2B2=-0.5, C=+0.8, D=-0.3,
                                   A=+0.8, B=-0.6, C1D1=-1.0, C2D2=-0.6, cpe=-1.2),
}
TAB6_ZONAS_0 = ["A1B1", "A2B2", "C", "D"]
TAB6_ZONAS_90 = ["A", "B", "C1D1", "C2D2"]

# ---------------------------------------------------------------------------
# 6.1.1 / Tabela 7 - Coef. de pressão e forma externos para TELHADOS 2 ÁGUAS
# simétricos, planta retangular a x b (b = menor dimensão).
# Colunas: EFI, GHJ (alpha=90°); EG, FH (alpha=0°); cpe médio (4 zonas de borda).
# Cada banda h/b -> lista de linhas (theta, EFI, GHJ, EG, FH, cpe1, cpe2, cpe3, cpe4)
# None = célula vazia na norma.
# ---------------------------------------------------------------------------
TAB7_TELHADO = {
    "hb<=0.5": [
        (0,  -0.8, -0.4, -0.8, -0.4, -2.0, -2.0, -2.0, None),
        (5,  -0.9, -0.4, -0.8, -0.4, -1.4, -1.2, -1.2, -1.0),
        (10, -1.2, -0.4, -0.8, -0.6, -1.4, -1.4, None, -1.2),
        (15, -1.0, -0.4, -0.8, -0.6, -1.4, -1.2, None, -1.2),
        (20, -0.4, -0.4, -0.7, -0.6, -1.0, None, None, -1.2),
        (30,  0.0, -0.4, -0.7, -0.6, -0.8, None, None, -1.1),
        (45, +0.3, -0.5, -0.7, -0.6, None, None, None, -1.1),
        (60, +0.7, -0.6, -0.7, -0.6, None, None, None, -1.1),
    ],
    "hb_0.5_1.5": [
        (0,  -0.8, -0.6, -1.0, -0.6, -2.0, -2.0, -2.0, None),
        (5,  -0.9, -0.6, -0.9, -0.6, -2.0, -2.0, -1.5, -1.0),
        (10, -1.1, -0.6, -0.8, -0.6, -2.0, -2.0, -1.5, -1.2),
        (15, -1.0, -0.6, -0.8, -0.6, -1.8, -1.5, -1.5, -1.2),
        (20, -0.7, -0.5, -0.8, -0.6, -1.5, -1.5, -1.5, -1.0),
        (30, -0.2, -0.5, -0.8, -0.8, -1.0, None, None, -1.0),
        (45, +0.2, -0.5, -0.8, -0.8, None, None, None, None),
        (60, +0.6, -0.5, -0.8, -0.8, None, None, None, None),
    ],
    "hb_1.5_6": [
        (0,  -0.8, -0.6, -0.9, -0.7, -2.0, -2.0, -2.0, None),
        (5,  -0.8, -0.6, -0.8, -0.8, -2.0, -2.0, -1.5, -1.0),
        (10, -0.8, -0.6, -0.8, -0.8, -2.0, -2.0, -1.5, -1.2),
        (15, -0.8, -0.6, -0.8, -0.8, -1.8, -1.8, -1.5, -1.2),
        (20, -0.8, -0.6, -0.8, -0.8, -1.5, -1.5, -1.5, -1.2),
        (30, -1.0, -0.5, -0.8, -0.7, -1.5, None, None, None),
        (40, -0.2, -0.5, -0.8, -0.7, -1.0, None, None, None),
        (50, +0.2, -0.5, -0.8, -0.7, None, None, None, None),
        (60, +0.5, -0.5, -0.8, -0.7, None, None, None, None),
    ],
}
TAB7_COLUNAS = ["EFI", "GHJ", "EG", "FH", "cpe_a", "cpe_b", "cpe_c", "cpe_d"]

# ---------------------------------------------------------------------------
# 6.1.2 / Figuras 4 e 5 - Coeficiente de arrasto Ca (edif. paralelepipédicas)
# DIGITALIZAÇÃO APROXIMADA lida do ábaco. Eixos:
#   x = l1/l2 (largura, perpendicular ao vento / profundidade, na direção do vento)
#   y = h/l1  (altura / largura, perpendicular ao vento)
# grid[i][j] = Ca no ponto (y=Y[i], x=X[j])
# CONFERIR sempre no ábaco (assets/fig4_arrasto_baixa.png, fig5_arrasto_alta.png)
# ---------------------------------------------------------------------------
CA_X = [0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0]          # l1/l2

# Figura 4 - vento de BAIXA turbulência
CA_FIG4_Y = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 40.0]           # h/l1
CA_FIG4 = [
    [0.60, 0.67, 0.72, 0.80, 0.86, 0.92, 1.05, 1.15, 1.28, 1.35],  # h/l1=0.5
    [0.68, 0.74, 0.80, 0.88, 0.95, 1.02, 1.15, 1.25, 1.38, 1.45],  # 1.0
    [0.76, 0.83, 0.90, 1.00, 1.08, 1.15, 1.28, 1.38, 1.50, 1.55],  # 2.0
    [0.81, 0.88, 0.96, 1.06, 1.15, 1.22, 1.35, 1.45, 1.57, 1.62],  # 3.0
    [0.87, 0.95, 1.04, 1.15, 1.25, 1.32, 1.45, 1.55, 1.66, 1.72],  # 5.0
    [0.94, 1.04, 1.14, 1.27, 1.37, 1.45, 1.58, 1.68, 1.80, 1.85],  # 10
    [1.02, 1.13, 1.24, 1.38, 1.50, 1.58, 1.72, 1.82, 1.95, 2.00],  # 20
    [1.08, 1.20, 1.33, 1.48, 1.60, 1.70, 1.85, 1.95, 2.08, 2.15],  # 40
]

# Figura 5 - vento de ALTA turbulência
CA_FIG5_Y = [0.5, 1.0, 2.0, 3.0, 6.0]
CA_FIG5 = [
    [0.55, 0.60, 0.65, 0.73, 0.80, 0.85, 0.95, 1.02, 1.15, 1.25],  # 0.5
    [0.60, 0.66, 0.72, 0.80, 0.88, 0.93, 1.05, 1.12, 1.25, 1.35],  # 1.0
    [0.68, 0.74, 0.80, 0.90, 0.97, 1.03, 1.15, 1.25, 1.40, 1.50],  # 2.0
    [0.72, 0.79, 0.85, 0.95, 1.03, 1.10, 1.22, 1.32, 1.48, 1.58],  # 3.0
    [0.80, 0.88, 0.95, 1.05, 1.15, 1.22, 1.35, 1.45, 1.60, 1.65],  # 6.0
]

# ---------------------------------------------------------------------------
# 6.3.2 - Coeficientes de pressão interna cpi (método simplificado)
# ---------------------------------------------------------------------------
# a) duas faces opostas igualmente permeáveis, demais impermeáveis
CPI_2FACES = {"perp_permeavel": +0.2, "perp_impermeavel": -0.3}
# b) quatro faces igualmente permeáveis -> considerar o mais nocivo
CPI_4FACES = [-0.3, 0.0]
# c) abertura dominante na face de barlavento (razão áreas barlavento/total)
CPI_DOMINANTE_BARLAVENTO = [(1.0, +0.1), (1.5, +0.3), (2.0, +0.5), (3.0, +0.6), (6.0, +0.8)]
# c) abertura dominante em zona de alta sucção externa (razão área dominante/demais)
CPI_DOMINANTE_ALTA_SUCCAO = [(0.25, -0.4), (0.50, -0.5), (0.75, -0.6),
                             (1.0, -0.7), (1.5, -0.8), (3.0, -0.9)]
# 6.3.2.2 edificações estanques -> mais nocivo
CPI_ESTANQUE = [-0.2, 0.0]

# ---------------------------------------------------------------------------
# Valores de referência de V0 (m/s) para capitais - APENAS ORIENTATIVOS.
# A norma exige leitura no mapa de isopletas (Figura 1). Estes valores são
# aproximações usuais; confira SEMPRE no mapa (assets/fig1_isopletas.png).
# ---------------------------------------------------------------------------
V0_REFERENCIA = {
    "Porto Alegre - RS": 47, "Florianópolis - SC": 43, "Curitiba - PR": 40,
    "São Paulo - SP": 38, "Rio de Janeiro - RJ": 35, "Belo Horizonte - MG": 34,
    "Vitória - ES": 35, "Campo Grande - MS": 42, "Cuiabá - MT": 34,
    "Goiânia - GO": 34, "Brasília - DF": 34, "Salvador - BA": 30,
    "Aracaju - SE": 30, "Maceió - AL": 30, "Recife - PE": 30,
    "João Pessoa - PB": 30, "Natal - RN": 30, "Fortaleza - CE": 30,
    "Teresina - PI": 32, "São Luís - MA": 30, "Belém - PA": 28,
    "Macapá - AP": 28, "Manaus - AM": 30, "Boa Vista - RR": 30,
    "Porto Velho - RO": 30, "Rio Branco - AC": 30, "Palmas - TO": 32,
}

# ===========================================================================
# Anexo A - Velocidade normalizada S2 e intervalo de tempo t (qualquer t)
# Tabela A.1 - Parâmetros bm, p (por categoria) e Fr (único, categoria II)
# em função de t(s). S2 = bm * Fr(t) * (z/10)^p
# ===========================================================================
ANEXO_A_T = [3, 5, 10, 15, 20, 30, 45, 60, 120, 300, 600, 3600]

ANEXO_A_FR = [1.00, 0.98, 0.95, 0.93, 0.90, 0.87, 0.84, 0.82, 0.77, 0.72, 0.69, 0.65]

# categoria -> {"bm":[...], "p":[...]}  (mesma ordem de ANEXO_A_T)
ANEXO_A_TAB1 = {
    "I":   {"bm": [1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.19, 1.21, 1.23, 1.25],
            "p":  [0.06, 0.065, 0.07, 0.075, 0.075, 0.08, 0.085, 0.085, 0.09, 0.095, 0.095, 0.10]},
    "II":  {"bm": [1.00] * 12,
            "p":  [0.085, 0.09, 0.10, 0.105, 0.11, 0.115, 0.12, 0.125, 0.135, 0.145, 0.15, 0.16]},
    "III": {"bm": [0.94, 0.94, 0.93, 0.92, 0.92, 0.91, 0.90, 0.90, 0.89, 0.87, 0.86, 0.85],
            "p":  [0.10, 0.105, 0.115, 0.125, 0.13, 0.14, 0.145, 0.15, 0.16, 0.175, 0.185, 0.20]},
    "IV":  {"bm": [0.86, 0.85, 0.84, 0.83, 0.83, 0.82, 0.80, 0.79, 0.76, 0.73, 0.71, 0.68],
            "p":  [0.12, 0.125, 0.135, 0.145, 0.15, 0.16, 0.17, 0.175, 0.195, 0.215, 0.23, 0.25]},
    "V":   {"bm": [0.74, 0.73, 0.71, 0.70, 0.69, 0.67, 0.64, 0.62, 0.58, 0.53, 0.50, 0.44],
            "p":  [0.15, 0.16, 0.175, 0.185, 0.19, 0.205, 0.22, 0.23, 0.255, 0.285, 0.31, 0.35]},
}

# ---------------------------------------------------------------------------
# Anexo B - Fator estatístico S3 para probabilidade Pm e vida útil ma (anos)
# S3 = 0,54 * [-ln(1-Pm)/ma]^(-0,157)
# ---------------------------------------------------------------------------
# (fórmula implementada em nbr6123_core.calc_s3_anexo_b; sem tabela necessária)

# ===========================================================================
# Seção 8.1.1 / Tabela 26 - Cx, Cy para barras prismáticas de faces planas
# (comprimento infinito). alpha em graus; Cx,Cy em relação à dimensão c.
# ---------------------------------------------------------------------------
TAB26_ALPHAS = [0, 45, 90, 135, 180]
TAB26_BARRAS = {
    "1_cantoneira": {
        "desc": "Cantoneira simples (perfil L)",
        "Cx": [1.9, 1.8, 2.0, -1.8, -2.0],
        "Cy": [0.95, 0.8, 1.7, -0.1, 0.1],
    },
    "2_cantoneiras_cruz_aberta": {
        "desc": "Duas cantoneiras formando seção aberta em V/X",
        "Cx": [1.8, 2.1, -1.9, -2.0, -1.4],
        "Cy": [1.8, 1.8, -1.0, 0.3, -1.4],
    },
    "3_cruciforme": {
        "desc": "Perfil cruciforme (+), espessura 0,1c",
        "Cx": [1.75, 0.85, 0.1, -0.75, -1.75],
        "Cy": [0.1, 0.85, 1.75, 0.75, -0.1],
    },
    "4_cantoneira_labio": {
        "desc": "Cantoneira com aba/lábio (0,45c x 0,1c)",
        "Cx": [1.6, 1.5, -0.95, -0.5, -1.5],
        "Cy": [0.0, -0.1, 0.7, 1.05, 0.0],
    },
    "5_perfil_C": {
        "desc": "Perfil C / U (1,1c)",
        "Cx": [2.0, 1.2, -1.6, -1.1, -1.7],
        "Cy": [0.0, 0.9, 2.15, 2.4, 2.1],
    },
    "6_perfil_Z": {
        "desc": "Perfil Z (0,43c)",
        "Cx": [2.05, 1.85, 0.0, -1.6, -1.8],
        "Cy": [0.0, 0.6, 0.6, 0.4, 0.0],
    },
    "7_caixao_duplo_C": {
        "desc": "Caixão formado por 2 perfis C (1,6c) — só 0°/45°/90°",
        "Cx": [1.4, 1.2, 0.0, None, None],
        "Cy": [0.0, 1.6, 2.2, None, None],
    },
    "8_perfil_I_assimetrico": {
        "desc": "Perfil I (0,48c) — só 0°/45°/90°",
        "Cx": [2.05, 1.95, 0.5, None, None],
        "Cy": [0.0, 0.6, 0.9, None, None],
    },
    "9_perfil_I": {
        "desc": "Perfil I simétrico (c) — só 0°/45°/90°",
        "Cx": [1.6, 1.5, 0.0, None, None],
        "Cy": [0.0, 1.5, 1.9, None, None],
    },
    "10_barra_retangular_fina": {
        "desc": "Barra retangular fina (0,1c) — só 0°/45°/90°",
        "Cx": [2.0, 1.8, 0.0, None, None],
        "Cy": [0.0, 0.1, 0.1, None, None],
    },
    "11_barra_retangular_media": {
        "desc": "Barra retangular média (0,5c) — só 0°/45°/90°",
        "Cx": [2.1, 1.4, 0.0, None, None],
        "Cy": [0.0, 0.7, 0.75, None, None],
    },
    "12_barra_quadrada": {
        "desc": "Barra quadrada maciça (c x c) — só 0°/45°/90°",
        "Cx": [2.0, 1.55, 0.0, None, None],
        "Cy": [0.0, 1.55, 2.0, None, None],
    },
}

# ---------------------------------------------------------------------------
# Seção 8.1.2 / Tabela 27 - Ca para barras prismáticas de seção circular
# (comprimento infinito), em função de Re = 70000 * Vk * d
# ---------------------------------------------------------------------------
TAB27_CA_CIRCULAR = [
    (4.2e5, 1.2, "subcrítico (Re < 4,2e5)"),
    (8.4e5, 0.6, "acima do crítico (4,2e5 ≤ Re < 8,4e5)"),
    (2.3e6, 0.7, "acima do crítico (8,4e5 ≤ Re < 2,3e6)"),
    (float("inf"), 0.8, "acima do crítico (Re ≥ 2,3e6)"),
]

# ---------------------------------------------------------------------------
# Seção 8.1.3 / Tabela 28 - Fator de redução K p/ barras de comprimento finito
# ---------------------------------------------------------------------------
TAB28_L_C = [2, 5, 10, 20, 40, 50, 100, 1e9]  # 1e9 representa "infinito"
TAB28_K = {
    "circular_subcritico": [0.58, 0.62, 0.68, 0.74, 0.82, 0.87, 0.98, 1.0],
    "circular_supercritico": [0.80, 0.80, 0.82, 0.90, 0.98, 0.99, 1.0, 1.0],
    "faces_planas": [0.62, 0.66, 0.69, 0.81, 0.87, 0.90, 0.95, 1.0],
}

# ---------------------------------------------------------------------------
# Seção 8.2 / Tabela 29 - Ca para fios e cabos com l/d > 60
# em função de Re = 70000 * Vk * d
# ---------------------------------------------------------------------------
TAB29_CA_CABOS = {
    # tipo -> (Re_baixo, Ca_baixo, Re_alto, Ca_alto); interpolar (log Re) entre eles
    "fio_liso":            {"desc": "Fio liso",                                   "re_lo": 2.5e5, "ca_lo": 1.2, "re_hi": 4.2e5, "ca_hi": 0.5},
    "fio_mod_liso":        {"desc": "Fio moderadamente liso (galvanizado/pintado)", "re_lo": 2.5e5, "ca_lo": 1.2, "re_hi": 4.2e5, "ca_hi": 0.7},
    "cabo_torcido_fino":   {"desc": "Cabo torcido de fios finos (r'/d ≤ 1/30)",     "re_lo": 2.5e4, "ca_lo": 1.2, "re_hi": 4.2e4, "ca_hi": 0.9},
    "cabo_torcido_grosso": {"desc": "Cabo torcido de fios grossos (r'/d ≥ 1/25)",   "re_lo": 2.5e4, "ca_lo": 1.3, "re_hi": 4.2e4, "ca_hi": 1.1},
}

# ===========================================================================
# Seção 9.3 / Tabela 31 - Parâmetros para determinação de efeitos dinâmicos
# gamma (expoente forma modal), zeta (amortecimento crítico), T1=1/f1
# ===========================================================================
TAB31_DINAMICA = {
    "edif_concreto_sem_cortina": {
        "desc": "Edifícios com estrutura aporticada de concreto, sem cortinas",
        "gamma": 1.2, "zeta": 0.020, "T1": lambda h: 0.05 + 0.015 * h,
    },
    "edif_concreto_com_cortina": {
        "desc": "Edifícios com estrutura de concreto, com cortinas para absorção de forças horizontais",
        "gamma": 1.6, "zeta": 0.015, "T1": lambda h: 0.05 + 0.012 * h,
    },
    "torre_chamine_concreto_variavel": {
        "desc": "Torres e chaminés de concreto, seção variável",
        "gamma": 2.7, "zeta": 0.015, "T1": lambda h: 0.02 * h,
    },
    "torre_mastro_chamine_concreto_uniforme": {
        "desc": "Torres, mastros e chaminés de concreto, seção uniforme",
        "gamma": 1.7, "zeta": 0.010, "T1": lambda h: 0.015 * h,
    },
    "edif_aco_soldada": {
        "desc": "Edifícios com estrutura de aço soldada",
        "gamma": 1.2, "zeta": 0.010, "T1": lambda h: 0.29 * math.sqrt(h) - 0.4,
    },
    "torre_chamine_aco_uniforme": {
        "desc": "Torres e chaminés de aço, seção uniforme",
        "gamma": 1.7, "zeta": 0.008, "T1": None,
    },
    "estrutura_madeira": {
        "desc": "Estruturas de madeira",
        "gamma": None, "zeta": 0.030, "T1": None,
    },
}

# ---------------------------------------------------------------------------
# Seção 9.3.2 / Tabela 32 - Expoente p e parâmetro bm (para q(z) dinâmico)
# ---------------------------------------------------------------------------
TAB32_P_BM = {
    "I":   {"p": 0.095, "bm": 1.23},
    "II":  {"p": 0.15,  "bm": 1.00},
    "III": {"p": 0.185, "bm": 0.86},
    "IV":  {"p": 0.23,  "bm": 0.71},
    "V":   {"p": 0.31,  "bm": 0.50},
}

# ===========================================================================
# Seção 10.3 / Tabela 33 - Número de Strouhal para diversas seções
# ---------------------------------------------------------------------------
TAB33_STROUHAL = {
    "circulo": {"desc": "Círculo (qualquer direção)", "St": 0.20},
    "placa_transversal": {"desc": "Placa plana, vento ⊥ à placa", "St": 0.16},
    "placa_longitudinal": {"desc": "Placa plana, vento // à placa", "St": 0.15},
    "retangulo": {
        "desc": "Retângulo ℓ2/ℓ1 (interpolar)",
        "x": [0.5, 1.0, 1.5, 2.0, 3.0, 3.5, 5.0, 10.0],
        "St": [0.12, 0.12, 0.09, 0.06, 0.06, 0.15, 0.11, 0.09],
    },
    "L_ab_1_2": {"desc": "Cantoneira/seção L, b/a=1,0–2,0 (vento ⊥, interpolar)",
                 "x": [1.0, 1.5, 2.0], "St": [0.12, 0.11, 0.14]},
    "U_ab_2_4": {"desc": "Seção U, b/a=2,0–4,0 (vento //, interpolar)",
                 "x": [2.0, 4.0], "St": [0.14, 0.14]},
    "C_ab_2_4": {"desc": "Seção C/canal, b/a=2,0–4,0 (vento //, interpolar)",
                 "x": [2.0, 4.0], "St": [0.14, 0.14]},
    "T_ab_0_5_2": {"desc": "Seção T, b/a=0,5–2,0 (vento →, interpolar)",
                   "x": [0.5, 1.0, 2.0], "St": [0.15, 0.13, 0.08]},
    "cantoneira_L": {"desc": "Cantoneira de abas iguais", "St": 0.13},
}

# ---------------------------------------------------------------------------
# Seção 10.4 / Tabela 34 - Valores de C e Ka0 em função de Re, Vcr, d0
# Re = 70000 * Vcr * d0.  Faixa intermediária 2e5<=Re<=1e6 usa fórmula log(Re).
# ---------------------------------------------------------------------------
TAB34 = {
    "Re<2e5":       {"C_baixa": 0.0554, "C_alta": 0.0261, "Ka0_baixa": 2.0, "Ka0_alta": 1.1},
    "2e5<=Re<=1e6": {"Ka0_baixa": 1.2, "Ka0_alta": 0.6},   # C por fórmula log
    "Re>1e6":       {"C_baixa": 0.0208, "C_alta": 0.0098, "Ka0_baixa": 1.2, "Ka0_alta": 0.6},
}

# ===========================================================================
# Seção 11.2.2 / Tabela 35 - Expoente p e parâmetro bm (para Pae / Vae)
# ===========================================================================
TAB35_PAE = {
    "I":   {"p": 0.10,  "bm": 1.25},
    "II":  {"p": 0.16,  "bm": 1.00},
    "III": {"p": 0.20,  "bm": 0.85},
    "IV":  {"p": 0.25,  "bm": 0.68},
    "V":   {"p": 0.35,  "bm": 0.44},
}

# ---------------------------------------------------------------------------
# Seção 11.5.1 / Tabela 36 - Taxas de amortecimento estrutural ζ (%)
# no modo fundamental de vibração de pontes íntegras com um ou mais vãos
# ---------------------------------------------------------------------------
TAB36_AMORTECIMENTO = {
    "aco_chapas_soldadas_asfalto":  {"desc": "Aço: chapas soldadas, pavimento asfáltico", "zeta_pct": 0.8},
    "aco_chapas_soldadas_concreto": {"desc": "Aço: chapas soldadas, pavimento em concreto", "zeta_pct": 1.0},
    "aco_parafusado_atrito":        {"desc": "Aço: peças parafusadas (ligação por atrito)", "zeta_pct": 1.5},
    "aco_rebitado":                 {"desc": "Aço: peças rebitadas", "zeta_pct": 1.5},
    "concreto_armado":              {"desc": "Concreto armado", "zeta_pct": 2.5},
    "concreto_protendido_total":    {"desc": "Concreto protendido (protensão completa)", "zeta_pct": 2.0},
    "concreto_protendido_parcial":  {"desc": "Concreto protendido (protensão parcial)", "zeta_pct": 2.5},
    "misto_alma_cheia":             {"desc": "Mista aço-concreto: vigas de alma cheia", "zeta_pct": 1.5},
    "misto_treliça":                {"desc": "Mista aço-concreto: vigas treliçadas", "zeta_pct": 2.0},
    "liga_aluminio":                {"desc": "Ligas de alumínio (indicativo)", "zeta_pct": 2.0},
    "madeira":                      {"desc": "Madeira (indicativo)", "zeta_pct": 8.0},
    "material_composito":           {"desc": "Material compósito - matriz polimérica + fibras (indicativo)", "zeta_pct": 6.0},
}
# 11.5.1 - pontes suspensas (estaiadas/pênseis), modo fundamental de baixa freq.
TAB36_SUSPENSAS = {
    "estaiada_concreto": 3.0, "estaiada_aco": 1.5,
    "suspensa_concreto": 5.0, "suspensa_aco": 2.5,
}

# ===========================================================================
# Versão da norma usada pelo app (controle de versão)
# ===========================================================================
NORMA_VERSAO = "ABNT NBR 6123:2023"
APP_VERSAO = "2.2 (núcleo + pontes/OAEs + Bloco A/B + correção ℓ1/ℓ2) — ver DOC.txt"

# ===========================================================================
# Seção 5.5 / Tabela 5 - Mudança de rugosidade do terreno
# ===========================================================================
# zg (altura da camada limite) e z0 (comprimento de rugosidade) por categoria
TAB5_ZG_Z0 = {
    "I":   {"zg": 250, "z0": 0.005},
    "II":  {"zg": 300, "z0": 0.07},
    "III": {"zg": 350, "z0": 0.30},
    "IV":  {"zg": 420, "z0": 1.0},
    "V":   {"zg": 500, "z0": 2.5},
}

# ===========================================================================
# Seção 6.2.1 / Tabela 13 - Distribuição de pressões externas em cilindros
# (Re > 4,2e5, vento perpendicular ao eixo). beta = ângulo a partir do
# ponto de estagnação (0° a 180°).
# ---------------------------------------------------------------------------
TAB13_BETA = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 180]
TAB13_CILINDRO = {
    # (rugosa h/d=10, rugosa h/d<=2.5, lisa h/d=10, lisa h/d<=2.5)
    0:   (1.0, 1.0, 1.0, 1.0),
    10:  (0.9, 0.9, 0.9, 0.9),
    20:  (0.7, 0.7, 0.7, 0.7),
    30:  (0.4, 0.4, 0.35, 0.35),
    40:  (0.0, 0.0, 0.0, 0.0),
    50:  (-0.5, -0.4, -0.7, -0.5),
    60:  (-0.95, -0.8, -1.2, -1.05),
    70:  (-1.25, -1.1, -1.4, -1.25),
    80:  (-1.2, -1.05, -1.45, -1.3),
    90:  (-1.0, -0.85, -1.4, -1.2),
    100: (-0.8, -0.65, -1.1, -0.85),
    120: (-0.5, -0.35, -0.6, -0.4),
    140: (-0.4, -0.3, -0.35, -0.25),
    160: (-0.4, -0.3, -0.35, -0.25),
    180: (-0.4, -0.3, -0.35, -0.25),
}

# ===========================================================================
# Seção 6.2.2 / Tabela 14 - Coeficientes de arrasto Ca para corpos de
# seção constante (comprimento infinito -> corrigir com fator K, Tabela 28).
# Cada forma: h_l1 = [1/2,1,2,5,10,20,inf]; re_faixas = lista de
# (re_max_1e5 ou None p/ "todos valores", lista de 7 Ca).
# ---------------------------------------------------------------------------
TAB14_H_L1 = [0.5, 1, 2, 5, 10, 20, 1e9]
# faixas: [(re_lo_1e5, lista)] se "todos os valores" (sem dependência de Re),
# ou [(re_lo_1e5, lista_baixa), (re_hi_1e5, lista_alta)] com interpolação
# log-linear em Re entre os dois limites (Re expresso em unidades de 1e5).
TAB14_FORMAS = {
    "circulo_liso": {
        "desc": "Círculo liso (metal, concreto, alvenaria rebocada)",
        "faixas": [(3.5, [0.7, 0.7, 0.7, 0.8, 0.9, 1.0, 1.2]),
                   (4.2, [0.5, 0.5, 0.5, 0.5, 0.5, 0.6, 0.6])],
    },
    "circulo_rugoso_002": {
        "desc": "Círculo c/ rugosidade/saliências = 0,02·ℓ1",
        "faixas": [(None, [0.7, 0.7, 0.8, 0.8, 0.9, 1.0, 1.2])],
    },
    "circulo_rugoso_008": {
        "desc": "Círculo c/ rugosidade/saliências = 0,08·ℓ1",
        "faixas": [(None, [0.8, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4])],
    },
    "elipse_1_2": {
        "desc": "Elipse ℓ1/ℓ2 = 1/2",
        "faixas": [(4.2, [0.5, 0.5, 0.5, 0.5, 0.6, 0.6, 0.7]),
                   (7, [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2])],
    },
    "elipse_2_1": {
        "desc": "Elipse ℓ1/ℓ2 = 2",
        "faixas": [(7, [0.8, 0.8, 0.9, 1.0, 1.1, 1.3, 1.7]),
                   (8, [0.8, 0.8, 0.9, 1.0, 1.1, 1.3, 1.5])],
    },
    "retangulo_r13": {
        "desc": "Retângulo ℓ1/ℓ2=1, cantos arred. r/ℓ1=1/3",
        "faixas": [(3.5, [0.6, 0.6, 0.6, 0.7, 0.8, 0.8, 1.0]),
                   (4.2, [0.4, 0.4, 0.4, 0.4, 0.5, 0.5, 0.5])],
    },
    "retangulo_r16": {
        "desc": "Retângulo ℓ1/ℓ2=1, cantos arred. r/ℓ1=1/6",
        "faixas": [(7, [0.7, 0.8, 0.8, 0.9, 1.0, 1.0, 1.3]),
                   (8, [0.5, 0.5, 0.5, 0.5, 0.6, 0.6, 0.6])],
    },
    "retangulo_alongado_r12": {
        "desc": "Retângulo alongado ℓ1/ℓ2=1/2, cantos arred. r/ℓ1=1/2",
        "faixas": [(2, [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.4]),
                   (3.5, [0.2, 0.2, 0.2, 0.2, 0.3, 0.3, 0.3])],
    },
    "retangulo_alongado_r16": {
        "desc": "Retângulo alongado ℓ1/ℓ2=1/2, cantos arred. r/ℓ1=1/6",
        "faixas": [(None, [0.5, 0.5, 0.5, 0.5, 0.6, 0.6, 0.7])],
    },
    "retangulo_esbelto_r112": {
        "desc": "Retângulo esbelto ℓ1/ℓ2=2, cantos arred. r/ℓ1=1/12",
        "faixas": [(None, [0.9, 0.9, 1.0, 1.1, 1.2, 1.5, 1.9])],
    },
    "retangulo_esbelto_r14": {
        "desc": "Retângulo esbelto ℓ1/ℓ2=2, cantos arred. r/ℓ1=1/4",
        "faixas": [(3.5, [0.7, 0.8, 0.8, 0.9, 1.0, 1.2, 1.6]),
                   (4.2, [0.5, 0.5, 0.5, 0.5, 0.5, 0.6, 0.6])],
    },
    "losango_r13": {
        "desc": "Losango (quadrado a 45°), cantos arred. r/a=1/3",
        "faixas": [(4.2, [0.8, 0.8, 0.9, 1.0, 1.1, 1.3, 1.5]),
                   (6, [0.5, 0.5, 0.5, 0.5, 0.5, 0.6, 0.6])],
    },
    "losango_r112": {
        "desc": "Losango, cantos arred. r/a=1/12",
        "faixas": [(None, [0.9, 0.9, 0.9, 1.1, 1.2, 1.3, 1.6])],
    },
    "losango_r148": {
        "desc": "Losango, cantos arred. r/a=1/48 (quase aresta viva)",
        "faixas": [(None, [0.9, 0.9, 0.9, 1.1, 1.2, 1.3, 1.6])],
    },
    "triangulo_arred_r14": {
        "desc": "Triângulo, vértice arredondado apontado p/ o vento, r/ℓ1=1/4",
        "faixas": [(7, [0.7, 0.7, 0.7, 0.8, 0.9, 1.0, 1.2]),
                   (10, [0.4, 0.4, 0.4, 0.4, 0.5, 0.5, 0.5])],
    },
    "triangulo_arred_r112": {
        "desc": "Triângulo, vértice arredondado, r/ℓ1=1/12",
        "faixas": [(None, [0.8, 0.8, 0.8, 1.0, 1.1, 1.2, 1.4])],
    },
    "triangulo_face_frontal_r148": {
        "desc": "Triângulo c/ face plana p/ o vento, r/ℓ1=1/48",
        "faixas": [(None, [0.7, 0.7, 0.8, 0.9, 1.0, 1.1, 1.3])],
    },
    "triangulo_reentrante_r14": {
        "desc": "Triângulo c/ reentrância (perfil tipo cantoneira), r/ℓ1=1/4",
        "faixas": [(5, [0.7, 0.7, 0.8, 0.9, 1.0, 1.1, 1.3]),
                   (7, [0.4, 0.4, 0.4, 0.4, 0.5, 0.5, 0.5])],
    },
    "triangulo_reentrante_r112_r148": {
        "desc": "Triângulo c/ reentrância, 1/48<r/ℓ1<1/12",
        "faixas": [(None, [1.2, 1.2, 1.2, 1.4, 1.6, 1.7, 2.1])],
    },
    "dodecagono": {
        "desc": "Dodecágono (ℓ1=ℓ2)",
        "faixas": [(5, [0.7, 0.7, 0.8, 0.9, 1.0, 1.1, 1.3]),
                   (12, [0.7, 0.7, 0.7, 0.7, 0.8, 0.9, 1.1])],
    },
    "octogono": {
        "desc": "Octógono (ℓ1=ℓ2)",
        "faixas": [(None, [1.0, 1.0, 1.1, 1.2, 1.2, 1.3, 1.4])],
    },
}

# ===========================================================================
# Seção 7.1 / Tabela 23 - Coeficientes de força Cf para muros e placas
# retangulares. Casos: "bidimensional" (afastado do solo, l/ha>=60 ou 10),
# "apoiado_solo" (base no chão), "elevado_solo" (afastado do solo >=0,25ha).
# Cada célula: (alpha_graus, e_fracao_l, Cf)
# ---------------------------------------------------------------------------
TAB23_MUROS = {
    ("bidimensional", "l_ha_60"): {"alpha": 90, "e": 0.5, "Cf": 2.0},
    ("bidimensional", "l_ha_10"): {"alpha": 50, "e": 0.3, "Cf": 1.6},
    ("bidimensional", "l_ha_1"):  {"alpha": 40, "e": 0.4, "Cf": 1.8},
    ("apoiado_solo", "l_ha_60"): {"alpha": 90, "e": None, "Cf": 1.2},
    ("apoiado_solo", "l_ha_10"): {"alpha": 90, "e": None, "Cf": 1.2, "Cf_50": 1.5},
    ("apoiado_solo", "l_ha_1"):  {"alpha": 90, "e": None, "Cf": 1.1, "Cf_40": 1.5},
    ("elevado_solo", "l_ha_60"): {"alpha": 90, "e": None, "Cf": 2.0},
    ("elevado_solo", "l_ha_10"): {"alpha": 90, "e": None, "Cf": 1.3, "Cf_50": 1.6},
    ("elevado_solo", "l_ha_1"):  {"alpha": 90, "e": None, "Cf": 1.15, "Cf_40": 1.8},
}
TAB23_L_HA = {"l_ha_60": 60.0, "l_ha_10": 10.0, "l_ha_1": 1.0}

# ===========================================================================
# Seção 7.2.1 / Tabela 24 - Coeficientes de pressão em coberturas isoladas
# a uma água plana. Valores de borda (linear ao longo de l2); usar a média
# para a força global e os dois valores para o gradiente local.
# 0 <= tg(theta) <= 0,7 (Carregamento 1); faixas do Carregamento 2 abaixo.
# ---------------------------------------------------------------------------
TAB24_UMA_AGUA = {
    "carregamento1": {"borda_alta": 2.0, "borda_baixa": "tgtheta",
                       "faixa_tgtheta": (0.0, 0.7)},
    "carregamento2_baixo": {"borda_alta": 2.0, "borda_baixa": "tgtheta",
                            "faixa_tgtheta": (0.0, 0.2), "sinal": -1},
    "carregamento2_alto": {"borda_alta": "6-20tgtheta", "borda_baixa": "0.6-2tgtheta",
                           "faixa_tgtheta": (0.2, 0.3), "sinal": -1},
}
# ---------------------------------------------------------------------------
# Seção 7.2.1 / Tabela 25 - Coeficientes de pressão em coberturas isoladas a
# DUAS águas planas simétricas. cpb = coef. na água de barlavento;
# cps = coef. na água de sotavento. Fórmulas fechadas em função de tg(theta).
# Carregamento 1: 0,07<=tgθ<=0,4 e 0,4<=tgθ<=0,6 (faixas distintas).
# Carregamento 2: idem.
# ---------------------------------------------------------------------------
TAB25_DUAS_AGUAS = {
    "carregamento1": {
        "faixa_baixa": {"tgtheta": (0.07, 0.4), "cpb": "2.4tg+0.6", "cps": "3.0tg-0.5"},
        "faixa_alta":  {"tgtheta": (0.4, 0.6), "cpb": "2.4tg+0.6_clamp2.0", "cps": "0.7"},
    },
    "carregamento2": {
        "faixa_baixa": {"tgtheta": (0.07, 0.4), "cpb": "0.6tg-0.74", "cps": "-1.0"},
        "faixa_alta":  {"tgtheta": (0.4, 0.6), "cpb": "6.5tg-3.1", "cps": "5.0tg-3.0"},
    },
}

# 7.2.6 - elementos de vedação em coberturas isoladas
CP_VEDACAO_COBERTURA_ISOLADA = 2.0
# 7.2.2 - Ft = 0,5*q*a*b (atrito, vento paralelo à geratriz)
FT_COBERTURA_ISOLADA_COEF = 0.5
# 7.2.5 - abas nas bordas da cobertura isolada
FA_ABA_BARLAVENTO_COEF = 1.3
FA_ABA_SOTAVENTO_COEF = 0.8
FT_ABA_PARALELA_COEF = 0.05

# ===========================================================================
# Seção 6.4.4 - Fator de vizinhança fv (2 pontos + interpolação linear)
# ---------------------------------------------------------------------------
TAB_VIZINHANCA_FV = {
    "paredes": {"s_d_baixo": 1.0, "fv_baixo": 1.3, "s_d_alto": 3.0, "fv_alto": 1.0},
    "cobertura": {"s_d_baixo": 0.5, "fv_baixo": 1.3, "s_d_alto": 3.0, "fv_alto": 1.0},
}

# ===========================================================================
# Seção 6.1.1 / Tabela 8 - Telhado de UMA água, planta a x b (b menor),
# h/b < 2. Ce por ângulo de incidência alpha (90,45,0a,0b,-45,-90) x theta.
# 0a = He/Le (0 a b/2); 0b = He/Le (b/2 a a/2)
# ---------------------------------------------------------------------------
TAB8_THETAS = [5, 10, 15, 20, 25, 30]
TAB8_CE = {
    # theta -> (HeI_90, LeJ_90, H_45, L_45, HeL_0a, HeL_0b, H_m45, L_m45, HeI_m90, LeJ_m90)
    5:  (-1.0, -0.5, -1.0, -0.9, -1.0, -0.5, -0.9, -1.0, -0.5, -1.0),
    10: (-1.0, -0.5, -1.0, -0.8, -1.0, -0.5, -0.8, -1.0, -0.4, -1.0),
    15: (-0.9, -0.5, -1.0, -0.7, -1.0, -0.5, -0.6, -1.0, -0.3, -1.0),
    20: (-0.8, -0.5, -1.0, -0.6, -0.9, -0.5, -0.5, -1.0, -0.2, -1.0),
    25: (-0.7, -0.5, -1.0, -0.6, -0.8, -0.5, -0.3, -0.9, -0.1, -0.9),
    30: (-0.5, -0.5, -1.0, -0.6, -0.8, -0.5, -0.1, -0.6, 0.0, -0.6),
}
TAB8_CE_COLS = ["HeI_90", "LeJ_90", "H_45", "L_45", "HeL_0a", "HeL_0b",
                "H_m45", "L_m45", "HeI_m90", "LeJ_m90"]
TAB8_CPE_MEDIO = {
    # theta -> (H1,H2,L1,L2,He,Le)
    5:  (-2.0, -1.5, -2.0, -1.5, -2.0, -2.0),
    10: (-2.0, -1.5, -2.0, -1.5, -2.0, -2.0),
    15: (-1.8, -0.9, -1.8, -1.4, -2.0, -2.0),
    20: (-1.8, -0.8, -1.8, -1.4, -2.0, -2.0),
    25: (-1.8, -0.7, -0.9, -0.9, -2.0, -2.0),
    30: (-1.8, -0.5, -0.5, -0.5, -2.0, -2.0),
}
TAB8_CPE_COLS = ["H1", "H2", "L1", "L2", "He", "Le"]

# ---------------------------------------------------------------------------
# Tabela 9 - Telhado DUAS águas simétrico, calha central, h/b=0,5
# ---------------------------------------------------------------------------
TAB9_DUAS_AGUAS_CALHA = [
    # (a/b, hp_h_banda, EF_90, GH_90, EG_0, FH_0)
    (1, "<=0.05", -0.6, -0.2, -0.7, -0.1),
    (1, "0.1-0.2", -0.7, -0.4, -0.7, -0.3),
    (2, "<=0.05", -0.8, -0.3, -0.4, 0.2),
    (2, "0.1-0.2", -0.8, -0.5, -0.5, 0.2),
]

# ---------------------------------------------------------------------------
# Tabelas 10, 11, 12 - Telhados múltiplos (sheds), tramos iguais
# zonas nomeadas a*,b*,c*,d*,m*,n*,x*,z* (Ce) + b1,b2,b3 (alpha=90°)
# ---------------------------------------------------------------------------
TAB10_MULTIPLOS_SIMETRICOS = {
    # theta -> (a*,b*,c*,d*,m*,n*,x*,z*)  [alpha=0]
    5:  (-0.9, -0.6, -0.4, -0.3, -0.3, -0.3, -0.3, -0.3),
    10: (-1.1, -0.6, -0.4, -0.3, -0.3, -0.3, -0.3, -0.4),
    20: (-0.7, -0.6, -0.4, -0.3, -0.3, -0.3, -0.3, -0.5),
    30: (-0.2, -0.6, -0.4, -0.3, -0.2, -0.3, -0.2, -0.5),
    45: (0.3, -0.6, -0.6, -0.4, -0.2, -0.4, -0.2, -0.5),
}
TAB10_B123_90 = {"b1": -0.8, "b2": -0.6, "b3": -0.2}  # alpha=90°, theta<=45
TAB10_CPE_MEDIO = {"clara": -1.5, "escura": -2.0}

TAB11_MULTIPLOS_ASSIMETRICOS_60 = {
    # alpha -> (a*,b*,c*,d*,m*,n*,x*,z*)  [theta fixo em 60° na água menor]
    0:   (0.6, -0.7, -0.7, -0.4, -0.3, -0.2, -0.1, -0.3),
    180: (-0.5, -0.3, -0.3, -0.3, -0.4, -0.6, -0.6, -0.1),
}
TAB11_B123_90 = {"b1": -0.8, "b2": -0.6, "b3": -0.2}
TAB11_CPE_MEDIO = {"clara": -1.5, "escura": -2.0}

TAB12_MULTIPLOS_UMA_AGUA = {
    # (theta, alpha) -> (a*,b*,c*,d*,m*,n*,x*,z*)
    (10, 0):   (0.6, -0.6, -0.5, -0.2, 0.2, -0.2, 0.2, -0.2),
    (10, 180): (-0.2, -0.1, -0.2, -0.1, -0.2, -0.2, -0.4, -0.2),
    (15, 0):   (0.6, -0.7, -0.6, -0.2, 0.1, -0.2, 0.1, -0.3),
    (15, 180): (-0.2, -0.1, -0.2, -0.1, -0.2, -0.2, -0.5, -0.2),
    (30, 0):   (0.7, -0.7, -0.6, -0.4, 0.1, -0.2, 0.1, -0.2),
    (30, 180): (-0.2, -0.1, -0.1, -0.1, -0.2, -0.1, -0.6, 0.1),
}
TAB12_B123_90 = {10: (-0.8, -0.6, -0.2), 15: (-0.8, -0.6, -0.2), 30: (-0.9, -0.6, -0.3)}
TAB12_CPE_MEDIO = {"clara": -1.5, "escura": -2.0}

# ===========================================================================
# Seção 6.2.3 - Abóbadas cilíndricas de seção circular
# Tabela 15 (perpendicular à geratriz, baixa turbulência)
# ---------------------------------------------------------------------------
TAB15_ABOBADA_PERP = {
    # (f/l2, h/l2) -> (cpe partes 1..6)
    ("1/5", 0):    (0.3, -0.3, -0.6, -0.7, -0.6, -0.2),
    ("1/5", "1/8"):  (-0.5, -0.5, -0.7, -0.7, -0.5, -0.2),
    ("1/5", "1/4"):  (-0.9, -0.6, -0.8, -0.8, -0.4, -0.2),
    ("1/5", "1/2"):  (-1.2, -0.7, -0.9, -0.8, -0.3, -0.2),
    ("1/5", 1):    (-1.4, -0.8, -0.9, -0.9, -0.4, -0.4),
    ("1/5", 5):    (-1.8, -1.0, -1.1, -1.2, -0.8, -0.7),
    ("1/10", "1/8"): (-1.0, -0.4, -0.4, -0.4, -0.4, -0.3),
    ("1/10", "1/4"): (-1.2, -0.5, -0.4, -0.4, -0.4, -0.3),
    ("1/10", "1/2"): (-1.5, -1.0, -0.7, -0.5, -0.4, -0.3),
    ("1/10", 1):   (-1.6, -1.0, -0.8, -0.6, -0.4, -0.3),
}
# Tabela 16 (paralelo à geratriz, baixa turbulência): partes A1+A2, B, C, D1+D2
TAB16_ABOBADA_PARALELO = {"A": -0.8, "B": -0.6, "C": -0.3, "D": -0.2}
# Tabela 17 (oblíquo, pontas de sucção, baixa turbulência): partes A1, D1
TAB17_ABOBADA_OBLIQUO = {"A1": -1.8, "D1": -1.8}
# Tabela 18 (perpendicular, alta turbulência, séries S1/S2)
TAB18_ABOBADA_PERP_ALTA = {
    # (serie, f_b, h_b) -> (partes 1..6)
    ("S1", "1/5", "1/4"): (-0.3, -0.7, -0.8, -0.6, -0.4, -0.4),
    ("S1", "1/5", "1/2"): (-0.9, -0.9, -0.9, -0.7, -0.5, -0.5),
    ("S1", "1/10", "1/4"): (-1.0, -0.6, -0.6, -0.6, -0.4, -0.3),
    ("S1", "1/10", "1/2"): (-1.0, -0.8, -0.7, -0.7, -0.5, -0.4),
    ("S2", None, None): (0.4, -0.6, -1.2, -0.9, -0.7, -0.7),
}
# Tabela 19 (paralelo, alta turbulência): partes A,B,C,D
TAB19_ABOBADA_PARALELO_ALTA = {
    ("S1", "1/5", "1/4"): (-0.8, -0.4, -0.3, -0.2),
    ("S1", "1/5", "1/2"): (-0.8, -0.6, -0.3, -0.2),
    ("S1", "1/10", "1/4"): (-0.8, -0.4, -0.3, -0.2),
    ("S1", "1/10", "1/2"): (-0.9, -0.6, -0.3, -0.2),
    ("S2", None, None): (-0.8, -0.4, -0.2, -0.2),
}
# Tabela 20 (oblíquo, alta turbulência): partes E,F,G,H
TAB20_ABOBADA_OBLIQUO_ALTA = {
    ("S1", "1/5", "1/4"): (-1.6, None, None, None),
    ("S1", "1/5", "1/2"): (-2.4, -1.2, None, None),
    ("S1", "1/10", "1/4"): (-1.4, -1.4, None, None),
    ("S1", "1/10", "1/2"): (-1.6, -1.8, None, None),
    ("S2", None, None): (-1.5, None, -1.8, -1.5),
}

# ===========================================================================
# Seção 6.2.4 - Cúpulas (Tabelas 21 e 22)
# ---------------------------------------------------------------------------
TAB21_CUPULA_TERRENO = {
    # f/d -> (cpe_sobrepressao, cpe_succao, Cs)
    "1/15": (0.1, -0.3, 0.15), "1/10": (0.2, -0.3, 0.2), "1/8": (0.2, -0.4, 0.2),
    "1/6": (0.3, -0.5, 0.3), "1/4": (0.4, -0.6, 0.3), "1/2": (0.6, -1.0, 0.5),
}
TAB22_CUPULA_PAREDE = {
    # (f/d, h/d) -> (cpe_barlavento, cpe_topo, cpe_lateral)
    ("1/2", "1/4"): (0.9, -1.5, -0.4), ("1/2", "1/2"): (0.8, -1.7, -0.4), ("1/2", 1): (0.8, -1.7, -0.5),
    ("1/6", "1/4"): (-0.1, -0.9, -0.4), ("1/10", "1/4"): (-1.2, -0.6, -0.3),
    ("1/15", "1/4"): (-1.4, -0.5, -0.3), ("1/20", "1/4"): (-1.4, -0.4, -0.2),
    ("1/6", 1): (-1.4, -1.1, -0.4), ("1/10", 1): (-1.7, -0.8, -0.4),
    ("1/15", 1): (-1.5, -0.5, -0.4), ("1/20", 1): (-1.4, -0.5, -0.4),
}
