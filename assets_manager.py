"""
assets_manager.py
-----------------
Gestiona la copia local de Mermaid.js.

Al llamar a `start_background_update_check()`, se lanza un hilo que:
  1. Consulta la API de jsDelivr para saber el último release de mermaid ^11.
  2. Compara con la versión en assets/mermaid.version.
  3. Si es diferente, descarga el nuevo mermaid.min.js y actualiza el archivo de versión.

La aplicación siempre arranca con la copia local disponible; la descarga es transparente
y sólo toma efecto en el próximo arranque (no recarga la ventana en caliente).
"""

import os
import threading
import urllib.request
import json
import logging
import ssl
import certifi
import paths_util

logger = logging.getLogger(__name__)

APP_SUPPORT_DIR = paths_util.get_app_support_path()
ASSETS_DIR = os.path.join(APP_SUPPORT_DIR, 'assets')
MERMAID_JS_PATH = os.path.join(ASSETS_DIR, 'mermaid.min.js')
MERMAID_VERSION_PATH = os.path.join(ASSETS_DIR, 'mermaid.version')

BUNDLED_ASSETS_DIR = os.path.join(paths_util.get_base_path(), 'assets')
BUNDLED_MERMAID_JS_PATH = os.path.join(BUNDLED_ASSETS_DIR, 'mermaid.min.js')

JSDELIVR_RESOLVE_URL = 'https://data.jsdelivr.com/v1/packages/npm/mermaid/resolved?specifier=%5E11'
JSDELIVR_DOWNLOAD_URL = 'https://cdn.jsdelivr.net/npm/mermaid@{version}/dist/mermaid.min.js'

TIMEOUT_SECONDS = 10

# Contexto SSL usando los certificados de certifi (fix para macOS)
SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _get_local_version() -> str:
    """Lee la versión guardada localmente. Devuelve '' si no existe."""
    try:
        with open(MERMAID_VERSION_PATH, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def _get_remote_version() -> str:
    """Consulta jsDelivr para obtener el último release de mermaid ^11."""
    req = urllib.request.Request(JSDELIVR_RESOLVE_URL, headers={'User-Agent': 'md-prev/1.0'})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode())
        return data['version']


def _download_mermaid(version: str) -> None:
    """Descarga mermaid.min.js para la versión dada y actualiza el archivo de versión."""
    url = JSDELIVR_DOWNLOAD_URL.format(version=version)
    logger.info(f'[assets_manager] Descargando mermaid@{version}...')

    os.makedirs(ASSETS_DIR, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'md-prev/1.0'})
    with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
        content = resp.read()

    # Escribir el JS y la versión de forma atómica (temp file → rename)
    tmp_js = MERMAID_JS_PATH + '.tmp'
    with open(tmp_js, 'wb') as f:
        f.write(content)
    os.replace(tmp_js, MERMAID_JS_PATH)

    with open(MERMAID_VERSION_PATH, 'w') as f:
        f.write(version)

    logger.info(f'[assets_manager] mermaid@{version} guardado ({len(content):,} bytes).')


def _update_check_worker() -> None:
    """Worker que corre en background. No lanza excepciones al hilo principal."""
    try:
        local = _get_local_version()
        remote = _get_remote_version()

        if local == remote:
            logger.info(f'[assets_manager] mermaid@{local} está al día.')
            return

        logger.info(f'[assets_manager] Nueva versión disponible: {remote} (local: {local or "ninguna"}).')
        _download_mermaid(remote)
        print(f'[md-prev] Mermaid actualizado a {remote}. Tomará efecto en el próximo arranque.')
    except Exception as e:
        # Fallo silencioso: la copia local sigue siendo válida.
        logger.warning(f'[assets_manager] Error al verificar actualizaciones: {e}')


def start_background_update_check() -> None:
    """Lanza el check de actualización en un hilo daemon. No bloquea el arranque."""
    t = threading.Thread(target=_update_check_worker, daemon=True, name='mermaid-update-check')
    t.start()


def get_mermaid_script() -> str:
    """
    Devuelve el contenido de mermaid.min.js para ser embebido inline.
    Prioriza la versión en Application Support, con fallback al bundle.
    Si el archivo local no existe, devuelve un script vacío y loggea un warning.
    """
    if os.path.exists(MERMAID_JS_PATH):
        path_to_load = MERMAID_JS_PATH
    elif os.path.exists(BUNDLED_MERMAID_JS_PATH):
        path_to_load = BUNDLED_MERMAID_JS_PATH
    else:
        logger.warning('[assets_manager] mermaid.min.js no encontrado en assets/. Ejecuta el setup.')
        return '/* mermaid.min.js no encontrado */'
        
    with open(path_to_load, 'r', encoding='utf-8') as f:
        return f.read()
