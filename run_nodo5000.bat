@echo off
setlocal
title Nodo Sucursal_5000 (5000)
echo ===============================
echo Iniciando Sucursal_5000 en 26.60.177.15:5000
echo ===============================

REM Ir a la carpeta del proyecto
cd /d "%~dp0"

REM Crear venv si no existe
if not exist "venv_win\Scripts\python.exe" (
  echo [INFO] Creando entorno virtual venv_win...
  py -3 -m venv venv_win
)

REM Activar venv
call "venv_win\Scripts\activate.bat"

REM Instalar dependencias (usa requirements si existe)
if exist requirements.txt (
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
) else (
  python -m pip install --upgrade pip
  python -m pip install Flask requests python-dotenv
)

REM === Variables de entorno ===
set HOST=0.0.0.0
set PORT=5000
set NODE_NAME=Sucursal_5000
set PUBLIC_HOST=26.60.177.15

REM Lista de peers (sin incluirte a vos mismo está OK)
set PEERS=26.39.171.184:5001,26.32.162.255:5002

REM Sync manual y cada 10 minutos
set AUTO_SYNC=0
set SYNC_INTERVAL=600

where python
python -V

REM === Ejecutar la app (entrypoint correcto) ===
python app\app.py

pause
endlocal
