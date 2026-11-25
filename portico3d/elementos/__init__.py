# -*- coding: utf-8 -*-
"""
elementos
Cópias dos motores de cálculo dos outros programas da pasta.

Estes arquivos **não são originais deste programa**: são cópias dos programas
de Pilares, Vigas, Lajes e NBR-6123 desta mesma pasta. Estão aqui, e não
importados de lá, para que o solver não quebre nem mude de resultado quando
aqueles programas evoluírem — o que se ganha é reprodutibilidade, e o que se
paga é ter de atualizar a cópia de propósito.

**A estrutura de pastas de cada origem é preservada.** Não é capricho: o
``saidas/desenho.py`` do Vigas importa ``..core.dimensionar``, e achatar tudo
num diretório só quebraria esse caminho. Corrigir o import à mão custaria a
integridade da cópia — que é exatamente o que se quer poder conferir.

A procedência está em ``PROCEDENCIA`` e o autoteste compara **byte a byte** com
a origem, quando ela está ao alcance. Ao trazer uma revisão nova, copie os
diretórios inteiros e atualize a entrada — não edite estes arquivos, ou a cópia
deixa de ser cópia e passa a ser um garfo que ninguém sabe que existe.

Do Pilares, do Vigas e do Lajes vieram o ``core/`` e o ``saidas/`` — é do
``saidas/`` que saem os desenhos das peças dimensionadas. As interfaces
ficaram de fora em todos os casos, e do Pilares ficou de fora também o
``compat_pcalc.py`` (modo de compatibilidade com o PCalc, que não é
verificação pela NBR): o motor o importa como opcional e segue sem ele.
"""

from __future__ import annotations

#: De onde veio cada cópia. ``partes`` são os diretórios trazidos, na mesma
#: estrutura em que estão na origem.
#:
#: Os programas de elemento viraram repositórios git (``<Programa>/Programa``,
#: uma tag por revisão), e as pastas de revisão (``Vigas R04`` etc.) não
#: existem mais. ``repositorio`` + ``commit`` + ``pacote`` dizem de que
#: commit a cópia é idêntica; o autoteste a confronta com ele por
#: ``git show``. ``commit`` vazio quer dizer que a cópia foi feita da pasta de
#: revisão **antes** de o estado dela virar commit — nenhum commit do
#: repositório é idêntico a ela, e ``origem`` guarda o caminho de onde veio.
PROCEDENCIA = {
    "pilares": {
        "programa": "Pilares",
        "revisao": "Pilares motor-2026-11-25",
        "repositorio": "Pilares/Programa",
        "pacote": "pilares",
        # tag motor-2026-11-25: dimensionar 1,6 a 20 vezes mais rápido,
        # resultado idêntico bit a bit, pedido pelo Pórticos
        "commit": "97c23adb974051dcce3e348f9733cc7440ccdba0",
        "origem": "",
        "partes": ("core", "saidas"),
        "copiado_em": "2026-11-25",
    },
    "vigas": {
        "programa": "Vigas",
        "revisao": "Vigas motor-2026-11-25",
        "repositorio": "Vigas/Programa",
        "pacote": "vigas",
        # tag motor-2026-11-25: barra pela mínima cortada pelo diagrama e
        # seção L, pedidas pelo Pórticos
        "commit": "1508440b74f57deab49891ae10171ba27ff1db1f",
        "origem": "",
        "partes": ("core", "saidas"),
        "copiado_em": "2026-11-25",
    },
    "lajes": {
        "programa": "Lajes",
        "revisao": "Lajes R14",
        "repositorio": "Lajes/Programa",
        "pacote": "lajes",
        # tag R14: DXF da laje treliçada (pedido do Pórticos)
        "commit": "fcc6aba3407629dd94d037524c14e35f1a649daa",
        "origem": "",
        "partes": ("core", "saidas"),
        "copiado_em": "2026-11-25",
    },
    "vento": {
        "programa": "NBR-6123",
        "revisao": "NBR-6123",
        "origem": "NBR-6123/App",
        "partes": ("",),
        "copiado_em": "2026-09-30",
    },
}
