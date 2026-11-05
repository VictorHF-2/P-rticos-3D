# -*- coding: utf-8 -*-
"""
puncao.py
Punção da laje maciça sob carga concentrada (R11) -- NBR 6118:2026, 19.5.

A carga concentrada lançada na laje (``CargaConcentrada``) é a "área
carregada" do item 19.5: a base de um equipamento, o pé de um pilarete. Sem
armadura de punção, a laje é verificada em dois contornos:

* **C**, o perímetro da área carregada (u0 = 2(c1 + c2)), na compressão
  diagonal do concreto (19.5.3.1)::

      τSd = FSd / (u0 d) <= τRd2 = 0,27 αv fcd,     αv = 1 - fck/250;

* **C'**, a 2d da área carregada (u1 = 2(c1 + c2) + 4πd), na tração
  diagonal (19.5.3.2)::

      τSd = FSd / (u1 d) <= τRd1 = 0,13 ke (100 ρ fck)^(1/3),
      ke = 1 + √(20/d) <= 2 (d em cm),  ρ = √(ρx ρy) <= 0,02.

A carga é centrada (sem momento transmitido), ``d = (dx + dy)/2`` e ρ vem
da armadura **inferior** adotada nas duas direções (a face tracionada sob a
carga), que é uniforme na laje -- a mesma taxa em "c + 3d para cada lado".
A parcela da carga distribuída dentro do contorno não é descontada de FSd
(a favor da segurança).

Fora do alcance, com aviso: a carga a menos de 2d de um apoio (o contorno
C' cruza a viga, e a carga desce direto para ela -- é caso de cortante, não
de punção) e a menos de 2d de um bordo livre (contorno reduzido, que o
programa não monta). Quando C' não passa, o programa não dimensiona
armadura de punção (19.5.3.3): avisa para aumentar h ou a área carregada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ResultadoPuncao:
    laje: str
    indice: int
    descricao: str
    P_d: float = 0.0                # kN
    c1: float = 0.0                 # cm, dimensões da área carregada
    c2: float = 0.0
    d: float = 0.0                  # cm
    u0: float = 0.0                 # cm
    u1: float = 0.0                 # cm
    tau_sd0: float = 0.0            # MPa, no contorno C
    tau_rd2: float = 0.0
    tau_sd1: float = 0.0            # MPa, no contorno C'
    tau_rd1: float = 0.0
    rho: float = 0.0
    ke: float = 0.0
    verificada: bool = True
    atende: bool = True
    observacao: str = ""

    @property
    def rotulo(self) -> str:
        return f"{self.laje}, {self.descricao}"


def tau_rd2(fck: float, fcd: float) -> float:
    """τRd2 = 0,27 αv fcd, MPa (19.5.3.1)."""
    return 0.27 * (1.0 - fck / 250.0) * fcd


def tau_rd1(fck: float, d: float, rho: float) -> tuple[float, float]:
    """``(τRd1, ke)`` do 19.5.3.2, sem protensão -- d em cm, MPa."""
    ke = min(1.0 + math.sqrt(20.0 / d), 2.0) if d > 0 else 2.0
    rho = min(max(rho, 0.0), 0.02)
    return 0.13 * ke * (100.0 * rho * fck) ** (1.0 / 3.0), ke


def verificar(laje, indice: int, descricao: str, P_d: float, u: float,
              v: float, du: float, dv: float, d_u: float, d_v: float,
              As_u: float, As_v: float, concreto) -> ResultadoPuncao:
    """Punção da carga ``indice`` da laje.

    ``u``/``v`` (m) é o centro da carga nas coordenadas da laje e ``du``/
    ``dv`` (cm) as dimensões dela; ``d_u``/``d_v`` (cm) as alturas úteis e
    ``As_u``/``As_v`` (cm²/m) as armaduras inferiores adotadas que correm
    nas direções ``u`` (ao longo de b) e ``v`` (ao longo de a).
    """
    r = ResultadoPuncao(laje=laje.nome, indice=indice, descricao=descricao,
                        P_d=P_d, c1=du, c2=dv)
    d = (d_u + d_v) / 2.0
    r.d = d
    if d <= 0.0:
        r.verificada, r.atende = False, False
        r.observacao = "altura útil nula"
        return r
    # distância da face da área carregada a cada bordo, cm
    folga = {1: u * 100.0 - du / 2.0, 3: (laje.b - u) * 100.0 - du / 2.0,
             2: v * 100.0 - dv / 2.0, 4: (laje.a - v) * 100.0 - dv / 2.0}
    perto_apoio = [k for k, f in folga.items()
                   if f < 2.0 * d and laje.bordos[k - 1].vinculo != "livre"]
    perto_livre = [k for k, f in folga.items()
                   if f < 2.0 * d and laje.bordos[k - 1].vinculo == "livre"]

    r.u0 = 2.0 * (du + dv)
    r.u1 = 2.0 * (du + dv) + 4.0 * math.pi * d
    # kN / cm² -> MPa (x 10)
    r.tau_sd0 = P_d / (r.u0 * d) * 10.0
    r.tau_rd2 = tau_rd2(concreto.fck, concreto.fcd)
    r.tau_sd1 = P_d / (r.u1 * d) * 10.0
    rho_u = As_u / (100.0 * d_u) if d_u > 0 else 0.0
    rho_v = As_v / (100.0 * d_v) if d_v > 0 else 0.0
    r.rho = min(math.sqrt(max(rho_u, 0.0) * max(rho_v, 0.0)), 0.02)
    r.tau_rd1, r.ke = tau_rd1(concreto.fck, d, r.rho)

    if perto_apoio:
        r.verificada = False
        r.atende = r.tau_sd0 <= r.tau_rd2 + 1e-9
        r.observacao = (
            f"a menos de 2d do apoio (bordo "
            f"{', '.join(map(str, perto_apoio))}): o contorno C' cruza a "
            f"viga e a carga desce direto para ela -- confira como "
            f"cortante (19.4); só o contorno C foi verificado")
        return r
    if perto_livre:
        r.verificada = False
        r.atende = r.tau_sd0 <= r.tau_rd2 + 1e-9
        r.observacao = (
            f"a menos de 2d do bordo livre {', '.join(map(str, perto_livre))}"
            f": o contorno C' é reduzido (19.5.2.3) e não foi montado -- só "
            f"o contorno C foi verificado")
        return r
    r.atende = (r.tau_sd0 <= r.tau_rd2 + 1e-9
                and r.tau_sd1 <= r.tau_rd1 + 1e-9)
    if not r.atende:
        r.observacao = (
            "não passa sem armadura de punção: aumente h ou a área "
            "carregada (o programa não dimensiona armadura de punção, "
            "19.5.3.3)" if r.tau_sd0 <= r.tau_rd2 + 1e-9 else
            "esmagamento da diagonal comprimida no contorno C: aumente h "
            "ou a área carregada")
    return r


def verificar_laje(rl, pav) -> list[ResultadoPuncao]:
    """Punção de todas as cargas concentradas da laje do resultado ``rl``
    (``dimensionar.ResultadoLaje``), com as armaduras já escolhidas."""
    laje, esf = rl.laje, rl.esforcos
    saida: list[ResultadoPuncao] = []
    if not laje.cargas_concentradas:
        return saida
    cfg = pav.config
    em_cruz = esf.classificacao.em_cruz
    direcao = esf.classificacao.direcao or "a"

    def escolha_e_d(chaves):
        for chave in chaves:
            esc = rl.escolhas.get(chave)
            if esc is None or esc.erro:
                continue
            f = rl.flexao_de(chave)
            return esc, (f.d if f is not None else 0.0)
        return None, 0.0

    for k, carga in enumerate(laje.cargas_concentradas, start=1):
        nome = carga.descricao or f"carga concentrada {k}"
        u, v, du, dv = laje.carga_local(carga)
        P_d = esf.gamma_n * (cfg.gamma_g * carga.g + cfg.gamma_q * carga.q)
        if em_cruz:
            esc_a, d_a = escolha_e_d(["vão a"])
            esc_b, d_b = escolha_e_d(["vão b"])
        else:
            outra = "b" if direcao == "a" else "a"
            esc_p, d_p = escolha_e_d([f"vão {direcao} — {nome}",
                                      f"vão {direcao} — sem parede",
                                      f"vão {direcao}"])
            esc_s, d_s = escolha_e_d([f"vão {outra}", "distribuição"])
            if d_s <= 0.0 and esc_p is not None:
                # a distribuição fica por cima da principal
                d_s = d_p - esc_p.phi / 10.0
            esc_a, d_a, esc_b, d_b = ((esc_p, d_p, esc_s, d_s)
                                      if direcao == "a" else
                                      (esc_s, d_s, esc_p, d_p))
        # a armadura do vão a corre ao longo de a (direção v) e a do vão b
        # ao longo de b (direção u)
        As_v = esc_a.As_efetiva if esc_a is not None else 0.0
        As_u = esc_b.As_efetiva if esc_b is not None else 0.0
        saida.append(verificar(laje, k, nome, P_d, u, v, du, dv, d_b, d_a,
                               As_u, As_v, pav.concreto))
    return saida
