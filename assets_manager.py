"""
assets_manager.py
-----------------
Gestiona la copia local de assets (Mermaid.js, MathJax, etc).

Al llamar a `start_background_update_check()`, se lanza un hilo que:
  1. Consulta la API de jsDelivr para saber el último release de cada asset.
  2. Compara con la versión local.
  3. Si es diferente, descarga el nuevo archivo y actualiza la versión.

La aplicación siempre arranca con las copias locales disponibles; si falta alguna, 
usa un fallback de CDN para no bloquear la visualización.
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
BUNDLED_ASSETS_DIR = os.path.join(paths_util.get_base_path(), 'assets')

# Mermaid
MERMAID_JS_PATH = os.path.join(ASSETS_DIR, 'mermaid.min.js')
MERMAID_VERSION_PATH = os.path.join(ASSETS_DIR, 'mermaid.version')
BUNDLED_MERMAID_JS_PATH = os.path.join(BUNDLED_ASSETS_DIR, 'mermaid.min.js')
MERMAID_RESOLVE_URL = 'https://data.jsdelivr.net/v1/packages/npm/mermaid/resolved?specifier=%5E11'
MERMAID_DOWNLOAD_URL = 'https://cdn.jsdelivr.net/npm/mermaid@{version}/dist/mermaid.min.js'
MERMAID_CDN_FALLBACK = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js'

# MathJax
MATHJAX_JS_PATH = os.path.join(ASSETS_DIR, 'mathjax.js')
MATHJAX_VERSION_PATH = os.path.join(ASSETS_DIR, 'mathjax.version')
BUNDLED_MATHJAX_JS_PATH = os.path.join(BUNDLED_ASSETS_DIR, 'mathjax.js')
MATHJAX_RESOLVE_URL = 'https://data.jsdelivr.net/v1/packages/npm/mathjax/resolved?specifier=%5E3'
MATHJAX_DOWNLOAD_URL = 'https://cdn.jsdelivr.net/npm/mathjax@{version}/es5/tex-mml-chtml.min.js'
MATHJAX_CDN_FALLBACK = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.min.js'

TIMEOUT_SECONDS = 10

# Contexto SSL usando los certificados de certifi (fix para macOS)
SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _get_local_version(path: str) -> str:
    """Lee la versión guardada localmente. Devuelve '' si no existe."""
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def _get_remote_version(url: str) -> str:
    """Consulta jsDelivr para obtener el último release."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'md-prev/1.0'})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode())
            return data['version']
    except Exception as e:
        logger.warning(f'[assets_manager] Error al obtener versión remota: {e}')
        return ''


def _download_asset(asset_name: str, url: str, target_path: str, version_path: str, version: str) -> None:
    """Descarga un asset y actualiza su archivo de versión."""
    logger.info(f'[assets_manager] Descargando {asset_name}@{version}...')

    os.makedirs(ASSETS_DIR, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'md-prev/1.0'})
    with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
        content = resp.read()

    # Escribir el JS y la versión de forma atómica (temp file → rename)
    tmp_js = target_path + '.tmp'
    with open(tmp_js, 'wb') as f:
        f.write(content)
    os.replace(tmp_js, target_path)

    with open(version_path, 'w') as f:
        f.write(version)

    logger.info(f'[assets_manager] {asset_name}@{version} guardado ({len(content):,} bytes).')


def _update_asset(name: str, resolve_url: str, download_url_tmpl: str, target_path: str, version_path: str, fallback_version: str) -> None:
    """Lógica genérica para actualizar un asset con fallback si falla la resolución."""
    try:
        remote = _get_remote_version(resolve_url)
        if not remote:
            logger.warning(f'[assets_manager] No se pudo resolver la versión para {name}. Usando fallback: {fallback_version}')
            remote = fallback_version

        local = _get_local_version(version_path)
        if local == remote and os.path.exists(target_path):
            logger.info(f'[assets_manager] {name}@{local} está al día.')
            return

        logger.info(f'[assets_manager] Intentando descargar/actualizar {name}: {remote} (local: {local or "ninguna"}).')
        download_url = download_url_tmpl.format(version=remote)
        _download_asset(name, download_url, target_path, version_path, remote)
        print(f'[md-prev] {name} actualizado a {remote}. Tomará efecto en el próximo arranque.')
    except Exception as e:
        logger.error(f'[assets_manager] Error crítico al actualizar {name}: {e}')


def _update_check_worker() -> None:
    """Worker que corre en background. No lanza excepciones al hilo principal."""
    # Actualizar Mermaid (Fallback a 11.4.0)
    _update_asset('Mermaid', MERMAID_RESOLVE_URL, MERMAID_DOWNLOAD_URL, MERMAID_JS_PATH, MERMAID_VERSION_PATH, '11.4.0')
    # Actualizar MathJax (Fallback a 3.2.2)
    _update_asset('MathJax', MATHJAX_RESOLVE_URL, MATHJAX_DOWNLOAD_URL, MATHJAX_JS_PATH, MATHJAX_VERSION_PATH, '3.2.2')


def start_background_update_check() -> None:
    """Lanza el check de actualización en un hilo daemon. No bloquea el arranque."""
    t = threading.Thread(target=_update_check_worker, daemon=True, name='assets-update-check')
    t.start()


def _get_asset_content(local_path: str, bundled_path: str, cdn_url: str, name: str) -> str:
    """Lógica estandarizada para obtener el contenido de un asset con fallback a CDN."""
    if os.path.exists(local_path):
        path_to_load = local_path
    elif os.path.exists(bundled_path):
        path_to_load = bundled_path
    else:
        logger.info(f'[assets_manager] {name} no encontrado localmente. Usando fallback de CDN.')
        return f"""
        (function() {{
            var script = document.createElement('script');
            script.src = '{cdn_url}';
            script.async = true;
            document.head.appendChild(script);
        }})();
        """
        
    with open(path_to_load, 'r', encoding='utf-8') as f:
        return f.read()


def get_mermaid_script() -> str:
    """Devuelve el contenido de mermaid.min.js (local o CDN loader)."""
    return _get_asset_content(MERMAID_JS_PATH, BUNDLED_MERMAID_JS_PATH, MERMAID_CDN_FALLBACK, 'mermaid.min.js')


def get_mathjax_script() -> str:
    """Devuelve el contenido de mathjax.js (local o CDN loader)."""
    return _get_asset_content(MATHJAX_JS_PATH, BUNDLED_MATHJAX_JS_PATH, MATHJAX_CDN_FALLBACK, 'mathjax.js')
