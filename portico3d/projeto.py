# -*- coding: utf-8 -*-
"""
projeto.py
O edifício inteiro, do modelo aos três arquivos que se entrega.

Até aqui cada motor produzia a sua saída: uma memória por viga, uma planta por
pavimento, um DXF por peça. Num edifício de quatro pavimentos isso dá dezenas
de arquivos, e ninguém entrega dezenas de arquivos — entrega-se **um** memorial,
**um** quadro de quantidades e **uma** prancha. É o que este módulo monta.

## O que ele acrescenta, além de juntar

Juntar é o menos. O que só existe neste nível é o que nenhum motor de elemento
tem como saber:

* os **esforços do pórtico**, com vento e desaprumo, que é o que amarra o
  edifício e o que os motores de elemento não calculam;
* a **estabilidade global** (γz), que é do edifício e de mais nada;
* as **reações**, que são a entrada da fundação;
* e o **confronto** entre o que cada motor dimensionou e o que a envoltória do
  pórtico exige — que é o que diz se o projeto fecha.

## O que ainda não entra

Fôrmas. O quadro de quantidades traz aço e concreto, que os motores calculam,
e **não** traz área de fôrma. Não é esquecimento: o critério é contar só as
faces que precisam segurar o concreto, e isso depende do que está encostado na
peça — a face superior da viga não leva fôrma onde a laje se apoia. Quem sabe
disso é o modelo do edifício, não o motor de elemento, e é conta para se fazer
aqui. Fica anotado como pendência, à vista, em vez de sair um quadro que
parece completo e não está.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core.modelo import ErroDeModelo, Modelo


@dataclass
class Projeto:
    """Tudo que o edifício produziu, num objeto só."""

    modelo: Modelo
    envoltorias: dict = field(default_factory=dict)
    combinacoes: list = field(default_factory=list)
    resultados: dict = field(default_factory=dict)
    pilares: list = field(default_factory=list)
    vigas: list = field(default_factory=list)
    lajes: list = field(default_factory=list)
    estabilidade: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    # -- vereditos ---------------------------------------------------------

    @property
    def lances_aprovados(self) -> list:
        return [v for v in self.pilares if v.aprovado]

    @property
    def vigas_aprovadas(self) -> list:
        return [v for v in self.vigas if v.aprovado]

    @property
    def pavimentos_aprovados(self) -> list:
        return [v for v in self.lajes
                if v.passou and not list(v.resultado.erros)]

    @property
    def fecha(self) -> bool:
        """Todo elemento verificado foi aprovado.

        Um único reprovado derruba o projeto, e é assim que tem de ser: não
        existe edifício aprovado com um pilar que não passa.
        """
        return (bool(self.pilares or self.vigas or self.lajes)
                and len(self.lances_aprovados) == len(self.pilares)
                and len(self.vigas_aprovadas) == len(self.vigas)
                and len(self.pavimentos_aprovados) == len(self.lajes))

    def resumo(self) -> str:
        linhas = [f"Projeto de {self.modelo.nome} — "
                  f"{len(self.modelo.nos)} nós, {len(self.modelo.barras)} "
                  f"barras, {len(self.modelo.lajes)} painéis de laje"]
        if self.combinacoes:
            linhas.append(f"  combinações últimas: {len(self.combinacoes)}")
        for rotulo, todos, bons in (
                ("lances de pilar", self.pilares, self.lances_aprovados),
                ("vigas contínuas", self.vigas, self.vigas_aprovadas),
                ("pavimentos de laje", self.lajes,
                 self.pavimentos_aprovados)):
            if todos:
                linhas.append(f"  {rotulo}: {len(bons)} de {len(todos)} "
                              "aprovados")
        linhas.append("  veredito: " + ("PROJETO FECHA" if self.fecha
                                        else "HÁ ELEMENTOS REPROVADOS"))
        linhas.extend(f"  ! {a}" for a in self.avisos[:8])
        return "\n".join(linhas)


def calcular(modelo: Modelo, fck: float | None = None,
             pasta_desenhos=None) -> Projeto:
    """Resolve o edifício e roda os três motores de elemento.

    A ordem importa: a envoltória vem primeiro porque os três dimensionamentos
    dependem dela — os pilares para os esforços do lance, as vigas para o
    confronto com o que o motor delas calculou, e as lajes só indiretamente.
    """
    from .core.combinacoes import resolver_combinacoes
    from .core.envoltoria import envoltoria
    from .core.estabilidade import gama_z
    from .core.nbr6118 import acoes_do_modelo, combinacoes_elu, validar_acoes
    from .dimensionamento import (verificar_lajes, verificar_pilares,
                                  verificar_vigas)

    projeto = Projeto(modelo=modelo)

    try:
        acoes = acoes_do_modelo(modelo)
        validar_acoes(modelo, acoes)
        projeto.combinacoes = combinacoes_elu(acoes)
        projeto.resultados = resolver_combinacoes(modelo, projeto.combinacoes)
        projeto.envoltorias = envoltoria(modelo, projeto.resultados)
    except ErroDeModelo as erro:
        projeto.avisos.append(
            f"sem envoltória: {erro}. Pilares e o confronto das vigas ficam "
            "de fora")

    # γz precisa do caso **horizontal** que produziu o deslocamento: é a
    # razão entre o momento de segunda ordem e o de primeira, e sem ação
    # lateral não há o que medir. O caso de vento da combinação é quem serve.
    for combinacao in projeto.combinacoes:
        resultado = projeto.resultados.get(combinacao.nome)
        if resultado is None:
            continue
        laterais = [n for n in combinacao.fatores
                    if modelo.casos.get(n) is not None
                    and modelo.casos[n].grupo == "vento"]
        for nome_caso in laterais:
            try:
                projeto.estabilidade.append(
                    gama_z(modelo, modelo.casos[nome_caso], resultado))
            except (ErroDeModelo, KeyError, IndexError, ValueError):
                continue

    if projeto.envoltorias:
        try:
            projeto.pilares = verificar_pilares(modelo, projeto.envoltorias,
                                                fck)
        except ErroDeModelo as erro:
            projeto.avisos.append(f"pilares: {erro}")

    try:
        projeto.vigas = verificar_vigas(modelo, pasta_desenhos, fck,
                                        envoltorias=projeto.envoltorias)
    except ErroDeModelo as erro:
        projeto.avisos.append(f"vigas: {erro}")

    try:
        projeto.lajes = verificar_lajes(modelo, pasta_desenhos, fck)
    except ErroDeModelo as erro:
        projeto.avisos.append(f"lajes: {erro}")

    for v in projeto.vigas:
        projeto.avisos.extend(v.avisos)
    return projeto


def gerar(projeto: Projeto, pasta, nome: str | None = None) -> list[str]:
    """Grava os três arquivos do projeto e devolve os caminhos.

    Um memorial, um quadro de quantidades, uma prancha. Cada um falha por si:
    faltar o ezdxf não pode impedir que a memória de cálculo saia.
    """
    from .saidas import desenho_unico, memoria, quantitativos

    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    base = nome or projeto.modelo.nome or "projeto"

    arquivos = []
    for gerador, sufixo in ((memoria.gerar, "memória de cálculo.docx"),
                            (quantitativos.gerar, "quadro de quantidades.xlsx"),
                            (desenho_unico.gerar, "desenhos.dxf")):
        caminho = destino / f"{base} — {sufixo}"
        try:
            arquivos.append(str(gerador(projeto, caminho)))
        except Exception as erro:                        # noqa: BLE001
            arquivos.append(f"({sufixo} não gerado: {erro})")
    return arquivos
