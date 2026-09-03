# Exemplos — o fluxo do programa de ponta a ponta

Dois arquivos, um pequeno e um de porte. O pequeno serve para ver cada tabela
de relance; o grande, para ver as análises dizerem algo.

```
py main.py exemplos/viga-continua.json --janela
py main.py exemplos/edificio-4-pav.json --janela
```

---

## O caminho, botão a botão

**1. Abrir.** O desenho aparece na vista *Modelo*. Ligue os rótulos de nós e de
barras para casar o desenho com as tabelas.

**2. Percorrer as abas, na ordem em que estão.** Materiais → Seções → Nós →
Barras → Apoios → Molas → Lajes → Casos → Cargas. Não é ordem arbitrária: cada
aba alimenta as listas suspensas da seguinte. Repare que na aba **Seções** as
colunas A, Iy, Iz e J estão em cinza e não aceitam digitação — saíram dos
lados. Mude o `h` de uma seção e veja as quatro se refazerem.

**3. Aplicar tabelas (F5).** Lê tudo de volta para um modelo novo. É aqui que
erro de digitação aparece — no relatório de baixo, não numa caixa de diálogo.
Experimente apagar o nome de um nó usado por uma barra e aplicar: o programa
recusa dizendo qual barra ficou órfã, e o modelo anterior segue intacto.

**4. Analisar caso (F9).** Resolve o caso escolhido na caixa *Caso*. A vista
salta para *Deformada*. Troque para `My`, `Mz`, `N` — os diagramas saem
desenhados no plano em que cada esforço flete. A escala vai no título; deixe
em "automática" ou fixe um número para comparar dois casos na mesma escala.

**5. Segunda ordem.** Refaz o mesmo caso com P-Δ. O relatório diz em quantas
iterações convergiu. Compare a deformada com a de primeira ordem: no edifício
a diferença é visível.

**6. Combinações NBR.** Gera as combinações últimas e de serviço da NBR 6118 a
partir da classificação dos casos, resolve todas e monta a envoltória. O
relatório traz, por barra, o extremo de cada esforço **com os valores
concomitantes** — o trio (N, My, Mz) da mesma combinação, que é o que o
dimensionamento de pilar precisa. Depois disso, a caixa *Caso* passa a listar
também as combinações: escolha `ELU 02` e veja o diagrama dela.

**7. Estabilidade.** γz por combinação, com a classificação em nós fixos ou
móveis e o aviso quando passa de 1,3.

**8. Flambagem.** Fator crítico e modo. Escolha um caso com compressão — no
edifício, `G` serve; na viga contínua não há barra comprimida, e o programa
diz isso em vez de devolver um número sem sentido.

**9. Reações (F8).** Tabela das reações do caso ou combinação escolhido, com a
resultante embaixo: carga vertical total, cortante na base e momento de
tombamento. Apoio elástico aparece marcado com `~`, porque ali a força é −k·d
e sai pela mola, não pelo apoio rígido. Na viga contínua isso é visível: dos
157,5 kN totais, 26,25 saem pela mola do `N4`.

**10. Salvar relatório.** Grava em texto tudo o que está no painel de baixo,
para levar à planilha ou ao memorial. "Limpar relatório" esvazia o painel
antes de uma rodada nova, para o texto não se misturar.

---

## viga-continua.json

Três tramos de 5 m, seção 20×50. Pequena de propósito: cabe inteira na tela e
cada tabela tem duas ou três linhas.

O que ela exercita, e onde olhar:

| Recurso | Onde |
|---|---|
| Rótula de extremidade | barra `T3`, liberação `ry` no nó inicial |
| Apoio elástico | mola vertical em `N4`, no lugar do apoio rígido |
| Recalque prescrito | caso `R`, 10 mm de descida em `N3` |
| Carga parcial e trapezoidal | caso `Q` em `T3`, de 25 % a 100 % do vão, de 4 a 16 kN/m |
| Peso próprio automático | caso `G`, gerado a partir do γ do material |

Duas coisas para reparar. O momento sobre `N3` é **nulo nas duas barras** que
chegam ali, porque a rótula solta a rotação e o apoio não a restringe: é uma
rótula de verdade, não um artifício de montagem. O diagrama de `My` mostra
isso de imediato, e é a maneira mais rápida de conferir que a liberação foi
entendida.

E o caso `R`, sozinho, produz esforço — 37,5 kN·m de pico só com os 10 mm de
recalque. É porque a viga é hiperestática; numa isostática o mesmo recalque
giraria a peça como corpo rígido e não produziria esforço nenhum.

## edificio-4-pav.json

Pórtico de quatro pavimentos, 3 m de pé-direito, planta de 11 × 5 m com seis
prumadas. Pilares 20×20, vigas 20×50, concreto C30.

| Caso | O que é |
|---|---|
| `G` | permanente: peso próprio das barras + laje + revestimento + parede |
| `Q` | acidental comercial, 3 kN/m² vindo das lajes |
| `VX`, `VY` | vento, 40 kN por pavimento, **no mesmo grupo excludente** |

### De onde vem cada carga

Oito painéis de laje, dois por pavimento, 220 m² no total. Vale abrir a aba
**Lajes** e a aba **Cargas distribuídas** lado a lado, porque a segunda é
consequência da primeira:

| Parcela | Origem | Como chega à viga |
|---|---|---|
| Peso próprio das barras | seção × γ do material | uniforme, 2,5 kN/m numa V20×50 |
| Laje, 12 cm | espessura × γ → 3,0 kN/m² | trapézio ou triângulo, por área de influência |
| Revestimento | 1,5 kN/m² na aba Lajes | junto com o peso da laje |
| Parede | 6 kN/m, digitado nas cargas distribuídas | uniforme — é o que de fato é linear |
| Acidental | 3 kN/m² na aba Lajes, vai para `Q` | trapézio ou triângulo |

Some tudo e dá **G = 10,33 kN/m²** e **Q = 3,00 kN/m²** de projeção — números
de edifício de verdade, e conferíveis: rode o caso `G` e leia a soma das
reações no relatório.

Numa viga de 6 m encostada num painel de 6 × 5 m, a carga aparece em três
trechos: rampa de 0 a 11,25 kN/m até 2,5 m, patamar de 11,25 kN/m no meio, e
rampa de volta a zero. O pico é `q·lx/2` com `lx` o menor lado do painel; a
soma dos quatro quinhões devolve exatamente o peso do painel, e há conferência
no autoteste para isso.

**A laje é painel de carga, não elemento de casca.** Ela não trabalha como
diafragma: cada prumada resiste ao vento pela sua própria rigidez, sem a
compatibilização horizontal que a laje real impõe. Para pórtico regular a
diferença é pequena; para planta muito assimétrica, não é.

O grupo do vento é o detalhe que vale conferir: `VX` e `VY` nunca aparecem
juntos numa combinação, porque o vento não sopra nas duas direções ao mesmo
tempo. Rode *Combinações NBR* e procure — são 15 combinações, 7 delas ELU, e
nenhuma traz as duas.

As vigas têm **trecho rígido** de 10 cm em cada ponta, que é metade da largura
do pilar. Por isso o diagrama da viga `VX1.1.1` vai de x = 0,10 a x = 5,90,
com os nós em 0,00 e 6,00: o que se lê na ponta é o momento na **face** do
pilar, que é o de dimensionar, e não o momento no eixo.

O concreto é **C30**, e o módulo não foi digitado: saiu da classe pelo item
8.2.8 da norma. Na aba Materiais, o campo E está em cinza e mostra
26.838.405 kN/m² — que é o E_cs de um C30 com agregado de granito. Troque a
classe para C40 e veja o número se refazer.

O pilar de 20×20 é o mínimo prático da norma, e é o que faz esta estrutura ser
de **nós móveis**: o γz governante dá 1,146, acima de 1,1. Como fica abaixo de
1,3, o item 15.7.2 ainda autoriza estimar a segunda ordem majorando as ações
horizontais por 0,95·γz.

Vale fazer o experimento: na aba Seções, mude os lados da seção `P20` de 0,20
para 0,24, aplique as tabelas e rode a estabilidade de novo. O γz cai para
1,075 e a estrutura passa a ser de **nós fixos**. Quatro centímetros no pilar
viram a classificação — é a mesma conta que se faz em projeto para decidir se
a segunda ordem global pode ser dispensada, e mostra como a decisão é
sensível. Vale repetir o teste trocando a classe do concreto em vez da seção:
subir de C30 para C40 enrijece o pórtico e também mexe no γz, por outro
caminho.

A flambagem sob `G` dá fator crítico próximo de 9,1 — a carga permanente cabe
nove vezes antes de a estrutura perder estabilidade. É folga confortável, e
serve de contraste: o γz mede o **acréscimo de esforço** sob a carga de
projeto, a flambagem mede a **distância até o colapso** por instabilidade. São
perguntas diferentes, e é normal uma estrutura ter γz desconfortável e fator
crítico folgado ao mesmo tempo.
