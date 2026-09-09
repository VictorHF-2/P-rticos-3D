# Pórticos 3D R02 — instruções de uso

Solver matricial de pórticos espaciais, com dimensionamento de pilares, vigas
e lajes pela NBR 6118 e emissão de memória de cálculo, quadro de quantidades e
desenhos.

**Não é preciso instalar Python nem nada além.** O programa já vem com tudo
dentro.

## Como abrir

Clique duas vezes em **`Porticos.exe`**.

A primeira abertura demora mais (uns 30 segundos): o programa monta um cache
de fontes na primeira vez. Nas seguintes, abre em poucos segundos.

> **Mantenha os arquivos juntos.** O `Porticos.exe` precisa da pasta
> `_internal` que está ao lado dele. Se quiser um atalho na Área de Trabalho,
> clique com o botão direito no `Porticos.exe` → *Enviar para* → *Área de
> trabalho (criar atalho)*. Não mova o `.exe` sozinho.

## Avisos do Windows

Na primeira execução o Windows pode mostrar **"O Windows protegeu o
computador"**. Isso acontece com qualquer programa sem assinatura digital
paga, não indica problema no arquivo. Clique em *Mais informações* → *Executar
assim mesmo*.

Se o antivírus corporativo bloquear, peça ao TI para liberar o executável.

## Primeiros passos

1. **Assistente (Ctrl+G)** é o caminho curto: três listas de números — vãos em
   X, vãos em Y, pés-direitos — e sai um edifício inteiro, com apoios, seções,
   lajes, peso próprio, carga de parede e vento por pavimento.
2. Ajuste o que quiser nas tabelas da esquerda e clique em **Aplicar tabelas
   (F5)**. As tabelas não editam o modelo enquanto se digita: elas são lidas
   de uma vez, e uma linha pela metade nunca deixa o modelo corrompido.
3. **Analisar caso (F9)** resolve um caso e imprime o resumo.
4. **Combinações NBR** gera as combinações últimas e a envoltória.
5. **Dimensionar pilares (F7)**, **vigas (F6)** e **lajes (F4)** mandam cada
   peça ao seu motor de cálculo.
6. **Projeto completo (F2)** faz tudo de uma vez e grava os três arquivos do
   projeto — leva alguns minutos num edifício inteiro.

Na pasta `exemplos` há dois modelos prontos: uma viga contínua e um edifício
de quatro pavimentos. Abrir um deles é a forma mais rápida de ver o fluxo
inteiro.

## As vistas

O seletor **Vista** troca o que o desenho mostra:

| | |
|---|---|
| Modelo | eixos, nós e apoios |
| 3D | as seções em dimensão real, não linhas |
| Laje | planta de um pavimento, com charneiras plásticas e momentos |
| Armadura | o aço de um pavimento no espaço, sobre o concreto translúcido |
| Deformada | traçada com as funções de forma, não por retas entre nós |
| N, Vy, Vz, T, My, Mz | os diagramas, com o momento do lado da fibra tracionada |
| Modo de flambagem | o modo crítico da análise de autovalor |

As vistas de **Laje** e **Armadura** são de um pavimento por vez — use o
seletor **Nível** ao lado.

## O que o programa grava

Nada é gravado sem que você mande. As saídas são:

| ação | o que sai |
|---|---|
| Projeto completo (F2) | memória de cálculo (.docx), quadro de quantidades (.xlsx) e a prancha com todas as peças (.dxf) |
| Dimensionar vigas / lajes | desenhos por peça, em PNG e DXF |
| Armadura em DXF (F3) | a armadura do pavimento em polilinhas 3D |
| Salvar relatório | o painel de baixo, em texto |

**DXF, e não DWG.** O DWG é formato binário e fechado, sem especificação
pública. O DXF é o formato de troca que a própria Autodesk publica, e
AutoCAD, BricsCAD, QCAD e Revit o abrem sem conversão nenhuma, com as camadas,
cotas e textos preservados.

## Versão de arquivo único

Também existe o `Porticos-portatil.exe`: um único arquivo, sem pasta ao lado.
É mais cômodo de enviar por e-mail ou pendrive, mas demora bem mais para abrir
a cada vez, porque se descompacta sozinho antes de rodar. Para uso no dia a
dia, prefira o `Porticos.exe`.

## Conferindo a instalação

O programa carrega 418 conferências de referência — problemas de solução
conhecida, comparações com o MASTAN2 e provas de que as pontes com os motores
de elemento traduzem certo. Para rodá-las:

```
Porticos.exe --autoteste
```

A janela não abre; o programa calcula e devolve código 0 se tudo passou. Leva
alguns minutos.

## Requisitos

Windows 10 ou 11, 64 bits. Cerca de 600 MB livres em disco.
