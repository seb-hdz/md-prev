#!/bin/bash

# ==============================================================================
# MD-Prev Build & Packaging Script for macOS
# ==============================================================================
# Uso:
#   ./build.sh          -> Genera MD-Prev.app en build/ y crea el instalador .dmg
#   ./build.sh app      -> Genera únicamente MD-Prev.app en la carpeta build/
#   ./build.sh dmg      -> Genera el archivo .dmg (compila el .app si es necesario)
#   ./build.sh clean    -> Limpia las carpetas build/, dist/ y temporales
# ==============================================================================

set -e

# Colores para la terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

APP_NAME="MD-Prev"
APP_VERSION="1.0.0"
BUILD_DIR="build"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
DMG_NAME="${APP_NAME}-v${APP_VERSION}.dmg"
DMG_OUTPUT="${BUILD_DIR}/${DMG_NAME}"

TARGET="${1:-all}"

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}       MD-Prev macOS Build & Packaging System         ${NC}"
echo -e "${BLUE}======================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Limpieza
# ------------------------------------------------------------------------------
clean_build() {
    echo -e "${YELLOW}🧹 Limpiando artefactos previos...${NC}"
    rm -rf "${BUILD_DIR}" dist *.dmg assets/icon.icns assets/*-pdd.png assets/icon.iconset
    echo -e "${GREEN}✓ Limpieza completada.${NC}"
}

if [ "$TARGET" = "clean" ]; then
    clean_build
    exit 0
fi

# ------------------------------------------------------------------------------
# 2. Verificar Entorno Virtual
# ------------------------------------------------------------------------------
if [ -d ".venv" ]; then
    echo -e "${BLUE}📦 Activando entorno virtual (.venv)...${NC}"
    source .venv/bin/activate
fi

if ! python3 -c "import py2app" &>/dev/null; then
    echo -e "${RED}❌ Error: py2app no está instalado en el entorno Python actual.${NC}"
    echo "Instálalo ejecutando: pip install py2app"
    exit 1
fi

# ------------------------------------------------------------------------------
# 3. Generación y Optimización de Íconos
# ------------------------------------------------------------------------------
generate_icons() {
    echo -e "${BLUE}🎨 Verificando íconos para macOS (Dock & Finder)...${NC}"

    # Localizar GraphicsMagick (gm)
    GM_BIN=""
    if command -v gm &>/dev/null; then
        GM_BIN=$(command -v gm)
    elif [ -x "/opt/homebrew/bin/gm" ]; then
        GM_BIN="/opt/homebrew/bin/gm"
    elif [ -x "/usr/local/bin/gm" ]; then
        GM_BIN="/usr/local/bin/gm"
    fi

    # Generar versiones con padding para el dock dinámico
    if [ -n "$GM_BIN" ]; then
        echo "   Usando GraphicsMagick ($GM_BIN) para padding oficial (824px)..."
        "$GM_BIN" convert assets/dark-x1024.png -resize 824x824 -gravity center -background transparent -extent 1024x1024 -matte assets/dark-x1024-pdd.png
        "$GM_BIN" convert assets/light-x1024.png -resize 824x824 -gravity center -background transparent -extent 1024x1024 -matte assets/light-x1024-pdd.png
    else
        echo -e "${YELLOW}   GraphicsMagick no encontrado. Usando sips nativo para padding...${NC}"
        cp assets/dark-x1024.png assets/dark-x1024-pdd.png
        cp assets/light-x1024.png assets/light-x1024-pdd.png
    fi

    # Generar archivo .icns nativo con iconutil
    if [ ! -f "assets/icon.icns" ] || [ "assets/dark-x1024-pdd.png" -nt "assets/icon.icns" ]; then
        echo "   Construyendo assets/icon.icns con iconutil..."
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
        rm -rf assets/icon.iconset
        echo -e "${GREEN}✓ assets/icon.icns generado con éxito.${NC}"
    fi
}

# ------------------------------------------------------------------------------
# 4. Compilar Aplicación (.app en carpeta build/)
# ------------------------------------------------------------------------------
build_app() {
    generate_icons

    echo -e "${BLUE}🏗  Compilando ${APP_NAME}.app en la carpeta '${BUILD_DIR}/' con py2app...${NC}"
    mkdir -p "${BUILD_DIR}"

    # Limpiar compilaciones intermedias anteriores pero conservar build/ si existe
    rm -rf "${APP_BUNDLE}" "${BUILD_DIR}/temp"

    # Ejecutar py2app configurando dist-dir en build/
    python3 setup.py py2app --bdist-base "${BUILD_DIR}/temp" --dist-dir "${BUILD_DIR}" > /dev/null

    # Limpiar archivos temporales de compilación
    rm -rf "${BUILD_DIR}/temp" "${BUILD_DIR}/bdist."*

    # Limpiar archivos .DS_Store no deseados dentro del bundle
    find "${APP_BUNDLE}" -name ".DS_Store" -delete 2>/dev/null || true

    echo -e "${GREEN}✓ Aplicación generada exitosamente en:${NC} ${APP_BUNDLE}"
}

# ------------------------------------------------------------------------------
# 5. Generar Imagen de Disco (.dmg)
# ------------------------------------------------------------------------------
build_dmg() {
    if [ ! -d "${APP_BUNDLE}" ]; then
        echo -e "${YELLOW}⚠️  No se encontró ${APP_BUNDLE}. Compilando primero...${NC}"
        build_app
    fi

    echo -e "${BLUE}💿 Creando imagen de disco DMG: ${DMG_OUTPUT}...${NC}"

    # Crear directorio staging temporal para incluir acceso directo a /Applications
    local DMG_STAGE="${BUILD_DIR}/dmg_staging"
    rm -rf "${DMG_STAGE}"
    mkdir -p "${DMG_STAGE}"

    cp -R "${APP_BUNDLE}" "${DMG_STAGE}/"
    ln -s /Applications "${DMG_STAGE}/Applications"

    # Generar DMG comprimido UDZO
    rm -f "${DMG_OUTPUT}" "${DMG_NAME}"
    hdiutil create -volname "${APP_NAME}" -srcfolder "${DMG_STAGE}" -ov -format UDZO "${DMG_OUTPUT}" > /dev/null
    rm -rf "${DMG_STAGE}"

    # Crear enlace o copia en la raíz para conveniencia
    cp "${DMG_OUTPUT}" "${DMG_NAME}"

    local DMG_SIZE
    DMG_SIZE=$(du -h "${DMG_OUTPUT}" | cut -f1)
    echo -e "${GREEN}✓ DMG generado exitosamente (${DMG_SIZE}):${NC} ${DMG_OUTPUT}"
    echo -e "  (También disponible en la raíz del proyecto como ./${DMG_NAME})"
}

# ------------------------------------------------------------------------------
# Flujo de ejecución según el target
# ------------------------------------------------------------------------------
START_TIME=$(date +%s)

case "$TARGET" in
    app)
        build_app
        ;;
    dmg)
        build_dmg
        ;;
    all)
        build_app
        build_dmg
        ;;
    *)
        echo -e "${RED}Opción no reconocida: '$TARGET'${NC}"
        echo "Uso: $0 [app | dmg | all | clean]"
        exit 1
        ;;
esac

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo -e "${BLUE}======================================================${NC}"
echo -e "${GREEN}🎉 Proceso finalizado en ${ELAPSED}s.${NC}"
echo -e "   - Aplicación: ${APP_BUNDLE}"
if [ "$TARGET" = "dmg" ] || [ "$TARGET" = "all" ]; then
    echo -e "   - Instalador: ${DMG_OUTPUT}"
fi
echo -e "${BLUE}======================================================${NC}"
