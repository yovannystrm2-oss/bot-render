from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import asyncio
import os
import threading
import uuid
import time
import re
import requests
from datetime import datetime
from queue import Queue
from werkzeug.utils import secure_filename

# ============================================
# CONFIGURACIÓN
# ============================================
api_id = 33774512
api_hash = '72af30fe5dd18997fc50a0a53e544f0c'
CHAT_ID = -1003732799535
CHAT_META = -1003771916049

SESSION_STR = os.environ.get("TELETHON_SESSION", "")

COMANDO_BIOMETRICO = '/facial'
COMANDO_FACIAL2 = '/facial2'
COMANDO_METAPLACA = '/metaplaca'
COMANDO_META = '/meta'
COMANDO_NM = '/nm'
COMANDO_SENTINEL = '/sentinel'
COMANDO_DMINSA = '/dminsa'

DNI_PROHIBIDO = '77662668'

CARPETA_DESCARGAS = 'descargas'
CARPETA_UPLOADS = 'uploads'
os.makedirs(CARPETA_DESCARGAS, exist_ok=True)
os.makedirs(CARPETA_UPLOADS, exist_ok=True)

client = TelegramClient(StringSession(SESSION_STR), api_id, api_hash)

solicitudes = {}
solicitudes_facial2 = {}
solicitudes_meta = {}
solicitudes_nm = {}
solicitudes_sentinel = {}
solicitudes_metaplaca = {}
solicitudes_dminsa = {}

cola_envios = Queue()
cola_facial2 = Queue()
cola_meta = Queue()
cola_nm = Queue()
cola_sentinel = Queue()
cola_metaplaca = Queue()
cola_dminsa = Queue()

resultados_envios = {}
resultados_facial2 = {}
resultados_meta = {}
resultados_nm = {}
resultados_sentinel = {}
resultados_metaplaca = {}
resultados_dminsa = {}

MI_ID = None

_SC = str.maketrans({
    'ʀ': 'r', 'ᴇ': 'e', 'ᴜ': 'u', 'ᴛ': 't', 'ᴀ': 'a', 'ᴅ': 'd', 'ᴏ': 'o', 'ɪ': 'i',
    'ɴ': 'n', 'ꜰ': 'f', 'ᴄ': 'c', 'ʟ': 'l', 'ᴍ': 'm', 'ᴘ': 'p', 'ᴡ': 'w', 'ʏ': 'y',
    'ᴢ': 'z', 'ɢ': 'g', 'ʙ': 'b', 'ᴋ': 'k', 'ᴊ': 'j', 'ᴠ': 'v', 'ʜ': 'h', 'ꜱ': 's',
    'ǫ': 'o',
})

def normalizar(texto):
    return (texto or '').translate(_SC).lower()

def es_sin_resultados(texto):
    n = normalizar(texto)
    return 'sin resultado' in n or 'otra foto' in n or 'sin coincidencia' in n or 'no se encontro' in n

def es_pdf(event):
    if not event.document: return False
    mime = getattr(event.document, 'mime_type', '') or ''
    return 'pdf' in mime.lower()

def marcar_completado(sol):
    sol['completado'] = True
    sol['fecha_completado'] = datetime.now().isoformat()

def extraer_dni_de_texto(texto):
    if not texto: return None
    t = texto.translate(_SC)
    m = re.search(r'dni\s*[·:：\-]?\s*(\d{6,9})', t, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'\b(\d{8})\b', t)
    if m: return m.group(1)
    return None

# ============================================
# PARSER /nm
# ============================================
def parsear_nm(texto):
    texto = (texto or '').replace('\\n', '\n')
    personas = []
    actual = None
    for raw in texto.split('\n'):
        ln = raw.strip()
        if not ln: continue
        if ln.startswith('**#SAKUMADATA') or ln.startswith('#SAKUMADATA'): continue
        if ln.startswith('➻'): continue
        if re.match(r'^ᴛᴏᴛᴀʟ\s*[:：]', ln, re.IGNORECASE): continue
        if 'ᴄʀᴇ́ᴅɪᴛᴏs' in ln or 'ᴄʀᴇᴅɪᴛᴏs' in ln: continue
        if 'ᴜsᴜᴀʀɪᴏ' in ln: continue
        if re.fullmatch(r'[-=_]{3,}', ln): continue
        if re.fullmatch(r'ʙᴜsǫᴜᴇᴅᴀ.*', ln): continue

        m_bloque = re.fullmatch(r'\[(\d+)\]', ln)
        if m_bloque:
            if actual: personas.append(actual)
            actual = {'dni': '', 'campos': []}
            continue

        m_dni_solo = re.fullmatch(r'[\*\`_\s]*(\d{8})[\*\`_\s]*', ln)
        if m_dni_solo:
            if actual and (actual.get('dni') or actual.get('campos')): personas.append(actual)
            actual = {'dni': m_dni_solo.group(1), 'campos': []}
            continue

        m_campo_dosp = re.match(r'^([^\s:：]+)\s*[:：]\s*(.+)$', ln)
        if m_campo_dosp and actual is not None:
            clave_raw = m_campo_dosp.group(1).strip()
            valor = m_campo_dosp.group(2).strip().strip('`*_ ')
            clave_norm = normalizar(clave_raw).strip().rstrip('.').strip()
            if clave_norm == 'dni' or 'dni' in clave_norm:
                actual['dni'] = re.sub(r'[^\d]', '', valor)
                continue
            actual['campos'].append(f"{clave_raw} : {valor}")
            continue

        if actual is not None:
            limpio = ln.strip()
            limpio = re.sub(r'^[\*\`_]+|[\*\`_]+$', '', limpio).strip()
            if limpio: actual['campos'].append(limpio)

    if actual: personas.append(actual)
    personas = [p for p in personas if p.get('dni') and p['dni'].isdigit() and len(p['dni']) == 8]
    return personas

# ============================================
# HANDLERS TELEGRAM
# ============================================
@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_facial(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    n = normalizar(texto)
    if 'reniec' in n or 'bsqueda' in n or 'busqueda' in n or 'ʙᴜsǫᴜᴇᴅᴀ' in texto: return

    sol = None
    tipo = None

    if event.reply_to_msg_id:
        if event.reply_to_msg_id in solicitudes_facial2:
            sol = solicitudes_facial2[event.reply_to_msg_id]; tipo = 'facial2'
        elif event.reply_to_msg_id in solicitudes:
            sol = solicitudes[event.reply_to_msg_id]; tipo = 'facial'

    if sol is None and es_sin_resultados(texto):
        pend2 = [x for x in solicitudes_facial2.values() if not x['completado']]
        pend1 = [x for x in solicitudes.values() if x['tipo'] == 'biometrico' and not x['completado']]
        if pend2 and (not pend1 or max(pend2, key=lambda x: x['fecha'])['fecha'] > max(pend1, key=lambda x: x['fecha'])['fecha']):
            sol = max(pend2, key=lambda x: x['fecha']); tipo = 'facial2'
        elif pend1:
            sol = max(pend1, key=lambda x: x['fecha']); tipo = 'facial'

    if sol is None and es_pdf(event):
        pend2 = [x for x in solicitudes_facial2.values() if not x['completado']]
        pend1 = [x for x in solicitudes.values() if x['tipo'] == 'biometrico' and not x['completado']]
        if pend2 and (not pend1 or max(pend2, key=lambda x: x['fecha'])['fecha'] > max(pend1, key=lambda x: x['fecha'])['fecha']):
            sol = max(pend2, key=lambda x: x['fecha']); tipo = 'facial2'
        elif pend1:
            sol = max(pend1, key=lambda x: x['fecha']); tipo = 'facial'

    if sol is None: return

    print(f"⚡ Respuesta {tipo} recibida")

    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass

    if es_sin_resultados(texto):
        sol['sin_resultados'] = True
        marcar_completado(sol)
        return

    if tipo == 'facial2':
        if not es_pdf(event): return
        try:
            ruta = await event.download_media(file=CARPETA_DESCARGAS)
            sol['archivo'] = os.path.basename(ruta)
            sol['tipo_archivo'] = 'PDF'
        except Exception as e:
            sol['error'] = str(e)
        marcar_completado(sol)
        return

    dni = extraer_dni_de_texto(texto)
    if dni and not sol.get('dni'):
        if dni == DNI_PROHIBIDO:
            sol['dni'] = dni; sol['texto'] = texto; sol['dni_bloqueado'] = True
        else:
            sol['dni'] = dni; sol['texto'] = texto
            request_id = str(uuid.uuid4())
            cola_meta.put({'request_id': request_id, 'dni': dni})
            inicio = time.time()
            while time.time() - inicio < 15:
                if request_id in resultados_meta:
                    r = resultados_meta.pop(request_id)
                    if r['ok']:
                        mid = r['message_id']
                        solicitudes_meta[mid] = {
                            'tipo': 'meta', 'dni': dni, 'completado': False,
                            'archivo': None, 'tipo_archivo': None, 'sin_resultados': False,
                            'fecha': datetime.now().isoformat(),
                            'mensaje_original_id': mid
                        }
                        sol['meta_message_id'] = mid
                    break
                await asyncio.sleep(0.2)

    if es_pdf(event):
        try:
            ruta = await event.download_media(file=CARPETA_DESCARGAS)
            sol['archivo_facial'] = os.path.basename(ruta)
        except Exception as e:
            sol['error'] = str(e)

@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_dminsa(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    sol = None

    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_dminsa:
        sol = solicitudes_dminsa[event.reply_to_msg_id]

    if sol is None:
        m = re.search(r'\b(\d{8})\b', texto)
        if m:
            dni = m.group(1)
            pendientes = [x for x in solicitudes_dminsa.values() if not x['completado'] and x.get('dni') == dni]
            if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])

    if sol is None and es_pdf(event):
        pendientes = [x for x in solicitudes_dminsa.values() if not x['completado']]
        if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])

    if sol is None: return
    print(f"⚡ Respuesta dminsa recibida (DNI: {sol.get('dni')})")

    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass

    if texto.strip(): sol['texto_respuesta'] = texto
    
    if es_pdf(event):
        try:
            ruta = await event.download_media(file=CARPETA_DESCARGAS)
            sol['archivo'] = os.path.basename(ruta)
            sol['tipo_archivo'] = 'PDF'
        except Exception as e:
            sol['error'] = str(e)
        marcar_completado(sol)

@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_metaplaca(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_metaplaca:
        sol = solicitudes_metaplaca[event.reply_to_msg_id]
    if sol is None:
        m = re.search(r'\b([A-Z0-9]{3}[-\s]?[A-Z0-9]{3})\b', texto.upper())
        if m:
            placa_detectada = m.group(1).replace('-', '').replace(' ', '')
            pendientes = [x for x in solicitudes_metaplaca.values() if not x['completado'] and x.get('placa') == placa_detectada]
            if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pendientes = [x for x in solicitudes_metaplaca.values() if not x['completado']]
        if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])
    if sol is None: return

    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass

    if es_sin_resultados(texto):
        sol['sin_resultados'] = True
        marcar_completado(sol)
        return

    if not es_pdf(event): return
    try:
        ruta = await event.download_media(file=CARPETA_DESCARGAS)
        sol['archivo'] = os.path.basename(ruta)
        sol['tipo_archivo'] = 'PDF'
    except Exception as e: sol['error'] = str(e)
    marcar_completado(sol)

@client.on(events.MessageEdited(chats=CHAT_ID))
@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_nm(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_nm:
        sol = solicitudes_nm[event.reply_to_msg_id]
    if sol is None:
        n = normalizar(texto)
        es_cabecera = ('reniec' in n) or ('bsqueda' in n) or ('busqueda' in n) or ('ʙᴜsǫᴜᴇᴅᴀ' in texto)
        es_txt = bool(event.document) and ('text' in (event.document.mime_type or '') or (event.file and event.file.name and event.file.name.lower().endswith('.txt')))
        if es_cabecera or es_txt or es_sin_resultados(texto):
            pendientes = [x for x in solicitudes_nm.values() if not x.get('completado')]
            if pendientes:
                ahora = time.time()
                recientes = []
                for x in pendientes:
                    try:
                        t = datetime.fromisoformat(x['fecha']).timestamp()
                        if ahora - t <= 120: recientes.append(x)
                    except Exception: pass
                if recientes: sol = max(recientes, key=lambda x: x['fecha'])
    if sol is None or sol.get('completado'): return

    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass

    if es_sin_resultados(texto):
        sol['sin_resultados'] = True
        sol['completado'] = True
        sol['fecha_completado'] = datetime.now().isoformat()
        return

    contenido = texto
    if event.document:
        nombre_archivo = (event.file.name or '').lower() if event.file else ''
        mime = event.document.mime_type or ''
        es_txt = ('text' in mime) or nombre_archivo.endswith('.txt')
        if es_txt:
            try:
                ruta = await event.download_media(file=CARPETA_DESCARGAS)
                nombre_unico = f"nm_{event.id}.txt"
                ruta_unica = os.path.join(CARPETA_DESCARGAS, nombre_unico)
                try: os.rename(ruta, ruta_unica)
                except Exception: ruta_unica = ruta; nombre_unico = os.path.basename(ruta)
                sol['txt_archivo'] = nombre_unico
                with open(ruta_unica, 'r', encoding='utf-8', errors='ignore') as f: contenido = f.read()
            except Exception as e: return

    personas = parsear_nm(contenido)
    if not personas: return

    sol['resultados'] = personas
    sol['completado'] = True
    sol['fecha_completado'] = datetime.now().isoformat()

@client.on(events.NewMessage(chats=CHAT_META))
async def handler_meta(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_meta:
        sol = solicitudes_meta[event.reply_to_msg_id]
    if sol is None:
        dni_detectado = extraer_dni_de_texto(texto)
        if dni_detectado:
            pendientes = [x for x in solicitudes_meta.values() if not x['completado'] and x.get('dni') == dni_detectado]
            if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pendientes = [x for x in solicitudes_meta.values() if not x['completado']]
        if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])
    if sol is None: return

    try: await client.delete_messages(CHAT_META, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_META, [sol['mensaje_original_id']])
        except: pass

    if es_sin_resultados(texto):
        sol['sin_resultados'] = True
        marcar_completado(sol)
        return
    if not es_pdf(event): return
    try:
        ruta = await event.download_media(file=CARPETA_DESCARGAS)
        sol['archivo'] = os.path.basename(ruta)
        sol['tipo_archivo'] = 'PDF'
    except Exception as e: sol['error'] = str(e)
    marcar_completado(sol)

@client.on(events.NewMessage(chats=CHAT_META))
async def handler_sentinel(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_sentinel:
        sol = solicitudes_sentinel[event.reply_to_msg_id]
    if sol is None:
        dni_detectado = extraer_dni_de_texto(texto)
        if dni_detectado:
            pendientes = [x for x in solicitudes_sentinel.values() if not x['completado'] and x.get('dni') == dni_detectado]
            if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pendientes = [x for x in solicitudes_sentinel.values() if not x['completado']]
        if pendientes: sol = max(pendientes, key=lambda x: x['fecha'])
    if sol is None: return

    try: await client.delete_messages(CHAT_META, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_META, [sol['mensaje_original_id']])
        except: pass

    if es_sin_resultados(texto):
        sol['sin_resultados'] = True
        marcar_completado(sol)
        return
    if not es_pdf(event): return
    try:
        ruta = await event.download_media(file=CARPETA_DESCARGAS)
        sol['archivo'] = os.path.basename(ruta)
        sol['tipo_archivo'] = 'PDF'
    except Exception as e: sol['error'] = str(e)
    marcar_completado(sol)

# ============================================
# WORKERS
# ============================================
async def procesar_cola():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_envios.get)
            request_id = item['request_id']
            try:
                mensaje = await client.send_file(CHAT_ID, item['ruta_imagen'], caption=item['comando'])
                try: os.remove(item['ruta_imagen'])
                except: pass
                resultados_envios[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_envios[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

async def procesar_cola_facial2():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_facial2.get)
            request_id = item['request_id']
            try:
                mensaje = await client.send_file(CHAT_ID, item['ruta_imagen'], caption=item['comando'])
                try: os.remove(item['ruta_imagen'])
                except: pass
                resultados_facial2[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_facial2[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

async def procesar_cola_meta():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_meta.get)
            request_id = item['request_id']; dni = item['dni']
            if dni == DNI_PROHIBIDO:
                resultados_meta[request_id] = {'ok': False, 'error': 'DNI bloqueado'}; continue
            try:
                mensaje = await client.send_message(CHAT_META, f"{COMANDO_META} {dni}")
                resultados_meta[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_meta[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

async def procesar_cola_nm():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_nm.get)
            request_id = item['request_id']; query = item['query']
            try:
                mensaje = await client.send_message(CHAT_ID, f"{COMANDO_NM} {query}")
                resultados_nm[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_nm[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

async def procesar_cola_sentinel():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_sentinel.get)
            request_id = item['request_id']; dni = item['dni']
            if dni == DNI_PROHIBIDO:
                resultados_sentinel[request_id] = {'ok': False, 'error': 'DNI bloqueado'}; continue
            try:
                mensaje = await client.send_message(CHAT_META, f"{COMANDO_SENTINEL} {dni}")
                resultados_sentinel[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_sentinel[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

async def procesar_cola_metaplaca():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_metaplaca.get)
            request_id = item['request_id']; placa = item['placa']
            try:
                mensaje = await client.send_message(CHAT_ID, f"{COMANDO_METAPLACA} {placa}")
                resultados_metaplaca[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_metaplaca[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

async def procesar_cola_dminsa():
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola_dminsa.get)
            request_id = item['request_id']; comando = item['comando']
            try:
                mensaje = await client.send_message(CHAT_ID, comando)
                resultados_dminsa[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e:
                resultados_dminsa[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except Exception as e: await asyncio.sleep(1)

# ============================================
# LIMPIEZA
# ============================================
def limpiar_viejos():
    ahora = time.time()
    for store in (solicitudes, solicitudes_facial2, solicitudes_meta, solicitudes_nm, solicitudes_sentinel, solicitudes_metaplaca, solicitudes_dminsa):
        for k in list(store.keys()):
            try:
                f = datetime.fromisoformat(store[k]['fecha']).timestamp()
                if ahora - f > 3600: del store[k]
            except Exception: pass

# ============================================
# FLASK Y ENDPOINTS
# ============================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": "*"}})

INDEX_PATH = os.path.join(BASE_DIR, 'index.html')

@app.errorhandler(404)
def not_found(e): return jsonify({'error': 'Ruta no encontrada en el backend'}), 404

@app.errorhandler(500)
def server_error(e): return jsonify({'error': 'Error interno en el backend'}), 500

@app.route('/')
def index():
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f: return f.read()
    except FileNotFoundError: return "index.html no encontrado", 404

@app.route('/css/<path:nombre>')
def servir_css(nombre): return send_from_directory(os.path.join(BASE_DIR, 'css'), nombre)

@app.route('/js/<path:nombre>')
def servir_js(nombre): return send_from_directory(os.path.join(BASE_DIR, 'js'), nombre)

@app.route('/favicon.ico')
def favicon(): return '', 204

@app.route('/facial', methods=['POST'])
def pedir_biometrico():
    if 'imagen' not in request.files: return jsonify({'error': 'No se envió imagen'}), 400
    archivo = request.files['imagen']
    if archivo.filename == '': return jsonify({'error': 'Nombre de archivo vacío'}), 400
    nombre_unico = f"{uuid.uuid4()}_{secure_filename(archivo.filename)}"
    ruta_imagen = os.path.join(CARPETA_UPLOADS, nombre_unico)
    archivo.save(ruta_imagen)
    request_id = str(uuid.uuid4())
    cola_envios.put({'request_id': request_id, 'comando': COMANDO_BIOMETRICO, 'tipo': 'imagen', 'ruta_imagen': ruta_imagen})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_envios:
            resultado = resultados_envios.pop(request_id)
            if resultado['ok']:
                mensaje_id = resultado['message_id']
                solicitudes[mensaje_id] = {
                    'tipo': 'biometrico', 'archivo_original': nombre_unico, 'completado': False,
                    'texto': None, 'archivo': None, 'archivo_facial': None, 'tipo_archivo': None,
                    'sin_resultados': False, 'dni': None, 'dni_bloqueado': False, 'meta_message_id': None,
                    'fecha': datetime.now().isoformat(), 'mensaje_original_id': mensaje_id
                }
                return jsonify({'success': True, 'message_id': mensaje_id})
            return jsonify({'error': resultado['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout esperando turno'}), 500

@app.route('/facial2', methods=['POST'])
def pedir_facial2():
    if 'imagen' not in request.files: return jsonify({'error': 'No se envió imagen'}), 400
    archivo = request.files['imagen']
    if archivo.filename == '': return jsonify({'error': 'Nombre de archivo vacío'}), 400
    nombre_unico = f"{uuid.uuid4()}_{secure_filename(archivo.filename)}"
    ruta_imagen = os.path.join(CARPETA_UPLOADS, nombre_unico)
    archivo.save(ruta_imagen)
    request_id = str(uuid.uuid4())
    cola_facial2.put({'request_id': request_id, 'comando': COMANDO_BIOMETRICO, 'tipo': 'imagen', 'ruta_imagen': ruta_imagen})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_facial2:
            resultado = resultados_facial2.pop(request_id)
            if resultado['ok']:
                mensaje_id = resultado['message_id']
                solicitudes_facial2[mensaje_id] = {
                    'tipo': 'facial2', 'archivo_original': nombre_unico, 'completado': False,
                    'archivo': None, 'tipo_archivo': None, 'sin_resultados': False,
                    'fecha': datetime.now().isoformat(), 'mensaje_original_id': mensaje_id
                }
                return jsonify({'success': True, 'message_id': mensaje_id})
            return jsonify({'error': resultado['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout esperando turno'}), 500

@app.route('/estado/<int:message_id>')
def ver_estado(message_id):
    sol = solicitudes.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    if sol.get('dni_bloqueado'):
        sol['completado'] = True
        return jsonify(sol)
    if sol.get('meta_message_id') and sol['meta_message_id'] in solicitudes_meta:
        meta = solicitudes_meta[sol['meta_message_id']]
        if meta.get('archivo'): sol['archivo'] = meta['archivo']; sol['tipo_archivo'] = 'PDF'; sol['completado'] = True
        if meta.get('sin_resultados'): sol['sin_resultados'] = True; sol['completado'] = True
    return jsonify(sol)

@app.route('/facial2_estado/<int:message_id>')
def ver_estado_facial2(message_id):
    sol = solicitudes_facial2.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    return jsonify(sol)

@app.route('/nm', methods=['POST'])
def pedir_nm():
    if request.is_json: data = request.get_json(silent=True) or {}
    else: data = request.form
    query = (data.get('query') or '').strip()
    if not query or len(query) > 80: return jsonify({'error': 'Consulta inválida'}), 400
    request_id = str(uuid.uuid4())
    cola_nm.put({'request_id': request_id, 'query': query})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_nm:
            r = resultados_nm.pop(request_id)
            if r['ok']:
                mid = r['message_id']
                solicitudes_nm[mid] = {
                    'tipo': 'nm', 'query': query, 'completado': False,
                    'resultados': [], 'txt_archivo': None, 'fecha': datetime.now().isoformat(),
                    'mensaje_original_id': mid
                }
                return jsonify({'success': True, 'message_id': mid})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout esperando turno'}), 500

@app.route('/nm_estado/<int:message_id>')
def ver_estado_nm(message_id):
    sol = solicitudes_nm.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    return jsonify(sol)

@app.route('/sentinel', methods=['POST'])
def pedir_sentinel():
    if request.is_json: data = request.get_json(silent=True) or {}
    else: data = request.form
    dni = (data.get('dni') or '').strip()
    if not dni or not re.fullmatch(r'\d{8}', dni): return jsonify({'error': 'DNI inválido'}), 400
    if dni == DNI_PROHIBIDO: return jsonify({'error': 'DNI bloqueado'}), 403
    request_id = str(uuid.uuid4())
    cola_sentinel.put({'request_id': request_id, 'dni': dni})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_sentinel:
            r = resultados_sentinel.pop(request_id)
            if r['ok']:
                mid = r['message_id']
                solicitudes_sentinel[mid] = {
                    'tipo': 'sentinel', 'dni': dni, 'completado': False,
                    'archivo': None, 'tipo_archivo': None, 'sin_resultados': False,
                    'fecha': datetime.now().isoformat(),
                    'mensaje_original_id': mid
                }
                return jsonify({'success': True, 'message_id': mid})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout esperando turno'}), 500

@app.route('/sentinel_estado/<int:message_id>')
def ver_estado_sentinel(message_id):
    sol = solicitudes_sentinel.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    return jsonify(sol)

@app.route('/metaplaca', methods=['POST'])
def pedir_metaplaca():
    if request.is_json: data = request.get_json(silent=True) or {}
    else: data = request.form
    placa = (data.get('placa') or '').strip().upper().replace('-', '').replace(' ', '')
    if not placa or not re.fullmatch(r'[A-Z0-9]{6}', placa): return jsonify({'error': 'Placa inválida'}), 400
    request_id = str(uuid.uuid4())
    cola_metaplaca.put({'request_id': request_id, 'placa': placa})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_metaplaca:
            r = resultados_metaplaca.pop(request_id)
            if r['ok']:
                mid = r['message_id']
                solicitudes_metaplaca[mid] = {
                    'tipo': 'metaplaca', 'placa': placa, 'completado': False,
                    'archivo': None, 'tipo_archivo': None, 'sin_resultados': False,
                    'fecha': datetime.now().isoformat(),
                    'mensaje_original_id': mid
                }
                return jsonify({'success': True, 'message_id': mid})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout esperando turno'}), 500

@app.route('/metaplaca_estado/<int:message_id>')
def ver_estado_metaplaca(message_id):
    sol = solicitudes_metaplaca.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    return jsonify(sol)

@app.route('/dminsa', methods=['POST'])
def pedir_dminsa():
    if request.is_json: data = request.get_json(silent=True) or {}
    else: data = request.form
    dni = (data.get('dni') or '').strip()
    nombre = (data.get('nombre') or '').strip()
    diagnostico = (data.get('diagnostico') or '').strip()
    hospital = (data.get('hospital') or '').strip()
    fecha = (data.get('fecha') or '').strip()
    dias = (data.get('dias') or '').strip()
    if not all([dni, nombre, diagnostico, hospital, fecha, dias]):
        return jsonify({'error': 'Todos los campos son obligatorios'}), 400
    try:
        dt = datetime.strptime(fecha, '%Y-%m-%d')
        fecha_formateada = dt.strftime('%d-%m-%Y')
    except: fecha_formateada = fecha
    comando = f"{COMANDO_DMINSA} {dni}|{nombre}|{diagnostico}|{hospital}|{fecha_formateada}|{dias}"
    request_id = str(uuid.uuid4())
    cola_dminsa.put({'request_id': request_id, 'comando': comando, 'dni': dni})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_dminsa:
            r = resultados_dminsa.pop(request_id)
            if r['ok']:
                mid = r['message_id']
                solicitudes_dminsa[mid] = {
                    'tipo': 'dminsa', 'dni': dni, 'completado': False,
                    'archivo': None, 'tipo_archivo': None, 'texto_respuesta': None,
                    'fecha': datetime.now().isoformat(),
                    'mensaje_original_id': mid
                }
                return jsonify({'success': True, 'message_id': mid})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout esperando turno'}), 500

@app.route('/dminsa_estado/<int:message_id>')
def ver_estado_dminsa(message_id):
    sol = solicitudes_dminsa.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    return jsonify(sol)

@app.route('/archivo/<path:nombre>')
def servir_archivo(nombre): return send_from_directory(CARPETA_DESCARGAS, nombre)

@app.route('/meta/<path:nombre>')
def meta_archivo(nombre):
    response = send_from_directory(CARPETA_DESCARGAS, nombre)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Content-Type'] = 'application/pdf'
    return response

@app.route('/nm_txt/<path:nombre>')
def nm_txt(nombre):
    response = send_from_directory(CARPETA_DESCARGAS, nombre)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response

# ============================================
# ARRANQUE Y PING AUTOMÁTICO
# ============================================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

async def main():
    global MI_ID
    await client.start()
    me = await client.get_me()
    MI_ID = me.id
    print(f"👤 Nodo enlazado: {me.first_name} (ID: {MI_ID})")

    asyncio.create_task(procesar_cola())
    asyncio.create_task(procesar_cola_facial2())
    asyncio.create_task(procesar_cola_meta())
    asyncio.create_task(procesar_cola_nm())
    asyncio.create_task(procesar_cola_sentinel())
    asyncio.create_task(procesar_cola_metaplaca())
    asyncio.create_task(procesar_cola_dminsa())

    async def _loop_limpieza():
        while True:
            limpiar_viejos()
            await asyncio.sleep(600)
    asyncio.create_task(_loop_limpieza())
    await client.run_until_disconnected()

def ping_automatico():
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if url:
        while True:
            try:
                requests.get(url, timeout=10)
                print("✅ Ping enviado")
            except Exception as e:
                print(f"⚠️ Error ping: {e}")
            time.sleep(600)

if __name__ == '__main__':
    # 1. Arrancamos el "ping" para que Render no apague el bot
    if os.environ.get('RENDER_EXTERNAL_URL'):
        threading.Thread(target=ping_automatico, daemon=True).start()

    # 2. Arrancamos Flask (la página web) en un hilo aparte
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 3. Arrancamos el bot de Telegram
    with client:
        client.loop.run_until_complete(main())
