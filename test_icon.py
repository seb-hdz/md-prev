from AppKit import NSApplication, NSImage
import webview

def on_start():
    import os
    icon_path = os.path.abspath("assets/dark-2x.png")
    app = NSApplication.sharedApplication()
    img = NSImage.alloc().initWithContentsOfFile_(icon_path)
    app.setApplicationIconImage_(img)
    print("Icon set")

window = webview.create_window("Test", html="<h1>Hello</h1>")
webview.start(on_start)
