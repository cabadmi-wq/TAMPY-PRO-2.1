import hashlib
import hmac
import io
import json
import logging
import os
import re
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from groq import Groq

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tampy")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
CLAVE_ACCESO = os.environ.get("TAMPY_CLAVE", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = False
DATA_DIR = Path(os.environ.get("TAMPY_DATA_DIR", str(Path(__file__).parent / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

MODELOS_TEXTO = [m for m in [
    os.environ.get("MODELO_TEXTO"),
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
] if m]
MODELOS_VISION = [m for m in [
    os.environ.get("MODELO_VISION"),
    "qwen/qwen3.8-27b",
] if m]

SYSTEM_BASE = (
    "Eres TAMPY, un asistente de IA profesional, claro y amable. "
    "Respondes siempre en español, salvo que el usuario pida otro idioma. "
    "Usa Markdown cuando ayude. No inventes información. "
    "Tienes memoria de largo plazo proporcionada por el sistema: úsala solo cuando sea relevante. "
    "Si una memoria contradice el mensaje actual del usuario, prioriza el mensaje actual."
)
MAX_MENSAJES = 16
MAX_CARACTERES = 70000
MAX_TEXTO_ARCHIVO = 40000
EXT_TEXTO = {"txt","md","csv","tsv","json","xml","html","htm","css","js","ts","py","java","c","cpp","cs","php","rb","go","rs","sql","yaml","yml","ini","log","sh","bat"}


def now():
    return datetime.now(timezone.utc).isoformat()


def profile_id():
    if not CLAVE_ACCESO:
        # For a public/no-key deployment, use a browser supplied id.
        return request.headers.get("X-Tampy-Profile", "public")[:120]
    return hashlib.sha256(CLAVE_ACCESO.encode()).hexdigest()[:32]


def autorizado():
    if not CLAVE_ACCESO:
        return True
    return hmac.compare_digest(request.headers.get("X-Clave", ""), CLAVE_ACCESO)


def db_kind():
    return "postgres" if USE_POSTGRES else "sqlite"


def sqlite_conn():
    c = sqlite3.connect(DATA_DIR / "tampy.db")
    c.row_factory = sqlite3.Row
    return c


def pg_conn():
    import psycopg
    from psycopg.rows import dict_row
    url = DATABASE_URL
    if url and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return psycopg.connect(url, autocommit=True, connect_timeout=10, row_factory=dict_row)


def init_db():
    if USE_POSTGRES:
        with pg_conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, title TEXT NOT NULL, messages JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conv_profile ON conversations(profile_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mem_profile ON memories(profile_id)")
    else:
        with sqlite_conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, title TEXT NOT NULL, messages TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conv_profile ON conversations(profile_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mem_profile ON memories(profile_id)")


try:
    if DATABASE_URL:
        try:
            init_db()
            USE_POSTGRES = True
            log.info("Memoria: PostgreSQL/Supabase activo")
        except Exception:
            USE_POSTGRES = False
            log.exception("No se pudo conectar a PostgreSQL/Supabase; se usará SQLite local como respaldo")
            init_db()
    else:
        init_db()
        log.info("Memoria: SQLite local activo")
except Exception:
    log.exception("No se pudo inicializar ninguna base de datos")


def save_conversation(cid, title, messages):
    pid = profile_id(); ts = now(); payload = json.dumps(messages, ensure_ascii=False)
    if USE_POSTGRES:
        with pg_conn() as c:
            exists = c.execute("SELECT id FROM conversations WHERE id=%s AND profile_id=%s", (cid,pid)).fetchone()
            if exists:
                c.execute("UPDATE conversations SET title=%s,messages=%s,updated_at=%s WHERE id=%s AND profile_id=%s", (title,payload,ts,cid,pid))
            else:
                c.execute("INSERT INTO conversations(id,profile_id,title,messages,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)", (cid,pid,title,payload,ts,ts))
    else:
        with sqlite_conn() as c:
            c.execute("INSERT OR REPLACE INTO conversations(id,profile_id,title,messages,created_at,updated_at) VALUES(?,?,?,?,COALESCE((SELECT created_at FROM conversations WHERE id=?),?),?)", (cid,pid,title,payload,cid,ts,ts))


def list_conversations():
    pid=profile_id()
    if USE_POSTGRES:
        with pg_conn() as c:
            rows=c.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE profile_id=%s ORDER BY updated_at DESC LIMIT 100",(pid,)).fetchall()
            return [dict(r) for r in rows]
    with sqlite_conn() as c:
        rows=c.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE profile_id=? ORDER BY updated_at DESC LIMIT 100",(pid,)).fetchall()
        return [dict(r) for r in rows]


def get_conversation(cid):
    pid=profile_id()
    if USE_POSTGRES:
        with pg_conn() as c: r=c.execute("SELECT id,title,messages,created_at,updated_at FROM conversations WHERE id=%s AND profile_id=%s",(cid,pid)).fetchone()
    else:
        with sqlite_conn() as c: r=c.execute("SELECT id,title,messages,created_at,updated_at FROM conversations WHERE id=? AND profile_id=?",(cid,pid)).fetchone()
    if not r: return None
    d=dict(r); d["messages"]=json.loads(d["messages"]) if isinstance(d["messages"],str) else d["messages"]; return d


def delete_conversation(cid):
    pid=profile_id()
    if USE_POSTGRES:
        with pg_conn() as c: c.execute("DELETE FROM conversations WHERE id=%s AND profile_id=%s",(cid,pid))
    else:
        with sqlite_conn() as c: c.execute("DELETE FROM conversations WHERE id=? AND profile_id=?",(cid,pid))


def add_memory(content, category="general"):
    mid=str(uuid.uuid4()); ts=now(); pid=profile_id()
    if USE_POSTGRES:
        with pg_conn() as c: c.execute("INSERT INTO memories(id,profile_id,content,category,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)",(mid,pid,content,category,ts,ts))
    else:
        with sqlite_conn() as c: c.execute("INSERT INTO memories VALUES(?,?,?,?,?,?)",(mid,pid,content,category,ts,ts))
    return mid


def list_memories():
    pid=profile_id()
    if USE_POSTGRES:
        with pg_conn() as c: rows=c.execute("SELECT id,content,category,created_at FROM memories WHERE profile_id=%s ORDER BY updated_at DESC LIMIT 200",(pid,)).fetchall()
    else:
        with sqlite_conn() as c: rows=c.execute("SELECT id,content,category,created_at FROM memories WHERE profile_id=? ORDER BY updated_at DESC LIMIT 200",(pid,)).fetchall()
    return [dict(r) for r in rows]


def delete_memory(mid):
    pid=profile_id()
    if USE_POSTGRES:
        with pg_conn() as c: c.execute("DELETE FROM memories WHERE id=%s AND profile_id=%s",(mid,pid))
    else:
        with sqlite_conn() as c: c.execute("DELETE FROM memories WHERE id=? AND profile_id=?",(mid,pid))


def extract_memory_candidates(user_text):
    # Conservative explicit-memory syntax. User can say: "Recuerda que ..." or "Recuerda: ..."
    m=re.search(r"\brecuerda(?: que|:)?\s+(.+)", user_text, re.I|re.S)
    if not m: return []
    content=re.sub(r"\s+"," ",m.group(1)).strip()
    if 8 <= len(content) <= 800:
        return [(content,"usuario")]
    return []


def memory_context():
    try:
        mems=list_memories()
    except Exception:
        log.exception("No se pudo leer la memoria; continúo sin memoria en esta petición")
        return ""
    if not mems: return ""
    return "\n\nMEMORIA DEL USUARIO (solo usa lo relevante):\n" + "\n".join(f"- [{m['category']}] {m['content']}" for m in mems[:80])


def extraer_texto(nombre, datos):
    ext=nombre.lower().rsplit('.',1)[-1] if '.' in nombre else ''
    if ext=='pdf':
        from pypdf import PdfReader
        lector=PdfReader(io.BytesIO(datos)); texto="\n\n".join((p.extract_text() or '') for p in lector.pages[:80])
        if not texto.strip(): raise ValueError('El PDF no tiene texto seleccionable. Súbelo como imagen si es un escaneo.')
    elif ext=='docx':
        import docx
        doc=docx.Document(io.BytesIO(datos)); partes=[p.text for p in doc.paragraphs]
        for tabla in doc.tables:
            for fila in tabla.rows: partes.append(' | '.join(c.text.strip() for c in fila.cells))
        texto='\n'.join(partes)
    elif ext in ('xlsx','xlsm'):
        from openpyxl import load_workbook
        libro=load_workbook(io.BytesIO(datos),read_only=True,data_only=True); partes=[]
        for hoja in list(libro.worksheets)[:8]:
            partes.append(f'## Hoja: {hoja.title}')
            for i,fila in enumerate(hoja.iter_rows(values_only=True)):
                if i>=1000: partes.append('... (más filas omitidas)'); break
                partes.append(' | '.join('' if v is None else str(v) for v in fila))
        texto='\n'.join(partes)
    elif ext in EXT_TEXTO:
        for codec in ('utf-8-sig','latin-1'):
            try: texto=datos.decode(codec); break
            except UnicodeDecodeError: continue
    else: raise ValueError(f'Formato .{ext or "?"} no soportado.')
    return texto[:MAX_TEXTO_ARCHIVO], len(texto)>MAX_TEXTO_ARCHIVO


def limpiar_mensajes(crudos):
    if not isinstance(crudos,list): raise ValueError('Formato de mensajes inválido.')
    out=[]
    for m in crudos[-MAX_MENSAJES:]:
        rol=m.get('role'); cont=m.get('content')
        if rol not in ('user','assistant'): continue
        if isinstance(cont,str): out.append({'role':rol,'content':cont})
        elif isinstance(cont,list) and rol=='user':
            parts=[]
            for p in cont:
                if p.get('type')=='text' and isinstance(p.get('text'),str): parts.append({'type':'text','text':p['text']})
                elif p.get('type')=='image_url':
                    url=(p.get('image_url') or {}).get('url','')
                    if url.startswith('data:image/'): parts.append({'type':'image_url','image_url':{'url':url}})
            if parts: out.append({'role':rol,'content':parts})
    last=max((i for i,m in enumerate(out) if m['role']=='user'),default=-1)
    for i,m in enumerate(out):
        if isinstance(m['content'],list) and i!=last:
            m['content']=' '.join(p.get('text','') for p in m['content'] if p['type']=='text')+'\n[imagen omitida]'
    def size(m):
        c=m['content']; return len(c) if isinstance(c,str) else sum(len(p.get('text','')) for p in c)
    while len(out)>1 and sum(size(m) for m in out)>MAX_CARACTERES: out.pop(0)
    while out and out[0]['role']!='user': out.pop(0)
    if not out: raise ValueError('No hay mensajes para procesar.')
    return out


def tiene_imagen(ms): return any(isinstance(m['content'],list) and any(p['type']=='image_url' for p in m['content']) for m in ms)

def modelo_no_disponible(e):
    t=str(e).lower(); return any(s in t for s in ('model_not_found','decommission','does not exist','not found','no longer supported'))


def consultar(mensajes):
    candidatos=MODELOS_VISION if tiene_imagen(mensajes) else MODELOS_TEXTO
    ultimo=None
    system={'role':'system','content':SYSTEM_BASE+memory_context()}
    for modelo in candidatos:
        try:
            r=client.chat.completions.create(model=modelo,messages=[system]+mensajes,temperature=.6,max_tokens=2500)
            texto=(r.choices[0].message.content or '').strip(); texto=re.sub(r'<think>.*?</think>','',texto,flags=re.S).strip()
            return texto or 'No obtuve respuesta del modelo.',modelo
        except Exception as e:
            ultimo=e
            if modelo_no_disponible(e): continue
            raise
    raise RuntimeError(f'Ningún modelo configurado está disponible en Groq. Último error: {ultimo}')


@app.route('/')
def index(): return render_template('index.html',requiere_clave=bool(CLAVE_ACCESO),storage=db_kind())
@app.route('/salud')
def salud(): return jsonify(ok=True,storage=db_kind())

@app.route('/diagnostico')
def diagnostico():
    db_ok=False
    db_error=''
    try:
        if USE_POSTGRES:
            with pg_conn() as c: c.execute('SELECT 1')
        else:
            with sqlite_conn() as c: c.execute('SELECT 1')
        db_ok=True
    except Exception as e:
        db_error=str(e)[:300]
    memoria_ok=False
    memoria_error=''
    try:
        list_memories()
        memoria_ok=True
    except Exception as e:
        memoria_error=str(e)[:300]
    return jsonify({
        'ok': bool(client) and db_ok and memoria_ok,
        'groq_configurada': bool(GROQ_API_KEY),
        'base_datos': db_kind(),
        'base_datos_ok': db_ok,
        'memoria_lectura_ok': memoria_ok,
        'database_url_configurada': bool(DATABASE_URL),
        'clave_tampy_configurada': bool(CLAVE_ACCESO),
        'modelo_texto': MODELOS_TEXTO[0] if MODELOS_TEXTO else None,
        'modelo_vision': MODELOS_VISION[0] if MODELOS_VISION else None,
        'detalle_bd': db_error,
        'detalle_memoria': memoria_error
    })

@app.route('/api/conversations',methods=['GET'])
def api_conversations():
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    return jsonify(conversaciones=list_conversations())

@app.route('/api/conversations/<cid>',methods=['GET','DELETE'])
def api_conversation(cid):
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    if request.method=='DELETE': delete_conversation(cid); return jsonify(ok=True)
    d=get_conversation(cid)
    return jsonify(d) if d else (jsonify(error='Conversación no encontrada.'),404)

@app.route('/api/conversations',methods=['POST'])
def api_save_conversation():
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    d=request.get_json(silent=True) or {}; msgs=d.get('mensajes',[]); cid=d.get('id') or str(uuid.uuid4()); title=(d.get('title') or 'Nueva conversación')[:120]
    save_conversation(cid,title,msgs); return jsonify(id=cid)

@app.route('/api/memories',methods=['GET','POST'])
def api_memories():
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    if request.method=='GET': return jsonify(memories=list_memories())
    d=request.get_json(silent=True) or {}; content=str(d.get('content','')).strip(); category=str(d.get('category','general'))[:50]
    if not content or len(content)>1000: return jsonify(error='Memoria inválida.'),400
    return jsonify(id=add_memory(content,category))

@app.route('/api/memories/<mid>',methods=['DELETE'])
def api_memory(mid):
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    delete_memory(mid); return jsonify(ok=True)

@app.route('/api/archivo',methods=['POST'])
def api_archivo():
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    f=request.files.get('archivo')
    if not f or not f.filename: return jsonify(error='No llegó ningún archivo.'),400
    raw=f.read()
    try: texto,truncado=extraer_texto(f.filename,raw)
    except Exception as e: return jsonify(error=str(e)),400
    # Store a local copy only when using local storage. Cloud file storage is an optional next step.
    if not USE_POSTGRES:
        safe=re.sub(r'[^A-Za-z0-9._-]','_',f.filename)[:100]
        (UPLOAD_DIR / f"{uuid.uuid4().hex}_{safe}").write_bytes(raw)
    return jsonify(nombre=f.filename,texto=texto,truncado=truncado)

@app.route('/api/chat',methods=['POST'])
def api_chat():
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    if client is None: return jsonify(error='Falta GROQ_API_KEY.'),500
    try:
        mensajes=limpiar_mensajes((request.get_json(silent=True) or {}).get('mensajes'))
        # Explicit memory command: store and also continue the conversation.
        for item in mensajes:
            if item['role']=='user' and isinstance(item['content'],str):
                for content,cat in extract_memory_candidates(item['content']):
                    try: add_memory(content,cat)
                    except Exception: log.exception('No se pudo guardar una memoria; continúo con la respuesta')
        texto,modelo=consultar(mensajes)
        return jsonify(respuesta=texto,modelo=modelo)
    except Exception as e:
        log.exception('Error /api/chat'); t=str(e).lower()
        if ('rate' in t and 'limit' in t) or '429' in t: return jsonify(error='Llegaste al límite de Groq. Intenta de nuevo en un momento.'),429
        if 'invalid api key' in t or '401' in t: return jsonify(error='La API key de Groq es inválida o fue revocada.'),500
        return jsonify(error=f'Error del modelo: {e}'),500


def md_to_plain(md):
    s=re.sub(r'```[\s\S]*?```',lambda m:'\n'+m.group(0)+'\n',md)
    s=re.sub(r'[#*_>`]','',s); return s

@app.route('/api/export',methods=['POST'])
def api_export():
    if not autorizado(): return jsonify(error='Clave incorrecta.'),401
    d=request.get_json(silent=True) or {}; text=str(d.get('text','')); fmt=str(d.get('format','txt')).lower()
    if not text: return jsonify(error='No hay contenido para exportar.'),400
    name=re.sub(r'[^A-Za-z0-9_-]','_',str(d.get('name','TAMPY_documento')))[:60]
    try:
        if fmt=='txt':
            bio=io.BytesIO(text.encode('utf-8')); mime='text/plain; charset=utf-8'; ext='txt'
        elif fmt=='docx':
            from docx import Document
            doc=Document();
            for line in text.splitlines(): doc.add_paragraph(md_to_plain(line))
            bio=io.BytesIO(); doc.save(bio); bio.seek(0); mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'; ext='docx'
        elif fmt=='pdf':
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from xml.sax.saxutils import escape
            bio=io.BytesIO(); doc=SimpleDocTemplate(bio,pagesize=A4,rightMargin=40,leftMargin=40,topMargin=40,bottomMargin=40); styles=getSampleStyleSheet(); story=[]
            for line in text.splitlines():
                line=line.strip()
                if not line: story.append(Spacer(1,8)); continue
                story.append(Paragraph(escape(md_to_plain(line)),styles['BodyText'])); story.append(Spacer(1,4))
            doc.build(story); bio.seek(0); mime='application/pdf'; ext='pdf'
        elif fmt=='xlsx':
            from openpyxl import Workbook
            wb=Workbook(); ws=wb.active; ws.title='TAMPY';
            for i,line in enumerate(text.splitlines(),1): ws.cell(i,1,md_to_plain(line))
            ws.column_dimensions['A'].width=120; bio=io.BytesIO(); wb.save(bio); bio.seek(0); mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'; ext='xlsx'
        else: return jsonify(error='Formato no soportado.'),400
        return send_file(bio,as_attachment=True,download_name=f'{name}.{ext}',mimetype=mime)
    except Exception as e:
        log.exception('Export error'); return jsonify(error=str(e)),500


if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
