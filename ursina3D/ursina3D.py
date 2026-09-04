from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
import math
import os
import json

app = Ursina()
window.fps_counter.enabled = True

# 0. TENTA CARREGAR A MÚSICA NATIVAMENTE
try:
    musica_fundo = Audio('ex021.mp3', loop=True, autoplay=True, volume=0.5)
except Exception:
    pass

# 1. CONFIGURAÇÕES DO MUNDO
TAMANHO_CHUNK = 8
ALTURA_MAXIMA = 10
DISTANCIA_VISAO = 3

cache_mapa = {}
chunks_entidades = {}
jogo_iniciado = False

TEXTURAS_BLOCOS = {
    'grama': 'grama.png' if os.path.exists('texturas/grama.png') else 'white_cube',
    'terra': 'terra.png' if os.path.exists('texturas/terra.png') else 'white_cube',
    'pedra': 'pedra.png' if os.path.exists('texturas/pedra.png') else 'white_cube',
    'bronze': 'bronze.png' if os.path.exists('texturas/bronze.png') else 'white_cube',
    'prata': 'prata.png' if os.path.exists('texturas/prata.png') else 'white_cube',
    'ouro': 'ouro.png' if os.path.exists('texturas/ouro.png') else 'white_cube'
}

ARQUIVO_SAVE = 'mundo_save.json'

# Criamos o jogador aqui no topo desativado
jogador = FirstPersonController(enabled=False)


# 2. FUNÇÕES DE FLUXO DO JOGO
def iniciar_novo_mundo():
    """ Inicia um mundo totalmente novo do zero """
    global jogo_iniciado
    jogo_iniciado = True  # Ativa o loop ANTES para o gerador funcionar

    menu_inicial.enabled = False
    cache_mapa.clear()

    # Ativa e posiciona o jogador no alto
    jogador.enabled = True
    jogador.x, jogador.y, jogador.z = 4, 25, 4

    # Prende o mouse para começar a jogar
    mouse.locked = True
    mouse.visible = False

    # Força a geração imediata do mapa ao redor
    gerenciar_chunks_visiveis()


def iniciar_mundo_carregado():
    """ Inicia o jogo carregando o save do arquivo JSON """
    global cache_mapa, jogo_iniciado
    if not os.path.exists(ARQUIVO_SAVE):
        print("Nenhum arquivo de save encontrado!")
        return

    jogo_iniciado = True
    menu_inicial.enabled = False

    jogador.enabled = True
    jogador.x, jogador.y, jogador.z = 4, 25, 4
    mouse.locked = True
    mouse.visible = False

    with open(ARQUIVO_SAVE, 'r') as f:
        dados_carregados = json.load(f)

    cache_mapa.clear()
    for chave_string, tipo in dados_carregados.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    gerenciar_chunks_visiveis()


def salvar_mundo():
    dados_para_salvar = {}
    for pos, tipo in cache_mapa.items():
        chave_string = f"{pos[0]},{pos[1]},{pos[2]}"
        dados_para_salvar[chave_string] = tipo

    with open(ARQUIVO_SAVE, 'w') as f:
        json.dump(dados_para_salvar, f)

    alternar_menu_pausa()


def carregar_mundo_pausa():
    global cache_mapa
    if not os.path.exists(ARQUIVO_SAVE):
        return
    with open(ARQUIVO_SAVE, 'r') as f:
        dados_carregados = json.load(f)
    cache_mapa.clear()
    for chave_string, tipo in dados_carregados.items():
        coordenadas = chave_string.split(',')
        if len(coordenadas) == 3:
            x, y, z = int(coordenadas[0]), int(coordenadas[1]), int(coordenadas[2])
            cache_mapa[(x, y, z)] = tipo

    for cx, cz in list(chunks_entidades.keys()):
        for sub_malha in chunks_entidades[(cx, cz)]:
            destroy(sub_malha)
        del chunks_entidades[(cx, cz)]
    gerenciar_chunks_visiveis()
    alternar_menu_pausa()


# 3. GERAÇÃO MATEMÁTICA DO TERRENO
def gerar_dados_relevo(cx, cz):
    for x in range(cx * TAMANHO_CHUNK, (cx + 1) * TAMANHO_CHUNK):
        for z in range(cz * TAMANHO_CHUNK, (cz + 1) * TAMANHO_CHUNK):
            altura_calculada = int((math.sin(x / 4) + math.cos(z / 4)) * 2.5)
            for y in range(altura_calculada - 4, altura_calculada + 1):
                pos = (x, y, z)
                if pos not in cache_mapa:
                    if y == altura_calculada:
                        cache_mapa[pos] = 'grama'
                    elif y >= altura_calculada - 2:
                        cache_mapa[pos] = 'terra'
                    elif y == altura_calculada - 3:
                        cache_mapa[pos] = 'pedra'
                    else:
                        cache_mapa[pos] = 'gold'


# 4. SISTEMA DE RE-MESCLAGEM INDEPENDENTE POR TEXTURA
def atualizar_malha_chunk(cx, cz):
    global chunks_entidades
    if (cx, cz) in chunks_entidades:
        for sub_malha in chunks_entidades[(cx, cz)]:
            sub_malha.collider = None
            destroy(sub_malha)
        del chunks_entidades[(cx, cz)]

    gerar_dados_relevo(cx, cz)
    sub_malhas_do_chunk = []

    for tipo_alvo, arquivo_textura in TEXTURAS_BLOCOS.items():
        conteiner_tipo = Entity(parent=scene)
        blocos_desse_tipo = 0

        for x in range(cx * TAMANHO_CHUNK, (cx + 1) * TAMANHO_CHUNK):
            for z in range(cz * TAMANHO_CHUNK, (cz + 1) * TAMANHO_CHUNK):
                for y in range(-ALTURA_MAXIMA, ALTURA_MAXIMA):
                    pos = (x, y, z)
                    if cache_mapa.get(pos) == tipo_alvo:
                        Entity(parent=conteiner_tipo, model='cube', position=pos, color=color.white)
                        blocos_desse_tipo += 1

        if blocos_desse_tipo > 0:
            conteiner_tipo.combine(auto_destroy=True)
            conteiner_tipo.texture = arquivo_textura
            conteiner_tipo.collider = 'mesh'
            sub_malhas_do_chunk.append(conteiner_tipo)
        else:
            destroy(conteiner_tipo)

    if sub_malhas_do_chunk:
        chunks_entidades[(cx, cz)] = sub_malhas_do_chunk


# 5. CARREGAMENTO DINÂMICO DE CHUNKS
def gerenciar_chunks_visiveis():
    chunk_player_x = int(jogador.x // TAMANHO_CHUNK)
    chunk_player_z = int(jogador.z // TAMANHO_CHUNK)

    chunks_necessarios = set()
    for cx in range(chunk_player_x - DISTANCIA_VISAO, chunk_player_x + DISTANCIA_VISAO + 1):
        for cz in range(chunk_player_z - DISTANCIA_VISAO, chunk_player_z + DISTANCIA_VISAO + 1):
            chunks_necessarios.add((cx, cz))

    for cx, cz in chunks_necessarios:
        if (cx, cz) not in chunks_entidades:
            atualizar_malha_chunk(cx, cz)

    chunks_para_remover = [c for c in chunks_entidades if c not in chunks_necessarios]
    for c in chunks_para_remover:
        for sub_malha in chunks_entidades[c]:
            destroy(sub_malha)
        del chunks_entidades[c]


# 6. RELAÇÃO DE INTERFACES
# --- MENU INICIAL ---
menu_inicial = Entity(parent=camera.ui, enabled=True)
fundo_inicial = Entity(parent=menu_inicial, model='quad', scale=(2, 2), color=color.dark_gray, z=2)
titulo_jogo = Text(parent=menu_inicial, text='JEBAS-3D', scale=3, position=(-0.15, 0.3), color=color.gold)

btn_novo = Button(parent=menu_inicial, text='NOVO MUNDO', color=color.azure, scale=(0.4, 0.08), position=(0, 0.05),
                  on_click=iniciar_novo_mundo)
btn_carregar = Button(parent=menu_inicial, text='CARREGAR MUNDO', color=color.orange, scale=(0.4, 0.08),
                      position=(0, -0.07), on_click=iniciar_mundo_carregado)
btn_sair_ini = Button(parent=menu_inicial, text='SAIR', color=color.red, scale=(0.4, 0.08), position=(0, -0.19),
                      on_click=application.quit)

# --- MENU DE PAUSA (ESC) ---
menu_pausa = Entity(parent=camera.ui, enabled=False)
fundo_pausa = Entity(parent=menu_pausa, model='quad', scale=(2, 2), color=color.Color(0, 0, 0, 0.7), z=1)

botao_salvar = Button(parent=menu_pausa, text='SALVAR MUNDO', color=color.azure, scale=(0.4, 0.08), position=(0, 0.1),
                      on_click=salvar_mundo)
botao_carregar = Button(parent=menu_pausa, text='RECARREGAR SAVE', color=color.orange, scale=(0.4, 0.08),
                        position=(0, -0.02), on_click=carregar_mundo_pausa)
botao_fechar = Button(parent=menu_pausa, text='SAIR DO JOGO', color=color.red, scale=(0.4, 0.08), position=(0, -0.14),
                      on_click=application.quit)


def alternar_menu_pausa():
    menu_pausa.enabled = not menu_pausa.enabled
    if menu_pausa.enabled:
        jogador.cursor.enabled = False
        mouse.locked = False
        mouse.visible = True
    else:
        jogador.cursor.enabled = True
        mouse.locked = True
        mouse.visible = False


# 7. GERENCIAMENTO GLOBAL DE ENTRADAS
bloco_selecionado = 'grama'
indicador = Text(text=f'Bloco: {bloco_selecionado.upper()}', position=(-0.80, 0.42), scale=2, color=color.yellow)


def input(key):
    global bloco_selecionado

    if not jogo_iniciado:
        return

    if key == 'escape':
        alternar_menu_pausa()
        return

    if menu_pausa.enabled:
        return

    if key in ['1', '2', '3', '4', '5', '6']:
        mapeamento = {'1': 'grama', '2': 'terra', '3': 'pedra', '4': 'bronze', '5': 'prata', '6': 'ouro'}
        bloco_selecionado = mapeamento[key]
        indicador.text = f'Bloco: {bloco_selecionado.upper()}'

    if mouse.hovered_entity and key in ['left mouse down', 'right mouse down']:
        ponto_colisao = mouse.world_point
        normal_face = mouse.normal

        if key == 'left mouse down':
            pos_alvo = ponto_colisao - normal_face * 0.5
            alvo_x, alvo_y, alvo_z = math.floor(pos_alvo.x + 0.5), math.floor(pos_alvo.y + 0.5), math.floor(
                pos_alvo.z + 0.5)

            coordenada_bloco = (alvo_x, alvo_y, alvo_z)
            if cache_mapa.get(coordenada_bloco) is not None:
                cache_mapa[coordenada_bloco] = None
                cx = alvo_x // TAMANHO_CHUNK
                cz = alvo_z // TAMANHO_CHUNK
                atualizar_malha_chunk(cx, cz)

        elif key == 'right mouse down':
            pos_alvo = ponto_colisao + normal_face * 0.5
            alvo_x, alvo_y, alvo_z = math.floor(pos_alvo.x + 0.5), math.floor(pos_alvo.y + 0.5), math.floor(
                pos_alvo.z + 0.5)

            coordenada_bloco = (alvo_x, alvo_y, alvo_z)
            cache_mapa[coordenada_bloco] = bloco_selecionado
            cx = alvo_x // TAMANHO_CHUNK
            cz = alvo_z // TAMANHO_CHUNK
            atualizar_malha_chunk(cx, cz)


# 8. LAÇO DE ATUALIZAÇÃO POR FRAME
_temporizador = 0


def update():
    global _temporizador

    if not jogo_iniciado:
        return

    if menu_pausa.enabled:
        jogador.speed = 0
        jogador.jump_height = 0
        return
    else:
        jogador.speed = 5
        jogador.jump_height = 1

    _temporizador += time.dt
    if _temporizador > 0.3:
        gerenciar_chunks_visiveis()
        _temporizador = 0

    if jogador.y < -30:
        jogador.x, jogador.y, jogador.z = 4, 25, 4


app.run()
