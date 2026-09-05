from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
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
DISTANCIA_VISAO = 3
cache_mapa = {}
chunks_entidades = {}
chunks_gerados = set()
# Chunks são construídos em pequenos lotes para não travar ao caminhar.
chunks_pendentes = set()

jogo_iniciado = False

TEXTURAS_BLOCOS = {
    'grama': 'texturas/grama.png' if os.path.exists('texturas/grama.png') else 'white_cube',
    'terra': 'texturas/terra.png' if os.path.exists('texturas/terra.png') else 'white_cube',
    'pedra': 'texturas/pedra.png' if os.path.exists('texturas/pedra.png') else 'white_cube',
    'bronze': 'texturas/bronze.png' if os.path.exists('texturas/bronze.png') else 'white_cube',
    'prata': 'texturas/prata.png' if os.path.exists('texturas/prata.png') else 'white_cube',
    'ouro': 'texturas/ouro.png' if os.path.exists('texturas/ouro.png') else 'white_cube',
    'madeira': 'texturas/madeira.png' if os.path.exists('texturas/madeira.png') else 'white_cube',
    'folhas': 'texturas/folhas.png' if os.path.exists('texturas/folhas.png') else 'white_cube'
}

ARQUIVO_SAVE = 'mundo_save.json'
ORDEM_BLOCOS = ['grama', 'terra', 'pedra', 'bronze', 'prata', 'ouro', 'madeira', 'folhas']
bloco_selecionado = 'grama'
indice_selecionado = 0
jogador = FirstPersonController(enabled=False)
# Um pulo extra fica disponível a cada vez que o jogador toca o chão.
pulos_extras = 1

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

# --- CRIAÇÃO DO MODELO DO BRAÇO/MÃO 3D ---
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


def mostrar_carregamento_novo():
    menu_inicial.enabled = False
    tela_carregamento.enabled = True
    invoke(iniciar_novo_mundo, delay=0.05)


def iniciar_novo_mundo():
    global jogo_iniciado
    jogo_iniciado = True
    cache_mapa.clear()
    resetar_entidades_mundo()
    jogador.enabled = True
    jogador.x, jogador.y, jogador.z = 4, 25, 4
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


def iniciar_mundo_carregado():
    global cache_mapa, jogo_iniciado
    jogo_iniciado = True
    jogador.enabled = True
    jogador.x, jogador.y, jogador.z = 4, 25, 4
    mouse.locked = True
    mouse.visible = False

    with open(ARQUIVO_SAVE, 'r') as f:
        dados_carregados = json.load(f)

    cache_mapa.clear()
    resetar_entidades_mundo()
    for chave_string, tipo in dados_carregados.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    gerenciar_chunks_visiveis()
    tela_carregamento.enabled = False
    hotbar_conteiner.enabled = True
    mao_jogador.enabled = True


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
    for chave_string, tipo in dados_carregados.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    resetar_entidades_mundo()
    gerenciar_chunks_visiveis()
    tela_carregamento.enabled = False
    hotbar_conteiner.enabled = True
    mao_jogador.enabled = True
    jogador.cursor.enabled = True
    mouse.locked = True
    mouse.visible = False


def voltar_ao_menu_inicial():
    global jogo_iniciado
    jogo_iniciado = False
    menu_pausa.enabled = False
    hotbar_conteiner.enabled = False
    mao_jogador.enabled = False
    jogador.enabled = False

    resetar_entidades_mundo()
    cache_mapa.clear()

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
def gerar_dados_relevo(cx, cz):
    # Se este chunk já teve seu relevo inicial gerado, não calcula de novo (evita recriar blocos cavados)
    if (cx, cz) in chunks_gerados:
        return

    random.seed(f"{cx}_{cz}_jebas3d")
    possiveis_locais_arvores = []

    for x in range(cx * TAMANHO_CHUNK, (cx + 1) * TAMANHO_CHUNK):
        for z in range(cz * TAMANHO_CHUNK, (cz + 1) * TAMANHO_CHUNK):
            altura_calculada = int((math.sin(x / 4) + math.cos(z / 4)) * 2.5)
            fundo_do_mundo = -12

            for y in range(fundo_do_mundo, altura_calculada + 1):
                pos = (x, y, z)
                if pos not in cache_mapa:
                    if y == altura_calculada:
                        cache_mapa[pos] = 'grama'
                        possiveis_locais_arvores.append((x, y, z))
                    elif y >= altura_calculada - 2:
                        cache_mapa[pos] = 'terra'
                    elif y == altura_calculada - 3:
                        cache_mapa[pos] = 'pedra'
                    elif y == altura_calculada - 4:
                        cache_mapa[pos] = 'bronze'
                    elif y == altura_calculada - 5:
                        cache_mapa[pos] = 'prata'
                    else:
                        cache_mapa[pos] = 'ouro'

    if possiveis_locais_arvores and random.random() < 0.3:
        local = random.choice(possiveis_locais_arvores)
        gerar_arvore_no_cache(*local)

    # Registra que este chunk já foi populado matematicamente
    chunks_gerados.add((cx, cz))


# --- 5. MALHAS DE FACES VISÍVEIS ---
# Blocos ocultos pelos seis vizinhos não viram geometria. Também evitamos criar
# milhares de Entity temporárias e chamar combine() para cada material.
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
        sub_malha.collider = None
        destroy(sub_malha)
    chunks_pendentes.discard((cx, cz))


def solicitar_atualizacao_chunk(cx, cz):
    """Agrupa pedidos repetidos de reconstrução no mesmo chunk."""
    chunks_pendentes.add((cx, cz))


def atualizar_malha_chunk(cx, cz):
    remover_chunk(cx, cz)
    gerar_dados_relevo(cx, cz)

    # Dados dos vizinhos evitam faces desenhadas em dobro nas bordas.
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            gerar_dados_relevo(cx + dx, cz + dz)

    dados_malha = {tipo: {'vertices': [], 'triangles': [], 'uvs': []}
                   for tipo in TEXTURAS_BLOCOS}
    x_min = cx * TAMANHO_CHUNK
    z_min = cz * TAMANHO_CHUNK

    # Apenas 3.840 consultas no dicionário por chunk, em vez de varrer o mapa
    # inteiro uma vez para cada chunk e para cada material.
    for x in range(x_min, x_min + TAMANHO_CHUNK):
        for z in range(z_min, z_min + TAMANHO_CHUNK):
            for y in range(-ALTURA_MAXIMA, ALTURA_MAXIMA):
                tipo = cache_mapa.get((x, y, z))
                if tipo is None:
                    continue
                dados = dados_malha[tipo]
                for (dx, dy, dz), vertices_face in FACES_CUBO:
                    if cache_mapa.get((x + dx, y + dy, z + dz)) is not None:
                        continue
                    inicio = len(dados['vertices'])
                    dados['vertices'].extend(
                        (x + vx, y + vy, z + vz) for vx, vy, vz in vertices_face
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
        # As faces são geradas manualmente. Desenhar ambos os lados impede que
        # uma face seja invisível caso a câmera a observe pelo verso.
        entidade = Entity(parent=scene, model=malha, texture=TEXTURAS_BLOCOS[tipo],
                          collider='mesh', double_sided=True)
        sub_malhas_do_chunk.append(entidade)
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
    """Reconstrói também o vizinho quando a alteração toca a borda do chunk."""
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
    """Converte uma posição do mundo para a grade dos blocos."""
    return (
        math.floor(ponto.x + 0.5),
        math.floor(ponto.y),
        math.floor(ponto.z + 0.5),
    )


def bloco_mirado(distancia_maxima=6):
    """Raycast exato na grade de voxels, independente do collider da malha."""
    origem = camera.world_position
    direcao = camera.forward.normalized()
    celula = coordenada_do_ponto(origem)

    passo_x = 1 if direcao.x >= 0 else -1
    passo_y = 1 if direcao.y >= 0 else -1
    passo_z = 1 if direcao.z >= 0 else -1

    # Os blocos ocupam x/z de -0.5 a +0.5 e y de 0 a +1.
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

    # O trabalho pesado é feito pela fila, no máximo um chunk por frame.
    for cx, cz in chunks_necessarios:
        if (cx, cz) not in chunks_entidades:
            solicitar_atualizacao_chunk(cx, cz)

    # Remove chunks distantes para manter o consumo de memória RAM sempre baixo
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

# --- MENUS DE CONFIGURAÇÃO DE GRÁFICOS AVANÇADO ---
menu_opcoes = Entity(parent=camera.ui, enabled=False)
fundo_opcoes = Entity(parent=menu_opcoes, model='quad', scale=(2, 2), color=color.dark_gray, z=1)
titulo_opcoes = Text(parent=menu_opcoes, text='OPÇÕES DE VÍDEO', scale=2.5, position=(-0.25, 0.4), color=color.white)


# Funções de alteração gráfica
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
    # A Ursina já força o redimensionamento centralizado nativamente


# Seção 1: Distância de Visão
texto_distancia = Text(parent=menu_opcoes, text=f'Distancia de Visao: {DISTANCIA_VISAO} Chunks', position=(-0.4, 0.25),
                       scale=1.5)
btn_vis_curta = Button(parent=menu_opcoes, text='CURTA (2)', scale=(0.18, 0.05), position=(-0.3, 0.17),
                       on_click=lambda: mudar_distancia_visao(2))
btn_vis_media = Button(parent=menu_opcoes, text='MÉDIA (3)', scale=(0.18, 0.05), position=(-0.1, 0.17),
                       on_click=lambda: mudar_distancia_visao(3))
btn_vis_longa = Button(parent=menu_opcoes, text='LONGA (4)', scale=(0.18, 0.05), position=(0.1, 0.17),
                       on_click=lambda: mudar_distancia_visao(4))

# Seção 2: Modo de Exibição da Janela
texto_modo_tela = Text(parent=menu_opcoes, text='Modo de Janela:', position=(-0.4, 0.05), scale=1.5)
btn_modo_janela = Button(parent=menu_opcoes, text='JANELA', scale=(0.18, 0.05), position=(-0.3, -0.03),
                         on_click=lambda: configurar_modo_tela('janela'))
btn_modo_sem_borda = Button(parent=menu_opcoes, text='SEM BORDAS', scale=(0.18, 0.05), position=(-0.1, -0.03),
                            on_click=lambda: configurar_modo_tela('sem_bordas'))
btn_modo_fullscreen = Button(parent=menu_opcoes, text='TELA CHEIA', scale=(0.18, 0.05), position=(0.1, -0.03),
                             on_click=lambda: configurar_modo_tela('tela_cheia'))

# Seção 3: Resolução da Tela
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

# Botões do Menu Inicial
btn_novo = Button(parent=menu_inicial, text='NOVO MUNDO', color=color.azure, scale=(0.4, 0.07), position=(0, 0.08),
                  on_click=mostrar_carregamento_novo)
btn_carregar = Button(parent=menu_inicial, text='CARREGAR MUNDO', color=color.orange, scale=(0.4, 0.07),
                      position=(0, 0.0), on_click=mostrar_carregamento_salvo)
btn_opcoes_ini = Button(parent=menu_inicial, text='OPÇÕES GRÁFICAS', color=color.violet, scale=(0.4, 0.07),
                        position=(0, -0.08), on_click=abrir_opcoes)
btn_sair_ini = Button(parent=menu_inicial, text='SAIR', color=color.red, scale=(0.4, 0.07), position=(0, -0.16),
                      on_click=application.quit)

# Menu de Pausa Configurado
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
    global bloco_selecionado, indice_selecionado, pulos_extras

    # Se o menu de opções gráficas estiver aberto, ESC apenas fecha ele
    if menu_opcoes.enabled and key == 'escape':
        fechar_opcoes()
        return

    # Se o jogo ainda não começou (está na tela de título), ignora o resto dos comandos
    if not jogo_iniciado:
        return

    # Se apertar ESC, ele simplesmente alterna o estado da pausa (abre ou fecha e volta pro jogo)
    if key == 'escape':
        alternar_menu_pausa()
        return

    # Se a pausa estiver aberta na tela, bloqueia os comandos de quebrar/colocar blocos abaixo
    if menu_pausa.enabled:
        return

    # O FirstPersonController cuida do primeiro pulo no chão. No ar, este
    # segundo pulo usa a mesma animação e só pode acontecer uma vez.
    if key == 'space' and not jogador.grounded and pulos_extras > 0:
        jogador.animate_y(jogador.y + jogador.jump_height, duration=.35, curve=curve.out_expo)
        pulos_extras -= 1
        return

    # --- SELEÇÃO DA HOTBAR ---
    if key in ['1', '2', '3', '4', '5', '6', '7', '8']:
        novo_index = int(key) - 1
        atualizar_selecao_hotbar(novo_index)

    if key == 'scroll up':
        novo_index = (indice_selecionado + 1) % len(ORDEM_BLOCOS)
        atualizar_selecao_hotbar(novo_index)
    if key == 'scroll down':
        novo_index = (indice_selecionado - 1) % len(ORDEM_BLOCOS)
        atualizar_selecao_hotbar(novo_index)

    # --- ANIMAÇÃO DE SOCO/MINERAÇÃO COM O CLIQUE ---
    if key in ['left mouse down', 'right mouse down']:
        mao_jogador.position = Vec3(0.5, -0.4, 0.9)
        mao_jogador.rotation = Vec3(25, -10, 15)
        mao_jogador.animate_position(Vec3(0.6, -0.5, 1.1), duration=0.1, curve=curve.linear)
        mao_jogador.animate_rotation(Vec3(15, -20, 5), duration=0.1, curve=curve.linear)

    # --- LOGICA DE QUEBRAR E COLOCAR BLOCOS ---
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
    global _temporizador, pulos_extras

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
        jogador.speed = 0
        jogador.jump_height = 0
        return
    else:
        jogador.speed = 5
        jogador.jump_height = 2
        if jogador.grounded:
            pulos_extras = 1

    # Mantém o carregamento suave mesmo ao entrar numa área ainda não criada.
    processar_fila_chunks(limite=1)

    _temporizador += time.dt
    if _temporizador > 0.3:
        gerenciar_chunks_visiveis()
        _temporizador = 0

    if jogador.y < -30:
        jogador.x, jogador.y, jogador.z = 4, 25, 4


# --- 10. INICIALIZAÇÃO DO JOGO ---
ceu = Sky()
sol = DirectionalLight()
sol.look_at(Vec3(1, -1, 1))

mouse.locked = False
mouse.visible = True

app.run()
