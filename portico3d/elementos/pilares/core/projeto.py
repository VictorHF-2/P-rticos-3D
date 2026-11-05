# -*- coding: utf-8 -*-
"""
projeto.py
Um **projeto**: a lista de lances de pilar que serão calculados, detalhados e
quantificados juntos, com a persistência e o cálculo em lote.

O escopo de cada lance continua sendo o de :mod:`pilares.core.modelo` -- seção
e armadura constantes, esforços de primeira ordem conhecidos nas duas pontas.
O que esta camada acrescenta é o **conjunto**: um projeto tem vários pilares,
e os entregáveis do conjunto (um DXF com todas as peças, um quadro de
quantidades consolidado) só existem no nível dele.

Cada lance é independente dos outros: nada aqui transmite esforço de um pilar
para o outro nem empilha lances de pavimentos diferentes. A independência é
proposital -- os esforços vêm do modelo global, que é anterior a este
programa --, e é o que permite calcular o lote em qualquer ordem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .modelo import (FORMATO_PROJETO, VERSAO_FORMATO, Pilar,
                     conferir_formato)


@dataclass
class Projeto:
    """Uma lista de lances de pilar, com identificação do projeto."""

    nome: str = "Projeto"
    responsavel: str = ""
    observacoes: str = ""
    pilares: list[Pilar] = field(default_factory=list)

    # -- manipulação da lista ----------------------------------------------
    def adicionar(self, pilar: Pilar) -> Pilar:
        """Acrescenta um lance, garantindo nome único."""
        pilar.nome = self._nome_livre(pilar.nome or "P1")
        self.pilares.append(pilar)
        return pilar

    def duplicar(self, indice: int) -> Pilar:
        """Copia o lance do índice dado -- o caminho normal de montar um
        projeto, em que os pilares se repetem com variações pequenas."""
        original = self.pilares[indice]
        copia = Pilar.de_dict(original.para_dict())
        return self.adicionar(copia)

    def remover(self, indice: int) -> None:
        del self.pilares[indice]

    def _nome_livre(self, base: str) -> str:
        usados = {p.nome for p in self.pilares}
        if base not in usados:
            return base
        i = 2
        while f"{base}-{i}" in usados:
            i += 1
        return f"{base}-{i}"

    def validar(self) -> list[str]:
        """Avisos do projeto -- o que só se vê olhando o conjunto."""
        from . import avisos as av
        saida: list[str] = []
        if not self.pilares:
            saida.append(av.erro("O projeto não tem nenhum pilar."))
        nomes = [p.nome for p in self.pilares]
        repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
        if repetidos:
            saida.append(av.erro(
                f"Nomes de pilar repetidos no projeto: "
                f"{', '.join(repetidos)}. O nome é o que amarra a peça ao "
                f"desenho e ao quadro de quantidades; repetido, o "
                f"quantitativo soma peças que a prancha mostra como uma só."))
        return saida

    # -- persistência -------------------------------------------------------
    def para_dict(self) -> dict:
        return {"_formato": FORMATO_PROJETO, "_versao": VERSAO_FORMATO,
                "nome": self.nome, "responsavel": self.responsavel,
                "observacoes": self.observacoes,
                "pilares": [p.para_dict() for p in self.pilares]}

    @staticmethod
    def de_dict(d: dict) -> "Projeto":
        conferir_formato(d, FORMATO_PROJETO, ("pilares",))
        return Projeto(nome=d.get("nome", "Projeto"),
                       responsavel=d.get("responsavel", ""),
                       observacoes=d.get("observacoes", ""),
                       pilares=[Pilar.de_dict(x) for x in d.get("pilares", [])])

    def salvar(self, caminho: str) -> str:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(self.para_dict(), f, ensure_ascii=False, indent=2)
        return caminho

    @staticmethod
    def carregar(caminho: str) -> "Projeto":
        with open(caminho, encoding="utf-8") as f:
            return Projeto.de_dict(json.load(f))


@dataclass
class ResultadoProjeto:
    """O projeto calculado: um resultado por lance, na ordem da lista."""

    projeto: Projeto
    resultados: list = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    #: nome do pilar -> mensagem, para os lances que nem calcularam. Um lance
    #: com dado inconsistente não pode derrubar o lote inteiro: o projeto
    #: segue, e a falha aparece nomeada.
    falhas: dict[str, str] = field(default_factory=dict)
    #: quantos lances ficaram sem calcular por cancelamento do usuário.
    interrompido: int = 0

    @property
    def ok(self) -> bool:
        """Verdadeiro quando todos os lances calcularam e passaram."""
        return (not self.falhas and not self.interrompido
                and bool(self.resultados)
                and all(r.ok for r in self.resultados))

    @property
    def reprovados(self) -> list:
        return [r for r in self.resultados if not r.ok]

    @property
    def quantitativo(self):
        from . import quantitativos as qt
        return qt.consolidar(self.resultados)

    def por_nome(self, nome: str):
        for r in self.resultados:
            if r.pilar.nome == nome:
                return r
        return None


def calcular(projeto: Projeto, progresso=None, cancelado=None
             ) -> ResultadoProjeto:
    """Calcula todos os lances do projeto.

    Um lance que levanta exceção -- dado inconsistente que a validação do
    modelo recusa de saída, por exemplo -- entra em ``falhas`` e o lote
    continua. Reprovação de verificação **não** é falha: o lance calculou, o
    resultado existe e diz que não passa, e é isso que tem de chegar à
    prancha.

    ``progresso(feito, total, nome)`` é chamado antes de cada lance e
    ``cancelado()`` entre eles; ambos são opcionais e servem à interface, que
    roda este laço fora da thread da janela. Cancelar devolve o que já foi
    calculado, com o que faltou anotado em ``interrompido``.
    """
    from .dimensionar import dimensionar
    saida = ResultadoProjeto(projeto=projeto)
    saida.avisos.extend(projeto.validar())
    total = len(projeto.pilares)
    for i, pilar in enumerate(projeto.pilares):
        if cancelado is not None and cancelado():
            saida.interrompido = total - i
            break
        if progresso is not None:
            progresso(i, total, pilar.nome)
        try:
            saida.resultados.append(dimensionar(pilar))
        except Exception as exc:                        # noqa: BLE001
            saida.falhas[pilar.nome] = str(exc)
    # Critério de projeto: basta uma barra tracionada em algum lance para
    # todas as barras da estrutura levarem a emenda de tração (item
    # 9.5.2.2.1) -- um comprimento de traspasse só, para não haver na obra
    # dois comprimentos que se confundem.
    from .dimensionar import impor_emenda_tracionada
    origem = next((r for r in saida.resultados
                   if r.ancoragem is not None and r.ancoragem.tracionada),
                  None)
    if origem is not None:
        motivo = f"lance {origem.pilar.nome}, {origem.ancoragem.motivo}"
        for r in saida.resultados:
            for rc in (r.resultados_combinacoes or [r]):
                impor_emenda_tracionada(rc, motivo)
        saida.avisos.append(
            f"Emenda por traspasse de barras tracionadas aplicada a todos os "
            f"lances do projeto: {motivo}.")
    if progresso is not None:
        progresso(total - saida.interrompido, total, "")
    return saida
