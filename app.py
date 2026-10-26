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
import unicodedata
import json
import requests
from datetime import datetime
from queue import Queue
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================
# CONFIGURACIÓN
# ============================================
api_id = 33774512
api_hash = '72af30fe5dd18997fc50a0a53e544f0c'
CHAT_ID = -1003732799535
CHAT_META = -1003771916049

SESSION_STR = os.environ.get("TELETHON_SESSION", "1AZWarzwBu6uxsF-V2dmYrNrbeUl4AXOZul8F7J-zpNmeOm5r8fEUfJQV4G4PC4XHUA-ccSX4Qz5RMpPZxzp_XCtQRlG_sYrgUnDAlrqtVSHjk5mR1guZYnrsmjP527CSxIfZiy114_K2U9BGjoGpoT9W0u_w0rEkV_zeyNX_gWi0rGidcPoy9li332SqeisMUFYg5HRyvjlZeqTEFNbzZODm5tiiMmiXmrl59e0s0iG4WSoyaJ7pMB-zqdY2NpQH8A-PLbT6-FDp-xKwl_HKI1h2brgWe1rxxnQWhEuEzhAEFnX-VaAf4BV3UKWYZDD0mI49aBIK0CgkzgYgenEvz5qUDWYhla0=").strip()
PANEL_PASS  = os.environ.get("PANEL_PASS", "1").strip()

if not SESSION_STR:
    raise RuntimeError("\n⚠️ TELETHON_SESSION no configurada.\n")

COMANDO_BIOMETRICO = '/facial'
COMANDO_FACIAL2    = '/facial2'
COMANDO_METAPLACA  = '/metaplaca'
COMANDO_META       = '/meta'
COMANDO_NM         = '/nm'
COMANDO_SENTINEL   = '/sentinel'
COMANDO_DMINSA     = '/dminsa'
COMANDO_C4         = '/c4'
COMANDO_BILLETERAS = '/billeteras'

# ============================================
# LISTA NEGRA
# ============================================
DNI_PROHIBIDO = {'77662668'}
NOMBRES_PROHIBIDOS = [
    'yovanny advincula',
    'yovanny carhuamaca advincula',
    'yovanny carhuamaca',
]

CARPETA_DESCARGAS = 'descargas'
CARPETA_UPLOADS = 'uploads'
os.makedirs(CARPETA_DESCARGAS, exist_ok=True)
os.makedirs(CARPETA_UPLOADS, exist_ok=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEVICES_FILE = os.path.join(BASE_DIR, 'devices.json')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

client = TelegramClient(StringSession(SESSION_STR), api_id, api_hash)

solicitudes = {}
solicitudes_facial2 = {}
solicitudes_meta = {}
solicitudes_nm = {}
solicitudes_sentinel = {}
solicitudes_metaplaca = {}
solicitudes_dminsa = {}
solicitudes_c4 = {}
solicitudes_billeteras = {}

cola_envios = Queue()
cola_facial2 = Queue()
cola_meta = Queue()
cola_nm = Queue()
cola_sentinel = Queue()
cola_metaplaca = Queue()
cola_dminsa = Queue()
cola_c4 = Queue()
cola_billeteras = Queue()

resultados_envios = {}
resultados_facial2 = {}
resultados_meta = {}
resultados_nm = {}
resultados_sentinel = {}
resultados_metaplaca = {}
resultados_dminsa = {}
resultados_c4 = {}
resultados_billeteras = {}

MI_ID = None

_SC = str.maketrans({'ʀ': 'r', 'ᴇ': 'e', 'ᴜ': 'u', 'ᴛ': 't', 'ᴀ': 'a', 'ᴅ': 'd', 'ᴏ': 'o', 'ɪ': 'i', 'ɴ': 'n', 'ꜰ': 'f', 'ᴄ': 'c', 'ʟ': 'l', 'ᴍ': 'm', 'ᴘ': 'p', 'ᴡ': 'w', 'ʏ': 'y', 'ᴢ': 'z', 'ɢ': 'g', 'ʙ': 'b', 'ᴋ': 'k', 'ᴊ': 'j', 'ᴠ': 'v', 'ʜ': 'h', 'ꜱ': 's', 'ǫ': 'o'})

def normalizar(texto): return (texto or '').translate(_SC).lower()

def _norm_txt(s):
    if not s: return ''
    s = s.translate(_SC).lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def nombre_bloqueado(nombre):
    n = _norm_txt(nombre)
    return any(p in n for p in NOMBRES_PROHIBIDOS) if n else False

def dni_bloqueado(dni): return str(dni) in DNI_PROHIBIDO

def es_sin_resultados(texto):
    n = normalizar(texto)
    return 'sin resultado' in n or 'otra foto' in n or 'sin coincidencia' in n or 'no se encontro' in n or 'error' in n or 'no existe' in n

def es_pdf(event):
    return event.document and 'pdf' in (getattr(event.document, 'mime_type', '') or '').lower()

def es_imagen(event):
    if event.photo: return True
    return event.document and (getattr(event.document, 'mime_type', '') or '').startswith('image/')

def marcar_completado(sol):
    sol['completado'] = True
    sol['fecha_completado'] = datetime.now().isoformat()

def extraer_dni_de_texto(texto):
    if not texto: return None
    t = texto.translate(_SC)
    m = re.search(r'dni\s*[·:：\-]?\s*(\d{6,9})', t, re.IGNORECASE)
    return m.group(1) if m else (re.search(r'\b(\d{8})\b', t).group(1) if re.search(r'\b(\d{8})\b', t) else None)

def _load_json(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def _save_json(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

# ============================================
# PARSER /nm
# ============================================
def parsear_nm(texto):
    texto = (texto or '').replace('\\n', '\n')
    personas = []
    actual = None
    for raw in texto.split('\n'):
        ln = raw.strip()
        if not ln or ln.startswith('**#SAKUMADATA') or ln.startswith('#SAKUMADATA') or ln.startswith('➻'): continue
        if re.match(r'^ᴛᴏᴛᴀʟ\s*[:：]', ln, re.IGNORECASE) or 'ᴄʀᴇ́ᴅɪᴛᴏs' in ln or 'ᴄʀᴇᴅɪᴛᴏs' in ln or 'ᴜsᴜᴀʀɪᴏ' in ln: continue
        if re.fullmatch(r'[-=_]{3,}', ln) or re.fullmatch(r'ʙᴜsǫᴜᴇᴅᴀ.*', ln): continue

        if re.fullmatch(r'\[(\d+)\]', ln):
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
            limpio = re.sub(r'^[\*\`_]+|[\*\`_]+$', '', ln.strip()).strip()
            if limpio: actual['campos'].append(limpio)

    if actual: personas.append(actual)
    return [p for p in personas if p.get('dni') and p['dni'].isdigit() and len(p['dni']) == 8]

def filtrar_personas_bloqueadas(personas):
    out = []
    for p in personas:
        if dni_bloqueado(p.get('dni')) or nombre_bloqueado(' '.join(p.get('campos', []))): continue
        out.append(p)
    return out

# ============================================
# HANDLERS TELEGRAM
# ============================================
@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_facial(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''
    if 'reniec' in normalizar(texto) or 'bsqueda' in normalizar(texto) or 'busqueda' in normalizar(texto) or 'ʙᴜsǫᴜᴇᴅᴀ' in texto: return
    sol = None; tipo = None
    if event.reply_to_msg_id:
        if event.reply_to_msg_id in solicitudes_facial2: sol = solicitudes_facial2[event.reply_to_msg_id]; tipo = 'facial2'
        elif event.reply_to_msg_id in solicitudes: sol = solicitudes[event.reply_to_msg_id]; tipo = 'facial'
    if sol is None and es_sin_resultados(texto):
        pend2 = [x for x in solicitudes_facial2.values() if not x['completado']]
        pend1 = [x for x in solicitudes.values() if x['tipo'] == 'biometrico' and not x['completado']]
        if pend2 and (not pend1 or max(pend2, key=lambda x: x['fecha'])['fecha'] > max(pend1, key=lambda x: x['fecha'])['fecha']): sol = max(pend2, key=lambda x: x['fecha']); tipo = 'facial2'
        elif pend1: sol = max(pend1, key=lambda x: x['fecha']); tipo = 'facial'
    if sol is None and es_pdf(event):
        pend2 = [x for x in solicitudes_facial2.values() if not x['completado']]
        pend1 = [x for x in solicitudes.values() if x['tipo'] == 'biometrico' and not x['completado']]
        if pend2 and (not pend1 or max(pend2, key=lambda x: x['fecha'])['fecha'] > max(pend1, key=lambda x: x['fecha'])['fecha']): sol = max(pend2, key=lambda x: x['fecha']); tipo = 'facial2'
        elif pend1: sol = max(pend1, key=lambda x: x['fecha']); tipo = 'facial'
    if sol is None: return
    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass
    if es_sin_resultados(texto): sol['sin_resultados'] = True; marcar_completado(sol); return
    if tipo == 'facial2':
        if es_pdf(event):
            try: sol['archivo'] = os.path.basename(await event.download_media(file=CARPETA_DESCARGAS)); sol['tipo_archivo'] = 'PDF'
            except: pass
        marcar_completado(sol); return
    dni = extraer_dni_de_texto(texto)
    if dni and not sol.get('dni'):
        if dni_bloqueado(dni): sol['dni'] = dni; sol['dni_bloqueado'] = True; marcar_completado(sol)
        else:
            sol['dni'] = dni; sol['texto'] = texto
            request_id = str(uuid.uuid4()); cola_meta.put({'request_id': request_id, 'dni': dni})
            inicio = time.time()
            while time.time() - inicio < 15:
                if request_id in resultados_meta:
                    r = resultados_meta.pop(request_id)
                    if r['ok']:
                        solicitudes_meta[r['message_id']] = {'tipo': 'meta', 'dni': dni, 'completado': False, 'archivo': None, 'tipo_archivo': None, 'sin_resultados': False, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                        sol['meta_message_id'] = r['message_id']
                    break
                await asyncio.sleep(0.2)
    if es_pdf(event):
        try: sol['archivo_facial'] = os.path.basename(await event.download_media(file=CARPETA_DESCARGAS))
        except: pass

@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_dminsa(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_dminsa: sol = solicitudes_dminsa[event.reply_to_msg_id]
    if sol is None:
        m = re.search(r'\b(\d{8})\b', texto)
        if m:
            pend = [x for x in solicitudes_dminsa.values() if not x['completado'] and x.get('dni') == m.group(1)]
            if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pend = [x for x in solicitudes_dminsa.values() if not x['completado']]
        if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None: return
    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass
    if texto.strip(): sol['texto_respuesta'] = texto
    if es_pdf(event):
        try: sol['archivo'] = os.path.basename(await event.download_media(file=CARPETA_DESCARGAS)); sol['tipo_archivo'] = 'PDF'
        except: pass
        marcar_completado(sol)

@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_metaplaca(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_metaplaca: sol = solicitudes_metaplaca[event.reply_to_msg_id]
    if sol is None:
        m = re.search(r'\b([A-Z0-9]{3}[-\s]?[A-Z0-9]{3})\b', texto.upper())
        if m:
            pend = [x for x in solicitudes_metaplaca.values() if not x['completado'] and x.get('placa') == m.group(1).replace('-', '').replace(' ', '')]
            if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pend = [x for x in solicitudes_metaplaca.values() if not x['completado']]
        if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None: return
    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass
    if es_sin_resultados(texto): sol['sin_resultados'] = True; marcar_completado(sol); return
    if es_pdf(event):
        try: sol['archivo'] = os.path.basename(await event.download_media(file=CARPETA_DESCARGAS)); sol['tipo_archivo'] = 'PDF'
        except: pass
        marcar_completado(sol)

@client.on(events.MessageEdited(chats=CHAT_ID))
@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_nm(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_nm: sol = solicitudes_nm[event.reply_to_msg_id]
    if sol is None:
        es_cabecera = ('reniec' in normalizar(texto)) or ('bsqueda' in normalizar(texto)) or ('busqueda' in normalizar(texto)) or ('ʙᴜsǫᴜᴇᴅᴀ' in texto)
        es_txt = bool(event.document) and ('text' in (event.document.mime_type or '') or (event.file and event.file.name and event.file.name.lower().endswith('.txt')))
        if es_cabecera or es_txt or es_sin_resultados(texto):
            pend = [x for x in solicitudes_nm.values() if not x.get('completado')]
            if pend:
                recientes = [x for x in pend if time.time() - datetime.fromisoformat(x['fecha']).timestamp() <= 120]
                if recientes: sol = max(recientes, key=lambda x: x['fecha'])
    if sol is None or sol.get('completado'): return
    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass
    if es_sin_resultados(texto): sol['sin_resultados'] = True; marcar_completado(sol); return
    contenido = texto
    if event.document:
        es_txt = ('text' in (event.document.mime_type or '')) or ((event.file.name or '').lower().endswith('.txt'))
        if es_txt:
            try:
                ruta = await event.download_media(file=CARPETA_DESCARGAS)
                nombre_unico = f"nm_{event.id}.txt"; ruta_unica = os.path.join(CARPETA_DESCARGAS, nombre_unico)
                try: os.rename(ruta, ruta_unica)
                except: ruta_unica = ruta; nombre_unico = os.path.basename(ruta)
                sol['txt_archivo'] = nombre_unico
                with open(ruta_unica, 'r', encoding='utf-8', errors='ignore') as f: contenido = f.read()
            except: return
    personas = filtrar_personas_bloqueadas(parsear_nm(contenido))
    if not personas: return
    sol['resultados'] = personas; sol['completado'] = True; sol['fecha_completado'] = datetime.now().isoformat()

@client.on(events.NewMessage(chats=CHAT_META))
async def handler_meta(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_meta: sol = solicitudes_meta[event.reply_to_msg_id]
    if sol is None:
        dni_det = extraer_dni_de_texto(texto)
        if dni_det:
            if dni_bloqueado(dni_det):
                try: await client.delete_messages(CHAT_META, [event.id])
                except: pass
                return
            pend = [x for x in solicitudes_meta.values() if not x['completado'] and x.get('dni') == dni_det]
            if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pend = [x for x in solicitudes_meta.values() if not x['completado']]
        if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None: return
    try: await client.delete_messages(CHAT_META, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_META, [sol['mensaje_original_id']])
        except: pass
    if es_sin_resultados(texto): sol['sin_resultados'] = True; marcar_completado(sol); return
    if es_pdf(event):
        try: sol['archivo'] = os.path.basename(await event.download_media(file=CARPETA_DESCARGAS)); sol['tipo_archivo'] = 'PDF'
        except: pass
        marcar_completado(sol)

@client.on(events.NewMessage(chats=CHAT_META))
async def handler_sentinel(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_sentinel: sol = solicitudes_sentinel[event.reply_to_msg_id]
    if sol is None:
        dni_det = extraer_dni_de_texto(texto)
        if dni_det:
            if dni_bloqueado(dni_det):
                try: await client.delete_messages(CHAT_META, [event.id])
                except: pass
                return
            pend = [x for x in solicitudes_sentinel.values() if not x['completado'] and x.get('dni') == dni_det]
            if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None and es_pdf(event):
        pend = [x for x in solicitudes_sentinel.values() if not x['completado']]
        if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None: return
    try: await client.delete_messages(CHAT_META, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_META, [sol['mensaje_original_id']])
        except: pass
    if es_sin_resultados(texto): sol['sin_resultados'] = True; marcar_completado(sol); return
    if es_pdf(event):
        try: sol['archivo'] = os.path.basename(await event.download_media(file=CARPETA_DESCARGAS)); sol['tipo_archivo'] = 'PDF'
        except: pass
        marcar_completado(sol)

@client.on(events.NewMessage(chats=CHAT_ID))
async def handler_c4(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_c4: sol = solicitudes_c4[event.reply_to_msg_id]
    if sol is None:
        m = re.search(r'\b(\d{8})\b', texto)
        if m:
            if dni_bloqueado(m.group(1)):
                try: await client.delete_messages(CHAT_ID, [event.id])
                except: pass
                return
            pend = [x for x in solicitudes_c4.values() if not x['completado'] and x.get('dni') == m.group(1)]
            if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None or sol.get('completado'): return
    if not es_imagen(event):
        if es_sin_resultados(texto):
            try: await client.delete_messages(CHAT_ID, [event.id])
            except: pass
            sol['sin_resultados'] = True; marcar_completado(sol)
        return
    foto = event.photo; doc = event.document; ancho = alto = 0
    if doc:
        for attr in doc.attributes:
            if hasattr(attr, 'w') and hasattr(attr, 'h'): ancho, alto = attr.w, attr.h
    elif foto:
        sizes = [s for s in foto.sizes if hasattr(s, 'w')]
        if sizes: big = max(sizes, key=lambda s: s.w * s.h); ancho, alto = big.w, big.h
    if not (alto > ancho if (ancho and alto) else False): return 
    try: await client.delete_messages(CHAT_ID, [event.id])
    except: pass
    if sol.get('mensaje_original_id'):
        try: await client.delete_messages(CHAT_ID, [sol['mensaje_original_id']])
        except: pass
    try:
        ruta = await event.download_media(file=CARPETA_DESCARGAS)
        if ruta:
            nombre_unico = f"c4_{sol['dni']}_{int(time.time())}.jpg"; ruta_unica = os.path.join(CARPETA_DESCARGAS, nombre_unico)
            try: os.rename(ruta, ruta_unica)
            except: ruta_unica = ruta; nombre_unico = os.path.basename(ruta)
            sol['imagen'] = nombre_unico
        marcar_completado(sol)
    except: marcar_completado(sol)

@client.on(events.NewMessage(chats=CHAT_META))
async def handler_billeteras(event):
    if event.sender_id == MI_ID: return
    texto = event.text or ''; sol = None
    if event.reply_to_msg_id and event.reply_to_msg_id in solicitudes_billeteras: 
        sol = solicitudes_billeteras[event.reply_to_msg_id]
    if sol is None:
        m = re.search(r'\b(\d{9})\b', texto)
        if m:
            pend = [x for x in solicitudes_billeteras.values() if not x['completado'] and x.get('telefono') == m.group(1)]
            if pend: sol = max(pend, key=lambda x: x['fecha'])
    if sol is None or sol.get('completado'): return
    
    if es_sin_resultados(texto):
        try: await client.delete_messages(CHAT_META, [event.id])
        except: pass
        sol['sin_resultados'] = True; marcar_completado(sol); return
        
    if "BILLETERAS ASOCIADAS" in texto.upper() or "Titular" in texto:
        # =========================================================
        # LIMPIEZA EXTREMA EN EL SERVIDOR (Oculto para el usuario)
        # =========================================================
        texto_limpio = re.sub(r'#GHOSTOPS_BOT[\s\S]*?(?=Titular)', '', texto, flags=re.IGNORECASE) 
        texto_limpio = re.sub(r'\[⚡\]\s*ESTADO DE CUENTA[\s\S]*$', '', texto_limpio, flags=re.IGNORECASE) 
        texto_limpio = texto_limpio.replace('*', '').replace('`', '').replace('**', '') 
        
        sol['resultados'] = texto_limpio.strip()
        marcar_completado(sol)
        
        try: await client.delete_messages(CHAT_META, [event.id])
        except: pass
        if sol.get('mensaje_original_id'):
            try: await client.delete_messages(CHAT_META, [sol['mensaje_original_id']])
            except: pass

# ============================================
# WORKERS (Colas)
# ============================================
async def worker(cola, resultados, tipo, funcion_envio):
    while True:
        try:
            item = await asyncio.get_event_loop().run_in_executor(None, cola.get)
            request_id = item['request_id']
            try:
                mensaje = await funcion_envio(item)
                if 'ruta_imagen' in item:
                    try: os.remove(item['ruta_imagen'])
                    except: pass
                resultados[request_id] = {'ok': True, 'message_id': mensaje.id}
            except Exception as e: resultados[request_id] = {'ok': False, 'error': str(e)}
            await asyncio.sleep(3)
        except: await asyncio.sleep(1)

async def main():
    global MI_ID
    await client.start()
    me = await client.get_me(); MI_ID = me.id
    print(f"👤 Nodo enlazado: {me.first_name} (ID: {MI_ID})")
    
    asyncio.create_task(worker(cola_envios, resultados_envios, 'envios', lambda i: client.send_file(CHAT_ID, i['ruta_imagen'], caption=i['comando'])))
    asyncio.create_task(worker(cola_facial2, resultados_facial2, 'facial2', lambda i: client.send_file(CHAT_ID, i['ruta_imagen'], caption=i['comando'])))
    asyncio.create_task(worker(cola_meta, resultados_meta, 'meta', lambda i: client.send_message(CHAT_META, f"{COMANDO_META} {i['dni']}")))
    asyncio.create_task(worker(cola_nm, resultados_nm, 'nm', lambda i: client.send_message(CHAT_ID, f"{COMANDO_NM} {i['query']}")))
    asyncio.create_task(worker(cola_sentinel, resultados_sentinel, 'sentinel', lambda i: client.send_message(CHAT_META, f"{COMANDO_SENTINEL} {i['dni']}")))
    asyncio.create_task(worker(cola_metaplaca, resultados_metaplaca, 'metaplaca', lambda i: client.send_message(CHAT_ID, f"{COMANDO_METAPLACA} {i['placa']}")))
    asyncio.create_task(worker(cola_dminsa, resultados_dminsa, 'dminsa', lambda i: client.send_message(CHAT_ID, i['comando'])))
    asyncio.create_task(worker(cola_c4, resultados_c4, 'c4', lambda i: client.send_message(CHAT_ID, f"{COMANDO_C4} {i['dni']}")))
    asyncio.create_task(worker(cola_billeteras, resultados_billeteras, 'billeteras', lambda i: client.send_message(CHAT_META, f"{COMANDO_BILLETERAS} {i['telefono']}")))

    async def _loop_limpieza():
        while True:
            ahora = time.time()
            for store in (solicitudes, solicitudes_facial2, solicitudes_meta, solicitudes_nm, solicitudes_sentinel, solicitudes_metaplaca, solicitudes_dminsa, solicitudes_c4, solicitudes_billeteras):
                for k in list(store.keys()):
                    try:
                        if ahora - datetime.fromisoformat(store[k]['fecha']).timestamp() > 3600: del store[k]
                    except: pass
            await asyncio.sleep(600)
    asyncio.create_task(_loop_limpieza())
    await client.run_until_disconnected()

# ============================================
# FLASK
# ============================================
app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": "*"}})

INDEX_PATH = os.path.join(BASE_DIR, 'index.html')

@app.route('/') 
def index():
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f: return f.read()
    except: return "index.html no encontrado", 404

@app.route('/css/<path:nombre>')
def servir_css(nombre): return send_from_directory(os.path.join(BASE_DIR, 'css'), nombre)

@app.route('/js/<path:nombre>')
def servir_js(nombre): return send_from_directory(os.path.join(BASE_DIR, 'js'), nombre)

@app.route('/favicon.ico')
def favicon(): return '', 204

@app.route('/facial', methods=['POST'])
def pedir_biometrico():
    if 'imagen' not in request.files: return jsonify({'error': 'No se envió imagen'}), 400
    archivo = request.files['imagen']; nombre_unico = f"{uuid.uuid4()}_{secure_filename(archivo.filename)}"
    ruta = os.path.join(CARPETA_UPLOADS, nombre_unico); archivo.save(ruta)
    request_id = str(uuid.uuid4()); cola_envios.put({'request_id': request_id, 'comando': COMANDO_BIOMETRICO, 'tipo': 'imagen', 'ruta_imagen': ruta})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_envios:
            r = resultados_envios.pop(request_id)
            if r['ok']:
                solicitudes[r['message_id']] = {'tipo': 'biometrico', 'archivo_original': nombre_unico, 'completado': False, 'texto': None, 'archivo': None, 'archivo_facial': None, 'tipo_archivo': None, 'sin_resultados': False, 'dni': None, 'dni_bloqueado': False, 'meta_message_id': None, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/facial2', methods=['POST'])
def pedir_facial2():
    if 'imagen' not in request.files: return jsonify({'error': 'No se envió imagen'}), 400
    archivo = request.files['imagen']; nombre_unico = f"{uuid.uuid4()}_{secure_filename(archivo.filename)}"
    ruta = os.path.join(CARPETA_UPLOADS, nombre_unico); archivo.save(ruta)
    request_id = str(uuid.uuid4()); cola_facial2.put({'request_id': request_id, 'comando': COMANDO_BIOMETRICO, 'tipo': 'imagen', 'ruta_imagen': ruta})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_facial2:
            r = resultados_facial2.pop(request_id)
            if r['ok']:
                solicitudes_facial2[r['message_id']] = {'tipo': 'facial2', 'archivo_original': nombre_unico, 'completado': False, 'archivo': None, 'tipo_archivo': None, 'sin_resultados': False, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/estado/<int:message_id>')
def ver_estado(message_id):
    sol = solicitudes.get(message_id)
    if not sol: return jsonify({'error': 'No encontrado'}), 404
    if sol.get('dni_bloqueado'): sol['completado'] = True; return jsonify(sol)
    if sol.get('meta_message_id') and sol['meta_message_id'] in solicitudes_meta:
        meta = solicitudes_meta[sol['meta_message_id']]
        if meta.get('archivo'): sol['archivo'] = meta['archivo']; sol['tipo_archivo'] = 'PDF'; sol['completado'] = True
        if meta.get('sin_resultados'): sol['sin_resultados'] = True; sol['completado'] = True
    return jsonify(sol)

@app.route('/facial2_estado/<int:message_id>')
def ver_estado_facial2(message_id):
    sol = solicitudes_facial2.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/nm', methods=['POST'])
def pedir_nm():
    data = request.get_json(silent=True) or request.form; query = (data.get('query') or '').strip()
    if not query or len(query) > 80: return jsonify({'error': 'Consulta inválida'}), 400
    if nombre_bloqueado(query): return jsonify({'error': 'Consulta bloqueada'}), 403
    request_id = str(uuid.uuid4()); cola_nm.put({'request_id': request_id, 'query': query})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_nm:
            r = resultados_nm.pop(request_id)
            if r['ok']:
                solicitudes_nm[r['message_id']] = {'tipo': 'nm', 'query': query, 'completado': False, 'resultados': [], 'txt_archivo': None, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/nm_estado/<int:message_id>')
def ver_estado_nm(message_id):
    sol = solicitudes_nm.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/sentinel', methods=['POST'])
def pedir_sentinel():
    data = request.get_json(silent=True) or request.form; dni = (data.get('dni') or '').strip()
    if not dni or not re.fullmatch(r'\d{8}', dni): return jsonify({'error': 'DNI inválido'}), 400
    if dni_bloqueado(dni): return jsonify({'error': 'DNI bloqueado'}), 403
    request_id = str(uuid.uuid4()); cola_sentinel.put({'request_id': request_id, 'dni': dni})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_sentinel:
            r = resultados_sentinel.pop(request_id)
            if r['ok']:
                solicitudes_sentinel[r['message_id']] = {'tipo': 'sentinel', 'dni': dni, 'completado': False, 'archivo': None, 'tipo_archivo': None, 'sin_resultados': False, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/sentinel_estado/<int:message_id>')
def ver_estado_sentinel(message_id):
    sol = solicitudes_sentinel.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/metaplaca', methods=['POST'])
def pedir_metaplaca():
    data = request.get_json(silent=True) or request.form; placa = (data.get('placa') or '').strip().upper().replace('-', '').replace(' ', '')
    if not placa or not re.fullmatch(r'[A-Z0-9]{6}', placa): return jsonify({'error': 'Placa inválida'}), 400
    request_id = str(uuid.uuid4()); cola_metaplaca.put({'request_id': request_id, 'placa': placa})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_metaplaca:
            r = resultados_metaplaca.pop(request_id)
            if r['ok']:
                solicitudes_metaplaca[r['message_id']] = {'tipo': 'metaplaca', 'placa': placa, 'completado': False, 'archivo': None, 'tipo_archivo': None, 'sin_resultados': False, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/metaplaca_estado/<int:message_id>')
def ver_estado_metaplaca(message_id):
    sol = solicitudes_metaplaca.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/dminsa', methods=['POST'])
def pedir_dminsa():
    data = request.get_json(silent=True) or request.form
    dni = (data.get('dni') or '').strip()
    nombre = (data.get('nombre') or '').strip()
    diagnostico = (data.get('diagnostico') or '').strip()
    hospital = (data.get('hospital') or '').strip()
    fecha = (data.get('fecha') or '').strip()
    dias = (data.get('dias') or '').strip()
    
    if not all([dni, nombre, diagnostico, hospital, fecha, dias]): return jsonify({'error': 'Faltan campos'}), 400
    if dni_bloqueado(dni) or nombre_bloqueado(nombre): return jsonify({'error': 'Bloqueado'}), 403
    try: fecha_formateada = datetime.strptime(fecha, '%Y-%m-%d').strftime('%d-%m-%Y')
    except: fecha_formateada = fecha
    request_id = str(uuid.uuid4()); cola_dminsa.put({'request_id': request_id, 'comando': f"{COMANDO_DMINSA} {dni}|{nombre}|{diagnostico}|{hospital}|{fecha_formateada}|{dias}", 'dni': dni})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_dminsa:
            r = resultados_dminsa.pop(request_id)
            if r['ok']:
                solicitudes_dminsa[r['message_id']] = {'tipo': 'dminsa', 'dni': dni, 'completado': False, 'archivo': None, 'tipo_archivo': None, 'texto_respuesta': None, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/dminsa_estado/<int:message_id>')
def ver_estado_dminsa(message_id):
    sol = solicitudes_dminsa.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/c4', methods=['POST'])
def pedir_c4():
    data = request.get_json(silent=True) or request.form; dni = (data.get('dni') or '').strip()
    if not dni or not re.fullmatch(r'\d{8}', dni): return jsonify({'error': 'DNI inválido'}), 400
    if dni_bloqueado(dni): return jsonify({'error': 'DNI bloqueado'}), 403
    request_id = str(uuid.uuid4()); cola_c4.put({'request_id': request_id, 'dni': dni})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_c4:
            r = resultados_c4.pop(request_id)
            if r['ok']:
                solicitudes_c4[r['message_id']] = {'tipo': 'c4', 'dni': dni, 'completado': False, 'imagen': None, 'sin_resultados': False, 'error': None, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/c4_estado/<int:message_id>')
def ver_estado_c4(message_id):
    sol = solicitudes_c4.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/c4_img/<path:nombre>')
def c4_img(nombre):
    r = send_from_directory(CARPETA_DESCARGAS, nombre); r.headers['Access-Control-Allow-Origin'] = '*'; r.headers['Content-Type'] = 'image/jpeg'; return r

@app.route('/billeteras', methods=['POST'])
def pedir_billeteras():
    data = request.get_json(silent=True) or request.form; telefono = (data.get('telefono') or '').strip()
    if not telefono or not re.fullmatch(r'\d{9}', telefono): return jsonify({'error': 'Celular inválido (9 dígitos)'}), 400
    request_id = str(uuid.uuid4()); cola_billeteras.put({'request_id': request_id, 'telefono': telefono})
    inicio = time.time()
    while time.time() - inicio < 60:
        if request_id in resultados_billeteras:
            r = resultados_billeteras.pop(request_id)
            if r['ok']:
                solicitudes_billeteras[r['message_id']] = {'tipo': 'billeteras', 'telefono': telefono, 'completado': False, 'resultados': None, 'sin_resultados': False, 'error': None, 'fecha': datetime.now().isoformat(), 'mensaje_original_id': r['message_id']}
                return jsonify({'success': True, 'message_id': r['message_id']})
            return jsonify({'error': r['error']}), 500
        time.sleep(0.2)
    return jsonify({'error': 'Timeout'}), 500

@app.route('/billeteras_estado/<int:message_id>')
def ver_estado_billeteras(message_id):
    sol = solicitudes_billeteras.get(message_id); return jsonify(sol) if sol else (jsonify({'error': 'No encontrado'}), 404)

@app.route('/archivo/<path:nombre>')
def servir_archivo(nombre): return send_from_directory(CARPETA_DESCARGAS, nombre)

@app.route('/meta/<path:nombre>')
def meta_archivo(nombre):
    r = send_from_directory(CARPETA_DESCARGAS, nombre); r.headers['Access-Control-Allow-Origin'] = '*'; r.headers['Content-Type'] = 'application/pdf'; return r

@app.route('/nm_txt/<path:nombre>')
def nm_txt(nombre):
    r = send_from_directory(CARPETA_DESCARGAS, nombre); r.headers['Access-Control-Allow-Origin'] = '*'; r.headers['Content-Type'] = 'text/plain; charset=utf-8'; return r

# ============================================
# GPS Y AUDITORÍA
# ============================================
@app.route('/audit_visita', methods=['POST'])
def audit_visita():
    try:
        data = request.get_json(silent=True) or {}; fp = (data.get('fingerprint') or '').strip()
        if not fp: return jsonify({'ok': False, 'error': 'Sin fingerprint'}), 400
        db = _load_json(DEVICES_FILE); reg = db.get(fp, {}); ubi = data.get('ubicacion') or {}
        reg.update({'fingerprint': fp, 'navegador': data.get('navegador') or reg.get('navegador', ''), 'so': data.get('so') or reg.get('so', ''), 'modelo': data.get('modelo') or reg.get('modelo', ''), 'pantalla': data.get('pantalla') or reg.get('pantalla', ''), 'idioma': data.get('idioma') or reg.get('idioma', ''), 'user_agent': data.get('user_agent') or reg.get('user_agent', ''), 'ip': ubi.get('ip') or reg.get('ip', ''), 'pais': ubi.get('pais') or reg.get('pais', ''), 'region': ubi.get('region') or reg.get('region', ''), 'ciudad': ubi.get('ciudad') or reg.get('ciudad', ''), 'org': ubi.get('org') or reg.get('org', ''), 'visitas': int(reg.get('visitas', 0)) + 1, 'ultima_visita': datetime.now().isoformat()})
        reg['primera_visita'] = reg.get('primera_visita') or reg['ultima_visita']; reg.setdefault('bloqueado', False); reg.setdefault('motivo', '')
        db[fp] = reg; _save_json(DEVICES_FILE, db); return jsonify({'ok': True})
    except: return jsonify({'ok': False}), 500

@app.route('/audit_gps', methods=['POST'])
def audit_gps():
    try:
        data = request.get_json(silent=True) or {}; fp = (data.get('fingerprint') or '').strip()
        if not fp: return jsonify({'ok': False}), 400
        db = _load_json(DEVICES_FILE); reg = db.get(fp, {'fingerprint': fp, 'visitas': 0})
        reg.update({'gps_lat': data.get('lat'), 'gps_lon': data.get('lon'), 'gps_acc': data.get('accuracy'), 'gps_fecha': datetime.now().isoformat()})
        db[fp] = reg; _save_json(DEVICES_FILE, db); return jsonify({'ok': True})
    except: return jsonify({'ok': False}), 500

@app.route('/audit_check')
def audit_check():
    fp = (request.args.get('fp') or '').strip()
    if not fp: return jsonify({'bloqueado': False, 'motivo': ''})
    db = _load_json(DEVICES_FILE); r = db.get(fp, {})
    return jsonify({'bloqueado': bool(r.get('bloqueado')), 'motivo': r.get('motivo', '')})

@app.route('/audit_panel', methods=['POST'])
def audit_panel():
    data = request.get_json(silent=True) or {}; pw = (data.get('password') or '').strip()
    if not PANEL_PASS or pw != PANEL_PASS: return jsonify({'ok': False, 'error': 'No autorizado'}), 403
    db = _load_json(DEVICES_FILE)
    items = [{'fingerprint': fp, 'navegador': r.get('navegador', ''), 'so': r.get('so', ''), 'modelo': r.get('modelo', ''), 'ip': r.get('ip', ''), 'ciudad': r.get('ciudad', ''), 'region': r.get('region', ''), 'pais': r.get('pais', ''), 'org': r.get('org', ''), 'visitas': r.get('visitas', 1), 'ultima_visita': r.get('ultima_visita', ''), 'gps_lat': r.get('gps_lat'), 'gps_lon': r.get('gps_lon'), 'bloqueado': bool(r.get('bloqueado')), 'motivo': r.get('motivo', ''), 'usuario': r.get('usuario', '')} for fp, r in db.items()]
    items.sort(key=lambda x: x.get('ultima_visita', ''), reverse=True)
    return jsonify({'ok': True, 'dispositivos': items})

@app.route('/audit_block', methods=['POST'])
def audit_block():
    data = request.get_json(silent=True) or {}; pw = (data.get('password') or '').strip()
    if not PANEL_PASS or pw != PANEL_PASS: return jsonify({'ok': False}), 403
    fp = (data.get('fingerprint') or '').strip(); motivo = (data.get('motivo') or '').strip() or 'Bloqueado'
    if not fp: return jsonify({'ok': False}), 400
    db = _load_json(DEVICES_FILE); r = db.get(fp, {'fingerprint': fp, 'visitas': 0}); r.update({'bloqueado': True, 'motivo': motivo, 'fecha_bloqueo': datetime.now().isoformat()})
    db[fp] = r; _save_json(DEVICES_FILE, db); return jsonify({'ok': True})

@app.route('/audit_unblock', methods=['POST'])
def audit_unblock():
    data = request.get_json(silent=True) or {}; pw = (data.get('password') or '').strip()
    if not PANEL_PASS or pw != PANEL_PASS: return jsonify({'ok': False}), 403
    fp = (data.get('fingerprint') or '').strip()
    if not fp: return jsonify({'ok': False}), 400
    db = _load_json(DEVICES_FILE)
    if fp in db: db[fp]['bloqueado'] = False; db[fp]['motivo'] = ''; _save_json(DEVICES_FILE, db)
    return jsonify({'ok': True})

# ============================================
# SISTEMA DE USUARIOS (AQUÍ SE GUARDA EL NOMBRE)
# ============================================
@app.route('/api/check_user', methods=['POST'])
def check_user():
    data = request.get_json(silent=True) or {}
    usuario = (data.get('usuario') or '').strip()
    password = (data.get('password') or '').strip()
    fingerprint = (data.get('fingerprint') or '').strip()
    
    if not usuario or not password:
        return jsonify({'ok': False, 'error': 'Faltan datos'}), 400
        
    users = _load_json(USERS_FILE)
    valido = False
    
    if not users:
        valido = True 
    elif usuario in users:
        user_data = users[usuario]
        if user_data.get('bloqueado'):
            return jsonify({'ok': False, 'error': 'Tu cuenta ha sido bloqueada por el administrador.'}), 403
        if user_data.get('password') == password:
            valido = True
            
    if valido:
        if fingerprint:
            db = _load_json(DEVICES_FILE)
            if fingerprint in db:
                db[fingerprint]['usuario'] = usuario
                _save_json(DEVICES_FILE, db)
        return jsonify({'ok': True})
            
    return jsonify({'ok': False, 'error': 'Credenciales incorrectas'}), 401

# ============================================
# ARRANQUE
# ============================================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    with client:
        client.loop.run_until_complete(main())
