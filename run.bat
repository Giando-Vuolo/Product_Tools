@echo off
:: Navegar a la carpeta del proyecto de manera segura
cd /d "%~dp0"

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
echo 📥 Verificando e instalar dependencias desde requirements.txt...
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 4. Iniciar la API en segundo plano
echo ⚙️ Lanzando API (FastAPI) en puerto 8000...
start /B uvicorn api:app --host 0.0.0.0 --port 8000

:: 5. Iniciar la aplicación de Streamlit
echo 🚀 Lanzando servidor de Streamlit...
streamlit run app.py

:: Al cerrar Streamlit, matar tambien la API que escucha en el puerto 8000
echo 🛑 Cerrando la API en el puerto 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

pause
