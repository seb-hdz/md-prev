# Configuración de MD-Prev

Sigue estos pasos para poner en marcha el previsualizador en tu máquina.

## Requisitos Previos
- macOS (probado en Big Sur o superior).
- Python 3.9+.

## Instalación

1. **Crear Entorno Virtual:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Instalar Dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

## Ejecución
Para iniciar el previsualizador, simplemente ejecuta:
```bash
python3 previewer.py
```

## Uso
1. Ejecuta el script. Se abrirá una ventana vacía o con el último archivo `.md` detectado.
2. Ve al Finder y selecciona cualquier archivo Markdown.
3. La ventana se actualizará automáticamente con el contenido formateado.
4. Presiona `Esc` o `Espacio` dentro de la ventana del previsualizador para cerrarlo.
