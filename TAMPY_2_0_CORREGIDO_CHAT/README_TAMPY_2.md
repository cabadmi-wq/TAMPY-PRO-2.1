# TAMPY 2.0 - memoria, historial y documentos

## Qué incluye
- Memoria permanente con SQLite local o PostgreSQL remoto.
- Historial de conversaciones guardado y recuperable desde cualquier dispositivo cuando se usa PostgreSQL + la misma TAMPY_CLAVE.
- Panel de memoria para agregar/eliminar recuerdos.
- Comando explícito: "Recuerda que ...".
- Lectura de PDF, DOCX, XLSX, CSV, TXT y código.
- Descarga de respuestas en TXT, Word, PDF y Excel.
- Interfaz con historial y memoria.
- Arquitectura híbrida: si no hay DATABASE_URL, funciona gratis y local con SQLite; si existe DATABASE_URL, usa PostgreSQL.

## Opción 100% local
1. Instala Python 3.11+.
2. Abre terminal en la carpeta donde está app.py.
3. Ejecuta: `pip install -r requirements.txt`
4. Copia `.env.example` como `.env` (o configura las variables en Windows).
5. Ejecuta: `python app.py`
6. Abre `http://127.0.0.1:5000`.
7. La memoria estará en `data/tampy.db`.

## Opción gratuita para usar desde cualquier lugar: Render + Supabase
Render Free NO debe usarse para guardar SQLite: su filesystem es efímero y se pierde al redeploy/restart/spin-down. En cambio, Render puede conectarse a una base PostgreSQL externa. Supabase ofrece un plan gratuito con 500 MB de base de datos y 1 GB de file storage, sujeto a sus límites y pausa por inactividad.

### Supabase
1. Crea una cuenta en Supabase.
2. Crea un proyecto Free.
3. Abre Connect / Database y copia la connection string de Postgres (usa la recomendada para tu entorno).
4. Esa cadena va en `DATABASE_URL`.
5. No publiques `DATABASE_URL` en GitHub.

### Render
1. Sube esta carpeta a GitHub.
2. En Render crea Web Service desde GitHub.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app`
5. Plan: Free.
6. Environment variables:
   - `GROQ_API_KEY` = tu clave de Groq
   - `TAMPY_CLAVE` = una clave privada larga. Debe ser EXACTAMENTE la misma en todos tus dispositivos.
   - `DATABASE_URL` = connection string de Supabase
   - `MODELO_TEXTO` = modelo vigente de Groq que quieras usar
   - `MODELO_VISION` = modelo de visión vigente de Groq
7. Deploy.

No agregues Persistent Disk en Render Free. Los Persistent Disks son de servicios de pago. La memoria estará en Supabase Postgres.

## Cómo funciona la identidad
Cuando TAMPY_CLAVE está configurada, el servidor deriva un identificador de perfil de esa clave. Por eso, si abres TAMPY desde PC, iPhone u otro navegador y usas la misma clave, todos acceden al mismo perfil de memoria e historial.

## Prueba de memoria
1. Abre TAMPY.
2. Escribe: `Recuerda que mi proyecto se llama TAMPY.`
3. Cierra la página.
4. Abre TAMPY en otro dispositivo usando la misma URL y clave.
5. Abre 🧠 Memoria o pregunta algo relacionado.

## Documentos descargables
Cada respuesta de TAMPY tiene botones TXT, Word, PDF y Excel. La generación ocurre bajo demanda y el archivo se descarga directamente al dispositivo.

## Importante sobre archivos subidos
En modo local, los archivos se guardan en `data/uploads/`. En modo PostgreSQL remoto, esta versión conserva la memoria y conversaciones en la nube, pero los archivos binarios originales no se sincronizan todavía a una nube de objetos. Para una biblioteca de documentos accesible desde cualquier dispositivo, la siguiente ampliación recomendada es Supabase Storage (1 GB incluido en el plan Free), con bucket privado y URLs firmadas.

## Seguridad
- Nunca subas `.env` ni claves a GitHub.
- Usa una `TAMPY_CLAVE` larga y privada.
- No uses una API key de Groq directamente en el navegador.
- Si publicas TAMPY en Internet, usa HTTPS (Render lo proporciona para su subdominio).


## Diagnóstico Render
Abre `https://TU-DOMINIO.onrender.com/diagnostico` para comprobar sin exponer secretos si Groq, la base de datos y la clave de TAMPY están configuradas.
