# -*- coding: utf-8 -*-
"""
alveolar_modelo.py
Dados de entrada da laje alveolar protendida (pré-tração, biapoiada, com ou
sem capa): a seção do painel, a protensão, os materiais, as cargas e os
critérios de verificação.

Convenções:
    comprimentos da seção ... cm;  vão e flechas ... m (flechas mostradas em
    cm/mm só na apresentação);  forças kN;  momentos kN·m;  tensões MPa;
    cargas superficiais kN/m², lineares kN/m **por painel** (largura ``b``).

Fontes das fórmulas (todas em ``alveolar.py``): ABNT NBR 6118:2026 (itens
9.4.5, 9.6, 13.4, 17.4.1), ABNT NBR 14861 (conforme transcrita nos manuais),
Gramalho (2013, cap. 5) e Ferro (2020, cap. 2). A NBR 14861 não foi lida
diretamente -- ver o aviso no relatório.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import pi

# ---------------------------------------------------------------------------
#  Armadura ativa
# ---------------------------------------------------------------------------

#: Cordoalhas de 7 fios (NBR 7483): bitola nominal em mm -> área nominal, mm².
CORDOALHAS = {6.4: 26.5, 7.9: 39.6, 9.5: 54.8, 11.1: 74.2, 12.7: 98.7,
              15.2: 140.0}

#: Aços de protensão de relaxação baixa: designação -> fptk, MPa.
ACOS_PROTENSAO = {"CP 190 RB": 1900.0, "CP 210 RB": 2100.0}

#: ψ1000 (relaxação a 1000 h, 20 °C) em função de σpi/fptk (NBR 6118, Tabela
#: de relaxação; interpolação linear). Pares (σ/fptk, ψ1000 em %).
PSI_1000 = ((0.5, 0.0), (0.6, 1.3), (0.7, 2.5), (0.8, 3.5))

#: Cimentos: s da função βdi (fluência) e α da maturidade (NBR 6118, A.2).
#: ``alfa_e``: natureza do agregado, afeta o módulo (8.2.8).
CIMENTOS = {"CP I / CP II": (0.25, 2), "CP III / CP IV": (0.38, 1),
            "CP V-ARI": (0.20, 3)}

AGREGADOS = {"Granito / gnaisse": 1.0, "Basalto / diabásio": 1.2,
             "Calcário": 0.9, "Arenito": 0.7}

#: Fatores de largura de seção usados quando só se conhece a altura.
LARGURA_PADRAO = 120.0   # cm (painel de 1,20 m)


# ---------------------------------------------------------------------------
#  Seção do painel
# ---------------------------------------------------------------------------

@dataclass
class SecaoAlveolar:
    """Propriedades da seção **simples** (só o painel pré-moldado).

    Todas vêm do catálogo do fabricante ou de ``secao_parametrica``.
    ``yi`` é a distância do centro de gravidade à face inferior.
    """

    h: float                 # cm, altura
    b: float                 # cm, largura do painel
    Ac: float                # cm²
    yi: float                # cm
    I: float                 # cm⁴
    sum_bw: float            # cm, soma das nervuras (menor largura de alma)
    perim_alveolos: float = 0.0   # cm, perímetro total dos alvéolos
    tf_sup: float = 0.0      # cm, mesa superior (só para avisos)
    tf_inf: float = 0.0      # cm, mesa inferior
    n_alveolos: int = 0
    origem: str = "informada"

    @property
    def ys(self) -> float:
        return self.h - self.yi

    @property
    def Wi(self) -> float:
        return self.I / self.yi

    @property
    def Ws(self) -> float:
        return self.I / self.ys

    def dados(self) -> dict:
        return dict(h=self.h, b=self.b, Ac=self.Ac, yi=self.yi, I=self.I,
                    sum_bw=self.sum_bw, perim_alveolos=self.perim_alveolos,
                    tf_sup=self.tf_sup, tf_inf=self.tf_inf,
                    n_alveolos=self.n_alveolos, origem=self.origem)


#: Seções genéricas **aproximadas** por altura (cm): (n alvéolos, largura do
#: alvéolo, mesa inferior, mesa superior, raio de canto, cm). Os alvéolos são
#: retangulares com cantos arredondados; as dimensões foram calibradas para
#: reproduzir a ordem de grandeza de Ac e Σbw dos painéis publicados nas
#: fontes (h = 20: 1290 cm², Σbw = 32 cm) -- **não são de nenhum fabricante**.
#: Para projeto, informe as propriedades do catálogo.
SECOES_GENERICAS = {
    15.0: (8, 10.5, 3.0, 3.0, 2.0),
    20.0: (6, 14.67, 3.5, 3.5, 2.5),
    26.5: (6, 14.67, 4.0, 4.0, 3.0),
    32.0: (5, 18.0, 4.5, 4.5, 3.5),
    40.0: (5, 18.5, 5.0, 5.0, 4.0),
}


def secao_parametrica(h: float, b: float = LARGURA_PADRAO, *,
                      n: int | None = None, a: float | None = None,
                      tf_inf: float | None = None,
                      tf_sup: float | None = None,
                      r: float | None = None) -> SecaoAlveolar:
    """Seção retangular b × h com ``n`` alvéolos de cantos arredondados.

    O que não for dado vem de ``SECOES_GENERICAS`` (altura mais próxima).
    Área, centroide e inércia são exatos para essa geometria; os alvéolos
    ficam centrados na altura livre entre as mesas.
    """
    h0 = min(SECOES_GENERICAS, key=lambda k: abs(k - h))
    n0, a0, ti0, ts0, r0 = SECOES_GENERICAS[h0]
    esc = h / h0
    n = n0 if n is None else int(n)
    a = (a0 if n == n0 else (b - 30.0) / max(n, 1)) if a is None else a
    tf_inf = ti0 * esc if tf_inf is None else tf_inf
    tf_sup = ts0 * esc if tf_sup is None else tf_sup
    r = r0 * esc if r is None else r
    hv = h - tf_inf - tf_sup                      # altura do alvéolo
    if n <= 0 or hv <= 0 or a <= 0:
        return SecaoAlveolar(h=h, b=b, Ac=b * h, yi=h / 2.0,
                             I=b * h ** 3 / 12.0, sum_bw=b,
                             tf_sup=tf_sup, tf_inf=tf_inf, origem="maciça")
    r = min(r, a / 2.0, hv / 2.0)
    # retângulo a × hv com quatro cantos de raio r
    a_v = a * hv - (4.0 - pi) * r * r
    # inércia do alvéolo em torno do próprio centro (x horizontal):
    #   retângulo cheio - 4 "quartos de canto" (área r²(1-π/4), cg em
    #   (a/2 - r + c, hv/2 - r + c) com c = 4r/(3(4-π)) ... usa-se a forma
    #   exata por composição retângulo-círculo)
    i_v = _inercia_retangulo_arredondado(a, hv, r)
    yv = tf_inf + hv / 2.0                        # centro dos alvéolos
    A0 = b * h
    A = A0 - n * a_v
    yi = (A0 * h / 2.0 - n * a_v * yv) / A
    I0 = b * h ** 3 / 12.0 + A0 * (h / 2.0 - yi) ** 2
    Iv = n * (i_v + a_v * (yv - yi) ** 2)
    I = I0 - Iv
    perim = n * (2.0 * (a - 2.0 * r) + 2.0 * (hv - 2.0 * r) + 2.0 * pi * r)
    return SecaoAlveolar(h=h, b=b, Ac=A, yi=yi, I=I, sum_bw=b - n * a,
                         perim_alveolos=perim, tf_sup=tf_sup, tf_inf=tf_inf,
                         n_alveolos=n, origem="paramétrica (genérica)")


def _inercia_retangulo_arredondado(a: float, hv: float, r: float) -> float:
    """Inércia, em torno do centro e do eixo horizontal, de um retângulo
    a × hv com os quatro cantos arredondados em raio r."""
    i_ret = a * hv ** 3 / 12.0
    if r <= 0.0:
        return i_ret
    # quarto de círculo de raio r dentro de um quadrado r × r: o canto
    # "removido" = quadrado - quarto de círculo.
    a_q = r * r * (1.0 - pi / 4.0)
    # centroide do canto removido a partir do vértice do quadrado r × r
    # (a região do canto é quadrado menos quarto de círculo centrado no
    # vértice oposto): c = (r/3) * (3 - ... ) calculado por composição
    c_circ = 4.0 * r / (3.0 * pi)          # cg do quarto de círculo
    a_circ = pi * r * r / 4.0
    # quarto de círculo centrado no vértice interno (r, r) em coordenadas do
    # quadrado [0,r]²: seu cg fica em (r - c_circ, r - c_circ)
    cg_circ = r - c_circ
    cg_quad = r / 2.0
    cg_canto = (r * r * cg_quad - a_circ * cg_circ) / a_q
    # inércia do canto removido em torno do próprio cg (eixo horizontal)
    i_quad = r ** 4 / 12.0 + r * r * (cg_quad - cg_canto) ** 2
    i_qc = (pi / 16.0 - 4.0 / (9.0 * pi)) * r ** 4 \
        + a_circ * (cg_circ - cg_canto) ** 2
    i_canto = i_quad - i_qc
    # distância vertical do cg do canto ao centro do alvéolo
    d = hv / 2.0 - cg_canto
    return i_ret - 4.0 * (i_canto + a_q * d * d)


# ---------------------------------------------------------------------------
#  A laje
# ---------------------------------------------------------------------------

@dataclass
class LajeAlveolar:
    """Um painel de laje alveolar protendida biapoiado."""

    nome: str = "A1"
    # -- geometria ----------------------------------------------------------
    vao: float = 8.0                    # m, vão teórico (eixo a eixo)
    secao: SecaoAlveolar | None = None  # None -> paramétrica de ``h``
    h: float = 20.0                     # cm, altura do painel
    capa: float = 5.0                   # cm, 0 = sem capa
    largura_capa: float | None = None   # cm; None -> largura do painel
    homogeneizar_capa: bool = True      # capa com outro Ec vira seção equiv.
    # -- materiais ----------------------------------------------------------
    fck: float = 40.0                   # MPa, painel
    fckj: float = 25.0                  # MPa, painel na protensão
    fck_capa: float = 30.0              # MPa
    agregado: str = "Granito / gnaisse"
    cimento: str = "CP V-ARI"
    gamma_c: float = 1.4                # combinações normais (NBR 6118)
    gamma_c_prefab: float = 1.3         # concreto pré-moldado (NBR 14861)
    usar_gamma_prefab: bool = True      # na tabela de tensões do manual
    gamma_s: float = 1.15
    # -- protensão ----------------------------------------------------------
    aco: str = "CP 190 RB"
    phi: float = 9.5                    # mm
    area_cordoalha: float | None = None  # mm²; None -> da tabela
    n_cordoalhas: int = 8
    d_linha: float = 4.0                # cm, face inferior ao CG das cordoalhas
    sigma_pi: float = 1400.0            # MPa, na saída do macaco
    Ep: float = 200000.0                # MPa
    # perdas ---------------------------------------------------------------
    perdas_modo: str = "simplificado"   # "simplificado" | "nbr"
    perda_imediata: float = 5.0         # %, no ato (modo simplificado)
    perda_total: float = 20.0           # %, ao fim do tempo (idem)
    pista: float = 100.0                # m, comprimento da pista (modo nbr)
    escorregamento: float = 6.0         # mm, encunhamento na ancoragem
    t_liberacao: float = 20.0           # h, do estiramento à liberação
    idade_protensao: float = 1.0        # dias (20 h ≈ 0,83 d)
    umidade: float = 70.0               # %, UR média
    temperatura: float = 20.0           # °C
    slump: float = 7.0                  # cm
    liberacao_gradual: bool = True      # ×1,25 em lbpt se não for gradual
    # -- cargas -------------------------------------------------------------
    g2: float = 1.5                     # kN/m², revestimento etc.
    q: float = 3.0                      # kN/m², sobrecarga
    psi1: float = 0.6
    psi2: float = 0.4
    gamma_g: float = 1.4
    gamma_q: float = 1.4
    acrescimo_chave: float = 2.5        # %, peso do chaveteamento
    peso_especifico: float = 25.0       # kN/m³
    # -- critérios ----------------------------------------------------------
    nivel_protensao: int = 2            # 1, 2 ou 3 (NBR 6118, Tab. 13.4)
    alfa_f: float = 1.2                 # fct,f = αf·fctk,inf (13.4.2)
    lim_flecha_den: float = 250.0       # flecha total ≤ L/den
    lim_contra_den: float = 350.0       # contraflecha ≤ L/den
    lim_flecha_ini_den: float = 500.0   # flecha líquida no ato ≤ L/den
    phi_flecha: float = 2.0             # coef. de fluência para as flechas
    q_flecha_inteira: bool = False      # q inteira na flecha (manual)
    encapar: int = 0                    # cordoalhas isoladas nas pontas
    encapar_comp: float = 0.0           # m, comprimento do isolamento
    # -- opções que reproduzem o material de referência ---------------------
    fctd_com_fctm: bool = False         # manual: fctd = fctm/γc (nº 50)
    excentr_perda_simples: bool = False  # manual: e da perda na seção simples
    # -- custo (só para a escolha automática) -------------------------------
    custo_concreto: float = 450.0       # R$/m³, painel
    custo_aco: float = 10.0             # R$/kg, cordoalha
    # -- escolha automática --------------------------------------------------
    automatica: bool = False

    def __post_init__(self) -> None:
        if self.secao is not None and not isinstance(self.secao,
                                                     SecaoAlveolar):
            self.secao = SecaoAlveolar(**self.secao)

    # -- derivados ----------------------------------------------------------
    @property
    def sec(self) -> SecaoAlveolar:
        if self.secao is not None:
            return self.secao
        return secao_parametrica(self.h)

    @property
    def b(self) -> float:
        """Largura do painel, m."""
        return self.sec.b / 100.0

    @property
    def Ap1(self) -> float:
        """Área de uma cordoalha, cm²."""
        a = self.area_cordoalha
        if a is None:
            a = CORDOALHAS.get(self.phi, pi * self.phi ** 2 / 4.0 * 0.78)
        return a / 100.0

    @property
    def Ap(self) -> float:
        return self.n_cordoalhas * self.Ap1

    @property
    def fptk(self) -> float:
        return ACOS_PROTENSAO[self.aco]
