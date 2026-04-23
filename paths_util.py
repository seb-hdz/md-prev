import os
import sys

def get_base_path():
    """
    Retorna la ruta base de la aplicación.
    Si estamos dentro de un bundle de macOS (.app) generado por py2app,
    devuelve la carpeta Contents/Resources. De lo contrario, devuelve la carpeta actual del script.
    """
    if 'RESOURCEPATH' in os.environ:
        return os.environ['RESOURCEPATH']
    return os.path.dirname(os.path.abspath(__file__))

def get_app_support_path():
    """
    Retorna la ruta de la carpeta Application Support de este proyecto.
    Útil para guardar datos dinámicos como mermaid.js, ya que el .app es read-only.
    """
    home = os.path.expanduser('~')
    app_support = os.path.join(home, 'Library', 'Application Support', 'MD-Prev')
    os.makedirs(app_support, exist_ok=True)
    return app_support
