from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
from panda3d.core import TransparencyAttrib
import math
import os
import json
import random

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

COR_AGUA = color.rgba(60, 170, 255, 85)  # Azul Perfeito

TEXTURAS_BLOCOS = {
    'grama': 'texturas/grama.png' if os.path.exists('texturas/grama.png') else 'white_cube',
    'terra': 'texturas/terra.png' if os.path.exists('texturas/terra.png') else 'white_cube',
    'pedra': 'texturas/pedra.png' if os.path.exists('texturas/pedra.png') else 'white_cube',
    'areia': 'texturas/areia.png' if os.path.exists('texturas/areia.png') else 'white_cube',
    'agua': 'texturas/agua.png' if os.path.exists('texturas/agua.png') else 'white_cube',
    'bronze': 'texturas/bronze.png' if os.path.exists('texturas/bronze.png') else 'white_cube',
    'prata': 'texturas/prata.png' if os.path.exists('texturas/prata.png') else 'white_cube',
    'ouro': 'texturas/ouro.png' if os.path.exists('texturas/ouro.png') else 'white_cube',
    'madeira': 'texturas/madeira.png' if os.path.exists('texturas/madeira.png') else 'white_cube',
    'folhas': 'texturas/folhas.png' if os.path.exists('texturas/folhas.png') else 'white_cube'
}

plano_agua = Entity(
    parent=scene,
    model='plane',
    scale=(500, 1, 500),
    position=(0, NIVEL_AGUA + 4, 0),
    texture='agua',
    color=color.azure,
    texture_scale=(25, 25),
    alpha=0.4,
    unlit=True,
    double_sided=True,
    collider=None
)

plano_agua.setTransparency(TransparencyAttrib.MAlpha)

ARQUIVO_SAVE = 'mundo_save.json'
ORDEM_BLOCOS = ['grama', 'terra', 'pedra', 'areia', 'agua', 'bronze', 'prata', 'ouro', 'madeira', 'folhas']
bloco_selecionado = 'grama'
indice_selecionado = 0

# Física manual
jogador = FirstPersonController(enabled=False)
jogador.gravity = 0
jogador.speed = 0
jogador.jump_height = 0

pulos_extras = 2
velocidade_vertical = 0.0

efeito_agua = Entity(parent=camera.ui, model='quad', scale=2,
                     color=color.rgba(20, 150, 255, 0.32), z=0.1, enabled=False)

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


def altura_do_chao(x, z):
    """Encontra o topo sólido da coluna para nascer/recuperar o jogador (ignora água)."""
    for y in range(ALTURA_MAXIMA - 1, -ALTURA_MAXIMA - 1, -1):
        tipo = cache_mapa.get((int(x), int(y), int(z)))
        if tipo is not None and tipo != 'agua' and tipo != 'folhas' and tipo != 'madeira':
            return y
    return 0


def posicionar_jogador_na_superficie(x, z):
    cx, cz = x // TAMANHO_CHUNK, z // TAMANHO_CHUNK
    atualizar_malha_chunk(cx, cz)
    y_chao = altura_do_chao(x, z)
    jogador.position = (x, y_chao + 3, z)


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
    plano_agua.enabled = True


def mostrar_carregamento_salvo():
    if not os.path.exists(ARQUIVO_SAVE):
        return
    menu_inicial.enabled = False
    tela_carregamento.enabled = True
    invoke(iniciar_mundo_carregado, delay=0.05)


def iniciar_mundo_carregado():
    global cache_mapa, jogo_iniciado, velocidade_vertical
    jogo_iniciado = True
    velocidade_vertical = 0
    jogador.enabled = True
    jogador.gravity = 0
    mouse.locked = True
    mouse.visible = False

    with open(ARQUIVO_SAVE, 'r') as f:
        dados_carregados = json.load(f)

    cache_mapa.clear()
    chunks_gerados.clear()
    chunks_com_agua.clear()
    resetar_entidades_mundo()
    for chave_string, tipo in dados_carregados.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    posicionar_jogador_na_superficie(4, 4)
    gerenciar_chunks_visiveis()
    tela_carregamento.enabled = False
    hotbar_conteiner.enabled = True
    mao_jogador.enabled = True
    plano_agua.enabled = True


def salvar_mundo():
    dados_para_salvar = {}
    for pos, tipo in cache_mapa.items():
        if tipo is not None:
            chave_string = f"{pos[0]},{pos[1]},{pos[2]}"
            dados_para_salvar[chave_string] = tipo
    with open(ARQUIVO_SAVE, 'w') as f:
        json.dump(dados_para_salvar, f)
    alternar_menu_pausa()


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
    with open(ARQUIVO_SAVE, 'r') as f:
        dados_carregados = json.load(f)
    cache_mapa.clear()
    chunks_gerados.clear()
    for chave_string, tipo in dados_carregados.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    resetar_entidades_mundo()
    posicionar_jogador_na_superficie(4, 4)
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
    plano_agua.enabled = False


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
    fundo_do_mundo = -12

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
                else:
                    cache_mapa[pos] = 'pedra'

            if eh_agua:
                chunks_com_agua.add((cx, cz))
                # A água é apenas um marcador, o plano global cuida do visual.
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
                if tipo is None or tipo == 'agua':
                    continue

                dados = dados_malha[tipo]
                for (dx, dy, dz), vertices_face in FACES_CUBO:
                    vizinho = cache_mapa.get((x + dx, y + dy, z + dz))
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
        sub_malhas_do_chunk.append(Entity(**opcoes))

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


def coordenada_do_ponto(ponto):
    return (
        math.floor(ponto.x + 0.5),
        math.floor(ponto.y),
        math.floor(ponto.z + 0.5),
    )


def jogador_esta_na_agua():
    return jogador.y < NIVEL_AGUA + 1.0


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


def mudar_distancia_visao(valor):
    global DISTANCIA_VISAO
    DISTANCIA_VISAO = valor
    texto_distancia.text = f'Distancia de Visao: {DISTANCIA_VISAO} Chunks'
    if jogo_iniciado:
        resetar_entidades_mundo()
        gerenciar_chunks_visiveis()


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

    if menu_pausa.enabled:
        return

    if key == 'space' and not jogador_esta_na_agua() and jogador.grounded:
        velocidade_vertical = 8.0
        jogador.grounded = False
        return

    if key in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']:
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
            del cache_mapa[coordenada_bloco]
            alvo_x, _, alvo_z = coordenada_bloco
            solicitar_atualizacoes_do_bloco(alvo_x, alvo_z)

        elif celula_livre is not None and cache_mapa.get(celula_livre) is None:
            cache_mapa[celula_livre] = bloco_selecionado
            alvo_x, _, alvo_z = celula_livre
            solicitar_atualizacoes_do_bloco(alvo_x, alvo_z)


# --- 9. LAÇO DE ATUALIZAÇÃO POR FRAME ---
_temporizador = 0


def update():
    global _temporizador, pulos_extras, velocidade_vertical

    if 'plano_agua' in globals() and plano_agua:
        # 1. CORRENTEZA BEM SUAVE: Reduzimos os valores para a textura deslizar devagarzinho
        plano_agua.texture_offset += Vec2(0.05 * time.dt, 0.01 * time.dt)

        # 2. MARÉ LENTA: Ajustamos o math.sin para subir e descer de forma quase imperceptível
        plano_agua.y = (NIVEL_AGUA + 4) + math.sin(time.time() * 0.8) * 0.03

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
        return

    esta_na_agua = jogador_esta_na_agua()
    efeito_agua.enabled = esta_na_agua

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
            movimento_horizontal = movimento_horizontal.normalized() * VELOCIDADE_NADO * time.dt
            jogador.position += movimento_horizontal

        alvo_vertical = 0.0
        if held_keys['space']:
            alvo_vertical = VELOCIDADE_VERTICAL_NADO
        if held_keys['shift']:
            alvo_vertical = -VELOCIDADE_VERTICAL_NADO

        if not held_keys['space'] and not held_keys['shift'] and abs(camera.forward.y) > 0.12:
            alvo_vertical = camera.forward.y * VELOCIDADE_VERTICAL_NADO

        jogador.y += alvo_vertical * time.dt

        if jogador.y > NIVEL_AGUA + 0.9 and not held_keys['space']:
            jogador.y = NIVEL_AGUA + 0.9

        y_chao_atual = altura_do_chao(jogador.x, jogador.z)
        if jogador.y < y_chao_atual + 1.2:
            jogador.y = y_chao_atual + 1.2

    else:
        # --- MODO TERRA ---
        velocidade_vertical -= 25 * time.dt
        jogador.y += velocidade_vertical * time.dt

        y_chao_atual = altura_do_chao(jogador.x, jogador.z)
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
            movimento_horizontal = movimento_horizontal.normalized() * velocidade_andar * time.dt

            nova_pos = jogador.position + movimento_horizontal
            bloco_na_frente = cache_mapa.get(coordenada_do_ponto(nova_pos))
            if bloco_na_frente is None or bloco_na_frente == 'agua':
                jogador.position = nova_pos

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
sol = DirectionalLight()
sol.look_at(Vec3(1, -1, 1))

mouse.locked = False
mouse.visible = True

app.run()
