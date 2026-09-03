# -*- coding: utf-8 -*-
"""
estabilidade.py
Estabilidade global pela ABNT NBR 6118:2026, seção 15.

Referências desta edição, conferidas no PDF da norma:

* 15.4.2   estruturas de nós fixos e de nós móveis — o critério dos 10 %
* 15.5.1   na análise global, E_cs pode ser majorado em 10 %
* 15.5.2   parâmetro de instabilidade α e os limites α1
* 15.5.3   coeficiente γ_z, válido a partir de quatro andares
* 15.7.2   majoração das ações horizontais por 0,95·γ_z, só para γ_z ≤ 1,3
* 15.7.3   rigidez secante aproximada para a não linearidade física

Uma nota sobre 15.7.3 que vale ler antes de usar: a edição de 2014 permitia,
para estrutura de contraventamento composta exclusivamente por vigas e pilares
com γ_z < 1,3, adotar o valor único (EI)_sec = 0,7·E_ci·I_c. **Esse parágrafo
não consta na edição 2026** — a leitura do PDF procurou por ele e não o
encontrou. Quem vier de projetos antigos vai estranhar; por isso o valor único
não é oferecido aqui.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .combinacoes import Combinacao
from .modelo import CasoDeCarga, ErroDeModelo, Modelo, Secao
from .nbr6118 import cargas_verticais_por_no
from .resultados import Resultado

# 15.7.3 — rigidez secante como fração de E_c·I_c
RIGIDEZ_LAJE = 0.3
RIGIDEZ_VIGA_ASSIMETRICA = 0.4
RIGIDEZ_VIGA_SIMETRICA = 0.5
RIGIDEZ_PILAR = 0.8

# 15.5.1 — majoração do módulo de deformação secante na análise global
MAJORACAO_ECS = 1.10

# 15.5.3 e 15.7.2
GAMA_Z_NOS_FIXOS = 1.10
GAMA_Z_LIMITE_MAJORACAO = 1.30
ANDARES_MINIMOS_GAMA_Z = 4


def _base(modelo: Modelo) -> float:
    return min(no.z for no in modelo.nos.values())


def _direcao_horizontal(modelo: Modelo, caso: CasoDeCarga
                        ) -> tuple[float, float]:
    """Direção da resultante horizontal das cargas nodais do caso."""
    fx = sum(c.fx for c in caso.nodais)
    fy = sum(c.fy for c in caso.nodais)
    norma = math.hypot(fx, fy)
    if norma < 1e-12:
        raise ErroDeModelo(
            f"o caso '{caso.nome}' não tem resultante horizontal: sem ela não "
            "há direção em que avaliar a estabilidade global")
    return fx / norma, fy / norma


def contar_andares(modelo: Modelo, tolerancia: float = 1e-6) -> int:
    """Níveis de barras horizontais acima da fundação — o ``n`` de 15.5.2."""
    base = _base(modelo)
    cotas = set()
    for barra in modelo.barras.values():
        pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
        if abs(pi[2] - pj[2]) <= tolerancia and pi[2] > base + tolerancia:
            cotas.add(round(pi[2] / tolerancia) * tolerancia)
    return len(cotas)


# ---------------------------------------------------------------------------
# 15.5.3 — coeficiente γ_z
# ---------------------------------------------------------------------------

@dataclass
class GamaZ:
    combinacao: str
    direcao: tuple[float, float]
    m1_tot_d: float
    delta_m_tot_d: float
    valor: float
    n_andares: int

    @property
    def nos_fixos(self) -> bool:
        """15.5.3: a estrutura é de nós fixos se γ_z ≤ 1,1."""
        return self.valor <= GAMA_Z_NOS_FIXOS

    @property
    def aplicavel(self) -> bool:
        """15.5.3: o processo vale para reticuladas de no mínimo quatro andares."""
        return self.n_andares >= ANDARES_MINIMOS_GAMA_Z

    @property
    def majoracao_valida(self) -> bool:
        """15.7.2: a majoração por 0,95·γ_z só vale para γ_z ≤ 1,3."""
        return self.valor <= GAMA_Z_LIMITE_MAJORACAO

    @property
    def fator_majoracao(self) -> float:
        return 0.95 * self.valor

    def __str__(self) -> str:
        estado = "nós fixos" if self.nos_fixos else "nós móveis"
        linhas = [
            f"γz de '{self.combinacao}' = {self.valor:.4f}  ({estado})",
            f"  M1,tot,d = {self.m1_tot_d:.4f}   "
            f"ΔMtot,d = {self.delta_m_tot_d:.4f}   "
            f"n = {self.n_andares} andares",
        ]
        if not self.aplicavel:
            linhas.append(
                f"  ATENÇÃO: 15.5.3 pede no mínimo {ANDARES_MINIMOS_GAMA_Z} "
                "andares; aqui o γz é informativo, não normativo")
        if not self.majoracao_valida:
            linhas.append(
                "  ATENÇÃO: γz acima de 1,3 — 15.7.2 não autoriza a majoração "
                "por 0,95·γz; é caso de análise de segunda ordem de verdade")
        return "\n".join(linhas)


def gama_z(modelo: Modelo, caso: CasoDeCarga, resultado: Resultado,
           direcao: tuple[float, float] | None = None) -> GamaZ:
    """Coeficiente γ_z de uma combinação — item 15.5.3.

        γz = 1 / (1 − ΔMtot,d / M1,tot,d)

    ``M1,tot,d`` é o momento de tombamento: a soma dos momentos de todas as
    forças horizontais da combinação, com valores de cálculo, em relação à
    base. ``ΔMtot,d`` é a soma dos produtos de todas as forças verticais pelos
    deslocamentos horizontais dos seus pontos de aplicação, **obtidos da
    análise de primeira ordem**.

    O ``caso`` e o ``resultado`` têm de ser os da mesma combinação, já com os
    valores de cálculo — daí a exigência de passar os dois: o caso traz as
    cargas, o resultado traz os deslocamentos.
    """
    if resultado.segunda_ordem:
        raise ErroDeModelo(
            "o γz sai da análise de primeira ordem (15.5.3), e o resultado "
            "recebido é de segunda ordem")

    d = direcao if direcao is not None else _direcao_horizontal(modelo, caso)
    base = _base(modelo)

    m1 = 0.0
    for carga in caso.nodais:
        braco = modelo.ponto(carga.no)[2] - base
        m1 += (carga.fx * d[0] + carga.fy * d[1]) * braco
    if abs(m1) < 1e-12:
        raise ErroDeModelo(
            f"momento de tombamento nulo em '{caso.nome}': o γz não é "
            "definido sem ação horizontal")

    delta_m = 0.0
    for no, vertical in cargas_verticais_por_no(modelo, caso).items():
        if vertical == 0.0:
            continue
        deslocamento = resultado.deslocamento(no)
        delta_m += vertical * (deslocamento[0] * d[0] + deslocamento[1] * d[1])

    razao = delta_m / m1
    if razao >= 1.0:
        raise ErroDeModelo(
            f"ΔMtot,d supera M1,tot,d em '{caso.nome}': a estrutura já perdeu "
            "estabilidade e o γz não tem significado")

    return GamaZ(caso.nome, d, m1, delta_m, 1.0 / (1.0 - razao),
                 contar_andares(modelo))


# ---------------------------------------------------------------------------
# 15.5.2 — parâmetro de instabilidade α
# ---------------------------------------------------------------------------

@dataclass
class Alfa:
    alfa: float
    limite: float
    H_tot: float
    N_k: float
    EI_equivalente: float
    n_andares: int
    contraventamento: str

    @property
    def nos_fixos(self) -> bool:
        return self.alfa < self.limite

    def __str__(self) -> str:
        estado = "nós fixos" if self.nos_fixos else "nós móveis"
        return (f"α = {self.alfa:.4f}  α1 = {self.limite:.2f}  ({estado})\n"
                f"  Htot = {self.H_tot:.3f}  Nk = {self.N_k:.3f}  "
                f"EI equivalente = {self.EI_equivalente:.4e}  "
                f"n = {self.n_andares}  contraventamento: "
                f"{self.contraventamento}")


def alfa_limite(n_andares: int, contraventamento: str = "associacao") -> float:
    """Valor-limite α1 do item 15.5.2.

    Para até três andares o limite cresce com o número de níveis. De quatro em
    diante ele passa a depender do que contraventa: 0,5 se só houver pórticos,
    0,7 se o contraventamento for exclusivamente de pilares-parede, e 0,6 nas
    associações dos dois — que é o caso das estruturas usuais de edifícios.
    """
    if n_andares <= 3:
        return 0.2 + 0.1 * n_andares
    limites = {"porticos": 0.5, "associacao": 0.6, "pilares_parede": 0.7}
    if contraventamento not in limites:
        raise ErroDeModelo(
            f"contraventamento '{contraventamento}' desconhecido; use um de "
            f"{', '.join(limites)}")
    return limites[contraventamento]


def rigidez_equivalente(modelo: Modelo, caso: CasoDeCarga,
                        resultado: Resultado,
                        direcao: tuple[float, float] | None = None) -> float:
    """E_cs·I_c do pilar equivalente, pelo procedimento de 15.5.2.

    A norma manda calcular o deslocamento do topo sob o carregamento
    horizontal e achar a rigidez de um pilar de seção constante, engastado na
    base e livre no topo, de mesma altura, que sofra o mesmo deslocamento sob
    o mesmo carregamento. Para forças concentradas nas cotas ``z_i``, o topo
    do pilar equivalente desloca ``Σ F_i·z_i²·(3H − z_i)/(6EI)``, e daí sai o
    ``EI`` que iguala os dois deslocamentos.
    """
    d = direcao if direcao is not None else _direcao_horizontal(modelo, caso)
    base = _base(modelo)
    H = max(no.z for no in modelo.nos.values()) - base

    numerador = 0.0
    for carga in caso.nodais:
        z = modelo.ponto(carga.no)[2] - base
        F = carga.fx * d[0] + carga.fy * d[1]
        numerador += F * z ** 2 * (3.0 * H - z) / 6.0

    topo = [no for no in modelo.nos
            if abs(modelo.ponto(no)[2] - base - H) < 1e-6]
    deslocamentos = [resultado.deslocamento(no)[0] * d[0]
                     + resultado.deslocamento(no)[1] * d[1] for no in topo]
    if not deslocamentos:
        raise ErroDeModelo("não há nó no topo para medir o deslocamento")
    delta = sum(deslocamentos) / len(deslocamentos)

    if abs(delta) < 1e-15:
        raise ErroDeModelo(
            "deslocamento de topo nulo: não dá para extrair a rigidez "
            "equivalente de uma estrutura que não se deslocou")
    return numerador / delta


def parametro_alfa(modelo: Modelo, caso_horizontal: CasoDeCarga,
                   resultado: Resultado, caso_vertical_caracteristico: CasoDeCarga,
                   contraventamento: str = "associacao",
                   direcao: tuple[float, float] | None = None) -> Alfa:
    """Parâmetro de instabilidade α — item 15.5.2.

        α = H_tot · √( N_k / (E_cs·I_c) )

    Atenção às duas naturezas de carga que entram aqui. O ``N_k`` é o
    somatório das cargas verticais com o seu **valor característico**, e não de
    cálculo — ao contrário do γz, que trabalha com valores de cálculo. Por isso
    os dois casos são pedidos em separado: o horizontal, que dá a direção e a
    rigidez equivalente, e o vertical característico, que dá o N_k.
    """
    base = _base(modelo)
    H_tot = max(no.z for no in modelo.nos.values()) - base
    if H_tot <= 0.0:
        raise ErroDeModelo("altura total nula")

    N_k = sum(cargas_verticais_por_no(
        modelo, caso_vertical_caracteristico).values())
    if N_k <= 0.0:
        raise ErroDeModelo(
            "carga vertical característica nula ou de sinal invertido: o α "
            "precisa do somatório das cargas verticais descendentes")

    EI = rigidez_equivalente(modelo, caso_horizontal, resultado, direcao)
    n = contar_andares(modelo)

    return Alfa(H_tot * math.sqrt(N_k / EI), alfa_limite(n, contraventamento),
                H_tot, N_k, EI, n, contraventamento)


# ---------------------------------------------------------------------------
# 15.7.2 — majoração das ações horizontais
# ---------------------------------------------------------------------------

def majorar_horizontais(modelo: Modelo, combinacao: Combinacao,
                        gama: GamaZ,
                        casos_horizontais: list[str] | None = None
                        ) -> Combinacao:
    """Combinação com as ações horizontais majoradas por 0,95·γ_z — 15.7.2.

    Os casos horizontais são reconhecidos por não terem carga vertical, e a
    lista pode ser dada explicitamente quando essa leitura não servir. O
    processo só é válido para γ_z ≤ 1,3, e acima disso o pedido é recusado em
    vez de devolver número: passar disso é caso de análise de segunda ordem, e
    não de majoração.
    """
    if not gama.majoracao_valida:
        raise ErroDeModelo(
            f"γz = {gama.valor:.4f} passa de {GAMA_Z_LIMITE_MAJORACAO}: o "
            "item 15.7.2 não autoriza a majoração por 0,95·γz nesse caso — "
            "faça a análise de segunda ordem")

    if casos_horizontais is None:
        casos_horizontais = [
            nome for nome in combinacao.fatores
            if abs(sum(cargas_verticais_por_no(
                modelo, modelo.casos[nome]).values())) < 1e-9]

    fator = gama.fator_majoracao
    fatores = {nome: (valor * fator if nome in casos_horizontais else valor)
               for nome, valor in combinacao.fatores.items()}

    return Combinacao(f"{combinacao.nome} × 0,95γz", fatores, combinacao.tipo,
                      f"{combinacao.descricao}; horizontais majoradas por "
                      f"0,95·γz = {fator:.4f}")


# ---------------------------------------------------------------------------
# 15.7.3 — rigidez secante aproximada
# ---------------------------------------------------------------------------

@dataclass
class RigidezSecante:
    modelo: Modelo
    fatores: dict[str, float] = field(default_factory=dict)

    def __str__(self) -> str:
        por_fator: dict[float, list[str]] = {}
        for barra, fator in self.fatores.items():
            por_fator.setdefault(fator, []).append(barra)
        return "rigidez secante: " + "; ".join(
            f"{len(barras)} barras × {fator:.1f}"
            for fator, barras in sorted(por_fator.items()))


def rigidez_secante(modelo: Modelo, vigas_simetricas: list[str] | None = None,
                    lajes: list[str] | None = None,
                    tolerancia: float = 1e-6) -> RigidezSecante:
    """Modelo com a rigidez reduzida do item 15.7.3.

        lajes  0,3·E_c·I_c
        vigas  0,4·E_c·I_c, ou 0,5 quando A_s' = A_s
        pilares 0,8·E_c·I_c

    Barra vertical é tomada como pilar e o resto como viga; ``vigas_simetricas``
    e ``lajes`` corrigem essa leitura onde ela não servir. A redução entra nas
    inércias, e não no módulo, para que a rigidez axial não seja reduzida
    junto — o item fala de (EI)_sec.

    Estes valores são para os esforços **globais** de segunda ordem. A própria
    norma avisa que não servem para avaliar efeitos locais, por mais refinada
    que seja a discretização.
    """
    vigas_simetricas = set(vigas_simetricas or [])
    lajes = set(lajes or [])

    novo = replace(modelo, nome=f"{modelo.nome} (rigidez secante)",
                   secoes=dict(modelo.secoes), barras={})
    fatores: dict[str, float] = {}
    cache: dict[tuple[str, float], str] = {}

    for nome, barra in modelo.barras.items():
        if nome in lajes:
            fator = RIGIDEZ_LAJE
        elif nome in vigas_simetricas:
            fator = RIGIDEZ_VIGA_SIMETRICA
        else:
            pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
            vertical = math.hypot(pi[0] - pj[0], pi[1] - pj[1]) <= tolerancia
            fator = RIGIDEZ_PILAR if vertical else RIGIDEZ_VIGA_ASSIMETRICA

        chave = (barra.secao, fator)
        if chave not in cache:
            original = modelo.secoes[barra.secao]
            reduzida = f"{original.nome} ({fator:.1f} EI)"
            novo.secoes[reduzida] = Secao(
                reduzida, original.A, fator * original.Iy,
                fator * original.Iz, fator * original.J)
            cache[chave] = reduzida

        novo.barras[nome] = replace(barra, secao=cache[chave])
        fatores[nome] = fator

    return RigidezSecante(novo, fatores)
