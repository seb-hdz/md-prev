from setuptools import setup

APP = ['previewer.py']
DATA_FILES = [
    'assets',
    'styles.css'
]
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'assets/icon.icns',
    'plist': {
        'CFBundleName': 'MD-Prev',
        'CFBundleDisplayName': 'MD-Prev',
        'CFBundleGetInfoString': 'Markdown Previewer',
        'CFBundleIdentifier': 'com.sebhdz.mdprev',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSRequiresAquaSystemAppearance': False,  # Soportar modo oscuro
    },
    'packages': ['webview', 'markdown', 'pygments'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
