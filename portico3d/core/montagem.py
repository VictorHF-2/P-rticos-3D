# -*- coding: utf-8 -*-
"""
montagem.py
Montagem da matriz de rigidez global, do vetor de cargas e solução do sistema.

A carga distribuída entra pelo caminho clássico: as forças de engastamento
perfeito viram cargas nodais equivalentes de sinal trocado, e depois são
somadas de volta aos esforços de extremidade da barra.

## A base de cálculo

As incógnitas do sistema não são, em geral, os graus de liberdade dos nós:

    D = D₀ + T·r

``D₀`` traz os recalques (deslocamento imposto nos graus com apoio) e ``r``
são as incógnitas de fato. Sem diafragma, ``T`` só escolhe os graus livres, e
a conta é a de sempre — ``K[livres, livres]``, sem nem montar ``T``. Com
diafragma (``core.diafragma``), ``T`` também amarra os ux, uy e rz dos nós
de cada pavimento aos três graus do pavimento. É a classe :class:`Base` que
guarda isso, e é por ela que passam a 1ª ordem, o P-Δ, a flambagem e a modal
— o diafragma vale para todas, e não só para a análise linear.

## Matriz densa ou esparsa

Até ``LIMITE_DENSO`` graus de liberdade a matriz é densa e a fatoração é de
Cholesky, como sempre foi. Acima disso — o que a laje em grelha produz
num edifício — ela é montada esparsa e fatorada por LU esparsa: uma matriz
densa de 10 000 graus ocupa 800 MB, e a esparsa do mesmo pórtico, poucos MB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.linalg import LinAlgError, cho_factor, cho_solve

from .carregamento import Segmento, forcas_engastamento, segmentos_da_barra
from .elemento import BarraPreparada, preparar
from .modelo import NOMES_GDL, CasoDeCarga, ErroDeModelo, Modelo
from .resultados import Resultado

# Queda admissível do pivô durante a fatoração, medida contra o termo original
# da diagonal. Abaixo disso o grau de liberdade perdeu praticamente toda a
# rigidez ao longo da eliminação, que é a assinatura do mecanismo.
TOL_PIVO = 1.0e-10

#: Acima deste número de graus de liberdade a matriz é montada esparsa.
LIMITE_DENSO = 3000


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


def esparsa(modelo: Modelo) -> bool:
    """Se as matrizes deste modelo são montadas esparsas."""
    return modelo.n_gdl > LIMITE_DENSO


class Montador:
    """Soma blocos de barra numa matriz global, densa ou esparsa.

    É o mesmo espalhamento ``K[g, g] += k`` para as três matrizes do
    programa — rigidez elástica, geométrica e massa —, escrito uma vez só.
    """

    def __init__(self, n: int, usar_esparsa: bool) -> None:
        self.n = n
        self.usar_esparsa = usar_esparsa
        if usar_esparsa:
            self._linhas: list[np.ndarray] = []
            self._colunas: list[np.ndarray] = []
            self._valores: list[np.ndarray] = []
        else:
            self.K = np.zeros((n, n))

    def somar(self, g, k: np.ndarray) -> None:
        g = np.asarray(g)
        if self.usar_esparsa:
            self._linhas.append(np.repeat(g, len(g)))
            self._colunas.append(np.tile(g, len(g)))
            self._valores.append(np.asarray(k, float).ravel())
        else:
            self.K[np.ix_(g, g)] += k

    def somar_diagonal(self, g, valores) -> None:
        g = np.asarray(g)
        valores = np.asarray(valores, float)
        if self.usar_esparsa:
            self._linhas.append(g)
            self._colunas.append(g)
            self._valores.append(valores)
        else:
            self.K[g, g] += valores

    def matriz(self):
        if not self.usar_esparsa:
            return self.K
        if not self._valores:
            return sp.csr_matrix((self.n, self.n))
        # A COO soma as entradas repetidas na conversão: é a montagem.
        return sp.coo_matrix(
            (np.concatenate(self._valores),
             (np.concatenate(self._linhas), np.concatenate(self._colunas))),
            shape=(self.n, self.n)).tocsr()


def matriz_global(modelo: Modelo, preparadas: dict[str, BarraPreparada]):
    montador = Montador(modelo.n_gdl, esparsa(modelo))
    for p in preparadas.values():
        montador.somar(p.gdl, p.k_global)
    for mola in modelo.molas.values():
        montador.somar_diagonal(modelo.gdl(mola.no), mola.vetor)
    return montador.matriz()


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


# ---------------------------------------------------------------------------
# Base de cálculo: graus livres e diafragmas
# ---------------------------------------------------------------------------

@dataclass
class Base:
    """As incógnitas do sistema e como elas viram deslocamento nodal.

    ``T`` é ``None`` quando não há diafragma: aí reduzir é só escolher os
    graus livres, exatamente como antes, sem matriz de transformação nenhuma.
    """

    livres: np.ndarray
    restritos: np.ndarray
    T: sp.csr_matrix | None
    nomes: list[str]
    diafragmas: list = field(default_factory=list)

    @property
    def m(self) -> int:
        return len(self.nomes)

    def reduzir(self, K):
        """``Tᵀ·K·T`` — a matriz nas incógnitas."""
        if self.T is None:
            if sp.issparse(K):
                K = K.tocsr()
                return K[self.livres][:, self.livres]
            return K[np.ix_(self.livres, self.livres)]
        if sp.issparse(K):
            return (self.T.T @ K @ self.T).tocsr()
        return np.asarray(self.T.T @ (self.T.T @ K.T).T)

    def reduzir_vetor(self, v: np.ndarray) -> np.ndarray:
        if self.T is None:
            return v[self.livres]
        return self.T.T @ v

    def expandir(self, r: np.ndarray) -> np.ndarray:
        """O deslocamento nodal completo que as incógnitas ``r`` produzem."""
        n = self.livres.size + self.restritos.size
        if self.T is None:
            D = np.zeros(n)
            D[self.livres] = r
            return D
        return np.asarray(self.T @ r).ravel()


def base_de_calculo(modelo: Modelo) -> Base:
    """Monta a base: os graus livres e, se houver, os diafragmas."""
    from .diafragma import GRAUS_DO_DIAFRAGMA, diafragmas

    livres, restritos = particionar(modelo)
    grupos = diafragmas(modelo)
    if not grupos:
        return Base(livres, restritos, None,
                    [_nomear(modelo, [g]) for g in livres])

    escravos: dict[int, tuple[int, int, float, float]] = {}
    for k, d in enumerate(grupos):
        for no in d.nos:
            n = modelo.nos[no]
            base = 6 * modelo.indice(no)
            dx, dy = n.x - d.centro[0], n.y - d.centro[1]
            for grau in GRAUS_DO_DIAFRAGMA:
                escravos[base + grau] = (k, grau, dx, dy)

    independentes = [g for g in livres if g not in escravos]
    coluna = {g: i for i, g in enumerate(independentes)}
    nomes = [_nomear(modelo, [g]) for g in independentes]
    primeira_do_pavimento = len(independentes)
    for d in grupos:
        rotulo = f"diafragma z={d.cota:g}"
        nomes += [f"{rotulo}.Ux", f"{rotulo}.Uy", f"{rotulo}.Rz"]

    linhas, colunas, valores = [], [], []
    for g in independentes:
        linhas.append(g)
        colunas.append(coluna[g])
        valores.append(1.0)
    for g, (k, grau, dx, dy) in escravos.items():
        ux, uy, rz = (primeira_do_pavimento + 3 * k + i for i in range(3))
        if grau == 0:              # ux = Ux − Rz·dy
            linhas += [g, g]
            colunas += [ux, rz]
            valores += [1.0, -dy]
        elif grau == 1:            # uy = Uy + Rz·dx
            linhas += [g, g]
            colunas += [uy, rz]
            valores += [1.0, dx]
        else:                      # rz = Rz
            linhas.append(g)
            colunas.append(rz)
            valores.append(1.0)
    T = sp.coo_matrix((valores, (linhas, colunas)),
                      shape=(modelo.n_gdl, len(nomes))).tocsr()
    return Base(livres, restritos, T, nomes, grupos)


# ---------------------------------------------------------------------------
# Solução
# ---------------------------------------------------------------------------

def _mecanismo(nomes: list[str], Kff: np.ndarray) -> str:
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
    return ", ".join(nomes[i] for i in principais)


def _fatorar_e_resolver(nomes: list[str], Kff, carga: np.ndarray) -> np.ndarray:
    """Fatoração com conferência de pivô, densa ou esparsa.

    A matriz de uma estrutura bem vinculada é positiva definida. Se a
    fatoração falha, ou se algum pivô desaba em relação ao termo original da
    diagonal, o modelo tem mecanismo — e aí interessa dizer onde, não apenas
    que existe. Confiar no ``solve`` genérico é pior do que parece: diante de
    um modo de corpo rígido ele às vezes devolve números em vez de erro.
    """
    if sp.issparse(Kff):
        diagonal = Kff.diagonal()
    else:
        diagonal = np.diag(Kff)

    maior = float(np.max(np.abs(diagonal))) if diagonal.size else 0.0
    soltos = np.flatnonzero(np.abs(diagonal) < 1.0e-12 * maior)
    if soltos.size:
        raise ErroDeModelo(
            "estrutura instável: sem rigidez alguma nos graus de liberdade "
            + ", ".join(nomes[i] for i in soltos[:6]))

    if sp.issparse(Kff):
        from scipy.sparse.linalg import splu
        try:
            lu = splu(Kff.tocsc(), permc_spec="MMD_AT_PLUS_A",
                      diag_pivot_thresh=0.0)
        except RuntimeError:
            raise ErroDeModelo(
                "estrutura instável: a matriz de rigidez é singular (há "
                "mecanismo)") from None
        pivos = np.abs(lu.U.diagonal())
        originais = np.abs(diagonal[lu.perm_c])
        razao = pivos / np.where(originais > 0.0, originais, 1.0)
        fracos = np.flatnonzero(razao < TOL_PIVO)
        if fracos.size:
            raise ErroDeModelo(
                "estrutura instável: a rigidez se anula durante a eliminação "
                "nos graus de liberdade "
                + ", ".join(nomes[lu.perm_c[i]] for i in fracos[:6]))
        return lu.solve(carga)

    try:
        fator = cho_factor(Kff, lower=True)
    except LinAlgError:
        raise ErroDeModelo(
            "estrutura instável: há mecanismo envolvendo "
            f"{_mecanismo(nomes, Kff)}") from None

    razao = np.diag(fator[0]) ** 2 / diagonal
    fracos = np.flatnonzero(razao < TOL_PIVO)
    if fracos.size:
        raise ErroDeModelo(
            "estrutura instável: a rigidez se anula durante a eliminação nos "
            "graus de liberdade " + ", ".join(nomes[i] for i in fracos[:6]))
    return cho_solve(fator, carga)


def resolver_deslocamentos(modelo: Modelo, K, P: np.ndarray, base: Base,
                           prescritos: np.ndarray) -> np.ndarray:
    """O deslocamento nodal completo: ``D = D₀ + T·r``.

    Recalque prescrito entra como carga: ``Tᵀ·K·T·r = Tᵀ·(P − K·D₀)``.
    """
    # Estrutura toda restringida não é erro: é o caso da barra biengastada sem
    # nó intermediário, em que a carga inteira vai direto para os apoios e os
    # esforços saem só do engastamento perfeito.
    if base.m == 0:
        return prescritos.copy()
    Kr = base.reduzir(K)
    carga = base.reduzir_vetor(P - K @ prescritos)
    r = _fatorar_e_resolver(base.nomes, Kr, carga)
    return prescritos + base.expandir(r)


def _resolver_sistema(modelo: Modelo, K, P: np.ndarray, livres: np.ndarray,
                      prescritos: np.ndarray) -> np.ndarray:
    """Compatibilidade: a solução só nos graus livres, sem diafragma."""
    base = Base(livres, np.array([], int), None,
                [_nomear(modelo, [g]) for g in livres])
    if livres.size == 0:
        return np.zeros(0)
    Kff = base.reduzir(K)
    carga = P[livres] - K[livres] @ prescritos if sp.issparse(K) else \
        P[livres] - K[np.ix_(livres, np.arange(K.shape[0]))] @ prescritos
    return _fatorar_e_resolver(base.nomes, Kff, carga)


def reacoes_das_molas(modelo: Modelo, base: Base,
                      D: np.ndarray) -> dict[str, np.ndarray]:
    # Onde há apoio, a força da mola já está dentro da reação do apoio; contar
    # as duas somaria a mesma força duas vezes no equilíbrio global.
    livre_por_gdl = np.zeros(modelo.n_gdl, dtype=bool)
    livre_por_gdl[base.livres] = True
    return {mola.no: -mola.vetor * D[modelo.gdl(mola.no)]
            * livre_por_gdl[modelo.gdl(mola.no)]
            for mola in modelo.molas.values()}


def usa_grelha(modelo: Modelo) -> bool:
    return bool(modelo.calculo.grelha and modelo.lajes)


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

    if usa_grelha(modelo):
        from .grelha import resolver_com_grelha
        return resolver_com_grelha(modelo, carregamento, resolver_caso)
    return resolver_caso(modelo, carregamento)


def resolver_caso(modelo: Modelo, carregamento: CasoDeCarga) -> Resultado:
    """A 1ª ordem de um caso dado como objeto — dentro ou fora do modelo."""
    preparadas = preparar_barras(modelo)
    segmentos = cargas_locais(carregamento, preparadas)
    K = matriz_global(modelo, preparadas)
    P = vetor_cargas(modelo, carregamento, preparadas, segmentos)
    base = base_de_calculo(modelo)

    # ``validar`` já garante que só há recalque em grau de liberdade com
    # apoio, então o vetor é nulo nas posições livres, como a partição exige.
    D = resolver_deslocamentos(modelo, K, P, base,
                               vetor_recalques(modelo, carregamento))

    reacoes = K @ D - P

    # Os esforços são os das extremidades do **vão flexível** — na face do
    # apoio, portanto, e não no eixo dele. É o que se quer para dimensionar.
    esforcos = {}
    for nome, p in preparadas.items():
        d = D[np.array(p.gdl)]
        esforcos[nome] = (p.k_local @ (p.TH @ d)
                          + p.engastamento(segmentos[nome]))

    return Resultado(modelo=modelo, caso=carregamento.nome, deslocamentos=D,
                     reacoes=reacoes, esforcos=esforcos,
                     preparadas=preparadas, segmentos=segmentos,
                     gdl_restritos=base.restritos,
                     reacoes_mola=reacoes_das_molas(modelo, base, D))
