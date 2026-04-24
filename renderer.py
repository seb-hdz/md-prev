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
import logging
import assets_manager
from pathlib import Path
import base64
import mimetypes

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

_LATEX_PLACEHOLDER = 'KLATEX{idx}K'
_LATEX_PLACEHOLDER_RE = re.compile(r'KLATEX(\d+)K')

# Regex para bloques LaTeX
# 1. Display math: \[ ... \] o $$ ... $$
LATEX_DISPLAY_RE = re.compile(
    r'(\\\[.*?\\\])|(\$\$.*?\$\$)',
    re.MULTILINE | re.DOTALL
)
# 2. Inline math: \( ... \) o $ ... $
LATEX_INLINE_RE = re.compile(
    r'(\\\(.*?\\\))|(\$.+?\$)',
    re.MULTILINE | re.DOTALL
)

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
            'sane_lists'
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
    # Pre/post processing de bloques LaTeX
    # ------------------------------------------------------------------

    def _extract_latex_blocks(self, text: str):
        """
        Extrae bloques LaTeX del markdown y los reemplaza por placeholders.
        Devuelve (texto_sin_latex, lista_de_formulas).
        """
        formulas = []

        def replacer(match):
            idx = len(formulas)
            # Guardamos la fórmula completa con sus delimitadores originales
            full_match = match.group(0)
            formulas.append(full_match)
            logger.debug(f'[renderer] Extraído bloque LaTeX #{idx}')
            return _LATEX_PLACEHOLDER.format(idx=idx)

        # Primero extraemos display math (más específico) y luego inline
        text = LATEX_DISPLAY_RE.sub(replacer, text)
        text = LATEX_INLINE_RE.sub(replacer, text)
        
        return text, formulas

    def _reinsert_latex(self, html: str, formulas: list) -> str:
        """Sustituye los placeholders LaTeX por su contenido original."""
        def replacer(match):
            idx = int(match.group(1))
            return formulas[idx]

        return _LATEX_PLACEHOLDER_RE.sub(replacer, html)

    def _fix_list_indentation(self, text: str) -> str:
        """
        Convierte indentación de 2 espacios a 4 espacios para listas,
        ya que Python-Markdown requiere 4 espacios para anidamiento.
        """
        lines = text.split('\n')
        new_lines = []
        for line in lines:
            # Match: espacios iniciales (al menos 2) + marcador de lista + espacio
            match = re.match(r'^(\s{2,})([-*+]|\d+\.)\s', line)
            if match:
                indent = match.group(1)
                marker_and_rest = line[len(indent):]
                # Duplicamos la sangría (2->4, 4->8, etc) para asegurar anidamiento
                new_indent = ' ' * (len(indent) * 2)
                new_lines.append(new_indent + marker_and_rest)
            else:
                new_lines.append(line)
        return '\n'.join(new_lines)

    def _get_data_uri(self, filepath: str) -> str:
        """Convierte un archivo local en una Data URI (base64)."""
        try:
            if not os.path.exists(filepath):
                return None
            
            mime_type, _ = mimetypes.guess_type(filepath)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            with open(filepath, 'rb') as f:
                data = f.read()
                b64 = base64.b64encode(data).decode('utf-8')
                return f'data:{mime_type};base64,{b64}'
        except Exception as e:
            logger.error(f'[renderer] Error al convertir a Data URI: {filepath} -> {e}')
            return None

    def _resolve_relative_paths(self, html: str, base_dir: str) -> str:
        """
        Encuentra atributos src="..." y href="..." con rutas relativas.
        - Para src (imágenes), intenta convertir a Data URI para evitar bloqueos de seguridad.
        - Para href (enlaces), convierte en URIs absolutas file://.
        """
        def replacer(match):
            attr = match.group(1)
            path = match.group(2)
            
            # Ignorar rutas absolutas, URIs y anclas
            if path.startswith(('http://', 'https://', 'file://', '/', '#')):
                return match.group(0)
            
            # Resolver ruta absoluta en el sistema de archivos
            abs_path = os.path.abspath(os.path.join(base_dir, path))
            
            # Si es un atributo src (usualmente imágenes), intentamos Data URI
            if attr == 'src':
                data_uri = self._get_data_uri(abs_path)
                if data_uri:
                    logger.debug(f'[renderer] Imagen convertida a Data URI: {path}')
                    print(f"[renderer] Imagen convertida a Data URI: {path}")
                    return f'{attr}="{data_uri}"'

            # Si falla la conversión o es un href, usamos file:// absoluta
            abs_uri = Path(abs_path).as_uri()
            logger.debug(f'[renderer] Ruta resuelta (file://): {path} -> {abs_uri}')
            print(f"[renderer] URL resuelta para {attr}: {abs_uri}")
            return f'{attr}="{abs_uri}"'

        # Buscamos src="..." y href="..." de forma segura
        new_html = re.sub(r'(src|href)="([^"]+)"', replacer, html)
        return new_html

    # ------------------------------------------------------------------
    # Render principal
    # ------------------------------------------------------------------

    def render(self, filepath):
        if not os.path.exists(filepath):
            logger.warning(f'[renderer] Archivo no encontrado: {filepath}')
            return '<h1>Archivo no encontrado</h1>'

        base_dir = os.path.dirname(os.path.abspath(filepath))
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw = f.read()

            logger.debug(f'[renderer] Procesando: {filepath} ({len(raw)} chars)')

            # 1. Limpiar indentación de listas y extraer bloques mermaid/LaTeX
            raw = self._fix_list_indentation(raw)
            prepped, diagrams = self._extract_mermaid_blocks(raw)
            prepped, formulas = self._extract_latex_blocks(prepped)

            # 2. Parsear el resto del markdown normalmente
            html = markdown.markdown(
                prepped,
                extensions=self.extensions,
                extension_configs=self.extension_configs
            )

            # 3. Reinsertar los diagramas y fórmulas
            if formulas:
                html = self._reinsert_latex(html, formulas)
            if diagrams:
                html = self._reinsert_mermaid(html, diagrams)

            # 4. Resolver rutas relativas a absolutas para asegurar visibilidad de imágenes
            html = self._resolve_relative_paths(html, base_dir)

            logger.debug(f'[renderer] HTML generado: {len(html)} chars')
            return html

        except Exception as e:
            logger.exception(f'[renderer] Error al renderizar {filepath}')
            return f'<h1>Error al renderizar</h1><pre>{e}</pre>'

    def wrap_in_template(self, html_content, css_content):
        """
        Ensambla el HTML final inyectando contenido y assets en el template.
        Todos los archivos se embeben inline (no hay servidor HTTP).
        """
        mermaid_js = assets_manager.get_mermaid_script()
        mathjax_js = assets_manager.get_mathjax_script()

        html = self._template
        html = html.replace('{%base_css%}', css_content)
        html = html.replace('{%pygments_css%}', self.get_pygments_css())
        html = html.replace('{%ui_css%}', self._ui_css)
        html = html.replace('{%mermaid_js%}', mermaid_js)
        html = html.replace('{%mathjax_js%}', mathjax_js)
        html = html.replace('{%glass_js%}', self._glass_js)
        html = html.replace('{%ui_js%}', self._ui_js)
        html = html.replace('{%content%}', html_content)

        return html
    def render_blank(self, css: str) -> str:
        """Renderiza el estado inicial vacío usando el template principal."""
        blank_path = os.path.join(paths_util.get_base_path(), 'assets', 'blank.html')
        try:
            with open(blank_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            content = f'<div class="blank-state"><h2>Error cargando blank.html: {e}</h2></div>'
        
        return self.wrap_in_template(content, css)
