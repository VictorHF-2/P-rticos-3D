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
py main.py --autoteste                 roda as 277 conferências de referência
py main.py modelo.json [caso]          resolve um caso e imprime o resumo
py main.py modelo.json --envoltoria    gera as combinações da NBR 6118,
                                       resolve todas e imprime a envoltória
py main.py modelo.json --estabilidade  γz por combinação, classificação de
                                       nós fixos ou móveis, e flambagem
```

Dependências: `py -m pip install -r requirements.txt` (numpy, scipy, PySide6 e
matplotlib).

## A janela

Tabelas à esquerda, desenho à direita, relatório embaixo. O caminho é montar,
analisar e ler o resultado, e a interface existe só para encurtá-lo: não há
uma linha de mecânica nela, e é de propósito — tudo continua no `core`, que é
o que as 277 conferências cobrem.

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

**A deformada não liga os nós deslocados por retas.** Ela é traçada com as
mesmas funções de forma que o solver usa para o engastamento perfeito, de modo
que a curva desenhada é a que a formulação descreve — inclusive a curvatura
dentro de uma barra carregada, que a ligação por retas esconderia justamente
onde ela interessa. A escala vai escrita no título, porque deformada em escala
real de um pórtico bem projetado é uma linha reta.

O visualizador é matplotlib, e não uma biblioteca 3D dedicada, para não
acrescentar dependência ao que os outros programas da pasta já usam. O preço é
a rotação ficar lenta em modelo muito grande; é a peça mais isolada do
programa, e trocá-la um dia não mexe em mais nada.

## O que já faz, e o que ainda não faz

Hoje o programa vai da geometria à envoltória: monta e resolve o pórtico
espacial para cada caso de carga, gera as combinações últimas e de serviço da
NBR 6118, superpõe os resultados e devolve, por barra, os extremos de esforço
com os valores concomitantes e a combinação que os governou.

| Fora do escopo desta revisão | Fase prevista |
|---|---|
| Ponte com os programas de elemento (Pilares, Vigas) | 4 |
| Efeitos locais de 2ª ordem nos elementos | 4 |
| Edição por clique no desenho 3D | — |
| Saídas em DXF, Word e Excel | 4 |
| Análise inelástica e dinâmica | 6 |

## Segunda ordem e estabilidade global

**A matriz de rigidez geométrica** é a peça de onde saem tanto o P-Δ quanto a
flambagem. Ela é a consistente, deduzida das mesmas cúbicas de Hermite da
rigidez elástica, o que dá o efeito de segunda ordem **dentro** da barra e não
apenas o P-Δ dos nós — mas exige malha para convergir: uma barra por pilar
erra a carga crítica de Euler em cerca de 0,8 %, e duas reduzem isso a menos
de 0,1 %.

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
programa de Lajes. E ela **não trabalha como diafragma**: não enrijece o
pavimento no próprio plano, de modo que as prumadas resistem ao vento cada uma
pela sua rigidez, sem a compatibilização horizontal que uma laje real impõe.
Para pórtico de contraventamento regular a diferença é pequena; para planta
muito assimétrica, não é.

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

## Organização

```
main.py                     linha de comando
portico3d/
    arquivo.py              leitura e gravação do modelo em JSON
    mastan.py               leitura dos modelos .mat do MASTAN2
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
        combinacoes.py      superposição dos casos e caso efetivo
        envoltoria.py       extremos com esforços concomitantes
        segunda_ordem.py    rigidez geométrica, P-Δ e flambagem
        estabilidade.py     γz, α, majoração 0,95γz, rigidez secante
    ui/
        janela.py           janela principal e as ações
        tabelas.py          as dez tabelas de entrada
        conversao.py        modelo ↔ linhas das tabelas
        assistente.py       gerador de pórtico regular
        vista3d.py          modelo, deformada, diagramas e modos
        tema.py             paleta clara, a mesma dos outros programas
```

Além das 277 conferências numéricas, o autoteste **monta a janela sem tela** e
faz dois percursos. No primeiro, gera um pórtico pelo assistente, acrescenta e
remove linha em cada uma das dez tabelas, analisa, combina, avalia
estabilidade e flambagem, e desenha as nove vistas. No segundo, monta uma viga
**do zero pelas tabelas**, na ordem em que alguém montaria — material, seção
pelos lados, nós, barra apontando para os nós, apoios, caso, carga — e confere
que o momento no vão dá wL²/8.

O passo de acrescentar linha parece bobo e não é: foi exatamente ali que a
primeira versão quebrava, porque a célula nova nasce vazia e formatar vazio
como número derrubava a janela. Conferência de interface que só verifica se a
janela abre não pega esse tipo de defeito.

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
