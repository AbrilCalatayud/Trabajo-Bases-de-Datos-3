@echo off
setlocal
title Nodo Sucursal_5002 (5002)
echo ===============================
echo Iniciando Sucursal_5002 en 26.32.162.255:5002
echo ===============================

cd /d "%~dp0"
if not exist "venv_win\Scripts\python.exe" (
  echo [INFO] Creando entorno virtual venv_win...
  py -3 -m venv venv_win
)

call "venv_win\Scripts\activate.bat"

if exist requirements.txt (
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
) else (
  python -m pip install --upgrade pip
  python -m pip install Flask requests python-dotenv
)

set HOST=0.0.0.0
set PORT=5002
set NODE_NAME=Sucursal_5002
set PUBLIC_HOST=26.32.162.255
set PEERS=26.60.177.15:5000,26.39.171.184:5001

set AUTO_SYNC=0
set SYNC_INTERVAL=600

where python
python -V

python app\app.py

pause
endlocal
