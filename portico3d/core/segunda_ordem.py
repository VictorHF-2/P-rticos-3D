# -*- coding: utf-8 -*-
"""
segunda_ordem.py
Efeitos de segunda ordem: P-Δ e flambagem elástica.

As duas análises saem da mesma peça, a matriz de rigidez geométrica, que
depende do esforço normal das barras — e é essa dependência que quebra a
linearidade. Duas consequências que mudam como o programa é usado:

* **A superposição deixa de valer.** Cada combinação precisa ser resolvida por
  si, com as cargas já ponderadas, e não somando respostas de casos. É para
  isso que existe ``combinacoes.caso_efetivo``.
* **Existe uma carga a partir da qual não há solução.** Quando o carregamento
  passa da carga crítica, a matriz deixa de ser positiva definida e a iteração
  não converge — o que não é falha numérica, é a estrutura dizendo que perdeu
  estabilidade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.linalg import eigh

from .combinacoes import Combinacao, caso_efetivo
from .elemento import (BarraPreparada, rigidez_geometrica,
                       rigidez_geometrica_refinada)
from .modelo import CasoDeCarga, ErroDeModelo, Modelo
from .montagem import (Montador, base_de_calculo, cargas_locais, esparsa,
                       matriz_global, preparar_barras, reacoes_das_molas,
                       resolver_deslocamentos, usa_grelha, vetor_cargas,
                       vetor_recalques)
from .resultados import Resultado

MAX_ITERACOES = 40
TOLERANCIA = 1.0e-9


def esforco_normal(esforcos: np.ndarray) -> float:
    """Normal médio da barra, positivo à tração.

    Nas duas extremidades o normal vale ``-q[0]`` e ``q[6]``; com carga axial
    distribuída eles diferem, e a matriz geométrica usa a média.
    """
    return float((esforcos[6] - esforcos[0]) / 2.0)


def _kg_da_barra(p: BarraPreparada, N: float) -> np.ndarray:
    """A rigidez geométrica local de uma barra, na versão que vale para ela.

    A refinada exige continuidade nos dois planos de flexão: com uma
    liberação, o giro que falta na extremidade não é o de uma barra contínua
    subdividida, e a condensação passaria a representar outra peça. Com
    liberação, a de sempre; sem, a que converge melhor.
    """
    kg = (rigidez_geometrica_refinada(p.Lf, N, p.material, p.secao)
          if not p.liberados
          else rigidez_geometrica(p.Lf, N, p.secao))
    # As liberações valem para a rigidez geométrica pelo mesmo motivo que
    # valem para a elástica: o grau de liberdade solto não transmite
    # esforço, venha ele de onde vier.
    if p.liberados:
        kg[p.liberados, :] = 0.0
        kg[:, p.liberados] = 0.0
    return kg


def matriz_geometrica_global(modelo: Modelo,
                             preparadas: dict[str, BarraPreparada],
                             normais: dict[str, float]) -> np.ndarray:
    montador = Montador(modelo.n_gdl, esparsa(modelo))
    for nome, p in preparadas.items():
        N = normais.get(nome, 0.0)
        if N == 0.0:
            continue
        kg = _kg_da_barra(p, N)
        montador.somar(p.gdl, p.TH.T @ kg @ p.TH)
    return montador.matriz()


def _montar(modelo: Modelo, caso: CasoDeCarga):
    preparadas = preparar_barras(modelo)
    segmentos = cargas_locais(caso, preparadas)
    Ke = matriz_global(modelo, preparadas)
    P = vetor_cargas(modelo, caso, preparadas, segmentos)
    base = base_de_calculo(modelo)
    prescritos = vetor_recalques(modelo, caso)
    return preparadas, segmentos, Ke, P, base, prescritos


def _esforcos_das_barras(preparadas, segmentos, D,
                         normais: dict[str, float] | None = None
                         ) -> dict[str, np.ndarray]:
    """Esforços nas extremidades de cada barra, a partir do deslocamento.

    ``normais`` é o que faz a diferença na segunda ordem. Sem ele (o caso da
    análise linear, e da passada de primeira ordem que estima os normais para
    a flambagem), o esforço vem só da rigidez elástica — não há geometria
    ainda a somar. **Com** ele, soma-se também a rigidez geométrica da barra:
    ``(Ke + Kg)·D``, e não ``Ke·D`` sozinho.

    A omissão do ``Kg`` aqui era o que fazia o momento recuperado de um P-Δ
    com uma barra por pilar errar a solução fechada em 6,6 % — o
    deslocamento já saía correto (a montagem ``Ke+Kg`` estava certa), mas a
    conversão de volta para esforço jogava fora a metade geométrica que a
    tinha corrigido. Somando-a, o mesmo caso de referência cai para 0,13 %,
    sem precisar de malha nenhuma — e a rigidez geométrica **refinada**
    ainda reduz esse resíduo mais um pouco, porque entra tanto na montagem
    quanto, agora, na recuperação.
    """
    saida = {}
    for nome, p in preparadas.items():
        d_local = p.TH @ D[np.array(p.gdl)]
        k = p.k_local
        if normais is not None:
            N = normais.get(nome, 0.0)
            if N != 0.0:
                k = k + _kg_da_barra(p, N)
        saida[nome] = k @ d_local + p.engastamento(segmentos[nome])
    return saida


def resolver_p_delta(modelo: Modelo, caso: CasoDeCarga | str,
                     max_iteracoes: int = MAX_ITERACOES,
                     tolerancia: float = TOLERANCIA) -> Resultado:
    """Análise de segunda ordem por iteração sobre a rigidez geométrica.

    A cada passo, o esforço normal da iteração anterior monta a matriz
    geométrica, o sistema é resolvido de novo, e os normais são recalculados —
    até que os deslocamentos parem de mudar. Como só a rigidez muda de uma
    iteração para a outra, e não o carregamento, a convergência é monotônica
    enquanto a carga estiver abaixo da crítica.
    """
    modelo.validar()
    if isinstance(caso, str):
        if caso not in modelo.casos:
            raise ErroDeModelo(f"caso de carga '{caso}' não existe")
        caso = modelo.casos[caso]

    if usa_grelha(modelo):
        from .grelha import resolver_com_grelha
        return resolver_com_grelha(
            modelo, caso, lambda m, c: resolver_p_delta(
                m, c, max_iteracoes, tolerancia))

    preparadas, segmentos, Ke, P, base, prescritos = _montar(modelo, caso)

    D = prescritos.copy()
    normais = {nome: 0.0 for nome in modelo.barras}
    iteracoes = 0

    for iteracoes in range(1, max_iteracoes + 1):
        Kg = matriz_geometrica_global(modelo, preparadas, normais)
        try:
            D_novo = resolver_deslocamentos(modelo, Ke + Kg, P, base,
                                            prescritos)
        except ErroDeModelo as erro:
            raise ErroDeModelo(
                "a segunda ordem não tem solução para este carregamento: a "
                "rigidez geométrica anulou a rigidez da estrutura, o que "
                "significa carga acima da crítica. Rode a análise de "
                f"flambagem para ver a margem. Causa imediata: {erro}"
            ) from None

        escala = float(np.max(np.abs(D_novo)))
        variacao = float(np.max(np.abs(D_novo - D)))
        D = D_novo
        # Os normais que entram aqui são os que montaram o ``Kg`` desta
        # mesma iteração: a recuperação usa o estado de esforço normal
        # consistente com a rigidez que gerou este ``D``, e não o que só vai
        # ser conhecido depois de recuperar os esforços.
        esforcos = _esforcos_das_barras(preparadas, segmentos, D, normais)
        normais = {nome: esforco_normal(q) for nome, q in esforcos.items()}

        if escala == 0.0 or variacao <= tolerancia * escala:
            break
    else:
        raise ErroDeModelo(
            f"a segunda ordem não convergiu em {max_iteracoes} iterações; a "
            "carga deve estar próxima da crítica")

    Kg = matriz_geometrica_global(modelo, preparadas, normais)
    reacoes = (Ke + Kg) @ D - P
    reacoes_mola = reacoes_das_molas(modelo, base, D)

    return Resultado(modelo=modelo, caso=caso.nome, deslocamentos=D,
                     reacoes=reacoes, esforcos=esforcos,
                     preparadas=preparadas, segmentos=segmentos,
                     gdl_restritos=base.restritos, reacoes_mola=reacoes_mola,
                     iteracoes=iteracoes, segunda_ordem=True)


def resolver_combinacoes_p_delta(modelo: Modelo,
                                 combinacoes: list[Combinacao]
                                 ) -> dict[str, Resultado]:
    """Resolve cada combinação em segunda ordem, uma por uma.

    Não há atalho por superposição aqui, e é essa a diferença de custo em
    relação à análise linear: são tantas análises quantas forem as combinações.
    """
    return {c.nome: resolver_p_delta(modelo, caso_efetivo(modelo, c))
            for c in combinacoes}


# ---------------------------------------------------------------------------
# Flambagem elástica
# ---------------------------------------------------------------------------

@dataclass
class Flambagem:
    """Cargas críticas como multiplicadores do carregamento de referência."""

    caso: str
    fatores: list[float]
    modos: list[np.ndarray] = field(default_factory=list)
    modelo: Modelo | None = None

    @property
    def fator_critico(self) -> float:
        return self.fatores[0]

    def modo(self, indice: int = 0) -> dict[str, np.ndarray]:
        """O modo de flambagem, nó a nó, normalizado pelo maior deslocamento."""
        if self.modelo is None:
            raise ErroDeModelo("modo de flambagem sem modelo associado")
        vetor = self.modos[indice]
        pico = float(np.max(np.abs(vetor))) or 1.0
        return {no: vetor[self.modelo.gdl(no)] / pico
                for no in self.modelo.nos}

    def __str__(self) -> str:
        fatores = ", ".join(f"{f:.4f}" for f in self.fatores)
        return (f"flambagem sob '{self.caso}': fatores críticos {fatores} "
                f"(o carregamento cabe {self.fator_critico:.3f} vezes)")


def flambagem(modelo: Modelo, caso: CasoDeCarga | str,
              n_modos: int = 3) -> Flambagem:
    """Carga crítica elástica e modos, por problema de autovalor.

    Resolve ``(Ke + λ·Kg)·φ = 0`` na forma ``-Kg·φ = μ·Ke·φ``, com ``λ = 1/μ``.
    A troca importa: ``Ke`` restrita aos graus livres é positiva definida, e
    ``-Kg`` não é — pôr a positiva definida no lugar de ``B`` é o que deixa o
    problema bem posto para o autossolver simétrico.

    O ``λ`` devolvido é o **multiplicador do carregamento de referência**: vale
    1,0 quando a estrutura está exatamente na iminência de flambar sob a carga
    dada, e quanto maior, maior a folga.
    """
    modelo.validar()
    if isinstance(caso, str):
        if caso not in modelo.casos:
            raise ErroDeModelo(f"caso de carga '{caso}' não existe")
        caso = modelo.casos[caso]

    if usa_grelha(modelo):
        from .grelha import flambagem_com_grelha
        return flambagem_com_grelha(modelo, caso, n_modos)

    preparadas, segmentos, Ke, P, base, prescritos = _montar(modelo, caso)

    D = resolver_deslocamentos(modelo, Ke, P, base, prescritos)
    esforcos = _esforcos_das_barras(preparadas, segmentos, D)
    normais = {nome: esforco_normal(q) for nome, q in esforcos.items()}

    if all(N >= 0.0 for N in normais.values()):
        raise ErroDeModelo(
            "não há barra comprimida neste carregamento: sem compressão não "
            "há flambagem a calcular")

    Kg = matriz_geometrica_global(modelo, preparadas, normais)
    A = -base.reduzir(Kg)
    B = base.reduzir(Ke)

    if sp.issparse(B):
        mu, vetores = _autovalores_esparsos(A, B, n_modos)
    else:
        mu, vetores = eigh(A, B)

    positivos = [i for i in range(len(mu)) if mu[i] > 1e-12 * max(abs(mu[-1]),
                                                                 1e-300)]
    if not positivos:
        raise ErroDeModelo(
            "nenhum modo de flambagem com fator positivo: sob este "
            "carregamento a estrutura não perde estabilidade")

    # μ grande é λ pequeno: a ordem de interesse é a inversa da do autossolver.
    ordenados = sorted(positivos, key=lambda i: mu[i], reverse=True)[:n_modos]

    fatores = []
    modos = []
    for i in ordenados:
        fatores.append(1.0 / float(mu[i]))
        modos.append(base.expandir(vetores[:, i]))

    return Flambagem(caso.nome, fatores, modos, modelo)


def _autovalores_esparsos(A, B, n_modos: int):
    """Os maiores ``μ`` de ``A·φ = μ·B·φ`` com ``B`` positiva definida.

    Só os ``n_modos`` de interesse, por Lanczos: na matriz esparsa de uma
    grelha, achar todos os autovalores seria o custo da matriz densa de novo.
    """
    from scipy.sparse.linalg import LinearOperator, eigsh, splu

    m = B.shape[0]
    k = max(1, min(n_modos + 2, m - 1))
    lu = splu(B.tocsc())
    inversa = LinearOperator((m, m), matvec=lu.solve, dtype=float)
    mu, vetores = eigsh(A.tocsr(), k=k, M=B.tocsr(), Minv=inversa,
                        which="LA")
    ordem = np.argsort(mu)
    return mu[ordem], vetores[:, ordem]
