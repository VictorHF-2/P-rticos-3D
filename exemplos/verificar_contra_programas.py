# -*- coding: utf-8 -*-
"""
verificar_contra_programas.py
O edifício de ``edificio_3pav.py`` dimensionado duas vezes: pelo Pórticos e
pelos programas de Vigas, Pilares e Lajes rodados **isoladamente** — os
originais, importados das pastas deles, e não as cópias do Pórticos.

A entrada isolada é montada daqui, a partir da geometria e das cargas do
edifício, **sem as funções da ponte** do Pórticos: vãos entre eixos de pilar,
largura do apoio pela seção do pilar, mola 4EI/ℓ dos lances, mesa colaborante
pela Figura 14.2, carga de laje pelas áreas a 45°, retângulos de vão livre
das lajes, esforços de pilar tirados das forças de extremidade do pórtico. É
o que um usuário faria com os três programas à mão; se a ponte traduzir
alguma coisa errado, a diferença aparece.

Saídas em ``exemplos/verificacao-3pav/``: ``relatorio.md``, os arquivos de
entrada de cada programa (abrem neles: ``vigas/*.json``, ``pilares/*.json``,
``lajes/*.json``) e as imagens da armadura 3D.

Uso: ``py exemplos/verificar_contra_programas.py`` (leva alguns minutos:
o programa de Pilares é a parte lenta).
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AQUI = Path(__file__).resolve().parent
PROGRAMA = AQUI.parent
#: a pasta ``Programas``, procurada pelo nome: a profundidade mudou quando o
#: Pórticos saiu de ``Porticos R03/Programa`` para ``Programa``, e um número
#: fixo de níveis fez o roteiro procurar os repositórios no lugar errado
PROGRAMAS = next(p for p in PROGRAMA.parents if p.name == "Programas")
sys.path.insert(0, str(PROGRAMA))
sys.path.insert(0, str(AQUI))


def _carregar_originais() -> dict[str, str]:
    """Põe no ``sys.path`` cada programa de origem **no commit de que o
    Pórticos copiou o motor** (``elementos.PROCEDENCIA``): o repositório é
    exportado por ``git archive`` para uma pasta temporária. Comparar com a
    pasta de trabalho do programa compararia versões diferentes, e a
    diferença não diria nada sobre a ponte.

    Sem commit registrado (a cópia veio de uma pasta de revisão que já não
    existe), usa-se a própria cópia, registrada como tal no relatório.
    Devolve, por pacote, de onde ele veio.
    """
    import subprocess
    import tempfile
    import types

    from portico3d.elementos import PROCEDENCIA

    origem = {}
    destino = Path(tempfile.mkdtemp(prefix="originais_"))
    for pacote in ("vigas", "pilares", "lajes"):
        dados = PROCEDENCIA[pacote]
        repo = PROGRAMAS / dados.get("repositorio", "")
        commit = dados.get("commit", "")
        if commit and not (repo / ".git").exists():
            # com commit registrado, cair na cópia faria o Pórticos se
            # comparar consigo mesmo sem ninguém perceber
            raise SystemExit(f"o repositório de {pacote} não foi achado em "
                             f"{repo}; sem ele não há o que comparar")
        if commit:
            arquivo = destino / f"{pacote}.tar"
            subprocess.run(["git", "-C", str(repo), "archive", "-o",
                            str(arquivo), commit, dados["pacote"]],
                           check=True)
            subprocess.run(["tar", "-xf", str(arquivo), "-C", str(destino)],
                           check=True)
            origem[pacote] = (f"{dados['repositorio']} no commit "
                              f"{commit[:7]} ({dados['revisao']})")
            continue
        # a cópia, sob o nome do pacote original
        import importlib
        copia = importlib.import_module(f"portico3d.elementos.{pacote}")
        sys.modules[pacote] = copia
        for sub in ("core", "saidas"):
            sys.modules[f"{pacote}.{sub}"] = importlib.import_module(
                f"portico3d.elementos.{pacote}.{sub}")
        origem[pacote] = (f"a cópia do Pórticos ({dados['revisao']}): a "
                          "pasta de origem não existe mais e nenhum commit "
                          "do repositório é idêntico a ela")
    sys.path.insert(0, str(destino))
    return origem

import edificio_3pav as E                                    # noqa: E402

SAIDA = AQUI / "verificacao-3pav"
GAMA_C = 25.0
CM = 100.0


# ---------------------------------------------------------------------------
# Geometria do edifício, lida do lançamento
# ---------------------------------------------------------------------------

def dimensoes_do_pilar(p) -> tuple[float, float]:
    """(dimensão em X, dimensão em Y) do pilar lançado, m."""
    if abs(p.angulo % 180.0) < 1e-6:
        return p.b, p.h
    return p.h, p.b


def pilar_em(planta, x, y):
    for p in planta.pilares:
        if abs(p.x - x) < 1e-6 and abs(p.y - y) < 1e-6:
            return p
    return None


class Cadeia:
    """Uma viga lançada, vista como viga contínua: eixo, apoios e balanços."""

    def __init__(self, viga, planta):
        self.viga = viga
        (xa, ya), (xb, yb) = viga.pontos[0], viga.pontos[-1]
        self.em_x = abs(ya - yb) < 1e-9
        self.linha = ya if self.em_x else xa
        self.ini, self.fim = ((min(xa, xb), max(xa, xb)) if self.em_x
                              else (min(ya, yb), max(ya, yb)))
        self.comprimento = self.fim - self.ini
        self.apoios = []          # (s, tipo, pilar ou viga de apoio)
        for p in planta.pilares:
            s, linha = (p.x, p.y) if self.em_x else (p.y, p.x)
            if abs(linha - self.linha) < 1e-6 and \
                    self.ini - 1e-6 <= s <= self.fim + 1e-6:
                self.apoios.append((s - self.ini, "pilar", p))
        self.apoios.sort(key=lambda a: a[0])

    def ponto(self, s: float):
        return ((self.ini + s, self.linha) if self.em_x
                else (self.linha, self.ini + s))

    def s_de(self, x, y) -> float:
        return (x if self.em_x else y) - self.ini


def montar_cadeias(planta) -> dict[str, Cadeia]:
    cadeias = {v.nome: Cadeia(v, planta) for v in planta.vigas}
    # a V8 não tem pilar: repousa nas pontas dos balanços de V1 e V2
    for c in cadeias.values():
        if c.apoios:
            continue
        for outra in cadeias.values():
            if outra is c or outra.em_x == c.em_x or not outra.apoios:
                continue
            for s_ponta in (0.0, outra.comprimento):
                x, y = outra.ponto(s_ponta)
                na_linha = abs((y if c.em_x else x) - c.linha) < 1e-6
                s = c.s_de(x, y)
                if na_linha and -1e-6 <= s <= c.comprimento + 1e-6:
                    c.apoios.append((s, "viga", outra))
        c.apoios.sort(key=lambda a: a[0])
    return cadeias


# ---------------------------------------------------------------------------
# Lajes do edifício: retângulos nos eixos, carga
# ---------------------------------------------------------------------------

def retangulos_das_lajes(planta) -> dict[str, tuple]:
    """nome -> (x0, y0, x1, y1, balanço?) nos eixos, pelos eixos do lançamento
    (cada laje lançada cai entre eixos conhecidos)."""
    xs = list(E.XS) + [E.X_BALANCO]
    ys = list(E.YS)
    saida = {}
    for l in planta.lajes:
        if l.balanco > 0.0:
            x0 = max(x for x in xs if x < l.x)
            x1 = min(x for x in xs if x > l.x)
            y0 = max(y for y in ys if y < l.y)
            saida[l.nome] = (x0, y0, x1, y0 + l.balanco, True)
            continue
        x0 = max(x for x in xs if x < l.x)
        x1 = min(x for x in xs if x > l.x)
        y0 = max(y for y in ys if y < l.y)
        y1 = min(y for y in ys if y > l.y)
        saida[l.nome] = (x0, y0, x1, y1, False)
    return saida


def g_da_laje(laje) -> float:
    return laje.espessura * GAMA_C + laje.permanente


# ---------------------------------------------------------------------------
# Vigas isoladas
# ---------------------------------------------------------------------------

def largura_da_viga_na_linha(planta, em_x: bool, linha: float, s: float):
    """Largura, m, da viga que passa na linha (em X ou em Y) no ponto s."""
    for v in planta.vigas:
        (xa, ya), (xb, yb) = v.pontos[0], v.pontos[-1]
        vx = abs(ya - yb) < 1e-9
        if vx != em_x:
            continue
        lin = ya if vx else xa
        a, b = (sorted((xa, xb)) if vx else sorted((ya, yb)))
        if abs(lin - linha) < 1e-6 and a - 1e-6 <= s <= b + 1e-6:
            return v.b
    return None


def secao_da_viga_isolada(V, c: Cadeia, planta, retangulos, lajes, k_tramo,
                          xa, xb, n_momentos):
    """Seção do tramo pela Figura 14.2: T quando há laje ao longo dele."""
    bw = c.viga.b
    L = xb - xa
    a = 2.0 * L if n_momentos is None else (1.0, 0.75, 0.60)[n_momentos] * L
    b1_total, hf = 0.0, math.inf
    lados = []
    for lado in (-1, 1):
        achadas = []
        for nome, (x0, y0, x1, y1, bal) in retangulos.items():
            # a laje encosta na linha da viga, do lado dado, cobrindo o tramo
            if c.em_x:
                encosta = (abs(y0 - c.linha) < 1e-6 and lado > 0) or \
                    (abs(y1 - c.linha) < 1e-6 and lado < 0)
                cobre = x0 - 1e-6 <= c.ini + xa and c.ini + xb <= x1 + 1e-6
                largura_laje = y1 - y0
            else:
                encosta = (abs(x0 - c.linha) < 1e-6 and lado > 0) or \
                    (abs(x1 - c.linha) < 1e-6 and lado < 0)
                cobre = y0 - 1e-6 <= c.ini + xa and c.ini + xb <= y1 + 1e-6
                largura_laje = x1 - x0
            if not (encosta and cobre):
                continue
            if bal:
                b2 = 2.0 * max(largura_laje - bw / 2.0, 0.0)
            else:
                outra = (c.linha + lado * largura_laje)
                b_outra = largura_da_viga_na_linha(
                    planta, c.em_x, outra, (c.ini + (xa + xb) / 2.0)) or 0.0
                b2 = largura_laje - bw / 2.0 - b_outra / 2.0
            achadas.append((b2, lajes[nome].espessura))
        if achadas:
            b2 = min(x[0] for x in achadas)
            b1_total += min(0.1 * a, 0.5 * b2)
            hf = min(hf, min(x[1] for x in achadas))
            lados.append(lado)
    if b1_total <= 1e-9:
        return V.Secao(bw=bw * CM, h=c.viga.h * CM)
    # seção L: a laje de um lado só. A viga anda em +x ou +y; olhando-a
    # entrar no papel, a esquerda de +x é +y, e a de +y é −x
    if len(lados) == 1:
        positivo_e_esquerda = c.em_x
        lado_mesa = ("esquerda" if (lados[0] > 0) == positivo_e_esquerda
                     else "direita")
    else:
        lado_mesa = "ambos"
    return V.Secao(bw=bw * CM, h=c.viga.h * CM, tipo="T",
                   bf=(bw + b1_total) * CM, hf=hf * CM, lado_mesa=lado_mesa)


def cargas_da_viga_isolada(V, c: Cadeia, retangulos, lajes):
    """Peso próprio e lajes pelas áreas a 45°, na coordenada da viga."""
    cargas = [V.CargaDistribuida(q1=c.viga.b * c.viga.h * GAMA_C,
                                 x_ini=0.0, x_fim=c.comprimento, acao="g",
                                 descricao="peso próprio")]
    for nome, (x0, y0, x1, y1, bal) in retangulos.items():
        laje = lajes[nome]
        lx, ly = x1 - x0, y1 - y0
        # as arestas da laje que caem nesta viga
        arestas = []
        if c.em_x:
            for yl in ((y0,) if bal else (y0, y1)):
                if abs(yl - c.linha) < 1e-6 and c.ini - 1e-6 <= x0 \
                        and x1 <= c.fim + 1e-6:
                    arestas.append((x0 - c.ini, x1 - c.ini, lx))
        else:
            if not bal:
                for xl in (x0, x1):
                    if abs(xl - c.linha) < 1e-6 and c.ini - 1e-6 <= y0 \
                            and y1 <= c.fim + 1e-6:
                        arestas.append((y0 - c.ini, y1 - c.ini, ly))
        for sa, sb, Le in arestas:
            for acao, q in (("g", g_da_laje(laje)), ("q", laje.acidental)):
                if q == 0.0:
                    continue
                if bal:
                    cargas.append(V.CargaDistribuida(
                        q1=q * laje.balanco, x_ini=sa, x_fim=sb, acao=acao,
                        descricao=f"{nome} em balanço"))
                    continue
                menor = min(lx, ly)
                total = q * menor * (2.0 * Le - menor) / 4.0
                r = min(menor / 2.0, Le / 2.0)
                pico = total / (Le - r)
                cargas.append(V.CargaDistribuida(
                    q1=0.0, q2=pico, x_ini=sa, x_fim=sa + r, acao=acao,
                    descricao=nome))
                if Le - 2.0 * r > 1e-9:
                    cargas.append(V.CargaDistribuida(
                        q1=pico, x_ini=sa + r, x_fim=sb - r, acao=acao,
                        descricao=nome))
                cargas.append(V.CargaDistribuida(
                    q1=pico, q2=0.0, x_ini=sb - r, x_fim=sb, acao=acao,
                    descricao=nome))
    return cargas


def viga_isolada(V, c: Cadeia, planta, retangulos, lajes, nivel: int,
                 n_niveis: int, h_lance: float, recebidas):
    """A ``Viga`` do programa de Vigas, montada como o usuário montaria."""
    pontos = [a[0] for a in c.apoios]
    ini_bal = pontos[0] > 1e-9
    fim_bal = c.comprimento - pontos[-1] > 1e-9
    vaos = [b - a for a, b in zip(pontos, pontos[1:])]
    tramos, apoios = [], []
    x = 0.0

    def tramo(L, n_momentos):
        nonlocal x
        s = secao_da_viga_isolada(V, c, planta, retangulos, lajes,
                                  len(tramos), x, x + L, n_momentos)
        x += L
        return V.Tramo(L=L, secao=s)

    def apoio(a):
        s, tipo, quem = a
        if tipo == "viga":
            # apoio indireto (18.3.6): a viga de apoio, o ponto nela e a
            # altura dela; os topos do pavimento alinhados
            return V.Apoio(tipo="simples", largura=quem.viga.b * CM,
                           viga_apoio=quem.viga.nome,
                           x_na_viga_apoio=quem.s_de(*c.ponto(s)),
                           h_viga_apoio=quem.viga.h * CM,
                           topos_alinhados=True)
        # o pilar descrito para a solidariedade do 14.6.6.1 (modelo
        # "rigidez", configurado abaixo): largura na direção da viga, a
        # perpendicular e os lances acima e abaixo do nó
        dx, dy = dimensoes_do_pilar(quem)
        largura, transversal = ((dx, dy) if c.em_x else (dy, dx))
        acima = h_lance * CM if nivel < n_niveis - 1 else 0.0
        return V.Apoio(tipo="simples", largura=largura * CM,
                       largura_pilar_transversal=transversal * CM,
                       altura_pilar_acima=acima,
                       altura_pilar_abaixo=h_lance * CM)

    if ini_bal:
        tramos.append(tramo(pontos[0], None))
        apoios.append(V.Apoio(tipo="livre"))
    n = len(vaos)
    for i, a in enumerate(c.apoios):
        if i > 0:
            k = i - 1
            momentos = int(k > 0 or ini_bal) + int(k < n - 1 or fim_bal)
            tramos.append(tramo(vaos[k], momentos))
        apoios.append(apoio(a))
    if fim_bal:
        tramos.append(tramo(c.comprimento - pontos[-1], None))
        apoios.append(V.Apoio(tipo="livre"))

    concentradas = []
    for s, g, q, de, pendurada, h_apoiada in recebidas:
        for acao, P in (("g", g), ("q", q)):
            if P > 1e-9:
                concentradas.append(V.CargaConcentrada(
                    P=P, x=s, acao=acao, descricao=f"{de} apoiada",
                    indireta=True, pendurada=pendurada,
                    h_apoiada=h_apoiada, topos_alinhados=True, origem=de))
    viga = V.Viga(nome=c.viga.nome, tramos=tramos, apoios=apoios,
                  distribuidas=cargas_da_viga_isolada(V, c, retangulos,
                                                      lajes),
                  concentradas=concentradas, concreto=V.Concreto(fck=30.0))
    viga.config.peso_proprio = False          # já está nas distribuídas
    viga.config.uniformizar_estribos = True
    viga.config.modelo_pilares = "rigidez"    # 14.6.6.1, pilares como molas
    return viga


def reacao(resultado, indice: int) -> tuple[float, float]:
    """(g, q) característicos que a viga entrega no apoio: permanente toda,
    variável só as parcelas positivas — o mesmo critério do programa."""
    g = q = 0.0
    for r in resultado.estrutura.respostas:
        v = float(r.reacoes[indice])
        if r.acao == "g":
            g += v
        else:
            q += max(v, 0.0)
    return max(g, 0.0), q


# ---------------------------------------------------------------------------
# Comparação de resultados de viga
# ---------------------------------------------------------------------------

def assinatura_da_viga(res) -> dict:
    """O que se compara: momentos de projeto, áreas e o detalhamento."""
    e = res.envoltoria
    return {
        "M_max": float(np.max(e.M_max)), "M_min": float(np.min(e.M_min)),
        "V_max": float(np.max(np.abs(e.V_max))),
        "regioes": [(r.nome, round(float(r.M), 2),
                     round(float(getattr(r.arranjo, "As_ef", 0.0)), 3),
                     f"{r.arranjo.n}Ø{r.arranjo.phi:g}")
                    for r in res.regioes],
        "posicoes": sorted(
            (p.tipo, p.face, p.n, float(p.phi), round(float(p.x_ini), 2),
             round(float(p.x_fim), 2), round(float(p.s or 0.0), 1))
            for p in res.posicoes),
        "ok": bool(getattr(res, "ok", False)),
    }


def diferencas(a: dict, b: dict) -> list[str]:
    saida = []
    for chave in ("M_max", "M_min", "V_max"):
        ref = max(abs(a[chave]), abs(b[chave]), 1e-9)
        if abs(a[chave] - b[chave]) / ref > 0.005:
            saida.append(f"{chave}: {a[chave]:.2f} × {b[chave]:.2f}")
    if a["regioes"] != b["regioes"]:
        saida.append(f"regiões: {a['regioes']} × {b['regioes']}")
    pa, pb = set(a["posicoes"]), set(b["posicoes"])
    if pa != pb:
        saida.append(f"posições só no Pórticos: {sorted(pa - pb)}; "
                     f"só no isolado: {sorted(pb - pa)}")
    if a["ok"] != b["ok"]:
        saida.append(f"veredito: {a['ok']} × {b['ok']}")
    return saida


# ---------------------------------------------------------------------------
# O roteiro
# ---------------------------------------------------------------------------

def main() -> int:
    from portico3d.armadura3d import armadura_do_pavimento
    from portico3d.continuidade import vigas_continuas
    from portico3d.core.envoltoria import envoltoria
    from portico3d.core.nbr6118 import acoes_do_modelo, combinacoes_elu
    from portico3d.core.segunda_ordem_global import \
        resultados_para_dimensionamento
    from portico3d.dimensionamento import (verificar_lajes, verificar_pilares,
                                           verificar_vigas)
    from portico3d.lancamento import gerar

    origens = _carregar_originais()
    from vigas.core import dimensionar as VD
    from vigas.core import modelo as V
    from pilares.core import dimensionar as PD
    from pilares.core import modelo as P
    from lajes.core import dimensionar as LD
    from lajes.core import modelo as L

    for sub in ("vigas", "pilares", "lajes", "imagens"):
        (SAIDA / sub).mkdir(parents=True, exist_ok=True)
    rel: list[str] = []
    dados: dict = {}
    t0 = time.time()

    def log(texto=""):
        print(texto, flush=True)
        rel.append(texto)

    lanc = E.lancamento()
    geracao = gerar(lanc)
    m = geracao.modelo
    planta = lanc.plantas["Tipo"]
    cotas = [p.cota for p in lanc.pavimentos]
    lajes_lancadas = {l.nome: l for l in planta.lajes}
    retangulos = retangulos_das_lajes(planta)
    log(f"# Edifício de 3 pavimentos — Pórticos × programas isolados\n")
    log("Programas isolados:\n")
    for pacote, de_onde in origens.items():
        log(f"- {pacote}: {de_onde}")
    log("")
    log(f"Modelo: {len(m.nos)} nós, {len(m.barras)} barras, "
        f"{len(m.lajes)} lajes. Avisos da geração: "
        f"{geracao.avisos or 'nenhum'}\n")

    res, _ = resultados_para_dimensionamento(
        m, combinacoes_elu(acoes_do_modelo(m)))
    env = envoltoria(m, res)
    log(f"Análise com 2ª ordem: {len(res)} combinações ({time.time()-t0:.0f} s)")

    # ===================================================================
    # VIGAS
    # ===================================================================
    log("\n## Vigas\n")
    vig_portico = {v.nome: v for v in verificar_vigas(m, envoltorias=env)}
    calculo = m.calculo
    m.calculo = replace(calculo, fonte_vigas="motor")
    vig_motor = {v.nome: v for v in verificar_vigas(m, envoltorias=env)}
    m.calculo = calculo
    cadeias_portico = {c.nome: c for c in vigas_continuas(m)}

    cadeias = montar_cadeias(planta)
    linhas_vigas = []
    mesma_entrada: list = []
    motivos_iso: list = []
    difs_vigas = 0
    for nivel, pav in enumerate(lanc.pavimentos):
        recebidas: dict[str, list] = {}
        # a V8 primeiro: a reação dela é carga na ponta de V1 e V2
        ordem = sorted(cadeias, key=lambda n: (cadeias[n].apoios[0][1]
                                               != "viga", n))
        for nome in ordem:
            c = cadeias[nome]
            viga = viga_isolada(V, c, planta, retangulos, lajes_lancadas,
                                nivel, len(cotas), 3.0,
                                recebidas.get(nome, []))
            viga.nome = f"{nome}.{pav.nome}"
            viga.salvar(str(SAIDA / "vigas" / f"{viga.nome}.json"))
            iso = VD.dimensionar(viga)
            for k, a in enumerate(c.apoios):
                if a[1] == "viga":
                    g, q = reacao(iso, k)
                    recebidas.setdefault(a[2].viga.nome, []).append(
                        (a[2].s_de(*c.ponto(a[0])), g, q, nome,
                         c.viga.h > a[2].viga.h + 1e-9, c.viga.h * CM))
            # a cadeia do Pórticos com o mesmo nome e pavimento
            chave = next((n for n, cp in cadeias_portico.items()
                          if any(b.startswith(f"{nome}.{pav.nome}.")
                                 for b in cp.barras)), None)
            vm = vig_motor.get(chave)
            vp = vig_portico.get(chave)
            if vm is None or not vm.passou:
                log(f"- {viga.nome}: o Pórticos não dimensionou "
                    f"({vm.erro if vm else 'sem cadeia'})")
                difs_vigas += 1
                continue
            a_iso = assinatura_da_viga(iso)
            a_mot = assinatura_da_viga(vm.resultado)
            d = diferencas(a_mot, a_iso)
            # A viga exatamente como o Pórticos a montou, gravada no formato
            # do programa de Vigas e aberta nele: separa "a ponte traduziu
            # diferente" de "o motor calculou diferente"
            arq = SAIDA / "vigas" / f"{viga.nome}-como-o-porticos-montou.json"
            vm.resultado.viga.salvar(str(arq))
            reaberta = VD.dimensionar(V.Viga.carregar(str(arq)))
            d_mesma = [t for t in diferencas(a_mot,
                                             assinatura_da_viga(reaberta))
                       if not t.startswith("veredito")]
            mesma_entrada.append((viga.nome, d_mesma))
            if not a_iso["ok"]:
                motivos_iso.append((viga.nome, [a for a in iso.avisos
                                                if a.lower().startswith(
                                                    ("erro", "[erro"))
                                                or "não ancora" in a][:3]))
            difs_vigas += bool(d)
            a_por = assinatura_da_viga(vp.resultado) if vp and vp.passou \
                else None
            linhas_vigas.append((viga.nome, a_iso, a_mot, a_por, d,
                                 vp.aprovado if vp else None))
            dados.setdefault("vigas", {})[viga.nome] = {
                "isolado": a_iso, "porticos_motor": a_mot,
                "porticos_portico": a_por, "diferencas": d}

    log("Comparação 1 — **mesma entrada**: Pórticos com as vigas armadas pelo "
        "motor (`fonte_vigas = \"motor\"`) contra o programa de Vigas isolado, com a "
        "entrada montada à mão.\n")
    log("| Viga | M+ máx (kN·m) | M− mín (kN·m) | V máx (kN) | "
        "posições de armadura | resultado |")
    log("|---|---|---|---|---|---|")
    for nome, a_iso, a_mot, a_por, d, _ in linhas_vigas:
        log(f"| {nome} | {a_mot['M_max']:.2f} / {a_iso['M_max']:.2f} | "
            f"{a_mot['M_min']:.2f} / {a_iso['M_min']:.2f} | "
            f"{a_mot['V_max']:.1f} / {a_iso['V_max']:.1f} | "
            f"{len(a_mot['posicoes'])} / {len(a_iso['posicoes'])} | "
            f"{'iguais' if not d else 'DIFEREM'} |")
    for nome, *_, d, _ in linhas_vigas:
        for t in d:
            log(f"- {nome}: {t}")

    log("\nComparação 1b — **a viga que o Pórticos montou**, gravada no "
        "formato do programa de Vigas e aberta nele: "
        f"{sum(not d for _, d in mesma_entrada)} de {len(mesma_entrada)} "
        "idênticas (momentos, regiões e posições de armadura).")
    for nome, d in mesma_entrada:
        for t in d:
            log(f"- {nome}: {t}")
    if motivos_iso:
        log("\nPor que o isolado reprova (o Pórticos aprova):\n")
        for nome, ms in motivos_iso:
            log(f"- {nome}: " + " | ".join(m[:230] for m in ms))

    log("\nComparação 2 — **o que o pórtico muda**: momentos de projeto com "
        "a envoltória do pórtico (vento, 2ª ordem, rigidez real dos pilares, "
        "trecho rígido) contra a viga contínua.\n")
    log("| Viga | região | M viga contínua | M pórtico | As contínua | "
        "As pórtico |")
    log("|---|---|---|---|---|---|")
    for nome, a_iso, a_mot, a_por, d, aprovado in linhas_vigas:
        if a_por is None:
            continue
        for (rn, M1, As1, arr1), (_, M2, As2, arr2) in zip(a_mot["regioes"],
                                                           a_por["regioes"]):
            log(f"| {nome} | {rn} | {M1:.2f} | {M2:.2f} | {arr1} | {arr2} |")

    # ===================================================================
    # LAJES
    # ===================================================================
    log("\n## Lajes\n")
    laj_portico = {round(v.cota, 3): v for v in verificar_lajes(m)}
    larg = {("y", 0.0): 0.20, ("y", 5.0): 0.20, ("y", 9.0): 0.20,
            ("x", 0.0): 0.15, ("x", 4.0): 0.20, ("x", 9.0): 0.20,
            ("x", 12.5): 0.15, ("x", 14.0): 0.15}
    for v in planta.vigas:                 # a largura vem do lançamento
        (xa, ya), (xb, yb) = v.pontos[0], v.pontos[-1]
        larg[("y", ya) if abs(ya - yb) < 1e-9 else ("x", xa)] = v.b
    difs_lajes = 0
    for pav in lanc.pavimentos:
        lajes_iso = []
        for nome, (x0, y0, x1, y1, bal) in retangulos.items():
            l = lajes_lancadas[nome]
            # retângulo de vão livre: meia largura da viga em cada lado
            # apoiado; a borda livre do balanço fica onde está
            fx0 = x0 + larg[("x", x0)] / 2.0
            fx1 = x1 - larg[("x", x1)] / 2.0
            fy0 = y0 + larg[("y", y0)] / 2.0
            fy1 = y1 if bal else y1 - larg[("y", y1)] / 2.0
            a_, b_ = fx1 - fx0, fy1 - fy0
            laje = L.Laje(nome=f"{nome}.{pav.nome}", a=a_, b=b_,
                          h=l.espessura * CM, x=fx0, y=fy0,
                          destino="balanco" if bal else "piso",
                          orientacao="X" if a_ >= b_ else "Y",
                          permanente_extra=l.permanente,
                          variavel=l.acidental)
            # a largura do apoio de cada bordo, pela face que ele ocupa
            faces = {"esquerda": larg[("x", x0)], "direita":
                     larg.get(("x", x1), 0.15), "baixo": larg[("y", y0)],
                     "cima": larg.get(("y", y1), 0.20)}
            for k in range(1, 5):
                face = laje.face_do_bordo(k)
                livre = bal and face != "baixo"
                laje.bordos[k - 1] = L.Bordo(
                    vinculo="livre" if livre else "apoiado",
                    t=faces[face] * CM)
            lajes_iso.append(laje)
        pav_iso = L.Pavimento(nome=f"{pav.nome} (isolado)", lajes=lajes_iso,
                              concreto=L.Concreto(fck=30.0))
        pav_iso.aplicar_continuidades(pav_iso.detectar_continuidades())
        pav_iso.salvar(str(SAIDA / "lajes" / f"{pav.nome}.json"))
        r_iso = LD.dimensionar(pav_iso)
        vp = laj_portico[round(pav.cota, 3)]
        r_por = vp.resultado

        def posicoes(r):
            return sorted((p.laje, p.face, p.eixo, float(p.phi),
                           float(p.espacamento), int(p.quantidade),
                           round(float(p.inicio), 1), round(float(p.fim), 1))
                          for p in r.todas_posicoes)

        def vinculos(pv):
            return {l.nome: tuple(b.vinculo for b in l.bordos)
                    for l in pv.lajes}

        pi, pp = posicoes(r_iso), posicoes(r_por)
        vi, vpv = vinculos(pav_iso), vinculos(r_por.pavimento)
        t_iso = {l.nome: tuple(b.t for b in l.bordos) for l in pav_iso.lajes}
        t_por = {l.nome: tuple(b.t for b in l.bordos)
                 for l in r_por.pavimento.lajes}
        log(f"### {pav.nome} (cota {pav.cota:g} m)\n")
        log(f"- posições: Pórticos {len(pp)}, isolado {len(pi)} — "
            f"{'iguais' if pi == pp else 'DIFEREM'}")
        log(f"- vínculos: {'iguais' if vi == vpv else 'DIFEREM'}; larguras "
            f"de apoio: {'iguais' if t_iso == t_por else 'DIFEREM'}")
        log(f"- aprovado: Pórticos {vp.aprovado} ({len(r_por.erros)} "
            f"erros), isolado {not r_iso.erros} ({len(r_iso.erros)} erros)")
        if vi != vpv:
            for n in vi:
                if vi[n] != vpv.get(n):
                    log(f"  - {n}: isolado {vi[n]} × Pórticos {vpv.get(n)}")
        if t_iso != t_por:
            for n in t_iso:
                if t_iso[n] != t_por.get(n):
                    log(f"  - {n}: t isolado {t_iso[n]} × Pórticos "
                        f"{t_por.get(n)}")
        if pi != pp:
            difs_lajes += 1
            si, sp = set(pi), set(pp)
            for p in sorted(sp - si)[:12]:
                log(f"  - só no Pórticos: {p}")
            for p in sorted(si - sp)[:12]:
                log(f"  - só no isolado:  {p}")
        dados.setdefault("lajes", {})[pav.nome] = {
            "porticos": pp, "isolado": pi}

    # ===================================================================
    # PILARES
    # ===================================================================
    log("\n## Pilares\n")
    pil = [] if "--sem-pilares" in sys.argv else verificar_pilares(m, env)
    log(f"Pórticos: {len(pil)} verificações de lance ({time.time()-t0:.0f} s)")
    difs_pilares = 0
    log("\n| Lance | combinação | Nd (kN) | Mx base/topo (kN·cm) | "
        "My base/topo (kN·cm) | arranjo Pórticos | arranjo isolado | "
        "resultado |")
    log("|---|---|---|---|---|---|---|---|")
    from portico3d.core.montagem import preparar_barras
    preparadas = preparar_barras(m)
    por_lance: dict[str, list] = {}
    for v in pil:
        por_lance.setdefault(v.barra, []).append(v)
    for barra, vs in sorted(por_lance.items()):
        b = m.barras[barra]
        # o pilar lançado que gerou o lance
        base_no = b.no_i if m.ponto(b.no_i)[2] < m.ponto(b.no_j)[2] \
            else b.no_j
        pb = m.ponto(base_no)
        p_lanc = pilar_em(planta, pb[0], pb[1])
        dx, dy = dimensoes_do_pilar(p_lanc)
        for v in vs:
            if not v.passou:
                continue
            r = res[v.combinacao]
            f = r.esforcos_barra(barra)
            R = preparadas[barra].R
            m_i = -(R.T @ f[3:6])          # momento interno, global, em i
            m_j = R.T @ f[9:12]
            n_i, n_j = f[0], -f[6]         # compressão positiva
            i_embaixo = m.ponto(b.no_i)[2] < m.ponto(b.no_j)[2]
            mb, mt = (m_i, m_j) if i_embaixo else (m_j, m_i)
            Nd = max(n_i, n_j)
            # Mx do programa de Pilares flete na direção x: é o momento em
            # torno do eixo global Y; My, em torno do X
            pilar = P.Pilar(
                nome=f"{barra} {v.combinacao}",
                secao=P.SecaoPilar(tipo="retangular", hx=dx * CM,
                                   hy=dy * CM),
                esforcos=P.Esforcos(Nd=Nd, Mx_base=mb[1] * CM,
                                    Mx_topo=mt[1] * CM, My_base=mb[0] * CM,
                                    My_topo=mt[0] * CM),
                lance=P.Lance(l=3.0 * CM, comprimento=3.0 * CM),
                concreto=P.Concreto(fck=30.0))
            iso = PD.dimensionar(pilar)
            pilar.salvar(str(SAIDA / "pilares" /
                             f"{barra}_{v.combinacao.replace(' ', '')}.json"))
            arr_p = getattr(v.resultado, "arranjo", None)
            arr_i = getattr(iso, "arranjo", None)
            desc = (lambda a: a.descricao() if callable(
                getattr(a, "descricao", None)) else str(a))
            dp, di = (desc(arr_p) if arr_p else "—",
                      desc(arr_i) if arr_i else "—")
            e = v.esforcos
            iguais = (dp == di and bool(v.resultado.ok) == bool(iso.ok)
                      and abs(e.Nd - Nd) <= 0.01 * max(abs(Nd), 1.0))
            difs_pilares += not iguais
            log(f"| {barra} | {v.combinacao} | {e.Nd:.1f} / {Nd:.1f} | "
                f"{e.Mx_base:.0f}/{e.Mx_topo:.0f} × {mb[1]*CM:.0f}/"
                f"{mt[1]*CM:.0f} | {e.My_base:.0f}/{e.My_topo:.0f} × "
                f"{mb[0]*CM:.0f}/{mt[0]*CM:.0f} | {dp} | {di} | "
                f"{'iguais' if iguais else 'DIFEREM'} |")
            dados.setdefault("pilares", []).append({
                "lance": barra, "comb": v.combinacao, "portico": dp,
                "isolado": di, "iguais": iguais,
                "esforcos_ponte": [e.Nd, e.Mx_base, e.Mx_topo, e.My_base,
                                   e.My_topo],
                "esforcos_isolado": [Nd, mb[1] * CM, mt[1] * CM, mb[0] * CM,
                                     mt[0] * CM]})

    # ===================================================================
    # ARMADURA 3D
    # ===================================================================
    log("\n## Armadura em 3D\n")
    for cota in cotas:
        arm = armadura_do_pavimento(m, cota, env)
        familias = {k: len(v) for k, v in arm.por_familia().items()}
        fora = _fora_do_concreto(m, arm)
        log(f"- cota {cota:g} m: {familias}; avisos: "
            f"{arm.avisos or 'nenhum'}; pontos de barra fora do concreto: "
            f"{ {k: len(v) for k, v in fora.items()} or 'nenhum'}")
        for familia, pts in fora.items():
            for elemento, pt in pts[:4]:
                log(f"  - {familia} {elemento}: {pt}")
        dados.setdefault("armadura", {})[str(cota)] = {
            "familias": familias, "avisos": arm.avisos}
        _imagens(m, arm, cota)

    log(f"\n## Resumo\n\nVigas com diferença: {difs_vigas}; pavimentos de "
        f"laje com diferença: {difs_lajes}; verificações de pilar com "
        f"diferença: {difs_pilares}. Tempo: {time.time()-t0:.0f} s.")
    (SAIDA / "relatorio.md").write_text("\n".join(rel), encoding="utf-8")
    (SAIDA / "dados.json").write_text(json.dumps(dados, indent=1,
                                                 ensure_ascii=False,
                                                 default=str),
                                      encoding="utf-8")
    return 0


def _fora_do_concreto(m, arm, folga: float = 0.005) -> dict[str, list]:
    """Pontos de barra que não caem dentro de concreto nenhum: alma de viga,
    seção de pilar ou laje (em planta e na espessura). Por família."""
    from portico3d.core.lajes import (deslocamento_do_centro,
                                      desnivel_da_viga, retangulo)
    from portico3d.core.montagem import preparar_barras

    caixas = []
    for nome, p in preparar_barras(m).items():
        s = m.secoes[p.barra.secao]
        # a viga com o topo no nível do pavimento, como o desenho a põe
        dz = np.array([0.0, 0.0, desnivel_da_viga(m, nome)])
        a, b = m.ponto(p.barra.no_i) + dz, m.ponto(p.barra.no_j) + dz
        caixas.append((a, b, np.asarray(p.R[0], float),
                       np.asarray(p.R[1], float), np.asarray(p.R[2], float),
                       s.b / 2.0, s.h / 2.0))
    placas = []
    for laje in m.lajes.values():
        x0, y0, x1, y1, z = retangulo(m, laje)
        c = z + deslocamento_do_centro(m, laje)
        e = max(laje.altura, 0.01) / 2.0
        placas.append((x0, y0, x1, y1, c - e, c + e))

    def dentro(pt) -> bool:
        for a, b, ex, ey, ez, mb, mh in caixas:
            d = pt - a
            L = float(np.linalg.norm(b - a))
            t = float(d @ ex)
            # o nó tem meia seção a mais de concreto (o pilar que o atravessa,
            # a viga que entra nele): tolerância de meia altura nas pontas
            if -mh - folga <= t <= L + mh + folga and \
                    abs(float(d @ ey)) <= mb + folga and \
                    abs(float(d @ ez)) <= mh + folga:
                return True
        for x0, y0, x1, y1, zb, zt in placas:
            if x0 - folga <= pt[0] <= x1 + folga and \
                    y0 - folga <= pt[1] <= y1 + folga and \
                    zb - folga <= pt[2] <= zt + folga:
                return True
        return False

    fora: dict[str, list] = {}
    for f in arm.fios:
        # longitudinais: as pontas bastam (são retas); estribos: os cantos
        for pt in f.pontos:
            if not dentro(pt):
                fora.setdefault(f.familia, []).append(
                    (f.elemento, tuple(round(float(v), 3) for v in pt)))
    return fora


def _imagens(m, arm, cota: float) -> None:
    """A armadura do pavimento fora de tela: vista geral e de cima."""
    try:
        import pyvista as pv
        from portico3d.ui.vista3d import construir_cena_armadura
    except Exception as erro:                        # pragma: no cover
        print(f"sem imagens: {erro}")
        return
    for nome, posicao in (("geral", "iso"), ("cima", "xy")):
        plotter = pv.Plotter(off_screen=True, window_size=(1600, 1000))
        construir_cena_armadura(plotter, m, arm, cota)
        if posicao == "xy":
            plotter.view_xy()
        else:
            plotter.view_isometric()
        plotter.reset_camera()
        plotter.camera.zoom(1.25)
        plotter.screenshot(str(SAIDA / "imagens" /
                               f"armadura_{cota:g}m_{nome}.png"))
        plotter.close()


if __name__ == "__main__":
    sys.exit(main())
