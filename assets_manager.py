"""
assets_manager.py
-----------------
Gestiona la copia local de assets (Mermaid.js, MathJax, etc).
Soporta dependencias compuestas (como MathJax y sus extensiones) para asegurar 100% offline.
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

# MathJax Core
MATHJAX_JS_PATH = os.path.join(ASSETS_DIR, 'mathjax.js')
MATHJAX_VERSION_PATH = os.path.join(ASSETS_DIR, 'mathjax.version')
BUNDLED_MATHJAX_JS_PATH = os.path.join(BUNDLED_ASSETS_DIR, 'mathjax.js')
MATHJAX_RESOLVE_URL = 'https://data.jsdelivr.net/v1/packages/npm/mathjax/resolved?specifier=%5E3'
MATHJAX_DOWNLOAD_URL = 'https://cdn.jsdelivr.net/npm/mathjax@{version}/es5/tex-mml-chtml.min.js'
MATHJAX_CDN_FALLBACK = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.min.js'

# MathJax Extensions
MATHJAX_EXT_DIR = os.path.join(ASSETS_DIR, 'mathjax_ext')
MATHJAX_EXTENSIONS = ['textmacros', 'physics', 'color', 'ams', 'nounderscore']
# URL base para extensiones: https://cdn.jsdelivr.net/npm/mathjax@3/es5/input/tex/extensions/{name}.js

TIMEOUT_SECONDS = 10
SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _get_local_version(path: str) -> str:
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def _get_remote_version(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'md-prev/1.0'})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode())
            return data['version']
    except Exception as e:
        logger.debug(f'[assets_manager] No se pudo consultar la versión remota: {e}')
        return ''


def _download_file(url: str, target_path: str) -> bool:
    """Descarga un archivo a una ruta específica."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'md-prev/1.0'})
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            content = resp.read()
        
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f'[assets_manager] Error descargando {url}: {e}')
        return False


def _update_asset(name: str, resolve_url: str, download_url_tmpl: str, target_path: str, version_path: str, fallback_version: str) -> None:
    try:
        remote = _get_remote_version(resolve_url)
        if not remote:
            remote = fallback_version

        local = _get_local_version(version_path)
        if local == remote and os.path.exists(target_path):
            return

        download_url = download_url_tmpl.format(version=remote)
        if _download_file(download_url, target_path):
            with open(version_path, 'w') as f:
                f.write(remote)
            logger.info(f'[assets_manager] {name} actualizado a {remote}.')
    except Exception as e:
        logger.error(f'[assets_manager] Error actualizando {name}: {e}')


def _update_mathjax_extensions(version: str):
    """Descarga las extensiones de MathJax para la versión dada."""
    os.makedirs(MATHJAX_EXT_DIR, exist_ok=True)
    for ext in MATHJAX_EXTENSIONS:
        ext_path = os.path.join(MATHJAX_EXT_DIR, f'{ext}.js')
        if os.path.exists(ext_path):
            continue
            
        url = f'https://cdn.jsdelivr.net/npm/mathjax@{version}/es5/input/tex/extensions/{ext}.js'
        logger.info(f'[assets_manager] Descargando extensión MathJax: {ext}...')
        _download_file(url, ext_path)


def _update_check_worker() -> None:
    # Mermaid
    _update_asset('Mermaid', MERMAID_RESOLVE_URL, MERMAID_DOWNLOAD_URL, MERMAID_JS_PATH, MERMAID_VERSION_PATH, '11.4.0')
    
    # MathJax Core
    _update_asset('MathJax', MATHJAX_RESOLVE_URL, MATHJAX_DOWNLOAD_URL, MATHJAX_JS_PATH, MATHJAX_VERSION_PATH, '3.2.2')
    
    # Extensiones de MathJax
    mj_version = _get_local_version(MATHJAX_VERSION_PATH) or '3.2.2'
    _update_mathjax_extensions(mj_version)


def start_background_update_check() -> None:
    t = threading.Thread(target=_update_check_worker, daemon=True, name='assets-update-check')
    t.start()


def get_mermaid_script() -> str:
    if os.path.exists(MERMAID_JS_PATH):
        path = MERMAID_JS_PATH
    elif os.path.exists(BUNDLED_MERMAID_JS_PATH):
        path = BUNDLED_MERMAID_JS_PATH
    else:
        return f"(function(){{var s=document.createElement('script');s.src='{MERMAID_CDN_FALLBACK}';document.head.appendChild(s);}})();"
    
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def get_mathjax_script() -> str:
    """Retorna un bundle que incluye MathJax Core + todas las extensiones locales."""
    scripts = []
    
    # 1. Cargar el Core
    if os.path.exists(MATHJAX_JS_PATH):
        core_path = MATHJAX_JS_PATH
    elif os.path.exists(BUNDLED_MATHJAX_JS_PATH):
        core_path = BUNDLED_MATHJAX_JS_PATH
    else:
        # Fallback a CDN solo para el core si nada existe
        scripts.append(f"(function(){{var s=document.createElement('script');s.src='{MATHJAX_CDN_FALLBACK}';document.head.appendChild(s);}})();")
        return "\n".join(scripts)

    with open(core_path, 'r', encoding='utf-8') as f:
        scripts.append(f.read())

    # 2. Cargar Extensiones locales si existen
    ext_count = 0
    if os.path.exists(MATHJAX_EXT_DIR):
        for ext_file in os.listdir(MATHJAX_EXT_DIR):
            if ext_file.endswith('.js'):
                ext_path = os.path.join(MATHJAX_EXT_DIR, ext_file)
                with open(ext_path, 'r', encoding='utf-8') as f:
                    scripts.append(f"\n/* Extension: {ext_file} */\n")
                    scripts.append(f.read())
                    ext_count += 1
    
    if ext_count > 0:
        logger.debug(f'[assets_manager] MathJax bundle generado con {ext_count} extensiones locales.')
                    
    return "\n".join(scripts)
