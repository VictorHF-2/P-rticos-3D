# -*- coding: utf-8 -*-
"""
fadiga.py
Estado-limite último de fadiga do pilar de ponte (NBR 6118:2026, 23.5, com
os fatores de redução da NBR 8681:2025, Tabela 7).

* **Combinação** (6118, 23.5.2): frequente, ``Fd = Fg,k + psi1,fad Fq,k``,
  com a carga móvel e seus efeitos dinâmicos nas duas posições extremas
  (máximo e mínimo de cada esforço). ``psi1,fad`` pela Tabela 7 da 8681:
  ponte rodoviária, meso e infraestrutura **ligadas à superestrutura só por
  aparelhos de apoio**: 0 (nota f) -- a verificação fica dispensada; ponte
  ferroviária: 1,0; passarela: 0. Ponte em pórtico ou estaiada (o pilar
  monolítico com o tabuleiro) não está na tabela, e o projetista informa o
  fator.
* **Modelo** (23.5.3): regime elástico, flexão composta no estádio II,
  ``alpha_e = 10``, ``gamma_f = 1,0``, ``gamma_c = 1,4``, ``gamma_s = 1,0``.
* **Armadura** (23.5.5): ``gamma_f Delta sigma_s <= Delta f_sd,fad`` da
  Tabela 23.2 para 2 x 10^6 ciclos -- barras retas (o caso das barras
  longitudinais do pilar), ou 110 MPa em ambiente marinho / CAA IV.
* **Concreto em compressão** (23.5.4.1): ``eta_c gamma_f sigma_c,max <=
  0,45 fcd``. O ``eta_c`` (gradiente de tensões, Figura 23.1) vale no máximo
  1; o programa adota 1, do lado seguro.

Verificadas as cotas de topo e base (momentos de 1ª ordem lineares ao longo
do lance). Fadiga dos estribos e do concreto em tração não são verificadas:
o pilar comprimido não tem a cortante cíclica de uma viga, e o concreto
armado não conta com a resistência à tração.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import avisos as av
from .fibras import amostrar_centros
from .formato import num
from .servico import RESOLUCAO, estadio_2, tem_esforcos

#: Tabela 7 da NBR 8681:2025 -- (psi1,fad, descrição).
OBRAS_FADIGA = {
    "": (None, "não verificar"),
    "rodoviaria": (0.0, "ponte rodoviária, pilar ligado por aparelhos de apoio"),
    "rodoviaria_monolitica": (None, "ponte rodoviária em pórtico ou estaiada"),
    "ferroviaria": (1.0, "ponte ferroviária"),
    "passarela": (0.0, "passarela de pedestres"),
}

#: Tabela 23.2, CA-50, barras retas ou dobradas com D >= 25 phi, 2e6 ciclos.
DELTA_FSD_RETAS = {10.0: 190.0, 12.5: 190.0, 16.0: 190.0, 20.0: 185.0,
                   22.0: 180.0, 25.0: 175.0, 32.0: 165.0, 40.0: 150.0}
#: Tabela 23.2, ambiente marinho / Classe IV (curva T4).
DELTA_FSD_MARINHO = 110.0
#: 23.5.3: relação Es/Ec do estádio II na fadiga.
ALFA_E_FADIGA = 10.0


def delta_fsd(phi_mm: float, caa: str) -> float:
    """Delta f_sd,fad da barra, MPa (Tabela 23.2)."""
    if caa == "IV":
        return DELTA_FSD_MARINHO
    for phi in sorted(DELTA_FSD_RETAS):
        if phi_mm <= phi + 1e-9:
            return DELTA_FSD_RETAS[phi]
    return DELTA_FSD_RETAS[40.0]


@dataclass
class CotaFadiga:
    nome: str
    estados: list = field(default_factory=list)   # (nome, N, Mx, My)
    delta_sigma_max: float = 0.0        # MPa
    barra_critica: tuple | None = None  # (x, y, phi, delta, limite)
    sigma_c_max: float = 0.0            # MPa
    convergiu: bool = True


@dataclass
class VerificacaoFadiga:
    aplicavel: bool = False
    motivo: str = ""
    obra: str = ""
    psi1: float = 0.0
    fcd_fad: float = 0.0                # MPa
    cotas: list[CotaFadiga] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def ok_aco(self) -> bool:
        return all(c.barra_critica is None
                   or c.barra_critica[3] <= c.barra_critica[4] + 1e-9
                   for c in self.cotas)

    @property
    def ok_concreto(self) -> bool:
        return all(c.sigma_c_max <= self.fcd_fad + 1e-9 for c in self.cotas)

    @property
    def ok(self) -> bool:
        return (not self.aplicavel
                or (all(c.convergiu for c in self.cotas)
                    and self.ok_aco and self.ok_concreto))


def _combinar(g, q, psi: float, campo: str) -> float:
    return getattr(g, campo) + psi * getattr(q, campo)


def verificar(pilar, arr) -> VerificacaoFadiga:
    from dataclasses import replace
    cfg = pilar.config
    v = VerificacaoFadiga(obra=cfg.fadiga_obra)
    if not cfg.fadiga_obra:
        v.motivo = "fadiga não pedida nos critérios"
        return v
    psi_tab, descricao = OBRAS_FADIGA.get(cfg.fadiga_obra, (None, "?"))
    psi = cfg.psi1_fadiga if cfg.psi1_fadiga > 0 else psi_tab
    if psi is None:
        v.motivo = (f"{descricao}: a Tabela 7 da NBR 8681 não dá ψ1,fad para "
                    f"a meso e infraestrutura monolítica -- informe o fator "
                    f"nos critérios")
        v.avisos.append(av.erro(f"Fadiga: {v.motivo}."))
        return v
    v.psi1 = psi
    if psi <= 0.0:
        v.motivo = (f"{descricao}: ψ1,fad = 0 (NBR 8681:2025, Tabela 7) -- a "
                    f"carga móvel não gera ciclo de tensão a verificar")
        v.avisos.append(av.construtivo(
            f"Fadiga dispensada: {v.motivo}."))
        return v
    g, qmax, qmin = (pilar.esforcos_fadiga_g, pilar.esforcos_fadiga_qmax,
                     pilar.esforcos_fadiga_qmin)
    if not (tem_esforcos(qmax) or tem_esforcos(qmin)):
        v.motivo = "esforços da carga móvel para a fadiga não informados"
        v.avisos.append(av.erro(
            f"Fadiga ({descricao}, ψ1,fad = {num(psi, 1)}): informe os "
            f"esforços característicos permanentes e da carga móvel (posições "
            f"de máximo e de mínimo) na aba Esforços."))
        return v
    if arr is None or not arr.barras:
        v.motivo = "sem arranjo de barras"
        return v
    v.aplicavel = True
    c = pilar.concreto
    v.fcd_fad = 0.45 * c.fck / 1.4                   # gamma_c = 1,4 (23.5.3)
    Es = pilar.aco.Es_kNcm2
    Ec = Es / ALFA_E_FADIGA
    contornos = pilar.secao.contornos()
    xs = [q[0] for cc in contornos for q in cc]
    ys = [q[1] for cc in contornos for q in cc]
    dx = (max(xs) - min(xs)) / RESOLUCAO
    dy = (max(ys) - min(ys)) / RESOLUCAO
    celulas = [(x, y, dx * dy)
               for x, y in amostrar_centros(contornos, RESOLUCAO)]
    barras_m = [(b.x, b.y, b.area) for b in arr.barras]
    caa = pilar.ambiente.caa

    def base(e):
        return replace(pilar, esforcos=e)

    for cota in ("Topo", "Base"):
        cf = CotaFadiga(nome=cota)
        tensoes = []
        for nome_q, q in (("máximo", qmax), ("mínimo", qmin)):
            N = _combinar(g, q, psi, "Nd")
            if cota == "Topo":
                Mx = _combinar(g, q, psi, "Mx_topo")
                My = _combinar(g, q, psi, "My_topo")
            else:
                # a convenção de sinal da base, aplicada ao estado combinado
                comb = replace(g, Nd=N,
                               Mx_base=_combinar(g, q, psi, "Mx_base"),
                               My_base=_combinar(g, q, psi, "My_base"))
                pb = base(comb)
                Mx, My = pb.momento_base("x"), pb.momento_base("y")
            cf.estados.append((nome_q, N, Mx, My))
            e0, kx, ky, ok = estadio_2(celulas, barras_m, Ec, Es, N, Mx, My)
            cf.convergiu = cf.convergiu and ok
            tensoes.append([Es * (e0 + kx * b.x + ky * b.y) * 10.0
                            for b in arr.barras])       # MPa, + compressão
            cf.sigma_c_max = max(cf.sigma_c_max, max(
                (Ec * (e0 + kx * x + ky * y) * 10.0 for x, y, _ in celulas),
                default=0.0))
        pior = None
        for b, s1, s2 in zip(arr.barras, tensoes[0], tensoes[1]):
            delta = abs(s1 - s2)
            limite = delta_fsd(b.phi, caa)
            if pior is None or delta / limite > pior[3] / pior[4]:
                pior = (b.x, b.y, b.phi, delta, limite)
        cf.barra_critica = pior
        cf.delta_sigma_max = pior[3] if pior else 0.0
        v.cotas.append(cf)

    if not all(cf.convergiu for cf in v.cotas):
        v.avisos.append(av.erro(
            "Fadiga: o estádio II não convergiu numa das cotas -- confira os "
            "esforços da combinação de fadiga."))
    for cf in v.cotas:
        x, y, phi, delta, limite = cf.barra_critica
        if delta > limite + 1e-9:
            v.avisos.append(av.erro(
                f"Fadiga da armadura (23.5.5), cota {cf.nome}: Δσs = "
                f"{num(delta, 0)} MPa na barra ø{num(phi)} em ({num(x, 1)}; "
                f"{num(y, 1)}) cm, acima de Δfsd,fad = {num(limite, 0)} MPa "
                f"(Tabela 23.2, 2 × 10⁶ ciclos)."))
        if cf.sigma_c_max > v.fcd_fad + 1e-9:
            v.avisos.append(av.erro(
                f"Fadiga do concreto (23.5.4.1), cota {cf.nome}: σc,máx = "
                f"{num(cf.sigma_c_max, 1)} MPa acima de fcd,fad = 0,45 fcd = "
                f"{num(v.fcd_fad, 1)} MPa (ηc = 1, do lado seguro)."))
    if v.ok:
        gov = max(v.cotas, key=lambda c: c.barra_critica[3] / c.barra_critica[4])
        v.avisos.append(av.construtivo(
            f"Fadiga ({descricao}, ψ1,fad = {num(psi, 1)}): Δσs máximo = "
            f"{num(gov.delta_sigma_max, 0)} MPa na cota {gov.nome}, contra "
            f"{num(gov.barra_critica[4], 0)} MPa (Tabela 23.2); σc,máx = "
            f"{num(max(c.sigma_c_max for c in v.cotas), 1)} MPa contra "
            f"0,45 fcd = {num(v.fcd_fad, 1)} MPa. Estádio II com αe = 10 "
            f"(23.5.3)."))
    return v
