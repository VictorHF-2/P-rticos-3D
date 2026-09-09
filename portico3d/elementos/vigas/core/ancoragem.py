# -*- coding: utf-8 -*-
"""
ancoragem.py
Aderência e ancoragem das armaduras longitudinais (NBR 6118, seção 9),
decalagem do diagrama de momentos (17.4.2.2) e emendas por traspasse (9.5.2).

Unidades: comprimentos em cm, tensões em kN/cm², forças em kN.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .materiais import Aco, Concreto
from . import avisos as av


# ---------------------------------------------------------------------------
# Aderência
# ---------------------------------------------------------------------------

def eta_2(boa_aderencia: bool) -> float:
    """Coeficiente de situação de aderência (9.3.2.1)."""
    return 1.0 if boa_aderencia else 0.7


def eta_3(phi_mm: float) -> float:
    """Coeficiente de diâmetro da barra (9.3.2.1)."""
    return 1.0 if phi_mm < 32.0 else (132.0 - phi_mm) / 100.0


#: distância de referência do item 9.3.1, cm
FAIXA_ADERENCIA = 30.0


def boa_aderencia(face: str, h_cm: float,
                  altura_barra: float | None = None) -> bool:
    """Situação de aderência de uma barra horizontal (9.3.1).

    O item pede a **posição da barra**, não a face:

    - em peças com ``h < 60 cm``, boa situação até 30 cm acima da face
      inferior;
    - em peças com ``h >= 60 cm``, boa situação a partir de 30 cm abaixo da
      face superior.

    ``altura_barra`` é a distância do eixo da barra à face inferior, em cm.
    Quando não é informada, cai na simplificação por face -- que reproduz o
    texto para as barras de fundo e de topo, mas trata como má situação
    qualquer barra intermediária, inclusive a de pele a meia altura de uma
    viga alta, que o item considera em boa situação.
    """
    if altura_barra is None:
        return face == "inferior" or h_cm <= FAIXA_ADERENCIA
    if h_cm < 60.0:
        return altura_barra <= FAIXA_ADERENCIA + 1e-9
    return h_cm - altura_barra >= FAIXA_ADERENCIA - 1e-9


def fbd(concreto: Concreto, aco: Aco, phi_mm: float,
        boa: bool = True) -> float:
    """Resistência de aderência de cálculo, kN/cm² (9.3.2.1)."""
    return aco.eta_1 * eta_2(boa) * eta_3(phi_mm) * concreto.fctd_kNcm2


@dataclass
class Ancoragem:
    """Comprimentos de ancoragem de uma barra."""

    phi: float                # mm
    face: str
    boa_aderencia: bool
    fbd: float                # kN/cm²
    lb: float                 # cm, ancoragem básica
    lb_em_phi: float          # múltiplo de phi
    alfa: float               # 1,0 reta / 0,7 com gancho admitido
    lb_nec: float             # cm
    lb_min: float             # cm
    As_calc: float
    As_ef: float
    gancho: bool
    avisos: list[str] = field(default_factory=list)


def ancorar(concreto: Concreto, aco: Aco, phi_mm: float, As_calc: float,
            As_ef: float, face: str, h_cm: float, gancho: bool = False,
            cobrimento_normal: float = 0.0,
            altura_barra: float | None = None) -> Ancoragem:
    """Comprimento de ancoragem necessário de uma barra (9.4.2.4/9.4.2.5).

    ``cobrimento_normal`` é o cobrimento medido no plano normal ao do gancho,
    em cm -- para o gancho dobrado no plano vertical de uma viga, é o
    cobrimento lateral. O item 9.4.2.5 só admite ``alfa = 0,7`` quando esse
    cobrimento é de pelo menos 3 Ø; abaixo disso a redução não vale e a
    ancoragem tem de ser dimensionada como reta, ainda que o gancho exista.
    """
    boa = boa_aderencia(face, h_cm, altura_barra)
    f = fbd(concreto, aco, phi_mm, boa)
    phi_cm = phi_mm / 10.0
    lb_calc = phi_cm * aco.fyd_kNcm2 / (4.0 * f)
    lb = max(lb_calc, 25.0 * phi_cm)          # o piso de 25 Ø é do item 9.4.2.4
    avisos: list[str] = []
    cobrimento_suficiente = cobrimento_normal >= 3.0 * phi_cm - 1e-9
    if gancho and cobrimento_suficiente:
        alfa = 0.7
    else:
        alfa = 1.0
        if gancho:
            avisos.append(av.construtivo(
                f"Gancho presente, mas o item 9.4.2.5 só admite alfa = 0,7 "
                f"com cobrimento de 3 Ø = {3.0 * phi_cm:.1f} cm no plano "
                f"normal ao do gancho, e há {cobrimento_normal:.1f} cm: a "
                f"ancoragem foi calculada com alfa = 1,0."))
    razao = As_calc / As_ef if As_ef > 0 else 1.0
    lb_min = max(0.3 * lb, 10.0 * phi_cm, 10.0)
    lb_nec = max(alfa * lb * razao, lb_min)
    if not boa:
        avisos.append(av.construtivo(
            "Barra em má situação de aderência (9.3.1): fbd reduzido por "
            "eta_2 = 0,7."))
    return Ancoragem(phi=phi_mm, face=face, boa_aderencia=boa, fbd=f, lb=lb,
                     lb_em_phi=lb / phi_cm, alfa=alfa, lb_nec=lb_nec,
                     lb_min=lb_min, As_calc=As_calc, As_ef=As_ef,
                     gancho=gancho, avisos=avisos)


# ---------------------------------------------------------------------------
# Decalagem do diagrama de momentos
# ---------------------------------------------------------------------------

def decalagem(d_cm: float, Vsd: float, Vc: float, modelo: int = 1,
              theta: float = 45.0, alpha: float = 90.0) -> tuple[float, str]:
    """Deslocamento al do diagrama de momentos, cm (17.4.2.2-c e 17.4.2.3-c).

    As duas expressões, transcritas da norma:

        Modelo I    al = d . [ Vsd,máx / (2 (Vsd,máx - Vc)) . (1 + cotg a)
                                - cotg a ]                            <= d
        Modelo II   al = 0,5 d . [ Vsd,máx / (Vsd,máx - Vc)
                                   . (cotg t + cotg a) - cotg a ]     <= d

    com ``al = d`` para ``|Vsd,máx| <= |Vc|``, ``al >= 0,5 d`` no caso geral e
    ``al >= 0,2 d`` para estribos inclinados a 45°. O item 17.4.2.3-c mantém as
    condições do 17.4.2.2-c ("se forem mantidas as condições estabelecidas em
    17.4.2.2-c"), e é de lá que vêm os pisos e o teto do Modelo II.

    A relação ``Vsd,máx / (Vsd,máx - Vc)`` é o coração dos dois: ela mede
    quanto do cortante a treliça tem de levar depois de descontada a parcela
    Vc, e cresce sem limite quando Vsd se aproxima de Vc -- daí o teto de d, que
    não é um arredondamento mas o valor que a norma manda adotar quando a
    expressão estoura.

    O estribo a 90° tem ``cotg a = 0`` e o Modelo I cai em ``d/2 . Vsd/(Vsd -
    Vc)``, que é a forma como a expressão costuma aparecer nas apostilas. É o
    caso padrão do programa.
    """
    import math

    Vsd = abs(Vsd)
    Vc = abs(Vc)
    cot_a = 1.0 / math.tan(math.radians(alpha))
    cot_t = 1.0 / math.tan(math.radians(theta))
    if Vsd <= Vc + 1e-9:
        # a treliça não é solicitada além de Vc: a norma fixa al = d, e a
        # expressão nem é avaliada (o denominador seria nulo ou negativo)
        al = d_cm
        obs = "|Vsd,máx| <= |Vc|: adotado al = d (17.4.2.2-c)"
    elif modelo == 1:
        al = d_cm * (Vsd / (2.0 * (Vsd - Vc)) * (1.0 + cot_a) - cot_a)
        obs = ("Modelo I: al = d.[Vsd/(2(Vsd-Vc)).(1+cotg a) - cotg a]"
               + (", estribo a 90° (cotg a = 0)" if cot_a < 1e-9
                  else f", a = {alpha:g}°"))
    else:
        al = 0.5 * d_cm * (Vsd / (Vsd - Vc) * (cot_t + cot_a) - cot_a)
        obs = (f"Modelo II: al = 0,5.d.[Vsd/(Vsd-Vc).(cotg {theta:g}° + "
               f"cotg {alpha:g}°) - cotg {alpha:g}°]")
    al_min = 0.2 * d_cm if abs(alpha - 45.0) < 1e-6 else 0.5 * d_cm
    if al < 0.0 or al > d_cm:
        al = d_cm
        obs += "; limitado a d"
    elif al < al_min:
        al = al_min
        obs += f"; elevado ao mínimo ({al_min / d_cm:.1f} d)"
    return al, obs


# ---------------------------------------------------------------------------
# Apoios extremos e emendas
# ---------------------------------------------------------------------------

@dataclass
class ApoioExtremo:
    """Verificação da ancoragem da armadura positiva no apoio de extremidade."""

    Rsd: float                # kN, força a ancorar
    As_necessaria: float      # cm²
    As_efetiva: float         # cm²
    lb_nec: float             # cm, exigido (já com os pisos de 18.3.2.4.1)
    lb_calculado: float       # cm, só o lb,nec de 9.4.2.5
    piso_gancho: float        # cm, r + 5,5 phi (Tabela 9.1)
    l_disponivel: float       # cm
    ok: bool
    apoio: int = 0            # nº do apoio, preenchido por quem verifica
    avisos: list[str] = field(default_factory=list)


def apoio_extremo(concreto: Concreto, aco: Aco, Vsd: float, al_cm: float,
                  d_cm: float, phi_mm: float, As_ef: float, largura_cm: float,
                  cobrimento_cm: float, gancho: bool = False,
                  cobrimento_normal: float = 0.0) -> ApoioExtremo:
    """Ancoragem da armadura positiva em apoio extremo (18.3.2.4).

    A força a ancorar é Rsd = (al/d).Vsd; o comprimento disponível vai da face
    interna do apoio até o fim da barra, descontado o cobrimento.
    """
    Rsd = abs(Vsd) * al_cm / d_cm
    As_nec = Rsd / aco.fyd_kNcm2
    anc = ancorar(concreto, aco, phi_mm, As_nec, As_ef, "inferior",
                  h_cm=0.0, gancho=gancho,
                  cobrimento_normal=cobrimento_normal)
    # o item 18.3.2.4.1 manda ancorar, a partir da face do apoio, o **maior**
    # entre lb,nec, (r + 5,5 phi) e 60 mm -- os dois últimos faltavam
    piso_gancho = aco.raio_dobramento(phi_mm) + 5.5 * phi_mm / 10.0
    lb_exigido = max(anc.lb_nec, piso_gancho, PISO_ANCORAGEM_APOIO)
    l_disp = largura_cm - cobrimento_cm
    ok = lb_exigido <= l_disp + 1e-9
    avisos: list[str] = list(anc.avisos)
    if lb_exigido > anc.lb_nec + 1e-9:
        origem = ("r + 5,5 Ø" if piso_gancho >= PISO_ANCORAGEM_APOIO
                  else "60 mm")
        avisos.append(av.construtivo(
            f"Ancoragem no apoio governada pelo piso do item 18.3.2.4.1 "
            f"({origem} = {lb_exigido:.1f} cm) e não por lb,nec "
            f"({anc.lb_nec:.1f} cm)."))
    # o veredito de "não cabe" **não** sai daqui: só quem chama sabe se há
    # grampo para completar a ancoragem, e emitir o erro aqui punha "use
    # gancho ou aumente o pilar" em toda viga que os grampos já resolviam.
    # O fato fica em `ok`, `lb_nec` e `l_disponivel`; a mensagem é de quem
    # decide
    return ApoioExtremo(Rsd=Rsd, As_necessaria=As_nec, As_efetiva=As_ef,
                        lb_nec=lb_exigido, lb_calculado=anc.lb_nec,
                        piso_gancho=piso_gancho, l_disponivel=l_disp,
                        ok=ok, avisos=avisos)


#: Piso absoluto da ancoragem no apoio, cm (18.3.2.4.1: 60 mm).
PISO_ANCORAGEM_APOIO = 6.0

#: Fração da força de uma barra que a armadura transversal da ancoragem tem de
#: resistir, para barras com Ø < 32 mm (9.4.2.6.1).
FRACAO_TRANSVERSAL_ANCORAGEM = 0.25

#: Comprimento comercial usual do vergalhão, cm.
COMPRIMENTO_COMERCIAL = 1200.0

#: Fração de barras emendadas na mesma seção adotada por padrão. Sem
#: informação sobre o escalonamento das emendas, adota-se 50 % (alfa_0t = 1,8),
#: mesma convenção do programa de blocos de coroamento.
PROPORCAO_EMENDADA_PADRAO = 0.50


def alfa_0t(proporcao_emendada: float) -> float:
    """Coeficiente alfa_0t da Tabela 9.4, pela fração emendada na seção."""
    if proporcao_emendada <= 0.20:
        return 1.2
    if proporcao_emendada <= 0.25:
        return 1.4
    if proporcao_emendada <= 0.33:
        return 1.6
    if proporcao_emendada <= 0.50:
        return 1.8
    return 2.0


def traspasse(concreto: Concreto, aco: Aco, phi_mm: float, As_calc: float,
              As_ef: float, face: str, h_cm: float,
              proporcao_emendada: float = PROPORCAO_EMENDADA_PADRAO,
              gancho: bool = False, cobrimento_normal: float = 0.0,
              altura_barra: float | None = None) -> float:
    """Comprimento de traspasse de barras tracionadas, cm (9.5.2.2.1).

        l0t = alfa_0t . lb,nec >= max(0,3 . alfa_0t . lb ; 15 phi ; 20 cm)
    """
    anc = ancorar(concreto, aco, phi_mm, As_calc, As_ef, face, h_cm, gancho,
                  cobrimento_normal, altura_barra)
    a0t = alfa_0t(proporcao_emendada)
    phi_cm = phi_mm / 10.0
    l0t = a0t * anc.lb_nec
    return max(l0t, 0.3 * a0t * anc.lb, 15.0 * phi_cm, 20.0)


def traspasse_compressao(concreto: Concreto, aco: Aco, phi_mm: float,
                         As_calc: float, As_ef: float, face: str,
                         h_cm: float) -> float:
    """Traspasse de barras **comprimidas**, cm (9.5.2.3).

        l0c = lb,nec >= max(0,6 lb ; 15 phi ; 200 mm)

    Não há alfa_0t: a barra comprimida transmite parte do esforço por contato,
    e o item não penaliza a proporção emendada na mesma seção. Sai bem menor
    que o traspasse de tração -- o programa usava o de tração para as duas
    situações, a favor da segurança.
    """
    anc = ancorar(concreto, aco, phi_mm, As_calc, As_ef, face, h_cm)
    phi_cm = phi_mm / 10.0
    return max(anc.lb_nec, 0.6 * anc.lb, 15.0 * phi_cm, 20.0)


def repartir_barra(comprimento_cm: float, l0t_cm: float,
                   comprimento_max: float = COMPRIMENTO_COMERCIAL
                   ) -> tuple[int, float]:
    """Reparte uma barra longa em peças comerciais emendadas por traspasse.

    Cada emenda consome ``l0t`` de sobreposição, então o material gasto cresce
    com o número de emendas: procura-se o menor ``n`` tal que ``n`` peças de
    até ``comprimento_max``, com ``n - 1`` traspasses, cubram o comprimento
    pedido. Devolve (nº de peças, comprimento de cada peça em cm).
    """
    if comprimento_cm <= comprimento_max:
        return 1, comprimento_cm
    denominador = max(comprimento_max - l0t_cm, 1e-6)
    n = max(2, math.ceil((comprimento_cm - l0t_cm) / denominador))
    return n, (comprimento_cm + (n - 1) * l0t_cm) / n
