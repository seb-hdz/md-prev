#!/bin/bash

# MD-Prev Build Script (v1.3 - GM Compatibility Fix)
# --------------------------------------------------

set -e 

echo "🚀 Iniciando construcción de MD-Prev..."

# 1. Limpiar
rm -rf build dist *.dmg assets/icon.icns assets/*-pdd.png

# 2. Generar íconos con padding oficial (824px)
# Usamos una técnica compatible con GraphicsMagick para asegurar transparencia
echo "🎨 Optimizando íconos para el Dock (824px)..."

process_icon() {
    local input=$1
    local output=$2
    # Redimensionar y centrar en un lienzo transparente de 1024x1024
    /opt/homebrew/bin/gm convert "$input" \
        -resize 824x824 -gravity center \
        -background transparent -extent 1024x1024 \
        -matte "$output"
}

process_icon "assets/dark-x1024.png" "assets/dark-x1024-pdd.png"
process_icon "assets/light-x1024.png" "assets/light-x1024-pdd.png"

# 3. Generar archivo .icns nativo
echo "🏗 Generando assets/icon.icns..."
mkdir -p assets/icon.iconset
sips -z 16 16     assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_16x16.png > /dev/null
sips -z 32 32     assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_16x16@2x.png > /dev/null
sips -z 32 32     assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_32x32.png > /dev/null
sips -z 64 64     assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_32x32@2x.png > /dev/null
sips -z 128 128   assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_128x128.png > /dev/null
sips -z 256 256   assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_128x128@2x.png > /dev/null
sips -z 256 256   assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_256x256.png > /dev/null
sips -z 512 512   assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_256x256@2x.png > /dev/null
sips -z 512 512   assets/dark-x1024-pdd.png --out assets/icon.iconset/icon_512x512.png > /dev/null
cp assets/dark-x1024-pdd.png assets/icon.iconset/icon_512x512@2x.png
iconutil -c icns assets/icon.iconset -o assets/icon.icns
rm -R assets/icon.iconset

# 4. Limpiar .DS_Store
find . -name ".DS_Store" -delete

# 5. Compilar
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "📦 Compilando con py2app..."
python3 setup.py py2app > /dev/null

# 6. Crear DMG
echo "💿 Creando .dmg..."
hdiutil create -volname "MD-Prev" -srcfolder dist/MD-Prev.app -ov -format UDZO MD-Prev-v1.0.0.dmg > /dev/null

echo "✅ ¡Listo! Prueba la app ahora."
