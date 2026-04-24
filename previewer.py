import webview
import subprocess
import time
import threading
import os
import paths_util
import assets_manager
from renderer import MarkdownRenderer

class Previewer:
    def __init__(self):
        self.renderer = MarkdownRenderer()
        self.last_path = None
        self.window = None
        self.is_running = True
        self.on_top_state = True   # estado inicial: siempre al frente

        # Cargar estilos base
        styles_path = os.path.join(paths_util.get_base_path(), 'styles.css')
        with open(styles_path, 'r') as f:
            self.base_css = f.read()
        
        self.current_icon_name = None  # Cache para no actualizar el Dock innecesariamente

    def get_finder_selection(self):
        """Usa AppleScript para obtener el archivo seleccionado en el Finder."""
        script = '''
        tell application "Finder"
            set theSelection to selection as alias list
            if theSelection is {} then return ""
            return POSIX path of item 1 of theSelection
        end tell
        '''
        try:
            path = subprocess.check_output(['osascript', '-e', script]).decode('utf-8').strip()
            return path
        except Exception:
            return ""

    def update_content(self):
        """Hilo de polling para detectar cambios en la selección del Finder."""
        while self.is_running:
            # --- Actualización Dinámica del Ícono del Dock ---
            try:
                from AppKit import NSApplication, NSImage, NSAppearanceNameDarkAqua
                app = NSApplication.sharedApplication()
                appearance = app.effectiveAppearance().name()
                is_dark = NSAppearanceNameDarkAqua in appearance
                
                icon_name = 'dark-x1024-pdd.png' if is_dark else 'light-x1024-pdd.png'
                
                if icon_name != self.current_icon_name:
                    icon_path = os.path.join(paths_util.get_base_path(), 'assets', icon_name)
                    if os.path.exists(icon_path):
                        img = NSImage.alloc().initWithContentsOfFile_(icon_path)
                        app.setApplicationIconImage_(img)
                        self.current_icon_name = icon_name
                    
                    # Notificar al webview para actualizar Mermaid y otros estilos
                    if self.window:
                        is_dark_js = "true" if is_dark else "false"
                        self.window.evaluate_js(f"if(window.updateTheme) window.updateTheme({is_dark_js});")
                        
                        # Si hay un archivo cargado, refrescarlo para asegurar coherencia total
                        if self.last_path:
                            self.reload_preview(self.last_path)
            except ImportError:
                pass # Ignorar si no estamos en macOS o falta pyobjc
            # ------------------------------------------------

            current_path = self.get_finder_selection()

            if current_path != self.last_path:
                if current_path.lower().endswith('.md'):
                    self.last_path = current_path
                    self.reload_preview(current_path)

            time.sleep(0.5)

    def reload_preview(self, path):
        """Renderiza el nuevo archivo y lo inyecta en el webview via JS."""
        if not self.window:
            return
        try:
            html_body = self.renderer.render(path)
            base_url = f"file://{os.path.dirname(os.path.abspath(path))}/"
            print(f"[reload_preview] Resolviendo rutas relativas con base_url: {base_url}")
            full_html = self.renderer.wrap_in_template(html_body, self.base_css, base_url=base_url)

            # Escapar para inyección segura en JS usando json.dumps (maneja backslashes y comillas)
            import json
            escaped_html = json.dumps(full_html)
            js = f"document.open(); document.write({escaped_html}); document.close();"
            self.window.evaluate_js(js)

            filename = os.path.basename(path)
            self.window.set_title(f"MD-Prev — {filename}")
        except Exception as e:
            print(f"[reload_preview] Error: {e}")

    def on_closing(self):
        self.is_running = False

    def start(self):
        def close_window():
            if self.window:
                self.window.destroy()

        def toggle_on_top():
            """Alterna el estado 'siempre al frente' de la ventana.
            Devuelve el nuevo estado (bool) al caller JS."""
            self.on_top_state = not self.on_top_state
            self.window.on_top = self.on_top_state
            return self.on_top_state

        def on_webview_ready():
            """Callback ejecutado por pywebview cuando la ventana está lista.
            Aquí sí es seguro arrancar el hilo de polling."""
            thread = threading.Thread(target=self.update_content, daemon=True)
            thread.start()

        # Crear la ventana inicial
        blank_url = f"file://{os.path.join(paths_util.get_base_path(), 'assets', 'blank.html')}"
        self.window = webview.create_window(
            'MD-Prev',
            url=blank_url,
            width=800,
            height=900,
            on_top=self.on_top_state,
            background_color='#1e1e1e'
        )

        # Exponer funciones al JS
        self.window.expose(close_window)
        self.window.expose(toggle_on_top)

        # webview.start(func=on_webview_ready) garantiza que el callback se ejecuta
        # DESPUÉS de que el motor WebKit esté completamente listo
        webview.start(on_webview_ready, debug=False)


if __name__ == '__main__':
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    # Verificar actualizaciones de Mermaid.js en background (no bloquea el arranque)
    assets_manager.start_background_update_check()
    app = Previewer()
    app.start()
