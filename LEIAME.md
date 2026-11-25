# Pórticos 3D — solver matricial de pórticos espaciais

Análise elástica linear de primeira ordem de pórticos espaciais pelo método
da rigidez direta, com geração das combinações de ações da NBR 6118 e
envoltória de esforços. É o núcleo que, nas fases seguintes, receberá a
segunda ordem e a flambagem, e que alimentará de esforços os programas de
elemento (Pilares, Vigas, Fundações).

Elemento de dois nós e doze graus de liberdade, de Euler-Bernoulli ou de
Timoshenko conforme a seção declare ou não área de cisalhamento, na forma do
capítulo de análise matricial de McGuire, Gallagher e Ziemian — *Matrix
Structural Analysis* —, que é o livro por trás do MASTAN2.

## Como executar

```
Iniciar_Porticos.bat
```

ou, direto no Python:

```
py main.py                             abre a janela
py main.py modelo.json --janela        abre a janela já com um modelo
py main.py --autoteste                 roda as 786 conferências de referência
py main.py modelo.json [caso]          resolve um caso e imprime o resumo
py main.py modelo.json --envoltoria    gera as combinações da NBR 6118,
                                       resolve todas e imprime a envoltória
py main.py modelo.json --estabilidade  γz por combinação, classificação de
                                       nós fixos ou móveis, e flambagem
```

Dependências: `py -m pip install -r requirements.txt` — numpy, scipy e PySide6
para calcular e montar a janela, **pyvista** e **pyvistaqt** para o motor de
desenho 3D (ver "O motor de desenho virou PyVista/VTK", mais abaixo), mais
**python-docx, openpyxl e ezdxf** para emitir. Estas três últimas não são
opcionais: são elas que gravam a memória de cálculo, o quadro de
quantidades e o CAD. Faltavam no arquivo, e numa instalação limpa o programa
subia e quebrava na primeira exportação.

## A janela

Tabelas à esquerda, desenho à direita, relatório embaixo. O caminho é montar,
analisar e ler o resultado, e a interface existe só para encurtá-lo: não há
uma linha de mecânica nela, e é de propósito — tudo continua no `core`, que é
o que as 786 conferências cobrem.

**A janela cabe em qualquer tela.** O tamanho de abertura sai da área útil
da tela desta máquina — já sem a barra de tarefas —, a janela é centrada nela,
e em tela pequena abre maximizada. Abaixo de 1200×720 de área útil isso
importa muito: um monitor de 1920×1080 com a escala do Windows em 150 % tem
1280×720 de área **lógica**, que é em pixels lógicos que o Qt trabalha.

Isso não bastaria sozinho. O Qt ignora um mínimo menor que o `minimumSizeHint`
do conteúdo, e o conteúdo aqui exigia **1752 px de largura** — a janela não
descia disso em tela nenhuma. Eram três coisas, e as três foram medidas antes
de serem mexidas:

| o que empurrava | quanto | o que mudou |
|---|---|---|
| Linha de controles do desenho | ~1 100 px | virou uma segunda barra de ferramentas, que transborda sozinha no botão `»` |
| Botões "Acrescentar material" e "Remover selecionadas" | 508 px | viraram "Acrescentar" e "Remover", com a frase no balão — a aba já diz de que registro se trata |
| Listas suspensas dimensionadas pelo maior item | 234 px só a de Vista | truncadas em 12 caracteres; o texto inteiro continua na lista aberta |

Hoje o conteúdo cabe em **334×275 px**, e o piso declarado é 800×520 — o mesmo
do programa de Pilares. Há conferência medindo isso: se algum widget novo
voltar a empurrar o mínimo acima do piso, o autoteste reprova.

**As doze tabelas do painel de entrada vêm em três abas, não uma fileira.**
`Inicial` (Materiais, Seções, Casos de carga, Carga nas lajes), `Geometria`
(Nós, Barras, Apoios, Molas, Lajes) e `Cargas` (Cargas nodais, Cargas
distribuídas, Recalques) — a ordem é a de preencher um modelo do zero: o que
não depende de geometria primeiro, a geometria depois, e por último as cargas
que a usam. Doze abas soltas lado a lado já truncava o rótulo por volta da
sétima; agrupadas por assunto, cada aba principal cabe com folga, e
`self.dados.tabelas` continua um dicionário achatado por chave — o
agrupamento é só de apresentação, ninguém que já lia ou escrevia ali precisou
mudar.

**"Carga nas lajes" nomeia um uso e aplica em lote.** Em vez de digitar
revestimento e acidental painel a painel, o projetista cria um tipo — "corredor",
"biblioteca", "lavanderia" — com os dois valores, na sub-aba `Carga nas lajes`
de `Inicial`; na aba `Lajes`, cada painel escolhe o tipo numa lista suspensa,
e Revestimento/Acidental saem calculados e travados dali, exatamente como a
seção sai calculada dos lados. O tipo fica gravado na laje mesmo depois de
resolvido (`Laje.tipo_carga`), então mudar um valor no tipo e mandar
"Aplicar tabelas" de novo atualiza **todos** os painéis daquele uso de uma
vez — é o que faz a setorização baixar de custo. Deixar o campo em branco
continua aceitando o revestimento e o acidental digitados à mão, como sempre.

**A barra principal agrupa por assunto.** Dezesseis ações lado a lado pediam
3 322 px e transbordavam **até num monitor de 1920**, deixando metade do
programa a dois cliques em qualquer tela. Agrupadas em `Dimensionar ▾`,
`Emitir ▾` e `Relatório ▾`, cabem inteiras. Os atalhos não mudaram — e como
menu que não está aberto só responde ao atalho se a ação estiver na cadeia da
janela, cada ação com atalho é registrada nela; há conferência exigindo que os
oito, de F2 a F9, continuem alcançáveis.

**Um botão só roda as análises, e uma lista escolhe qual olhar.** O botão
`Análise` (F9) substituiu o "Analisar caso" e o menu `Análise ▾`: um clique
resolve **tudo** — 1ª e 2ª ordem de cada caso de carga, as combinações da NBR
com a envoltória, a estabilidade global, a flambagem de cada caso e o modal.
Uma análise que não se aplica ao modelo (a flambagem de um caso sem carga
vertical, uma 2ª ordem que não converge) é anotada no relatório e não derruba
as outras. Na barra de desenho, a lista **Análise** — ao lado de Vista e Caso —
escolhe qual está na tela: `Modelo`, `1ª ordem`, `2ª ordem`, `Combinações`,
`Estabilidade`, `Flambagem` ou `Modal`.

**Cada análise oferece só as vistas que fazem sentido para ela.** O modal não
tem armadura, e a flambagem não tem diagrama de momento: o modal mostra o modo
de vibração, a flambagem o modo de flambagem, a 1ª e a 2ª ordem a deformada e
os diagramas de esforço, e a armadura fica no desenho do modelo e na
envoltória das combinações, onde há dimensionamento por trás. A caixa Caso
lista só os casos que **aquela** análise resolveu, e fica apagada onde não há
caso (o modal é vibração livre). Os controles que não valem para a vista na
tela (escala, nível, rótulos, forma do diagrama) ficam apagados. Escolher uma
análise escreve no relatório o resumo dela — o detalhe que o botão não despeja
de uma vez. A 2ª ordem e a 1ª ordem do mesmo caso ficam guardadas **à parte**:
antes, rodar uma apagava a outra.

Rodar `Dimensionar` não apaga a análise que está na tela quando as tabelas não
mudaram — só uma edição nelas descarta os resultados.

**Ler o esforço com o clique.** Nos diagramas de esforço, clicar numa barra ou na
área do diagrama mostra o valor naquele ponto — com a posição, os valores nos
dois nós e o máximo e o mínimo da barra —, **sem mover a câmera** (o padrão do
PyVista é recentrar a vista a cada malha acrescentada, e era isso que a
devolvia ao início a cada clique), e o valor também aparece **ao lado do
ponto**, no próprio 3D, numa etiqueta que se lê de relance. O texto de detalhe
fica abaixo da legenda da vista, e não por cima dela. Girar o desenho não lê
nada: só vale o clique, apertar e soltar quase no mesmo lugar.

**Vista de cargas.** A lista Análise ganhou `Cargas`, com a vista `Cargas`: as
cargas de um caso — ou de uma **combinação**, já ponderada pelos fatores dela,
que é o que de fato é aplicado — desenhadas como setas: força nodal em
vermelho, momento em roxo, carga distribuída em azul (fileira de setas com a
linha que une as caudas, que é o diagrama da carga) e recalque como um cubo
laranja no nó. O comprimento da seta é proporcional à intensidade, e a escala
fica na legenda. É uma vista **à parte da dos esforços**, e funciona antes de
qualquer análise: mostra o que as tabelas aplicam.

Ela foi pensada para ser **auditada**. O título traz a **resultante** do caso —
a soma das forças no sistema global —, que é a primeira linha a conferir: num
caso de peso próprio tem de bater com o peso da estrutura, e num de vento com a
força horizontal total. Clicar numa seta mostra a carga inteira (intensidade nas
duas pontas, sistema de eixos, trecho do vão e total global), clicar numa barra
lista as cargas que caem nela, e clicar num nó traz as nodais e os recalques
dele; o relatório recebe o mesmo texto ao escolher a análise. Tudo sai de
`core/auditoria_cargas.py`, de modo que o desenho e o texto são a mesma conta —
e há conferência para ela (uniforme é q·L, trapézio é a média das pontas, carga
em eixo local é girada para o global pela matriz da montagem, e a combinação
soma os casos vezes os fatores).

**Várias cargas na mesma barra ficam em camadas.** Peso próprio, o quinhão de
cada laje e a parede atuam na mesma viga, e desenhadas todas a partir do eixo
se sobrepunham. Agora as que atuam do mesmo lado se **empilham para fora** a
partir da barra — a primeira encostada nela, a seguinte depois do fim das
setas da anterior —, e a escala das setas sai da pilha mais alta, para as
camadas não passarem do pavimento de cima. A carga que atua para o outro lado
não disputa lugar, e a que atua **ao longo** da barra (o peso próprio de um
pilar) sai ao lado dela, e não sobre ela. A entrada `todos os casos` da lista
Caso junta o permanente, o variável e o vento de uma vez, cada um com a sua
cor e o nome do caso na etiqueta — é onde se vê tudo o que o modelo aplica, e
onde o vento (cargas nodais horizontais, setas vermelhas) aparece junto da
gravidade. As setas de força nodal também ficaram maiores.

**A laje do modelo 3D fica com o topo no topo das vigas.** O plano dos nós passa
pelo eixo das vigas e a laje era desenhada centrada nele, atravessada pelas
vigas ao meio; agora o plano médio dela sobe `h_viga/2 − e/2`
(`core.lajes.deslocamento_do_centro`). É geometria de desenho e de posição da
armadura — a armadura de laje e a fôrma do DXF acompanham —, nenhum cálculo
depende disso. As lajes também ficaram opacas, com uma caixa "lajes" para
escondê-las sem redesenhar.

**O assistente é o que resolve o caso comum.** Um edifício de quatro
pavimentos com seis prumadas tem umas cem barras; digitá-las uma a uma seria
absurdo, e o assistente as gera a partir de três listas de números — vãos em
X, vãos em Y, pés-direitos —, já com apoios, seções, lajes, peso próprio,
carga de parede e vento por pavimento. Cada célula da grelha vira um painel de
laje, e é a laje que carrega as vigas. As tabelas ficam para o ajuste fino e
para ver o que saiu.

Os nomes gerados são posicionais: `N2.3.1` é o nó da segunda prumada em X,
terceira em Y, no primeiro pavimento; `VX1.1.3` é a viga em X do primeiro vão,
primeiro alinhamento, terceiro pavimento. Assim dá para achar uma barra pelo
nome sem procurar no desenho.

**Campo que aponta para outra coisa é lista suspensa, não texto livre.** O nó
de uma barra, o material, a seção, o caso de uma carga, a natureza e a
categoria de ψ — todos saem de uma lista montada na hora a partir do que já
está nas outras abas. O nome nunca sai errado, e o programa mostra o que
existe em vez de esperar que alguém lembre. A ordem de trabalho é a das abas:
materiais, seções, nós, barras, apoios, casos, cargas — cada uma alimentando
as listas da seguinte.

**O concreto é definido pela classe, e o módulo sai da norma.** Escolhido o
tipo `concreto`, informa-se a classe (C20 a C90), o agregado graúdo e se o
módulo é o secante ou o inicial; o E aparece calculado e travado. As fórmulas
são as do item 8.2.8 — `E_ci = α_E·5600·√f_ck` até 50 MPa, a expressão
cúbica acima disso, e `E_cs = α_i·E_ci` com `α_i = 0,8 + 0,2·f_ck/80 ≤ 1`.
O tipo `generico` continua aceitando o E digitado, para aço, madeira, ou
concreto de módulo medido em ensaio.

O padrão é o **secante**, porque é o que o item 14.5.2 manda usar na análise
("devendo, em princípio, ser considerado o módulo de elasticidade secante
E_cs"). Vale saber que a edição 2026 **removeu** o parágrafo de 2014 que
autorizava o módulo inicial no cálculo de esforços solicitantes: ali o E_ci
sobrou para perdas de protensão e idades novas.

Só o E é travado. O coeficiente de Poisson e o peso específico ficam
editáveis, preenchidos com 0,2 e 25 kN/m³ quando em branco — peso específico é
justamente onde se costuma embutir outra coisa, e travá-lo atrapalharia. O
módulo transversal não precisa de campo: o item 8.2.9 dá `G_c = E_cs/2,4`, e o
`G = E/(2(1+ν))` que o programa calcula dá exatamente isso com ν = 0,2.

**A seção é definida pelos lados, e as propriedades saem sozinhas.** Escolhido
o tipo `retangular` ou `circular`, basta informar os lados: A, Iy, Iz, J e as
áreas de cisalhamento aparecem calculados e travados contra edição. Só o tipo
`generica` espera as propriedades digitadas. O modelo guarda **como a seção
foi definida**, e não apenas o resultado, de modo que reabrir um arquivo e
mudar uma altura recalcula tudo — antes, voltariam só os momentos de inércia.

Um detalhe que decorre disso: as colunas calculadas são de **exibição**,
arredondadas a seis dígitos. Por isso a leitura de volta refaz a seção a partir
dos lados em vez de ler os números da tela — o que vale é a dimensão digitada.

As tabelas **não editam o modelo em cima da digitação**. Elas são lidas para um
modelo novo quando se pede "Aplicar tabelas", e o modelo anterior segue
intacto se a leitura falhar — uma linha pela metade nunca deixa o modelo
corrompido, e o erro aparece no relatório em vez de derrubar a janela.

**As reações têm ação própria (F8).** Elas ficavam soterradas no resumo geral —
num modelo de sessenta nós, depois de sessenta linhas de deslocamento —, e
reação é justamente o que se leva para a fundação. A tabela traz a resultante
embaixo: carga vertical total, cortante na base e momento de tombamento. Apoio
elástico aparece marcado, porque ali a força sai pela mola e não pelo apoio
rígido; sem listá-lo, a soma não fecharia com a carga aplicada e nada diria por
quê. "Salvar relatório" grava o painel em texto.

**O momento é traçado do lado da fibra tracionada**, que é a convenção de
projeto: numa biapoiada sob gravidade o momento positivo traciona a face
inferior, e é embaixo da viga que ele aparece; sobre o apoio de um balanço,
onde traciona em cima, ele sobe. Assim o desenho já diz de que lado vai a
armadura.

Os dois planos não levam o mesmo sinal de desenho, e isso não é descuido. Com
carga para baixo, o momento no meio do vão sai **+wL²/8 em My** e **−wL²/8 em
Mz** — a mesma troca de sinal que a convenção θy = −dw/dx impõe à matriz de
rigidez. O Mz já nasce negativo do lado tracionado e é traçado direto; o My
precisa da inversão. Há conferência exigindo, nos dois planos, que o traçado
caia do lado que desceu — igualar os sinais por simetria aparente poria um dos
diagramas do lado errado.

**A vista 3D desenha as seções, não linhas.** Cada barra vira o sólido da sua
seção, orientado pelos eixos locais, e as lajes viram placas da sua espessura.
Seção trocada, barra girada, laje na cota errada — tudo isso salta aos olhos
aqui e passa despercebido no desenho de eixos. Seção genérica, que só tem
propriedades, ganha o **retângulo equivalente**: o de mesma área e mesmas
inércias. É desenho, não cálculo.

**A vista de Laje é planta de um pavimento.** As vigas e os pilares aparecem
apagados e sem dado nenhum — são contorno, não o assunto. O assunto é o painel:
as **charneiras plásticas** e os momentos nas duas direções. O seletor de nível
existe porque planta de laje é de um pavimento por vez: com quatro pavimentos
sobrepostos, as charneiras de todos caem umas sobre as outras e não se lê nada.

Os momentos vêm do **programa de Lajes** desta mesma pasta, como o vento vem do
NBR-6123: o solver não refaz o que outro programa já resolve. Daqui sai o que
só o modelo do pórtico sabe — a geometria dos painéis e **quais bordos são
contínuos**, que é derivável: bordo que separa dois painéis é engastado, bordo
que só tem painel de um lado é apoiado.

A geometria das charneiras, essa sim, é traçada aqui — de propósito, para não
quebrar quando o programa de Lajes mudar por dentro. O preço de ter geometria
própria é ter de provar que ela concorda com o cálculo do outro lado, e é o que
o autoteste faz: integra a área de cada região desenhada e compara com as
frações de carga que o programa de Lajes publica, em cinco painéis, inclusive
assimétricos e com bordo livre. As diferenças dão zero.

**A deformada não liga os nós deslocados por retas.** Ela é traçada com as
mesmas funções de forma que o solver usa para o engastamento perfeito, de modo
que a curva desenhada é a que a formulação descreve — inclusive a curvatura
dentro de uma barra carregada, que a ligação por retas esconderia justamente
onde ela interessa. A escala vai escrita no título, porque deformada em escala
real de um pórtico bem projetado é uma linha reta.

**A vista de Armadura mostra o aço de um pavimento no espaço.** Pilares,
vigas e laje daquele nível, cada barra no lugar em que ela fica, sobre o
concreto translúcido — sem essa referência não há como julgar cobrimento
nenhum. Seis famílias, seis cores: longitudinal e estribo do pilar,
longitudinal e estribo da viga, positiva e negativa da laje.

Não se dimensiona nada aqui. Os três motores de elemento já resolveram a
armadura, e o que este programa faz é **pôr essa armadura no lugar dela**,
convertendo a coordenada de seção de cada um para os eixos locais da barra e
daí para o global. São três conversões independentes, e um sinal trocado em
qualquer uma joga a barra para fora da peça sem levantar erro nenhum: por isso
há conferência medindo, para cada barra, a distância ao eixo em fração da
meia-seção. Passou de 1, a barra está no ar.

**Um pavimento por vez, e o número é medido, não estimado.** O edifício de
quatro pavimentos do exemplo tem 1 724 barras longitudinais e 964 estribos, que
dão cerca de 10 000 segmentos de reta; o matplotlib os desenha em 560 ms por
rotação, e a vista abre mas não gira. Um pavimento fica na casa dos 2 000
segmentos — 106 ms —, e aí ela responde ao arrasto do mouse. O recorte não é
arbitrário: é o mesmo que o projeto já usa em planta de fôrma e de armação.

O pilar que entra é o lance **de baixo**, o que termina na cota. É ele que
entrega carga à laje e às vigas mostradas, de modo que o que está na tela é um
caminho de carga fechado; o lance de cima é o desenho do pavimento de cima.

Rodar os três motores custa alguns segundos, e por isso a armadura de cada cota
fica guardada: girar o desenho não redimensiona o prédio de novo. Trocar o
modelo joga fora o que estava guardado.

**"Armadura em DXF" (F3) grava esse mesmo aço em três dimensões**: uma
polilinha 3D por barra, na camada da sua família (`ARM-PILAR`, `ARM-VIGA-EST`,
`ARM-LAJE-POS`…), mais a fôrma em `FORMA` — só o contorno das peças, que é o
bastante para conferir cobrimento no CAD sem dobrar o tamanho do arquivo. Não é
uma planta; é o arame do pavimento no espaço, que é justamente o que não cabe
numa folha. Vale aqui a mesma observação sobre DWG que está mais abaixo.

Um pilar que o motor reprova continua sendo desenhado, com o arranjo da
combinação mais armada e um aviso dizendo que foi reprovado — é no desenho que
se vê por que ele não coube, e apagá-lo esconderia o problema. O que não dá
para desenhar é o lance para o qual nenhum arranjo foi achado, e esse vira
aviso em vez de sumir calado.

### O motor de desenho virou PyVista/VTK (2026-09-30)

Era matplotlib; agora as sete vistas — Modelo, Sólido, Laje, Armadura,
Deformada, os seis diagramas de esforço e Modo de flambagem — usam
PyVista/VTK, o mesmo caminho que Consolos R03 e Lajes R06 já tinham
percorrido. Nada mudou no `core`: a geometria pura (`perfil_da_secao`,
`faces_da_barra`, `faces_da_laje`, `_forma_deformada`, `pontos_do_diagrama`)
é a mesma de sempre, só a representação final trocou de
`Poly3DCollection`/`Line3DCollection` para `PolyData`.

**"Modelo" e "Sólido" ganharam picking** — passe o mouse ou clique num nó ou
numa barra, e ela acende em âmbar enquanto o resto apaga a opacidade; um texto
no canto mostra material, seção e comprimento (ou, para um nó, as coordenadas
e o apoio/mola, se houver). É picking só nessas duas, por enquanto: são as
vistas de conferência de entrada de dados, onde faz sentido perguntar "que
barra é essa"; Deformada e Modo de flambagem continuam esqueleto de linhas,
sem picking, no mesmo estilo visual de antes.

**A seleção sincroniza com a tabela que estiver em foco.** Clicar uma barra
com a sub-aba "Seções" aberta destaca ali a seção daquela barra; com "Barras"
aberta, destaca a própria barra; com "Materiais", o material dela; um nó
sincroniza com "Nós", "Apoios" ou "Molas", o que estiver visível. Sem
correlação (ou nenhuma tabela em foco), só o 3D destaca e mostra o texto — o
que sempre acontece, tabela ou não. Tudo passa por um único método central em
`janela.py` (`_ao_selecionar_elemento`), que decide olhando
`PainelDeDados.subabas`; a lógica de picking em si mora só em `vista3d.py`,
uma vez.

**"Diagrama de esforços" ganhou um botão de representação**: "barras" é o
esqueleto de sempre (linha/tubo escalado pelo valor); "3D" desenha o sólido
extrudado da seção real, com o diagrama traçado ao redor dele — fica óbvio
quando um elemento muito solicitado tem seção pequena. Sem picking em nenhuma
das duas: aqui o assunto é o valor do esforço, não a entrada de dados.

**"Armadura" é a única vista que abre como janela nativa separada do VTK**
(`abrir_vista_interativa_armadura`, botão "Abrir vista 3D da armadura" — só
habilitado com um nível escolhido), não o widget embutido nas outras seis. É
onde o número de segmentos cresce de verdade — um pavimento inteiro de aço —,
e a janela nativa mede ~2 ms por evento de mouse contra ~16 ms do widget Qt
embutido; a mesma medição já feita em Consolos R03 e Lajes R06. O destaque ali
é por **família** de armadura (pilar longitudinal, viga estribo, laje
positiva…), não por barra individual — um pavimento tem milhares de barras, e
detalhar cada uma criaria atores demais para o VTK segurar.

**O `--autoteste` não confere mais um PNG do matplotlib.** Sob
`QT_QPA_PLATFORM=offscreen`, o widget embutido monta a cena inteira sem
problema (`add_mesh`, `reset_camera`, `add_text`, os observadores de picking),
mas `render()`/`screenshot()` não têm janela real para desenhar
(`RenderWindowUnavailable`). A conferência passou a olhar o **conteúdo** da
cena — quantos atores foram desenhados, quantas famílias de armadura foram
identificadas — em vez do pixel renderizado; a janela nativa da armadura é
conferida chamando `construir_cena_armadura` direto, com um `pv.Plotter`
fora de tela, sem nunca chamar `.show()` (que bloquearia o autoteste
esperando um clique que nunca vem).

## O que já faz, e o que ainda não faz

O programa vai da geometria ao detalhamento:

* monta e resolve o pórtico espacial (1ª e 2ª ordem, estabilidade, flambagem
  e modal), com a laje como carga, como diafragma ou como grelha;
* gera as combinações da NBR 6118 e a envoltória com os esforços
  concomitantes;
* dimensiona pilares, vigas e lajes pelos motores copiados;
* emite pranchas DXF, memória em Word e quantitativos em Excel.

Os efeitos locais de 2ª ordem dos pilares são do motor de Pilares (curvatura
aproximada, 15.8.3.3.2).

| Pendência ou expansão futura | Situação |
|---|---|
| Lançamento: mover elemento com o mouse, copiar/espelhar, desfazer, cotas no desenho | pendente; hoje se edita a coordenada no painel de propriedades |
| Lançamento: excentricidade viga–pilar, rebaixo, viga invertida, laje não retangular, abertura, parede sobre laje | pendente; hoje são recusados com o motivo |
| Ponte com Fundações (sapatas, blocos, estacas) | pendente; as reações já saem por apoio |
| **Laje em casca** (elemento finito de placa/membrana no lugar da grelha) | expansão futura — ver abaixo |
| Pilar-parede e núcleo rígido em casca | expansão futura; hoje barra equivalente |
| Espectro de resposta e massa sísmica (NBR 15421) | expansão futura; a modal já existe |
| Edição por clique no desenho 3D | — |
| Análise inelástica e dinâmica no tempo | 6 |

**Laje em casca — expansão futura (registrada em 2026-10-16).** Hoje a laje
entra como carga, diafragma ou grelha de barras. A casca é para os casos em
que a barra não descreve bem a peça:

* laje lisa ou cogumelo, com Mx, My e Mxy diretos e base para a punção;
* rigidez de membrana real, sem o artefato do diafragma rígido, que impede o
  banzo de treliça no plano da laje de alongar (ver a passarela do DNIT);
* ligações largas e curtas, que a ligação pontual barra–grelha subestima (ver
  o TCC do prédio com NDV).

O caminho previsto não substitui o motor de barras, que está validado e é o
que as pontes de dimensionamento entendem. A casca acrescenta um elemento
novo, só na laje, pelo mesmo mecanismo da grelha: um modelo de cálculo
derivado, com o resultado remontado no modelo do usuário. As etapas:

1. Elemento quadrilátero plano de placa e membrana (MITC4 ou DKMQ, com
   rotação no plano), sem travamento em placa fina.
2. Malha regular por painel retangular — os painéis já são retângulos, o que
   dispensa malhador.
3. Ligação com viga e pilar, incluindo a excentricidade laje–viga.
4. Saída para o programa de Lajes (momentos por faixa) e para a punção.
5. Bateria de validação: patch tests, placa de Navier, placa engastada,
   Scordelis-Lo e o confronto com a grelha.

O custo maior está nas etapas 3 e 4, não no elemento. Uma biblioteca pronta
(o `ShellMITC4` do OpenSeesPy, ou scikit-fem) encurta só a etapa 1.

## Segunda ordem e estabilidade global

**A matriz de rigidez geométrica** é a peça de onde saem tanto o P-Δ quanto a
flambagem. Ela é a consistente, deduzida das mesmas cúbicas de Hermite da
rigidez elástica, o que dá o efeito de segunda ordem **dentro** da barra e não
apenas o P-Δ dos nós — mas exige malha para convergir: uma barra por pilar
erra a carga crítica de Euler em cerca de 0,8 %, e duas reduzem isso a menos
de 0,1 %.

**Confrontado com o PyNiteFEA**, biblioteca de elementos finitos
independente, no caso clássico da viga-coluna em balanço (carga axial a 50 %
da crítica) — e foi esse confronto que achou um defeito de verdade, não só
uma diferença de malha. O deslocamento do topo já batia a treze algarismos
com uma barra só (a montagem de `Ke + Kg` e a iteração de Newton estavam
corretas), mas o **momento recuperado na extremidade** errava a solução
fechada em **+6,6 %**, contra 0,15 % do PyNiteFEA na mesma malha grosseira.

A causa não era falta de malha: `_esforcos_das_barras` recuperava o esforço
só com a rigidez **elástica** (`Ke·D`), sem somar a **geométrica** que tinha
corrigido o deslocamento — o `Kg` entrava na montagem e sumia na volta.
Somando-o (`(Ke + Kg)·D`), o erro já cai para 0,13 % **sem tocar em malha
nenhuma**. O resíduo que sobra, esse sim de malha, tem correção própria:
`elemento.rigidez_geometrica_refinada` subdivide a barra só por dentro do
cálculo — condensação estática (Guyan) de sub-elementos, sem nó nenhum que o
usuário veja —, e entra tanto na montagem quanto na recuperação. As duas
correções juntas deixam o caso de referência a **-0,0007 %** do fechado, com
uma barra só — a malha que o assistente usa, um lance por pavimento. A
conferência trava os números de agora, não mais os de antes de corrigir
(`validacao.p_delta_confrontado_com_pynite`).

**A superposição deixa de valer.** Na análise linear dá no mesmo somar as
cargas antes ou as respostas depois; com P-Δ não dá, porque o efeito de uma
ação passa a depender das outras que atuam junto. Por isso cada combinação é
resolvida por si, a partir de um caso de carga com as ações já ponderadas
(`combinacoes.caso_efetivo`). O custo é esse: tantas análises quantas forem as
combinações.

**Carga acima da crítica não tem solução**, e o programa diz isso com essas
palavras em vez de acusar mecanismo — a estrutura está bem vinculada, o que
falta é margem de estabilidade. A análise de flambagem devolve o fator pelo
qual o carregamento cabe antes de a estrutura perder estabilidade.

**γ_z e α** são os dois processos aproximados da norma para decidir se a
análise de segunda ordem pode ser dispensada. Ambos estão implementados com a
numeração desta edição, e há conferência exigindo que classifiquem igual uma
mesma estrutura. O γ_z é ainda cruzado contra o P-Δ: numa estrutura com
γ_z = 1,307 a amplificação do deslocamento de topo pelo P-Δ dá 1,338, 2,4 % de
diferença entre duas formulações que não compartilham nada.

## Bateria cruzada contra o PyNiteFEA, e análise modal (2026-10-01)

**Dez cenários, cada um cruzando o que existir de solução fechada, motor
próprio e PyNiteFEA** (`validacao.py`, seção "Bateria cruzada contra o
PyNiteFEA"): viga biapoiada com carga uniforme e com carga concentrada,
balanço vertical, pórtico plano com travessa flexível, grelha ortogonal com
acoplamento flexão-torção, barra com seção girada, flambagem de Euler
(engastado-livre e biapoiado), apoio elástico, trecho rígido numa ponta, e o
pórtico espacial completo (quatro pilares, quatro vigas e duas barras
inclinadas). O tradutor comum `_pynite_do_modelo` monta o `FEModel3D` a
partir do mesmo `Modelo` desta casa, uma vez só para os dez cenários.

**OpenSeesPy não entrou nesta primeira rodada.** Não por falta de tentativa:
o pacote está instalado (`pip show openseespy` mostra 3.8.0.0), mas o
`opensees.pyd` do `openseespywin` (a dependência Windows) foi compilado
contra `python312.dll` — confirmado abrindo o binário com `pefile` e lendo a
tabela de importação — e esta máquina só tinha Python 3.14. O import falha
com "DLL load failed" antes de montar modelo nenhum; é incompatibilidade de
ABI entre interpretadores, não erro de uso. **Fechado no mesmo dia, numa
segunda passada** (ver a entrada "O terceiro motor — OpenSeesPy, entre
processos" logo abaixo): o usuário instalou um Python 3.12 ao lado, e a
suíte passou a chamá-lo por `subprocess`.

**A armadilha confirmada, e documentada para não se repetir**: o PyNiteFEA
usa, para barra **vertical**, uma convenção de eixos locais y/z trocada em
relação à desta casa. Alimentando a seção do PyNiteFEA com o mesmo par
`Iy`/`Iz` deste programa, a flecha de um balanço vertical sob carga lateral
saía errada por um fator `Iy/Iz` certinho — achado comparando contra a
solução fechada `PL³/3EI`, não só contra o PyNiteFEA. Invertendo os dois na
seção do PyNiteFEA, bateu a treze algarismos. A troca não para na rigidez:
o momento que esta casa chama `Mz` (plano x–y, inércia `Iz`) sai do
PyNiteFEA rotulado `"My"` para barra vertical, e vice-versa — os dois
planos trocam de rótulo inteiro. `_pynite_do_modelo`/`_momento_pynite` já
escondem essa troca do chamador.

O décimo cenário do roteiro original pedia um apoio inclinado (eixo de
restrição rotacionado); nem esta casa nem o PyNiteFEA têm essa primitiva —
implementá-la seria uma funcionalidade nova no solver (a partição de graus
de liberdade teria que ganhar um eixo de restrição não ortogonal ao
global), fora do escopo desta bateria. Foi substituído pelo pórtico espacial
completo, que é mais exigente do que parece: mistura barra vertical,
horizontal e oblíqua, carga nodal, distribuída local e global, e momento
concentrado, tudo no mesmo modelo.

**Análise modal — frequências e modos de vibração livre**
(`core/dinamica.py`), a mesma mecânica de autovalor que
`segunda_ordem.flambagem` já usa, com a matriz de massa consistente no lugar
da geométrica: `Ke·φ = ω²·M·φ`, resolvido direto por
`scipy.linalg.eigh(Ke, M)` — sem a troca de sinal que a flambagem precisa,
porque aqui `M` já nasce positiva definida (massa não é negativa nunca).

A matriz de massa local 12×12 segue a mesma decomposição por família de
graus de liberdade que `elemento.rigidez_local` já usa — axial, torção,
flexão x–y (`Iz`), flexão x–z (`Iy`) —, massa consistente de
Euler-Bernoulli (McGuire/Logan, *A First Course in the Finite Element
Method*, cap. 16.6), com a mesma troca de sinal entre os dois planos de
flexão que a rigidez elástica e a geométrica já fazem.

Três simplificações assumidas nesta rodada, documentadas no próprio módulo
e não escondidas:

* **massa sem Timoshenko** — a matriz consistente é só a de Euler-Bernoulli,
  mesmo quando a seção declara área de cisalhamento e a rigidez elástica já
  tem a correção;
* **só massa própria** — nenhuma carga permanente ou acidental vira massa
  sísmica nesta rodada; a NBR 15421 teria regra própria para isso, que fica
  para quando houver espectro de resposta;
* **sem trecho rígido pesado** — a massa é calculada sobre o vão flexível,
  do mesmo jeito que a rigidez; a massa que fisicamente estaria no trecho
  rígido não entra à parte.

**Confrontada contra a fórmula fechada de viga em balanço**
(`ωn = (βnL)²·√(EI/(ρAL⁴))`, três primeiras raízes de
`cos(βL)·cosh(βL) = -1`): os três primeiros modos de flexão no plano
conferido batem dentro de 5·10⁻⁴ com 16 barras de malha — o terceiro modo
de flexão exige essa malha mais fina para convergir, o mesmo efeito que já
aparece na flambagem, só que aqui sem uma versão "refinada" por dentro do
cálculo. O confronto contra `ops.eigen()` do OpenSeesPy, pedido no roteiro
original, fechou na segunda passada do mesmo dia — ver abaixo.

A interface ganhou "Análise ▾ → Modal", ao lado de "Flambagem", desenhando o
modo de vibração escolhido em "Modo de vibração" (lista `VISTAS`) com o
mesmo esqueleto de linhas de "Modo de flambagem" — o título mostra
frequência e período em vez de fator crítico.

### O terceiro motor — OpenSeesPy, entre processos (2026-10-01, segunda passada)

O Python 3.12 que faltava acima entrou na mesma máquina, ao lado do 3.14
principal, e o `openseespy` (3.8.0.0) importa nele sem problema
(`py -3.12 -c "import openseespy.opensees as ops; ops.wipe()"` funciona).
Como o `openseespy` continua incompatível com o Python 3.14 deste programa,
a integração é **entre processos**, não um import direto: um script
autocontido, `portico3d/core/opensees_ponte.py`, roda sob `py -3.12`,
recebe a descrição de um modelo por JSON na entrada padrão e devolve
deslocamentos, reações, esforços de barra e (no modo modal) frequências e
modos por JSON na saída padrão. Do lado 3.14, `validacao.py` (seção 44, logo
depois da bateria de dez cenários) chama esse script com
`subprocess.run(["py", "-3.12", caminho, ...], input=json, ...)` — nenhum
código em Python 3.14 importa `openseespy` direto. `_opensees_disponivel()`
testa a disponibilidade antes de cada confronto; se `py -3.12` ou o pacote
não existirem noutra máquina, a conferência é pulada com um aviso claro, em
vez de derrubar a suíte.

**Seis dos dez cenários ganharam o terceiro motor** — os que fazem sentido
para ele: 4 (pórtico plano), 5 (grelha), 6 (seção rotacionada), 8 (apoio
elástico), 9 (trecho rígido, traduzido para `geomTransf(..., '-jntOffset',
...)` — o OpenSeesPy tem essa primitiva, ao contrário do PyNiteFEA) e 10
(pórtico espacial completo). Todos batem contra o motor próprio a 1e-6 ou
melhor (a maioria a 1e-13/1e-15). Os cenários 1–3 continuam só com o
PyNiteFEA — são vigas isoladas, sem nada que o OpenSeesPy testasse de
diferente dos outros sete.

**Convenção de eixo local — medida, não suposta.** Ao contrário do
PyNiteFEA (que troca `Iy`/`Iz` e os rótulos `My`/`Mz` em barra vertical), o
OpenSeesPy **não precisa de troca nenhuma**, desde que o `vecxz` que ele
pede seja o eixo local z **desta casa** (linha `ez` de `matriz_rotacao`, em
coordenadas globais) — confirmado com um balanço vertical e um balanço
horizontal sob carga lateral, comparando a flecha do OpenSeesPy com
`PL³/3EI` nas duas ordens possíveis de `Iy`/`Iz`; só a ordem sem troca bateu
a 1e-12, nos dois casos. `_opensees_payload_do_modelo`/`_momento_opensees`
não fazem troca de rótulo nenhuma — ao contrário dos nomes gêmeos do lado
PyNiteFEA, que fazem.

**Pegadinha de API achada na marra**: `ops.eleForce(tag)` devolve a força do
elemento em coordenadas **globais**, não locais — ficou claro comparando o
balanço vertical contra a reação de apoio (os dois vetores saíam idênticos,
o que só acontece sem rotação nenhuma de eixo). Quem dá as coordenadas
locais de verdade é `ops.eleResponse(tag, "localForce")`; é o que o
script-ponte usa.

**Análise modal confrontada contra `ops.eigen()`**: fechou. Outra pegadinha
de API, também achada na marra e confirmada com um teste isolado antes de
entrar na suíte: `elasticBeamColumn` não gera massa nenhuma sozinho — sem
`'-mass', massa_por_comprimento, '-cMass'` na chamada de `element(...)`, o
`ops.eigen()` falha com `ArpackSolver::Error ... Starting vector is zero`
(matriz de massa nula), em vez de dar um resultado errado silenciosamente.
Com a massa declarada (`ρA` por comprimento, `-cMass` para a matriz
consistente — a mesma formulação de `massa_local` desta casa), os três
primeiros modos do plano x–y do balanço em 16 barras batem com o OpenSeesPy
a 2·10⁻⁷, 5·10⁻⁶ e 4·10⁻⁵ de erro relativo (o terceiro modo é o que mais
precisa de malha fina para convergir, o mesmo efeito já visto contra a
fórmula fechada).

**A flambagem (cenário 7) não ganhou o terceiro motor, e não é pendência —
é limite medido do OpenSeesPy.** Checado contra a documentação oficial antes
de tentar qualquer sintaxe: a página de integradores estáticos do OpenSees
(`opensees.github.io/OpenSeesDocumentation`) lista só quatro —
`LoadControl`, `DisplacementControl`,
`MinimumUnbalancedDisplacementNorm` e `Arc-Length` — sem nenhum
`LinearBucklingIntegrator`, que não existe na distribuição oficial. O
próprio time do OpenSees confirma por quê (blog de um dos mantenedores,
"Ordinary Eigenvalues", `openseesdigital.com`, e o fórum oficial): não há
`getGeometricTangentStiff()` implementado para elemento de pórtico — só
elementos de fluido PFEM o implementam —, então não existe matriz
geométrica de barra para montar o autovalor de estabilidade. O único
"jeito" documentado de arrancar flambagem do `eigen()` é um truque de massa
fictícia válido só para uma coluna isolada, não uma funcionalidade de
flambagem de verdade — não serve para generalizar nem foi usado aqui. O
confronto do cenário 7 continua motor próprio × Euler fechada, como antes.

**requirements.txt** ganhou a receita de instalação do Python 3.12 separado
e o caminho do script-ponte, para quem for reproduzir noutra máquina.

### Análise modal em edifícios inteiros, com pareamento de modo por MAC (2026-10-01, terceira passada)

A análise modal acima (seção "Análise modal — frequências e modos de
vibração livre") só tinha sido confrontada num cantilever isolado de 16
barras, um plano de flexão por vez. O que faltava — e o que de fato testa a
formulação num caso realista — é um **edifício inteiro**: vários modos de
frequência próxima, e, em planta assimétrica, modos **acoplados**
(translação e torção na mesma forma). É aí que comparar só "modo 3 com modo
3" pode mascarar um erro de verdade, ou, ao contrário, acusar divergência
onde os dois motores só acharam os mesmos modos em ordem diferente.

`validacao.py`, seção 45 ("Análise modal em edifícios inteiros — pareamento
de modo por MAC"), monta quatro edifícios pela API crua do `Modelo` (grelha
retangular de pilares e vigas de concreto C30, com peso específico de
verdade) e confronta cada um contra `ops.eigen()`:

1. **Pequeno, 2×2 vãos de 5 m, 2 pavimentos** — calibração. Duplamente
   simétrico em planta, serve para conferir que o caso trivial bate quase
   exato antes dos difíceis. Frequência fundamental 4,9608 Hz (motor
   próprio) × 4,9609 Hz (OpenSeesPy), 0,003 % de diferença.
2. **Alto, mesma planta, 10 pavimentos** — o desafio é numérico: mais graus
   de liberdade, frequências mais próximas nos modos de ordem alta. De fato
   o par fundamental sai em ordem trocada entre os dois motores (modo 1-2 no
   motor próprio, 2-1 no OpenSeesPy) — o MAC resolve isso antes de comparar
   frequência. Fundamental 1,0151 Hz nos dois motores.
3. **Com balanço, 3×2 vãos, 6 pavimentos**, com 2 m de viga em balanço além
   da última linha de pilares em X, sem apoio na ponta, em toda a altura —
   testa se a massa do trecho em balanço (inércia sem apoio próximo) entra
   certa nos dois motores. Fundamental 1,6154 Hz nos dois. A quebra de
   simetria em Y que o balanço introduz já acopla translação Y com torção em
   quase todos os modos.
4. **Assimétrico, 3×3 vãos, 8 pavimentos**, planta em L (falta o pilar do
   canto) e um pilar 60×60 no canto oposto (os demais são 30×30) —
   desloca o centro de rigidez para longe do centro de massa de propósito.
   Fundamental 1,2795 Hz nos dois motores.

**Pareamento de modo pelo MAC** (Modal Assurance Criterion,
`MAC(i,j) = (φᵢᵀφⱼ)²/((φᵢᵀφᵢ)(φⱼᵀφⱼ))`, só nos graus de liberdade de
translação — evita ter que escalar rotação contra translação para comparar):
em todos os quatro edifícios, todo par de modo pareado bateu com
**MAC ≥ 0,99** (a maioria exatamente 1,0000) e erro de frequência **≤
0,011 %** — muito abaixo da tolerância de 0,2 % usada nas conferências
permanentes.

**Classificação do modo** (translação X, Y, torção, ou combinação): em vez
de olhar o maior componente num nó qualquer (frágil contra a malha),
`_classificar_modo` ajusta por mínimos quadrados um campo de corpo rígido no
plano do pavimento mais alto (`ux = u0x − θ(y−y0)`, `uy = u0y + θ(x−x0)`) e
compara a translação pura do centro com o giro equivalente na borda
(`|θ|·R`) — a mesma unidade, o que `θ` sozinho não tem contra `u0x`/`u0y`.

**O edifício 4 confirma o que a torção pede de verdade**: dois modos saem
claramente torsionais (giro equivalente dominante, translação do centro
quase nula) — modo 3 (1,4327 Hz) e modo 9 (4,3668 Hz) — e os **dois
motores concordam que são torção**, não translação disfarçada, com MAC ≈
1,0000 e erro de frequência ≤ 0,002 % nos dois pares.

**Achado que não é erro, e vale registrar para não se confundir depois**:
o edifício 1, duplamente simétrico, tem pares de modo **degenerados** (mesma
frequência — translação X e translação Y, por exemplo, viram uma base
arbitrária dentro do mesmo subespaço bidimensional). O MAC *individual* de
um modo assim pode cair bem abaixo de 1,0 (medido: 0,7934 no par mais alto,
14,16 Hz) sem que isso seja divergência nenhuma — conferido à parte
reconstruindo um modo do motor próprio como combinação linear do par
degenerado do OpenSeesPy: o resíduo relativo fica em 5·10⁻⁵, ou seja, o
**subespaço** bate quase exato, só a base escolhida por cada `eigh`/
`eigen()` dentro dele é diferente. Por isso a conferência permanente do
edifício 1 pede só os 6 primeiros modos — já cobrem translação X, Y e
torção, e o par degenerado mais alto (que exigiria comparar subespaço, não
vetor a vetor) fica de fora por não ser necessário ao que a bateria promete.

Os quatro edifícios rodam em menos de meio segundo cada (malha pequena mas
genuína — grelha completa, sem redução de porte); viraram quatro novas
funções em `validacao.py` (`edificio_modal_pequeno_opensees`,
`edificio_modal_alto_opensees`, `edificio_modal_balanco_opensees`,
`edificio_modal_assimetrico_opensees`), seguindo o mesmo padrão de pulo
gracioso (`_opensees_ou_pulado`) das demais conferências contra o
OpenSeesPy.

### Massa adicional por caso de carga, e o confronto com a passarela do DNIT (2026-10-01, quarta passada)

Até aqui a análise modal só sabia somar a massa das próprias barras
(`matriz_massa_global`). Isso basta para edifício, onde a laje já entra pela
espessura do pilar/viga ou nem entra. Não basta para uma passarela metálica:
o tabuleiro (steeldeck + capa de concreto) pesa em cima da treliça sem ser
barra nenhuma.

**A capacidade nova**, em `core/dinamica.py`:

* `massa_adicional_global(modelo, preparadas, casos)` reaproveita
  `montagem.vetor_cargas` para montar o vetor de cargas equivalente de cada
  caso pedido, toma a componente Fz (a direção da gravidade) de cada nó e
  divide por `GRAVIDADE` — é peso de um caso de carga já existente, virando
  massa por `F/g`, sem entidade de dados nova nenhuma. A massa entra igual
  nos três graus de translação (não tem direção), e não entra nos de
  rotação.
* `analisar_modal` ganhou o parâmetro `casos_de_massa: tuple[str, ...] = ()`;
  vazio (o padrão), o caminho é bit a bit igual ao de antes — é essa a prova
  de que a capacidade é aditiva, não um desvio por baixo do que já existia.
  As **553 conferências do autoteste continuaram passando sem mudar um
  número**, rodadas de novo depois da mudança.

**O benchmark**: a passarela metálica PL-35 do DNIT (treliça espacial
Warren, vão de 35 m, dois eixos de treliça plana afastados 2,5 m, altura
2,5 m, 14 painéis de 2,5 m, sem montante nos painéis internos), remontada do
zero pela API crua do `core` em `exemplos/passarela_dnit.py`, com os perfis W
da memória de cálculo do projeto (W360x72 no banzo superior, W360x44,6 no
inferior, W200x35,9 nas diagonais, aço A572 Grau 50) e confrontada contra as
duas frequências que o projeto publica (Tabela 3.1 do Volume 2, SAP2000):
3,21 Hz de flexão vertical e 5,58 Hz de flexão transversal.

A malha bateu com a contagem esperada antes de rodar modal nenhum: **60 nós,
174 barras** (2 eixos × 30 nós cada; por eixo, 14 barras de banzo inferior +
14 de superior + 14 diagonais do zigue-zague + 2 montantes de apoio, mais
15×2 transversais entre eixos e 14×2×2 diagonais de contraventamento em X).

O peso do tabuleiro não está fechado em número no documento — só o SAP2000
original sabia, pela casca que alguém modelou lá. Aqui ele é o parâmetro de
calibração: um caso de carga `"TABULEIRO"`, nodal nos nós de banzo inferior
pela área de influência (tributário 2,5 m nos nós internos, 1,25 m nas
pontas), virando massa pela capacidade nova.

**Resultado — bateu bem numa frequência, não bateu na outra, e por um motivo
identificável, não por acaso**:

* **Flexão vertical**: com a hipótese inicial de 8 cm de capa de concreto, o
  modelo deu 3,74 Hz contra 3,21 Hz do documento — 16,7 % acima. Calibrando
  só a espessura da capa (varredura de 6 a 16 cm, ajuste de f² linear em
  espessura), **13,7 cm reproduz 3,21 Hz com -0,46 % de erro** — espessura
  de capa perfeitamente plausível para um tabuleiro de steeldeck MF-75 numa
  passarela.
* **Flexão transversal**: em toda a varredura de espessura, o modelo ficou
  entre 51 % e 63 % ABAIXO dos 5,58 Hz publicados, e calibrar a espessura
  pela vertical (13,7 cm) não aproxima a transversal — afasta mais um pouco
  (-60,5 % de erro). Isso não é problema de massa: é falta de **rigidez**
  transversal. Testado à parte (não persistido): multiplicar por 5 a área
  do contraventamento em X quase não mexeu na frequência transversal — a
  rigidez que falta não está nos perfis de aço aproximados por catálogo
  (M01, TS01, TI01, CS01/CI01). O suspeito mais plausível é o que este
  motor **nunca modela**: a capa de concreto como diafragma rígido no
  próprio plano — a mesma ressalva que `Laje` já registra em `modelo.py`
  ("a laje não trabalha como diafragma"). A flexão vertical depende
  sobretudo da rigidez axial das cordas (bem capturada aqui, daí o bom
  ajuste); a flexão transversal, nesta geometria, depende da treliça
  resistir como viga deitada com as duas cordas longitudinais fazendo de
  mesa a 2,5 m uma da outra — e é exatamente aí que a rigidez de diafragma
  do tabuleiro, modelada só como massa por desenho desta capacidade,
  contaria muito e está ausente.

Perfis aproximados por falta de dado no documento (não extraídos do Volume
1/2, montados por catálogo compatível com a massa linear informada): M01
(montante de apoio), TS01 e TI01 (transversais), e a cantoneira dupla
CS01/CI01 do contraventamento (aproximada como seção maciça equivalente de
mesma área). Nenhum deles, isoladamente, explica o gap da transversal (ver o
teste de sensibilidade acima) — o que pesa é a ausência estrutural do
diafragma, não a aproximação de um perfil específico.

A varredura completa, os dois achados e a comparação lado a lado ficam em
`exemplos/passarela_dnit.py` — rodar com `py exemplos/passarela_dnit.py`.

### Dois TCCs contra a análise modal — vigas do Lima e o edifício do Nascimento (2026-10-02)

Mais dois confrontos contra literatura acadêmica, no mesmo espírito do PyNite,
do OpenSeesPy e da passarela do DNIT: resolver os mesmos modelos que um
trabalho publicado resolveu e comparar número a número — sem arredondar o
que não bateu.

**Lima (TCC UnB, 2019) — viga biapoiada e viga engastada-livre**, aço
(E = 2×10⁸ kN/m², ν = 0,3, peso específico 76,982 kN/m³ — o valor exato do
documento, não o padrão de 78,5 kN/m³ da casa), seção 0,1×0,3 m, vão de 4,0 m
(não escrito no texto, mas retrocalculado da própria frequência publicada
contra a fórmula fechada do autor — bate em 4,0 m exato nos dois casos),
remontados em `exemplos/lima_vigas.py`, 16 elementos por vão:

* **1º modo: bateu bem nos dois casos** — biapoiada 42,9153 Hz contra
  42,512 Hz publicados (+0,95 %); engastada-livre 15,2884 Hz contra
  15,221 Hz (+0,44 %).
* **2º e 3º modos, tomados pelo valor publicado: "não batem"** — biapoiada
  171,66 Hz contra 123,08 Hz publicados (+39,5 %) e 386,27 Hz contra
  192,16 Hz (+101 %); engastada-livre 95,81 Hz contra 77,754 Hz (+23,2 %) e
  268,28 Hz contra 159,645 Hz (+68,1 %). **Mas a causa não é deste motor**
  — ver o achado abaixo.

Achado, confirmado por conferência cruzada (reler o relatório do agente que
gerou este script antes de aceitar "gap inexplicado"): os modos calculados
aqui seguem **exatamente** a razão clássica de Euler-Bernoulli entre
harmônicos — 1:4:9 para biapoiada (42,9153 × 4 = 171,661, × 9 = 386,24,
batendo com o calculado até a 3ª casa) e 1:6,267:17,55 para engastada-livre
(15,2884 × 6,267 = 95,83, × 17,55 = 268,31 — as mesmas razões de
`validacao.modal_viga_em_balanco`, as raízes de cos(βL)cosh(βL) = -1). Essa
razão é **a mesma fórmula fechada que o próprio documento diz ter usado**
para validar seu modelo ANSYS (equações 15-20 do TCC, reproduzidas no
docstring deste script). Só que os números publicados **não seguem essa
razão**: 123,08/42,512 = 2,895 (não 4) e 192,16/42,512 = 4,521 (não 9);
77,754/15,221 = 5,108 (não 6,267) e 159,645/15,221 = 10,49 (não 17,55).
Ou seja, se as frequências publicadas fossem de verdade o 2º e 3º harmônico
de flexão vertical da mesma viga, elas teriam de respeitar a mesma razão que
o próprio autor usa para validar o 1º modo — e não respeitam. A explicação
mais provável não é um defeito deste motor (que reproduz a teoria à risca,
inclusive confirmado contra Timoshenko à parte — a correção por cisalhamento
desloca o 2º modo da biapoiada de 171,66 para só 166,95 Hz, longe de cobrir
o gap de 39,5 %): é que o 2º/3º "modo de flexão vertical" que o TCC extraiu
do ANSYS Workbench **não é** o 2º/3º harmônico puro — é comum, em um
elemento de pórtico 3D genérico (BEAM188/BEAM4, 6 GDL/nó) sem o cuidado de
filtrar por direção, a lista de modos ordenada por frequência intercalar
modos de flexão no eixo forte com os do eixo fraco, axiais e torcionais, e
um trabalho de graduação confundir qual é qual ao ler a interface do
software — exatamente o tipo de armadilha que `classificar_modos_verticais`
neste script existe para evitar, e que o próprio TCC não documenta ter
filtrado. O 1º modo, que não sofre dessa ambiguidade (é sempre o mais baixo
de todos, não há com o que confundir), bateu bem nos dois casos — e é o
que a maioria dos trabalhos usa como validação principal.

**Nascimento (TCC UFSM, 2025) — edifício de 12 pavimentos, sem alvenaria
participante** (simulações 1, 2 e 5 do documento — a diagonal de Mainstone
fica de fora desta rodada). Grelha de 15 pilares (5×3, vãos de 6 m), pé-direito
3 m, 12 pavimentos; pilares 50×50 cm na linha Y = 6 m e 40×40 cm nas linhas
Y = 0/12 m; vigas 20×60 cm nas duas direções; dois concretos com EI reduzido
simplificado (NBR 6118:2023, 15.7.3) via E — pilar a 0,8 EI, viga a 0,4 EI —
C40 nos dois primeiros lances/pisos, C25 do 3º ao 12º; peso específico
24,516625 kN/m³ (2500 kgf/m³ × 9,80665, não os 25 kN/m³ padrão da casa).
Massa pela capacidade de `casos_de_massa`: parede (310 kgf/m² × 2,40 m =
7,296 kN/m) em todas as vigas, revestimento (100 kgf/m² = 0,980665 kN/m²,
40 kgf/m² = 0,392266 kN/m² na cobertura) repassado pelas lajes via
`lajes.aplicar_lajes` — que já soma o peso próprio da espessura (13 cm) ao
revestimento antes de ratear pela área de influência, decisão de modelagem
registrada no cabeçalho de `exemplos/nascimento_edificio.py`. Malha
conferida antes do modal: **195 nós, 444 barras, 96 lajes** (pórtico
espacial) e **39 nós, 60 barras** (pórtico plano).

*Pórtico plano (a linha de pilares P3-P8-P13, X = 12 m — confinado ao plano
Y-Z restringindo ux, ry, rz em TODOS os nós, não só nos apoios, porque uma
barra isolada fora do plano fica mecanismo nessas três direções)*:
simulações 2 e 5 do documento, que diferem só no método de ratear a carga
de laje nas vigas — "método 1" (metade para cada viga) contra "método 2"
(charneiras/área de influência). **Os dois métodos colapsam no mesmo número
aqui**: os painéis adjacentes a este pórtico são quadrados (6×6 m), e para
painel quadrado a fórmula de área de influência de `lajes.distribuir`
("quinhão = q·lx·(2·Le−lx)/4") cai exatamente no triângulo simétrico que o
rateio por metade também daria — é a mesma coincidência que o próprio
documento registra (Tabela 6: os dois métodos batem entre si a menos de
0,1 % para este edifício). Por isso um modelo só foi confrontado com os
dois alvos:

* modo 1: 0,4214 Hz × 0,3434/0,3435 Hz publicados → **+22,7 %**
* modo 2: 1,3013 Hz × 1,0591/1,0594 Hz → **+22,9 %**
* modo 3: 2,2955 Hz × 1,8609/1,8620 Hz → **+23,3 %**

As **razões entre os três modos batem quase exatas** com o documento
(1,3013/0,4214 = 3,088 contra 1,0591/0,3434 = 3,085; 2,2955/0,4214 = 5,447
contra 1,8609/0,3434 = 5,419) — prova de que são o mesmo trio de modos (o
1º, 2º e 3º harmônico de flexão do pórtico no plano Y-Z), não um descompasso
de identificação de modo.

**Bug real encontrado e corrigido na revisão deste resultado**: a primeira
versão de `carga_tributaria_laje_quadrada` (a função que reproduz à mão a
fórmula de `lajes.distribuir` para o pórtico reduzido a um plano, que não
tem as 4 vigas de contorno reais que o mecanismo `Laje` exige) desenhava só
a **metade** do triângulo de carga — a rampa de subida (0 ao meio do vão),
sem a rampa de descida simétrica (do meio ao fim do vão) que
`lajes.distribuir` sempre fecha, mesmo quando o patamar do meio desaparece
para painel quadrado. Isso aplicava só metade da força total que cada
painel deveria repassar à viga — um fator 2 faltando bem na massa
tributária da laje, a maior parcela da massa adicional deste modelo.
Corrigido acrescentando a segunda rampa (ver o código), o erro caiu de
**+37 % para +23 %** nos três modos — confirma que a causa raiz era mesmo
massa faltando, e que a maior parte dela já foi encontrada.

**O que ainda falta para fechar os ≈ 23 % restantes**: comparando o pórtico
plano (corrigido) contra o **próprio** pórtico espacial deste programa (não
contra o documento) — 0,4214 Hz contra 0,3493 Hz, 20,6 % de diferença —, fica
claro que a divergência não é mais só contra a literatura, é entre os dois
modelos deste mesmo motor que deveriam descrever a mesma linha de pórtico.
O pórtico espacial usa o mecanismo `Laje`/`aplicar_lajes` de verdade (código
já validado por anos de conferências) e bate o 1º modo do documento a
-1,01 % — é o lado confiável. O pórtico plano precisa reconstruir a laje à
mão porque está reduzido a um plano sem as 4 vigas de contorno, e é nessa
reconstrução manual que ainda deve morar o resíduo (um candidato óbvio,
ainda não conferido: o pórtico plano não tem como saber que as vigas X desse
mesmo nó, no edifício de verdade, também carregam uma fração da parede e da
laje que o modelo plano não tem onde pôr — mas essa parcela deveria ser nula
num corte exatamente pelo eixo do pórtico, não precisa de mais investigação
sem reabrir o modelo). Fica como pendência menor — o achado principal (o
bug do triângulo pela metade) já está corrigido, e o caminho confiável
(pórtico espacial, modo 1) já valida a capacidade de massa adicional em
escala de edifício real.

*Pórtico espacial (simulação 1, o edifício inteiro em 3D)*: o 1º modo
(translação pura em Y, sem torção) bateu bem — 0,3493 Hz contra 0,3529 Hz
publicados (**-1,01 %**). Mas os modos 2 e 3 calculados aqui, tomados
literalmente na ordem que `analisar_modal` devolve, são **translação em X**
(0,3749 Hz) e **torção** (0,4018 Hz) — não são o 2º e 3º harmônico de
flexão em Y que a comparação do pórtico plano (acima) deixa claro ser o que
o documento publica (as razões 1,0815/0,3529 = 3,065 e 1,8920/0,3529 = 5,362
são praticamente as mesmas do pórtico plano). Uma varredura de 20 modos não
achou uma sequência limpa de harmônicos só-translação-em-Y além do 1º e do
5º (f = 0,6513 Hz) — a torção se mistura com a translação a partir do 2º
harmônico, ao contrário do pórtico plano (que não tem torção nenhuma, por
construção). Isso é consistente com uma explicação já registrada nesta
mesma seção para a passarela do DNIT: **a laje aqui nunca é diafragma**
(`Laje`, em `core/modelo.py`, só entrega carga, nunca rigidez no próprio
plano) — na estrutura real, a laje de concreto (mesmo sem alvenaria
participante) amarra as prumadas e enrijece a torção e a translação em X o
bastante para que o 2º e 3º modo do edifício inteiro continuem sendo
harmônicos de Y, em vez de aparecer torção e X-translação intercaladas tão
cedo quanto o 2º modo. Por isso a comparação direta modo-a-modo do pórtico
espacial contra a Simulação 1 não é honesta além do 1º modo — e por isso o
pórtico plano (que não sofre dessa ambiguidade, por não ter X nem torção) é
a comparação que vale mais aqui.

**Pendência, revisada**: a causa principal do excesso (o triângulo de carga
pela metade, ver acima) já foi encontrada e corrigida — caiu de ≈ 37 % para
≈ 23 %. O resíduo de ≈ 23 % continua sem causa identificada com certeza, mas
agora está isolado: é um desacordo entre os dois modelos **deste mesmo
programa** (pórtico plano × pórtico espacial, 0,4214 × 0,3493 Hz), não mais
entre o programa e o documento — e o lado espacial, que usa o mecanismo
`Laje` de verdade em vez da reconstrução manual, já bate o 1º modo publicado
a -1,01 %. Quem for investigar o resíduo deve olhar a reconstrução manual da
carga de laje no pórtico plano (`carga_tributaria_laje_quadrada`), não o
motor `analisar_modal`/`casos_de_massa`, que já se mostrou correto nos dois
outros benchmarks de edifício (os 4 edifícios de ontem e o pórtico espacial
de hoje).

Os dois scripts completos, com a malha conferida antes do modal e a
comparação lado a lado, ficam em `exemplos/lima_vigas.py` e
`exemplos/nascimento_edificio.py` — rodar com `py exemplos/lima_vigas.py` e
`py exemplos/nascimento_edificio.py`. As 553 conferências do autoteste
continuam passando sem mudar um número — nenhum arquivo de `core` nem
`validacao.py` foi tocado nesta rodada, só os dois scripts novos em
`exemplos/`.

### Mais dois trabalhos contra a análise modal — dissertação de identificação modal e TCC do prédio com NDV (2026-10-16)

**Dissertação "Aplicação de métodos no domínio da frequência"**
(`exemplos/dissertacao_vigas.py`).

O trabalho é de identificação modal por sinal (PP e FDD), e só dois dos seis
casos dele têm estrutura descrita:

* Os "Casos Controle" são sinais sintéticos.
* As pontes PI-57 e PK075+317 trazem só as frequências de referência, sem
  geometria, seção nem material.

| Viga | Referência | Programa |
|---|---|---|
| Numérica, 6 m (E = 210 GPa, A = 2,81·10⁻³ m², I = 1,845·10⁻⁸ m⁴) | 0,58 / 2,31 / 5,21 Hz | 0,5783 / 2,3131 / 5,2045 Hz — fórmula fechada a 0,00 %, valor publicado (arredondado) a 0,3 % |
| COPPE, 1,46 m, 76,2 × 8,0 mm | analítica 8,59 / 34,34 / 77,27 / 137,37 / 214,64 Hz | idem, até a última casa (com A e I arredondados como a dissertação os publica) |

Para os ensaios da COPPE, o programa fica onde a fórmula fica:

* **Vibração aleatória:** −7,1 / +3,3 / +4,7 / +1,0 / +9,2 %.
* **Impacto:** +3,2 / +3,2 / +5,5 / +1,5 %.

São as mesmas diferenças que a dissertação mostra entre fórmula e ensaio. A
diferença é de ensaio (apoio real, massa do acelerômetro), não de modelo.

**TCC "Simulação de edifício esbelto com neutralizador de vibrações"**
(`exemplos/tcc_edificio_ndv.py`).

O protótipo é um prédio de quatro pavimentos em escala:

* chapas de aço de 220 × 150 × 11,5 mm, de 3,0 kg;
* barras chatas de 19 × 2,75 mm, com 250 mm livres entre as chapas;
* um NDV em pêndulo invertido no topo: um cubo de 1,382 kg sobre uma haste
  inox de 71 × 26 × 0,9 mm.

O TCC compara três ferramentas: um modelo de cisalhamento no Octave e sólidos
no SolidWorks e no ANSYS. O NDV entrou sem mudar nada no programa, só com
barra, trecho rígido e massa de caso de carga:

* a haste é uma barra engastada no centro da chapa do topo;
* o cubo é uma barra rígida sem peso, com metade da massa em cada um de dois
  nós a `±a/√6` do centro. É o par que tem a massa e a inércia de rotação do
  cubo.

| | Programa | × SolidWorks | × ANSYS | × Octave |
|---|---|---|---|---|
| Primário, chapa rígida | 4,312 / 12,470 / 19,243 / 23,733 Hz | −0,2 a −0,3 % | −1,2 a −1,5 % | −1,8 a −3,5 % |
| Primário, chapa em grelha | 4,286 / 12,412 / 19,192 / 23,715 Hz | −0,4 a −0,8 % | −1,3 a −2,1 % | −1,9 a −4,1 % |
| NDV isolado, haste como viga | 3,990 Hz | −2,9 % | −4,1 % | (teórico −1,2 %) |
| NDV isolado, haste como lâmina | 4,186 Hz | +1,9 % | +0,7 % | (teórico +3,6 %) |
| Global, chapa rígida, haste como lâmina | 3,459 / 5,117 / 12,472 / 19,175 / 23,699 Hz | −0,3 a +0,5 % | −1,3 a −0,1 % | — |

O que esses números ensinam:

* **O Octave fica acima dos três modelos de elementos finitos.** Ele usa a
  massa equivalente do pilar concentrada (3,0973 kg por pavimento). A massa
  consistente daqui concorda com os sólidos e não com ele.
* **A haste é lâmina, não viga.** Com 26 mm de largura para 0,9 mm de
  espessura e 71 mm de comprimento, ela flete entre a viga (módulo E) e a
  placa em flexão cilíndrica (E/(1−ν²), 9,9 % mais rígida), porque a largura
  contém a curvatura anticlástica. Os dois CAD caem entre esses dois limites.
  Com a leitura de lâmina, o sistema global bate com o SolidWorks a 0,5 %.
* **A chapa rígida é a leitura certa deste protótipo.**
  * Na grelha, o pilar se liga à chapa num nó só. No sólido, a barra chata de
    19 mm fica colada ao longo da chapa.
  * Na direção fraca isso custa 0,5 %. Na forte, o modo em Y cai para 22,8 Hz
    e entra entre os quatro primeiros, o que o SolidWorks não mostra.
  * Com a chapa rígida, a torção (24,9 Hz) e o modo em Y (26,7 Hz) ficam
    acima dos quatro de direção fraca, como no TCC.
  * É um limite da ligação pontual barra–grelha, que vale anotar para
    ligações curtas e largas.

De passagem, a modal ganhou um recurso de reserva: no caminho esparso, se o
Lanczos não converge (sistema pequeno e quase todo sem massa), ela condensa os
graus sem massa e resolve denso.

## Modelagem

**Liberações de extremidade.** Cada barra pode soltar qualquer dos seis graus
de liberdade locais em cada ponta. A rótula de viga metálica é
`liberacoes_j=("ry", "rz")`. A implementação é condensação estática — a
rótula não é artifício de montagem, é a condição de esforço nulo naquela
extremidade —, e a condensação corrige **também o vetor de engastamento
perfeito**, sem o que o momento de uma engastada-apoiada sob carga uniforme
não daria wL²/8. Liberar o mesmo esforço axial ou de torção nas duas pontas
solta a barra por inteiro, e o programa recusa dizendo isso.

**Carga distribuída** pode cobrir um trecho qualquer da barra e variar
linearmente entre as pontas: `inicio` e `fim` em posição relativa de 0 a 1, e
`qx_fim`, `qy_fim`, `qz_fim` para o trapézio. As forças de engastamento
perfeito saem da integral das funções de forma por quadratura de Gauss de
quatro pontos — exata, e não aproximada, porque o integrando é no máximo do
quarto grau.

**Apoios elásticos e recalques.** A mola é rigidez concentrada num nó, nos
eixos globais, e a sua reação entra no equilíbrio global. O recalque é
deslocamento **prescrito**, e mora no caso de carga porque é uma ação: entra
nas combinações com o seu próprio coeficiente. Prescrever deslocamento onde
não há vínculo é recusado.

**Deformação por cortante.** Declarando `Asy` e `Asz` na seção — ou pedindo
`Secao.retangular(..., cortante=True)` —, a flexão passa a ser a de
Timoshenko. Sem elas, que é o padrão, continua a de Euler-Bernoulli. O padrão
é esse de propósito: a parcela de cortante só pesa em peça baixa e alta (num
balanço de 1,5 m com seção de 50 cm ela vale 8,7 % da flecha; numa viga
esbelta some), e ligá-la sozinha mudaria calados os resultados de todo modelo
já feito.

As funções de forma usadas no engastamento perfeito são as de Timoshenko, e
não as cúbicas puras — se a rigidez fosse de uma barra e o vetor de carga de
outra, os dois descreveriam peças diferentes. Vale notar que, para carga
uniforme, wL²/12 e wL/2 continuam valendo com ou sem cortante: as integrais
das funções de forma dão exatamente L/12 e 1/2, com o (1+Φ) do numerador
cancelando o do denominador. É uma conferência forte justamente por isso —
qualquer coeficiente errado nas funções de forma quebraria o cancelamento.

**Trechos rígidos.** `offset_i` e `offset_j` encurtam o vão flexível da barra,
representando o que está dentro do nó viga-pilar. Toda a mecânica do elemento
acontece no vão flexível: a rigidez, o engastamento perfeito, a matriz
geométrica e o diagrama, cujas abscissas começam depois do nó e terminam antes
do outro. Os esforços de extremidade passam a ser os da **face** do apoio, que
são os de dimensionar, enquanto a reação no nó continua carregando a estática
inteira.

Um cuidado que a conferência revelou: sob carga de gravidade o momento que
chega ao nó **cresce** com o braço, porque ao `w·Lf²/12` da face soma-se o
cortante vezes o braço. Trecho rígido não reduz tudo — reduz o momento de
dimensionamento da viga e enrijece o pórtico ao deslocamento lateral, que é
outra coisa.

**Lajes.** O painel de laje é definido por dois cantos de uma diagonal e entra
como **carga**, não como elemento: o programa pesa a espessura pelo γ do
material, soma o revestimento e o acidental, e reparte tudo para as quatro
vigas de contorno pelas áreas de influência a 45° — o processo das áreas. Daí
sai carga triangular no lado menor do painel e trapezoidal no maior, que é
exatamente o tipo de carga que a fase 2 passou a aceitar; por isso esta peça
coube sem tocar no núcleo.

O quinhão de cada aresta é `q·lx·(2·Le − lx)/4`, com `lx` o menor lado do
painel. A fórmula é a mesma para o lado curto e para o longo, e a soma dos
quatro devolve `q·lx·ly` exatamente. Quando a viga tem trecho rígido, o perfil
é desenhado sobre o vão flexível mas a intensidade sai do **total**, não da
geometria do painel — sem esse cuidado a carga que cai sobre o braço rígido
sumiria do modelo sem que nada acusasse.

Duas coisas que a laje **não** faz. Ela não é dimensionada aqui — disso cuida o
programa de Lajes. E, por padrão, ela **não trabalha como diafragma** nem tem
rigidez à flexão: é só carga. As duas coisas existem como opção do menu
**Cálculo** — ver "Laje como diafragma e como grelha; vigas armadas pelo
pórtico", mais abaixo.

**Alternância de cargas acidentais.** O caso acidental se desdobra nos padrões
clássicos — todos os tramos, tramos alternados, pares de tramos adjacentes —
e os padrões nascem todos no mesmo grupo excludente, porque são alternativas
da mesma ação: combiná-los entre si contaria a mesma carga duas vezes.

**Vento.** O programa **não recalcula a NBR 6123**: importa o
`nbr6123_core.py` do programa NBR-6123 desta mesma pasta de programas, que já
é biblioteca de funções puras. Daqui sai só o que depende do modelo — os
pavimentos, a altura tributária de cada um, a largura frontal na direção do
vento e o rateio da força pelos nós. É a primeira peça de integração entre
programas, e antecipa o formato da fase 4.

Duas coisas para saber ao ler o relatório do vento. A força total aplicada é
**menor** que `Ca·q·ℓ1·h`, porque a faixa de meio pé-direito junto ao chão vai
direto para a fundação sem solicitar a estrutura; a altura dessa faixa é
declarada no relatório. E a chamada ao `coef_arrasto` passa a **largura
frontal** como primeiro argumento, contrariando o docstring daquele módulo:
a NBR 6123:2023, item 3.2, define ℓ1 como a largura perpendicular ao vento e
ℓ2 como a profundidade, e é nessa orientação que as tabelas de lá foram
digitalizadas. Há conferência travando isso, e o comentário no código explica
por quê — para que ninguém "conserte" de volta.

## Edifício de 3 pavimentos contra os programas isolados (2026-11-05)

`exemplos/edificio_3pav.py` é um edifício para conferir o Pórticos contra os
programas de Vigas, Pilares e Lajes rodados **isoladamente**:

* vãos de 4,0 / 5,0 / 3,5 m em X e 5,0 / 4,0 m em Y;
* vigas de cinco seções (15×40 a 20×60);
* V1 e V2 em balanço de 1,5 m, com a V8 nas pontas e a sacada L7 sobre elas;
* L8 e L9 em balanço puro de 1,2 m além da V3;
* pilares 20×40, 20×50 e 25×60, parte deles girados 90°;
* vento.

`exemplos/verificar_contra_programas.py` monta a entrada de cada programa à
mão — sem as funções da ponte —, roda os **originais** (Vigas R04, Pilares
R05, Lajes R11, das pastas deles), compara e grava em
`exemplos/verificacao-3pav/` o relatório, as entradas no formato de cada
programa (abrem neles) e as imagens da armadura 3D.

### O que bateu

* **Vigas:** a viga que o Pórticos monta, gravada no formato do Vigas R04 e
  aberta no original, dá resultado **idêntico** nas 24 cadeias (momentos,
  regiões e cada posição de armadura). Montada à mão, as seções T, as
  larguras de apoio e as molas 4EI/ℓ batem exatamente; o que difere é
  escolha de modelagem, documentada:
  * a carga de laje vai só para o **vão flexível** (com o trecho rígido do
    14.6.2.1, o total se conserva): momento de vão 1 a 3 % maior;
  * o peso da viga dentro do pilar fica com o pilar.
* **Pilares:** em todos os lances verificados, mesmo Nd, mesmos momentos de
  topo e de base (o sinal geral sai invertido, a relação topo/base — que é
  o que decide a curvatura e o αb — é a mesma) e o **mesmo arranjo**.
* **Lajes:** posições, vínculos e larguras de apoio idênticos, menos nas
  duas lajes em balanço lado a lado (ver abaixo).

### Defeitos achados e corrigidos aqui

* **Laje em balanço** não existia. Agora existe (`Laje.balanco`,
  `Laje.sentido`; no lançamento, `LajeLancada.balanco/sentido` com o ponto
  na sacada): a carga vai inteira para a viga do lado apoiado (q·b por
  metro), e o programa de Lajes a arma como balanço engastado na laje de
  dentro (`destino = "balanco"`, que leva a negativa até a ponta e o h
  mínimo de 10 cm do 13.2.4.1). O momento do engaste é equilibrado pela
  laje de dentro; o solver não tem torque distribuído, e por isso a laje em
  balanço **sem** laje contínua do outro lado da viga é recusada com o
  motivo. Duas em balanço lado a lado não se engastam pela borda lateral.
  Na viga T, o lado da laje em balanço colabora com b3 ≤ b4 (Figura 14.2).
* **Largura do pilar girado.** `compatibilizacao.largura_do_pilar` supunha o
  eixo local y = X global e ignorava a rotação da barra: a viga em Y sobre
  um 20×50 girado 90° recebia 50 cm de apoio em vez de 20 — com eles a
  ancoragem, o arredondamento sobre o apoio e a posição dos estribos.
* **Largura de apoio das lajes no bordo errado.** A ponte passava as
  larguras na ordem das arestas, e o programa de Lajes numera os bordos
  pela orientação da laje: na orientação Y a viga da direita ia para o
  bordo da esquerda. Agora vai pela face.
* **3D — mesa da viga de borda.** O motor de Vigas trata a mesa simétrica;
  na viga de borda metade das barras do laço da mesa ficava no ar, do lado
  sem laje. O desenho agora põe a mesa inteira do lado da laje (seção L).
* **3D — topos nivelados.** Vigas de alturas diferentes ficavam com o topo
  em níveis diferentes, e cada laje seguia a viga mais alta do próprio
  contorno: a mesa da viga T saía abaixo da laje, e a negativa entre duas
  lajes, acima de uma delas. O desenho agora põe toda viga e toda laje com o
  topo no **nível do pavimento** — o topo da viga mais alta da cota
  (`core.lajes.nivel_do_pavimento`, `desnivel_da_viga`); o cálculo continua
  com os eixos na cota.

Com isso o verificador do 3D (cada ponto de cada barra dentro de alma de
viga, seção de pilar ou laje) não acha barra fora do concreto.

### Achados nos outros programas (pedidos às janelas deles)

* **Lajes R11:** (1) a negativa da borda comum é centrada na face da
  primeira laje do par, e não no eixo da viga — do lado da segunda ela
  entra a largura da viga a menos; no balanço, termina ~20 cm antes da
  borda livre; (2) o balanço é reconhecido pelo `destino`, e não pelos
  vínculos; (3) duas lajes em balanço lado a lado se engastam pela borda
  lateral livre, e sai uma negativa de −87,5 a 867,5 cm.
* **Vigas R04:** a negativa do apoio de extremidade só desce no pilar se o
  apoio for "engaste"; com "mola" (que o próprio programa diz representar
  os pilares) reprova. O Pórticos contorna isso só na verificação de
  ancoragem; o programa isolado reprova quase todas as vigas do edifício.

### Ainda reprovado, e é veredito

* No exemplo residencial, a borda comum L4/L5 dos dois pavimentos maciços:
  wk = 0,304 mm contra 0,300 mm — verificação nova do Lajes R11.

Conferências: seção 53 de `validacao.py`.

**Atualização de 25/11/2026 — Lajes.** Os três achados do Lajes R11 foram
corrigidos lá na R12 e entraram com a recópia da R13. Uma consequência na
ponte: o programa de Lajes passou a recusar continuidade em bordo livre de
balanço, e a ponte entregava a laje em balanço com os quatro bordos livres
(o do lado apoiado virava engastado na continuidade). Agora o bordo do lado
apoiado entra "apoiado" e os outros três livres; a continuidade com a laje
de dentro o engasta como antes. Na nova rodada as lajes dos três pavimentos
saem com as mesmas posições, vínculos e veredito do programa isolado.

**Atualização de 25/11/2026 — Vigas.** O achado do Vigas R04 foi corrigido lá
(`e1afab0`) e entrou com a recópia `motor-2026-11-25`; a mesa da viga de
borda agora é a seção L do próprio motor (`Secao.lado_mesa`), e a mola dos
pilares é a do 14.6.6.1 feita pelo motor. Na nova rodada a viga que o
Pórticos monta continua idêntica no programa de Vigas (24 de 24). A ponte
passava a altura da viga apoiada em cm × 100 (`h_apoiada`, que reduz a
carga de suspensão do 18.3.6); corrigido. Os momentos de vão 1 a 3 %
maiores que os da montagem à mão continuam sendo a carga de laje só no vão
flexível.

## Sacada: viga em balanço que carrega laje (2026-10-16)

O usuário lançou uma sacada (vigas avançando em balanço além dos pilares, uma
viga de borda nas pontas e a laje em cima) e achou a armadura "generalizada",
sem o reforço superior que o balanço pede. A verificação, sobre um modelo
igual (`_sacada` em `validacao.py`), separou o que estava certo do que não
estava.

**Certo — o cálculo do balanço.** A viga em balanço é armada pela envoltória
do pórtico, e o momento do motor bate ponto a ponto com o do pórtico. Com a
sacada carregada (2,5 m de balanço, 5 kN/m²) o apoio pede 110 kN.m e sai
2Ø20 em cima, do apoio à ponta; o resto da face superior fica só com
porta-estribos 2Ø6,3. O reforço do balanço existe.

**Por que parece generalizado no caso leve.** Com 1,5 m de balanço e 3 kN/m²
o momento é 41 kN.m, a área calculada (2,1 cm²) fica abaixo da mínima da
seção T (2,55 cm², 17.3.5.2.1) e **a mínima comanda os dois apoios**: os dois
saem com 4Ø10. Além disso o motor de vigas estende as barras que só existem
por causa da mínima até o fim da região do apoio (meio vão), e não até onde
o momento negativo acaba — isso está no motor do Vigas R04, que aqui é cópia
idêntica, e foi entregue como pedido para a janela daquele programa.

**Errado — e corrigido aqui:**

* **A viga de borda ficava sem armadura.** A V5, apoiada só nas pontas dos
  balanços, era recusada ("sem apoio em pilar nem em viga"): a regra de que
  ponta de balanço não é apoio (pilar de canto retirado) valia para ela
  também. Agora a viga **sem pilar nenhum** pode repousar nas pontas dos
  balanços (`continuidade._apoiar_nas_pontas_de_balanco`), desde que ganhe
  pelo menos dois apoios; sai com o aviso de apoio deslocável — o pórtico já
  tem o deslocamento da ponta, o modelo isolado da viga o trata como fixo.
  A reação dela entra como carga na ponta do balanço. O caso do pilar de canto
  (cada viga tem o seu pilar) continua como era.
* **O desenho 3D descartava calado** a viga com menos de dois apoios. Agora
  avisa.
* **O negativo entre duas lajes caía dentro da viga.** O programa de Lajes dá
  a ele o nome das duas ("L1 / L2"); o desenho procurava uma laje com esse
  nome, não achava, e punha a barra no plano dos nós — 20 cm abaixo da laje.
  Agora fica sob o topo mais alto das duas. A conferência antiga de "barra
  dentro da laje" pulava justamente esse caso, e passou a cobri-lo.

Conferências: seção 51 de `validacao.py` (9).

## Lançamento por planta (2026-10-16, fase 1: o gerador)

Os programas de edifício não pedem nós e barras: o engenheiro desenha a
**planta de fôrma** de cada pavimento, e o modelo de cálculo sai sozinho. O
pacote `portico3d/lancamento/` é essa camada. Nesta fase ela entra por
código ou por arquivo JSON; o editor gráfico de planta vem em seguida, sobre
ela.

### O que se lança (`lancamento/modelo.py`)

| Elemento | Como é lançado |
|---|---|
| Pavimento | nome, cota (do eixo das vigas) e a **planta** que usa — várias cotas podem usar a mesma planta: é o pavimento-tipo |
| Pilar | ponto, `b × h`, ângulo em planta e ponto de inserção (centro ou um canto). O pilar da planta de um pavimento é o lance que **chega** nele |
| Viga | polilinha de ponta a ponta, `b × h` |
| Laje | um ponto dentro do contorno de vigas, mais os dados de laje (maciça ou treliçada, carga ou tipo de carga) |
| Parede | polilinha sobre vigas, espessura, peso específico e altura (padrão: até o fundo da viga de cima) |
| Vento | V0, categoria e grupo da NBR 6123 — sai nas quatro direções |

### O que o gerador decide (`lancamento/gerador.py`)

* **Nós.** Viga cruzando viga, viga encostando noutra, viga passando por
  pilar e vértices de polilinha: pontos coincidentes viram um nó só.
* **Quebra das vigas** nesses nós. Quem apoia em quem é a regra de viga
  apoiada em viga de sempre (`continuidade`), que agora recebe o modelo
  pronto.
* **Trecho rígido** em cada ponta de viga com pilar, pelo 14.6.2.1. A
  Figura 14.1, conferida na imagem da norma, leva o trecho do eixo do pilar
  até `0,3·h` da viga antes da face: `c/2 − 0,3·h`, com `c` a dimensão do
  pilar **na direção da viga**, que leva em conta o giro do pilar.
* **Pilares.**
  * O primeiro lance engasta na fundação.
  * O lance que tem pilar embaixo continua dele.
  * O que não tem nasce na viga do pavimento de baixo (transição, com aviso),
    e essa viga é quebrada embaixo dele.
* **Lajes.** O retângulo de vigas em volta do ponto. O lado pode ser coberto
  por várias vigas na mesma reta, por exemplo onde uma viga secundária nasce
  no meio dele. Para isso o `core.lajes` passou a aceitar lado composto
  (`Aresta.trechos`), e a grelha, a viga T, a faixa treliçada e as fôrmas
  acompanham. O quinhão do lado é o mesmo perfil de rampa e patamar,
  recortado em cada barra.
* **Casos.**
  * `G`: peso próprio das barras, lajes e paredes;
  * `Q`: acidental das lajes;
  * com V0 > 0, `VX+`, `VX−`, `VY+` e `VY−` pela NBR 6123.

### Conferência de lançamento

O gerador **recusa**, com a lista dos motivos, em vez de devolver um modelo
errado:

* pilar que nasce no ar;
* viga que passa perto do pilar mas fora do eixo dele (a excentricidade
  viga–pilar ainda não é modelada);
* laje sem contorno fechado, não retangular, ou com viga atravessando o
  painel;
* parede que não está inteira sobre viga;
* pavimentos fora de ordem, planta inexistente, nome repetido.

Ele **avisa** sem recusar: pilar de transição, pilar sem viga no topo, viga
sem apoio, trecho rígido que não coube.

### Arquivo e janela

O lançamento é um JSON com `"tipo": "lancamento"` (`lancamento/arquivo.py`).
O leitor de modelo (`arquivo.ler`) reconhece esse tipo e gera o modelo na
hora, de modo que "Abrir" na janela e a linha de comando funcionam com ele
sem mais nada. As tabelas mostram o modelo de cálculo gerado; editar nelas
não volta ao lançamento.

### Exemplo

`exemplos/lancamento_residencial.py` grava `exemplos/lancamento-residencial.json`:

* três pavimentos, planta-tipo repetida em dois e cobertura com laje
  treliçada;
* grade irregular de pilares 20×40, os de extremidade girados 90°;
* a viga V7 nascendo na V1 e morrendo na V2;
* paredes no perímetro e vento.

Saem 42 nós, 72 barras e 15 lajes. O modelo gerado passa pelo caminho
inteiro (análise com 2ª ordem, os três motores e a compatibilização) com
tudo aprovado.

Um achado no caminho mostra para que serve a compatibilização. Com os
pilares de extremidade sem giro, a viga V2 terminava num pilar de 20 cm na
direção dela: a ancoragem dispunha de 17,0 cm e precisava de 17,3 cm. O
motor de Vigas aprovava a viga, e a conferência do nó viga–pilar pegou.

### Conferências (seção 50 de `validacao.py`)

| Conferência | Resultado |
|---|---|
| Contagem de nós e barras do exemplo; quebra da V1 em x = 4; 6,5; 9 | exato |
| Trecho rígido 0,40/2 − 0,3·0,45 = 0,065 m; no pilar girado, o mesmo; no lado de 20 cm, zero | exato |
| Lado da L5 coberto por duas vigas, que recebem juntas o quinhão do lado; L5 entrega q·lx·ly | exato |
| ΣFz do permanente = barras (vão flexível) + lajes + paredes | 2,7·10⁻¹⁶ |
| Pavimento-tipo repetido; vento nas quatro direções; sem erro nem viga solta | sim |
| Pilar de transição nasce na viga de baixo, quebrada embaixo dele | sim |
| Recusa: pilar no ar, viga fora do eixo, laje sem contorno, parede fora de viga | sim |
| JSON gravado e lido gera o mesmo modelo; o leitor de modelo aceita o lançamento | exato |
| Ponta a ponta: 21 vigas, todos os lances de pilar, três pavimentos de laje, emendas e nós | aprovados |

### Fase 2: o editor de planta (`ui/editor_planta.py`)

Botão **Lançamento** (Ctrl+L) na barra da janela principal. Ele abre a janela
do editor com o lançamento de onde o modelo atual veio, ou com um novo. O
editor só desenha e grava o `Lancamento`; toda regra estrutural continua no
gerador da fase 1.

**A folha.** A planta de um pavimento por vez:

* zoom na roda, deslocamento com o botão do meio, "Enquadrar" na barra;
* grade de 1 m desenhada e captura a cada 5 cm;
* os pilares da planta do pavimento de baixo aparecem tracejados, em
  fantasma, para o pilar de cima nascer sobre eles;
* depois de "Gerar modelo", os painéis de laje que o gerador achou aparecem
  pintados.

**Ferramentas:**

| Ferramenta | Tecla | Uso |
|---|---|---|
| Selecionar | S | escolhe o elemento e mostra as propriedades dele |
| Pilar | P | um clique |
| Viga | V | ponto a ponto; duplo clique, Enter ou botão direito termina; Esc cancela; Shift trava em X/Y |
| Laje | L | um clique dentro do contorno |
| Parede | W | como a viga |
| Apagar | Del | um clique no elemento |

**Captura.** O clique vai, nesta ordem, para o ponto notável mais próximo a
até 10 px (centro de pilar, vértice ou cruzamento de vigas, ponta de linha do
DXF), para o eixo da viga mais próxima, ou para a grade.

**Painéis:**

* **À esquerda:**
  * pavimentos (nome, cota e planta de cada um, com + e −);
  * a planta em edição (nova, duplicar, renomear — é o pavimento-tipo);
  * os dados do edifício: concreto, cota da base, trecho rígido, vento e
    tipos de carga de laje.
* **À direita:**
  * as propriedades do elemento selecionado (ou do próximo elemento da
    ferramenta), montadas a partir dos campos do lançamento — inclusive os
    pontos da viga como texto, para coordenada exata;
  * a conferência do gerador, com os erros em vermelho e os avisos em
    laranja.

**DXF de fundo.** Linhas, polilinhas, arcos, círculos e blocos explodidos
num nível, em cinza. A unidade é sugerida pelo `$INSUNITS` do arquivo e
confirmada pelo usuário.

**Gerar modelo (F9).** Roda o gerador e, quando ele fecha, entrega o modelo à
janela principal, com as opções do menu Cálculo que já estavam escolhidas.
Abrir um arquivo de lançamento pela janela também deixa o lançamento pronto
para editar.

**Precisão de posicionamento** — a segunda linha da barra, pedida pelo
usuário depois do primeiro uso:

* **O elemento aparece no cursor antes do clique.**
  * O pilar sai com a seção, o ângulo e o ponto de inserção que vai ter,
    transparente, com "20×40 · 90°" ao lado. **R** (ou "Girar 90°") gira o
    próximo pilar — ou o selecionado —, e a mudança se vê na hora.
  * Viga e parede mostram a largura real enquanto se desenha, e o comprimento
    do trecho em curso.
* **Coordenadas:**
  * uma etiqueta (x; y) acompanha o cursor, com vírgula decimal;
  * a barra de status traz o comprimento e o ângulo do trecho;
  * "Coordenadas dos pilares" escreve (x; y) ao lado de cada pilar, e o
    elemento selecionado mostra os seus;
  * a caixa **Coordenada** coloca o ponto exato da ferramenta: `2,2; 2,8` é
    absoluto, `@3; 0` é relativo ao último ponto (o separador é o
    ponto-e-vírgula, porque a vírgula é a decimal).
* **Grade na vista inteira.** É desenhada no fundo da vista (`drawBackground`)
  em qualquer zoom e posição, e não só em volta do lançado:
  * a malha fina segue o passo e se adensa de 2 em 2, 2,5 em 2,5 quando
    ficaria ilegível;
  * a forte marca o metro (ou os 10 m, de longe);
  * os eixos x = 0 e y = 0 vão em azul.
* **Passo.** O campo "Passo" define a captura na grade, por exemplo 0,10 m,
  para os pontos caírem só de 10 em 10 cm. "Captura em objetos" desligada
  deixa só o passo valendo, sem o ímã de pilar e viga.

**Grelha de eixos, zoom e viga por direção (2026-10-19)** — a terceira
leva de ajustes pedida pelo usuário:

* **Zoom no ponto que se olha.** A roda aproxima e afasta mantendo parado o
  ponto da planta sob o mouse (`VistaPlanta.zoom_em`). Antes todo zoom ia
  para o (0; 0): a âncora "sob o mouse" do Qt usa a posição que o
  `mouseMoveEvent` da classe base registra, e a vista o substitui sem
  chamá-lo. O ponto agora é preso à mão, pelas barras de rolagem.
* **Uma viga por direção.** A polilinha que muda de direção vira uma viga por
  trecho reto (`lancamento.grelha.dividir_por_direcao`): (0; 0) (4,5; 0)
  (6; 2) dá V1 e V2. Pontos no meio de um trecho reto não quebram a viga, e
  a viga editada no formulário que passar a dobrar é quebrada do mesmo modo.
* **Grelha de eixos** (painel Pavimentos → Grelha; `Lancamento.grelha`,
  comum a todas as plantas e gravada no arquivo):
  * colunas verticais com **letras** (A, B, …, Z, AA…), da esquerda para a
    direita; linhas horizontais com **números**, de baixo para cima. O
    encontro **2-E** é a linha 2 com a 5ª coluna;
  * quantidade e espaçamento de colunas e de linhas, e a origem;
  * **Pilares**: um pilar em cada encontro (com a seção do "próximo pilar"),
    menos onde já há um; **Vigas**: em cada eixo, uma viga do primeiro ao
    último pilar sobre ele, com a seção da "próxima viga" — o gerador a
    quebra nos pilares do meio. Gerar de novo não duplica nada;
  * os eixos passam 2 m antes do primeiro encontro e 6 m depois do último,
    com a bolha do nome nas duas pontas, e capturam o clique (encontro e
    eixo);
  * a **4 m do último encontro** fica a linha de cotas, com o valor de cada
    espaço no meio dele. **Clicar na cota** abre o valor daquele espaço, e
    só ele muda: os eixos seguintes se deslocam, e o que está lançado anda
    junto em todas as plantas — o que está sobre um eixo fica sobre ele, o
    que está entre dois eixos fica na mesma proporção do vão (a laje no meio
    do vão continua no meio), o que está além do último anda o que o último
    andou (`lancamento.grelha.mudar_espaco`). O pilar anda pelo centro, não
    pelo ponto de inserção.
* A captura no eixo de uma viga já lançada anda no passo ao longo dela,
  contado do vértice. Antes devolvia a projeção crua — o clique em 4,5 m
  sobre uma viga existente caía em 4,503 —, e foi o teste por clique da viga
  dobrada que pegou.
* As caixas de opção do editor ganharam borda: no Fusion claro elas saíam
  brancas sobre o painel branco, e desmarcadas não se viam.

Conferências: seção 52 de `validacao.py` (17) e o autoteste da janela, que
confere a deriva do zoom em pixels, a viga dobrada por clique e a cota da
grelha.

**Seleção múltipla (2026-10-19).** **Ctrl+clique** soma o elemento à
seleção e **Alt+clique** o tira, com qualquer ferramenta (menos no meio de
uma polilinha). A seleção é sempre de uma família só — pilares, vigas, lajes
ou paredes —, e o elemento de outra família é recusado com aviso na barra de
status. Com vários selecionados:

* o painel mostra os campos do primeiro, e **o que se muda vale para todos**
  (`Formulario.alvos`); o campo em que eles diferem leva "(vários)" no
  rótulo. Nome, posição e pontos não aparecem: dar o mesmo valor a todos
  empilharia os elementos;
* **R** (Girar 90°) gira todos os pilares selecionados, cada um em torno do
  próprio ponto de inserção;
* **Delete** apaga todos;
* todos aparecem destacados, e Esc ou um clique simples recomeça a seleção.

Conferido no autoteste da janela por clique com Ctrl e Alt (`QTest`).

**Duas armadilhas de interface achadas no teste por clique (`QTest`):**

* **A cena precisa de área fixa.** Sem isso ela cresce a cada item, a vista se
  recentraliza e a folha "pula" debaixo do mouse.
* **Os painéis laterais precisam de largura fixa.** Trocar de ferramenta troca
  o formulário, e o painel que muda de largura empurra a folha. O primeiro
  pilar clicado depois de escolher a ferramenta caía meio metro ao lado.

**Conferência da janela (`main.py`).** Um pórtico de 5 × 4 m lançado por
cliques de mouse de verdade:

* pilares clicados fora da grade, que a captura põe no lugar;
* viga capturando os centros dos pilares;
* laje e dois pavimentos;
* gerado e entregue à janela (12 nós, 16 barras);
* depois o exemplo residencial aberto e gerado pelo editor.

## Dimensionamento mais perto de um programa de edifício (2026-10-16)

Três lacunas apontadas na comparação com o Eberick, fechadas nesta rodada.
Fundações ficaram de fora por decisão do usuário.

### 1. A 2ª ordem global chega ao dimensionamento (`core/segunda_ordem_global.py`)

O item 15.7.1 manda considerar, no dimensionamento das estruturas de nós
móveis, os efeitos globais de 2ª ordem. Até aqui a envoltória que ia aos
pilares e às vigas era de 1ª ordem pura, e o γz era só relatado. Agora cada
combinação ELU recebe, pelo γz dela:

| γz da combinação | Tratamento |
|---|---|
| sem ação horizontal | 1ª ordem (γz não se define) |
| ≤ 1,10 | 1ª ordem — nós fixos (15.4.2) |
| 1,10 a 1,30, com ao menos 4 andares | ações horizontais × 0,95·γz (15.7.2), por superposição |
| > 1,30, ou menos de 4 andares | P-Δ da combinação com a rigidez secante (15.7.3) |

* **O γz passou a ser calculado com a rigidez secante** do 15.7.3: 0,8 EI nos
  pilares, 0,4 nas vigas e 0,3 nas lajes em grelha
  (`OpcoesDeCalculo.fator_rigidez_laje`). É a rigidez com que a norma pede a
  análise dos esforços globais de 2ª ordem. Antes a janela relatava o γz com
  a rigidez cheia, que sai menor que o de projeto.
* **A Análise já monta a envoltória do dimensionamento.** "Combinações"
  guarda as ELU com a 2ª ordem dentro, e "Dimensionar" usa essa envoltória
  sem resolver de novo. O relatório lista o tratamento de cada combinação, e a
  memória de cálculo ganhou a tabela no capítulo 4.
* **Nos exemplos de teste:**
  * prédio de 8 pavimentos (γz 1,22): as combinações são majoradas;
  * prédio de 12 pavimentos (γz 1,46): elas vão por P-Δ;
  * a envoltória dos lances térreos cresce 3 a 11 %.

### 2. Viga T e laje treliçada

* **Viga T pela mesa colaborante (14.6.2.2).** A viga é armada como seção T:
  * `bf = bw + Σ b1`, com `b1 ≤ 0,1·a` e `b1 ≤ 0,5·b2` para cada lado com laje
    ao longo do tramo inteiro;
  * `a` = 1,00 / 0,75 / 0,60 / 2,00 ℓ conforme o tramo;
  * a mesa é a espessura da laje, ou a capa na treliçada.

  É opção do menu Cálculo, ligada por padrão. A análise do pórtico segue com
  a seção retangular, só o dimensionamento usa a T.

  De passagem, a conferência contra o pórtico passou a usar o momento **com
  sinal** e o As de **cálculo**, sem a armadura mínima. Em módulo, o momento
  negativo seria calculado com a mesa comprimida. Com o mínimo dentro, a
  seção T, cujo mínimo é sobre a área da mesa, acusava falta de aço perto do
  apoio por 1 kN·m.
* **Laje treliçada.** A laje ganhou `tipo` ("macica" ou "trelicada"),
  `direcao` das nervuras, treliça, enchimento, altura do enchimento, capa,
  bloco e base da vigota. Tudo isso tem colunas na tabela de lajes e vai para
  o JSON.
  * **Carga:** o peso próprio por m² é o mesmo do programa de Lajes (por
    nervura ÷ intereixo). A laje se apoia **só nas duas vigas perpendiculares
    às nervuras**.
  * **Grelha:** na direção das nervuras entra a seção T da nervura, repartida
    pela faixa; na outra, só a capa. A carga vai inteira pelas faixas das
    nervuras.
  * **Dimensionamento:** a cópia do motor de Lajes subiu do R04 para o
    **R07**, que tem o módulo de laje treliçada. Os painéis treliçados
    encostados na direção das nervuras viram uma **faixa contínua**, com vãos
    de eixo a eixo e a largura de cada viga como apoio. A vigota entra na
    viga o que ela dá (largura − 3 cm). A faixa vai inteira ao
    `dimensionar_trelicada`.
  * **Desenho:** a vista de Laje e a armadura 3D avisam que a treliçada sai
    por faixa e não a desenham.
  * **O que não foi feito:** a laje nervurada **bidirecional** moldada no
    local não entrou, porque o programa de Lajes não tem esse dimensionamento.
    Seria pedido para a janela do Lajes, não deste programa.

### 3. Continuidade dos pilares e nós viga–pilar (`compatibilizacao.py`)

**Prumadas.** Os lances de um mesmo pilar, em ordem. Em cada pavimento é
conferida a emenda:

* a espera do lance de baixo (ℓ0c, 9.5.2.3, do motor de Pilares);
* a **taxa na emenda**, (As de baixo + As de cima)/Ac de cima ≤ 8 %
  (17.3.5.3.2, que conta a sobreposição);
* o **espaço livre entre pares emendados**, face a face (18.4.2.2, que vale na
  emenda);
* barras que param ou que nascem;
* redução de seção e mudança de bitola.

A armadura 3D passou a desenhar a espera subindo no lance de cima. O
quantitativo do motor já a contava.

**Nós viga–pilar.** O 21.4 não dá verificação fechada para o nó, que é
região D (Figura 22.1, a2). O que se confere sem modelo de bielas:

* a **ancoragem da armadura positiva da viga no pilar de extremidade**
  (18.3.2.4);
* a largura da viga contra a do pilar;
* os **nós de joelho** da cobertura (sem pilar acima), onde o laço da
  armadura negativa tem de ser detalhado.

Junto veio a correção de um defeito antigo: a largura do pilar que a ponte
dava ao motor de Vigas era sempre o lado `b`, que na barra vertical mede em X.
Uma viga em Y sobre um pilar 20×60, com os 60 cm em Y, recebia 20 cm de apoio.
Agora a largura é medida **na direção da viga**.

"Dimensionar" pilares e vigas roda a compatibilização quando os dois já
existem. O Projeto completo também, e a memória ganhou os itens 6.2
(continuidade) e 7.2 (nós).

### Conferências (seção 49 de `validacao.py`)

| Conferência | Resultado |
|---|---|
| Prédio rígido fica em 1ª ordem, igual à superposição | exato |
| Majoração multiplica só a parcela horizontal, por (0,95γz − 1) | 1,6·10⁻¹⁶ |
| γz > 1,3 vai por P-Δ e amplifica o topo além de γz | sim |
| γz secante maior que o γz com a rigidez cheia | sim |
| bf = 50 / 53,75 / 80 cm nos três casos do 14.6.2.2; hf = laje ou capa | exato |
| Peso da treliçada igual ao do programa de Lajes; paralelas sem carga; perpendiculares com a laje inteira; grelha conserva a carga | exato |
| Faixa treliçada de 2 vãos dimensionada pelo motor e atendendo | sim |
| Taxa na emenda, espera, redução de seção, largura do pilar por direção, joelho só na cobertura, ancoragem em todo nó de extremidade | exato |

## Laje como diafragma e como grelha; vigas armadas pelo pórtico (2026-10-16)

Três opções novas, no menu **Cálculo ▾** da barra. Elas moram no modelo
(`Modelo.calculo`, uma `OpcoesDeCalculo`), vão para o arquivo JSON no bloco
`"calculo"` e sobrevivem ao "Aplicar tabelas". Mudar qualquer uma apaga as
análises e o dimensionamento feitos com a opção anterior. Arquivo antigo, sem
o bloco, abre com os padrões.

| Opção | Padrão | O que faz |
|---|---|---|
| Laje como diafragma rígido | desligada | os nós de cada pavimento com laje transladam em X e Y e giram em Z juntos |
| Lajes em grelha (malha) | desligada, 1,0 m | cada laje vira grelha de barras ligada às vigas de contorno |
| Vigas armadas com | envoltória do pórtico | de onde vêm os esforços ELU com que o motor de Vigas arma a viga |

### Diafragma rígido (`core/diafragma.py`)

Restrição **exata**, por transformação de coordenadas, e não mola rígida de
penalidade: `D = D₀ + T·r`. Os ux, uy e rz de cada nó do pavimento deixam de
ser incógnitas e passam a sair dos três graus do pavimento (Ux, Uy, Rz),
referidos ao centro dos nós dele. Os graus fora do plano (uz, rx, ry)
continuam livres, que é onde a laje é flexível e onde a viga trabalha.

* **Quem entra:** os nós da cota de uma laje que estão sobre algum painel,
  seja canto, borda ou interior (os nós da grelha, quando há grelha). O nó
  com apoio em ux, uy ou rz fica de fora e é listado no relatório da Análise.
* **Onde vale:** em todas as análises. A classe `montagem.Base` é por onde
  passam a 1ª ordem, o P-Δ, a flambagem e a modal. Sem diafragma, `T` nem
  existe, e a conta é a de antes: `K[livres, livres]`.
* **O que muda no resultado:**
  * o vento se reparte pelos pórticos pela rigidez de cada um;
  * o pavimento em planta assimétrica gira;
  * o **normal das vigas no plano some**, porque elas deixam de alongar.
    É o comportamento conhecido do diafragma rígido em qualquer programa de
    edifício.

### Laje em grelha (`core/grelha.py`)

O modelo do usuário não muda. Na hora de calcular, monta-se um **modelo de
cálculo**:

* **A malha:** cada painel é dividido em faixas de espaçamento próximo da
  malha pedida, com no mínimo duas por lado.
* **As vigas de contorno:** são partidas onde as faixas chegam. Cada pedaço
  herda seção, material, giro, liberação e trecho rígido da sua ponta. Se uma
  faixa cair dentro de um trecho rígido, sai erro pedindo outra malha.
* **As faixas:** cada faixa interna é uma barra de seção b×e, com `I = b·e³/12`
  e a rigidez à torção da placa, `J = b·e³/6` (analogia de grelha de Hambly).
  O material dela não tem peso, porque o peso da laje já está na carga.
* **As faixas de borda:** meia largura de laje correm em paralelo com cada
  viga de contorno, como barras à parte. Sem elas faltava perto dos bordos a
  rigidez à torção da placa, e a grelha convergia para a placa só linearmente
  com a malha (14 % de erro na flecha com malha de 0,5 m). Com elas converge
  com o quadrado da malha.
* **A carga:** a laje carregava as vigas pelas áreas a 45°, e essas cargas
  agora levam a marca `origem = "laje:L1"` (coluna **Origem** na tabela de
  distribuídas, e no JSON). A grelha tira das vigas o que tem essa marca,
  converte em carga por área (`q = W/(lx·ly)`, o total se conserva
  exatamente) e reaplica metade em cada direção, cada faixa com a sua largura
  de influência. A faixa de borda é a própria viga.
* **A volta ao modelo do usuário:** deslocamentos e reações saem dos nós
  dele. Cada viga partida é **remontada numa barra só**: as forças que as
  faixas aplicam nela entram como ações concentradas ao longo da barra
  (`Resultado.pontuais`). Diagrama, envoltória, combinação e dimensionamento
  leem a viga como sempre leram. O resultado no modelo de cálculo fica em
  `Resultado.calculo`.

Fica de fora, de propósito:

* **Excentricidade laje–viga:** a grelha está no plano dos eixos das vigas,
  então a mesa colaborante não entra.
* **Laje sem espessura ou sem material:** fica fora da grelha, com aviso.
* **Modelo antigo, com a carga de laje nas vigas sem a marca:** a grelha entra
  só com a rigidez, também com aviso. Reabrir no assistente refaz as marcas.
* **Dimensionamento da laje:** continua pelas tabelas do programa de Lajes.
* **Vista de Cargas:** continua mostrando a carga como o usuário a tem, nas
  vigas.

### Matriz esparsa

A grelha multiplica os graus de liberdade: o prédio de 10 pavimentos com 120
lajes vai de 1 320 para 22 200. Uma matriz densa desse tamanho ocupa 4 GB.
Acima de `montagem.LIMITE_DENSO` (3 000 graus) a montagem passa a ser esparsa
(`Montador`) e as soluções mudam junto:

| Análise | Abaixo do limite | Acima do limite |
|---|---|---|
| 1ª ordem e P-Δ | Cholesky | LU esparsa, com a mesma conferência de pivô contra mecanismo |
| Flambagem | autovalores densos | Lanczos, só os modos pedidos |
| Modal | autovalores densos | Lanczos com deslocamento em zero, só os modos pedidos |

Os nós internos da grelha não têm massa:

* No caminho **denso**, a modal faz a condensação estática exata desses graus.
* No caminho **esparso**, o Lanczos com deslocamento em zero aceita a massa
  singular.

Prédio de 10 pavimentos com 120 lajes, diafragma e grelha de 1 m: 2,6 s por
caso na 1ª ordem e 2,6 s na modal.

### Vigas armadas pelo pórtico

O motor de Vigas fazia a própria análise de viga contínua sob g e q, e o
pórtico só conferia a armadura no fim. Agora, havendo envoltória (o
"Dimensionar vigas" sempre a monta), a **envoltória ELU do pórtico substitui
a dele**. Com isso entram na armadura:

* o vento e o desaprumo;
* a rigidez real dos pilares;
* com a grelha, a carga que a laje entrega pela rigidez.

O ELS (flecha e fissura), as reações para viga apoiada em viga e a
suspensão continuam saindo da viga contínua sob g e q.

* **Sem editar o motor:** a cópia do motor é conferida byte a byte contra o
  Vigas R04. A troca é feita por fora (`dimensionar_com_envoltoria`): durante
  a chamada, o `combinacoes` que o motor enxerga devolve tudo igual, menos a
  envoltória ELU.
* **Sem redução sobre o apoio no motor:** com a envoltória do pórtico, o
  motor não reduz o momento negativo sobre o apoio. Quem quer considerar a
  largura do apoio modela o trecho rígido. No Vigas R03 a redução era "à
  face" (`momento_face_apoio`); no R04 virou o arredondamento R·t/8 do
  14.6.3 (`arredondar_momento_apoio`), que tira o R do modelo isolado da
  viga, e não do pórtico — por isso também fica desligado. Sem isso, na viga de um vão só do teste, o pórtico
  exigia no apoio 1,15 vez o aço que o motor detalhava.
* **As outras duas fontes:**
  * `"envolvente"` usa o pior dos dois em cada seção;
  * `"motor"` é o comportamento antigo.
* **No relatório:** "Dimensionar vigas" diz com que esforços armou, e a
  memória de cálculo descreve a opção usada.

### Conferências desta rodada (seção 48 de `validacao.py`)

| Conferência | Contra o quê | Resultado |
|---|---|---|
| Diafragma, estática | `rigidDiaphragm` do OpenSeesPy, prédio em L de 3 pavimentos com torção | deslocamentos e momentos a 1e-14 |
| Diafragma, modal | idem | MAC = 1 nos três modos. A frequência difere na quinta casa **com ou sem** diafragma, do mesmo tamanho: é a inércia de rotação do `-cMass` dele, não a restrição |
| Diafragma, cinemática | a definição | o pavimento se move como corpo rígido a 1e-16, o normal das vigas zera, ΣFx fecha |
| Grelha × placa de Navier | placa quadrada apoiada nos 4 bordos, ν = 0 (Timoshenko & Woinowsky-Krieger §30) | malha 0,5 m: flecha a 0,08 %, Mx a 1,6 %; malha 0,25 m: 0,02 % e 0,39 % |
| Grelha, equilíbrio | a laje pelas áreas | ΣFz igual a 1e-14; a viga remontada fecha com o último pedaço a 1e-15 e coincide com os pedaços no meio de cada um |
| Esparsa × densa | o mesmo prédio, com diafragma e grelha | 1ª ordem, P-Δ, quatro frequências e fator de flambagem a 1e-11 |
| Vigas pelo pórtico | a envoltória do pórtico | a envoltória do motor é a do pórtico exatamente; todas as vigas cobrem o pórtico; com vento a armadura muda |
| Arquivo | ida e volta | opções e origem das cargas voltam iguais |

## Cargas, combinações e envoltória

O caso de carga carrega a sua própria classificação normativa — `natureza`
(permanente ou variável), `categoria` (a linha da tabela de ψ) e `grupo`. O
`grupo` marca casos **mutuamente excludentes**: as incidências de vento X e Y
pertencem ao mesmo grupo e nunca aparecem juntas numa combinação.

A classificação vai junto no arquivo do modelo, de propósito: é ela que
permite a outro programa montar as combinações sozinho, sem receber a lista
pronta.

O peso próprio sai de `γ · A` por metro de barra, com o `γ` declarado no
material. O padrão do material é peso específico zero, e não um valor
plausível — carga nenhuma aparece no modelo sem ter sido pedida.

**Os esforços concomitantes são o ponto da envoltória.** Guardar o maior N, o
maior My e o maior Mz de uma barra não serve para dimensionar pilar, porque os
três costumam vir de combinações diferentes e a flexão composta oblíqua é
verificada com um trio simultâneo. Cada extremo da envoltória carrega os seis
esforços da combinação que o produziu, e o nome dela. Ainda assim, a envoltória
é uma **seleção**: para o rigor completo da flexão composta oblíqua o caminho
seguro é percorrer todas as combinações, e é por isso que o nome de cada uma
acompanha o resultado.

## Unidades

Consistentes, à escolha de quem monta o modelo. Os exemplos e as conferências
usam **kN e m**: E em kN/m², forças em kN, momentos em kN·m.

## Eixos e convenções de sinal

É a parte que precisa ser lida antes de interpretar qualquer número.

**Eixos globais.** X e Y horizontais, Z vertical para cima.

**Eixos locais da barra.** O eixo local x vai do nó inicial ao final. Os eixos
y e z são os principais da seção, e saem de um vetor de referência:

| Barra | Eixo local y | Eixo local z |
|---|---|---|
| Não vertical | horizontal, perpendicular à barra | no plano vertical, para cima |
| Vertical | na direção do X global | na direção do Y global |

Consequência prática: **numa viga horizontal a carga de gravidade flete a
barra em torno do eixo local y**, ou seja, quem governa é `Iy`. Numa seção
retangular `b × h` criada por `Secao.retangular(nome, b, h)`, o `b` é medido
na direção local y e o `h` na local z — então `Iy = b·h³/12`, que é o que se
espera de uma viga de altura `h`.

O campo `rotacao` da barra gira os eixos y e z em torno do eixo x, em graus. O
campo `vetor_ref` substitui o vetor de referência padrão quando a orientação
da seção não é a convencional.

**Esforços internos.** `N` é positivo à tração. `T` é positivo no sentido do
eixo local x. `My` e `Mz` são positivos quando tracionam a face de coordenada
local negativa: numa viga horizontal sob gravidade isso dá `My` positivo no
vão e negativo sobre os apoios, que é a leitura usual do diagrama. As
cortantes `Vy` e `Vz` obedecem a dM/dx = V no respectivo plano — e há uma
conferência no autoteste que verifica exatamente essa relação, barra a barra.

## As conferências

O autoteste não confere o programa contra ele mesmo. Cada valor esperado é
uma solução fechada da Resistência dos Materiais, uma condição de equilíbrio
ou uma invariância que a formulação tem obrigação de respeitar:

| Grupo | O que fixa |
|---|---|
| Barra axial, torção pura | rigidez axial e de Saint-Venant |
| Balanço nos dois planos | as duas inércias, e que não estão trocadas |
| Biapoiada e biengastada com carga uniforme | forças de engastamento perfeito e cargas nodais equivalentes |
| Balanço em L no espaço | flexão e torção acopladas, com solução fechada |
| Invariância sob rotação rígida | a matriz de transformação de eixos |
| Pórtico de travessa rígida | montagem do pórtico (M na base = Hh/4) |
| Equilíbrio global e por barra | que nada se perde entre a carga e a reação |
| dMy/dx = Vz e dMz/dx = Vy | a convenção de sinais dos diagramas |
| Recusa de mecanismo | que modelo instável para com erro, e não devolve número |
| Peso próprio e superposição | que o fator entra uma vez só, e no lugar certo |
| Concomitantes da envoltória | que não se cruzam máximos de combinações diferentes |
| Coeficientes γ e ψ, geração das combinações | os valores das Tabelas 11.1 a 11.4 |
| Grupos excludentes | que vento X e vento Y nunca entram juntos |
| Desaprumo | θ1, θa, os truncamentos e a regra dos 30 % |
| Ciclo completo | classificar, combinar, resolver e envoltoriar, de ponta a ponta |
| Engastada-apoiada e birrotulada | a condensação estática, na rigidez e no engastamento |
| Carga triangular e parcial | a quadratura das funções de forma em trecho qualquer |
| Molas e recalques | rigidez em paralelo, 6EIδ/L², e a convergência para o apoio rígido |
| Recalque em isostática | que não aparece esforço nenhum |
| Alternância | que os padrões são excludentes e agravam o momento de vão |
| Vento | a geometria, a área tributária, a unidade e o rateio |
| Flambagem de Euler | Pcr = π²EI/(kL)² nos quatro casos de vinculação |
| P-Δ contra viga-coluna | M = H·tan(kL)/k, a solução exata e não um majorador |
| γz e α | as fórmulas de 15.5.2 e 15.5.3, e os limites α1 |
| γz contra P-Δ | duas formulações independentes chegando ao mesmo número |
| Rigidez secante | 0,8 nos pilares, 0,4 e 0,5 nas vigas, área intocada |
| Módulo do concreto | as fórmulas de 8.2.8, e que os dois ramos se encontram em C50 |
| Charneiras plásticas | que a geometria desenhada dá as frações que o programa de Lajes calcula |
| Lajes | que a soma dos quinhões devolve o peso do painel, com e sem trecho rígido |
| Cortante em balanço e em vão | PL/GAs e wL²/8GAs somados às parcelas de flexão |
| Engastamento com cortante | que wL²/12 e wL/2 sobrevivem ao Φ |
| Trechos rígidos | δ = (P/EI)(Lf³/3 + cLf² + c²Lf), e a diferença de c³/3EI |
| Trecho rígido na flambagem | que a carga crítica cresce com (L/Lf)² |

Duas dessas merecem nota. **Carga parcial** é conferida contra um modelo em
que a barra foi dividida em três e a do meio recebeu carga uniforme de barra
inteira — ou seja, contra um caminho que as soluções fechadas já validaram. E
**recalque em estrutura isostática** tem de dar esforço nulo: é a conferência
que separa o recalque implementado como deslocamento prescrito da gambiarra
de aplicar uma força equivalente, que produziria esforço onde não há.

Esse último merece nota. A verificação de estabilidade é feita por fatoração
de Cholesky com conferência de razão de pivô, e não pelo `solve` genérico: em
uma barra com torção livre nas duas extremidades — mecanismo real — o `solve`
devolvia números sem reclamar, porque a diagonal da matriz continua cheia e
só a eliminação revela que o modo de giro rígido não tem vínculo. Quando o
mecanismo é detectado, o autovetor associado ao menor autovalor diz **quais
graus de liberdade** estão soltos, e a mensagem os nomeia.

## Formato do arquivo

JSON, descrito em `portico3d/arquivo.py`. O autoteste grava um exemplo em
`autoteste/exemplo.json`. É por esse formato que vão entrar, nas próximas
fases, os modelos vindos de planilha ou de CAD, e é ele que o orquestrador
vai ler quando o solver for acoplado aos programas de elemento.

## O executável

```
py construir.py                 monta, verifica e publica
py construir.py --sem-teste     pula a verificação (mais rápido)
```

Sai em `dist/`, no molde do Hidra: uma **pasta do programa**
(`Porticos.exe` mais `_internal`, que abre rápido) e um **arquivo único**
(`Porticos-portatil.exe`, cômodo de enviar, lento de abrir porque se
descompacta a cada vez). A receita é o `Porticos.spec`; o ícone é desenhado
por `criar_icone.py` — um pórtico de dois vãos com apoios engastados, sem
arquivo de arte para alguém ter de manter.

Depois de montar, `construir.py` **publica em `Pórticos 3D/Exe atual`**, que é
irmã das pastas de revisão. O nome quer dizer o que está escrito: ali fica o
build corrente, e a pasta é apagada e reescrita a cada construção — duas
versões convivendo ali seria justamente o que o nome promete que não acontece.

### Três coisas que o Hidra exclui e aqui são obrigatórias

`scipy` (autovalores da flambagem e sistemas esparsos), `openpyxl` (o quadro
de quantidades) e a dupla `python-docx`/`ezdxf` (memória de cálculo e CAD).
As duas últimas carregam **arquivos de dados** — os modelos .xml do docx, os
recursos do ezdxf —, que a receita coleta à mão: sem eles o pacote monta e só
falha na hora de gravar, que é o pior momento para descobrir.

Desde a troca do motor de desenho para PyVista/VTK, o `.spec` também arrasta
`pyvista`, `vtkmodules`, `pyvistaqt` e `qtpy` inteiros por `collect_all()` —
não há hook dedicado do PyInstaller para eles, e VTK importa centenas de
submódulos por nome em tempo de execução que a varredura estática não
descobre sozinha (a mesma receita de Consolos R03 e Lajes R06). Diferente do
Lajes, aqui `pyvistaqt`/`qtpy` **são** necessários: seis das sete vistas usam
o widget embutido, só a Armadura abre em janela nativa. Isso engorda o
executável em dezenas de MB — é o preço da vista interativa embutida.

### O que o empacotamento quebrou, e a conferência que ficou

Duas coisas funcionavam em Python e quebravam empacotadas. As duas foram
achadas rodando `--autoteste` **no executável**, que é a razão de
`construir.py` fazer isso antes de publicar.

**O motor de vento não carregava.** A cópia do NBR-6123 faz
`import nbr6123_data` sem ponto, como módulo de topo, e o carregador punha a
pasta dela no `sys.path` para que isso funcionasse. No executável essa pasta
não existe em disco — os módulos vivem dentro do arquivo —, o `sys.path` não
achava nada e o programa levantava `ModuleNotFoundError` na primeira conta de
vento. Hoje o carregador **registra o módulo em `sys.modules` sob o nome de
topo**, que funciona nos dois casos, e há conferência que refaz a carga com a
pasta fora do `sys.path` para provar isso.

**Metade dos motores de elemento ficava de fora.** O programa alcança boa
parte deles por nome montado em tempo de execução, e o que o PyInstaller não
vê importado ele não empacota. A receita passou a arrastar
`portico3d.elementos` inteiro: vendorizar é prometer que a cópia dentro do
programa é a cópia **inteira**, e a promessa vale também depois de empacotado.

Há ainda um terceiro caso, que não é defeito e sim limite: **as conferências
que olham o disco não podem rodar empacotadas.** Contar os `.py` copiados ou
ler o `requirements.txt` não faz sentido dentro de um executável, e as que
dependem disso agora **declaram que não se aplicam** em vez de reprovar.
Reprovar o que não se pode medir ensina o usuário a ignorar o relatório
inteiro. No lugar delas, o executável confere o que ali importa: que as sete
bibliotecas importem e que as sete portas dos motores de elemento respondam.

## Organização

```
main.py                     linha de comando
construir.py                monta o executável e publica em "Exe atual"
criar_icone.py              desenha o ícone
Porticos.spec               a receita do PyInstaller
portico3d/
    arquivo.py              leitura e gravação do modelo em JSON
    mastan.py               leitura dos modelos .mat do MASTAN2
    dimensionamento.py      a ponte da envoltória para os motores
    continuidade.py         reconhece as cadeias de viga contínua
    armadura3d.py           a armadura de um pavimento posta no espaço
    armadura_dxf.py         essa armadura em polilinhas 3D, para o CAD
    projeto.py              o edifício inteiro: calcula e emite
    recursos/               o ícone e o logotipo, desenhados por código
    saidas/
        memoria.py          a memória de cálculo em Word
        quantitativos.py    o quadro de quantidades em Excel, com fôrmas
        desenho_unico.py    a prancha única em DXF
    elementos/              cópias de Pilares, Vigas, Lajes e NBR-6123
    validacao.py            os problemas de referência
    core/
        modelo.py           nós, barras, seções, materiais, apoios, cargas
        elemento.py         rigidez 12×12, eixos locais, engastamento perfeito
        montagem.py         matriz global, vínculos, solução
        resultados.py       deslocamentos, reações, esforços, diagramas
        concreto.py         módulo de elasticidade pela classe (8.2.8)
        carregamento.py     segmentos de carga, engastamento por quadratura
        cargas.py           peso próprio e alternância de acidental
        lajes.py            painéis de carga e repartição às vigas
        nbr6118.py          γ, ψ, geração das combinações, desaprumo
        vento.py            integração com o programa NBR-6123
        programa_lajes.py   momentos e charneiras, pelo programa de Lajes
        combinacoes.py      superposição dos casos e caso efetivo
        envoltoria.py       extremos com esforços concomitantes
        segunda_ordem.py    rigidez geométrica, P-Δ e flambagem
        estabilidade.py     γz, α, majoração 0,95γz, rigidez secante
    ui/
        janela.py           janela principal e as ações
        tabelas.py          as doze tabelas de entrada
        conversao.py        modelo ↔ linhas das tabelas
        assistente.py       gerador de pórtico regular
        vista3d.py          modelo, sólido, laje, armadura, diagramas
        tema.py             paleta clara, a mesma dos outros programas
```

Além das 430 conferências numéricas, o autoteste **monta a janela sem tela** e
faz dois percursos. No primeiro, gera um pórtico pelo assistente, acrescenta e
remove linha em cada uma das doze tabelas, analisa, combina, avalia
estabilidade e flambagem, e desenha as nove vistas. No segundo, monta uma viga
**do zero pelas tabelas**, na ordem em que alguém montaria — material, seção
pelos lados, nós, barra apontando para os nós, apoios, caso, carga — e confere
que o momento no vão dá wL²/8.

O passo de acrescentar linha parece bobo e não é: foi exatamente ali que a
primeira versão quebrava, porque a célula nova nasce vazia e formatar vazio
como número derrubava a janela. Conferência de interface que só verifica se a
janela abre não pega esse tipo de defeito.

## Os motores de elemento são cópias, não importações

`portico3d/elementos/` guarda os `core/` dos programas de Pilares, Vigas e
Lajes — **cópias**, e não importações da pasta onde eles moram. O que se ganha
é reprodutibilidade: o resultado deste programa não muda sozinho quando
aqueles evoluem. O que se paga é ter de atualizar a cópia de propósito.

A procedência de cada uma está em `elementos/__init__.py`, e o autoteste
compara **byte a byte** com a origem quando ela está ao alcance. Cópia editada
à mão deixa de ser cópia e vira um garfo silencioso — a conferência existe para
que isso não passe.

**Procedência pelo commit (25/11/2026).** Os programas de origem viraram
repositórios git — `Vigas/Programa`, `Pilares/Programa`, `Lajes/Programa`,
uma tag por revisão — e as pastas de revisão (`Vigas R04`, `Pilares R05`,
`Lajes R11`) deixaram de existir. A `PROCEDENCIA` ganhou `repositorio`,
`pacote` e `commit`, e o autoteste confronta a cópia com o commit por
`git show`, comparando o conteúdo sem o fim de linha:

| Cópia | Commit de origem | Situação |
|---|---|---|
| Lajes | `fcc6aba` (tag R14 de `Lajes/Programa`) | recopiada em 25/11; idêntica, confrontada |
| Vigas | `1508440` (tag `motor-2026-11-25` de `Vigas/Programa`) | recopiada em 25/11; idêntica, confrontada |
| Pilares | `97c23ad` (tag `motor-2026-11-25` de `Pilares/Programa`) | recopiada em 25/11; idêntica, confrontada |

Desde 25/11 as três cópias vêm de um commit e são confrontadas com ele.

**Pilares recopiado em 25/11/2026 (`motor-2026-11-25`).** Pedido do Pórticos
ao programa de Pilares: o `dimensionar` ficou de 1,6 a 20 vezes mais rápido,
com resultado idêntico bit a bit lá. A cópia anterior era a pasta `Pilares
R05` de 05/11; entre ela e o commit o programa ganhou também verificação em
incêndio (NBR 15200, desligada por padrão), ações com combinações próprias,
seções vazadas e eixos principais — nada disso a ponte liga — e mudou dois
padrões: `exigir_interacao_17_2_5` desligado (parecer de 11/11) e a escolha
do arranjo por custo (`peso_por_barra` 0,02). No edifício de 3 pavimentos os
214 arranjos saíram os mesmos da cópia anterior e os mesmos do programa de
Pilares no commit; os pilares levaram 37 s em vez de 266 s.

**Vigas recopiado em 25/11/2026 (`motor-2026-11-25`).** O programa de Vigas
atendeu dois pedidos do Pórticos e ganhou outras coisas desde 03/11. O que
isso mudou aqui:

* **Barra pela mínima** (pedido): a barra que só existe porque As,mín
  governa para onde o momento negativo daquela face acaba, mais aℓ e ℓb,nec,
  e não no fim da região do apoio. Na V1 da sacada, as duas barras além das
  de canto do apoio 1 iam a 3,36 m e agora param em 1,56 m.
* **Seção L** (pedido): `Secao.lado_mesa`. A ponte o preenche na viga de
  borda — "esquerda" é o lado +1 de quem anda no sentido da cadeia — e o
  motor põe o laço da mesa só desse lado. O deslocamento da mesa que o
  desenho 3D fazia sai. E o desenho passou a levar o `u` da seção do motor
  (que cresce para a direita de quem olha a viga entrando no papel) para
  −(ẑ × eixo): antes ia para o +y local, que numa viga horizontal aponta para
  a **esquerda** — com a seção simétrica não aparecia, com a L sairia
  espelhada.
* **Solidariedade viga-pilar, 14.6.6.1** (novo no Vigas): a ponte deixa de
  calcular a mola ela mesma (`4EI/ℓ` do lance, metade da do item) e passa
  ao motor o pilar descrito — largura na direção da viga, a perpendicular e
  os lances acima e abaixo —, com o modelo `rigidez`: o motor faz
  `k = 4·Ecs·(I_sup/(ℓ_sup/2) + I_inf/(ℓ_inf/2))`, a rigidez da Figura 14.8.
  As correções do modelo clássico (alíneas a, b e c, feitas com a análise da
  viga isolada) não entram: no modo pórtico a envoltória é a do pórtico,
  onde a solidariedade é exata. A viga contínua daqui fica igual à do
  programa de Vigas montado à mão; muda o que sai dela (flecha, reações
  entre vigas, e os modos `motor` e `envolvente`).
* **Negativa de extremidade descendo no pilar** (corrigido no Vigas em 05/11,
  `e1afab0`): o motor aceita mola e apoio simples com o lance de baixo
  informado. A troca temporária para "engaste" que a ponte fazia na
  verificação de ancoragem (`_no_monolitico_na_ancoragem`) saiu.
* **Apoio em outra viga** (18.3.6): o apoio leva `viga_apoio`,
  `x_na_viga_apoio`, `h_viga_apoio` e os topos alinhados (o desenho nivela os
  topos do pavimento); a reação recebida leva a altura da viga apoiada, com
  que o motor reduz a carga de suspensão. Sem `viga_apoio`, o motor tomava o
  apoio por pilar.

Vieram o `core/` e o `saidas/` (é do `saidas/` que saem os desenhos das
peças); as interfaces ficaram de fora.

**Revisões em uso** (atualizadas em 2026-11-03):

| Elemento | Revisão | O que a troca trouxe para cá |
|---|---|---|
| Vigas | `motor-2026-11-25` (25/11) | seção L; barra pela mínima cortada pelo diagrama; solidariedade viga-pilar do 14.6.6.1; apoio em outra viga (18.3.6); itens complementares e furos na alma. Antes (R04, 03/11): arredondamento R·t/8 sobre o apoio (14.6.3) no lugar da redução à face; ancoragem das negativas e da torção nos extremos; ductilidade com o aço adotado; costura em faixas |
| Pilares | `motor-2026-11-25` (25/11) | dimensionar 1,6 a 20 vezes mais rápido, resultado idêntico; incêndio, ações, seções vazadas (não usados aqui); interação do 17.2.5 desligada por padrão; arranjo por custo. Antes (R05, 05/11): várias combinações por pilar com armadura comum; método geral; elipse do momento mínimo; desaprumo no balanço; busca exata dos arranjos (com processos paralelos, desligáveis por `PILARES_SEM_PARALELO`) |
| Lajes | Lajes R14 (25/11) | R14: DXF da laje treliçada e da nervurada unidirecional, quantitativo por bitola da treliçada. R12: negativa da borda comum centrada no eixo da viga, balanço reconhecido também pelos vínculos, bordo livre de balanço sem continuidade (sacadas vizinhas); R13: ancoragem no apoio pelo 18.3.2.4, ℓb ≥ 25Ø, 4 cm além do eixo. Antes (R11, 05/11): laje em balanço reconhecida pelo destino; fissuração nas bordas comuns; nervurada, alveolar, MEF de placa (não usados aqui) |

Do Pilares ficou de fora o `compat_pcalc.py`: é o modo de
compatibilidade com o PCalc, que não é verificação pela NBR, e o motor o
importa como opcional.

**Custo.** O Pilares R05 verificava a envoltória e a seção mínima com mais
rigor, e cada combinação de cada lance levava cerca de 4 s (no pórtico de três
pavimentos da conferência de continuidade, 18 lances); com o
`motor-2026-11-25` e o paralelismo do Pórticos, os 214 lances do edifício de
3 pavimentos levam 37 s. O tempo é do motor, e
a cópia não se edita; a ponte o chama uma vez por combinação governante.

**O que a troca para o Vigas R04 mudou nos resultados:**

* **Ancoragem da negativa nos apoios de extremidade** (18.3.2.4-d, a partir
  da face). Quando o trecho reto não basta, o motor faz a barra descer no
  pilar — mas só admite isso no apoio "engaste", e a ponte representa o
  pilar como "mola" (a rigidez dos lances) ou "simples". Sem ajuste, 18 das
  21 vigas do exemplo residencial reprovavam com "não há onde a barra
  descer", com o pilar lá. A ponte agora passa ao motor a **altura do pilar
  abaixo da viga** (`altura_do_pilar_abaixo`, campo previsto no R04, que o
  motor usa para conferir se a perna cabe) e, **só durante a verificação de
  ancoragem**, apresenta o apoio de extremidade com pilar embaixo como o nó
  monolítico que ele é (`_no_monolitico_na_ancoragem`). A análise da viga
  isolada (flecha, reações) continua com mola ou apoio simples. Como a
  envoltória, a troca é por fora: a cópia não é editada.
* **Secundárias apoiadas em viga.** As três V7 do exemplo (uma por
  pavimento) se apoiam em vigas, sem pilar. O pórtico lhes dá negativo nas
  pontas pela rigidez à torção das vigas de apoio, e a ancoragem a partir
  da face não cabe: 17 cm de apoio contra até 73 cm exigidos (Ø16). É
  veredito do motor, não defeito da ponte — as três ficam reprovadas, e a
  conferência trava que essa seja a única razão de reprovação do exemplo.
* **Laço da mesa.** Na seção T o R04 detalha o laço que abraça a mesa, com
  barras de canto dentro da laje, fora da alma. O desenho 3D já as punha no
  lugar certo; a conferência de "barra dentro da seção" passou a aceitar
  barra fora da alma quando ela cai na faixa da laje.

## Cache e paralelismo dos motores (2026-11-25)

O motor de Pilares é a parte lenta do programa — no edifício de 3 pavimentos,
214 verificações de lance a uns 5 s cada —, e a mesma verificação era feita
de novo na armadura 3D de cada pavimento, no projeto completo e na
compatibilização. `cache_motores.py` resolve as duas coisas sem tocar nas
cópias:

* **Cache pela impressão da entrada.** O resultado do motor fica guardado
  pelo SHA-256 do `para_dict()` da entrada (o `asdict` dela inteira); na
  viga, mais a impressão da envoltória externa que a ponte aplica
  (`envoltoria_externa` a anota em `aplicar.chave`; envoltória sem
  impressão não é guardada). Entrada diferente, chave diferente: modelo
  alterado nunca reaproveita resultado velho e não há invalidação a
  esquecer. Guarda os 5000 mais recentes de cada motor.
* **Pilares em paralelo.** `verificar_pilares` monta primeiro todos os
  `Pilar` e passa o lote de uma vez; os que não estão no cache vão para um
  pool de processos (núcleos − 1, no máximo 8), com a busca paralela do
  próprio motor desligada nos filhos (`PILARES_SEM_PARALELO`). A ordem e o
  resultado são os da execução em série; pool que falha cai para série.
  `PORTICOS_SEM_PARALELO=1` desliga. `main.py` chama
  `multiprocessing.freeze_support()` para o executável.
* `armadura_do_pavimento` chama `verificar_pilares` uma vez por cota, com
  todos os lances, em vez de uma vez por lance.

Medido no edifício de 3 pavimentos (`edificio_3pav.py`), mesma máquina:

| etapa | antes (s) | depois (s) |
|---|---|---|
| análise com 2ª ordem | 1,1 | 1,5 |
| pilares (214 verificações) | 1097,5 | 224,1 |
| vigas (24 cadeias) | 5,7 | 6,4 |
| lajes | 0,8 | 0,7 |
| armadura 3D, cota 3 m | 313,7 | 0,9 |
| armadura 3D, cota 6 m | 292,3 | 0,9 |
| armadura 3D, cota 9 m | 287,6 | 1,2 |
| **total** | **1998,7** | **235,7** |

Os pilares, as posições de armadura das vigas e a contagem de barras do 3D
saíram idênticos nas duas rodadas. Conferências: em
`ponte_roda_o_lote_do_edificio`, série × paralelo × cache no mesmo lote.

Depois disso o programa de Pilares otimizou o próprio motor (pedido
daqui) e ele foi recopiado (`motor-2026-11-25`): os pilares do mesmo
edifício caíram de 266 s para 37 s (no script de verificação), e o autoteste inteiro, de 18 para
2,5 minutos.

## As pranchas (2026-11-25)

`saidas/pranchas.py` substitui o "desenho único" (um DXF com todas as peças
lado a lado no espaço do modelo) por pranchas de verdade: o arquivo
`desenhos.dxf` do projeto completo tem o espaço do modelo em verdadeira
grandeza, em centímetros, e **uma folha (layout) por prancha**, com moldura
(margens da NBR 10068), carimbo de 178 mm e as vistas em janelas
(*viewports*) na escala.

**Ordem.** Por pavimento: planta de forma, armação das lajes, armação das
vigas; depois os pilares, prumada a prumada e de baixo para cima (o arranjo
de cada lance é o adotado, `_arranjo_adotado`); por último o quadro de
quantidades. As vistas de um mesmo conteúdo são empacotadas por linhas, na
ordem, desviando do carimbo e das notas; a folha com uma vista só a leva ao
centro.

**Escala.** Os programas de elemento escrevem o texto em centímetros do
modelo — 2 cm no pilar, 5 cm na viga, 8 cm no pavimento de lajes —, cada
um supondo uma escala de impressão. A vista vai na maior redução em que o
texto predominante sai com pelo menos 1,6 mm (`TEXTO_MIN`): 1:10, 1:25 e
1:50. Se não cabe na A1, a folha passa a A0 na mesma escala; só se nem a A0
bastar a escala cresce. No edifício de 3 pavimentos: 3 formas A1 a 1:50, 3
folhas de lajes A0 a 1:50, 18 folhas de vigas A0 a 1:25 (uma ou duas vigas
por folha), 18 de pilares A1 a 1:10 (dois lances por folha) e o quadro —
43 folhas, geradas em 10 s.

**Planta de forma.** Desenhada aqui (`planta_de_forma`, `desenhar_forma`):
cada face de viga e cada borda de laje é recortada pelos retângulos das
outras vigas e dos pilares (recorte de segmento contra retângulo, sem
dependência nova); a viga avança, em cada ponta, meia largura da viga
transversal que chega ao nó, para fechar o canto. Pilar com os eixos locais
da barra (o girado sai girado); hachura se chega por baixo, X se nasce no
pavimento. Os rótulos (nome e seção; nas lajes, nome e h, "TR" na
treliçada) procuram, entre posições candidatas, uma que não caia sobre
outro rótulo nem sobre pilar. Cotas entre eixos de pilar por cima e pela
esquerda, e a total entre faces extremas.

**Cotas dos motores.** O importador do ezdxf trazia as cotas (DIMENSION)
sem o bloco anônimo da geometria: no CAD o AUDIT as apagava (567 no
edifício de 3 pavimentos). Antes de importar, as cotas são explodidas na
origem (linhas, setas, textos). O mesmo valia para o DXF do "Dimensionar
vigas" (`desenho_unico`), corrigido também. Camadas que os desenhos usam
sem declarar (o "BARRA" do Vigas) são criadas no destino.

**Conferências** (seção 50b e o fim de `lancamento_dimensiona_ponta_a_ponta`):
na planta de forma do exemplo residencial, todo pilar, viga e laje da cota
com rótulo, nenhum rótulo sobre outro, nenhuma face de viga por dentro de
pilar, hachura só nos pilares que chegam por baixo, cotas parciais iguais
aos vãos entre pilares medidos no modelo; na diagramação, as escalas 1:10,
1:25 e 1:50 pelos textos de 2, 5 e 8 cm, a viga que não cabe na A1 indo
para a A0 na mesma escala, o empacotamento de cinco vistas em 2 + 2 + 1;
no projeto ponta a ponta, uma forma por pavimento, toda viga e todo lance
numa folha, nenhuma sobreposição e o AUDIT sem erro nem correção.

### R05 (2026-11-25): pranchas completas

* **Pilares iguais numa vista.** Cada lance é exportado pelo motor e
  ganha uma assinatura do desenho sem o nome da peça (tipo, camada e caixa
  de cada entidade; texto e ponto de inserção dos textos, com o nome
  trocado por `#`). Lances com a mesma assinatura saem desenhados iguais e
  vão numa vista só, com todos os nomes no título (que quebra em até quatro
  linhas) e o aço multiplicado. P2 (50x20) e P5 (20x50) juntam: é a mesma
  peça girada em planta, e o motor de Pilares a desenha igual. No edifício
  de 3 pavimentos, 36 lances viram 6 vistas, e as folhas de pilar caem de
  18 para 3.
* **Numeração por folha.** Cada motor numera as posições a partir de N1;
  depois de montadas as folhas, todo texto das vistas de uma folha
  (rótulos, chamadas, tabela de posições) é renumerado na ordem das vistas
  e, dentro de cada uma, na ordem do motor (`numerar`, padrão
  `(?<![A-Za-z0-9])N(\d+)(?![0-9])`). O desenho e a tabela de cada peça
  continuam batendo; a folha não tem dois N1.
* **Resumo do aço da folha.** Por bitola, comprimento e massa, total e
  total com 10 % de perdas, logo acima do carimbo (as notas sobem). O aço
  de cada vista vem do motor: `quantitativo["por_bitola"]` na viga e no
  pavimento de lajes, `quantitativos.calcular(...).aco` no pilar (barra
  longitudinal com a espera, e os estribos), vezes os lances iguais. A
  reserva acima do carimbo é calculada por grupo, com todas as bitolas dele.
* **Cortes esquemáticos.** A-A (plano y = constante, olhando para +Y) e B-B
  (x = constante, olhando para +X), no meio do maior intervalo central entre
  linhas de nó (pilares e vigas): o plano nunca cai sobre um eixo de viga —
  caía, na primeira versão, sobre a secundária do exemplo residencial, e
  cortava as duas barras que terminam no nó. Lajes e vigas atravessadas
  pelo plano em traço grosso e hachuradas, com o topo no nível do
  pavimento; além do plano, a primeira linha de vigas paralelas e a primeira
  linha de pilares, em traço fino, recortadas pelo que está na frente;
  níveis em metros à esquerda (base e topo de cada pavimento). A linha de
  cada corte, com as letras, vai nas plantas de forma.
* **Folhas** do edifício de 3 pavimentos: 3 formas, 3 lajes, 18 de vigas, 1
  de cortes, 3 de pilares e o quadro — 29, em 10 s.

**Conferências** (`cortes_esquematicos` e o fim de
`lancamento_dimensiona_ponta_a_ponta`): vigas e lajes cortadas e lances
vistos contados contra o modelo, um nível por pavimento; todo lance de pilar
numa vista e uma vez só, os lances de uma vista iguais pelo resultado do
motor (seção, barras, bitola, estribos, comprimento, espera — e não pelo
desenho que os agrupou), menos vistas que lances; numeração por folha sem
repetir entre vistas e sem buraco; o resumo do aço de todas as folhas igual
à soma do aço que os motores calcularam.

**Laje treliçada (Lajes R14, 25/11).** O programa de Lajes passou a
desenhar a treliçada em DXF (`saidas/dxf_trelicada.py`, pedido daqui), no
padrão das maciças, e a guardar `quantitativo["por_bitola"]` e
`quantitativo["trelicas"]`. Cada faixa treliçada aprovada vira uma vista na
folha de lajes da cota; as vigotas entram no resumo do aço em linha própria
(`vigota <designação>`), porque não são barra de bitola. A conferência do
resumo passou a somar o `aco_kg` de cada faixa.

**Pendente.** Cortes cotados e detalhes típicos.

## A ponte com o dimensionamento

`Dimensionar pilares` (F7) gera as combinações últimas, monta a envoltória e
entrega a cada lance vertical os trios de esforço **concomitantes** que o
governam — que é exatamente o que a flexão composta oblíqua precisa, e a razão
de a envoltória guardar os concomitantes desde a fase 2. O veredito é do motor
de Pilares; daqui sai só a tradução.

**Três coisas mudam na fronteira, e cada uma tem conferência própria.** É
justamente por os dois programas falarem línguas parecidas que a tradução é
perigosa:

| | Aqui | No programa de Pilares |
|---|---|---|
| Unidade | kN e **metro** | kN e **centímetro** |
| Normal | negativo à compressão | `Nd` **positivo** à compressão |
| Eixo | `Mz` tem excentricidade em y local | `Mx` tem excentricidade em x |

A última é a que engana: a letra coincide e o significado não. O `Mx` de lá
recebe o **`Mz`** daqui. Numa barra vertical o eixo local y é o X global e o
local z é o Y global, então a seção do pilar sai alinhada com os eixos do
prédio sem giro nenhum, e `hx` recebe o lado `b`.

Base e topo saem da **cota**, não da ordem dos nós da barra: barra lançada de
cima para baixo é comum em modelo gerado, e trocar topo com base inverteria a
curvatura que o item 15.8.2 lê para achar o α_b.

Armadura, cobrimento, agressividade e arranjo continuam sendo do programa de
Pilares.

### Vigas contínuas

No modelo do pórtico não existe "viga de três vãos": existem três barras
alinhadas, uma atrás da outra. `continuidade.py` ensina o programa a ver o que
quem lê o desenho vê — duas barras entram na mesma viga quando são
horizontais, colineares e se encontram num nó.

Dentro da cadeia, os nós se dividem em dois, e a distinção define os vãos:
**apoio** é o nó em que chega um pilar; **passagem** é o nó que existe só
porque a malha foi dividida ali. Tratar um nó de passagem como apoio
inventaria um vão que não existe — há conferência com uma viga de quatro
barras que tem três vãos, justamente por causa disso.

`Dimensionar vigas` (F6) monta a viga do programa de Vigas a partir da cadeia
— vãos, seção, largura dos apoios tirada do pilar, e as cargas traduzidas para
a coordenada da viga em kN/m positivos para baixo —, chama o
`dimensionar` dele e **atualiza o modelo 3D da armadura**. Não pergunta pasta
nem grava nada: a prancha (a elevação com armadura e estribos, o quadro de
barras explodido e as seções) sai em `Emitir ▾ > Pranchas de vigas`, quando o
usuário pedir, a partir do último dimensionamento — sem calcular de novo. É o
mesmo para `Dimensionar lajes` (`Emitir ▾ > Pranchas de lajes`) e para
`Dimensionar pilares`, que também só atualiza o modelo 3D. O desenho é o do
programa de Vigas; daqui sai só a tradução e o destino.

**Antes**, os três botões pediam a pasta antes de calcular e gravavam
desenho na hora, mesmo quando o usuário só queria ver o resultado; agora
dimensionar e imprimir são dois passos. Rodar `Dimensionar` duas vezes seguidas
com as tabelas iguais não descarta o que foi guardado (a assinatura das
tabelas é comparada), e é isso que deixa a prancha sair sem recálculo.

**Viga apoiada em viga.** Onde duas vigas se encontram num nó em que não chega
pilar, uma **repousa na outra**: em V1, que se apoia, a V2 entra como
**apoio** (simples e indeslocável, com a largura da seção de V2), e em V2, que
recebe, a V1 entra como **carga concentrada** — a reação de V1 naquele nó,
separada em permanente e variável porque o motor combina as duas com os
próprios coeficientes. A carga entra como **indireta** (item 18.3.6), o que faz
o motor armar a suspensão; e se a viga apoiada é mais alta que a de apoio
(face de baixo abaixo da outra), é **viga pendurada**, com a conta do tirante
inteiro.

**Só serve de apoio a viga que está segura naquele ponto.** O nó tem de cair
*dentro* dos vãos da viga de apoio, entre o primeiro e o último apoio dela. Na
ponta de um balanço não há apoio: a ponta deforma, e tratá-la como apoio
indeslocável fazia a outra viga sair dimensionada como uma viga apoiada
qualquer. Foi o defeito de **retirar um pilar de canto**: as duas vigas que
chegavam nele viravam balanços, mas uma "se apoiava" na ponta da outra e saía
com a armadura de uma viga comum. Agora as duas ficam em balanço, com o
encontro das pontas como aviso no resultado. Quem apoia quem sai de onde o
nó cai, e só desempata por prioridade; as vigas são dimensionadas das que
repousam nas outras para as que recebem, e um ciclo (A em B, B em C, C em A) é
desfeito. Entre as que podem servir de apoio, vale a prioridade **da viga inteira**: mais apoios de pilar, depois a maior altura de seção, depois
a mais comprida, e o nome só para desempatar. No caso corrente — uma
secundária que nasce no meio de uma principal —, a principal tem os dois
pilares e leva a prioridade. As vigas são dimensionadas das mais secundárias
para as mais principais, porque a reação de uma só se conhece depois que ela
está pronta. A reação variável é a **máxima** possível no apoio (soma das
parcelas positivas dos casos-base), e a permanente é a da viga toda carregada.

Duas simplificações declaradas, e que aparecem como aviso no resultado da
viga apoiada: o apoio na viga de apoio é **indeslocável** (a flecha dela não
entra) e **sem restrição à rotação** (a torção dela não entra). Se uma viga
apoiada falha no dimensionamento, a viga de apoio avisa que aquela reação NÃO
entrou como carga. Junto veio a correção de um defeito antigo: uma viga com
**balanço depois do último pilar** perdia esse apoio na tradução (a lista de
apoios do motor saía um a menos que os tramos), o que agora tem conferência.

**De onde saem os momentos.** Aquele programa faz a própria análise da viga
contínua. Até 2026-10-16 os momentos de apoio saíam dela, e não da rigidez que
o pórtico 3D conhece. Agora, por padrão, a envoltória ELU do **pórtico**
substitui a dele — ver "Vigas armadas pelo pórtico". A análise própria do
motor segue valendo para o ELS, as reações e a suspensão, e volta a ser a fonte
inteira com a opção "Só a viga contínua (g e q)".

A carga é conferida pelo **total**: a soma de q·comprimento dos trechos
traduzidos tem de dar a carga que o pórtico tem, senão a viga seria
dimensionada para menos do que carrega.

### Lajes

`Dimensionar lajes` (F4) vai por **pavimento**, e não painel a painel, porque a
compatibilização dos momentos negativos do item 14.7.6.2 acontece entre painéis
vizinhos — as duas lajes de uma borda comum recebem **uma** armadura negativa,
dimensionada para o maior dos dois momentos. Painel sozinho não tem com quem
compatibilizar.

Três coisas que a tradução tem de acertar, e o programa de Lajes reclama quando
erradas:

* **O vão é o livre**, descontada meia viga de cada lado. O painel do pórtico é
  definido por nós, que estão nos eixos das vigas; o programa de Lajes espera o
  vão livre mais a largura do apoio, e monta o vão efetivo do item 14.7.2.2 a
  partir dos dois. Passar eixo a eixo daria uma laje maior do que ela é.
* **A continuidade quem detecta é ele**, pela posição dos painéis em planta.
* **Detectar não basta: é preciso aplicar.** `aplicar_continuidades` é o que
  engasta os bordos e anota a vizinha. Só detectar deixava os bordos apoiados,
  e o programa acusou a incoerência — foi assim que este passo apareceu.

Saem duas plantas de armação por pavimento, a da face inferior e a da superior,
com as posições numeradas e as bitolas. São os desenhos do programa de Lajes.

Um detalhe de leitura do resultado: `ResultadoPavimento` **não tem um campo
`ok`** — o veredito é a lista de erros estar vazia. Perguntar por um `ok` que
não existe devolvia sempre "com ressalva", e o relatório mentia sem falhar.

### Vigas: o que o pórtico sabe e o motor não

O motor de Vigas resolve a viga contínua a partir das cargas e das **suas**
combinações, e isso deixava três coisas para trás. As três estão corrigidas, e
vale saber quais são porque cada uma muda o resultado:

**A rigidez dos pilares.** Os apoios não vão como rótula. Até 25/11 a
ponte passava uma mola de `4EI/ℓ` por lance; desde a recópia do Vigas
(`motor-2026-11-25`) ela passa o pilar descrito e o motor faz a mola do
14.6.6.1 (modelo `rigidez`, Figura 14.8) — ver "Vigas recopiado em
25/11/2026". A inércia é medida **na direção da viga**: pilar 20×60 com os
60 cm no rumo da viga trava muito mais que o mesmo pilar virado, e há
conferência travando isso pela razão dos cubos.

**O peso próprio, uma vez só.** Ele vem do pórtico, e o do motor fica
desligado. Antes os dois entravam: na viga 20×50 do exemplo, 2,5 kN/m sobre
10,4 — **24 % a mais de carga permanente**, somados numa distribuída só, sem
nada na memória de cálculo dizendo que metade daquilo foi contada duas vezes.
Desligar sem conferir seria trocar carga a mais por carga a menos, que é pior:
se o pórtico não trouxer nem o peso da própria seção, sai aviso.

**As ações laterais.** O motor combina apenas `g` e `q` — não há como dar
vento a ele. E o vento não é detalhe: na viga do exemplo ele produz 63 kN·m,
**mais que o peso permanente**, e não chegava à armadura.

A ponte não finge que resolveu isso. Ela **confere**: a armadura detalhada é
confrontada com a envoltória do pórtico ponto a ponto, e a viga é reprovada
quando não cobre. A comparação é em **área de aço na face tracionada**, e não
em momento, de propósito — momento é grandeza intermediária, dois momentos
parecidos pedem armaduras diferentes se caírem em faces opostas, e um momento
de sinal trocado (o vento revertendo o apoio) não tem razão numérica que o
descreva. O As exigido sai da mesma função de flexão que o motor usa, com a
mesma seção e o mesmo d, de modo que a diferença entre os dois números seja
**só** a solicitação.

No exemplo isso reprova a V1 no último apoio: o pórtico pede 5,38 cm² na face
superior e o detalhamento tem 1,51 cm² — 3,6 vezes.

Injetar momentos fictícios para forçar a passagem foi tentado e descartado: no
apoio interno um momento nodal cria salto no diagrama, o sinal muda de uma
extremidade para a outra, e uma memória de cálculo com carregamento inventado
não é conferível por ninguém.

**Os estribos saem numa distribuição só por tramo, não escalonados.** O motor
de Vigas já tinha o botão pronto para isso — `Config.uniformizar_estribos`,
que funde as faixas do escalonamento fino na mais conservadora (o menor
espaçamento, com a maior bitola), estendida de ponta a ponta do trecho, pelo
item 18.3.3.2 — e a ponte é que não o acionava. Agora aciona sempre: sai mais
aço do que o escalonamento fino, e sai uma peça só para montar e conferir na
obra.

**O desenho da viga sai num DXF só, com todas lado a lado, e sem PNG.** Antes
cada viga gravava um par de imagens (elevação e seções) mais um DXF; num
edifício com vinte vigas contínuas isso são sessenta arquivos, a metade deles
imagem que ninguém abre fora do programa. Pular o render em matplotlib das
imagens — que ninguém consome aqui — é o que mais barateia o tempo: medido no
exemplo de vinte vigas, a geração dos desenhos caiu de 15,1 s para 4,0 s.
A prancha única é montada do mesmo jeito que a do projeto inteiro — cada
desenho é importado com a própria camada e transladado para a sua vaga, numa
coluna —, e o título de cada viga vem do próprio DXF que ela já grava, sem
duplicar.

## O projeto completo (F2)

Um botão, três arquivos, e é o que fecha o programa:

| | |
|---|---|
| `memória de cálculo.docx` | dez capítulos: metodologia, modelo, esforços, estabilidade global, reações, pilares, vigas, confronto com a envoltória, lajes e quantitativos |
| `quadro de quantidades.xlsx` | resumo, quantidades por tipo de peça, aço por bitola e o veredito peça a peça |
| `desenhos.dxf` | uma prancha com todas as peças detalhadas, em colunas por tipo, mais o quadro de quantidades desenhado |

O que só existe neste nível — e é a razão de o programa existir — são os
capítulos de **esforços do pórtico**, **estabilidade global**, **reações** e
**confronto**. O passo a passo de cada peça continua nos relatórios dos
motores de elemento: reescrevê-lo aqui seria duplicar código que pode
divergir, e o que a memória do edifício traz de cada peça é a síntese
verificável — solicitação, armadura adotada, detalhamento com bitolas,
ancoragem, traspasse e esperas, e o veredito.

A prancha é montada importando o desenho de cada peça inteiro, com as camadas
que ele trouxe, e transladando-o para a sua vaga. As vagas saem da **extensão
real** de cada desenho, medida depois de importado: desenho de viga de três
vãos é bem mais largo que o de um vão, e um passo fixo ou os sobreporia ou
deixaria meia prancha vazia.

### Fôrmas

O critério é o do vazamento — conta-se só a face que precisa conter o
concreto — e por isso a área de fôrma não coincide com a área das peças:

**Laje.** Fundo descontada a faixa que se apoia sobre a viga: essa faixa já é
fôrma da viga, e contá-la nas duas peças mede a mesma chapa duas vezes. Mais o
fechamento lateral **só nos bordos livres** — onde o bordo apoia numa viga, a
lateral dela já sobe e fecha; onde é bordo comum com outra laje, o concreto é
contínuo e não há o que fechar.

**Viga.** Fundo integral, mais cada lateral com `h` menos a espessura da laje
que encosta **naquele lado**. Viga entre dois painéis desconta dos dois lados;
viga de bordo, de um só. O topo nunca leva: é por onde se concreta.

**Pilar.** Perímetro moldante vezes a altura do lance.

Os dois primeiros critérios vêm dos próprios motores (`lajes.core.formas` e
`pilares.core.quantitativos`); o da viga é calculado aqui, e é o caso que
justifica a conta ser deste nível — o motor de Vigas não conhece as lajes
vizinhas, e sem elas não há como saber qual lateral está fechada.

### DXF, e não DWG

Cada viga e cada pavimento saem também em **DXF**, com as camadas separadas —
`FORMA`, `EIXO`, `ARM_POSITIVA`, `ARM_NEGATIVA`, `ARM_DISTRIB`, `TEXTO`,
`COTAS` — prontas para o CAD.

**DWG não sai, e a razão é de formato, não de esforço.** O DWG é binário,
proprietário e fechado da Autodesk; não há especificação pública para escrevê-lo.
A biblioteca de CAD usada aqui (ezdxf) grava DXF, que é o formato de troca que a
própria Autodesk publica e que AutoCAD, BricsCAD, QCAD, Revit e afins abrem sem
conversão nenhuma. Quem precisar de DWG converte com o **ODA File Converter**,
gratuito e instalado à parte — o `ezdxf` até sabe chamá-lo, mas depender de um
executável externo para fechar o fluxo do programa não pareceu troca boa.

Na prática o DXF costuma ser o que se quer: preserva camadas, cotas e textos, e
é editável do outro lado.

### Ter veredito e ser aprovado são coisas diferentes

O motor de Pilares pode concluir a verificação inteira e **reprovar** o lance —
o caso comum é nenhum arranjo de barras caber nas bitolas permitidas, e aí o
arranjo volta vazio e o erro fica nos avisos. `passou` só diz que houve
veredito; quem diz que o veredito foi bom é `aprovado`, que lê o `ok` dele.

A distinção não é preciosismo: enquanto o relatório contava por `passou`, um
lance reprovado aparecia entre os verificados sem que uma linha dissesse que
ele não passou. Hoje o resumo separa "sem veredito" de "REPROVADAS" e traz o
motivo nas palavras do motor. Foi a vista de Armadura que revelou isso — quatro
dos seis pilares do térreo do exemplo saíam sem barra nenhuma, em silêncio.

Fundações ainda não têm ponte — ver a tabela de escopo.

## Aferição contra o MASTAN2

O programa se propõe a substituir o MASTAN2, e a maneira honesta de sustentar
isso é resolver os mesmos modelos e comparar número a número. O módulo
`mastan.py` lê os arquivos `.mat` do MASTAN2 — geometria, seções, eixos locais
das barras, vínculos, cargas em eixos de barra e peso próprio — e o autoteste
confronta os resultados com os que o próprio MASTAN gravou no arquivo.

Nos oito modelos de referência da pasta `MASTAN`, um edifício de 68 nós e 112
barras em oito casos de carga, as diferenças ficam na ordem de **10⁻¹³
relativo**: deslocamentos, reações e esforços de extremidade coincidem até o
arredondamento de ponto flutuante. Não há tolerância de engenharia envolvida
— os dois programas resolvem o mesmo sistema e chegam ao mesmo número.

Dois pontos que a leitura do formato exigiu resolver, e que valem saber:

* **No MASTAN2 o vertical é Y; aqui é Z.** A conversão é a permutação cíclica
  `(x, y, z) → (z, x, y)`, escolhida entre as seis possíveis por ser **rotação
  e não reflexão**. Qualquer permutação ímpar inverteria a mão do sistema, e
  com ela o sinal de toda torção e de todo momento.
* **O peso próprio do MASTAN2 não aparece na tabela de cargas.** Ele é gerado
  do peso específico do material, e só se descobre isso fechando o equilíbrio:
  nos modelos de referência, a soma das cargas distribuídas dá 11 041,28 kN e
  a reação vertical 13 588,16 kN; a diferença de 2 546,88 kN é exatamente o
  volume de barras vezes o peso específico declarado.

A convenção de sinal dos esforços de extremidade coincide com a nossa sem
troca alguma — conferido por comparação direta, com a variante de sinal
trocado dando 200 % de erro, como tem de dar.

## A norma nesta implementação

Os valores normativos foram transcritos da ABNT NBR 6118:2026 — a edição que
renumerou tabelas em relação à de 2014 mantendo o conteúdo dos itens. As
referências estão no cabeçalho de `nbr6118.py`: 11.3.3.4.1 e Figura 11.1 para
o desaprumo, Tabela 11.1 para γf, Tabela 11.2 para ψ, Tabela 11.3 para as
combinações últimas e Tabela 11.4 para as de serviço.

Três pontos em que a leitura literal da norma decidiu a implementação:

1. **A combinação rara usa ψ1 nas ações secundárias**, não ψ0 — Tabela 11.4.
   É onde a implementação distraída erra.
2. **γg = 1,0 fica fora por padrão.** A nota ᵃ da Tabela 11.3 dispensa, "no
   caso de estruturas usuais de edifícios", as combinações com o permanente
   favorável. Para os demais casos existe o parâmetro que as gera.
3. **θ1mín = 1/300 e θ1máx = 1/200**, com θ1 = 1/(100√H) e
   θa = θ1·√[(1+1/n)/2]. A regra dos 30 % entre vento e desaprumo está
   implementada nos três ramos do item, e a norma dispensa o desaprumo no ELS.

Não são valores de memória: saíram de uma leitura do PDF da norma feita para
esta implementação.

Do item **8.2.8**, um achado que muda como o programa se confere: a edição 2026
**removeu a tabela de valores estimados de E_ci e E_cs por classe** que a de
2014 trazia — a numeração 8.1 passou para a tabela de retração e fluência. Não
há mais tabela normativa contra a qual bater os módulos, e por isso as
conferências atacam as fórmulas por outro lado: o valor calculado à mão, o
ponto exato em que α_i satura (C80), e sobretudo a **quase continuidade entre
os dois ramos em f_ck = 50 MPa** — 39 598 MPa por um, 39 603 pelo outro, 0,013 %
de diferença. São expressões independentes, com coeficientes diferentes; elas
só se encontram ali se ambas estiverem transcritas certo.

Vale registrar que os valores de C20 a C50 reproduzem exatamente os números da
antiga tabela — 25 044, 28 000, 30 672, 33 130, 35 418, 37 566 e 39 598 MPa.
Para as classes altas não há tabela nesta edição, e o valor é o da fórmula.

Para a estabilidade global valem os itens 15.4.2 (nós fixos e móveis, com o
critério dos 10 %), 15.5.2 (α e os limites α1), 15.5.3 (γ_z, válido a partir de
quatro andares, nós fixos até 1,1), 15.7.2 (majoração por 0,95·γ_z, só até
γ_z = 1,3) e 15.7.3 (rigidez secante). Mais três pontos que a leitura fixou:

4. **γ_z pede no mínimo quatro andares** (15.5.3). Abaixo disso o programa
   calcula, mas marca o resultado como informativo e não normativo.
5. **O valor único (EI)_sec = 0,7·E·I sumiu.** A edição de 2014 o permitia para
   contraventamento composto exclusivamente por vigas e pilares com γ_z < 1,3;
   a busca no PDF de 2026 não encontrou esse parágrafo. Por isso ele não é
   oferecido aqui, e quem vier de projeto antigo vai estranhar a ausência.
6. **Na análise global E_cs pode ser majorado em 10 %** (15.5.1). O programa
   não faz isso sozinho — é decisão de quem monta o material.

O `core` não importa nada de interface: é biblioteca pura, chamável por outro
programa. Foi assim que os programas de elemento foram organizados, e é o que
torna possível o acoplamento previsto para a fase 4.
