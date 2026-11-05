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
ficaram de fora em todos os casos, e do Pilares R05 ficou de fora também o
``compat_pcalc.py`` (modo de compatibilidade com o PCalc, que não é
verificação pela NBR): o motor o importa como opcional e segue sem ele.
"""

from __future__ import annotations

#: De onde veio cada cópia. ``partes`` são os diretórios trazidos, na mesma
#: estrutura em que estão na origem.
PROCEDENCIA = {
    "pilares": {
        "programa": "Pilares",
        "revisao": "Pilares R05",
        "origem": "Pilares/Pilares R05/Programa/pilares",
        "partes": ("core", "saidas"),
        "copiado_em": "2026-11-05",
    },
    "vigas": {
        "programa": "Vigas",
        "revisao": "Vigas R04",
        "origem": "Vigas/Vigas R04/Programa/vigas",
        "partes": ("core", "saidas"),
        "copiado_em": "2026-11-03",
    },
    "lajes": {
        "programa": "Lajes",
        "revisao": "Lajes R11",
        "origem": "Lajes/Lajes R11/Programa/lajes",
        "partes": ("core", "saidas"),
        "copiado_em": "2026-11-05",
    },
    "vento": {
        "programa": "NBR-6123",
        "revisao": "NBR-6123",
        "origem": "NBR-6123/App",
        "partes": ("",),
        "copiado_em": "2026-09-30",
    },
}
