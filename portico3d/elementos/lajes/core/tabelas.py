# -*- coding: utf-8 -*-
"""
tabelas.py
Tabelas de coeficientes das lajes maciças retangulares, transcritas de
*Projeto de lajes maciças de concreto armado* (A. Campos Filho, DECIV/UFRGS,
2014) e de *Vigas continuas, pórticos y placas* (J. Hahn, 1966).

São três tabelas, todas indexadas pelo **caso de vinculação** (1 a 9):

    ALFA_ELASTICO ... momentos em regime elástico, m = alfa . p . a²  (§3.1)
    K_FLECHA ........ flecha imediata, f = k . p . a⁴ / (Ecs . Ieq)   (§1.6)
    HAHN ............ parcela do carregamento que vai a cada borda    (§3.4)

Convenção dos bordos, que vale em todo o programa e vem da própria apostila
(§3.2): os bordos são numerados 1, 2, 3 e 4 no contorno, **começando por um
bordo de menor comprimento**. Assim os bordos 1 e 3 têm comprimento ``a`` (o
vão menor) e os bordos 2 e 4 têm comprimento ``b``.

Daí sai a correspondência entre bordo e direção, que é a fonte de meia
confusão neste assunto: o bordo 1, de comprimento ``a``, apoia a faixa que
**vaza na direção b**; logo o momento negativo dele pertence à direção b:

    m1' = -i1 . mb        m2' = -i2 . ma
    m3' = -i3 . mb        m4' = -i4 . ma

Os vãos são ``a <= b`` e a relação tabelada é sempre ``a/b`` (de 0,5 a 1,0)
nas tabelas de momento e de flecha, e ``b/a`` (de 1,00 a 2,00) na de Hahn.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Casos de vinculação
# ---------------------------------------------------------------------------

#: Tipos de vínculo de bordo. O código de um caso é a concatenação dos quatro
#: vínculos na ordem 1-2-3-4, com 1 = apoiado e 2 = engastado.
LIVRE, APOIADO, ENGASTADO = 0, 1, 2

#: Código de vinculação -> caso da tabela (1 a 9). Os casos 3, 6, 7, 8 e 9
#: reúnem os arranjos que são o mesmo problema girado ou espelhado.
CASOS = {
    "1111": 1,                                      # quatro bordos apoiados
    "2222": 2,                                      # quatro engastados
    "2112": 3, "2211": 3, "1122": 3, "1221": 3,     # dois adjacentes
    "2121": 4,                                      # os dois bordos "a"
    "1212": 5,                                      # os dois bordos "b"
    "2111": 6, "1121": 6,                           # um bordo "a"
    "1112": 7, "1211": 7,                           # um bordo "b"
    "2212": 8, "1222": 8,                           # três, com os dois "b"
    "2122": 9, "2221": 9,                           # três, com os dois "a"
}

#: Descrição de cada caso, para a memória de cálculo e para a interface.
DESCRICAO_CASO = {
    1: "quatro bordos apoiados",
    2: "quatro bordos engastados",
    3: "dois bordos adjacentes engastados",
    4: "os dois bordos de comprimento a engastados",
    5: "os dois bordos de comprimento b engastados",
    6: "um bordo de comprimento a engastado",
    7: "um bordo de comprimento b engastado",
    8: "três bordos engastados, entre eles os dois de comprimento b",
    9: "três bordos engastados, entre eles os dois de comprimento a",
}

# ---------------------------------------------------------------------------
# Momentos em regime elástico (apostila §3.1, tabela da página 28)
# ---------------------------------------------------------------------------

#: Relações a/b tabeladas.
RELACOES_AB = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

#: Coeficientes alfa de ``m = alfa . p . a²``, por caso e por componente.
#: ``ma`` e ``mb`` são os momentos positivos das direções a e b; ``ma_`` e
#: ``mb_`` são os momentos negativos (em módulo) dos engastes daquela direção.
#: Um componente ausente significa que aquele caso não tem engaste naquela
#: direção -- e não que o coeficiente seja zero por acaso.
ALFA_ELASTICO: dict[int, dict[str, tuple[float, ...]]] = {
    1: {"ma":  (0.099, 0.086, 0.073, 0.061, 0.051, 0.042),
        "mb":  (0.032, 0.037, 0.040, 0.042, 0.043, 0.042)},
    2: {"ma":  (0.041, 0.038, 0.034, 0.029, 0.025, 0.021),
        "mb":  (0.010, 0.013, 0.017, 0.018, 0.020, 0.021),
        "ma_": (0.084, 0.080, 0.074, 0.067, 0.059, 0.052),
        "mb_": (0.058, 0.058, 0.058, 0.057, 0.055, 0.052)},
    3: {"ma":  (0.057, 0.052, 0.045, 0.039, 0.033, 0.027),
        "mb":  (0.016, 0.020, 0.024, 0.026, 0.027, 0.027),
        "ma_": (0.119, 0.111, 0.101, 0.091, 0.080, 0.070),
        "mb_": (0.082, 0.082, 0.080, 0.078, 0.074, 0.070)},
    4: {"ma":  (0.084, 0.065, 0.049, 0.037, 0.027, 0.020),
        "mb":  (0.036, 0.038, 0.039, 0.037, 0.034, 0.031),
        "mb_": (0.119, 0.111, 0.102, 0.091, 0.080, 0.070)},
    5: {"ma":  (0.042, 0.041, 0.039, 0.037, 0.034, 0.031),
        "mb":  (0.008, 0.010, 0.013, 0.016, 0.018, 0.020),
        "ma_": (0.084, 0.083, 0.082, 0.078, 0.074, 0.070)},
    6: {"ma":  (0.091, 0.075, 0.060, 0.048, 0.037, 0.030),
        "mb":  (0.034, 0.038, 0.040, 0.039, 0.038, 0.036),
        "mb_": (0.122, 0.117, 0.110, 0.102, 0.093, 0.084)},
    7: {"ma":  (0.060, 0.056, 0.051, 0.046, 0.040, 0.036),
        "mb":  (0.015, 0.019, 0.023, 0.026, 0.028, 0.030),
        "ma_": (0.122, 0.116, 0.109, 0.101, 0.093, 0.084)},
    8: {"ma":  (0.042, 0.040, 0.037, 0.033, 0.029, 0.026),
        "mb":  (0.009, 0.012, 0.015, 0.018, 0.019, 0.021),
        "ma_": (0.085, 0.083, 0.079, 0.074, 0.068, 0.062),
        "mb_": (0.056, 0.057, 0.058, 0.058, 0.057, 0.055)},
    # o ma_ do caso 9 sai da fonte com 0,088 em a/b = 0,80, entre 0,091 e
    # 0,066: o valor rompe a tendência da linha e é, quase certamente, erro
    # de digitação da apostila. Fica como está porque é maior que o vizinho
    # interpolado -- ou seja, o desvio é a favor da segurança.
    9: {"ma":  (0.055, 0.048, 0.040, 0.033, 0.026, 0.021),
        "mb":  (0.018, 0.023, 0.025, 0.027, 0.026, 0.026),
        "ma_": (0.114, 0.102, 0.091, 0.088, 0.066, 0.055),
        "mb_": (0.082, 0.081, 0.078, 0.074, 0.068, 0.062)},
}

# ---------------------------------------------------------------------------
# Flecha imediata (apostila §1.6, tabelas das páginas 9 e 10)
# ---------------------------------------------------------------------------

#: Coeficiente k de ``f = k . p . a⁴ / (Ecs . Ieq)`` para laje armada em duas
#: direções, por caso de vinculação e relação a/b.
K_FLECHA: dict[int, tuple[float, ...]] = {
    1: (0.99, 0.85, 0.71, 0.59, 0.48, 0.40),
    2: (0.25, 0.23, 0.21, 0.18, 0.15, 0.13),
    3: (0.46, 0.41, 0.36, 0.30, 0.25, 0.21),
    4: (0.83, 0.63, 0.48, 0.35, 0.26, 0.19),
    5: (0.25, 0.25, 0.24, 0.23, 0.21, 0.19),
    6: (0.91, 0.73, 0.58, 0.46, 0.35, 0.28),
    7: (0.48, 0.44, 0.41, 0.36, 0.31, 0.28),
    8: (0.24, 0.24, 0.23, 0.20, 0.18, 0.16),
    9: (0.44, 0.38, 0.32, 0.25, 0.20, 0.16),
}

#: Coeficiente k da laje armada em uma só direção, por esquema estrutural
#: (1 = biapoiada, 2 = apoiada-engastada, 3 = biengastada, 4 = balanço).
K_FLECHA_1D = {1: 1.30, 2: 0.53, 3: 0.26, 4: 12.5}

# ---------------------------------------------------------------------------
# Momentos da laje armada em uma só direção (apostila §2, página 16)
# ---------------------------------------------------------------------------

#: Esquemas estruturais da laje armada em uma direção.
ESQUEMAS_1D = {
    1: "biapoiada",
    2: "apoiada em um bordo e engastada no outro",
    3: "engastada nos dois bordos",
    4: "em balanço",
}

#: Coeficientes de ``m = alfa . p . L²`` em **regime elástico**, usados no ELS.
#: ``vao`` é o momento positivo e ``engaste`` o negativo, em módulo.
ALFA_ELASTICO_1D = {
    1: {"vao": 1.0 / 8.0,   "engaste": 0.0},
    2: {"vao": 9.0 / 128.0, "engaste": 1.0 / 8.0},
    3: {"vao": 1.0 / 24.0,  "engaste": 1.0 / 12.0},
    4: {"vao": 0.0,         "engaste": 1.0 / 2.0},
}

#: Coeficientes em **regime rígido-plástico**, usados no ELU. É a redistribuição
#: das rótulas plásticas: o engaste alivia e o vão recebe o que ele soltou.
ALFA_PLASTICO_1D = {
    1: {"vao": 1.0 / 8.0,   "engaste": 0.0},
    2: {"vao": 1.0 / 13.32, "engaste": 1.0 / 8.88},
    3: {"vao": 1.0 / 20.0,  "engaste": 3.0 / 40.0},
    4: {"vao": 0.0,         "engaste": 1.0 / 2.0},
}

#: Reações de apoio da laje armada em uma direção, em parcelas de ``p . L``.
#: No esquema 2 a reação do engaste é ``p L / 2 + |mE| / L`` e a do apoio é
#: ``p L / 2 - |mE| / L``; aqui já com o mE do regime rígido-plástico.
REACOES_1D = {
    1: {"apoio": 0.500, "engaste": 0.000},
    2: {"apoio": 0.500 - 1.0 / 8.88, "engaste": 0.500 + 1.0 / 8.88},
    3: {"apoio": 0.000, "engaste": 0.500},
    4: {"apoio": 0.000, "engaste": 1.000},
}

# ---------------------------------------------------------------------------
# Reações de apoio em duas direções (Hahn, apostila §3.4, página 34)
# ---------------------------------------------------------------------------

#: Relações b/a tabeladas por Hahn.
RELACOES_BA = (1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.45,
               1.50, 1.55, 1.60, 1.80, 2.00)

#: Parcela da carga total da laje que vai a cada bordo, em milésimos.
#: ``va``/``vb`` valem quando os dois bordos daquela direção têm o mesmo
#: vínculo; ``vae``/``var`` (e ``vbe``/``vbr``) separam o engastado do
#: apoiado. Em toda linha a soma das quatro parcelas fecha 1000.
#:
#: A ordem das linhas na fonte **não** é a das tabelas de momento; a
#: correspondência foi levantada pela estrutura de cada linha (quais bordos
#: se distinguem) e conferida pela soma e pelos valores que se repetem entre
#: linhas -- o ``var`` do caso 6 em b/a = 2,00, por exemplo, é exatamente o
#: ``va`` do caso 1.
HAHN: dict[int, dict[str, tuple[float, ...]]] = {
    1: {"va":  (250, 238, 227, 217, 208, 200, 192, 185, 179, 173, 167, 161,
                156, 139, 125),
        "vb":  (250, 262, 273, 283, 292, 300, 308, 315, 321, 327, 333, 339,
                344, 361, 375)},
    2: {"va":  (250, 238, 227, 217, 208, 200, 192, 185, 179, 173, 167, 161,
                156, 139, 125),
        "vb":  (250, 262, 273, 283, 292, 300, 308, 315, 321, 327, 333, 339,
                344, 361, 375)},
    3: {"vae": (317, 302, 288, 276, 264, 254, 244, 235, 227, 219, 211, 204,
                198, 176, 159),
        "var": (183, 175, 167, 160, 153, 147, 141, 136, 131, 126, 122, 118,
                115, 102, 91),
        "vbe": (317, 332, 347, 359, 371, 381, 391, 400, 408, 416, 424, 431,
                437, 459, 476),
        "vbr": (183, 191, 198, 205, 212, 218, 224, 229, 234, 239, 243, 247,
                250, 263, 274)},
    4: {"va":  (356, 349, 341, 334, 327, 320, 312, 304, 297, 290, 283, 275,
                267, 241, 217),
        "vb":  (144, 151, 159, 166, 173, 180, 188, 196, 203, 210, 217, 225,
                233, 259, 283)},
    5: {"va":  (144, 137, 131, 125, 120, 115, 111, 107, 103, 99, 96, 93,
                90, 80, 72),
        "vb":  (356, 363, 369, 375, 380, 385, 389, 393, 397, 401, 404, 407,
                410, 420, 428)},
    6: {"vae": (402, 388, 378, 366, 355, 342, 331, 320, 310, 300, 289, 280,
                272, 241, 217),
        "var": (232, 226, 218, 212, 205, 198, 191, 184, 179, 173, 167, 161,
                156, 139, 125),
        "vb":  (183, 193, 202, 211, 220, 230, 239, 248, 256, 264, 272, 280,
                286, 310, 329)},
    7: {"va":  (183, 175, 167, 160, 153, 147, 141, 136, 131, 126, 122, 118,
                115, 102, 92),
        "vbe": (402, 412, 422, 431, 440, 447, 455, 461, 468, 474, 479, 484,
                488, 504, 517),
        "vbr": (232, 238, 244, 249, 254, 259, 263, 267, 270, 274, 277, 280,
                282, 292, 299)},
    8: {"vae": (250, 237, 227, 217, 208, 200, 192, 185, 179, 173, 166, 161,
                156, 138, 125),
        "var": (144, 137, 131, 125, 120, 114, 110, 107, 103, 99, 96, 93,
                90, 80, 71),
        "vb":  (303, 313, 321, 329, 336, 343, 349, 354, 359, 364, 369, 373,
                377, 391, 402)},
    9: {"va":  (304, 294, 284, 274, 264, 254, 244, 235, 227, 219, 211, 204,
                198, 176, 159),
        "vbe": (250, 263, 275, 288, 301, 314, 327, 339, 350, 360, 370, 378,
                387, 416, 437),
        "vbr": (142, 149, 157, 164, 171, 178, 185, 191, 196, 202, 208, 214,
                217, 232, 245)},
}


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def _interpolar(x: float, xs: tuple[float, ...],
                ys: tuple[float, ...]) -> float:
    """Interpolação linear em tabela crescente, com extremos constantes."""
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return float(ys[i] + (ys[i + 1] - ys[i]) * t)
    return float(ys[-1])


def caso_de(vinculos: tuple[int, int, int, int]) -> int | None:
    """Caso de vinculação (1 a 9) dos quatro bordos, ou None se houver livre.

    ``vinculos`` são os bordos 1 a 4 com :data:`APOIADO` ou
    :data:`ENGASTADO`. Bordo livre não tem tabela de placa: aquela laje é
    resolvida como armada em uma só direção.
    """
    if any(v == LIVRE for v in vinculos):
        return None
    return CASOS.get("".join(str(v) for v in vinculos))


def alfa_elastico(caso: int, a_sobre_b: float) -> dict[str, float]:
    """Coeficientes elásticos do caso, interpolados em a/b.

    Devolve as chaves presentes na tabela daquele caso -- ``ma``, ``mb`` e os
    negativos ``ma_`` e ``mb_`` que existirem.
    """
    linha = ALFA_ELASTICO[caso]
    return {k: _interpolar(a_sobre_b, RELACOES_AB, v)
            for k, v in linha.items()}


def k_flecha(caso: int, a_sobre_b: float) -> float:
    """Coeficiente k da flecha imediata, interpolado em a/b."""
    return _interpolar(a_sobre_b, RELACOES_AB, K_FLECHA[caso])


def hahn(caso: int, b_sobre_a: float) -> dict[str, float]:
    """Parcelas de Hahn do caso, interpoladas em b/a e já como frações.

    As chaves seguem a fonte: ``va``/``vb`` quando os dois bordos da direção
    têm o mesmo vínculo, ``vae``/``var`` e ``vbe``/``vbr`` quando não têm.
    """
    linha = HAHN[caso]
    return {k: _interpolar(b_sobre_a, RELACOES_BA, v) / 1000.0
            for k, v in linha.items()}


def conferir_tabelas() -> list[str]:
    """Confere a consistência interna das tabelas transcritas.

    Três verificações que pegam erro de digitação sem precisar da fonte:

    - toda linha de Hahn fecha 1000 milésimos, porque as quatro bordas
      recebem a carga inteira da laje. A fonte arredonda cada parcela
      isoladamente, então três linhas do caso 6 fecham 1001; a tolerância de
      um milésimo cobre esse arredondamento e ainda pega erro de digitação,
      que erra o dígito inteiro;
    - todo caso tem exatamente os componentes negativos que a vinculação
      pede -- ``mb_`` quando algum bordo de comprimento ``a`` é engastado e
      ``ma_`` quando é um de comprimento ``b``;
    - toda linha tem o mesmo número de colunas da respectiva abscissa.

    Devolve a lista de inconsistências; vazia significa tabela coerente.
    """
    erros: list[str] = []

    for caso, linha in HAHN.items():
        for i, ba in enumerate(RELACOES_BA):
            va = linha.get("va")
            vb = linha.get("vb")
            total = 0.0
            total += 2 * va[i] if va else linha["vae"][i] + linha["var"][i]
            total += 2 * vb[i] if vb else linha["vbe"][i] + linha["vbr"][i]
            if abs(total - 1000.0) > 1.0:
                erros.append(f"Hahn, caso {caso}, b/a = {ba:.2f}: as parcelas "
                             f"somam {total:.0f} em vez de 1000")

    for codigo, caso in CASOS.items():
        v = [int(c) for c in codigo]
        tem_mb_ = v[0] == ENGASTADO or v[2] == ENGASTADO   # bordos "a"
        tem_ma_ = v[1] == ENGASTADO or v[3] == ENGASTADO   # bordos "b"
        linha = ALFA_ELASTICO[caso]
        if tem_mb_ != ("mb_" in linha):
            erros.append(f"caso {caso} ({codigo}): mb' "
                         f"{'faltando' if tem_mb_ else 'sobrando'}")
        if tem_ma_ != ("ma_" in linha):
            erros.append(f"caso {caso} ({codigo}): ma' "
                         f"{'faltando' if tem_ma_ else 'sobrando'}")

    for caso, linha in ALFA_ELASTICO.items():
        for nome, valores in linha.items():
            if len(valores) != len(RELACOES_AB):
                erros.append(f"alfa elástico, caso {caso}, {nome}: "
                             f"{len(valores)} colunas")
    for caso, valores in K_FLECHA.items():
        if len(valores) != len(RELACOES_AB):
            erros.append(f"k de flecha, caso {caso}: {len(valores)} colunas")
    for caso, linha in HAHN.items():
        for nome, valores in linha.items():
            if len(valores) != len(RELACOES_BA):
                erros.append(f"Hahn, caso {caso}, {nome}: "
                             f"{len(valores)} colunas")
    return erros
