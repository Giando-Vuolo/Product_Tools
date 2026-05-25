@echo off
echo ==========================================================
echo 🎯 Iniciando Planificador Trimestral de Epicas con Sprints
echo ==========================================================

:: 1. Crear entorno virtual si no existe
if not exist .venv (
    echo 📦 Creando entorno virtual aislado (.venv)...
    python -m venv .venv
)

:: 2. Activar entorno virtual
echo 🔋 Activando entorno virtual...
call .venv\Scripts\activate

:: 3. Actualizar pip e instalar dependencias
echo 📥 Verificando e instalar dependencias (Streamlit, Pandas, Plotly)...
python -m pip install --upgrade pip
pip install streamlit pandas plotly

:: 4. Iniciar la aplicación de Streamlit
echo 🚀 Lanzando servidor de Streamlit...
streamlit run app.py

pause
