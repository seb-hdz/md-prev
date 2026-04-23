import sys
import importlib.util
import html.parser
import os

# --- Parche para compatibilidad de Markdown con py2app / Python 3.13 ---
# Evita el error "AttributeError: 'NoneType' object has no attribute 'loader'"
# al intentar cargar html.parser dentro del bundle.
_orig_find_spec = importlib.util.find_spec
def _patched_find_spec(name, package=None):
    spec = _orig_find_spec(name, package)
    if name == 'html.parser' and spec is None:
        return importlib.util.spec_from_loader(name, html.parser.__loader__)
    return spec
importlib.util.find_spec = _patched_find_spec
# -----------------------------------------------------------------------

import re
import markdown
from pygments.formatters import HtmlFormatter
import os
import logging
import assets_manager

logger = logging.getLogger(__name__)

# Regex para capturar bloques ```mermaid ... ``` antes de que el parser los toque.
# Soporta tanto ``` como ~~~, con o sin espacios antes de la etiqueta.
MERMAID_FENCE_RE = re.compile(
    r'^(?P<fence>`{3}|~{3})\s*mermaid\s*\n(?P<code>.*?)^(?P=fence)\s*$',
    re.MULTILINE | re.DOTALL
)

import paths_util

_MERMAID_PLACEHOLDER = '<!-- __MERMAID_{idx}__ -->'
_MERMAID_PLACEHOLDER_RE = re.compile(r'<!-- __MERMAID_(\d+)__ -->')

ASSETS_DIR = os.path.join(paths_util.get_base_path(), 'assets')


def _read_asset(filename):
    """Lee un archivo de la carpeta assets/."""
    path = os.path.join(ASSETS_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class MarkdownRenderer:
    def __init__(self):
        self.extensions = [
            'fenced_code',
            'codehilite',
            'tables',
            'toc',
            'nl2br'
        ]
        self.extension_configs = {
            'codehilite': {
                'css_class': 'highlight',
                'guess_lang': False   # evita que Pygments intente adivinar mermaid
            }
        }

        # Pre-cargar assets estáticos (se leen una sola vez al iniciar)
        self._template = _read_asset('template.html')
        self._ui_css = _read_asset('ui.css')
        self._ui_js = _read_asset('ui.js')
        self._glass_js = _read_asset('liquid-glass.js')
        logger.debug('[renderer] Assets cargados desde disco.')

    def get_pygments_css(self):
        """Genera los estilos de Pygments para modo claro y oscuro."""
        formatter_dark = HtmlFormatter(style='monokai')
        formatter_light = HtmlFormatter(style='friendly')

        return f"""
        /* Estilos de código para modo claro */
        @media (prefers-color-scheme: light) {{
            {formatter_light.get_style_defs('.highlight')}
        }}
        /* Estilos de código para modo oscuro */
        @media (prefers-color-scheme: dark) {{
            {formatter_dark.get_style_defs('.highlight')}
        }}
        """

    # ------------------------------------------------------------------
    # Pre/post processing de bloques Mermaid
    # ------------------------------------------------------------------

    def _extract_mermaid_blocks(self, text: str):
        """
        Extrae bloques ```mermaid del markdown y los reemplaza por placeholders.
        Devuelve (texto_sin_mermaid, lista_de_diagramas).
        """
        diagrams = []

        def replacer(match):
            idx = len(diagrams)
            diagrams.append(match.group('code').strip())
            logger.debug(f'[renderer] Extraído bloque mermaid #{idx} ({len(diagrams[-1])} chars)')
            return _MERMAID_PLACEHOLDER.format(idx=idx)

        new_text = MERMAID_FENCE_RE.sub(replacer, text)
        logger.debug(f'[renderer] {len(diagrams)} bloque(s) mermaid encontrado(s)')
        return new_text, diagrams

    def _reinsert_mermaid(self, html: str, diagrams: list) -> str:
        """
        Sustituye los placeholders HTML por <div class="mermaid"> con el diagrama.
        """
        def replacer(match):
            idx = int(match.group(1))
            code = diagrams[idx]
            logger.debug(f'[renderer] Reinsertando bloque mermaid #{idx}')
            return f'<div class="mermaid">{code}</div>'

        return _MERMAID_PLACEHOLDER_RE.sub(replacer, html)

    # ------------------------------------------------------------------
    # Render principal
    # ------------------------------------------------------------------

    def render(self, filepath):
        if not os.path.exists(filepath):
            logger.warning(f'[renderer] Archivo no encontrado: {filepath}')
            return '<h1>Archivo no encontrado</h1>'

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw = f.read()

            logger.debug(f'[renderer] Procesando: {filepath} ({len(raw)} chars)')

            # 1. Extraer bloques mermaid antes de que codehilite los toque
            prepped, diagrams = self._extract_mermaid_blocks(raw)

            # 2. Parsear el resto del markdown normalmente
            html = markdown.markdown(
                prepped,
                extensions=self.extensions,
                extension_configs=self.extension_configs
            )

            # 3. Reinsertar los diagramas como <div class="mermaid">
            if diagrams:
                html = self._reinsert_mermaid(html, diagrams)

            logger.debug(f'[renderer] HTML generado: {len(html)} chars')
            return html

        except Exception as e:
            logger.exception(f'[renderer] Error al renderizar {filepath}')
            return f'<h1>Error al renderizar</h1><pre>{e}</pre>'

    def wrap_in_template(self, html_content, css_content, base_url=""):
        """
        Ensambla el HTML final inyectando contenido y assets en el template.
        Todos los archivos se embeben inline (no hay servidor HTTP).
        """
        if base_url:
            logger.debug(f'[renderer] Inyectando base_url para imágenes/enlaces: {base_url}')
        
        mermaid_js = assets_manager.get_mermaid_script()

        html = self._template
        html = html.replace('{%base_url%}', base_url)
        html = html.replace('{%base_css%}', css_content)
        html = html.replace('{%pygments_css%}', self.get_pygments_css())
        html = html.replace('{%ui_css%}', self._ui_css)
        html = html.replace('{%mermaid_js%}', mermaid_js)
        html = html.replace('{%glass_js%}', self._glass_js)
        html = html.replace('{%ui_js%}', self._ui_js)
        html = html.replace('{%content%}', html_content)

        return html
