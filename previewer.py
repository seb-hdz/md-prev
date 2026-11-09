import webview
import subprocess
import time
import threading
import os
import uuid
import json
from pathlib import Path
import paths_util
import assets_manager
from renderer import MarkdownRenderer
from notes_manager import NotesManager

class Previewer:
    def __init__(self):
        self.renderer = MarkdownRenderer()
        self.last_path = None
        self.window = None
        self.is_running = True
        self.on_top_state = True   # estado inicial: siempre al frente

        # Notes system
        self.notes_manager = NotesManager()
        self._view_token = None          # opaque token identifying current render
        self._view_filepath = None       # filepath associated with current token
        self._token_lock = threading.Lock()
        self._edit_in_progress = False    # True while user is editing a note
        self._pending_reload = None       # Deferred reload path

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

    def _generate_view_token(self, filepath: str) -> str:
        """Generate an opaque token that binds a render to a filepath."""
        token = uuid.uuid4().hex[:16]
        with self._token_lock:
            self._view_token = token
            self._view_filepath = filepath
            self._edit_in_progress = False
        return token

    def _resolve_token(self, view_token: str) -> str | None:
        """Return the filepath for *view_token*, or None if expired."""
        with self._token_lock:
            if view_token == self._view_token:
                return self._view_filepath
        return None

    def reload_preview(self, path):
        """Renderiza el nuevo archivo y lo inyecta en el webview via JS."""
        if not self.window:
            return

        # If user is editing a note, defer the reload
        with self._token_lock:
            if self._edit_in_progress:
                self._pending_reload = path
                return

        try:
            html_body = self.renderer.render(path)
            full_html = self.renderer.wrap_in_template(html_body, self.base_css)

            # Generate a new view token for this render
            view_token = self._generate_view_token(path)

            # Calcular el base_uri para darle al documento permisos de origen file://
            # Esto es vital para que WebKit permita cargar imágenes locales.
            base_uri = Path(path).parent.absolute().as_uri() + '/'
            
            print(f"--- RELOAD PREVIEW ---")
            print(f"[previewer] Inyectando HTML con origin base_uri: {base_uri}")
            self.window.load_html(full_html, base_uri=base_uri)

            filename = os.path.basename(path)
            self.window.set_title(f"MD-Prev — {filename}")

            # After load_html, inject the view token so JS can request notes
            # We use evaluate_js with a small delay to allow the DOM to settle
            def inject_token():
                time.sleep(0.15)
                if self.window:
                    escaped = json.dumps(view_token)
                    self.window.evaluate_js(
                        f'if(window.notesOnFileLoaded) {{ window.notesOnFileLoaded({escaped}); }} else {{ window._pendingNotesToken = {escaped}; }}'
                    )
            threading.Thread(target=inject_token, daemon=True).start()

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

        # ------ Notes bridge API ------

        def notes_list(view_token):
            """Return all notes for the file associated with *view_token*."""
            filepath = self._resolve_token(view_token)
            if filepath is None:
                return {'error': 'expired_token'}
            try:
                notes = self.notes_manager.list_notes(filepath)
                return {'ok': True, 'notes': notes}
            except Exception as e:
                print(f"[notes_list] Error: {e}")
                return {'error': str(e)}

        def notes_create(view_token, note_id, body, selector):
            """Create a note for the current file."""
            filepath = self._resolve_token(view_token)
            if filepath is None:
                return {'error': 'expired_token'}
            try:
                if isinstance(selector, str):
                    selector = json.loads(selector)
                note = self.notes_manager.create_note(filepath, body, selector, note_id)
                return {'ok': True, 'note': note}
            except Exception as e:
                print(f"[notes_create] Error: {e}")
                return {'error': str(e)}

        def notes_update(view_token, note_id, body=None, selector=None):
            """Update an existing note's body and/or selector."""
            filepath = self._resolve_token(view_token)
            if filepath is None:
                return {'error': 'expired_token'}
            try:
                if isinstance(selector, str):
                    selector = json.loads(selector)
                note = self.notes_manager.update_note(
                    filepath, note_id, body=body, selector=selector
                )
                return {'ok': True, 'note': note}
            except Exception as e:
                print(f"[notes_update] Error: {e}")
                return {'error': str(e)}

        def notes_delete(view_token, note_id):
            """Delete a note by ID."""
            filepath = self._resolve_token(view_token)
            if filepath is None:
                return {'error': 'expired_token'}
            try:
                deleted = self.notes_manager.delete_note(filepath, note_id)
                return {'ok': True, 'deleted': deleted}
            except Exception as e:
                print(f"[notes_delete] Error: {e}")
                return {'error': str(e)}

        def notes_begin_edit(view_token):
            """Signal that user started editing a note (defers file reloads)."""
            with self._token_lock:
                if view_token == self._view_token:
                    self._edit_in_progress = True
                    self._pending_reload = None
                    return {'ok': True}
            return {'error': 'expired_token'}

        def notes_end_edit(view_token):
            """Signal that user finished editing a note.
            If a file reload was deferred, it is applied now."""
            pending = None
            with self._token_lock:
                if view_token == self._view_token:
                    self._edit_in_progress = False
                    pending = getattr(self, '_pending_reload', None)
                    self._pending_reload = None
            if pending:
                self.reload_preview(pending)
            return {'ok': True}

        def on_webview_ready():
            """Callback ejecutado por pywebview cuando la ventana está lista.
            Aquí sí es seguro arrancar el hilo de polling."""
            thread = threading.Thread(target=self.update_content, daemon=True)
            thread.start()

        # Crear la ventana inicial usando el template (esto incluye el toolbar de Pin/Search)
        blank_html = self.renderer.render_blank(self.base_css)
        self.window = webview.create_window(
            'MD-Prev',
            html=blank_html,
            width=800,
            height=900,
            on_top=self.on_top_state,
            background_color='#1e1e1e'
        )

        # Exponer funciones al JS
        self.window.expose(close_window)
        self.window.expose(toggle_on_top)
        self.window.expose(notes_list)
        self.window.expose(notes_create)
        self.window.expose(notes_update)
        self.window.expose(notes_delete)
        self.window.expose(notes_begin_edit)
        self.window.expose(notes_end_edit)

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
