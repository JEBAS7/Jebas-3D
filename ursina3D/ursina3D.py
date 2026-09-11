from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from panda3d.core import TransparencyAttrib, Fog
import math
import os
import json
import random
from collections import deque

app = Ursina()
window.fps_counter.enabled = True

# --- 0. TENTA CARREGAR A MÚSICA NATIVAMENTE ---
try:
    musica_fundo = Audio('ex021.mp3', loop=True, autoplay=True, volume=0.5)
except Exception:
    pass

# --- 1. CONFIGURAÇÕES DO MUNDO ---
TAMANHO_CHUNK = 8
ALTURA_MAXIMA = 30
DISTANCIA_VISAO = 2
SEED_MUNDO = 93817
NIVEL_AGUA = 0
NIVEL_OCEANO = 0
LIMITE_OCEANO = 0.43

# --- BIOMAS E ÁGUA ---
TAMANHO_BIOMA = 120
BIOMAS = {
    'planicie': {'topo': 'grama', 'subsolo': 'terra', 'arvores': 0.16, 'altura': 0},
    'floresta': {'topo': 'grama', 'subsolo': 'terra', 'arvores': 0.48, 'altura': 1},
    'deserto': {'topo': 'areia', 'subsolo': 'areia', 'arvores': 0.02, 'altura': -1},
    'montanha': {'topo': 'pedra', 'subsolo': 'pedra', 'arvores': 0.01, 'altura': 8},
}
cache_biomas = {}

VELOCIDADE_NADO = 3.6
VELOCIDADE_VERTICAL_NADO = 3.2

cache_mapa = {}
chunks_entidades = {}
chunks_gerados = set()
chunks_pendentes = set()
chunks_com_agua = set()

jogo_iniciado = False

# [FIX] color.rgba() no Ursina espera valores de 0 a 1, não de 0 a 255.
# A definição antiga -- color.rgba(60, 170, 255, 85) -- estourava todo canal
# acima de 1.0, que é clampado para 1.0: o resultado era um branco sólido e
# opaco, não um azul semi-transparente. É por isso que o plano antigo (que
# funcionava) nunca usou essa constante e preferia color.azure + alpha=0.4.
# Aqui convertemos a mesma intenção de cor (azul de água) para a escala 0-1.
# [AJUSTE] Azul mais saturado/escuro e mais opaco que antes, a pedido do
# usuário -- o azul claro e fraco (60,170,255 com alpha 0.35) fazia a água
# parecer meio "lavada". Agora é um azul mais profundo e mais opaco.
COR_AGUA = color.rgba(5 / 255, 55 / 255, 210 / 255, 0.68)  # Azul mais saturado/profundo

# Tom usado no overlay de tela (efeito_agua) quando a câmera está debaixo
# d'água -- um azul mais escuro/saturado que o da água em si, pra dar a
# sensação de estar olhando "através" da água e não só perto dela.
# [AJUSTE] Azul mais vívido/intenso a pedido do usuário (era um azul-marinho
# meio apagado, 4,35,130). Agora é um azul mais vibrante e saturado.
COR_EFEITO_AGUA = (0 / 255, 60 / 255, 220 / 255)

# [AJUSTE] Margem de segurança (em unidades de mundo) que os OLHOS precisam
# estar abaixo da superfície antes da visão turva ligar. Sem essa margem,
# profundidade_olhos_na_agua() já retorna positivo assim que a câmera cruza
# a própria fronteira do bloco de água (o topo geométrico do bloco), o que
# visualmente ainda parece "acima" da superfície por causa da textura de
# ondas -- daí a sensação de a tela embaçar cedo demais. Com essa margem, só
# embaça quando os olhos já estão visivelmente por baixo d'água de verdade.
#
# [FIX] Usamos DOIS limiares (histerese) em vez de um só: LIGA só quando a
# profundidade passa de MARGEM_LIGAR, mas DESLIGA só quando ela cai abaixo de
# MARGEM_DESLIGAR (mais baixo/negativo que MARGEM_LIGAR). Sem essa folga,
# flutuando parado bem na superfície (onde profundidade_olhos oscila poucos
# centésimos pra cima e pra baixo da linha da água a cada frame) a visão
# turva fica ligando e desligando entre um frame e o outro -- exatamente o
# "quicar" que fazia duas capturas quase idênticas mostrarem uma com e outra
# sem o efeito, mesmo com a câmera praticamente parada no mesmo lugar.
MARGEM_LIGAR_TURVA = 0.15
MARGEM_DESLIGAR_TURVA = -0.05

TEXTURAS_BLOCOS = {
    'grama': 'texturas/grama.png' if os.path.exists('texturas/grama.png') else 'white_cube',
    'terra': 'texturas/terra.png' if os.path.exists('texturas/terra.png') else 'white_cube',
    'pedra': 'texturas/pedra.png' if os.path.exists('texturas/pedra.png') else 'white_cube',
    'areia': 'texturas/areia.png' if os.path.exists('texturas/areia.png') else 'white_cube',
    'bedrock': 'texturas/bedrock.png' if os.path.exists('texturas/bedrock.png') else 'white_cube',
    'agua': 'texturas/agua.png' if os.path.exists('texturas/agua.png') else 'white_cube',
    'bronze': 'texturas/bronze.png' if os.path.exists('texturas/bronze.png') else 'white_cube',
    'prata': 'texturas/prata.png' if os.path.exists('texturas/prata.png') else 'white_cube',
    'ouro': 'texturas/ouro.png' if os.path.exists('texturas/ouro.png') else 'white_cube',
    'diamante': 'texturas/diamante.png' if os.path.exists('texturas/diamante.png') else 'white_cube',
    'madeira': 'texturas/madeira.png' if os.path.exists('texturas/madeira.png') else 'white_cube',
    'folhas': 'texturas/folhas.png' if os.path.exists('texturas/folhas.png') else 'white_cube'
}

# O plano gigante de água foi removido: agora cada célula de água é um bloco
# de verdade dentro de cache_mapa (a mesma lógica de lagos/oceanos que já
# existia na geração de terreno), desenhado como uma malha semi-transparente
# só nos chunks carregados -- ver atualizar_malha_chunk mais abaixo.

# Trava de segurança para o preenchimento de buracos com água (ver
# encher_buraco_com_agua): sem isso, despejar água numa área aberta em vez
# de um buraco fechado faria o flood-fill tentar inundar o mundo inteiro.
LIMITE_INUNDACAO = 4000

# [FIX] O LIMITE_INUNDACAO sozinho não bastava: se existisse qualquer
# caminho de células vazias (céu acima de um vale, uma depressão do
# terreno) na mesma altura do balde ou mais abaixo, o flood-fill viajava
# por ele -- mesmo que fosse bem longe do lago/poça onde a água foi
# despejada. O resultado era água de verdade aparecendo flutuando no ar
# sobre outras partes do mapa (às vezes bem longe, perto do oceano até),
# o que ligava a visão turva em lugares onde não tinha água nenhuma
# visível. Este raio limita o quão longe (em blocos, no plano X/Z) a
# inundação pode viajar a partir do ponto onde a água foi colocada --
# suficiente pra encher uma lagoa, pequeno demais pra vazar pelo mapa.
RAIO_MAXIMO_INUNDACAO = 40

ARQUIVO_SAVE = 'mundo_save.json'
ORDEM_BLOCOS = ['grama', 'terra', 'pedra', 'areia', 'bronze', 'prata', 'ouro', 'diamante', 'madeira', 'folhas', 'agua']
bloco_selecionado = 'grama'
indice_selecionado = 0

# Física manual
jogador = FirstPersonController(enabled=False)
jogador.gravity = 0
jogador.speed = 0
jogador.jump_height = 0

pulos_extras = 2
velocidade_vertical = 0.0
# [FIX] Estado persistente do efeito de água turva entre frames -- necessário
# para a histerese (ver MARGEM_LIGAR_TURVA / MARGEM_DESLIGAR_TURVA acima):
# sem lembrar se já estava ligado no frame anterior, não dá pra aplicar um
# limiar diferente pra ligar e pra desligar.
agua_efeito_ativo = False

# [FIX] Distância real entre os PÉS (jogador.y) e os OLHOS (camera.world_y),
# medida e guardada enquanto o jogador está andando em TERRA FIRME (uma
# situação estável, sem nenhuma correção de altura acontecendo). Antes o
# teto de natação lia "camera.world_y - jogador.y" AO VIVO, no mesmo frame em
# que jogador.y acabava de ser alterado -- se a câmera do Panda3D ainda não
# tivesse propagado essa mudança bem na hora da leitura (um atraso de um
# frame), a conta saía errada, e como a correção só empurra o jogador PRA
# BAIXO quando dá errado (nunca pra cima), qualquer erro pequeno se acumulava
# frame após frame até o jogador atravessar o fundo do oceano -- exatamente o
# "cai para debaixo do fundo do oceano" relatado. Guardando esse número
# enquanto o jogador está em terra (fora do próprio laço que o usa pra
# corrigir a natação), a natação usa sempre um valor estável e correto, sem
# realimentação.
altura_olhos_referencia = jogador.camera_pivot.y

# Em vez de um quad colorido puro, use um quad com textura radial
efeito_agua = Entity(parent=camera.ui, model='quad', scale=2,
                     color=color.rgba(*COR_EFEITO_AGUA, 0.35),
                     z=0.5, enabled=False)

# --- CHUVA ---
# Já existe áudio de chuva de fundo -- isso aqui é só o visual: um monte de
# gotinhas caindo ao redor do jogador.
#
# [FIX] A primeira versão desenhava cada gota como uma LINHA (mode='line').
# Só que no Ursina esse modo conecta TODOS os vértices numa única linha
# contínua (um "line strip"), não em segmentos separados -- o resultado
# era uma teia de traços ligando uma gota na outra pela tela inteira, não
# chuva. Agora cada gota é desenhada como dois retângulos finos cruzados
# em "X" (mesma técnica de FACES_CUBO usada pros blocos do mundo: 4
# vértices + 2 triângulos por retângulo) -- isolados uns dos outros, e
# visíveis de qualquer ângulo horizontal por causa do cruzamento.
#
# Em vez de criar uma Entity por gota (o Ursina teria que desenhar centenas
# de objetos separados todo frame, pesado), tudo vira um ÚNICO Mesh -- um
# desenho só, resolvendo tudo de uma vez.
#
# O container fica com parent=jogador (não parent=camera!): assim ele anda
# junto com o jogador automaticamente, e como jogador só gira no eixo Y
# (olhar pra cima/baixo é só a câmera dentro dele), as gotas continuam
# sempre verticais na tela, nunca inclinadas. Se fosse parent=camera, olhar
# pra cima ou pra baixo inclinaria a chuva inteira junto com a câmera.
# [OTIMIZAÇÃO FPS] Reduzido de 220 -- cada gota vira 8 vértices no mesh e,
# mais importante, cada gota que bate no chão dispara um respingo. Com 220
# gotas o jogo criava e destruía uma Entity de respingo ~150-200 vezes por
# segundo, e criar/destruir Entity é uma das operações mais caras do
# Panda3D/Ursina -- essa era a maior causa da queda de FPS. 150 gotas
# mantém a chuva visualmente cheia com bem menos pressão de CPU.
NUM_GOTAS_CHUVA = 150
RAIO_CHUVA = 18            # gotas aparecem espalhadas nesse raio (X/Z) ao redor do jogador
ALTURA_CHUVA = 16          # começam a essa altura acima do jogador, e reaparecem lá quando passam do chão
VELOCIDADE_QUEDA_CHUVA = 26
COMPRIMENTO_GOTA = 0.6
LARGURA_GOTA = 0.035

gotas_chuva = [
    Vec3(random.uniform(-RAIO_CHUVA, RAIO_CHUVA),
         random.uniform(-ALTURA_CHUVA, ALTURA_CHUVA),
         random.uniform(-RAIO_CHUVA, RAIO_CHUVA))
    for _ in range(NUM_GOTAS_CHUVA)
]

# [NOVO] Altura (em coordenada MUNDIAL, não local) onde cada gota deve
# "bater" -- o topo do chão sólido, ou o topo da água, o que for mais alto
# ali. Começa como None (ainda não calculado) porque as funções que
# calculam isso (altura_do_chao / nivel_superficie_agua) só são definidas
# mais abaixo no arquivo -- o valor real de cada uma é preenchido na
# primeira vez que o update() processa aquela gota (ver calcular_estado_gota).
impactos_chuva = [None] * NUM_GOTAS_CHUVA

# [FIX] Se cada gota está bloqueada ou não (True = tem teto sólido acima
# dessa coluna especificamente, então a gota não deve aparecer). Antes a
# chuva inteira ligava/desligava com base numa única checagem na coluna do
# JOGADOR -- perto da boca de uma caverna isso é errado: parado bem na
# entrada olhando pra fora (céu aberto lá fora), a coluna debaixo dos SEUS
# pés ainda tinha teto de pedra, então a chuva inteira ficava desligada,
# inclusive as gotas que deveriam estar caindo lá fora, visíveis na tela.
# Agora cada gota checa a PRÓPRIA coluna (calculada junto com o impacto, em
# calcular_estado_gota), então gotas em área aberta aparecem e gotas sobre
# uma coluna com teto ficam invisíveis, ao mesmo tempo.
bloqueios_chuva = [False] * NUM_GOTAS_CHUVA

# [OTIMIZAÇÃO FPS] Contador de frames pra chuva -- ver uso lá no update(),
# onde ele decide se a malha da chuva é reenviada pra GPU neste frame.
_frame_chuva = 0


def calcular_estado_gota(offset_x, offset_z):
    """Pra uma coluna (X/Z relativo ao jogador), retorna (altura_impacto,
    bloqueada).

    altura_impacto é onde a gota deve parar de cair -- o relevo real dessa
    coluna (topo_solido_coluna, que já ignora água), ou o topo da água, o
    que for mais alto ali.

    bloqueada é True quando o relevo real dessa coluna está bem ACIMA de
    onde a chuva nasce perto do jogador (jogador.y + ALTURA_CHUVA) -- sinal
    de que existe uma camada de pedra sólida de verdade entre a região onde
    a chuva cai perto do jogador e o céu ali (uma caverna/teto), não só uma
    ladeira ou diferença comum de relevo (que fica dentro desse alcance).
    Sem esse limite, uma gota tentaria cair até um "chão" que já está ACIMA
    de onde ela nasce e nunca chegaria lá (nunca reapareceria).
    """
    wx = jogador.x + offset_x
    wz = jogador.z + offset_z
    topo = topo_solido_coluna(wx, wz)
    agua = nivel_superficie_agua(wx, wz, jogador.y)
    impacto = max(topo + 1, agua)
    bloqueada = (topo - jogador.y) > ALTURA_CHUVA
    return impacto, bloqueada


# [OTIMIZAÇÃO FPS] Pool de respingos: antes, cada gota que batia no chão
# chamava Entity(...) e depois destroy(...) -- com ~150-200 impactos por
# segundo isso significava criar e destruir centenas de objetos do Panda3D
# a cada segundo (cada Entity() novo passa por criação de NodePath,
# atribuição de textura/modelo, etc. -- caro mesmo sendo pequeno). Em vez
# disso, criamos um número fixo de Entities de respingo UMA VEZ no início e
# ficamos girando entre elas (round-robin), só reposicionando e reanimando
# a que estiver "livre" (a mais antiga). Zero criação/destruição em tempo
# de jogo -- é praticamente de graça pra CPU.
NUM_RESPINGOS_POOL = 40
_pool_respingos = [
    Entity(parent=jogador, model='quad', rotation_x=90, scale=0.06,
           unlit=True, double_sided=True, enabled=False,
           color=color.rgba(225 / 255, 240 / 255, 255 / 255, 0))
    for _ in range(NUM_RESPINGOS_POOL)
]
_indice_pool_respingos = 0


def criar_respingo_chuva(offset_x, altura_local, offset_z):
    """Um respingo rápido (cresce e some) no ponto de impacto de uma gota.
    Reaproveita uma Entity do pool em vez de criar/destruir uma nova.
    """
    global _indice_pool_respingos
    respingo = _pool_respingos[_indice_pool_respingos]
    _indice_pool_respingos = (_indice_pool_respingos + 1) % NUM_RESPINGOS_POOL

    respingo.position = Vec3(offset_x, altura_local, offset_z)
    respingo.scale = 0.06
    respingo.color = color.rgba(225 / 255, 240 / 255, 255 / 255, 0.65)
    respingo.enabled = True
    respingo.animate_scale(0.3, duration=0.15, curve=curve.out_expo)
    respingo.animate_color(color.rgba(225 / 255, 240 / 255, 255 / 255, 0), duration=0.25)
    invoke(setattr, respingo, 'enabled', False, delay=0.3)


def gerar_vertices_chuva():
    """Monta os vértices de todas as gotas a partir de gotas_chuva (a
    posição do TOPO de cada uma). A topologia (quantos vértices, quais
    formam triângulo com quem) nunca muda -- só as posições -- por isso
    os triângulos são gerados uma vez só em gerar_triangulos_chuva().

    [FIX] Gotas cuja coluna está marcada em bloqueios_chuva (teto sólido
    acima, ex: dentro de uma caverna) viram um retângulo DEGENERADO -- os 8
    vértices colapsados no mesmo ponto, ou seja, área zero, invisível --
    em vez de serem puladas. Isso mantém a contagem de vértices/triângulos
    sempre igual ao número de gotas, que é o que gerar_triangulos_chuva()
    (topologia fixa, gerada uma vez só) espera.
    """
    vertices = []
    for i, g in enumerate(gotas_chuva):
        if bloqueios_chuva[i]:
            vertices.extend([g] * 8)
            continue
        base = g + Vec3(0, -COMPRIMENTO_GOTA, 0)
        # retângulo alinhado ao eixo X
        vertices.extend([
            g + Vec3(-LARGURA_GOTA, 0, 0),
            g + Vec3(LARGURA_GOTA, 0, 0),
            base + Vec3(LARGURA_GOTA, 0, 0),
            base + Vec3(-LARGURA_GOTA, 0, 0),
        ])
        # retângulo alinhado ao eixo Z, perpendicular ao de cima -- forma
        # o "X" que fica visível não importa de que lado você olha.
        vertices.extend([
            g + Vec3(0, 0, -LARGURA_GOTA),
            g + Vec3(0, 0, LARGURA_GOTA),
            base + Vec3(0, 0, LARGURA_GOTA),
            base + Vec3(0, 0, -LARGURA_GOTA),
        ])
    return vertices


def gerar_triangulos_chuva():
    triangulos = []
    for i in range(NUM_GOTAS_CHUVA):
        b = i * 8
        triangulos.extend([
            b, b + 1, b + 2, b, b + 2, b + 3,          # retângulo X
            b + 4, b + 5, b + 6, b + 4, b + 6, b + 7,  # retângulo Z
        ])
    return triangulos


_triangulos_chuva = gerar_triangulos_chuva()  # topologia fixa -- gerada uma vez só

chuva = Entity(parent=jogador,
               model=Mesh(vertices=gerar_vertices_chuva(), triangles=_triangulos_chuva, mode='triangle'),
               color=color.rgba(190 / 255, 210 / 255, 255 / 255, 0.55),
               unlit=True, double_sided=True, y=2)

# --- CRIAÇÃO DA HOTBAR VISUAL ---
hotbar_conteiner = Entity(parent=camera.ui, enabled=False)
slots_hotbar = []
mini_blocos_icones = []
TAMANHO_SLOT = 0.07
ESPACAMENTO_SLOT = 0.08
LARGURA_TOTAL = (len(ORDEM_BLOCOS) - 1) * ESPACAMENTO_SLOT
START_X = -LARGURA_TOTAL / 2

for i, nome_material in enumerate(ORDEM_BLOCOS):
    x_pos = START_X + (i * ESPACAMENTO_SLOT)
    slot = Entity(
        parent=hotbar_conteiner,
        model='quad',
        texture='white_cube',
        color=color.Color(0, 0, 0.1, 0.7),
        scale=(TAMANHO_SLOT, TAMANHO_SLOT),
        position=(x_pos, -0.42, 0)
    )
    slots_hotbar.append(slot)

    mini_bloco = Entity(
        parent=slot,
        model='cube',
        texture=TEXTURAS_BLOCOS[nome_material],
        scale=(0.5, 0.5, 0.5),
        position=(0, 0, -1),
        rotation=(20, 45, 0)
    )
    mini_blocos_icones.append(mini_bloco)

hotbar_seletor = Entity(
    parent=hotbar_conteiner,
    model='quad',
    color=color.clear,
    scale=(TAMANHO_SLOT + 0.01, TAMANHO_SLOT + 0.01),
    position=(slots_hotbar[0].x, -0.42, -0.1),
    border_color=color.white,
    border_width=0.07
)

mao_jogador = Entity(
    parent=camera,
    model='cube',
    texture=TEXTURAS_BLOCOS[bloco_selecionado],
    position=(0.6, -0.5, 1.1),
    rotation=(15, -20, 5),
    scale=(0.2, 0.2, 0.6),
    enabled=False
)


def atualizar_selecao_hotbar(novo_indice):
    global indice_selecionado, bloco_selecionado
    indice_selecionado = novo_indice
    bloco_selecionado = ORDEM_BLOCOS[indice_selecionado]
    hotbar_seletor.x = slots_hotbar[indice_selecionado].x
    mao_jogador.texture = TEXTURAS_BLOCOS[bloco_selecionado]


# --- 2. FUNÇÕES DE FLUXO DO JOGO ---
def resetar_entidades_mundo():
    for cx, cz in list(chunks_entidades.keys()):
        for sub_malha in chunks_entidades[(cx, cz)]:
            destroy(sub_malha)
    chunks_entidades.clear()
    chunks_pendentes.clear()
    chunks_com_agua.clear()


def garantir_dados_da_coluna(x, z):
    """Garante que os dados de terreno da coluna (x, z) já existem em cache_mapa.

    A geração de dados normalmente só acontece dentro de atualizar_malha_chunk,
    que é enfileirada e processada aos poucos (1 chunk por frame, veja
    processar_fila_chunks). Se o jogador anda rápido o bastante, ele pode
    chegar a uma coluna cujo chunk ainda não tem dados: cache_mapa.get()
    retorna None ali (como se fosse ar vazio), e a colisão deixa passar --
    o jogador atravessa uma parede que ainda nem existe nos dados do jogo,
    e some segundos depois, quando o chunk finalmente processa e a pedra
    "aparece" ao redor dele. Aqui forçamos a geração dos DADOS (rápida,
    sem construir a malha visual) na hora, então a colisão nunca compara
    contra uma coluna vazia por falta de ter sido gerada ainda.
    """
    cx, cz = int(x) // TAMANHO_CHUNK, int(z) // TAMANHO_CHUNK
    if (cx, cz) not in chunks_gerados:
        gerar_dados_relevo(cx, cz)


def altura_do_chao(x, z, y_referencia=None):
    """Encontra o topo sólido da coluna (ignora água/folhas/madeira).

    Se y_referencia for informado, a busca começa a partir dessa altura
    (arredondada pra baixo) em vez do topo absoluto do mapa. Isso é essencial
    para a colisão em tempo real: sem isso, dentro de uma caverna com teto,
    a função encontraria o teto (bloco sólido mais alto da coluna) e não o
    piso onde o jogador realmente está pisando.
    """
    garantir_dados_da_coluna(x, z)

    if y_referencia is None:
        inicio = ALTURA_MAXIMA - 1
    else:
        inicio = min(ALTURA_MAXIMA - 1, math.floor(y_referencia))

    for y in range(inicio, -ALTURA_MAXIMA - 1, -1):
        tipo = cache_mapa.get((int(x), int(y), int(z)))
        if tipo is not None and tipo != 'agua' and tipo != 'folhas' and tipo != 'madeira':
            return y
    return 0


def topo_solido_coluna(x, z):
    """Altura do bloco sólido mais alto dessa coluna (ignorando água,
    folhas e madeira), procurando do TOPO do mundo pra baixo -- ou seja, o
    relevo real do terreno ali, sem depender de onde o jogador está.

    [FIX] Substitui ceu_visivel(), que escaneava a partir da altura do
    JOGADOR em vez da coluna sendo checada. Isso quebrava perto de uma
    caverna que dá numa ladeira/superfície de altura bem diferente: o
    jogador dentro da caverna tem um Y baixo, e escanear pra cima a partir
    dele numa coluna de FORA (cujo chão de verdade é bem mais alto) batia
    na terra sólida NORMAL daquela coluna -- terra comum sendo confundida
    com um "teto de pedra", quando era só o interior do relevo ali, sem
    caverna nenhuma. Escaneando sempre do topo absoluto do mapa pra baixo,
    achamos o relevo real de qualquer coluna, não importa a altura do
    jogador.

    [FIX] Ignoramos 'folhas' e 'madeira' igual altura_do_chao já fazia --
    sem isso, uma gota caindo bem em cima da copa de uma árvore achava que
    aquilo era o chão e fazia o respingo lá, flutuando no ar bem acima da
    grama de verdade (o respingo "no ar" relatado pelo usuário).
    """
    garantir_dados_da_coluna(x, z)
    for y in range(ALTURA_MAXIMA - 1, -ALTURA_MAXIMA - 1, -1):
        tipo = cache_mapa.get((int(x), int(y), int(z)))
        if tipo is not None and tipo != 'agua' and tipo != 'folhas' and tipo != 'madeira':
            return y
    return -ALTURA_MAXIMA


def posicionar_jogador_na_superficie(x, z):
    global velocidade_vertical
    cx, cz = x // TAMANHO_CHUNK, z // TAMANHO_CHUNK
    atualizar_malha_chunk(cx, cz)

    # Antes, isso calculava a altura do "topo sólido" da coluna e colocava o
    # jogador 3 acima -- mas em terreno de montanha isso pode achar uma
    # saliência/overhang, uma caverna com teto baixo perto da superfície, ou
    # até (perto do mar) uma coluna de oceano bem profunda, colocando o
    # jogador embutido em pedra ou muito abaixo do nível real do chão. Em
    # vez de confiar num cálculo isolado, soltamos o jogador de bem acima
    # de qualquer altura possível do mundo e deixamos a MESMA física de
    # queda/colisão usada durante o jogo normal (a função update()) achar
    # o chão de verdade -- é a lógica que já testamos e sabemos que funciona.
    velocidade_vertical = 0
    jogador.position = (x, ALTURA_MAXIMA + 5, z)


def mostrar_carregamento_novo():
    menu_inicial.enabled = False
    tela_carregamento.enabled = True
    invoke(iniciar_novo_mundo, delay=0.05)


def iniciar_novo_mundo():
    global jogo_iniciado, velocidade_vertical
    jogo_iniciado = True
    velocidade_vertical = 0
    cache_mapa.clear()
    cache_biomas.clear()
    chunks_gerados.clear()
    chunks_com_agua.clear()
    resetar_entidades_mundo()
    jogador.enabled = True
    jogador.gravity = 0
    posicionar_jogador_na_superficie(4, 4)
    mouse.locked = True
    mouse.visible = False
    gerenciar_chunks_visiveis()
    tela_carregamento.enabled = False
    hotbar_conteiner.enabled = True
    mao_jogador.enabled = True


def mostrar_carregamento_salvo():
    if not os.path.exists(ARQUIVO_SAVE):
        return
    menu_inicial.enabled = False
    tela_carregamento.enabled = True
    invoke(iniciar_mundo_carregado, delay=0.05)


def carregar_dados_do_save():
    """Lê o arquivo de save e devolve (blocos, chunks_ja_gerados, posicao_salva).

    Aceita tanto o formato novo ({'blocos': ..., 'chunks_gerados': ...,
    'jogador_pos': ...}) quanto o formato antigo (um dict plano "x,y,z" ->
    tipo, sem chunks nem posição), pra não quebrar saves feitos antes dessa
    correção -- nesse caso não há como saber quais chunks já foram
    visitados nem onde o jogador estava, então o mundo é regenerado do
    zero e o jogador nasce no ponto fixo (não resolve saves antigos, mas
    não trava o jogo neles).
    """
    with open(ARQUIVO_SAVE, 'r') as f:
        dados_carregados = json.load(f)

    if 'blocos' in dados_carregados:
        blocos = dados_carregados['blocos']
        chunks_salvos = dados_carregados.get('chunks_gerados', [])
        posicao_salva = dados_carregados.get('jogador_pos')
    else:
        blocos = dados_carregados
        chunks_salvos = []
        posicao_salva = None

    return blocos, chunks_salvos, posicao_salva


def aplicar_dados_carregados(blocos, chunks_salvos):
    for chave_string, tipo in blocos.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    for cx, cz in chunks_salvos:
        chunks_gerados.add((int(cx), int(cz)))


def restaurar_ou_reposicionar_jogador(posicao_salva):
    """Restaura o jogador perto de onde ele salvou, com um teto de segurança.

    Como o terreno das áreas já visitadas fica idêntico ao que era antes de
    salvar (graças a chunks_gerados persistido), a posição salva devia
    sempre ser um lugar seguro. Mas o save pode ter capturado a posição num
    frame ruim (por exemplo, no meio de um degrau ou logo após pisar em
    algo), então em vez de aceitar cegamente o ponto exato ou desistir dele
    de vez (mandando pro spawn fixo, longe de onde o jogador estava),
    subimos célula por célula a partir da posição salva até achar espaço
    livre de verdade -- é basicamente automatizar o "pular pra sair" que
    você teria que fazer na mão.
    """
    global velocidade_vertical

    if posicao_salva and len(posicao_salva) == 3:
        x, y, z = posicao_salva
        garantir_dados_da_coluna(x, z)

        y_base = math.floor(y)
        for tentativa_y in range(y_base, y_base + 8):
            if coluna_livre_para_jogador(Vec3(x, tentativa_y, z)):
                velocidade_vertical = 0
                jogador.position = (x, tentativa_y, z)
                return

        # Nada livre por perto do ponto salvo: solta de cima nesse mesmo
        # x, z (sem abandonar o lugar) e deixa a física de queda normal
        # achar o chão de verdade.
        velocidade_vertical = 0
        jogador.position = (x, ALTURA_MAXIMA + 5, z)
        return

    posicionar_jogador_na_superficie(4, 4)


def iniciar_mundo_carregado():
    global cache_mapa, jogo_iniciado, velocidade_vertical
    jogo_iniciado = True
    velocidade_vertical = 0
    jogador.enabled = True
    jogador.gravity = 0
    mouse.locked = True
    mouse.visible = False

    blocos, chunks_salvos, posicao_salva = carregar_dados_do_save()

    cache_mapa.clear()
    chunks_gerados.clear()
    chunks_com_agua.clear()
    resetar_entidades_mundo()
    aplicar_dados_carregados(blocos, chunks_salvos)

    restaurar_ou_reposicionar_jogador(posicao_salva)
    gerenciar_chunks_visiveis()
    tela_carregamento.enabled = False
    hotbar_conteiner.enabled = True
    mao_jogador.enabled = True


def salvar_mundo():
    dados_para_salvar = {
        'blocos': {},
        'jogador_pos': [jogador.x, jogador.y, jogador.z],
        # Sem isso, o carregamento marca tudo como "nunca gerado" e o jogo
        # regenera cada chunk do zero conforme você explora de novo. Blocos
        # que você colocou têm um valor salvo, então voltam certinho -- mas
        # um buraco (caverna natural ou túnel cavado por você) nunca teve
        # um registro de "isso aqui é vazio", só ausência de dado. A
        # regeneração então enche esse vazio de novo com pedra/minério,
        # exatamente onde você pode estar parado. Salvando quais chunks já
        # foram gerados, o carregamento nunca tenta regerar o que você já
        # visitou, e os buracos continuam exatamente como você deixou.
        'chunks_gerados': [[cx, cz] for cx, cz in chunks_gerados],
    }
    for pos, tipo in cache_mapa.items():
        if tipo is not None:
            chave_string = f"{pos[0]},{pos[1]},{pos[2]}"
            dados_para_salvar['blocos'][chave_string] = tipo
    with open(ARQUIVO_SAVE, 'w') as f:
        json.dump(dados_para_salvar, f)
    # Fechar o menu na hora (em vez de adiar pro próximo frame, como o
    # carregamento já faz) deixava uma brecha: o clique em "SALVAR MUNDO" é
    # um evento bruto de mouse que o jogo também recebe no input() global.
    # Se o menu já tivesse fechado antes desse evento terminar de ser
    # processado, a checagem "menu_pausa.enabled" já via False, e o mesmo
    # clique também minerava o bloco mirado pela câmera -- cavando o chão
    # debaixo do jogador bem na hora de salvar. Adiando o fechamento pro
    # próximo frame, o menu continua "aberto" (bloqueando mineração) durante
    # todo o processamento desse clique.
    invoke(alternar_menu_pausa, delay=0.05)


def mostrar_carregamento_pausa():
    if not os.path.exists(ARQUIVO_SAVE):
        return
    menu_pausa.enabled = False
    tela_carregamento.enabled = True
    hotbar_conteiner.enabled = False
    mao_jogador.enabled = False
    invoke(carregar_mundo_pausa, delay=0.05)


def carregar_mundo_pausa():
    global cache_mapa
    blocos, chunks_salvos, posicao_salva = carregar_dados_do_save()

    cache_mapa.clear()
    chunks_gerados.clear()
    chunks_com_agua.clear()
    resetar_entidades_mundo()
    aplicar_dados_carregados(blocos, chunks_salvos)

    restaurar_ou_reposicionar_jogador(posicao_salva)
    gerenciar_chunks_visiveis()
    tela_carregamento.enabled = False
    hotbar_conteiner.enabled = True
    mao_jogador.enabled = True
    jogador.cursor.enabled = True
    mouse.locked = True
    mouse.visible = False


def voltar_ao_menu_inicial():
    global jogo_iniciado, velocidade_vertical
    jogo_iniciado = False
    velocidade_vertical = 0
    menu_pausa.enabled = False
    hotbar_conteiner.enabled = False
    mao_jogador.enabled = False
    jogador.enabled = False
    jogador.gravity = 0

    resetar_entidades_mundo()
    cache_mapa.clear()
    cache_biomas.clear()

    menu_inicial.enabled = True
    mouse.locked = False
    mouse.visible = True


# --- 3. GERADOR PROCEDURAL DE ÁRVORES ---
def gerar_arvore_no_cache(base_x, base_y, base_z):
    altura_tronco = random.randint(3, 5)
    for i in range(1, altura_tronco + 1):
        pos_tronco = (base_x, base_y + i, base_z)
        if pos_tronco not in cache_mapa:
            cache_mapa[pos_tronco] = 'madeira'

    topo_y = base_y + altura_tronco
    for fx in range(-2, 3):
        for fz in range(-2, 3):
            for fy in range(-1, 2):
                if abs(fx) == 2 and abs(fz) == 2 and fy != 0:
                    continue
                pos_folha = (base_x + fx, topo_y + fy + 1, base_z + fz)
                if pos_folha not in cache_mapa:
                    cache_mapa[pos_folha] = 'folhas'


# --- 4. GERAÇÃO MATEMÁTICA DO TERRENO ---
def valor_aleatorio(x, z, seed=0):
    valor = math.sin(x * 127.1 + z * 311.7 + (SEED_MUNDO + seed) * 74.7) * 43758.5453
    return valor - math.floor(valor)


def ruido(x, z, escala, seed=0):
    x /= escala
    z /= escala
    x0, z0 = math.floor(x), math.floor(z)
    x1, z1 = x0 + 1, z0 + 1
    tx, tz = x - x0, z - z0
    tx = tx * tx * (3 - 2 * tx)
    tz = tz * tz * (3 - 2 * tz)
    baixo = lerp(valor_aleatorio(x0, z0, seed), valor_aleatorio(x1, z0, seed), tx)
    alto = lerp(valor_aleatorio(x0, z1, seed), valor_aleatorio(x1, z1, seed), tx)
    return lerp(baixo, alto, tz)

def valor_aleatorio_3d(x, y, z, seed=0):
    valor = math.sin(x * 127.1 + y * 311.7 + z * 74.7 + (SEED_MUNDO + seed) * 57.3) * 43758.5453
    return valor - math.floor(valor)


def ruido_3d(x, y, z, escala, seed=0):
    x /= escala; y /= escala; z /= escala
    x0, y0, z0 = math.floor(x), math.floor(y), math.floor(z)
    x1, y1, z1 = x0 + 1, y0 + 1, z0 + 1
    tx, ty, tz = x - x0, y - y0, z - z0
    tx = tx * tx * (3 - 2 * tx)
    ty = ty * ty * (3 - 2 * ty)
    tz = tz * tz * (3 - 2 * tz)

    def v(xx, yy, zz):
        return valor_aleatorio_3d(xx, yy, zz, seed)

    x00 = lerp(v(x0, y0, z0), v(x1, y0, z0), tx)
    x10 = lerp(v(x0, y1, z0), v(x1, y1, z0), tx)
    x01 = lerp(v(x0, y0, z1), v(x1, y0, z1), tx)
    x11 = lerp(v(x0, y1, z1), v(x1, y1, z1), tx)
    y0_ = lerp(x00, x10, ty)
    y1_ = lerp(x01, x11, ty)
    return lerp(y0_, y1_, tz)

def ruido_suave(x, z, escala, seed=0):
    return (
            ruido(x, z, escala, seed) * 0.50
            + ruido(x + 31, z + 17, escala * 2, seed + 1) * 0.30
            + ruido(x - 47, z + 12, escala * 4, seed + 2) * 0.20
    )


def obter_bioma(x, z):
    chave = (x // TAMANHO_BIOMA, z // TAMANHO_BIOMA)
    if chave in cache_biomas:
        return cache_biomas[chave]
    bx, bz = chave
    temperatura = ruido_suave(bx * 17, bz * 17, 5, 70)
    umidade = ruido_suave(bx * 23 + 100, bz * 23 - 50, 5, 80)
    altitude = ruido_suave(bx * 11 - 30, bz * 11 + 20, 5, 90)

    if altitude > 0.68:
        bioma = 'montanha'
    elif temperatura > 0.62 and umidade < 0.48:
        bioma = 'deserto'
    elif umidade > 0.58:
        bioma = 'floresta'
    else:
        bioma = 'planicie'
    cache_biomas[chave] = bioma
    return bioma


def gerar_dados_relevo(cx, cz):
    if (cx, cz) in chunks_gerados:
        return

    possiveis_locais_arvores = []
    fundo_do_mundo = -16

    for x in range(cx * TAMANHO_CHUNK, (cx + 1) * TAMANHO_CHUNK):
        for z in range(cz * TAMANHO_CHUNK, (cz + 1) * TAMANHO_CHUNK):
            bioma = obter_bioma(x, z)
            cfg = BIOMAS[bioma]

            relevo_grande = ruido_suave(x, z, 42, 10) * 18
            relevo_detalhe = ruido_suave(x, z, 11, 20) * 5
            altura_calculada = int(relevo_grande + relevo_detalhe - 8 + cfg['altura'])

            mascara_oceano = ruido_suave(x, z, 90, 55)
            mascara_lago = ruido_suave(x, z, 35, 30)
            eh_oceano = mascara_oceano < LIMITE_OCEANO
            eh_lago = mascara_lago > 0.69 and not eh_oceano
            eh_agua = eh_oceano or eh_lago

            if eh_oceano:
                profundidade = int((LIMITE_OCEANO - mascara_oceano) * 28) + 3
                altura_calculada = min(altura_calculada, NIVEL_OCEANO - profundidade)
            elif eh_lago:
                profundidade = int((mascara_lago - 0.69) * 22) + 2
                altura_calculada = min(altura_calculada, NIVEL_AGUA - profundidade)

            altura_fundo_agua = altura_calculada
            if eh_agua:
                altura_fundo_agua = NIVEL_AGUA - 3

            for y in range(fundo_do_mundo, altura_calculada + 1):
                pos = (x, y, z)
                if pos in cache_mapa:
                    continue

                # --- CAVERNAS: só no subsolo, longe da superfície, sem mexer em água
                # e nunca abaixo do nível do mar ---
                # A checagem "not eh_agua" só olha a coluna ATUAL (x, z). Ela não
                # impede nada: uma caverna esculpida numa coluna de montanha pode
                # ir fundo o bastante (y <= NIVEL_AGUA) pra encostar numa coluna de
                # oceano vizinha, que é água até esse mesmo nível. Sem pedra entre
                # as duas colunas, a caverna simplesmente abre um buraco direto pro
                # oceano. Por isso também exigimos y > NIVEL_AGUA aqui: caverna
                # nunca existe na faixa de profundidade onde mares/lagos têm água,
                # então nunca pode encostar neles, não importa a coluna vizinha.
                profundidade_superficie = altura_calculada - y
                if (not eh_agua and profundidade_superficie > 4
                        and y > fundo_do_mundo + 2 and y > NIVEL_AGUA):
                    densidade_caverna = ruido_3d(x, y, z, 13, 200)
                    if densidade_caverna > 0.74:
                        continue  # bloco vazio = caverna

                if y == altura_calculada:
                    if eh_agua or altura_calculada <= NIVEL_AGUA + 1:
                        cache_mapa[pos] = 'areia'
                    elif bioma == 'montanha' and altura_calculada > 13:
                        cache_mapa[pos] = 'pedra'
                    else:
                        cache_mapa[pos] = cfg['topo']
                        if cfg['arvores'] > 0:
                            possiveis_locais_arvores.append((x, y, z))
                elif eh_agua and y > altura_fundo_agua and y <= NIVEL_AGUA:
                    cache_mapa[pos] = 'areia'
                elif y >= altura_calculada - 3:
                    cache_mapa[pos] = cfg['subsolo']
                elif y >= altura_calculada - 15:
                    sorteio = random.random()
                    if sorteio < 0.03:
                        cache_mapa[pos] = 'ouro'
                    elif sorteio < 0.05:
                        cache_mapa[pos] = 'diamante'
                    elif sorteio < 0.10:
                        cache_mapa[pos] = 'prata'
                    elif sorteio < 0.25:
                        cache_mapa[pos] = 'bronze'
                    else:
                        cache_mapa[pos] = 'pedra'
                elif y <= fundo_do_mundo + 2:
                    cache_mapa[pos] = 'bedrock'
                else:
                    cache_mapa[pos] = 'pedra'

            if eh_agua:
                chunks_com_agua.add((cx, cz))
                for y in range(altura_calculada + 1, NIVEL_AGUA + 1):
                    pos_agua = (x, y, z)
                    if pos_agua not in cache_mapa:
                        cache_mapa[pos_agua] = 'agua'

    rng = random.Random(f"{cx}_{cz}_{SEED_MUNDO}")
    bioma_centro = obter_bioma(cx * TAMANHO_CHUNK + TAMANHO_CHUNK // 2,
                               cz * TAMANHO_CHUNK + TAMANHO_CHUNK // 2)
    chance_arvore = BIOMAS[bioma_centro]['arvores']
    if possiveis_locais_arvores and rng.random() < chance_arvore:
        gerar_arvore_no_cache(*rng.choice(possiveis_locais_arvores))

    chunks_gerados.add((cx, cz))


# --- 5. MALHAS COMBINADAS (double_sided=False para nunca bugar) ---
FACES_CUBO = (
    ((1, 0, 0), ((.5, 0, -.5), (.5, 0, .5), (.5, 1, .5), (.5, 1, -.5))),
    ((-1, 0, 0), ((-.5, 0, -.5), (-.5, 0, .5), (-.5, 1, .5), (-.5, 1, -.5))),
    ((0, 1, 0), ((-.5, 1, -.5), (-.5, 1, .5), (.5, 1, .5), (.5, 1, -.5))),
    ((0, -1, 0), ((-.5, 0, .5), (-.5, 0, -.5), (.5, 0, -.5), (.5, 0, .5))),
    ((0, 0, 1), ((.5, 0, .5), (.5, 1, .5), (-.5, 1, .5), (-.5, 0, .5))),
    ((0, 0, -1), ((-.5, 0, -.5), (-.5, 1, -.5), (.5, 1, -.5), (.5, 0, -.5))),
)
UV_FACE = ((0, 0), (1, 0), (1, 1), (0, 1))


def remover_chunk(cx, cz):
    for sub_malha in chunks_entidades.pop((cx, cz), []):
        destroy(sub_malha)
    chunks_pendentes.discard((cx, cz))


def solicitar_atualizacao_chunk(cx, cz):
    chunks_pendentes.add((cx, cz))


def atualizar_malha_chunk(cx, cz):
    remover_chunk(cx, cz)
    gerar_dados_relevo(cx, cz)

    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            gerar_dados_relevo(cx + dx, cz + dz)

    dados_malha = {tipo: {'vertices': [], 'triangles': [], 'uvs': []}
                   for tipo in TEXTURAS_BLOCOS}

    x_min = cx * TAMANHO_CHUNK
    z_min = cz * TAMANHO_CHUNK

    for x in range(x_min, x_min + TAMANHO_CHUNK):
        for z in range(z_min, z_min + TAMANHO_CHUNK):
            for y in range(-ALTURA_MAXIMA, ALTURA_MAXIMA):
                tipo = cache_mapa.get((x, y, z))
                if tipo is None:
                    continue

                dados = dados_malha[tipo]
                for (dx, dy, dz), vertices_face in FACES_CUBO:
                    vizinho = cache_mapa.get((x + dx, y + dy, z + dz))

                    # Regra de culling: um bloco sólido esconde a face quando o
                    # vizinho também é sólido (a água, sendo transparente, não
                    # conta como "esconder" -- por isso dá pra ver o fundo do
                    # lago por baixo d'água). Já um bloco de ÁGUA só desenha a
                    # face quando o vizinho é ar (None): contra outro bloco de
                    # água a face ficaria invisível e custaria performance à
                    # toa, e contra um bloco sólido a face já está tampada por
                    # fora, então também não precisa ser desenhada.
                    if tipo == 'agua':
                        if vizinho is not None:
                            continue
                    else:
                        if vizinho is not None and vizinho != 'agua':
                            continue

                    inicio = len(dados['vertices'])
                    dados['vertices'].extend(
                        (x + vx, y + vy, z + vz)
                        for vx, vy, vz in vertices_face
                    )
                    dados['triangles'].extend((inicio, inicio + 1, inicio + 2,
                                               inicio, inicio + 2, inicio + 3))
                    dados['uvs'].extend(UV_FACE)

    sub_malhas_do_chunk = []
    for tipo, dados in dados_malha.items():
        if not dados['vertices']:
            continue
        malha = Mesh(vertices=dados['vertices'], triangles=dados['triangles'],
                     uvs=dados['uvs'], mode='triangle', static=True)

        # CORREÇÃO DO BUG BRANCO: double_sided=False e camera frustum culling
        opcoes = {'parent': scene, 'model': malha, 'texture': TEXTURAS_BLOCOS[tipo],
                  'double_sided': True, 'collider': None}
        entidade_malha = Entity(**opcoes)

        if tipo == 'agua':
            # Água nunca tem colisão (jogador nada por dentro dela -- ver
            # coluna_livre_para_jogador) e precisa ser semi-transparente,
            # exatamente como era o plano gigante antigo, só que agora só
            # existe onde realmente há um bloco de água nos dados.
            entidade_malha.color = COR_AGUA
            entidade_malha.unlit = True
            entidade_malha.setTransparency(TransparencyAttrib.MAlpha)

        sub_malhas_do_chunk.append(entidade_malha)

    if sub_malhas_do_chunk:
        chunks_entidades[(cx, cz)] = sub_malhas_do_chunk


def processar_fila_chunks(limite=1):
    if not chunks_pendentes:
        return
    jogador_chunk = (int(jogador.x // TAMANHO_CHUNK), int(jogador.z // TAMANHO_CHUNK))
    proximos = sorted(chunks_pendentes,
                      key=lambda c: (c[0] - jogador_chunk[0]) ** 2 + (c[1] - jogador_chunk[1]) ** 2)
    for chunk in proximos[:limite]:
        chunks_pendentes.discard(chunk)
        atualizar_malha_chunk(*chunk)


def solicitar_atualizacoes_do_bloco(x, z):
    cx, cz = x // TAMANHO_CHUNK, z // TAMANHO_CHUNK
    solicitar_atualizacao_chunk(cx, cz)
    if x % TAMANHO_CHUNK == 0:
        solicitar_atualizacao_chunk(cx - 1, cz)
    elif x % TAMANHO_CHUNK == TAMANHO_CHUNK - 1:
        solicitar_atualizacao_chunk(cx + 1, cz)
    if z % TAMANHO_CHUNK == 0:
        solicitar_atualizacao_chunk(cx, cz - 1)
    elif z % TAMANHO_CHUNK == TAMANHO_CHUNK - 1:
        solicitar_atualizacao_chunk(cx, cz + 1)


def encher_buraco_com_agua(posicao_inicial):
    """Espalha água a partir de um bloco recém colocado, preenchendo o buraco.

    É um flood-fill: a partir da célula onde a água foi colocada, ele anda
    pelas células vazias vizinhas (None) que estão no mesmo nível ou mais
    abaixo -- nunca mais alto que o ponto onde a água caiu, pra não "subir
    ladeira acima". Ele para sozinho ao esbarrar em blocos sólidos dos dois
    lados (um buraco fechado vira uma lagoa cheia) e tem uma trava de
    segurança (LIMITE_INUNDACAO) para o caso de a água ser despejada numa
    área aberta em vez de um buraco, evitando inundar o mundo inteiro.

    [FIX] Antes esta função chamava garantir_dados_da_coluna() para cada
    célula vizinha -- e essa função GERA TERRENO NOVO (gerar_dados_relevo)
    sempre que a água tenta se espalhar para um chunk que ainda não existia.
    Na prática, jogar água perto de área inexplorada criava terreno de
    verdade ali (relevo, fundo de areia etc.), como se a água estivesse
    "esculpindo" o mundo. Agora a água só se espalha por chunks que JÁ foram
    gerados -- se ela bate numa borda do mundo ainda não gerada, para ali,
    exatamente como bateria num bloco sólido.

    [FIX] Também agora respeitamos RAIO_MAXIMO_INUNDACAO: a água nunca se
    espalha mais longe do que isso (em X/Z) do ponto onde foi despejada,
    não importa quantos caminhos de célula vazia existam -- ver o
    comentário da constante para o motivo.
    """
    fila = deque([posicao_inicial])
    visitados = {posicao_inicial}
    chunks_afetados = set()
    ix, iy, iz = posicao_inicial

    while fila and len(visitados) < LIMITE_INUNDACAO:
        x, y, z = fila.popleft()
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0)):
            nx, ny, nz = x + dx, y + dy, z + dz
            if ny > posicao_inicial[1] or (nx, ny, nz) in visitados:
                continue
            if abs(nx - ix) > RAIO_MAXIMO_INUNDACAO or abs(nz - iz) > RAIO_MAXIMO_INUNDACAO:
                continue

            # Só avança se o chunk dessa célula já existir -- nunca gera
            # terreno novo como efeito colateral de despejar água.
            if (nx // TAMANHO_CHUNK, nz // TAMANHO_CHUNK) not in chunks_gerados:
                continue
            if cache_mapa.get((nx, ny, nz)) is not None:
                continue  # bloco sólido ou já com algo -- água não passa

            cache_mapa[(nx, ny, nz)] = 'agua'
            visitados.add((nx, ny, nz))
            fila.append((nx, ny, nz))
            chunks_afetados.add((nx // TAMANHO_CHUNK, nz // TAMANHO_CHUNK))

    for cx, cz in chunks_afetados:
        for dcx in (-1, 0, 1):
            for dcz in (-1, 0, 1):
                solicitar_atualizacao_chunk(cx + dcx, cz + dcz)


def coordenada_do_ponto(ponto):
    return (
        math.floor(ponto.x + 0.5),
        math.floor(ponto.y),
        math.floor(ponto.z + 0.5),
    )


def coluna_livre_para_jogador(ponto):
    """Verifica se o jogador cabe na coluna (pé + cabeça) daquele ponto.

    Testar só 1 célula (como antes) deixava passar dois bugs clássicos de
    colisão em grade: (1) andar na diagonal perto de uma parede permitia
    "cortar a quina" e atravessar a parede sem nunca testar a célula que
    realmente bloqueia; (2) só uma altura era checada, então uma parede que
    só existisse na altura da cabeça (ou um degrau na altura dos pés) não
    era detectada. Aqui checamos as duas células verticais que o corpo do
    jogador ocupa.
    """
    base = coordenada_do_ponto(ponto)
    garantir_dados_da_coluna(base[0], base[2])
    for dy in (0, 1):
        tipo = cache_mapa.get((base[0], base[1] + dy, base[2]))
        if tipo is not None and tipo != 'agua':
            return False
    return True


def bloco_em(x, y, z):
    """Devolve o tipo do bloco na célula de grade que contém o ponto (x,y,z),
    garantindo que os dados daquela coluna já existam.
    """
    garantir_dados_da_coluna(x, z)
    cx = math.floor(x + 0.5)
    cz = math.floor(z + 0.5)
    return cache_mapa.get((cx, math.floor(y), cz))


def jogador_esta_na_agua():
    """Física de natação: liga assim que existe água no peito do jogador
    (um pouco acima dos pés).

    [FIX] Antes isso usava nivel_superficie_agua() para "procurar" uma
    superfície de água perto da coluna do jogador, subindo/descendo até 3
    blocos a partir da posição atual. Essa busca heurística tinha um efeito
    colateral perigoso: ao encher o lago com água extra, era fácil a água
    vazar/alcançar uma bolsa escondida no terreno (uma caverna, um buraco
    debaixo do chão) perto o bastante da coluna do jogador para a busca
    "achar água" ali por engano, mesmo o jogador estando bem longe e acima
    de qualquer água visível -- exatamente o que causava a visão turva
    aparecendo acima do nível real da água depois de despejar mais água no
    lago. Checar diretamente o bloco onde o corpo do jogador está é muito
    mais confiável: só conta como "na água" a célula onde ele literalmente
    está.
    """
    return bloco_em(jogador.x, jogador.y + 0.9, jogador.z) == 'agua'


def profundidade_olhos_na_agua():
    """Retorna o quanto os OLHOS (a câmera) estão abaixo da superfície da
    água que os envolve: positivo = câmera submersa, -1 = câmera fora
    d'água (mesmo raciocínio de jogador_esta_na_agua(): primeiro checamos
    o bloco EXATO onde a câmera está, em vez de procurar uma superfície
    por perto, pra não confundir água escondida no terreno com a água
    visível onde o jogador realmente está).

    [FIX] Antes a altura dos olhos era calculada como
    "jogador.y + jogador.camera_pivot.y", supondo um valor fixo pra essa
    distância (2 unidades). Só que isso é a posição LOCAL do pivot, e
    qualquer diferença entre esse número suposto e a altura real da câmera
    no mundo jogava a conta inteira pra cima -- exatamente o motivo de tanto
    a visão turva quanto o "teto" de natação (mais abaixo, no laço de update)
    ligarem cedo demais, um bloco inteiro (ou mais) acima do nível visível da
    água. Usar camera.world_y direto pega a altura REAL da câmera no mundo,
    sem depender de nenhuma suposição sobre a altura do personagem.
    """
    altura_olhos = camera.world_y
    if bloco_em(jogador.x, altura_olhos, jogador.z) != 'agua':
        return -1
    superficie = nivel_superficie_agua(jogador.x, jogador.z, altura_olhos)
    return superficie - altura_olhos


def nivel_superficie_agua(x, z, y_referencia):
    """Acha a altura da superfície da água que envolve o ponto (x, y, z).

    Sobe célula por célula a partir de y_referencia enquanto a coluna
    continuar sendo água, e devolve a primeira altura que já não é mais
    água -- ou seja, o topo da poça/lago/mar ali. Precisamos disso em vez de
    usar NIVEL_AGUA fixo porque, com blocos de água colocados pelo jogador,
    uma lagoa pode existir em qualquer altura do mundo, não só no nível do
    mar.

    [FIX] jogador_esta_na_agua() considera o jogador "na água" se OU o peito
    OU os pés (0.9 abaixo) estiverem numa célula de água. Só que aqui a
    busca partia direto de y_referencia (o peito) -- se exatamente o peito
    já tinha saído da água mas os pés ainda estavam molhados (a situação
    típica de estar boiando na superfície), a célula de partida já não era
    'agua', o laço nem rodava, e a função devolvia a própria altura atual do
    jogador sem achar a superfície de verdade -- por isso o nado ficava
    "acima" do nível visível da água. Agora, se a célula de partida não for
    água, primeiro descemos (até 3 células) até achar água de verdade antes
    de subir procurando o topo.
    """
    cx = math.floor(x + 0.5)
    cz = math.floor(z + 0.5)
    garantir_dados_da_coluna(x, z)
    y = math.floor(y_referencia)
    limite_inferior = y - 3
    while cache_mapa.get((cx, y, cz)) != 'agua' and y > limite_inferior:
        y -= 1

    limite_superior = y + ALTURA_MAXIMA  # trava de segurança
    while cache_mapa.get((cx, y, cz)) == 'agua' and y < limite_superior:
        y += 1
    return y


def bloco_mirado(distancia_maxima=6):
    origem = camera.world_position
    direcao = camera.forward.normalized()
    celula = coordenada_do_ponto(origem)

    passo_x = 1 if direcao.x >= 0 else -1
    passo_y = 1 if direcao.y >= 0 else -1
    passo_z = 1 if direcao.z >= 0 else -1

    limite_x = celula[0] + (0.5 if passo_x > 0 else -0.5)
    limite_y = celula[1] + (1 if passo_y > 0 else 0)
    limite_z = celula[2] + (0.5 if passo_z > 0 else -0.5)

    infinito = float('inf')
    t_x = (limite_x - origem.x) / direcao.x if direcao.x else infinito
    t_y = (limite_y - origem.y) / direcao.y if direcao.y else infinito
    t_z = (limite_z - origem.z) / direcao.z if direcao.z else infinito
    delta_x = abs(1 / direcao.x) if direcao.x else infinito
    delta_y = abs(1 / direcao.y) if direcao.y else infinito
    delta_z = abs(1 / direcao.z) if direcao.z else infinito

    distancia = 0
    for _ in range(128):
        anterior = celula
        if t_x <= t_y and t_x <= t_z:
            distancia = t_x
            t_x += delta_x
            celula = (celula[0] + passo_x, celula[1], celula[2])
        elif t_y <= t_z:
            distancia = t_y
            t_y += delta_y
            celula = (celula[0], celula[1] + passo_y, celula[2])
        else:
            distancia = t_z
            t_z += delta_z
            celula = (celula[0], celula[1], celula[2] + passo_z)

        if distancia > distancia_maxima:
            break
        if cache_mapa.get(celula) is not None:
            return celula, anterior
    return None, None


# --- 6. CARREGAMENTO DINÂMICO DE CHUNKS SUAVE ---
def gerenciar_chunks_visiveis():
    if not jogo_iniciado:
        return
    chunk_player_x = int(jogador.x // TAMANHO_CHUNK)
    chunk_player_z = int(jogador.z // TAMANHO_CHUNK)

    chunks_necessarios = set()
    for cx in range(chunk_player_x - DISTANCIA_VISAO, chunk_player_x + DISTANCIA_VISAO + 1):
        for cz in range(chunk_player_z - DISTANCIA_VISAO, chunk_player_z + DISTANCIA_VISAO + 1):
            chunks_necessarios.add((cx, cz))

    for cx, cz in chunks_necessarios:
        if (cx, cz) not in chunks_entidades:
            solicitar_atualizacao_chunk(cx, cz)

    chunks_para_remover = [c for c in chunks_entidades if c not in chunks_necessarios]
    for c in chunks_para_remover:
        remover_chunk(*c)


# --- 7. RELAÇÃO DE INTERFACES E MENUS GRÁFICOS ---
tela_carregamento = Entity(parent=camera.ui, enabled=False)
fundo_carregamento = Entity(parent=tela_carregamento, model='quad', scale=(2, 2), color=color.black, z=3)
texto_carregamento = Text(parent=tela_carregamento, text='CARREGANDO MUNDO...', scale=3, position=(-0.35, 0),
                          color=color.white)

menu_inicial = Entity(parent=camera.ui, enabled=True)
fundo_inicial = Entity(parent=menu_inicial, model='quad', scale=(2, 2), color=color.dark_gray, z=2)
titulo_jogo = Text(parent=menu_inicial, text='JEBAS-3D', scale=3, position=(-0.15, 0.3), color=color.gold)

menu_opcoes = Entity(parent=camera.ui, enabled=False)
fundo_opcoes = Entity(parent=menu_opcoes, model='quad', scale=(2, 2), color=color.dark_gray, z=1)
titulo_opcoes = Text(parent=menu_opcoes, text='OPÇÕES DE VÍDEO', scale=2.5, position=(-0.25, 0.4), color=color.white)


# --- NEBLINA DE DISTÂNCIA ---
# [NOVO] O motivo de "2 Chunks" parecer um mundinho quebrado não é o mundo em
# si -- ele continua sendo gerado sem limites conforme o jogador anda (veja
# gerenciar_chunks_visiveis, que sempre carrega ao REDOR da posição atual,
# não uma área fixa). O problema é que, sem neblina, o limite onde os chunks
# carregados terminam é um corte seco: do lado de dentro, chão e árvores; do
# lado de fora, nada -- ar vazio até o céu. Com DISTANCIA_VISAO=2 esse corte
# fica bem perto do jogador e salta aos olhos; com 6 ele só fica mais longe,
# mas o problema é o mesmo.
#
# A neblina resolve isso escurecendo/clareando gradualmente tudo que já está
# perto dessa borda até a cor do céu -- então o jogador nunca chega a ver o
# corte, só um horizonte que se perde de vista, como um mundo de verdade.
# Isso não desenha NADA a mais (não custa FPS): só recolore pixels que já
# seriam desenhados de qualquer forma. É por isso que dá pra ter qualquer
# DISTANCIA_VISAO, mesmo curta, sem parecer um mapa pequeno.
_COR_NEBLINA = (0.72, 0.78, 0.83)  # tom acinzentado/azulado -- combina com o horizonte do Sky() padrão do Ursina
_neblina_mundo = Fog('neblina_mundo')
_neblina_mundo.setColor(*_COR_NEBLINA)
scene.setFog(_neblina_mundo)


def atualizar_neblina():
    """Recalcula o alcance da neblina a partir de DISTANCIA_VISAO, pra que
    ela sempre comece um pouco antes da borda dos chunks carregados e já
    esteja totalmente opaca bem em cima dela -- não importa a distância de
    visão escolhida, o limite do mundo carregado nunca fica visível.
    """
    alcance = DISTANCIA_VISAO * TAMANHO_CHUNK
    inicio = max(6, alcance * 0.55)
    fim = max(inicio + 4, alcance * 0.95)
    _neblina_mundo.setLinearRange(inicio, fim)


def mudar_distancia_visao(valor):
    global DISTANCIA_VISAO
    DISTANCIA_VISAO = valor
    texto_distancia.text = f'Distancia de Visao: {DISTANCIA_VISAO} Chunks'
    atualizar_neblina()
    if jogo_iniciado:
        resetar_entidades_mundo()
        gerenciar_chunks_visiveis()


atualizar_neblina()


def configurar_modo_tela(modo):
    if modo == 'janela':
        window.fullscreen = False
        window.borderless = True
    elif modo == 'sem_bordas':
        window.fullscreen = True
        window.borderless = True
    elif modo == 'tela_cheia':
        window.fullscreen = True
        window.borderless = False


def configurar_resolucao(largura, altura):
    window.size = (largura, altura)


texto_distancia = Text(parent=menu_opcoes, text=f'Distancia de Visao: {DISTANCIA_VISAO} Chunks', position=(-0.4, 0.25),
                       scale=1.5)
btn_vis_curta = Button(parent=menu_opcoes, text='CURTA (2)', scale=(0.18, 0.05), position=(-0.3, 0.17),
                       on_click=lambda: mudar_distancia_visao(2))
btn_vis_media = Button(parent=menu_opcoes, text='MÉDIA (3)', scale=(0.18, 0.05), position=(-0.1, 0.17),
                       on_click=lambda: mudar_distancia_visao(3))
btn_vis_longa = Button(parent=menu_opcoes, text='LONGA (6)', scale=(0.18, 0.05), position=(0.1, 0.17),
                       on_click=lambda: mudar_distancia_visao(6))

texto_modo_tela = Text(parent=menu_opcoes, text='Modo de Janela:', position=(-0.4, 0.05), scale=1.5)
btn_modo_janela = Button(parent=menu_opcoes, text='JANELA', scale=(0.18, 0.05), position=(-0.3, -0.03),
                         on_click=lambda: configurar_modo_tela('janela'))
btn_modo_sem_borda = Button(parent=menu_opcoes, text='SEM BORDAS', scale=(0.18, 0.05), position=(-0.1, -0.03),
                            on_click=lambda: configurar_modo_tela('sem_bordas'))
btn_modo_fullscreen = Button(parent=menu_opcoes, text='TELA CHEIA', scale=(0.18, 0.05), position=(0.1, -0.03),
                             on_click=lambda: configurar_modo_tela('tela_cheia'))

texto_resolucao = Text(parent=menu_opcoes, text='Resolucao do Jogo:', position=(-0.4, -0.15), scale=1.5)
btn_res_baixa = Button(parent=menu_opcoes, text='1280x720', scale=(0.18, 0.05), position=(-0.3, -0.23),
                       on_click=lambda: configurar_resolucao(1280, 720))
btn_res_media = Button(parent=menu_opcoes, text='1600x900', scale=(0.18, 0.05), position=(-0.1, -0.23),
                       on_click=lambda: configurar_resolucao(1600, 900))
btn_res_alta = Button(parent=menu_opcoes, text='1920x1080', scale=(0.18, 0.05), position=(0.1, -0.23),
                      on_click=lambda: configurar_resolucao(1920, 1080))


def abrir_opcoes():
    menu_inicial.enabled = False
    menu_pausa.enabled = False
    menu_opcoes.enabled = True


def fechar_opcoes():
    menu_opcoes.enabled = False
    if jogo_iniciado:
        menu_pausa.enabled = True
    else:
        menu_inicial.enabled = True


btn_voltar_opc = Button(parent=menu_opcoes, text='VOLTAR', color=color.gray, scale=(0.25, 0.06), position=(0, -0.35),
                        on_click=fechar_opcoes)

btn_novo = Button(parent=menu_inicial, text='NOVO MUNDO', color=color.azure, scale=(0.4, 0.07), position=(0, 0.08),
                  on_click=mostrar_carregamento_novo)
btn_carregar = Button(parent=menu_inicial, text='CARREGAR MUNDO', color=color.orange, scale=(0.4, 0.07),
                      position=(0, 0.0), on_click=mostrar_carregamento_salvo)
btn_opcoes_ini = Button(parent=menu_inicial, text='OPÇÕES GRÁFICAS', color=color.violet, scale=(0.4, 0.07),
                        position=(0, -0.08), on_click=abrir_opcoes)
btn_sair_ini = Button(parent=menu_inicial, text='SAIR', color=color.red, scale=(0.4, 0.07), position=(0, -0.16),
                      on_click=application.quit)

menu_pausa = Entity(parent=camera.ui, enabled=False)
fundo_pausa = Entity(parent=menu_pausa, model='quad', scale=(2, 2), color=color.Color(0, 0, 0, 0.7), z=1)

botao_salvar = Button(parent=menu_pausa, text='SALVAR MUNDO', color=color.azure, scale=(0.4, 0.07), position=(0, 0.15),
                      on_click=salvar_mundo)
botao_carregar = Button(parent=menu_pausa, text='RECARREGAR SAVE', color=color.orange, scale=(0.4, 0.07),
                        position=(0, 0.07), on_click=mostrar_carregamento_pausa)
botao_opcoes_pausa = Button(parent=menu_pausa, text='OPÇÕES GRÁFICAS', color=color.violet, scale=(0.4, 0.07),
                            position=(0, -0.01), on_click=abrir_opcoes)
botao_menu_inicial = Button(parent=menu_pausa, text='MENU PRINCIPAL', color=color.yellow, text_color=color.black,
                            scale=(0.4, 0.07), position=(0, -0.09), on_click=voltar_ao_menu_inicial)
botao_fechar = Button(parent=menu_pausa, text='SAIR DO JOGO', color=color.red, scale=(0.4, 0.07), position=(0, -0.17),
                      on_click=application.quit)


def alternar_menu_pausa():
    if menu_opcoes.enabled:
        return
    menu_pausa.enabled = not menu_pausa.enabled
    if menu_pausa.enabled:
        jogador.cursor.enabled = False
        mouse.locked = False
        mouse.visible = True
        hotbar_conteiner.enabled = False
        mao_jogador.enabled = False
    else:
        jogador.cursor.enabled = True
        mouse.locked = True
        mouse.visible = False
        hotbar_conteiner.enabled = True
        mao_jogador.enabled = True


# --- 8. GERENCIAMENTO GLOBAL DE ENTRADAS ---
def input(key):
    global bloco_selecionado, indice_selecionado, pulos_extras, velocidade_vertical

    if menu_opcoes.enabled and key == 'escape':
        fechar_opcoes()
        return

    if not jogo_iniciado:
        return

    if key == 'escape':
        alternar_menu_pausa()
        return

    if menu_pausa.enabled or tela_carregamento.enabled:
        return

    if key == 'space' and not jogador_esta_na_agua() and jogador.grounded:
        velocidade_vertical = 8.0
        jogador.grounded = False
        return

    if key in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-']:
        # [FIX] int(key) - 1 quebrava com ValueError assim que a tecla era
        # '-' ('-' não é um número, então int('-') nunca funciona -- é
        # exatamente o traceback que travava o jogo). O '0' também já era
        # tratado errado antes: int('0') - 1 dá -1, um índice negativo que
        # em Python conta a partir do FIM da lista (ORDEM_BLOCOS[-1] é
        # 'agua', não o 10º slot que o '0' devia selecionar). Como
        # ORDEM_BLOCOS tem 11 blocos, não cabe só em '1'-'9': '0' é o 10º
        # slot (índice 9) e '-' é o 11º e último (índice 10) -- mapeamos os
        # dois na mão em vez de derivar de int(key).
        if key == '0':
            novo_index = 9
        elif key == '-':
            novo_index = 10
        else:
            novo_index = int(key) - 1
        if novo_index < len(ORDEM_BLOCOS):
            atualizar_selecao_hotbar(novo_index)

    if key == 'scroll up':
        novo_index = (indice_selecionado + 1) % len(ORDEM_BLOCOS)
        atualizar_selecao_hotbar(novo_index)
    if key == 'scroll down':
        novo_index = (indice_selecionado - 1) % len(ORDEM_BLOCOS)
        atualizar_selecao_hotbar(novo_index)

    if key in ['left mouse down', 'right mouse down']:
        mao_jogador.position = Vec3(0.5, -0.4, 0.9)
        mao_jogador.rotation = Vec3(25, -10, 15)
        mao_jogador.animate_position(Vec3(0.6, -0.5, 1.1), duration=0.1, curve=curve.linear)
        mao_jogador.animate_rotation(Vec3(15, -20, 5), duration=0.1, curve=curve.linear)

    if key in ['left mouse down', 'right mouse down']:
        coordenada_bloco, celula_livre = bloco_mirado()
        if coordenada_bloco is None:
            return

        if key == 'left mouse down':
            if cache_mapa.get(coordenada_bloco) == 'bedrock':
                return  # não deixa quebrar
            del cache_mapa[coordenada_bloco]
            alvo_x, alvo_y, alvo_z = coordenada_bloco
            solicitar_atualizacoes_do_bloco(alvo_x, alvo_z)

            # Se o buraco recém-aberto tem água colada do lado (você cavou
            # perto de um lago/mar existente), a água escoa pra dentro dele
            # -- antes isso só acontecia ao COLOCAR água manualmente; cavar
            # do lado de fora não puxava a água pra dentro.
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0)):
                vizinho = (alvo_x + dx, alvo_y + dy, alvo_z + dz)
                if cache_mapa.get(vizinho) == 'agua':
                    encher_buraco_com_agua(vizinho)
                    break

        elif celula_livre is not None and cache_mapa.get(celula_livre) is None:
            cache_mapa[celula_livre] = bloco_selecionado
            alvo_x, _, alvo_z = celula_livre
            solicitar_atualizacoes_do_bloco(alvo_x, alvo_z)
            if bloco_selecionado == 'agua':
                encher_buraco_com_agua(celula_livre)


# --- 9. LAÇO DE ATUALIZAÇÃO POR FRAME ---
_temporizador = 0


def update():
    global _temporizador, pulos_extras, velocidade_vertical, agua_efeito_ativo, altura_olhos_referencia
    global _frame_chuva

    if not jogo_iniciado or tela_carregamento.enabled:
        return

    for b in mini_blocos_icones:
        b.rotation_y += time.dt * 45

    se_movendo = held_keys['w'] or held_keys['s'] or held_keys['a'] or held_keys['d']

    if se_movendo and not menu_pausa.enabled:
        frequencia = time.time() * 12
        balanco_y = math.sin(frequencia) * 0.03
        balanco_x = math.cos(frequencia * 0.5) * 0.02
        mao_jogador.position = Vec3(0.6 + balanco_x, -0.5 + balanco_y, 1.1)
    else:
        mao_jogador.position = lerp(mao_jogador.position, Vec3(0.6, -0.5, 1.1), time.dt * 5)

    if menu_pausa.enabled:
        efeito_agua.enabled = False
        chuva.enabled = False
        return

    # [FIX] Limitamos (clamp) o dt usado na física. Sem isso, se um frame
    # qualquer demorar muito no mundo real (por exemplo, logo depois de
    # fechar o menu de pausa, salvar, carregar, ou gerar vários chunks de
    # uma vez), o Ursina reporta um time.dt gigante nesse frame seguinte.
    # Como multiplicamos velocidade e posição por time.dt diretamente, um
    # dt inflado fazia o jogador cair várias unidades de uma vez só nesse
    # ÚNICO frame -- rápido demais pra colisão pegar no meio do caminho --
    # atravessando o chão de vez (era exatamente o "SALTO ANORMAL DE Y" que
    # os logs de debug mostraram, ex: 8.0 -> -7.0 num frame só). O jogo
    # então "escalava" de volta 1 bloco por frame até a superfície, o que
    # parecia um bug de colisão mas na real era esse dt sem limite. 0.05
    # equivale a no mínimo ~20 quadros por segundo de física por frame,
    # suficiente pra qualquer soluço não atravessar um bloco inteiro.
    #
    # [FIX] Movido pra cá (antes só existia mais abaixo) porque a atualização
    # da chuva também precisa de um dt confiável -- sem isso, na primeira
    # execução dessa parte do update() o "dt" ainda nem existia.
    dt = min(time.dt, 0.05)

    esta_na_agua = jogador_esta_na_agua()  # controla a FÍSICA de natação (baseado nos pés)

    # [FIX] Só remedimos altura_olhos_referencia enquanto o jogador está fora
    # da água (esta_na_agua == False) -- é a única situação estável, sem
    # nenhuma correção de altura em andamento que possa contaminar a leitura.
    if not esta_na_agua:
        altura_olhos_referencia = camera.world_y - jogador.y

    # [FIX] O efeito visual (tela turva/azulada) agora é controlado à parte,
    # pela submersão dos OLHOS (profundidade_olhos_na_agua), não dos pés --
    # ver o docstring da função para o motivo. Assim a visão só embaça
    # quando a câmera realmente está abaixo do nível visível da água, e
    # desliga assim que a cabeça sai, mesmo que os pés continuem molhados.
    profundidade_olhos = profundidade_olhos_na_agua()
    # [FIX] Histerese: se o efeito já estava ligado, só desliga quando a
    # profundidade cair abaixo de MARGEM_DESLIGAR_TURVA (bem acima da
    # superfície); se estava desligado, só liga quando passar de
    # MARGEM_LIGAR_TURVA (visivelmente abaixo da superfície). Isso impede o
    # efeito de piscar ligado/desligado quando o jogador está boiando parado
    # bem em cima da linha da água.
    if agua_efeito_ativo:
        agua_efeito_ativo = profundidade_olhos > MARGEM_DESLIGAR_TURVA
    else:
        agua_efeito_ativo = profundidade_olhos > MARGEM_LIGAR_TURVA
    cabeca_submersa = agua_efeito_ativo
    efeito_agua.enabled = cabeca_submersa
    if cabeca_submersa:
        # [FIX] Curva suave: logo que passa da margem de entrada, a tela fica
        # só levemente turva (não direto escura/opaca) -- a intensidade forte
        # só aparece quando o jogador já está visivelmente fundo, não bem na
        # beira da superfície. profundidade_efetiva desconta a margem de
        # entrada, então ela começa em ~0 exatamente onde o efeito liga.
        # [AJUSTE] A pedido do usuário, o efeito agora começa mais forte
        # (0.35 em vez de 0.22) e sobe mais rápido com a profundidade (0.55
        # em vez de 0.32), chegando bem mais turvo/azul quanto mais fundo
        # o jogador mergulha.
        profundidade_efetiva = max(0.0, profundidade_olhos - MARGEM_LIGAR_TURVA)
        alpha = min(0.95, 0.35 + profundidade_efetiva * 0.55)
        efeito_agua.color = color.rgba(*COR_EFEITO_AGUA, alpha)

    # [FIX] A chuva some debaixo d'água (não faria sentido ver gotas caindo
    # enquanto está submerso) e com o menu de pausa (senão o mundo "continua
    # chovendo" por trás do menu). A visibilidade por CAVERNA/teto agora é
    # decidida gota por gota (ver bloqueios_chuva/calcular_estado_gota), não
    # pelo jogo inteiro de uma vez: a coluna debaixo dos PÉS do jogador podia
    # estar bloqueada (parado bem na boca de uma caverna, olhando pra fora)
    # enquanto a maior parte das gotas ao redor, já em área aberta, deveria
    # continuar visível -- checar só a coluna do jogador desligava a chuva
    # inteira nesse caso.
    chuva.enabled = not cabeca_submersa
    if chuva.enabled:
        for i, g in enumerate(gotas_chuva):
            if impactos_chuva[i] is None:
                impactos_chuva[i], bloqueios_chuva[i] = calcular_estado_gota(g.x, g.z)

            # altura de impacto em coordenada LOCAL (relativa a jogador.y),
            # pra comparar direto com a posição da gota, que também é local.
            altura_impacto_local = impactos_chuva[i] - jogador.y

            nova_altura = g.y - VELOCIDADE_QUEDA_CHUVA * dt
            if nova_altura <= altura_impacto_local:
                # [NOVO] bateu na superfície (chão ou água) -- um respingo
                # rápido bem na altura certa, só se a coluna não estiver
                # bloqueada por um teto (não faz sentido respingo onde a
                # própria gota nem aparece na tela). Depois reaparece lá em
                # cima numa posição X/Z nova, com um novo estado calculado
                # pra essa nova coluna.
                if not bloqueios_chuva[i]:
                    criar_respingo_chuva(g.x, altura_impacto_local, g.z)
                novo_x = random.uniform(-RAIO_CHUVA, RAIO_CHUVA)
                novo_z = random.uniform(-RAIO_CHUVA, RAIO_CHUVA)
                gotas_chuva[i] = Vec3(novo_x, ALTURA_CHUVA, novo_z)
                impactos_chuva[i], bloqueios_chuva[i] = calcular_estado_gota(novo_x, novo_z)
            else:
                gotas_chuva[i] = Vec3(g.x, nova_altura, g.z)

        # [OTIMIZAÇÃO FPS] chuva.model.generate() reenvia a malha inteira
        # (todos os vértices) pra GPU -- é a parte mais cara do sistema de
        # chuva depois dos respingos. Fazendo isso a cada 2 frames em vez de
        # todo frame, cortamos essa metade do custo pela metade sem dar pra
        # perceber (a chuva ainda "atualiza" a 30fps quando o jogo roda a
        # 60fps, e gotas caindo rápido escondem bem esse detalhe).
        _frame_chuva += 1
        if _frame_chuva % 2 == 0:
            chuva.model.vertices = gerar_vertices_chuva()
            chuva.model.generate()

    # [FIX] Limitamos (clamp) o dt usado na física -- ver comentário no topo
    # do update(), onde essa variável agora é calculada.
    if esta_na_agua:
        # --- MODO NATAÇÃO ---
        velocidade_vertical = 0

        direcao_frente = camera.forward
        direcao_frente.y = 0
        direcao_frente = direcao_frente.normalized()
        direcao_lado = camera.right
        direcao_lado.y = 0
        direcao_lado = direcao_lado.normalized()

        movimento_horizontal = Vec3(0, 0, 0)
        if held_keys['w']: movimento_horizontal += direcao_frente
        if held_keys['s']: movimento_horizontal -= direcao_frente
        if held_keys['d']: movimento_horizontal += direcao_lado
        if held_keys['a']: movimento_horizontal -= direcao_lado

        if movimento_horizontal.length() > 0:
            movimento_horizontal = movimento_horizontal.normalized() * VELOCIDADE_NADO * dt

            # [FIX] Antes isso era "jogador.position += movimento_horizontal"
            # direto, sem checar colisão nenhuma -- diferente do modo terra
            # (que testa coluna_livre_para_jogador antes de mover). Resultado:
            # nadando na direção da margem, dava pra atravessar o bloco da
            # parede/beirada do lago e ficar preso dentro dele quando saía
            # da água (a "visão por trás do bloco"). Testamos X e Z
            # separadamente, igual no modo terra, pra também poder deslizar
            # ao longo de uma parede em vez de travar.
            pos_x = jogador.position + Vec3(movimento_horizontal.x, 0, 0)
            if coluna_livre_para_jogador(pos_x):
                jogador.x = pos_x.x

            pos_z = jogador.position + Vec3(0, 0, movimento_horizontal.z)
            if coluna_livre_para_jogador(pos_z):
                jogador.z = pos_z.z

        alvo_vertical = 0.0
        if held_keys['space']:
            alvo_vertical = VELOCIDADE_VERTICAL_NADO
        if held_keys['shift']:
            alvo_vertical = -VELOCIDADE_VERTICAL_NADO

        if not held_keys['space'] and not held_keys['shift'] and abs(camera.forward.y) > 0.12:
            alvo_vertical = camera.forward.y * VELOCIDADE_VERTICAL_NADO

        jogador.y += alvo_vertical * dt

        # Antes isso travava o jogador em NIVEL_AGUA + 0.9 (o nível do mar
        # fixo). Como agora pode existir água em qualquer altura (lagos,
        # poças feitas pelo jogador), calculamos a superfície da água LOCAL
        # em vez de usar um número fixo -- senão nadar numa lagoa de montanha
        # ia te puxar de volta pro nível do mar.
        #
        # [FIX] jogador.y é a posição dos PÉS (a base do FirstPersonController),
        # e a câmera fica montada acima disso. Usamos altura_olhos_referencia
        # (medida em terra firme, ver definição da variável lá em cima) em vez
        # de ler "camera.world_y - jogador.y" ao vivo aqui dentro -- ler ao
        # vivo bem no frame em que jogador.y acabou de mudar podia sair errado
        # por um atraso de propagação da câmera, e como essa correção só
        # empurra o jogador pra baixo (nunca pra cima), o erro se acumulava a
        # cada frame até o jogador atravessar o fundo do oceano.
        #
        # [FIX] Calculamos y_chao_atual (o fundo real) ANTES de aplicar esse
        # clamp, e nunca deixamos limite_pes cair abaixo dele. Antes, em água
        # rasa (perto da praia, por exemplo), "superficie_local - altura_camera"
        # podia dar um valor mais baixo que o fundo sólido de verdade -- ou
        # seja, o próprio clamp empurrava os PÉS do jogador pra dentro do
        # chão, sem saber que o fundo estava mais perto que isso. Pior: a
        # trava de segurança que vinha logo depois (y_chao_atual + 1.2) rodava
        # DEPOIS desse empurrão, procurando o chão a partir de uma posição já
        # afundada demais -- como altura_do_chao só procura pra BAIXO, ela
        # nunca mais encontrava o fundo real, e sim alguma camada sólida mais
        # profunda ainda (uma caverna, rocha), fazendo o jogador continuar
        # afundando cada vez mais até precisar pular várias vezes pra escapar.
        # [AJUSTE] A pedido do usuário, a posição de descanso ao nadar (sem
        # segurar espaço) ficava com os OLHOS um pouco ABAIXO da superfície
        # (o "-0.1" no cálculo) -- só subindo pra cima d'água quando ele
        # segurava espaço. Trocamos pra "+0.35": por padrão, flutuando parado,
        # a cabeça já fica um pouco ACIMA da água (como nadar de verdade), e
        # segurar espaço continua subindo mais alto que isso.
        y_chao_atual = altura_do_chao(jogador.x, jogador.z, jogador.y)
        superficie_local = nivel_superficie_agua(jogador.x, jogador.z, jogador.y)
        altura_camera = altura_olhos_referencia
        limite_pes = max(superficie_local - altura_camera + 0.35, y_chao_atual + 1.2)
        if jogador.y > limite_pes and not held_keys['space']:
            jogador.y = limite_pes

        if jogador.y < y_chao_atual + 1.2:
            jogador.y = y_chao_atual + 1.2

    else:
        # --- MODO TERRA ---
        velocidade_vertical -= 25 * dt
        jogador.y += velocidade_vertical * dt

        y_chao_atual = altura_do_chao(jogador.x, jogador.z, jogador.y)
        if jogador.y <= y_chao_atual + 1.0:
            jogador.y = y_chao_atual + 1.0
            velocidade_vertical = 0
            jogador.grounded = True
            pulos_extras = 1
        else:
            jogador.grounded = False

        velocidade_andar = 5.0
        direcao_frente = camera.forward
        direcao_frente.y = 0
        direcao_frente = direcao_frente.normalized()
        direcao_lado = camera.right
        direcao_lado.y = 0
        direcao_lado = direcao_lado.normalized()

        movimento_horizontal = Vec3(0, 0, 0)
        if held_keys['w']: movimento_horizontal += direcao_frente
        if held_keys['s']: movimento_horizontal -= direcao_frente
        if held_keys['d']: movimento_horizontal += direcao_lado
        if held_keys['a']: movimento_horizontal -= direcao_lado

        if movimento_horizontal.length() > 0:
            movimento_horizontal = movimento_horizontal.normalized() * velocidade_andar * dt

            # Testamos X e Z separadamente (em vez do ponto de destino combinado)
            # para o jogador poder "deslizar" ao longo da parede da caverna em
            # vez de travar, e para não cortar a quina na diagonal.
            pos_x = jogador.position + Vec3(movimento_horizontal.x, 0, 0)
            if coluna_livre_para_jogador(pos_x):
                jogador.x = pos_x.x

            pos_z = jogador.position + Vec3(0, 0, movimento_horizontal.z)
            if coluna_livre_para_jogador(pos_z):
                jogador.z = pos_z.z

    processar_fila_chunks(limite=1)

    _temporizador += time.dt
    if _temporizador > 0.3:
        gerenciar_chunks_visiveis()
        _temporizador = 0

    if jogador.y < -15:
        velocidade_vertical = 0
        px = math.floor(jogador.x)
        pz = math.floor(jogador.z)
        posicionar_jogador_na_superficie(px, pz)


# --- 10. INICIALIZAÇÃO DO JOGO ---
ceu = Sky()
# [NOVO] Tingir o céu com a mesma cor da neblina (_COR_NEBLINA) -- sem isso,
# dava pra ver onde a neblina "termina" e o céu original começa, uma linha
# ou faixa de cor diferente bem no horizonte. Com a mesma cor dos dois lados,
# neblina e céu se misturam sem costura.
ceu.color = color.rgba(*_COR_NEBLINA, 1)
sol = DirectionalLight()
sol.look_at(Vec3(1, -1, 1))

mouse.locked = False
mouse.visible = True

app.run()
