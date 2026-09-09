# -*- coding: utf-8 -*-
"""
green.py
Integração da contribuição do concreto ao equilíbrio da seção pelo Teorema de
Green: a integral de superfície das tensões é transformada numa integral de
linha ao longo do contorno, sem fatiar a seção.

Esta é a técnica de CADAMURO JÚNIOR (1997, "Dimensionamento de pilares
esbeltos de concreto armado com seção qualquer solicitados por flexão
composta oblíqua", TCC EESC-USP, sistema FLEXOR, capítulo 4.3.3), com uma
diferença de propósito: o TCC deriva antiderivadas **polinomiais** porque
resolve a integral de linha em forma inteiramente fechada, o que exige
pré-definir o diagrama tensão-deformação como sequência de polinômios. Aqui a
antiderivada em relação à deformação (:func:`_antideriv0`, :func:`_antideriv1`)
é obtida em forma fechada para o diagrama parábola-retângulo do item 8.2.10.1
-- válida para **qualquer** expoente ``n``, inteiro ou não, o que cobre tanto
fck <= 50 MPa quanto as classes acima --, e só a integral de linha ao longo de
cada lado do polígono é resolvida por quadratura de Gauss-Legendre. É a mesma
divisão de trabalho que o item 4.3.3-h6 do TCC descreve como alternativa
("Processo da Poligonal com Integração Numérica"), e que ele credita a SANTOS
(1994) como suficientemente precisa com poucos pontos de Gauss.

Dedução, em duas etapas:

1. **Redução a uma integral de linha** (Teorema de Green). Numa seção
   referida aos eixos ``(u, v)`` -- ``u`` ao longo da compressão, ``v`` ao
   longo da linha neutra --, a deformação ``eps(u) = eps_ref + k(u - u_ref)``
   depende só de ``u``. Para qualquer ``g(u)`` com antiderivada ``H(u)``,

       ∬_A g(u) du dv = ∮_∂A H(u) dv        (tome Q=H(u), P=0 em Green:
                                              ∂Q/∂u − ∂P/∂v = H'(u) = g(u))

       ∬_A g(u)·v du dv = ∮_∂A H(u)·v dv     (tome Q=H(u)·v, P=0:
                                              ∂Q/∂u = H'(u)·v = g(u)·v)

   Com ``g0(u) = sigma_c(eps(u))`` e ``g1(u) = u·g0(u)``, e ``H0``, ``H1`` as
   antiderivadas correspondentes:

       N  = ∮ H0(u) dv
       S1 = ∮ H1(u) dv
       T1 = ∮ H0(u)·v dv
       Mx = S1 cos(theta) − T1 sin(theta)
       My = S1 sin(theta) + T1 cos(theta)

   Um lado paralelo ao eixo u (``v`` constante) não contribui -- ``dv = 0``
   ao longo dele --, o que sai automaticamente da parametrização por lado, sem
   caso especial. Vazios são subtraídos automaticamente pelo sentido de
   circuição invertido do contorno, pela mesma razão que a área de um furo
   sai negativa na fórmula do shoelace.

2. **As antiderivadas em ‰, por substituição** ``w = eps(u)``, ``dw = k du``:

       H0(u) = Sigma_C(w) / k
       H1(u) = (u_ref/k)·Sigma_C(w) + (Sigma_C1(w) − eps_ref·Sigma_C(w)) / k²

   com ``Sigma_C(w) = ∫ sigma_c(w) dw`` e ``Sigma_C1(w) = ∫ w·sigma_c(w) dw``,
   fechadas para o diagrama parábola-retângulo (:func:`_antideriv0` e
   :func:`_antideriv1`) -- ambas conferidas por diferenciação numérica no
   autoteste, e não só pela álgebra.
"""

from __future__ import annotations

import math

import numpy as np

from . import geometria as geo
from .materiais import Concreto

#: Ordem da quadratura de Gauss-Legendre por lado do polígono. O integrando
#: (a antiderivada composta com uma parametrização linear) é analítico e sem
#: bicos dentro do trecho comprimido; poucos pontos bastam para precisão
#: muito além da que qualquer fatiamento alcançaria.
ORDEM_GAUSS = 10

_GAUSS_NOS, _GAUSS_PESOS = np.polynomial.legendre.leggauss(ORDEM_GAUSS)
# de [-1, 1] para [0, 1]
_T_NOS = (_GAUSS_NOS + 1.0) / 2.0
_T_PESOS = _GAUSS_PESOS / 2.0

#: Abaixo deste ``|k|`` (‰/cm) a deformação é praticamente uniforme na seção
#: inteira, e a substituição ``w = eps(u)`` degenera (divisão por ~0). Nesse
#: regime a resultante já é bem aproximada pela compressão uniforme -- o autor
#: do TCC observa a mesma degenerescência no item 4.3.6 e propõe a mesma
#: saída: uma fórmula à parte para deformação uniforme.
K_MINIMO = 1e-9


def _r(eps_mil: np.ndarray, eps_c2: float) -> np.ndarray:
    """``r = 1 - eps/eps_c2``, recortado em ``[0, 1]``, vetorizado.

    O recorte é o que permite escrever :func:`_antideriv0` e
    :func:`_antideriv1` como uma **única** expressão válida em toda a faixa
    ``eps <= eps_cu``, sem ramificar por ``eps`` -- e o que evita elevar um
    número negativo a um expoente não inteiro, que daria complexo ou NaN.

    ``minimum(maximum(...))`` no lugar de ``clip``: nos vetores curtos deste
    laço (uma dúzia de lados por seis pontos de Gauss) o custo é o despacho
    do numpy, não a aritmética, e o ``clip`` despacha quase duas vezes mais
    caro. Medido em 2,6 us contra 1,4 us por chamada, e são mais de cem mil
    chamadas por lance com varredura.
    """
    return np.minimum(np.maximum(1.0 - eps_mil / eps_c2, 0.0), 1.0)


def _pot(r: np.ndarray, expoente: float) -> np.ndarray:
    """``r ** expoente``, por multiplicação quando o expoente é 3 ou 4.

    Para fck <= 50 MPa o item 8.2.10.1 dá ``n = 2``, e as antiderivadas caem
    em ``r^3`` e ``r^4`` -- o caso comum. O ``pow`` do numpy com expoente real
    custa três vezes uma multiplicação (2,8 us contra 0,9 us nos vetores
    curtos deste laço), e o resultado é o mesmo até o último bit para
    expoente inteiro. As classes acima de 50 MPa, com ``n`` fracionário,
    seguem pelo ``pow`` -- que é o único caminho correto lá.
    """
    if expoente == 3.0:
        return r * r * r
    if expoente == 4.0:
        r2 = r * r
        return r2 * r2
    return r ** expoente


def _antideriv0(c: Concreto, eps_mil: np.ndarray) -> np.ndarray:
    """``Sigma_C(eps) = ∫ sigma_c(eps) d(eps)``, kN/cm²·‰, vetorizada.

    Fechada para o diagrama parábola-retângulo, com o expoente ``n`` do item
    8.2.10.1 tratado como real -- vale tanto para fck <= 50 (``n = 2``,
    polinômio genuíno) quanto para as classes acima (``n`` não inteiro).

        Sigma_C(eps) = fcd_ac · [eps + eps_c2/(n+1) · r^(n+1)],  eps <= eps_c2
                     = fcd_ac · eps,                              eps_c2 < eps <= eps_cu
                     = fcd_ac · eps_c2/(n+1),                     eps <= 0

    As duas primeiras linhas já concordam em ``eps = eps_c2`` (``r = 0``) sem
    precisar de constante de ajuste -- e é por isso que a expressão de cima,
    com ``r`` recortado, vale nas duas faixas de uma só vez. A terceira linha
    é a mesma expressão de cima congelada em ``eps = 0`` (``r = 1``): abaixo
    de zero o concreto não resiste, ``sigma_c = 0``, e a antiderivada tem de
    ficar constante, não seguir a parábola para trás. Conferida por
    diferenciação numérica contra ``sigma_c`` no autoteste, para qualquer
    ``n``, e não só pela álgebra.
    """
    fcd_ac = c.alfa_c * c.fcd_kNcm2
    eps_c2 = c.eps_c2_mil
    n = c.expoente_n
    eps = np.maximum(eps_mil, 0.0)
    r = _r(eps, eps_c2)
    return fcd_ac * (eps + eps_c2 / (n + 1.0) * _pot(r, n + 1.0))


def _antideriv1(c: Concreto, eps_mil: np.ndarray) -> np.ndarray:
    """``Sigma_C1(eps) = ∫ eps · sigma_c(eps) d(eps)``, kN/cm²·‰², vetorizada.

    Mesma ideia de :func:`_antideriv0`, uma faixa a mais de trabalho porque o
    integrando carrega um ``eps`` extra. Com ``r = 1 - eps/eps_c2``:

        Sigma_C1(eps) = -fcd_ac·eps_c2² · [r - r²/2 - r^(n+1)/(n+1)
                                             + r^(n+2)/(n+2)],   eps <= eps_c2
                       = fcd_ac · (eps² - eps_c2²)/2,             eps_c2 < eps <= eps_cu

    As duas concordam em ``eps = eps_c2`` (``r=0``): a primeira dá 0, a
    segunda também. Abaixo de zero (``r=1``) a primeira linha, congelada,
    serve de novo -- ``eps · sigma_c(eps) = 0`` aí, e ela é constante.
    Conferida por diferenciação numérica no autoteste, como a anterior.
    """
    fcd_ac = c.alfa_c * c.fcd_kNcm2
    eps_c2 = c.eps_c2_mil
    n = c.expoente_n
    eps = np.maximum(eps_mil, 0.0)
    r = _r(eps, eps_c2)
    baixo = -fcd_ac * eps_c2 * eps_c2 * (
        r - r * r / 2.0 - _pot(r, n + 1.0) / (n + 1.0)
        + _pot(r, n + 2.0) / (n + 2.0))
    alto = fcd_ac * (eps * eps - eps_c2 * eps_c2) / 2.0
    return np.where(eps <= eps_c2, baixo, alto)


def _h0_h1(c: Concreto, u: np.ndarray, eps_ref: float, k: float,
           u_ref: float) -> tuple[np.ndarray, np.ndarray]:
    """``H0(u)`` e ``H1(u)`` -- antiderivadas em ``u`` --, vetorizadas.

    Por substituição ``w = eps(u) = eps_ref + k(u - u_ref)``:

        H0(u) = Sigma_C(w) / k
        H1(u) = (u_ref/k)·Sigma_C(w) + [Sigma_C1(w) − eps_ref·Sigma_C(w)] / k²
    """
    w = eps_ref + k * (u - u_ref)
    sigma_c0 = _antideriv0(c, w)
    sigma_c1 = _antideriv1(c, w)
    h0 = sigma_c0 / k
    h1 = (u_ref / k) * sigma_c0 + (sigma_c1 - eps_ref * sigma_c0) / (k * k)
    return h0, h1


def _clip_zero(pol: geo.Poligono, theta: float, eps_ref: float, k: float,
               u_ref: float) -> geo.Poligono:
    """Recorta o polígono no semiplano comprimido, ``eps(u) >= 0``.

    É o único recorte que a integração de Green precisa: dentro dele o
    diagrama tensão-deformação é liso (o item 8.2.10.1 empalma a parábola com
    o patamar sem quina -- as duas têm derivada nula em ``eps = eps_c2``), e
    a quadratura de Gauss não perde precisão por causa de um bico que não
    existe. O fatiamento em faixas resolvia esse mesmo problema faixa a
    faixa; aqui um recorte só já basta.

    O limite do semiplano é ``u_zero = u_ref - eps_ref/k`` -- onde
    ``eps(u_zero) = 0`` --, **não** ``u = 0``: a origem de ``u`` é o CG da
    seção, e a fibra neutra quase nunca passa por ali.
    """
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    u_zero = u_ref - eps_ref / k
    return geo.recortar_semiplano(pol, cos_t, sin_t, u_zero,
                                  manter_acima=(k > 0.0))


def resultantes_concreto(contornos: list[geo.Poligono], concreto: Concreto,
                         theta: float, eps_ref: float, k: float,
                         u_ref: float) -> tuple[float, float, float]:
    """``(N, Mx, My)`` da contribuição do concreto, pelo Teorema de Green.

    ``eps_ref``, ``k`` e ``u_ref`` descrevem o plano de deformações --
    ``eps(u) = eps_ref + k(u - u_ref)`` -- na mesma convenção de
    :class:`pilares.core.seccional.Plano`. Devolve zero quando ``|k|`` é
    pequeno demais para a substituição funcionar (deformação quase uniforme);
    quem chama já tem, para esse caso, a fórmula fechada de compressão
    uniforme (:func:`pilares.core.seccional.normal_resistente_maxima`).

    Todos os pontos de Gauss de todos os lados do polígono (e dos furos, se
    houver) entram numa única chamada de :func:`_h0_h1`, em vez de uma por
    lado: para os 4 a 12 lados usuais de uma seção de pilar, isso troca uma
    dúzia de operações vetorizadas de meia dúzia de elementos -- onde o custo
    fixo do numpy pesa mais que a conta em si -- por uma só, de umas cem.
    """
    if abs(k) < K_MINIMO:
        return 0.0, 0.0, 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    u0s: list[float] = []
    dus: list[float] = []
    v0s: list[float] = []
    dvs: list[float] = []
    for anel in contornos:
        recortado = _clip_zero(anel, theta, eps_ref, k, u_ref)
        n = len(recortado)
        if n < 3:
            continue
        for i in range(n):
            x0, y0 = recortado[i]
            x1, y1 = recortado[(i + 1) % n]
            v0 = -x0 * sin_t + y0 * cos_t
            v1 = -x1 * sin_t + y1 * cos_t
            dv = v1 - v0
            if abs(dv) < 1e-12:
                continue                    # lado paralelo à linha neutra
            u0 = x0 * cos_t + y0 * sin_t
            u1 = x1 * cos_t + y1 * sin_t
            u0s.append(u0)
            dus.append(u1 - u0)
            v0s.append(v0)
            dvs.append(dv)
    if not dvs:
        return 0.0, 0.0, 0.0

    u0_arr = np.asarray(u0s)[:, None]
    du_arr = np.asarray(dus)[:, None]
    v0_arr = np.asarray(v0s)[:, None]
    dv_arr = np.asarray(dvs)                # (lados,)

    u_t = u0_arr + du_arr * _T_NOS[None, :]         # (lados, ordem)
    v_t = v0_arr + dv_arr[:, None] * _T_NOS[None, :]
    h0, h1 = _h0_h1(concreto, u_t, eps_ref, k, u_ref)

    S0 = float(dv_arr @ (h0 @ _T_PESOS))
    S1 = float(dv_arr @ (h1 @ _T_PESOS))
    T1 = float(dv_arr @ ((h0 * v_t) @ _T_PESOS))
    N = S0
    Mx = S1 * cos_t - T1 * sin_t
    My = S1 * sin_t + T1 * cos_t
    return N, Mx, My
