# -*- coding: utf-8 -*-
"""
auditoria.py
Roteiro de verificações da memória de cálculo: uma linha por item da norma
que o programa confere, com o valor apurado, o limite e o veredito.

Serve para a memória ser **auditável**. Quem revisa o projeto não quer
percorrer o cálculo inteiro: quer a lista do que foi verificado, com o número
de cada verificação e o item que a justifica, e poder ir direto ao que não
fechou. É isso que este módulo monta.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Verificacao:
    """Uma linha do roteiro."""

    item: str                       # item da NBR 6118 ou § da apostila
    descricao: str
    onde: str = ""                  # laje / bordo
    valor: str = ""
    limite: str = ""
    atende: bool = True
    #: Linha de **preferência** do projetista, e não de exigência normativa.
    #: A distinção existe para o resumo não somar as duas: uma faixa de bitola
    #: não atendida não reprova a laje, que continua verificada em tudo o que
    #: a norma pede.
    preferencia: bool = False

    @property
    def veredito(self) -> str:
        if self.atende:
            return "OK"
        return "fora da preferência" if self.preferencia else "NÃO OK"


def _n(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def roteiro(res) -> list[Verificacao]:
    """Monta o roteiro completo de verificações do pavimento."""
    linhas: list[Verificacao] = []
    pav = res.pavimento
    cfg = pav.config

    # -- 13.2.4.1: espessura mínima ----------------------------------------
    from ..core.els import espessura_minima_normativa
    for rl in res.lajes:
        minima = espessura_minima_normativa(rl.laje)
        linhas.append(Verificacao(
            "13.2.4.1", f"Espessura mínima de laje maciça ({rl.laje.destino})",
            rl.nome, f"h = {_n(rl.laje.h, 1)} cm",
            f">= {_n(minima, 1)} cm", rl.laje.h >= minima - 1e-9))

    # -- 20.1: bitola máxima e espaçamento máximo --------------------------
    for p in res.todas_posicoes:
        laje = pav.laje(p.laje.split(" / ")[0])
        if laje is None:
            continue
        limite_phi = laje.h / 8.0 * 10.0
        linhas.append(Verificacao(
            "20.1", f"Bitola da armadura de flexão <= h/8 — N{p.numero}",
            p.laje, f"Ø = {_n(p.phi, 1)} mm",
            f"<= {_n(limite_phi, 1)} mm", p.phi <= limite_phi + 1e-9))
        principal = p.tipo != "distribuição"
        s_max = (min(2.0 * laje.h, cfg.espacamento_maximo_principal)
                 if principal else cfg.espacamento_maximo_distribuicao)
        linhas.append(Verificacao(
            "20.1",
            f"Espaçamento máximo da armadura "
            f"{'principal' if principal else 'de distribuição'} — "
            f"N{p.numero}", p.laje, f"s = {_n(p.espacamento, 1)} cm",
            f"<= {_n(s_max, 1)} cm", p.espacamento <= s_max + 1e-9))

    # -- faixa de bitola desejada, quando houver ---------------------------
    if cfg.bitola_desejada_minima or cfg.bitola_desejada_maxima:
        for rl in res.lajes:
            for chave, e in rl.escolhas.items():
                if not e.faixa_desejada or e.phi <= 0.0:
                    continue
                dentro = ((not e.faixa_desejada[0]
                           or e.phi >= e.faixa_desejada[0] - 1e-9)
                          and (not e.faixa_desejada[1]
                               or e.phi <= e.faixa_desejada[1] + 1e-9))
                linhas.append(Verificacao(
                    "preferência",
                    f"Bitola dentro da faixa desejada — {chave}", rl.nome,
                    f"Ø = {_n(e.phi, 1)} mm", e.texto_faixa(), dentro,
                    preferencia=True))

    # -- 14.6.4.3 / §1.7: ductilidade em regime rígido-plástico ------------
    for rl in res.lajes:
        for f in rl.flexoes:
            if f.md <= 0.0:
                continue
            linhas.append(Verificacao(
                "14.6.4.3", f"Ductilidade x/d no regime rígido-plástico — "
                            f"{f.rotulo}", rl.nome,
                f"x/d = {_n(f.x_sobre_d, 3)}",
                f"<= {_n(f.x_sobre_d_limite, 2)}", f.ductil))

    # -- 17.3.5.2 / §1.8: armadura mínima ----------------------------------
    for rl in res.lajes:
        for f in rl.flexoes:
            linhas.append(Verificacao(
                "17.3.5.2", f"Armadura mínima ({f.tipo_minima}) — {f.rotulo}",
                rl.nome, f"As = {_n(f.As)} cm²/m",
                f">= {_n(f.As_minima)} cm²/m",
                f.As >= f.As_minima - 1e-6))

    # -- resistência: As adotada cobre a necessária ------------------------
    for p in res.todas_posicoes:
        linhas.append(Verificacao(
            "17.2.2", f"Armadura adotada cobre a necessária — N{p.numero}",
            p.laje, f"As,ef = {_n(p.As_efetiva)} cm²/m",
            f">= {_n(p.As_necessaria)} cm²/m",
            p.As_efetiva >= p.As_necessaria - 1e-6))

    # -- 13.3 / §1.6: flecha -----------------------------------------------
    for rl in res.lajes:
        if rl.els is None:
            continue
        linhas.append(Verificacao(
            "Tabela 13.3", "Deslocamento limite — aceitabilidade visual",
            rl.nome, f"f(t=∞) = {_n(rl.els.f_diferida)} cm",
            f"<= {_n(rl.els.f_admissivel)} cm (L/{rl.els.divisor})",
            rl.els.atende))

    # -- 19.4.1: cortante ---------------------------------------------------
    for rl in res.lajes:
        for c in rl.cortantes:
            linhas.append(Verificacao(
                "19.4.1", "Cortante sem armadura transversal", c.rotulo,
                f"VSd = {_n(c.v_sd, 1)} kN/m",
                f"<= VRd1 = {_n(c.v_rd1, 1)} kN/m", c.atende))
            if c.precisa_armadura and not c.erro:
                linhas.append(Verificacao(
                    "19.4.2", "Armadura transversal necessária, com fywd "
                              "limitado pela espessura", c.rotulo,
                    f"Asw = {_n(c.asw_por_m2)} cm²/m por metro",
                    f"fywd <= {_n(c.fywd, 0)} MPa", True))

    # -- 7.4.7.5: cobrimento da face superior cobre a bitola adotada -------
    # o cobrimento da face revestida cai a 15 mm, mas nunca menos que a
    # bitola da barra -- e a bitola só se conhece depois do cálculo. Este é
    # o registro de que o ciclo fechou: o cobrimento usado para achar a
    # armadura já é o que a bitola finalmente adotada exige.
    for c in res.cobrimentos:
        linhas.append(Verificacao(
            "7.4.7.5", f"Cobrimento da face superior cobre a bitola Ø"
                       f"{_n(c.bitola_adotada, 1)} adotada", c.rotulo,
            f"c' = {_n(c.cobrimento_usado, 2)} cm",
            f">= {_n(c.cobrimento_exigido, 2)} cm", c.atende))
        if not c.convergiu:
            linhas.append(Verificacao(
                "7.4.7.5", "Convergência bitola × cobrimento", c.rotulo,
                "não fechou nas voltas tentadas", "deveria fechar", False))

    # -- 9.4.2.5: ancoragem no apoio de extremidade -------------------------
    # positiva no apoio simples e negativa que termina num apoio real (não
    # numa laje vizinha) passam pela mesma checagem
    for rl in res.lajes:
        for a in rl.ancoragens:
            linhas.append(Verificacao(
                "9.4.2.5", "Ancoragem no apoio de extremidade",
                a.rotulo, f"disponível = {_n(a.disponivel, 1)} cm"
                          + (f" + gancho {_n(a.ponta_gancho, 0)} cm"
                             if a.com_gancho else ""),
                f">= lb,nec = {_n(a.lb_nec, 1)} cm", a.atende))

    # -- §1.7: razão mínima entre momento de borda e de vão ----------------
    for rl in res.lajes:
        esf = rl.esforcos
        from ..core.esforcos import BORDOS_DA_DIRECAO
        for bordo, m_neg in esf.m_neg.items():
            direcao = "b" if bordo in BORDOS_DA_DIRECAO["b"] else "a"
            m_vao = esf.momento_da_direcao(direcao)
            if m_vao <= 1e-9:
                continue
            razao = m_neg / m_vao
            linhas.append(Verificacao(
                "§1.7", f"Razão entre momento de borda e de vão — bordo "
                        f"{bordo}", rl.nome, f"m'/m = {_n(razao)}",
                f">= {_n(cfg.razao_minima_borda_vao, 1)}",
                razao >= cfg.razao_minima_borda_vao - 1e-6))

    # -- 14.7.6.2: compatibilização ----------------------------------------
    comp = res.compatibilizacao
    if comp is not None:
        for b in comp.bordas:
            linhas.append(Verificacao(
                "14.7.6.2", "Armadura única de continuidade na borda comum",
                b.rotulo,
                f"m' adotado = {_n(b.m_adotado)} kN·m/m com d = "
                f"{_n(b.d_adotado, 1)} cm",
                f">= max({_n(b.m_a)} ; {_n(b.m_b)}) e d = min das duas",
                b.m_adotado >= max(b.m_a, b.m_b) - 1e-6))

    # -- reações: a carga entregue é a carga recebida -----------------------
    for rl in res.lajes:
        if rl.reacoes is None:
            continue
        soma = sum(r.fracao for r in rl.reacoes.bordos)
        tem_apoio = any(r.vinculo != "livre" for r in rl.reacoes.bordos)
        if not tem_apoio:
            continue
        linhas.append(Verificacao(
            "14.7.6.1", "Reações repartidas somam a carga da laje", rl.nome,
            f"soma = {_n(soma * 100.0, 1)} %", "= 100 %",
            abs(soma - 1.0) <= 0.02))
    return linhas


def resumo(linhas: list[Verificacao]) -> tuple[int, int, int]:
    """``(verificações normativas, reprovadas, preferências não atendidas)``.

    As preferências ficam fora da contagem de reprovações: uma faixa de
    bitola não atendida não reprova a laje, que continua verificada em tudo
    o que a norma exige.
    """
    normativas = [v for v in linhas if not v.preferencia]
    preferencias = [v for v in linhas if v.preferencia]
    return (len(normativas), sum(1 for v in normativas if not v.atende),
            sum(1 for v in preferencias if not v.atende))


def metodologia(res) -> list[tuple[str, str]]:
    """Pares ``(assunto, o que o programa fez)`` para o capítulo de método."""
    pav = res.pavimento
    cfg = pav.config
    criterio = {"nenhuma": "não compatibilizados",
                "maior": "compatibilizados pelo maior dos dois momentos",
                "iterativa": "equilibrados por ajuste iterativo dos graus "
                             "de engastamento"}
    return [
        ("Classificação das lajes",
         "Relação entre os lados e vinculação dos bordos (§1.2): b/a > 2, ou "
         "apoio em apenas dois bordos paralelos, ou balanço, produzem laje "
         "armada em uma só direção; o resto é armada em cruz."),
        ("Vãos efetivos",
         "lef = l0 + a1 + a2, com ai = min(ti/2 ; 0,3 h) em cada apoio "
         "(14.7.2.2). No balanço, o vão livre acrescido de 0,3 h junto ao "
         "apoio."),
        ("Solicitações no estado limite último",
         "Regime rígido-plástico -- método das linhas de ruptura (§3.2). Laje "
         "isótropa para 0,8 <= a/b <= 1 e ortótropa abaixo disso, com o "
         "coeficiente de ortotropia phi = [(12 - i2 - i4)/(12 - i1 - i3)] "
         "(a/b)^1,7. Cargas lineares de parede pelos coeficientes alfa e "
         "beta do formulário, obtido para a posição mais desfavorável. Na "
         "laje armada em uma direção, os coeficientes de vão e de engaste "
         "dos quatro esquemas estruturais (§2)."),
        ("Solicitações no estado limite de serviço",
         "Regime elástico -- m = alfa p a², com o alfa tabelado por "
         "vinculação e por a/b (§3.1). Combinação quase permanente, com "
         "psi_2 = " + f"{cfg.psi_2:g}."),
        ("Momentos negativos",
         "m'k = -ik . m da direção que o bordo apoia, com i entre 0,7 e 2,0 "
         "e a norma recomendando i <= 1,5 (§3.2). Momentos das bordas comuns "
         + criterio.get(cfg.compatibilizacao, "") + " (14.7.6.2)."),
        ("Flexão",
         "Diagrama retangular equivalente do item 17.2.2 em faixa de 1 m, "
         "armadura simples, com lambda e alfa_c dependentes do fck. Limite "
         "de x/d de " + f"{pav.concreto.x_sobre_d_limite:g}" + " imposto pelo "
         "item 14.6.4.3 a quem determina as solicitações em regime "
         "rígido-plástico. Armaduras mínimas pela tabela do §1.8, que "
         "distingue negativa de continuidade, negativa de borda, positiva "
         "em cruz, positiva principal e de distribuição."),
        ("Serviço",
         "Flecha f = k p a⁴/(Ecs Ieq) com o k tabelado (§1.6), Ieq em dois "
         "patamares (Ic enquanto ma <= mr; 0,30 Ic acima), mr = 0,25 fctm "
         "b h², e flecha diferida por (1 + alfa_f) = "
         f"{cfg.fator_fluencia:g} (17.3.2.1.2, com t0 = 1 mês). Limite "
         f"L/{cfg.divisor_flecha} e L/{cfg.divisor_flecha_balanco} em "
         "balanço (Tabela 13.3)."),
        ("Força cortante",
         "VRd1 = [tau_Rd k (1,2 + 40 rho1) + 0,15 sigma_cp] bw d do item "
         "19.4.1, com tau_Rd = 0,25 fctd, k = |1,6 - d| >= 1 porque o item "
         "20.1 leva toda a armadura positiva ao apoio, e rho1 <= 0,02. "
         "Quando VSd passa de VRd1, armadura transversal pelo item 19.4.2, "
         "com fywd limitado a 250 MPa até 15 cm e 435 MPa acima de 35 cm."),
        ("Reações de apoio",
         "Charneiras plásticas aproximadas por retas a 45° entre apoios do "
         "mesmo tipo, 60° a partir do engastado e 90° a partir do bordo "
         "vizinho ao livre (14.7.6.1). Onde a tabela de Hahn se aplica "
         "(1,00 <= b/a <= 2,00 e quatro bordos vinculados) valem os valores "
         "dela; nos demais casos, a construção geométrica das mesmas "
         "charneiras."),
        ("Detalhamento",
         "Bitola limitada a h/8 e espaçamento a min(2h ; 20 cm) na armadura "
         "principal e 33 cm na de distribuição (20.1). Armadura positiva "
         "levada inteira ao apoio, sem escalonamento, prolongada 4 cm além "
         "do eixo teórico. Armadura de continuidade estendida um quarto do "
         "maior dos vãos menores para cada lado do eixo, e de contorno um "
         "quinto do vão menor (§3.3)."),
    ]
