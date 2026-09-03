# -*- coding: utf-8 -*-
"""
montagem.py
Montagem da matriz de rigidez global, do vetor de cargas e solução do sistema.

A carga distribuída entra pelo caminho clássico: as forças de engastamento
perfeito viram cargas nodais equivalentes de sinal trocado, e depois são
somadas de volta aos esforços de extremidade da barra.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import LinAlgError, cho_factor, cho_solve

from .carregamento import Segmento, forcas_engastamento, segmentos_da_barra
from .elemento import BarraPreparada, preparar
from .modelo import NOMES_GDL, CasoDeCarga, ErroDeModelo, Modelo
from .resultados import Resultado

# Queda admissível do pivô durante a fatoração, medida contra o termo original
# da diagonal. Abaixo disso o grau de liberdade perdeu praticamente toda a
# rigidez ao longo da eliminação, que é a assinatura do mecanismo.
TOL_PIVO = 1.0e-10


def preparar_barras(modelo: Modelo) -> dict[str, BarraPreparada]:
    return {nome: preparar(modelo, barra)
            for nome, barra in modelo.barras.items()}


def cargas_locais(caso: CasoDeCarga, preparadas: dict[str, BarraPreparada]
                  ) -> dict[str, list[Segmento]]:
    """Carga distribuída de cada barra, em segmentos nos eixos locais."""
    # O comprimento é o do vão flexível: a carga distribuída atua sobre a
    # barra, não sobre os braços rígidos, que são recurso de cinemática e não
    # peça carregada. Por isso ``inicio`` e ``fim`` são frações do vão livre.
    return {nome: segmentos_da_barra(caso, nome, p.Lf, p.R)
            for nome, p in preparadas.items()}


def matriz_global(modelo: Modelo,
                  preparadas: dict[str, BarraPreparada]) -> np.ndarray:
    K = np.zeros((modelo.n_gdl, modelo.n_gdl))
    for p in preparadas.values():
        g = np.array(p.gdl)
        K[np.ix_(g, g)] += p.k_global
    for mola in modelo.molas.values():
        K[modelo.gdl(mola.no), modelo.gdl(mola.no)] += mola.vetor
    return K


def vetor_cargas(modelo: Modelo, caso: CasoDeCarga,
                 preparadas: dict[str, BarraPreparada],
                 segmentos: dict[str, list[Segmento]]) -> np.ndarray:
    P = np.zeros(modelo.n_gdl)

    for carga in caso.nodais:
        P[modelo.gdl(carga.no)] += carga.vetor

    for nome, p in preparadas.items():
        if not segmentos[nome]:
            continue
        P[np.array(p.gdl)] -= p.TH.T @ p.engastamento(segmentos[nome])

    return P


def vetor_recalques(modelo: Modelo, caso: CasoDeCarga) -> np.ndarray:
    """Deslocamentos impostos, montados no vetor global."""
    D = np.zeros(modelo.n_gdl)
    for recalque in caso.recalques:
        D[modelo.gdl(recalque.no)] += recalque.vetor
    return D


def particionar(modelo: Modelo) -> tuple[np.ndarray, np.ndarray]:
    """Separa os graus de liberdade livres dos restringidos."""
    livre = np.ones(modelo.n_gdl, dtype=bool)
    for apoio in modelo.apoios.values():
        base = 6 * modelo.indice(apoio.no)
        for k, restrito in enumerate(apoio.restricoes):
            if restrito:
                livre[base + k] = False
    return np.flatnonzero(livre), np.flatnonzero(~livre)


def _nomear(modelo: Modelo, graus) -> str:
    nos = list(modelo.nos)
    return ", ".join(f"{nos[g // 6]}.{NOMES_GDL[g % 6]}" for g in graus)


def _mecanismo(modelo: Modelo, Kff: np.ndarray, livres: np.ndarray) -> str:
    """Nomeia os graus de liberdade que mais participam do mecanismo.

    O autovetor associado ao menor autovalor é o modo de deslocamento que a
    estrutura percorre sem armazenar energia — é ele que diz onde está a
    falta de vínculo, e é essa a informação que falta na mensagem de matriz
    singular.
    """
    _, vetores = np.linalg.eigh(Kff)
    modo = np.abs(vetores[:, 0])
    ordem = np.argsort(modo)[::-1]
    corte = 0.1 * modo[ordem[0]]
    principais = [i for i in ordem[:6] if modo[i] > corte]
    return _nomear(modelo, livres[principais])


def _resolver_sistema(modelo: Modelo, K: np.ndarray, P: np.ndarray,
                      livres: np.ndarray, prescritos: np.ndarray) -> np.ndarray:
    """Fatoração de Cholesky com conferência de pivô.

    A matriz de uma estrutura bem vinculada é positiva definida. Se a
    fatoração falha, ou se algum pivô desaba em relação ao termo original da
    diagonal, o modelo tem mecanismo — e aí interessa dizer onde, não apenas
    que existe. Confiar no ``solve`` genérico é pior do que parece: diante de
    um modo de corpo rígido ele às vezes devolve números em vez de erro.
    """
    # Estrutura toda restringida não é erro: é o caso da barra biengastada sem
    # nó intermediário, em que a carga inteira vai direto para os apoios e os
    # esforços saem só do engastamento perfeito.
    if livres.size == 0:
        return np.zeros(0)

    Kff = K[np.ix_(livres, livres)]
    diagonal = np.diag(Kff)

    soltos = livres[np.abs(diagonal) < 1.0e-12 * float(np.max(diagonal))]
    if soltos.size:
        raise ErroDeModelo(
            "estrutura instável: sem rigidez alguma nos graus de liberdade "
            f"{_nomear(modelo, soltos[:6])}")

    try:
        fator = cho_factor(Kff, lower=True)
    except LinAlgError:
        raise ErroDeModelo(
            "estrutura instável: há mecanismo envolvendo "
            f"{_mecanismo(modelo, Kff, livres)}") from None

    razao = np.diag(fator[0]) ** 2 / diagonal
    fracos = livres[razao < TOL_PIVO]
    if fracos.size:
        raise ErroDeModelo(
            "estrutura instável: a rigidez se anula durante a eliminação nos "
            f"graus de liberdade {_nomear(modelo, fracos[:6])}")

    # Recalque prescrito entra como carga: K_ff·d_f = P_f - K_fs·d_s.
    carga = P[livres] - K[np.ix_(livres, np.arange(K.shape[0]))] @ prescritos
    return cho_solve(fator, carga)


def resolver(modelo: Modelo, caso: str | None = None) -> Resultado:
    """Análise elástica linear de primeira ordem para um caso de carga."""
    modelo.validar()

    if caso is None:
        if len(modelo.casos) != 1:
            raise ErroDeModelo(
                "informe o caso de carga: o modelo tem "
                f"{len(modelo.casos)} casos")
        caso = next(iter(modelo.casos))
    if caso not in modelo.casos:
        raise ErroDeModelo(f"caso de carga '{caso}' não existe")
    carregamento = modelo.casos[caso]

    preparadas = preparar_barras(modelo)
    segmentos = cargas_locais(carregamento, preparadas)
    K = matriz_global(modelo, preparadas)
    P = vetor_cargas(modelo, carregamento, preparadas, segmentos)
    livres, restritos = particionar(modelo)

    # ``validar`` já garante que só há recalque em grau de liberdade com
    # apoio, então o vetor é nulo nas posições livres, como a partição exige.
    D = vetor_recalques(modelo, carregamento)
    D[livres] = _resolver_sistema(modelo, K, P, livres, D)

    reacoes = K @ D - P

    # Onde há apoio, a força da mola já está dentro da reação do apoio; contar
    # as duas somaria a mesma força duas vezes no equilíbrio global.
    livre_por_gdl = np.zeros(modelo.n_gdl, dtype=bool)
    livre_por_gdl[livres] = True
    reacoes_mola = {
        mola.no: -mola.vetor * D[modelo.gdl(mola.no)]
        * livre_por_gdl[modelo.gdl(mola.no)]
        for mola in modelo.molas.values()}

    # Os esforços são os das extremidades do **vão flexível** — na face do
    # apoio, portanto, e não no eixo dele. É o que se quer para dimensionar.
    esforcos = {}
    for nome, p in preparadas.items():
        d = D[np.array(p.gdl)]
        esforcos[nome] = (p.k_local @ (p.TH @ d)
                          + p.engastamento(segmentos[nome]))

    return Resultado(modelo=modelo, caso=caso, deslocamentos=D,
                     reacoes=reacoes, esforcos=esforcos,
                     preparadas=preparadas, segmentos=segmentos,
                     gdl_restritos=restritos, reacoes_mola=reacoes_mola)
