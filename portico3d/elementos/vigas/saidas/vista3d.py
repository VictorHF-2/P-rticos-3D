# -*- coding: utf-8 -*-
"""
vista3d.py
Vista 3D da viga detalhada em PyVista/VTK: o concreto como sólido e cada
posição de armadura como tubo, com o gancho, a dobra e o espaçamento que o
detalhamento calculou.

METODOLOGIA copiada do programa de Sapatas
(``nucleo_calculo/sapatas_vista3d.py``), depois de a primeira tentativa -- um
``pyvistaqt.QtInteractor`` embutido numa aba -- se mostrar inviável nesta
classe de máquina. São duas peças, e é a separação entre elas que faz a
interação ser rápida:

1. **a aba mostra uma imagem** (:func:`renderizar_png`), renderizada fora de
   tela: estática, barata, e disponível até no ``--autoteste``, que roda sem
   janela nenhuma;
2. **a interação vive numa janela própria do VTK**
   (:func:`abrir_vista_interativa`), aberta por um botão. Ela desenha direto
   na superfície nativa dela: não há ``QOpenGLWidget`` no caminho, e portanto
   não há o ciclo de repintura do Qt (resolve e cópia do framebuffer) nem o
   render duplo por evento de mouse que o ``pyvistaqt`` impõe. Foi medido, e
   era esse caminho -- não a geometria -- que travava a versão embutida:
   ~16 ms por evento de mouse contra ~2 ms para desenhar a viga inteira.

O módulo é **puro de Qt**: quem embute a imagem e quem chama o botão é
``vigas/ui/janela.py``. É isso que permite o ``--autoteste`` exercitar a vista
inteira sem interface.

**Um ator por posição, não por barra.** As barras de um mesmo "N" têm a mesma
bitola, o mesmo comprimento e o mesmo texto: fundidas numa malha só
(:func:`_juntar`), apontar qualquer barra acende a posição inteira -- que é o
que se decide em projeto; ninguém dimensiona a sétima barra, dimensiona a
posição. Também é o que torna a vista utilizável em viga pesada: com um ator
por barra, uma viga T carregada levava 245 s para montar a cena contra 1,8 s
fundida, porque o custo está em cada ``add_mesh``, não na geometria.

A geometria vem das mesmas funções que já montam a elevação e o DXF
(``vigas/saidas/geometria.py``) -- o contorno da seção, a altura de cada
camada, o traçado do gancho com o raio de verdade, o laço fechado do estribo.
Uma fonte só: a vista 3D não pode mostrar um gancho diferente do que a
prancha mostra.

**A largura é repartida entre as posições que convivem**, e não posição a
posição -- ver :func:`_laterais_por_posicao`. Sem isso, uma face com quatro
barras (duas que seguem até o apoio e duas que o escalonamento corta) saía
com as quatro em dois lugares, e a armadura negativa de dois vãos se
desenhava dentro de si mesma sobre o apoio.

Simplificações declaradas, para quem for estender isto depois:

* numa zona de traspasse a camada fica congestionada por construção -- as
  duas barras que se emendam convivem ali --, e a repartição as põe lado a
  lado com a folga que couber, que pode ser menor que o espaçamento livre do
  item 18.3.2.2. Quem cobra esse espaçamento é o cálculo
  (``detalhamento.montar_arranjo``); o desenho mostra o que o detalhamento
  produziu;
* os ramos internos do estribo (além dos dois externos) não são desenhados,
  pela mesma razão de ``montar_secao`` não os desenhar: não há posição na
  malha de dados para a perna interna, só a área que ela soma;
* o grampo é orientado pela proximidade a cada extremidade da viga (a mesma
  regra que ``montar_elevacao`` usa para decidir onde fica o traço da dobra).
"""

from __future__ import annotations

import numpy as np
import pyvista as pv

from ..core import alinhamento as al
from ..core import ganchos as gk
from . import estilo
from .geometria import (
    _contorno_secao, _parte_reta_do_gancho, _y_barra, barra_com_dobras,
    cantos_da_mesa, laco_da_mesa, grampo_em_u, retangulo_arredondado)

#: Raio mínimo do tubo de armadura, cm -- metade da bitola já dá um tubo fino
#: mas visível, e proporcional entre bitolas diferentes; abaixo desse piso um
#: Ø5 ficaria fino demais para acertar com o mouse.
_RAIO_MINIMO = 0.30

#: Opacidade de quem NÃO está em destaque, e a do concreto, que é moldura e
#: não assunto.
_OPACIDADE_APAGADA = 0.15
_OPACIDADE_CONCRETO = 0.30
_OPACIDADE_CONCRETO_APAGADO = 0.06

#: Cor de destaque -- o mesmo âmbar de "atenção" do resto da interface
#: (``ui.tema.AMBAR``), repetido aqui em vez de importado: este módulo não
#: depende de ``ui``.
_AMBAR = (0.69, 0.49, 0.11)

#: cor das posições construtivas (porta-estribo e barra só-de-canto), para não
#: se confundirem com armadura calculada. As demais seguem a convenção do
#: croqui e do DXF (LEIAME.md, "Cores das armaduras"): superior azul,
#: inferior vermelho, estribo verde, pele laranja.
_COR_CONSTRUTIVA = (0.55, 0.55, 0.55)


def _raio_barra(phi_mm: float) -> float:
    return max(phi_mm / 20.0, _RAIO_MINIMO)


def _tubo(pontos, raio: float) -> pv.PolyData:
    linha = pv.MultipleLines(points=np.asarray(pontos, dtype=float))
    return linha.tube(radius=raio)


def _juntar(pecas: list) -> pv.PolyData:
    """Funde as barras de uma posição numa malha só.

    Um ator por barra física custa caro em tudo o que a interação faz: cada
    ator é uma chamada de desenho por quadro, uma entrada a mais no pick e
    uma propriedade a mais para mexer no destaque. E não compra nada: o que
    esta vista explica é a **posição** (o "N" da lista de aço), não a barra
    individual -- as barras de uma posição têm a mesma bitola, o mesmo
    comprimento e o mesmo texto. Fundidas, uma viga comum sai com ~15
    atores em vez de ~130.
    """
    return pecas[0] if len(pecas) == 1 else pv.merge(pecas)


def _solido(pontos_yz, x0: float, x1: float) -> pv.PolyData:
    """Extruda o contorno 2D ``(y, z)`` da seção transversal ao longo do eixo
    da viga, de ``x0`` a ``x1`` -- o mesmo contorno que ``geometria.
    _contorno_secao`` já entrega para a seção transversal em 2D, aqui virando
    um sólido de verdade."""
    contorno = np.array([[x0, y, z] for y, z in pontos_yz], dtype=float)
    n = len(contorno)
    poligono = pv.PolyData(contorno, faces=[n] + list(range(n)))
    return poligono.extrude((x1 - x0, 0.0, 0.0), capping=True)


def _cor_longitudinal(p) -> tuple[float, float, float]:
    if p.tipo == "porta" or p.so_canto:
        return _COR_CONSTRUTIVA
    return _rgb(estilo.VERMELHO if p.face == "inferior"
                      else estilo.AZUL)


def _rgb(cor_hex: str) -> tuple[float, float, float]:
    """``"#RRGGBB"`` -> ``(r, g, b)`` em [0, 1], o que ``add_mesh`` espera."""
    cor_hex = cor_hex.lstrip("#")
    return tuple(int(cor_hex[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _laterais_por_posicao(res, cob: float) -> dict[int, list[float]]:
    """Onde cada barra de cada posição fica na largura, cm da face esquerda.

    Devolve ``{número da posição: [y de cada barra]}``.

    **Barra não ocupa o lugar de outra.** Duas coisas obrigam a decidir isto
    para a viga inteira, e não posição a posição:

    * uma face com 4 barras costuma virar **duas posições** -- as que seguem
      até o apoio e as que o escalonamento corta. Espalhando cada uma como se
      estivesse sozinha, as duas caem nas extremidades e o meio da seção fica
      vazio: quatro barras em dois lugares;
    * a armadura negativa de dois vãos vizinhos se **cruza sobre o apoio**,
      no traspasse. São posições de trechos diferentes, mas que convivem ali
      -- e ali, na peça, elas estão lado a lado, nunca no mesmo ponto.

    Por isso as vagas são repartidas por ``(face, camada)`` ao longo de toda
    a viga, e não por trecho: conta-se quantas barras chegam a conviver na
    abscissa mais cheia, criam-se essas vagas, e cada posição toma vagas que
    nenhuma posição **que se sobreponha a ela em x** já tenha tomado. Onde as
    curtas já acabaram, as vagas delas ficam livres e o vão parece mais
    folgado -- que é o que acontece na peça.

    **Quem fica no canto**: a de maior bitola, como na seção transversal
    (``geometria.montar_secao``); entre bitolas iguais, a mais comprida. A
    segunda regra não existe na seção porque lá não há comprimento a comparar
    -- a seção é uma abscissa só. Aqui há: o escalonamento corta de dentro
    para fora e mantém as dos cantos até o apoio
    (``detalhamento.escalonar``), então é a barra comprida que ocupa o canto
    do estribo.
    """
    viga = res.viga
    cfg = viga.config
    trechos = viga.trechos
    grupos: dict[tuple, list] = {}
    for p in res.posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        grupos.setdefault((p.face, p.camada), []).append(p)

    def convivem(a, b) -> bool:
        """As duas posições existem juntas em alguma abscissa?"""
        return a[0] < b[1] - 1e-9 and b[0] < a[1] - 1e-9

    laterais: dict[int, list[float]] = {}
    for grupo in grupos.values():
        # quantas barras chegam a conviver na abscissa mais cheia
        cortes = sorted({p.x_ini for p in grupo} | {p.x_fim for p in grupo})
        n_vagas = 1
        for a, b in zip(cortes, cortes[1:]):
            meio = (a + b) / 2.0
            n_vagas = max(n_vagas, sum(
                max(p.n, 1) for p in grupo
                if p.x_ini - 1e-9 <= meio <= p.x_fim + 1e-9))
        # ordem de escolha das vagas: da borda para o meio, como na seção
        centro = (n_vagas - 1) / 2.0
        ordem = sorted(range(n_vagas),
                       key=lambda k: (-abs(k - centro), k))
        ocupacao: dict[int, list[tuple[float, float]]] = {}
        phi_max = max(p.phi for p in grupo)

        for p in sorted(grupo, key=lambda p: (-p.phi,
                                              -(p.x_fim - p.x_ini),
                                              p.numero)):
            faixa = (p.x_ini, p.x_fim)
            escolhidas = [v for v in ordem
                          if not any(convivem(faixa, ja)
                                     for ja in ocupacao.get(v, ()))]
            quantas = max(p.n, 1)
            if len(escolhidas) < quantas:
                # não deveria acontecer -- `n_vagas` é o máximo que convive --,
                # mas perder barra por causa da repartição seria pior que
                # repetir uma vaga: completa com as que faltam
                escolhidas += [v for v in ordem if v not in escolhidas]
            escolhidas = escolhidas[:quantas]
            for v in escolhidas:
                ocupacao.setdefault(v, []).append(faixa)

            # a geometria da vaga é a da seção DESTA posição: com seção
            # variável a largura muda de trecho para trecho, e a vaga k tem
            # de cair dentro do concreto que existe ali
            secao = trechos[al.trecho_da(viga, p)].secao
            recuo = cob + cfg.phi_estribo / 10.0 + phi_max / 20.0
            y0, y1 = recuo, secao.bw - recuo
            if n_vagas == 1:
                laterais[p.numero] = [(y0 + y1) / 2.0]
                continue
            passo = (y1 - y0) / (n_vagas - 1)
            laterais[p.numero] = sorted(y0 + v * passo for v in escolhidas)
    return laterais


def _texto_posicao(p, titulo: str, extra: str = "") -> str:
    """Mesma leitura da posição que a "Tabela de ferros" mostra -- os mesmos
    números, não uma segunda conta."""
    linhas = [
        f"{p.texto_quantidade}x Ø{p.phi:g} mm"
        + (f", c/{p.s:g} cm" if p.s else ""),
        f"Comprimento de corte: {p.comprimento:.0f} cm por barra "
        f"({p.comprimento_total:.2f} m e {p.massa:.2f} kg no total).",
    ]
    if p.descricao:
        linhas.append(p.descricao)
    if extra:
        linhas.append(extra)
    return "\n" + "\n".join(linhas)


# ---------------------------------------------------------------------------
# Cena
# ---------------------------------------------------------------------------

def construir_cena(plotter, res) -> dict[str, tuple[str, str]]:
    """Monta o concreto (por trecho) e todas as posições de armadura em
    ``plotter`` (qualquer ``pv.Plotter`` -- o de tela ou o de fora de
    tela).

    Devolve ``{nome_do_ator: (título, texto)}`` -- é o que a interação usa
    para saber o que mostrar quando o pick acerta um ator. A chave é o nome
    (string) passado a ``add_mesh``, não ``id(ator)``: o objeto que
    ``add_mesh`` devolve não fica retido em lugar nenhum além da variável
    local do laço, e o Python reaproveita o mesmo endereço de memória para o
    ator seguinte antes de o laço terminar -- quem chama precisa religar a
    chave ao ator de verdade depois, lendo ``plotter.renderer.actors``.

    O concreto não entra no dicionário: ``pickable`` fica ``False`` nele, de
    propósito, porque não é o que esta vista existe para explicar.
    """
    viga = res.viga
    cfg = viga.config
    cob = viga.ambiente.cobrimento_nominal
    trechos = viga.trechos
    bases_v = al.bases_verticais(viga)
    bases_l = al.bases_laterais(viga)
    comp_viga_cm = viga.comprimento * 100.0

    info: dict[str, tuple[str, str]] = {}
    laterais_na_largura = _laterais_por_posicao(res, cob)

    # -- concreto: um sólido por trecho, com o degrau na face do pilar -------
    lim_ini = [t.x_ini * 100.0 for t in trechos]
    lim_fim = [t.x_fim * 100.0 for t in trechos]
    for j in al.juntas(viga):
        lim_fim[j.trecho_esq] = j.x_face * 100.0
        lim_ini[j.trecho_dir] = j.x_face * 100.0
    for t in trechos:
        a, b = lim_ini[t.k], lim_fim[t.k]
        if b <= a + 1e-6:
            continue
        contorno = [(bases_l[t.k] + y, bases_v[t.k] + z)
                    for y, z in _contorno_secao(t.secao)]
        plotter.add_mesh(_solido(contorno, a, b), color=estilo.CONCRETO,
                         opacity=_OPACIDADE_CONCRETO, pickable=False,
                         name=f"concreto_{t.k}", smooth_shading=True)

    # -- longitudinais: flexão e porta-estribo -------------------------------
    for p in res.posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        z = bases_v[i_trecho] + _y_barra(secao, cob, cfg.phi_estribo, p.phi,
                                         p.camada, p.face, cfg.d_agregado)
        x0cm, x1cm = p.x_ini * 100.0, p.x_fim * 100.0
        sinal = 1.0 if p.face == "inferior" else -1.0
        tipo_gancho = p.tipo_gancho or gk.normalizar(cfg.tipo_gancho)
        raio_dobra = p.raio_da_dobra(viga.aco)
        pontos_xz = barra_com_dobras(x0cm, x1cm, z, p.dobra_ini, p.dobra_fim,
                                     sinal, raio_dobra, p.phi, tipo_gancho)

        # a largura é dividida entre TODAS as posições da mesma face, camada e
        # trecho -- ver `_laterais_por_posicao`
        laterais = laterais_na_largura.get(p.numero, [])
        cor = _cor_longitudinal(p)
        titulo = (f"N{p.numero} — "
                 f"{'Porta-estribo' if p.tipo == 'porta' else 'Armadura longitudinal'}"
                 f" ({p.face})")
        texto = _texto_posicao(p, titulo)
        pecas = []
        for y_lateral in laterais:
            y_global = bases_l[i_trecho] + y_lateral
            pecas.append(_tubo([(x, y_global, zz) for x, zz in pontos_xz],
                              _raio_barra(p.phi)))
        nome = f"long_{p.numero}"
        plotter.add_mesh(_juntar(pecas), color=cor, name=nome,
                         smooth_shading=True)
        info[nome] = (titulo, texto)

    # -- porta-estribos dos cantos do laço da mesa --------------------------
    for p in res.posicoes:
        if p.tipo != "porta_mesa":
            continue
        i_trecho = al.trecho_da(viga, p)
        cantos = cantos_da_mesa(trechos[i_trecho].secao, cob, p.phi)
        if not cantos:
            continue
        x0cm, x1cm = p.x_ini * 100.0, p.x_fim * 100.0
        titulo = f"N{p.numero} — Porta-estribo dos cantos da mesa"
        texto = _texto_posicao(p, titulo)
        pecas = [_tubo([(x0cm, bases_l[i_trecho] + cy,
                        bases_v[i_trecho] + cz),
                       (x1cm, bases_l[i_trecho] + cy,
                        bases_v[i_trecho] + cz)], _raio_barra(p.phi))
                for cy, cz in cantos]
        nome = f"long_{p.numero}"
        plotter.add_mesh(_juntar(pecas), color=_COR_CONSTRUTIVA, name=nome,
                         smooth_shading=True)
        info[nome] = (titulo, texto)

    # -- pele: duas faces laterais fixas, espalhada na altura da alma -------
    for p in res.posicoes:
        if p.tipo != "pele":
            continue
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        y0z, y1z = p.faixa_altura
        if not any(p.faixa_altura):
            y0z, y1z = cob + 10.0, secao.h - cob - 10.0
        n_face = max(p.n // 2, 1)
        x0cm, x1cm = p.x_ini * 100.0, p.x_fim * 100.0
        titulo = f"N{p.numero} — Armadura lateral (pele/torção)"
        texto = _texto_posicao(p, titulo)
        pecas = []
        for k in range(n_face):
            z_local = y0z + (y1z - y0z) * (k / max(n_face - 1, 1))
            z_global = bases_v[i_trecho] + z_local
            pontos_xz = barra_com_dobras(
                x0cm, x1cm, z_global, p.dobra_ini, p.dobra_fim, 1.0, 0.0)
            for lado in (cob + 1.0, secao.bw - cob - 1.0):
                y_global = bases_l[i_trecho] + lado
                pecas.append(_tubo([(x, y_global, zz) for x, zz in pontos_xz],
                                  _raio_barra(p.phi)))
        nome = f"pele_{p.numero}"
        plotter.add_mesh(_juntar(pecas), color=_rgb(estilo.LARANJA),
                         name=nome, smooth_shading=True)
        info[nome] = (titulo, texto)

    # -- estribos, a distribuição real do tramo (res.zonas_estribo) ---------
    cor_estribo = _rgb(estilo.VERDE)
    for z in res.zonas_estribo:
        n = max(2, z.n_estribos)
        x0cm, x1cm = z.x_ini * 100.0, z.x_fim * 100.0
        passo = (x1cm - x0cm) / max(n - 1, 1)
        titulo = f"Estribo Ø{z.phi:g} c/{z.s:g} — tramo {z.tramo + 1}"
        texto = (f"\n{z.n_ramos} ramos, Asw/s necessária "
                f"{z.asw_req:.2f} cm²/m, efetiva {z.asw_ef:.2f} cm²/m.")
        pecas = []
        for k in range(n):
            xcm = x0cm + k * passo
            i_tr = al.trecho_em(viga, xcm / 100.0)
            secao = trechos[i_tr].secao
            raio_est = (viga.aco.diametro_dobramento_estribo(z.phi) / 2.0
                       + z.phi / 20.0)
            gancho = 0.0 if not cfg.gancho_estribo else max(
                5.0 * z.phi / 10.0, 5.0)
            local = retangulo_arredondado(secao.bw - 2.0 * cob,
                                          secao.h - 2.0 * cob, raio_est,
                                          gancho)
            pecas.append(_tubo(
                [(xcm, bases_l[i_tr] + cob + u, bases_v[i_tr] + cob + v)
                 for u, v in local], _raio_barra(z.phi)))
        nome = f"estribo_{z.tramo}_{z.trecho}_{z.x_ini:.2f}"
        plotter.add_mesh(_juntar(pecas), color=cor_estribo, name=nome,
                         smooth_shading=True)
        info[nome] = (titulo, texto)

        # o laço que abraça a MESA, na mesma bitola e no mesmo espaçamento --
        # a segunda peça do estribo da seção T
        secao_z = trechos[min(z.trecho, len(trechos) - 1)].secao
        if secao_z.tipo == "retangular" or secao_z.bf <= secao_z.bw + 1e-9:
            continue
        y_laco, z_laco, y1_laco, z1_laco = laco_da_mesa(secao_z, cob)
        raio_est = (viga.aco.diametro_dobramento_estribo(z.phi) / 2.0
                   + z.phi / 20.0)
        gancho = 0.0 if not cfg.gancho_estribo else max(5.0 * z.phi / 10.0,
                                                        5.0)
        local = retangulo_arredondado(y1_laco - y_laco,
                                      z1_laco - z_laco, raio_est,
                                      gancho)
        pecas_mesa = []
        for k in range(n):
            xcm = x0cm + k * passo
            i_tr = al.trecho_em(viga, xcm / 100.0)
            pecas_mesa.append(_tubo(
                [(xcm, bases_l[i_tr] + y_laco + u,
                  bases_v[i_tr] + z_laco + v) for u, v in local],
                _raio_barra(z.phi)))
        nome = f"estribomesa_{z.tramo}_{z.trecho}_{z.x_ini:.2f}"
        plotter.add_mesh(_juntar(pecas_mesa), color=cor_estribo, name=nome,
                         smooth_shading=True)
        info[nome] = (
            f"Estribo da MESA Ø{z.phi:g} c/{z.s:g} — tramo {z.tramo + 1}",
            f"\nLaço de {secao_z.bf:g}x{secao_z.hf:g} cm abraçando a mesa, "
            f"na bitola e no espaçamento do estribo da alma.\nAtravessa o "
            f"plano de ligação mesa-alma com os dois ramos verticais "
            f"(18.3.7).")

    # -- costura e suspensão: mesmo laço fechado do estribo, na posição das
    # suas próprias faixas (elas não têm zona em res.zonas_estribo -- são
    # armadura suplementar, não a distribuição principal do tramo)
    for p in res.posicoes:
        if p.tipo not in ("costura", "suspensao"):
            continue
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        raio_est = (viga.aco.diametro_dobramento_estribo(p.phi) / 2.0
                   + p.phi / 20.0)
        gancho = 0.0 if not cfg.gancho_estribo else max(5.0 * p.phi / 10.0,
                                                        5.0)
        titulo = ("N%d — %s" % (
            p.numero, "Costura de emenda" if p.tipo == "costura"
            else "Suspensão"))
        texto = _texto_posicao(p, titulo)
        local = retangulo_arredondado(secao.bw - 2.0 * cob,
                                      secao.h - 2.0 * cob, raio_est, gancho)
        pecas = []
        for xa, xb, _esp, quantos in (p.faixas or
                                      [(p.x_ini, p.x_fim, p.s, p.n)]):
            n = max(1, quantos)
            xa_cm, xb_cm = xa * 100.0, xb * 100.0
            passo = (xb_cm - xa_cm) / max(n - 1, 1) if n > 1 else 0.0
            for k in range(n):
                xcm = xa_cm + (k * passo if n > 1 else (xb_cm - xa_cm) / 2.0)
                pecas.append(_tubo(
                    [(xcm, bases_l[i_trecho] + cob + u,
                      bases_v[i_trecho] + cob + v) for u, v in local],
                    _raio_barra(p.phi)))
        nome = f"transv_{p.numero}"
        plotter.add_mesh(_juntar(pecas), color=cor_estribo, name=nome,
                         smooth_shading=True)
        info[nome] = (titulo, texto)

    # -- ligação mesa-alma: barra reta atravessando a alma até a mesa -------
    for p in res.posicoes:
        if p.tipo != "ligacao":
            continue
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        # a barra corre na altura da junção mesa/alma: no topo da alma para
        # a mesa em cima (T), na base dela para a mesa embaixo (T invertida)
        z_local = secao.h - secao.hf if secao.tipo == "T" else secao.hf
        z_global = bases_v[i_trecho] + z_local
        titulo = f"N{p.numero} — Ligação mesa-alma"
        texto = _texto_posicao(p, titulo)
        pecas = []
        for xa, xb, _esp, quantos in (p.faixas or
                                      [(p.x_ini, p.x_fim, p.s, p.n)]):
            n = max(1, quantos)
            xa_cm, xb_cm = xa * 100.0, xb * 100.0
            passo = (xb_cm - xa_cm) / max(n - 1, 1) if n > 1 else 0.0
            for k in range(n):
                xcm = xa_cm + (k * passo if n > 1 else (xb_cm - xa_cm) / 2.0)
                pecas.append(_tubo(
                    [(xcm, bases_l[i_trecho], z_global),
                     (xcm, bases_l[i_trecho] + p.comprimento, z_global)],
                    _raio_barra(p.phi)))
        nome = f"ligacao_{p.numero}"
        plotter.add_mesh(_juntar(pecas), color=cor_estribo, name=nome,
                         smooth_shading=True)
        info[nome] = (titulo, texto)

    # -- grampos de ancoragem e de costura -----------------------------------
    for p in res.posicoes:
        if p.tipo != "grampo":
            continue
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        x0cm, x1cm = p.x_ini * 100.0, p.x_fim * 100.0
        # a dobra que fecha o U fica na extremidade da viga -- o lado de
        # x0/x1 mais perto de uma delas -- e a abertura aponta para o vão,
        # a mesma regra que geometria.montar_elevacao usa para o traço
        externo = x0cm if abs(x0cm) < abs(comp_viga_cm - x1cm) else x1cm
        interno = x1cm if externo == x0cm else x0cm
        perna = p.perna or (p.comprimento / 2.0)
        vao = max(p.comprimento - 2.0 * perna, 2.0)
        raio_est = (viga.aco.diametro_dobramento_estribo(p.phi) / 2.0
                   + p.phi / 20.0)
        local = grampo_em_u(perna, vao, raio_est, espelhado=False)
        sinal_x = 1.0 if interno >= externo else -1.0
        titulo = ("N%d — Grampo de %s" % (
            p.numero, "ancoragem" if p.papel == "ancoragem" else "costura"))
        texto = _texto_posicao(p, titulo)
        if p.papel == "ancoragem":
            y_ini, y_fim = _parte_reta_do_gancho(res, x0cm, x1cm, cob,
                                                 bases_v[i_trecho])
            alturas = ([y_ini + (k + 1) / (p.n + 1) * (y_fim - y_ini)
                       for k in range(p.n)] if y_fim > y_ini + 1e-6 else
                      [bases_v[i_trecho] + _y_barra(
                          secao, cob, cfg.phi_estribo, p.phi, 1, "inferior",
                          cfg.d_agregado)])
        else:
            alturas = [bases_v[i_trecho] + _y_barra(
                secao, cob, cfg.phi_estribo, p.phi, 1, "inferior",
                cfg.d_agregado)]
        pecas = [_tubo([(externo + sinal_x * u, bases_l[i_trecho] + cob + v,
                        z_global) for u, v in local], _raio_barra(p.phi))
                for z_global in alturas]
        nome = f"grampo_{p.numero}"
        plotter.add_mesh(_juntar(pecas), color=cor_estribo, name=nome,
                         smooth_shading=True)
        info[nome] = (titulo, texto)

    plotter.set_background("white")
    return info


def _posicionar_camera(plotter, res) -> None:
    """Câmera em 3/4, enquadrando a viga inteira.

    A direção é fixa -- de frente, de cima e de lado, com a viga correndo na
    diagonal da tela --, mas a **distância** é do ``reset_camera``, que mede a
    cena montada. Arbitrar a distância a partir do comprimento da viga (o que
    a primeira versão fazia) cortava as pontas assim que a seção era alta ou a
    janela tinha outra proporção: quem sabe o que cabe no quadro é quem
    conhece o quadro.
    """
    foco = np.array(plotter.bounds).reshape(3, 2).mean(axis=1)
    direcao = np.array([-0.45, -1.0, 0.45])
    direcao = direcao / np.linalg.norm(direcao)
    plotter.camera_position = [tuple(foco + direcao), tuple(foco),
                               (0.0, 0.0, 1.0)]
    plotter.reset_camera()
    # o `reset_camera` enquadra a ESFERA que contém a cena, o que sobra muito
    # numa peça longa e fina: uma viga de 12 m fica do tamanho de um risco no
    # meio do branco. O fator foi calibrado no olho, com a viga da garagem
    # (12,5 m em 940x560), para encher o quadro ainda deixando margem
    plotter.camera.zoom(1.4)


#: o que a legenda da janela interativa diz enquanto nada está apontado
_MENSAGEM_PADRAO = (
    "Gire com o botão esquerdo, aproxime com a roda do mouse.\n"
    "Passe sobre uma armadura para identificá-la — a posição inteira\n"
    "acende junto — ou clique para fixar a explicação.")


# ---------------------------------------------------------------------------
# Saída 1: imagem fora de tela, para a aba
# ---------------------------------------------------------------------------

def renderizar_png(res, caminho: str, tamanho=(900, 620),
                   fundo: str = "white") -> str:
    """Renderiza a cena FORA DE TELA num PNG, e devolve o caminho.

    É o que a aba "Vista 3D" mostra. Fora de tela não há janela nem contexto
    a dividir com o Qt: o VTK abre o próprio buffer, desenha e fecha. Serve
    também ao ``--autoteste``, que roda sem interface nenhuma.
    """
    plotter = pv.Plotter(off_screen=True, window_size=list(tamanho))
    plotter.set_background(fundo)
    try:
        construir_cena(plotter, res)
        _posicionar_camera(plotter, res)
        plotter.screenshot(caminho, return_img=False)
    finally:
        plotter.close()
    return caminho


# ---------------------------------------------------------------------------
# Saída 2: janela interativa, com destaque por posição
# ---------------------------------------------------------------------------

class VistaInterativa:
    """Janela própria do VTK, com pick por posição.

    Sem Qt no caminho: é o que faz a interação ser fluida mesmo com centenas
    de barras -- ver a nota no topo do módulo.
    """

    def __init__(self, res, titulo: str = "Vista 3D da viga") -> None:
        self.plotter = pv.Plotter(title=titulo, window_size=[1180, 820])
        self.plotter.set_background("white")
        info_por_nome = construir_cena(self.plotter, res)

        self._info: dict = {}
        self._cor_original: dict = {}
        self._atores: list = []
        for nome, ator in self.plotter.renderer.actors.items():
            if nome in info_por_nome:
                self._info[ator] = info_por_nome[nome]
                self._cor_original[ator] = ator.GetProperty().GetColor()
                self._atores.append(ator)
        self._concreto = [a for nome, a in self.plotter.renderer.actors.items()
                          if nome not in info_por_nome]
        self._atual = None
        self._fixado = False
        self._legenda = self.plotter.add_text(
            _MENSAGEM_PADRAO, position="upper_left", font_size=9,
            color=estilo.CINZA, name="legenda_3d")

        from vtkmodules.vtkRenderingCore import vtkCellPicker
        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.002)
        self.plotter.iren.add_observer("MouseMoveEvent", self._ao_mover)
        self.plotter.iren.add_observer("LeftButtonPressEvent", self._ao_clicar)
        _posicionar_camera(self.plotter, res)

    # -- interação ----------------------------------------------------------
    def _ator_sob_o_mouse(self):
        x, y = self.plotter.iren.get_event_position()
        self._picker.Pick(x, y, 0, self.plotter.renderer)
        ator = self._picker.GetActor()
        return ator if ator is not None and ator in self._info else None

    def _destacar(self, ator) -> None:
        """Acende a posição apontada e apaga o resto, o concreto inclusive.

        É o contraste, e não a cor sozinha, que faz a peça certa saltar aos
        olhos no meio de dezenas de tubos parecidos.
        """
        for outro in self._atores:
            prop = outro.GetProperty()
            if outro is ator:
                prop.SetColor(*_AMBAR)
                prop.SetOpacity(1.0)
            else:
                prop.SetOpacity(_OPACIDADE_APAGADA)
        for c in self._concreto:
            c.GetProperty().SetOpacity(_OPACIDADE_CONCRETO_APAGADO)

    def _limpar_destaque(self) -> None:
        for ator in self._atores:
            prop = ator.GetProperty()
            cor = self._cor_original.get(ator)
            if cor is not None:
                prop.SetColor(*cor)
            prop.SetOpacity(1.0)
        for c in self._concreto:
            c.GetProperty().SetOpacity(_OPACIDADE_CONCRETO)

    def _mostrar_info(self, ator) -> None:
        if self._legenda is None:
            return
        if ator is None:
            self._legenda.set_text("upper_left", _MENSAGEM_PADRAO)
            return
        titulo, texto = self._info[ator]
        prefixo = "[fixado] " if self._fixado else ""
        self._legenda.set_text("upper_left", f"{prefixo}{titulo}\n{texto}")

    def _render(self) -> None:
        try:
            self.plotter.render()
        except Exception:                                # noqa: BLE001
            pass                                         # sem janela nativa

    def _ao_mover(self, _caller, _evento) -> None:
        if self._fixado:
            return
        ator = self._ator_sob_o_mouse()
        if ator is self._atual:
            return
        self._atual = ator
        if ator is not None:
            self._destacar(ator)
        else:
            self._limpar_destaque()
        self._mostrar_info(ator)
        self._render()

    def _ao_clicar(self, _caller, _evento) -> None:
        ator = self._ator_sob_o_mouse()
        if ator is None:
            if self._fixado:
                self._fixado = False
                self._atual = None
                self._limpar_destaque()
                self._mostrar_info(None)
                self._render()
            return
        if self._fixado and ator is self._atual:
            self._fixado = False
            self._limpar_destaque()
            self._mostrar_info(None)
        else:
            self._fixado = True
            self._atual = ator
            self._destacar(ator)
            self._mostrar_info(ator)
        self._render()

    def mostrar(self) -> None:
        self.plotter.show()


def abrir_vista_interativa(res, titulo: str = "Vista 3D da viga") -> None:
    """Abre a janela interativa. Bloqueia até o usuário fechá-la, como um
    diálogo modal -- é o comportamento de ``Plotter.show``, e o mesmo do
    programa de Sapatas de onde esta metodologia veio."""
    VistaInterativa(res, titulo=titulo).mostrar()
