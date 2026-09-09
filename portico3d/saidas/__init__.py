# -*- coding: utf-8 -*-
"""
saidas
Os três arquivos que se entrega do edifício.

``memoria`` grava a memória de cálculo em Word, ``quantitativos`` o quadro de
quantidades em Excel e ``desenho_unico`` a prancha em DXF. Os três leem o mesmo
:class:`~portico3d.projeto.Projeto` e não calculam nada: quem calcula é o
``core`` e os motores de elemento copiados.

O estilo é o da casa, e vem emprestado dos próprios motores — ``estilo_planilha``
para o Excel, a fonte Aptos e os títulos em azul para o Word —, de modo que o
memorial do edifício e o da viga avulsa saiam com a mesma cara.
"""
