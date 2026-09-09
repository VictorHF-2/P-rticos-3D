# -*- coding: utf-8 -*-
"""
esforcos.py
Momentos fletores das lajes maciças retangulares, nos dois regimes que o
projeto usa:

    **regime elástico** (apostila §3.1) -- ``m = alfa . p . a²`` com o alfa
    tabelado. É o regime dos estados limites de serviço: tratar o concreto
    armado como elástico é boa aproximação sob carga de serviço.

    **regime rígido-plástico** (apostila §3.2) -- método das linhas de
    ruptura. É o regime do estado limite último: na ruptura o concreto armado
    se comporta como rígido-plástico, e é dele que sai a armadura.

A classificação da laje vem antes dos dois: armada em uma só direção ou em
cruz. A relação entre os lados decide (b/a > 2 é uma direção só), mas a
vinculação tem precedência -- laje suportada em apenas dois bordos paralelos,
ou em balanço, é armada em uma direção qualquer que seja a relação (§1.2).

Convenção dos bordos, repetida aqui porque é a fonte de confusão do assunto:
os bordos 1 e 3 medem ``a`` e estão separados por ``b``; os bordos 2 e 4
medem ``b`` e estão separados por ``a``. Logo os bordos 2 e 4 apoiam a faixa
que vaza na direção ``a``, e os bordos 1 e 3 apoiam a que vaza na direção
``b``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import tabelas as tb
from .materiais import gamma_n
from .modelo import Config, Laje

# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------

CRUZ, UMA_DIRECAO = "cruz", "uma direção"

#: Bordos que apoiam cada direção: a direção ``a`` vaza entre os bordos 2 e 4.
BORDOS_DA_DIRECAO = {"a": (2, 4), "b": (1, 3)}

#: Fatores de momento da carga linear perpendicular ao vão, em parcelas de
#: ``P . L``, na posição mais desfavorável de cada esquema estrutural. São as
#: envoltórias elásticas exatas da carga concentrada -- a apostila §2.2 manda
#: resolver o caso pelo método das rótulas plásticas e não dá formulário, e
#: usar a envoltória elástica em toda posição é o que sobra a favor da
#: segurança, como a própria apostila autoriza em §3.2(b).
FATOR_CONCENTRADA = {
    1: {"vao": 0.2500, "engaste": 0.0000},     # biapoiada: P L / 4
    2: {"vao": 0.1740, "engaste": 0.1925},     # apoiada-engastada
    3: {"vao": 0.1250, "engaste": 0.1481},     # biengastada
    4: {"vao": 0.0000, "engaste": 1.0000},     # balanço: P L
}


@dataclass
class Classificacao:
    """Como a laje vaza: em cruz ou em uma direção, e qual é essa direção."""

    tipo: str                       # CRUZ ou UMA_DIRECAO
    direcao: str = ""               # "a" ou "b", quando é uma direção só
    caso: int | None = None         # caso de vinculação 1..9 (em cruz)
    esquema: int | None = None      # esquema estrutural 1..4 (uma direção)
    motivo: str = ""

    @property
    def em_cruz(self) -> bool:
        return self.tipo == CRUZ

    @property
    def balanco(self) -> bool:
        return self.esquema == 4


def _apoiado(laje: Laje, bordo: int) -> bool:
    """O bordo suporta a laje (é apoiado ou engastado)."""
    return laje.bordos[bordo - 1].vinculo != "livre"


def _esquema_1d(laje: Laje, direcao: str) -> int:
    """Esquema estrutural (1 a 4) da faixa que vaza na direção dada.

    O produto dos códigos dos dois bordos que apoiam a faixa resolve os
    quatro casos: 1x1 é biapoiada, 1x2 é apoiada-engastada, 2x2 é
    biengastada, e qualquer produto nulo (algum bordo livre) é balanço.
    """
    i, j = BORDOS_DA_DIRECAO[direcao]
    produto = laje.bordos[i - 1].codigo * laje.bordos[j - 1].codigo
    return {1: 1, 2: 2, 4: 3}.get(produto, 4)


def classificar(laje: Laje) -> Classificacao:
    """Decide se a laje é armada em cruz ou em uma só direção."""
    apoia_a = [_apoiado(laje, k) for k in BORDOS_DA_DIRECAO["a"]]
    apoia_b = [_apoiado(laje, k) for k in BORDOS_DA_DIRECAO["b"]]
    dois_em_a = all(apoia_a)
    dois_em_b = all(apoia_b)

    if laje.em_balanco:
        # o único bordo vinculado é o engaste; a faixa vaza para longe dele
        vinculado = next(k for k in (1, 2, 3, 4) if _apoiado(laje, k))
        direcao = "b" if vinculado in BORDOS_DA_DIRECAO["b"] else "a"
        return Classificacao(UMA_DIRECAO, direcao, esquema=4,
                             motivo="laje em balanço: três bordos livres")

    if dois_em_a and not dois_em_b:
        return Classificacao(
            UMA_DIRECAO, "a", esquema=_esquema_1d(laje, "a"),
            motivo="apoiada só nos dois bordos de comprimento b, logo armada "
                   "em uma direção qualquer que seja a relação entre os lados "
                   "(§1.2)")
    if dois_em_b and not dois_em_a:
        return Classificacao(
            UMA_DIRECAO, "b", esquema=_esquema_1d(laje, "b"),
            motivo="apoiada só nos dois bordos de comprimento a, logo armada "
                   "em uma direção qualquer que seja a relação entre os lados "
                   "(§1.2)")
    if not dois_em_a and not dois_em_b:
        # nem uma direção fecha os dois apoios: a laje não se sustenta
        return Classificacao(UMA_DIRECAO, "a", esquema=4,
                             motivo="vinculação insuficiente")

    # as duas direções têm os dois apoios
    caso = tb.caso_de(laje.vinculos)
    if caso is None:
        # há bordo livre com as duas direções apoiadas -- não ocorre, porque
        # um bordo livre zera um dos pares; guarda de segurança
        direcao = "a" if laje.a <= laje.b else "b"
        return Classificacao(UMA_DIRECAO, direcao,
                             esquema=_esquema_1d(laje, direcao),
                             motivo="vinculação sem tabela de placa")
    if laje.b_ef / laje.a_ef > 2.0:
        return Classificacao(
            UMA_DIRECAO, "a", esquema=_esquema_1d(laje, "a"), caso=caso,
            motivo=f"b/a = {laje.b_ef / laje.a_ef:.2f} > 2, logo armada em "
                   f"uma só direção (§1.2)")
    return Classificacao(
        CRUZ, caso=caso,
        motivo=f"b/a = {laje.b_ef / laje.a_ef:.2f} <= 2 e os quatro bordos "
               f"vinculados: armada em duas direções, caso "
               f"{caso} ({tb.DESCRICAO_CASO[caso]})")


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class Esforcos:
    """Momentos de uma laje, nos dois regimes, em kN·m/m."""

    laje: str
    classificacao: Classificacao

    # -- cargas -------------------------------------------------------------
    g: float = 0.0                  # kN/m², permanente superficial
    q: float = 0.0                  # kN/m², variável
    g_paredes: float = 0.0          # kN/m², paredes espalhadas
    p_d: float = 0.0                # kN/m², de cálculo (ELU)
    p_ser: float = 0.0              # kN/m², quase permanente (ELS)
    gamma_n: float = 1.0

    # -- ELU (regime rígido-plástico) --------------------------------------
    ma: float = 0.0                 # momento positivo na direção a
    mb: float = 0.0                 # momento positivo na direção b
    m_neg: dict[int, float] = field(default_factory=dict)   # bordo -> |m'|

    # -- ELS (regime elástico) ---------------------------------------------
    ma_ser: float = 0.0
    mb_ser: float = 0.0
    m_neg_ser: dict[int, float] = field(default_factory=dict)

    # -- ortotropia e vãos reduzidos (em cruz) -----------------------------
    phi: float = 1.0
    ar: float = 0.0
    br: float = 0.0
    br_estrela: float = 0.0
    p_estrela: float = 0.0
    alfa_parede: float = 0.0
    beta_parede: float = 0.0
    isotropa: bool = True

    # -- coeficientes usados (para a memória) ------------------------------
    alfas_elasticos: dict[str, float] = field(default_factory=dict)
    k_flecha: float = 0.0
    vao_referencia: float = 0.0     # m, o vão que governa a flecha

    # -- faixa de parede paralela ao vão (uma direção) ---------------------
    faixas: list["Faixa"] = field(default_factory=list)

    avisos: list[str] = field(default_factory=list)

    @property
    def m_ser_maximo(self) -> float:
        """Momento de serviço da seção crítica (§1.6-d).

        É o máximo momento de vão em laje apoiada ou contínua, e o momento do
        apoio em laje em balanço -- onde não há momento de vão nenhum.
        """
        candidatos = [self.ma_ser, self.mb_ser]
        if self.classificacao.balanco:
            candidatos = list(self.m_neg_ser.values()) or [0.0]
        return max(candidatos) if candidatos else 0.0

    def momento_da_direcao(self, direcao: str) -> float:
        return self.ma if direcao == "a" else self.mb


@dataclass
class Faixa:
    """Faixa de laje armada em uma direção com carga linear paralela ao vão.

    A carga de parede paralela ao vão não se espalha na laje toda: ela se
    difunde a 45° até o plano médio e carrega uma faixa de largura ``bw``
    (§2.1). O programa dimensiona duas faixas -- a que tem a parede e a que
    não tem --, porque a armadura de uma não serve para a outra.
    """

    nome: str
    largura: float                  # cm, bw
    p_d: float = 0.0                # kN/m² dentro da faixa
    p_ser: float = 0.0
    m_vao: float = 0.0              # kN·m/m
    m_eng: float = 0.0
    m_vao_ser: float = 0.0
    m_eng_ser: float = 0.0
    bw_vao: float = 0.0             # cm
    bw_eng: float = 0.0
    a1: float = 0.0                 # cm, distância do eixo da parede ao apoio
    b_difusao: float = 0.0          # cm, t + h
    descricao: str = ""


# ---------------------------------------------------------------------------
# Combinações
# ---------------------------------------------------------------------------

def _combinar_variaveis(cfg: Config, principais: list[float]) -> float:
    """Maior combinação de ações variáveis com uma delas como principal.

    Item 11.7.1: a variável principal entra inteira e as outras com psi_0.
    Com uma só ação variável a expressão recai no valor dela.
    """
    valores = [v for v in principais if abs(v) > 1e-12]
    if not valores:
        return 0.0
    if len(valores) == 1:
        return valores[0]
    return max(v + cfg.psi_0 * (sum(valores) - v) for v in valores)


def _combinar_servico(cfg: Config, principais: list[float]) -> float:
    """Combinação quase permanente de serviço: psi_2 em toda variável."""
    return cfg.psi_2 * sum(principais)


# ---------------------------------------------------------------------------
# Laje armada em uma só direção
# ---------------------------------------------------------------------------

def _difusao(parede, h: float) -> float:
    """Largura ``b = t + h`` da carga difundida a 45° até o plano médio."""
    return parede.espessura + h


def _delta_bw(a1: float, b: float, L: float, tipo: str) -> float:
    """Acréscimo ``delta`` da largura de influência da parede (§2.1), cm.

    ``a1`` é a distância do centro da carga ao apoio do lado da seção que se
    estuda, ``b`` a largura já difundida e ``L`` o vão. As três expressões da
    apostila -- momento positivo, negativo e de balanço.
    """
    if L <= 0.0:
        return 0.0
    fator = 1.0 - b / L
    if fator <= 0.0:
        return 0.0
    if tipo == "vao":
        return 2.0 * a1 * (1.0 - a1 / L) * fator
    if tipo == "engaste":
        return a1 * (2.0 - a1 / L) * fator
    return 1.5 * a1 * fator                       # balanço


def _esforcos_uma_direcao(laje: Laje, cls: Classificacao, cfg: Config,
                          gn: float) -> Esforcos:
    """Momentos da laje armada em uma só direção."""
    direcao = cls.direcao
    L = laje.vao_efetivo(direcao)
    esquema = cls.esquema or 1
    plastico = tb.ALFA_PLASTICO_1D[esquema]
    elastico = tb.ALFA_ELASTICO_1D[esquema]

    g = laje.g_superficial
    q = laje.variavel

    paralelas = [p for p in laje.paredes if p.direcao == direcao]
    perpendiculares = [p for p in laje.paredes if p.direcao != direcao]

    esf = Esforcos(laje=laje.nome, classificacao=cls, g=g, q=q, gamma_n=gn)
    esf.vao_referencia = L
    esf.k_flecha = tb.K_FLECHA_1D[esquema]
    esf.alfas_elasticos = dict(elastico)

    # -- carga linear perpendicular ao vão: entra como carga concentrada ----
    fator = FATOR_CONCENTRADA[esquema]
    m_perp_vao = sum(p.carga for p in perpendiculares) * L * fator["vao"]
    m_perp_eng = sum(p.carga for p in perpendiculares) * L * fator["engaste"]
    if perpendiculares:
        esf.avisos.append(
            f"{laje.nome}: a parede perpendicular ao vão foi lançada como "
            f"carga concentrada na posição mais desfavorável, com a "
            f"envoltória elástica -- a apostila §2.2 remete ao método das "
            f"rótulas plásticas e não traz formulário fechado.")

    # -- carga variável de borda livre --------------------------------------
    m_qv_vao = m_qv_eng = m_qh_vao = m_qh_eng = 0.0
    if laje.borda_livre is not None and esquema == 4:
        # balanço de verdade: não existe momento de vão nenhum -- o
        # corrimão empurra a ponta livre, e todo o efeito, vertical ou
        # horizontal, vai inteiro para o engaste (a mesma razão por que só
        # m_qv_eng, e não m_qv_vao, é preenchido logo abaixo)
        bl = laje.borda_livre
        m_qv_eng = bl.vertical * L
        m_qh_eng = bl.horizontal * bl.altura_corrimao
    elif laje.borda_livre is not None:
        bl = laje.borda_livre
        m_qv_vao = bl.vertical * L * fator["vao"]
        m_qv_eng = bl.vertical * L * fator["engaste"]
        m_qh_vao = bl.horizontal * bl.altura_corrimao * fator["vao"]
        m_qh_eng = bl.horizontal * bl.altura_corrimao * fator["engaste"]

    # -- faixa sem parede paralela -----------------------------------------
    def montar_faixa(nome: str, g_faixa: float, bw_vao: float, bw_eng: float,
                     a1: float, b_dif: float, descricao: str) -> Faixa:
        mg_vao = plastico["vao"] * g_faixa * L ** 2
        mg_eng = plastico["engaste"] * g_faixa * L ** 2
        mq_vao = plastico["vao"] * q * L ** 2
        mq_eng = plastico["engaste"] * q * L ** 2
        variaveis_vao = [mq_vao + m_perp_vao, m_qv_vao, m_qh_vao]
        variaveis_eng = [mq_eng + m_perp_eng, m_qv_eng, m_qh_eng]
        m_vao = gn * (cfg.gamma_g * mg_vao
                      + cfg.gamma_q * _combinar_variaveis(cfg, variaveis_vao))
        m_eng = gn * (cfg.gamma_g * mg_eng
                      + cfg.gamma_q * _combinar_variaveis(cfg, variaveis_eng))
        # serviço, combinação quase permanente
        mg_vao_s = elastico["vao"] * g_faixa * L ** 2
        mg_eng_s = elastico["engaste"] * g_faixa * L ** 2
        m_vao_s = mg_vao_s + _combinar_servico(
            cfg, [elastico["vao"] * q * L ** 2, m_perp_vao, m_qv_vao,
                  m_qh_vao])
        m_eng_s = mg_eng_s + _combinar_servico(
            cfg, [elastico["engaste"] * q * L ** 2, m_perp_eng, m_qv_eng,
                  m_qh_eng])
        return Faixa(nome=nome, largura=bw_vao, p_d=cfg.gamma_g * g_faixa
                     + cfg.gamma_q * q, p_ser=g_faixa + cfg.psi_2 * q,
                     m_vao=m_vao, m_eng=m_eng, m_vao_ser=m_vao_s,
                     m_eng_ser=m_eng_s, bw_vao=bw_vao, bw_eng=bw_eng,
                     a1=a1, b_difusao=b_dif, descricao=descricao)

    esf.faixas.append(montar_faixa(
        "sem parede", g, 100.0, 100.0, 0.0, 0.0,
        "faixa de 1 m fora da influência das paredes paralelas ao vão"))

    for k, parede in enumerate(paralelas, start=1):
        b_dif = _difusao(parede, laje.h)
        pos = parede.posicao
        a1 = (L / 2.0 if pos is None else min(max(pos, 0.0), L)) * 100.0
        if esquema == 4:
            bw_v = bw_e = b_dif + _delta_bw(a1, b_dif, L * 100.0, "balanco")
        else:
            bw_v = b_dif + _delta_bw(a1, b_dif, L * 100.0, "vao")
            bw_e = b_dif + _delta_bw(a1, b_dif, L * 100.0, "engaste")
        # a parede carrega a faixa: a linha de carga espalhada na largura bw
        g_faixa = g + parede.carga / (bw_v / 100.0)
        nome = parede.descricao or f"faixa da parede {k}"
        esf.faixas.append(montar_faixa(
            nome, g_faixa, bw_v, bw_e, a1, b_dif,
            f"faixa de {bw_v:.0f} cm sob a parede de "
            f"{parede.espessura:g} cm ({parede.carga:.2f} kN/m), "
            f"difusão a 45° com b = t + h = {b_dif:.0f} cm"))

    # a laje é dimensionada pela faixa mais solicitada de cada seção
    esf.p_d = max(f.p_d for f in esf.faixas)
    esf.p_ser = max(f.p_ser for f in esf.faixas)
    m_vao = max(f.m_vao for f in esf.faixas)
    m_eng = max(f.m_eng for f in esf.faixas)
    m_vao_s = max(f.m_vao_ser for f in esf.faixas)
    m_eng_s = max(f.m_eng_ser for f in esf.faixas)

    if direcao == "a":
        esf.ma, esf.ma_ser = m_vao, m_vao_s
    else:
        esf.mb, esf.mb_ser = m_vao, m_vao_s
    for bordo in BORDOS_DA_DIRECAO[direcao]:
        if laje.bordos[bordo - 1].vinculo == "engastado":
            esf.m_neg[bordo] = m_eng
            esf.m_neg_ser[bordo] = m_eng_s
    return esf


# ---------------------------------------------------------------------------
# Laje armada em duas direções
# ---------------------------------------------------------------------------

def _esforcos_em_cruz(laje: Laje, cls: Classificacao, cfg: Config,
                      gn: float) -> Esforcos:
    """Momentos da laje armada em cruz.

    O ELU sai do método das linhas de ruptura (§3.2) e o ELS da tabela de
    coeficientes elásticos (§3.1). São dois caminhos independentes: o
    primeiro dá a armadura, o segundo dá a flecha e a fissuração.
    """
    caso = cls.caso or 1
    a, b = laje.a_ef, laje.b_ef
    i1, i2, i3, i4 = laje.graus

    g_sup = laje.g_superficial
    q = laje.variavel
    g_par = laje.g_paredes_distribuida()

    esf = Esforcos(laje=laje.nome, classificacao=cls, g=g_sup, q=q,
                   g_paredes=g_par, gamma_n=gn)
    esf.vao_referencia = a

    # -- coeficiente de ortotropia (§3.2 a.2) ------------------------------
    a_sobre_b = a / b
    if a_sobre_b >= 0.8:
        phi = 1.0
        esf.isotropa = True
    else:
        phi = ((12.0 - i2 - i4) / (12.0 - i1 - i3)) * a_sobre_b ** 1.7
        esf.isotropa = False
    esf.phi = phi

    # -- vãos reduzidos ----------------------------------------------------
    ar = 2.0 * a / (math.sqrt(1.0 + i2) + math.sqrt(1.0 + i4))
    br = 2.0 * b / (math.sqrt(1.0 + i1) + math.sqrt(1.0 + i3))
    esf.ar, esf.br = ar, br

    # -- cargas lineares: alfa e beta (§3.2 b) -----------------------------
    # p é a carga superficial; as paredes entram pelos coeficientes, e não
    # espalhadas -- espalhar e ainda aplicar (1 + alfa + 2 beta) contaria a
    # parede duas vezes.
    p_sup_d = cfg.gamma_g * g_sup + cfg.gamma_q * q
    p_a = sum(p.carga for p in laje.paredes if p.direcao == "a")
    p_b = sum(p.carga for p in laje.paredes if p.direcao == "b")
    alfa = cfg.gamma_g * p_a / (p_sup_d * b) if p_sup_d > 0 else 0.0
    beta = cfg.gamma_g * p_b / (p_sup_d * a) if p_sup_d > 0 else 0.0
    esf.alfa_parede, esf.beta_parede = alfa, beta

    p_estrela = p_sup_d * (1.0 + alfa + 2.0 * beta)
    br_estrela = (br / math.sqrt(phi)) * math.sqrt(
        (1.0 + alfa + 2.0 * beta) / (1.0 + 3.0 * beta))
    esf.p_estrela, esf.br_estrela = p_estrela, br_estrela
    esf.p_d = p_sup_d

    # -- momento no vão ----------------------------------------------------
    m = (p_estrela / 8.0) * (ar * br_estrela) / (
        1.0 + ar / br_estrela + br_estrela / ar)
    esf.ma = gn * m
    esf.mb = gn * phi * m

    # -- momentos nos engastes: m'k = -ik . m da direção que o bordo apoia -
    for bordo, i in enumerate((i1, i2, i3, i4), start=1):
        if i <= 0.0:
            continue
        base = esf.mb if bordo in BORDOS_DA_DIRECAO["b"] else esf.ma
        esf.m_neg[bordo] = i * base

    # -- ELS: regime elástico, combinação quase permanente ------------------
    p_ser = g_sup + g_par + cfg.psi_2 * q
    esf.p_ser = p_ser
    alfas = tb.alfa_elastico(caso, a_sobre_b)
    esf.alfas_elasticos = alfas
    esf.k_flecha = tb.k_flecha(caso, a_sobre_b)
    esf.ma_ser = alfas["ma"] * p_ser * a ** 2
    esf.mb_ser = alfas["mb"] * p_ser * a ** 2
    for bordo, i in enumerate((i1, i2, i3, i4), start=1):
        if i <= 0.0:
            continue
        chave = "mb_" if bordo in BORDOS_DA_DIRECAO["b"] else "ma_"
        if chave in alfas:
            esf.m_neg_ser[bordo] = alfas[chave] * p_ser * a ** 2

    if laje.paredes:
        esf.avisos.append(
            f"{laje.nome}: as paredes entraram no ELU pelos coeficientes "
            f"alfa = {alfa:.3f} e beta = {beta:.3f} do formulário de linhas "
            f"de ruptura (§3.2 b), obtido para a posição mais desfavorável; "
            f"no ELS elas foram espalhadas na área, porque a tabela elástica "
            f"só trata carga uniforme.")
    return esf


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def calcular(laje: Laje, cfg: Config) -> Esforcos:
    """Momentos da laje nos dois regimes."""
    cls = classificar(laje)
    gn = gamma_n(laje.h) if cls.balanco else 1.0
    if cls.em_cruz:
        esf = _esforcos_em_cruz(laje, cls, cfg, gn)
    else:
        esf = _esforcos_uma_direcao(laje, cls, cfg, gn)

    if gn > 1.0:
        esf.avisos.append(
            f"{laje.nome}: laje em balanço com h = {laje.h:g} cm, logo os "
            f"esforços de cálculo foram majorados por gamma_n = {gn:.2f} "
            f"(13.2.4.1).")

    # razão mínima entre momento de borda e momento de vão (§1.7)
    for bordo, m_neg in esf.m_neg.items():
        direcao = "b" if bordo in BORDOS_DA_DIRECAO["b"] else "a"
        m_vao = esf.momento_da_direcao(direcao)
        if m_vao > 1e-9 and m_neg / m_vao < cfg.razao_minima_borda_vao - 1e-6:
            esf.avisos.append(
                f"{laje.nome}, bordo {bordo}: a razão entre o momento de "
                f"borda e o de vão é {m_neg / m_vao:.2f}, abaixo do mínimo "
                f"de {cfg.razao_minima_borda_vao:.1f}:1 do §1.7 -- aumente o "
                f"grau de engastamento i deste bordo.")
    return esf
