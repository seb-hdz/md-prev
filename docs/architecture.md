# Arquitectura de MD-Prev

MD-Prev funciona como una aplicación de previsualización desacoplada del sistema operativo pero sincronizada con la actividad del usuario en el Finder.

## Componentes

### 1. Motor de Seguimiento (Polling Engine)
Ubicado en `previewer.py`, utiliza un hilo secundario para ejecutar comandos de AppleScript via `osascript`. 
- **Comando:** `tell application "Finder" to get selection`
- **Frecuencia:** 500ms.
- **Lógica:** Si la selección cambia a un archivo con extensión `.md`, se dispara un evento de recarga.

### 2. Renderizador (Renderer)
Ubicado en `renderer.py`, utiliza la librería `markdown`.
- Convierte el texto plano en HTML.
- Utiliza `Pygments` para generar clases CSS de resaltado de sintaxis.
- Pre-procesa bloques `mermaid` para evitar que Pygments los toque.
- Ensambla el HTML final cargando assets desde `assets/`.

### 3. Interfaz (GUI)
Basada en `pywebview`.
- Utiliza el motor nativo WebKit de macOS.
- **Topmost:** La ventana se mantiene por encima de otras para simular la persistencia de Quick Look (toggle con botón de pin).

### 4. Liquid Glass
Ubicado en `assets/liquid-glass.js`.
- Genera displacement maps usando Snell's Law y perfiles de superficie squircle.
- Crea filtros SVG con `<feDisplacementMap>` para efecto de refracción.
- Detecta WebKit automáticamente y usa `backdrop-filter: blur()` como fallback.

## Estructura de Assets
```
assets/
├── template.html       ← Esqueleto HTML con placeholders {%...%}
├── ui.css              ← Estilos de botones, barra de búsqueda
├── ui.js               ← Lógica de pin, búsqueda, atajos de teclado
├── liquid-glass.js     ← Motor de displacement maps + fallback
├── mermaid.min.js      ← Copia local de Mermaid.js
└── mermaid.version     ← Versión actual (auto-actualizada)
```

## Flujo de Datos
```
Finder (Selección)
  → AppleScript
    → Python (Path)
      → renderer.py: lee .md → extrae mermaid → parsea markdown → reinserta mermaid
        → wrap_in_template: carga assets/ → interpola placeholders → HTML final
          → pywebview: evaluate_js(document.write(html))
```

## Funciones Expuestas a JS (via pywebview)
- `close_window()` — Cierra la ventana
- `toggle_on_top()` — Alterna el estado "siempre al frente", retorna bool
