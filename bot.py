import os
import urllib.parse
import json
import requests
import xml.etree.ElementTree as ET
import re
import time
from datetime import datetime
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

# ⚙️ CONFIGURACIÓN
MODO_TURBO = True
NOTICIAS_POR_CARRERA = 4 if MODO_TURBO else 1

RSS_FEEDS = [
    "https://aristeguinoticias.com/feed/",
    "https://www.proceso.com.mx/rss/feed.html",
    "https://www.jornada.com.mx/rss/edicion.xml?v=1",
    "https://milenio.com/rss",
    "https://www.eluniversal.com.mx/rss.xml",
]

JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/124.0.0.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-MX,es;q=0.9,en;q=0.8',
}

session = requests.Session()
session.headers.update(HEADERS)

def cargar_noticias():
    if not os.path.exists(JSON_PATH): return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def guardar_noticias(noticias):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def limpiar_titulo(titulo):
    if not titulo:
        return ""
    titulo = re.sub(r'\s+', ' ', titulo).strip()
    titulo = re.sub(r'\.{2,}$', '', titulo).strip()
    titulo = titulo.replace('"', "'").replace('\\', '')
    return titulo[:200]

def extraer_imagen_de_articulo(url_real):
    if not url_real:
        return None
    try:
        r = session.get(url_real, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        selectores = [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"},
            {"name": "twitter:image:src"},
        ]
        for sel in selectores:
            meta = soup.find("meta", attrs=sel)
            if meta and meta.get("content"):
                img = meta.get("content")
                if ('logo' not in img.lower() and 'icon' not in img.lower()
                        and len(img) > 10 and img.startswith('http')):
                    return urljoin(url_real, img)
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-lazy-src")
            if (src and len(src) > 40
                    and 'logo' not in src.lower()
                    and 'icon' not in src.lower()
                    and 'avatar' not in src.lower()
                    and 'placeholder' not in src.lower()):
                return urljoin(url_real, src)
    except Exception as e:
        print(f"   ⚠️ Error extrayendo imagen: {e}")
    return None

def imagen_fallback(titulo):
    seed = abs(hash(titulo)) % 9999
    return f"https://picsum.photos/seed/{seed}/800/500"

def obtener_imagen(titulo, url_real):
    print(f"   🌐 URL: {url_real[:65]}...")
    img = extraer_imagen_de_articulo(url_real)
    if img:
        print(f"   🖼️ Imagen extraída ✅")
        url_segura = urllib.parse.quote(img, safe='')
        return f"https://wsrv.nl/?url={url_segura}", url_real
    print(f"   ⚠️ Sin imagen, usando fallback")
    return imagen_fallback(titulo), url_real

def reescribir_con_ia(titulo_orig):
    if not GROQ_API_KEY:
        return titulo_orig, "Noticia reciente.", "Detalles en el enlace original."

    titulo_limpio = limpiar_titulo(titulo_orig)

    if len(titulo_limpio.split()) < 3:
        print(f"   ⚠️ Título demasiado corto, saltando IA")
        return titulo_limpio, "Noticia en desarrollo.", "Consulta el enlace original para más detalles."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # ── PROMPT MEJORADO PARA ADSENSE ──
    prompt = f"""Tienes frente a ti el siguiente titular de un medio mexicano:

"{titulo_limpio}"

Redacta una nota periodística completa como si fuera escrita por un reportero mexicano experimentado de 45 años que lleva 20 años cubriendo noticias nacionales. Usa su voz natural: directa, sin adornos, con oraciones cortas y variadas. Mezcla párrafos largos con párrafos cortos. Incluye frases coloquiales mexicanas ocasionalmente ("cabe destacar", "en ese sentido", "al respecto"). Varía la estructura de los párrafos para que no suenen repetitivos.

La nota debe incluir:
- Titular: claro, informativo, máximo 85 caracteres, sin signos de exclamación
- Resumen: 2-3 oraciones que respondan qué pasó y por qué importa. Entre 60 y 100 palabras
- Contenido: nota completa de entre 400 y 600 palabras con:
  * Primer párrafo: el hecho central (quién, qué, cuándo, dónde)
  * Segundo y tercer párrafo: contexto y antecedentes
  * Cuarto párrafo: reacciones o declaraciones probables de los involucrados (usa "señaló", "indicó", "expresó")
  * Quinto párrafo: impacto en la población o en el país
  * Párrafo de cierre: perspectiva a corto plazo
  * Separa cada párrafo con una línea en blanco
  * NO uses listas ni bullets
  * NO uses encabezados dentro del contenido

Responde ÚNICAMENTE con un objeto JSON con estas claves exactas: titulo, resumen, contenido."""

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": "Eres un editor de noticias mexicano. Tu única función es devolver un JSON válido con las claves titulo, resumen y contenido. No añades texto fuera del JSON. No usas markdown. No explicas nada."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.85,
        "max_tokens": 1800
    }

    for intento in range(2):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=45)
            res = r.json()

            if 'choices' not in res:
                msg = res.get('error', {}).get('message', 'Error desconocido')
                print(f"   ⚠️ API Groq Error (intento {intento+1}): {msg}")
                time.sleep(5)
                continue

            contenido_crudo = res['choices'][0]['message']['content']
            contenido_crudo = re.sub(r'^```json\s*', '', contenido_crudo.strip())
            contenido_crudo = re.sub(r'```$', '', contenido_crudo.strip())

            data = json.loads(contenido_crudo)
            titulo  = limpiar_titulo(data.get("titulo", titulo_limpio))
            resumen  = data.get("resumen", "Noticia importante de México.")
            contenido = data.get("contenido", "Revisa el enlace original para más detalles.")

            # Si el contenido es muy corto, añadir el resumen al final
            if len(contenido.split()) < 150:
                contenido += "\n\n" + resumen

            return titulo, resumen, contenido

        except json.JSONDecodeError as e:
            print(f"   ⚠️ JSON inválido (intento {intento+1}): {e}")
            time.sleep(5)
        except Exception as e:
            print(f"⚠️ Error IA (intento {intento+1}): {e}")
            time.sleep(5)

    return titulo_limpio, "Noticia importante de México.", "Revisa el enlace original para más detalles."

def ejecutar():
    noticias_guardadas = cargar_noticias()
    nuevos = 0
    noticias_procesadas = 0

    for feed_url in RSS_FEEDS:
        if noticias_procesadas >= NOTICIAS_POR_CARRERA:
            break

        print(f"\n📡 Leyendo feed: {feed_url}")
        try:
            res = session.get(feed_url, timeout=10)
            res.encoding = res.apparent_encoding
            root = ET.fromstring(res.text)
        except Exception as e:
            print(f"❌ Error leyendo feed {feed_url}: {e}")
            continue

        for item in root.findall(".//item"):
            if noticias_procesadas >= NOTICIAS_POR_CARRERA:
                break

            t_orig = item.find("title")
            if t_orig is None or not t_orig.text:
                continue
            t_orig = t_orig.text

            if len(limpiar_titulo(t_orig).split()) < 4:
                print(f"   ⏭️ Saltando título muy corto: {t_orig[:40]}")
                continue

            link_elem = item.find("link")
            link_directo = ""
            if link_elem is not None and link_elem.text:
                link_directo = link_elem.text
            else:
                for child in item:
                    if child.tag == 'link' and child.tail:
                        link_directo = child.tail.strip()
                        break

            if not link_directo:
                guid = item.find("guid")
                if guid is not None and guid.text:
                    link_directo = guid.text

            if any(n.get('titulo_original') == t_orig for n in noticias_guardadas):
                continue

            print(f"\n🔄 Procesando: {t_orig[:60]}...")
            t_ia, r_ia, c_ia = reescribir_con_ia(t_orig)
            img_url, url_real = obtener_imagen(t_ia, link_directo)

            nuevo_id = max([n.get("id", 0) for n in noticias_guardadas], default=0) + 1
            noticias_guardadas.append({
                "id": nuevo_id,
                "titulo_original": t_orig,
                "titulo": t_ia,
                "resumen": r_ia,
                "contenido": c_ia,
                "imagen": img_url,
                "fecha": datetime.today().strftime('%Y-%m-%d'),
                "url_origen": url_real
            })
            nuevos += 1
            noticias_procesadas += 1
            print(f"✅ Guardada: {t_ia[:50]} ({len(c_ia.split())} palabras)")

            if noticias_procesadas < NOTICIAS_POR_CARRERA:
                time.sleep(11)

    if nuevos > 0:
        if len(noticias_guardadas) > 100:
            noticias_guardadas = noticias_guardadas[-100:]
        guardar_noticias(noticias_guardadas)
        print(f"\n💾 Guardadas {nuevos} noticias nuevas.")
    else:
        print("ℹ️ No hay noticias nuevas.")

if __name__ == "__main__":
    ejecutar()
