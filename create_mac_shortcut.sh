#!/bin/bash
# Navegar de forma segura al directorio donde reside este script
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="$HOME/Desktop"

echo "============================================="
echo "🖥️  Creando acceso directo en el Escritorio..."
echo "============================================="

# 1. Compilar la aplicación nativa en el Escritorio con la ruta absoluta de esta laptop
osacompile -o "$DESKTOP_DIR/PO_Tools.app" -e "do shell script \"$PROJECT_DIR/run.sh > /dev/null 2>&1 &\""

# 2. Copiar el icono personalizado si existe
if [ -f "$PROJECT_DIR/assets/app_icon.icns" ]; then
    echo "🎨 Aplicando el icono de analítica..."
    cp "$PROJECT_DIR/assets/app_icon.icns" "$DESKTOP_DIR/PO_Tools.app/Contents/Resources/applet.icns"
    touch "$DESKTOP_DIR/PO_Tools.app"
fi

echo "✅ ¡Listo! La app PO_Tools ya está en tu Escritorio y configurada para esta laptop."
