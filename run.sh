#!/bin/bash
# Navegar a la carpeta del proyecto de manera segura
cd "$(dirname "$0")"

echo "=========================================================="
echo "🎯 Iniciando Planificador Trimestral de Épicas con Sprints"
echo "=========================================================="

# 1. Crear entorno virtual si no existe
if [ ! -d ".venv" ]; then
    echo "📦 Creando entorno virtual aislado (.venv)..."
    python3 -m venv .venv
fi

# 2. Activar entorno virtual
echo "🔋 Activando entorno virtual..."
source .venv/bin/activate

# 3. Actualizar pip e instalar dependencias
echo "📥 Verificando e instalando dependencias (Streamlit, Pandas, Plotly)..."
python -m pip install --upgrade pip
pip install streamlit pandas plotly

# 4. Iniciar la aplicación de Streamlit
echo "🚀 Lanzando servidor de Streamlit..."
streamlit run app.py
