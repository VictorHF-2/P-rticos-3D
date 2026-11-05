# -*- coding: utf-8 -*-
"""
vista3d.py
Vista 3D do pavimento detalhado em PyVista/VTK: a laje e a viga de cada
bordo com apoio como sólidos translúcidos, e cada posição de armadura como
tubo, com o gancho a 90° no comprimento real que o detalhamento calculou.

METODOLOGIA portada do programa de Vigas (``vigas/saidas/vista3d.py``, que
por sua vez a copiou do programa de Sapatas), depois de a primeira tentativa
da casa -- um ``pyvistaqt.QtInteractor`` embutido numa aba (Consolos R03) --
se mostrar lenta demais para interação fluida. São duas peças, e é a
separação entre elas que faz a interação ser rápida:

1. **a aba mostra uma imagem** (:func:`renderizar_png`), renderizada fora de
   tela: estática, barata, e disponível até no ``--autoteste``, que roda sem
   janela nenhuma;
2. **a interação vive numa janela própria do VTK**
   (:func:`abrir_vista_interativa`), aberta por um botão. Sem ``QOpenGLWidget``
   do Qt no caminho não há o ciclo de repintura dele nem o render duplicado
   por evento de mouse que ``pyvistaqt`` impõe -- é isso que resolve o
   travamento, não a geometria.

O módulo é **puro de Qt**: quem embute a imagem e quem chama o botão é
``lajes/ui/janela.py``. É isso que permite o ``--autoteste`` exercitar a
vista inteira sem interface.

**Um ator por posição, não por barra física.** As barras de uma mesma
posição têm a mesma bitola, o mesmo comprimento e o mesmo gancho: fundidas
numa malha só (:func:`_juntar`), apontar qualquer uma acende a posição
inteira -- que é o que se decide em projeto, ninguém detalha a sétima barra
de N3, detalha N3.

**A cor segue a face, não o tipo** -- a mesma inversão proposital já
adotada na vista estática que esta substitui: superior (negativa, contorno,
continuidade) em vermelho, inferior (positiva, distribuição) em azul.
Olhando um modelo em pé, é a posição na espessura que salta aos olhos
primeiro, não o nome da armadura -- ver ``lajes/saidas/estilo.py``.

**O gancho é físico, não esquemático.** A planta 2D (``desenho.py``) desenha
o gancho como um traço perpendicular *no plano da planta* -- uma convenção
de legibilidade, porque uma dobra vertical vista de cima seria só um ponto.
Aqui, em 3D, a dobra é a de verdade: **vertical**, no comprimento exato que
o detalhamento calculou (``pos.gancho_inicio``/``gancho_fim``, o mesmo h−2c
construtivo da negativa ou a ponta de ancoragem da positiva -- nunca um
valor inventado para o desenho). A direção adotada -- negativa dobra para
**baixo**, positiva dobra para **cima**, ambas em direção ao meio da
espessura -- é a convenção usual de ancoragem no apoio (a barra dobra para
dentro da viga, não para fora da laje); não há tabela de raio de dobra para
laje na apostila nem na NBR 6118 aplicada aqui, então o raio da concordância
é só **decorativo** (proporcional à bitola, não normativo) -- sem ele a
dobra sairia em aresta viva, que lê mal num tubo 3D.

**A viga é a mesma faixa das plantas de vinculação**, extrudada para baixo:
mesma largura ``t`` e mesma posição (centrada no bordo, ``t/2`` embutido sob
a laje e ``t/2`` para fora -- ver ``graficos._vigas``), com o topo rente ao
fundo da laje (``z = 0``) descendo ``h_viga`` -- um campo novo em
:class:`~lajes.core.modelo.Bordo`, ao lado de ``t``, que **não entra em
nenhum cálculo**: é só a altura que o usuário escolhe para a viga aparecer
no modelo, e sozinha não muda vão efetivo, ancoragem nem esforço nenhum. Só
o bordo livre fica sem viga -- a mesma regra da planta.
"""

from __future__ import annotations

import math

import numpy as np
import pyvista as pv

from . import estilo
from .desenho import MAXIMO_BARRAS, _barras

#: Raio mínimo do tubo de armadura, m -- metade da bitola já dá um tubo fino
#: mas visível; abaixo desse piso um Ø5 ficaria fino demais para o mouse
#: acertar.
_RAIO_MINIMO_M = 0.003

#: Opacidade de quem NÃO está em destaque, e a da laje e da viga, que são
#: moldura e não assunto.
_OPACIDADE_APAGADA = 0.15
_OPACIDADE_MOLDURA = 0.28
_OPACIDADE_MOLDURA_APAGADA = 0.06

#: Cor de destaque -- âmbar, a mesma semântica de "atenção" do resto da casa.
_AMBAR = (0.69, 0.49, 0.11)

#: Segmentos da concordância do gancho -- decorativo, ver docstring do
#: módulo; 8 já fica liso num tubo deste raio.
_SEGMENTOS_DOBRA = 8


def _rgb(cor_hex: str) -> tuple[float, float, float]:
    """``"#RRGGBB"`` -> ``(r, g, b)`` em [0, 1], o que ``add_mesh`` espera."""
    cor_hex = cor_hex.lstrip("#")
    return tuple(int(cor_hex[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _raio_barra(phi_mm: float) -> float:
    """Raio do tubo, em metros, a partir da bitola em mm."""
    return max(phi_mm / 2000.0, _RAIO_MINIMO_M)


def _cor_face(face: str) -> tuple[float, float, float]:
    return _rgb(estilo.VERMELHO if face == "superior" else estilo.AZUL)


def _n(valor, casas: int = 2) -> str:
    """Formata em padrão brasileiro -- vírgula decimal, sem depender da UI."""
    try:
        return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",") \
            .replace("@", ".")
    except (TypeError, ValueError):
        return str(valor)


def _quina(p: np.ndarray, d_in: np.ndarray, d_out: np.ndarray, raio: float,
          segmentos: int = _SEGMENTOS_DOBRA) -> list[np.ndarray]:
    """Pontos que arredondam, com um arco de ``raio``, o encontro de duas
    retas em ``p`` -- uma chegando na direção ``d_in``, outra saindo na
    direção ``d_out``. Só cobre o caso de 90° entre elas, que é o único que
    o gancho da laje usa (ver docstring do módulo). Validado num script
    isolado (dois casos: negativa com gancho nas duas pontas, positiva com
    gancho numa só) antes de entrar aqui.
    """
    d_in = d_in / np.linalg.norm(d_in)
    d_out = d_out / np.linalg.norm(d_out)
    centro = p - raio * d_in + raio * d_out
    pontos = []
    for k in range(segmentos + 1):
        ang = (k / segmentos) * (math.pi / 2.0)
        pontos.append(centro + raio * math.cos(ang) * (-d_out)
                      + raio * math.sin(ang) * d_in)
    return pontos


def _eixo_hat(eixo: str) -> np.ndarray:
    return np.array([1.0, 0.0, 0.0] if eixo == "X" else [0.0, 1.0, 0.0])


def _ponto(eixo: str, ao_longo: float, transversal: float,
          z: float) -> np.ndarray:
    if eixo == "X":
        return np.array([ao_longo, transversal, z])
    return np.array([transversal, ao_longo, z])


def _pontos_barra(eixo: str, x0: float, x1: float, c: float, z: float,
                  gancho_ini: float, gancho_fim: float, dz: float,
                  raio_dobra: float) -> np.ndarray:
    """Polilinha (x, y, z), em metros, de uma barra ao longo de ``eixo``,
    na cota transversal ``c`` e na altura ``z`` da face, com o gancho de
    cada ponta (0 = sem gancho) dobrando na direção ``dz`` (+1 sobe,
    -1 desce -- ver docstring do módulo)."""
    hat = _eixo_hat(eixo)
    p_ini, p_fim = _ponto(eixo, x0, c, z), _ponto(eixo, x1, c, z)
    pontos: list[np.ndarray] = []

    if gancho_ini > 1e-6:
        raio = min(raio_dobra, gancho_ini * 0.8)
        ponta = p_ini.copy()
        ponta[2] = z + dz * gancho_ini
        pontos.append(ponta)
        pontos += _quina(p_ini, np.array([0.0, 0.0, -dz]), hat, raio)
    else:
        pontos.append(p_ini)

    if gancho_fim > 1e-6:
        raio = min(raio_dobra, gancho_fim * 0.8)
        pontos += _quina(p_fim, hat, np.array([0.0, 0.0, dz]), raio)
        ponta = p_fim.copy()
        ponta[2] = z + dz * gancho_fim
        pontos.append(ponta)
    else:
        pontos.append(p_fim)
    return np.array(pontos)


def _tubo(pontos: np.ndarray, raio: float) -> pv.PolyData:
    linha = pv.MultipleLines(points=pontos)
    return linha.tube(radius=raio)


def _juntar(pecas: list[pv.PolyData]) -> pv.PolyData:
    """Funde as barras de uma posição numa malha só -- ver docstring do
    módulo: um ator por posição, não por barra física."""
    return pecas[0] if len(pecas) == 1 else pv.merge(pecas)


def _texto_posicao(p, titulo: str) -> str:
    """Os mesmos números da tabela de posições e do quantitativo -- não uma
    segunda conta."""
    linhas = [
        f"{p.quantidade}x Ø{p.phi:g} mm"
        + (f", c/{p.espacamento:g} cm" if p.espacamento else ""),
        f"Comprimento de corte: {p.comprimento:.0f} cm por barra "
        f"({_n(p.comprimento_total, 2)} m e {_n(p.massa, 2)} kg no "
        f"total).",
    ]
    if p.tem_gancho:
        partes = []
        if p.gancho_inicio > 0.0:
            partes.append(f"início {p.gancho_inicio:.0f} cm")
        if p.gancho_fim > 0.0:
            partes.append(f"fim {p.gancho_fim:.0f} cm")
        linhas.append("Gancho a 90°: " + ", ".join(partes) + ".")
    if p.rotulo:
        linhas.append(p.rotulo)
    if p.observacoes:
        linhas.append(" ".join(p.observacoes))
    return "\n" + "\n".join(linhas)


def _pecas_da_posicao(res, pos, laje) -> tuple[list[pv.PolyData], float]:
    """As barras (já como tubos) de uma posição, na laje em que ela nasceu.

    A cota z da face vem do cobrimento de verdade -- o nominal embaixo, o de
    cada bitola em cima (7.4.7.5), a mesma regra da vista estática que esta
    substitui. A direção do gancho segue a face (docstring do módulo).
    """
    amb = res.pavimento.ambiente
    h_m = laje.h / 100.0
    if pos.face == "inferior":
        c_m = amb.cobrimento_nominal / 100.0
        z = min(c_m, h_m * 0.4)
        dz = 1.0
    else:
        c_m = amb.cobrimento_superior(pos.phi) / 100.0
        z = max(h_m - c_m, h_m * 0.6)
        dz = -1.0

    raio_barra = _raio_barra(pos.phi)
    raio_dobra = max(2.0 * pos.phi / 1000.0, 0.01)
    coords = _barras(pos)
    salto = max(1, math.ceil(len(coords) / MAXIMO_BARRAS))
    pecas = []
    for c_cm in coords[::salto]:
        pontos = _pontos_barra(
            pos.eixo, pos.inicio / 100.0, pos.fim / 100.0, c_cm / 100.0, z,
            pos.gancho_inicio / 100.0, pos.gancho_fim / 100.0, dz,
            raio_dobra)
        pecas.append(_tubo(pontos, raio_barra))
    return pecas, h_m


def _caixa_da_viga(laje, bordo: int
                   ) -> tuple[float, float, float, float, float, float] | None:
    """Bounds ``(x0, x1, y0, y1, z0, z1)`` da viga de um bordo, em metros --
    ``None`` quando o bordo não tem viga (livre) ou ``t`` está zerado.

    A faixa em planta é a mesma de ``graficos._vigas`` -- centrada na linha
    do bordo, ``t/2`` para dentro, ``t/2`` para fora --, só extrudada para
    baixo a partir do fundo da laje (ver docstring do módulo)."""
    b = laje.bordos[bordo - 1]
    if b.vinculo == "livre":
        return None
    t = b.t / 100.0
    if t <= 0.0:
        return None
    h_viga = b.h_viga / 100.0
    bx0, by0, bx1, by1 = laje.segmento_do_bordo(bordo)
    vertical = abs(bx1 - bx0) < 1e-9
    if vertical:
        x0, x1, y0, y1 = bx0 - t / 2.0, bx0 + t / 2.0, by0, by1
    else:
        x0, x1, y0, y1 = bx0, bx1, by0 - t / 2.0, by0 + t / 2.0
    return (x0, x1, y0, y1, -h_viga, 0.0)


# ---------------------------------------------------------------------------
# Cena
# ---------------------------------------------------------------------------

#: Cor da laje de cada sistema (a maciça é a do concreto).
_COR_TIPO = {"trelicada": estilo.LARANJA_CLARO, "alveolar": estilo.VERDE_CLARO,
             "nervurada_uni": estilo.AZUL_CLARO, "nervurada_bi": "#cfc2e0"}


def _lajes_especiais(plotter, res) -> None:
    """As lajes treliçadas, alveolares e nervuradas da planta, como caixas
    translúcidas na cor do sistema, com a viga de cada bordo apoiado -- a
    armadura delas não entra no modelo (está nas tabelas e na memória)."""
    for e in getattr(res, "especiais", []):
        for nome in e.lajes:
            laje = res.pavimento.laje(nome)
            if laje is None:
                continue
            x0, y0, x1, y1 = laje.retangulo
            plotter.add_mesh(
                pv.Box(bounds=(x0, x1, y0, y1, 0.0, laje.h / 100.0)),
                color=_COR_TIPO[laje.tipo], opacity=_OPACIDADE_MOLDURA,
                pickable=False, name=f"laje_{laje.nome}",
                smooth_shading=True)
            for bordo in (1, 2, 3, 4):
                bounds = _caixa_da_viga(laje, bordo)
                if bounds is None:
                    continue
                plotter.add_mesh(pv.Box(bounds=bounds),
                                 color=estilo.CONCRETO,
                                 opacity=_OPACIDADE_MOLDURA, pickable=False,
                                 name=f"viga_{laje.nome}_{bordo}",
                                 smooth_shading=True)


def construir_cena(plotter, res) -> dict[str, tuple[str, str]]:
    """Monta a laje (por painel) e todas as posições de armadura em
    ``plotter`` (qualquer ``pv.Plotter`` -- o de tela ou o de fora de tela).

    Devolve ``{nome_do_ator: (título, texto)}`` -- o que a interação usa
    para saber o que mostrar quando o pick acerta um ator. A chave é o nome
    (string) passado a ``add_mesh``, não ``id(ator)``: o objeto que
    ``add_mesh`` devolve não fica retido em lugar nenhum além da variável
    local do laço, e o Python reaproveita o mesmo endereço de memória para o
    ator seguinte antes de o laço terminar -- quem chama religa a chave ao
    ator de verdade lendo ``plotter.renderer.actors`` depois.

    A laje e a viga não entram no dicionário: ``pickable=False``, de
    propósito, porque não é o que esta vista existe para explicar.
    """
    info: dict[str, tuple[str, str]] = {}

    for rl in res.lajes:
        laje = rl.laje
        x0, y0, x1, y1 = laje.retangulo
        h_m = laje.h / 100.0
        caixa = pv.Box(bounds=(x0, x1, y0, y1, 0.0, h_m))
        plotter.add_mesh(caixa, color=estilo.CONCRETO,
                         opacity=_OPACIDADE_MOLDURA, pickable=False,
                         name=f"laje_{laje.nome}", smooth_shading=True)

        for bordo in (1, 2, 3, 4):
            bounds = _caixa_da_viga(laje, bordo)
            if bounds is None:
                continue
            caixa_viga = pv.Box(bounds=bounds)
            plotter.add_mesh(caixa_viga, color=estilo.CONCRETO,
                             opacity=_OPACIDADE_MOLDURA, pickable=False,
                             name=f"viga_{laje.nome}_{bordo}",
                             smooth_shading=True)

        for pos in rl.posicoes:
            pecas, _ = _pecas_da_posicao(res, pos, laje)
            if not pecas:
                continue
            titulo = f"N{pos.numero} — {pos.laje}, face {pos.face}"
            nome = f"pos_{pos.numero}_{pos.laje}"
            plotter.add_mesh(_juntar(pecas), color=_cor_face(pos.face),
                             name=nome, smooth_shading=True)
            info[nome] = (titulo, _texto_posicao(pos, titulo))

    _lajes_especiais(plotter, res)

    # continuidade: atravessa a borda comum entre duas lajes -- a cota z usa
    # a laje mais fina das duas, para o gancho não furar o painel vizinho
    laje_por_nome = {rl.laje.nome: rl.laje for rl in res.lajes}
    for pos in res.posicoes_continuidade:
        nomes = [n.strip() for n in pos.laje.split(" / ")]
        lajes_vizinhas = [laje_por_nome[n] for n in nomes
                          if n in laje_por_nome]
        if not lajes_vizinhas:
            continue
        laje_fina = min(lajes_vizinhas, key=lambda lj: lj.h)
        pecas, _ = _pecas_da_posicao(res, pos, laje_fina)
        if not pecas:
            continue
        titulo = f"N{pos.numero} — continuidade {pos.laje}"
        nome = f"pos_{pos.numero}_cont"
        plotter.add_mesh(_juntar(pecas), color=_cor_face(pos.face),
                         name=nome, smooth_shading=True)
        info[nome] = (titulo, _texto_posicao(pos, titulo))

    plotter.set_background("white")
    return info


def _posicionar_camera(plotter) -> None:
    """Câmera em 3/4, de cima, enquadrando o pavimento inteiro.

    A direção é fixa; a distância vem do ``reset_camera``, que mede a cena
    montada -- arbitrar pela maior dimensão do pavimento cortaria as pontas
    num painel muito alongado ou numa tela de outra proporção.
    """
    foco = np.array(plotter.bounds).reshape(3, 2).mean(axis=1)
    direcao = np.array([-0.55, -0.85, 0.75])
    direcao = direcao / np.linalg.norm(direcao)
    plotter.camera_position = [tuple(foco + direcao), tuple(foco),
                               (0.0, 0.0, 1.0)]
    plotter.reset_camera()
    plotter.camera.zoom(1.25)


#: o que a legenda da janela interativa diz enquanto nada está apontado
_MENSAGEM_PADRAO = (
    "Gire com o botão esquerdo, aproxime com a roda do mouse.\n"
    "Passe sobre uma armadura para identificá-la — a posição inteira\n"
    "acende junto — ou clique para fixar a explicação."
)


# ---------------------------------------------------------------------------
# Saída 1: imagem fora de tela, para a aba
# ---------------------------------------------------------------------------

def renderizar_png(res, caminho: str, tamanho=(900, 620),
                   fundo: str = "white") -> str:
    """Renderiza a cena FORA DE TELA num PNG, e devolve o caminho.

    É o que a aba "Modelo 3D" mostra. Fora de tela não há janela nem
    contexto a dividir com o Qt: o VTK abre o próprio buffer, desenha e
    fecha -- funciona até no ``--autoteste``, que roda sem interface
    nenhuma.
    """
    plotter = pv.Plotter(off_screen=True, window_size=list(tamanho))
    plotter.set_background(fundo)
    try:
        construir_cena(plotter, res)
        _posicionar_camera(plotter)
        plotter.screenshot(caminho, return_img=False)
    finally:
        plotter.close()
    return caminho


# ---------------------------------------------------------------------------
# Saída 2: janela interativa, com destaque por posição
# ---------------------------------------------------------------------------

class VistaInterativa:
    """Janela própria do VTK, com pick por posição.

    Sem Qt no caminho: é o que faz a interação ser fluida mesmo com dezenas
    de posições -- ver a nota no topo do módulo.
    """

    def __init__(self, res, titulo: str = "Vista 3D do pavimento") -> None:
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
        # tudo que não é posição de armadura -- laje e viga -- é moldura:
        # some junto quando uma posição é destacada (ver _destacar).
        self._moldura = [a for nome, a in self.plotter.renderer.actors.items()
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
        _posicionar_camera(self.plotter)

    # -- interação ------------------------------------------------------
    def _ator_sob_o_mouse(self):
        x, y = self.plotter.iren.get_event_position()
        self._picker.Pick(x, y, 0, self.plotter.renderer)
        ator = self._picker.GetActor()
        return ator if ator is not None and ator in self._info else None

    def _destacar(self, ator) -> None:
        """Acende a posição apontada e apaga o resto, laje e viga inclusive
        -- é o contraste, não a cor sozinha, que faz a peça certa saltar
        aos olhos no meio de dezenas de tubos parecidos."""
        for outro in self._atores:
            prop = outro.GetProperty()
            if outro is ator:
                prop.SetColor(*_AMBAR)
                prop.SetOpacity(1.0)
            else:
                prop.SetOpacity(_OPACIDADE_APAGADA)
        for peca in self._moldura:
            peca.GetProperty().SetOpacity(_OPACIDADE_MOLDURA_APAGADA)

    def _limpar_destaque(self) -> None:
        for ator in self._atores:
            prop = ator.GetProperty()
            cor = self._cor_original.get(ator)
            if cor is not None:
                prop.SetColor(*cor)
            prop.SetOpacity(1.0)
        for peca in self._moldura:
            peca.GetProperty().SetOpacity(_OPACIDADE_MOLDURA)

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


def abrir_vista_interativa(res, titulo: str = "Vista 3D do pavimento"
                           ) -> None:
    """Abre a janela interativa. Bloqueia até o usuário fechá-la, como um
    diálogo modal -- é o comportamento de ``Plotter.show``."""
    VistaInterativa(res, titulo=titulo).mostrar()
