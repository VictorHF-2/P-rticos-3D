# -*- coding: utf-8 -*-
"""
complementares.py
Verificações da NBR 6118:2026 que leem o resultado do dimensionamento sem
alterá-lo (19/11/2026):

* **15.10** -- instabilidade lateral de vigas, pelo procedimento aproximado
  ``b >= l0/50`` e ``b >= βfl·h`` (Tabela 15.1);
* **23.3** -- estado-limite de vibrações excessivas, ``fn > 1,2 fcrit``, com
  a frequência natural da análise modal do modelo de barras (massas da
  combinação frequente, 11.8.3.1) e o piso absoluto de 3 Hz;
* **17.3.3.2 (Nota)** -- a armadura de pele na zona tracionada limita a
  abertura de fissuras na sua região de envolvimento, com espaçamento
  <= 15 Ø.

Unidades: cm, kN, kN·cm; vãos e coordenadas em m; frequências em Hz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import avisos as av
from . import els
from .analise import (Estrutura, _carga_distribuida_no_elemento,
                      graus_restritos)
from .materiais import area_barra
from .modelo import Viga

# ---------------------------------------------------------------------------
# 15.10 -- instabilidade lateral
# ---------------------------------------------------------------------------

#: Tabela 15.1: seções retangular, T e I com a compressão em uma mesa ou
#: alma isolada. O valor 0,20 é de seções com almas ligadas por laje inferior
#: (tipo U ou π invertido), que o programa não modela
BETA_FL = 0.40

#: b >= l0/50
RAZAO_L0_LATERAL = 50.0


@dataclass
class EstabilidadeLateral:
    """Uma zona comprimida de um tramo diante do item 15.10."""

    tramo: int
    face_comprimida: str      # "superior" (vão) ou "inferior" (apoio)
    b: float                  # cm, largura da zona comprimida
    h: float                  # cm
    l0: float                 # m, entre travamentos laterais
    origem_l0: str
    beta_fl: float
    b_min_l0: float           # cm, l0/50
    b_min_beta: float         # cm, βfl·h
    dispensada: bool          # zona comprimida travada pela laje
    critica: bool             # não atendida reprova (erro) ou só alerta
    observacao: str = ""

    @property
    def b_min(self) -> float:
        return max(self.b_min_l0, self.b_min_beta)

    @property
    def atende(self) -> bool:
        return self.dispensada or self.b >= self.b_min - 1e-9

    @property
    def ok(self) -> bool:
        """Reprova só a zona crítica não atendida."""
        return self.atende or not self.critica

    @property
    def veredito(self) -> str:
        if self.dispensada:
            return "DISPENSADA"
        if self.atende:
            return "OK"
        return "NÃO OK" if self.critica else "ALERTA"


def _largura_comprimida(secao, face: str) -> float:
    """b da Tabela 15.1: a mesa se ela está na face comprimida, senão bw."""
    if face == "superior" and secao.tipo == "T":
        return secao.bf
    if face == "inferior" and secao.tipo == "T invertida":
        return secao.bf
    return secao.bw


def verificar_estabilidade_lateral(viga: Viga, x: np.ndarray,
                                   M_max: np.ndarray, M_min: np.ndarray,
                                   avisos: list[str]
                                   ) -> list[EstabilidadeLateral]:
    """Aplica o procedimento aproximado do item 15.10 tramo a tramo.

    Cada tramo tem até duas zonas comprimidas: a de cima, onde a envoltória
    tem momento positivo, e a de baixo, onde tem negativo. ``l0`` é o vão do
    tramo -- os apoios são os suportes que contraventam --, ``2 L`` no
    balanço (a ponta livre não trava nada) e, se o usuário informou uma
    distância máxima entre travamentos laterais, o menor dos dois.

    A face superior travada por laje monolítica dispensa a zona de cima. A de
    baixo continua sendo conferida, mas o não atendimento é **alerta**: o
    banzo tracionado está preso à laje, o que a regra aproximada não
    distingue, e a decisão sobre uma verificação mais refinada é do
    projetista. Sem laje (viga isolada, pré-moldada, fase construtiva) toda
    zona comprimida é crítica e o não atendimento é erro.
    """
    cfg = viga.config
    saida: list[EstabilidadeLateral] = []
    for i, tramo in enumerate(viga.tramos):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        m = (x >= a - 1e-9) & (x <= b + 1e-9)
        if not m.any():
            continue
        balanco = (viga.apoios[i].tipo == "livre"
                   or viga.apoios[i + 1].tipo == "livre")
        l0 = 2.0 * tramo.L if balanco else tramo.L
        origem = "2 L do balanço" if balanco else "vão do tramo"
        if cfg.l0_lateral > 1e-9 and cfg.l0_lateral < l0:
            l0, origem = cfg.l0_lateral, "travamento lateral informado"
        secoes = [t.secao for t in viga.trechos if t.tramo == i] or \
            [tramo.secao]
        h = max(s.h for s in secoes)
        for face, existe in (("superior", float(np.max(M_max[m])) > 1e-6),
                             ("inferior", float(np.min(M_min[m])) < -1e-6)):
            if not existe:
                continue
            largura = min(_largura_comprimida(s, face) for s in secoes)
            dispensada = face == "superior" and cfg.face_superior_travada
            critica = not cfg.face_superior_travada
            obs = ""
            if dispensada:
                obs = ("zona comprimida contida pela laje monolítica da face "
                       "superior: não está sujeita à flambagem lateral")
            item = EstabilidadeLateral(
                tramo=i, face_comprimida=face, b=largura, h=h, l0=l0,
                origem_l0=origem, beta_fl=BETA_FL,
                b_min_l0=l0 * 100.0 / RAZAO_L0_LATERAL,
                b_min_beta=BETA_FL * h, dispensada=dispensada,
                critica=critica, observacao=obs)
            if not item.atende:
                lado = ("zona comprimida superior (vão)" if face == "superior"
                        else "zona comprimida inferior (momento negativo)")
                texto = (f"Tramo {i + 1}, {lado}: b = {largura:.0f} cm é menor "
                         f"que o exigido pelo procedimento aproximado do item "
                         f"15.10, b >= l0/50 = {item.b_min_l0:.1f} cm "
                         f"(l0 = {l0:.2f} m, {origem}) e b >= βfl·h = "
                         f"{BETA_FL:.2f} × {h:.0f} = {item.b_min_beta:.1f} cm.")
                if critica:
                    avisos.append(av.erro(
                        texto + " Viga sem travamento lateral: aumente a "
                                "largura, trave a zona comprimida ou faça uma "
                                "verificação de instabilidade lateral por "
                                "procedimento apropriado."))
                else:
                    item.observacao = ("banzo tracionado preso à laje; a "
                                       "regra aproximada não distingue esse "
                                       "caso")
                    avisos.append(av.construtivo(
                        texto + " A face superior está travada pela laje, mas "
                                "o banzo comprimido é o inferior: avalie se a "
                                "ligação com a laje basta ou verifique por "
                                "procedimento apropriado."))
            saida.append(item)
    return saida


# ---------------------------------------------------------------------------
# 23.3 -- vibrações excessivas
# ---------------------------------------------------------------------------

#: Tabela 23.1 -- frequência crítica para vibrações verticais pela ação de
#: pessoas, Hz
FREQUENCIAS_CRITICAS = {
    "Ginásio de esportes e academias de ginástica": 8.0,
    "Salas de dança ou de concerto sem cadeiras fixas": 7.0,
    "Passarelas de pedestres ou ciclistas": 4.5,
    "Escritórios": 4.0,
    "Salas de concerto com cadeiras fixas": 3.5,
}

#: "Em nenhum caso a frequência natural da estrutura do piso pode ser
#: inferior a 3 Hz" (23.3)
FREQUENCIA_MINIMA_PISO = 3.0

#: aceleração da gravidade, m/s², para passar de peso (kN) a massa (t)
GRAVIDADE = 9.81


@dataclass
class ResultadoVibracao:
    """Frequência natural da viga contra a frequência crítica (23.3)."""

    fn: float                 # Hz, primeiro modo de flexão
    fcrit: float              # Hz
    massa_total: float        # t
    rigidez: str              # de onde saiu o EI
    modos: list[float] = field(default_factory=list)   # Hz, os primeiros

    @property
    def limite(self) -> float:
        return max(1.2 * self.fcrit, FREQUENCIA_MINIMA_PISO)

    @property
    def ok(self) -> bool:
        return self.fn > 1.2 * self.fcrit and \
            self.fn >= FREQUENCIA_MINIMA_PISO - 1e-9

    @property
    def veredito(self) -> str:
        return "OK" if self.ok else "NÃO OK"


def _massa_elemento(m1: float, m2: float, L: float) -> np.ndarray:
    """Matriz de massa consistente da viga de Euler-Bernoulli.

    Massa linear variando de ``m1`` a ``m2`` (t/m); toma-se a média, que é
    exata na carga uniforme e no erro de segunda ordem na trapezoidal.
    """
    m = 0.5 * (m1 + m2)
    c = m * L / 420.0
    return c * np.array([
        [156.0, 22.0 * L, 54.0, -13.0 * L],
        [22.0 * L, 4.0 * L * L, 13.0 * L, -3.0 * L * L],
        [54.0, 13.0 * L, 156.0, -22.0 * L],
        [-13.0 * L, -3.0 * L * L, -22.0 * L, 4.0 * L * L],
    ])


def frequencias_naturais(viga: Viga, est: Estrutura, psi1: float,
                         n_modos: int = 3) -> tuple[list[float], float]:
    """Frequências naturais de flexão, Hz, e a massa total, t.

    Análise modal do mesmo modelo de barras da análise (malha, rigidez, molas
    e apoios de ``est``), com as massas "correspondentes aos pesos definidos
    nas combinações de serviço frequente" (23.3, 11.8.3.1): ``g + ψ1·q`` em
    todos os tramos, distribuídas em matriz consistente e as concentradas
    como massa nodal. Problema de autovalores generalizado ``K φ = ω² M φ``
    nos graus livres.
    """
    malha = est.malha
    n = 2 * malha.n_nos
    M = np.zeros((n, n))
    Ls = malha.comprimentos
    total = 0.0
    for e in range(malha.n_elem):
        xa, xb = malha.x_nos[e], malha.x_nos[e + 1]
        t = int(malha.tramo_elem[e])
        wg = _carga_distribuida_no_elemento(viga, xa, xb, "g", t)
        wq = _carga_distribuida_no_elemento(viga, xa, xb, "q", t)
        m1 = (wg[0] + psi1 * wq[0]) / GRAVIDADE
        m2 = (wg[1] + psi1 * wq[1]) / GRAVIDADE
        if m1 <= 0.0 and m2 <= 0.0:
            continue
        g = slice(2 * e, 2 * e + 4)
        M[g, g] += _massa_elemento(max(m1, 0.0), max(m2, 0.0), Ls[e])
        total += 0.5 * (m1 + m2) * Ls[e]
    for p in viga.concentradas:
        fator = 1.0 if p.acao == "g" else psi1
        if p.P * fator <= 0.0:
            continue
        no = int(np.argmin(np.abs(malha.x_nos - p.x)))
        M[2 * no, 2 * no] += p.P * fator / GRAVIDADE
        total += p.P * fator / GRAVIDADE
    livres = np.setdiff1d(np.arange(n),
                          np.array(graus_restritos(viga, malha), dtype=int))
    K = est.K.toarray()[np.ix_(livres, livres)]
    Mf = M[np.ix_(livres, livres)]
    # graus sem massa (rotações com massa nula num elemento descarregado)
    # tornam M singular; um resíduo mínimo não muda o modo de flexão
    Mf = Mf + np.eye(len(livres)) * max(1e-12, 1e-9 * float(np.max(
        np.abs(np.diag(Mf))) or 1.0))
    from scipy.linalg import eigh
    autovalores = eigh(K, Mf, eigvals_only=True,
                       subset_by_index=[0, min(n_modos, len(livres)) - 1])
    freqs = [math.sqrt(max(w2, 0.0)) / (2.0 * math.pi) for w2 in autovalores]
    return freqs, total


def verificar_vibracao(viga: Viga, est: Estrutura, rigidez: str,
                       avisos: list[str]) -> ResultadoVibracao | None:
    """``fn > 1,2 fcrit`` e ``fn >= 3 Hz`` (23.3); None se desligada."""
    cfg = viga.config
    if cfg.fcrit_vibracao <= 0.0:
        return None
    freqs, total = frequencias_naturais(viga, est, cfg.psi1)
    r = ResultadoVibracao(fn=freqs[0], fcrit=cfg.fcrit_vibracao,
                          massa_total=total, rigidez=rigidez, modos=freqs)
    if not r.ok:
        avisos.append(av.erro(
            f"Vibrações excessivas (23.3): a frequência natural da viga é "
            f"fn = {r.fn:.2f} Hz e o item exige fn > 1,2·fcrit = "
            f"{1.2 * r.fcrit:.2f} Hz e fn >= {FREQUENCIA_MINIMA_PISO:g} Hz. "
            f"Aumente a rigidez (altura da seção) ou faça uma análise "
            f"dinâmica mais acurada."))
    return r


# ---------------------------------------------------------------------------
# 17.3.3.2 -- armadura de pele no controle da fissuração
# ---------------------------------------------------------------------------

#: Nota do 17.3.3.2: espaçamento da pele na zona tracionada, em Ø
ESPACAMENTO_PELE_FISSURACAO = 15.0


@dataclass
class PeleFissuracao:
    """Abertura de fissuras na região de envolvimento de uma barra de pele."""

    regiao: str
    posicao: int              # N da pele
    phi: float                # mm
    y: float                  # cm, da face comprimida ao eixo da barra
    sigma_s: float            # kN/cm², Estádio II no eixo da barra
    Acri: float               # cm²
    rho_ri: float
    wk_1: float               # mm
    wk_2: float               # mm
    wk: float                 # mm
    wk_limite: float          # mm
    s: float                  # cm, espaçamento vertical da pele
    s_max: float              # cm, 15 Ø

    @property
    def ok(self) -> bool:
        return self.wk <= self.wk_limite + 1e-9

    @property
    def espacamento_ok(self) -> bool:
        return self.s <= self.s_max + 1e-6


def pele_na_fissuracao(viga: Viga, regioes, posicoes, phi_estribo: float,
                       avisos: list[str]) -> list[PeleFissuracao]:
    """Abertura de fissuras na pele tracionada de cada região (17.3.3.2).

    A Nota do item pede que "toda a armadura de pele φi da viga, na sua zona
    tracionada, limite a abertura de fissuras na região Acri correspondente"
    (Figura 17.4), com espaçamento <= 15 φ. Para cada barra de pele abaixo da
    linha neutra do Estádio II da região (acima dela, na região de momento
    negativo):

    * ``σsi = αe·M·(y − x)/I`` no eixo da barra, com ``x`` e ``I`` da mesma
      verificação de fissuras da região;
    * ``Acri``: na largura, da face ao eixo + 7,5 φ (limitado a bw/2); na
      altura, 7,5 φ para cada lado, limitado à metade da distância às barras
      vizinhas e à linha neutra;
    * ``wk`` pelas duas expressões do item, o menor.

    O wk que passa do limite é erro; o espaçamento acima de 15 φ é alerta,
    porque a Nota diz "é conveniente".
    """
    conc, aco = viga.concreto, viga.aco
    alpha_e = aco.Es / conc.Ecs
    cob = viga.ambiente.cobrimento_nominal
    Esi = aco.Es / 10.0
    fctm = conc.fctm / 10.0
    saida: list[PeleFissuracao] = []
    alertas: set[str] = set()
    for r in regioes:
        f = r.fissuracao
        if f is None or r.construtiva or not f.fissurada or f.I_II <= 0.0:
            continue
        tramo = viga.tramo_em(r.x)
        peles = [p for p in posicoes if p.tipo == "pele" and p.n_faces == 2
                 and p.tramo == tramo and p.As_torcao <= 1e-6
                 and p.x_ini - 1e-9 <= r.x <= p.x_fim + 1e-9]
        for p in peles:
            n_face = max(p.n // 2, 1)
            y0, y1 = p.faixa_altura
            alturas = ([0.5 * (y0 + y1)] if n_face == 1 else
                       [y0 + (y1 - y0) * k / (n_face - 1)
                        for k in range(n_face)])
            passo = (y1 - y0) / (n_face - 1) if n_face > 1 else r.secao.h
            phi_cm = p.phi / 10.0
            meia = els.MEIA_ENVOLTORIA * phi_cm
            h = r.secao.h
            for y_fundo in alturas:
                # profundidade a partir da face comprimida
                y = h - y_fundo if r.face == "inferior" else y_fundo
                if y <= f.x_II + 1e-9:
                    continue                      # zona comprimida
                sigma = alpha_e * abs(f.M_servico) * 100.0 * (y - f.x_II) / f.I_II
                eixo_h = cob + phi_estribo / 10.0 + phi_cm / 2.0
                largura = min(eixo_h + meia, r.secao.bw / 2.0)
                acima = min(meia, passo / 2.0, y - f.x_II)
                abaixo = min(meia, passo / 2.0)
                Acri = largura * (acima + abaixo)
                rho = area_barra(p.phi) / Acri if Acri > 0 else 0.0
                k = p.phi / (12.5 * aco.eta_1)
                wk1 = k * sigma / Esi * 3.0 * sigma / fctm
                wk2 = (k * sigma / Esi * (4.0 / rho + 45.0) if rho > 0
                       else float("inf"))
                item = PeleFissuracao(
                    regiao=r.nome, posicao=p.numero, phi=p.phi, y=y,
                    sigma_s=sigma, Acri=Acri, rho_ri=rho, wk_1=wk1, wk_2=wk2,
                    wk=min(wk1, wk2), wk_limite=f.wk_limite, s=round(passo, 1),
                    s_max=ESPACAMENTO_PELE_FISSURACAO * phi_cm)
                saida.append(item)
        piores = [s for s in saida if s.regiao == r.nome]
        if piores:
            pior = max(piores, key=lambda s: s.wk)
            if not pior.ok:
                f.ok = False
                f.avisos.append(av.erro(
                    f"{r.nome}: a armadura de pele N{pior.posicao} na zona "
                    f"tracionada abre wk = {pior.wk:.3f} mm, acima do limite "
                    f"de {pior.wk_limite:.2f} mm (17.3.3.2, Figura 17.4). "
                    f"Reduza a bitola ou o espaçamento da pele."))
                r.avisos.append(f.avisos[-1])
            if not pior.espacamento_ok:
                alertas.add(
                    f"Armadura de pele N{pior.posicao}: espaçamento de "
                    f"{pior.s:g} cm na zona tracionada, acima dos 15 Ø = "
                    f"{pior.s_max:g} cm que a Nota do item 17.3.3.2 considera "
                    f"conveniente para a pele limitar as fissuras da sua "
                    f"região de envolvimento.")
    for texto in sorted(alertas):
        avisos.append(av.construtivo(texto))
    return saida
