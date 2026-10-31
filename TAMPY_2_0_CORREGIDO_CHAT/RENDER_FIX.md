# TAMPY 2.0 - Render

## Si Render muestra: No such file or directory: requirements.txt
Esto significa que Render está ejecutando el build en una carpeta que no contiene requirements.txt.

### Opción 1 (recomendada si el repositorio contiene una carpeta `tampy`)
En Render > Settings > Build & Deploy > Root Directory, escribe:
`tampy`

Deja:
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`

### Opción 2
Sube los archivos de este ZIP directamente a la raíz del repositorio, de modo que `app.py` y `requirements.txt` queden al mismo nivel.

## Variables de entorno
- GROQ_API_KEY = tu clave de Groq
- TAMPY_CLAVE = tu clave privada larga
- DATABASE_URL = conexión PostgreSQL de Supabase
- MODELO_TEXTO = modelo de texto de Groq
- MODELO_VISION = modelo de visión de Groq

No subas `.env` a GitHub.
