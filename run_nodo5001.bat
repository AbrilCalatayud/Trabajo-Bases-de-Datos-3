@echo off
setlocal
title Nodo Sucursal5001 (5001)
echo ===============================
echo Iniciando Sucursal5001 en 26.39.171.184:5001
echo ===============================

cd /d "%~dp0"

if not exist "venv_win\Scripts\python.exe" (
  echo [INFO] Creando entorno virtual venv_win...
  py -3 -m venv venv_win
)

call "%~dp0venv_win\Scripts\activate.bat"

if exist requirements.txt (
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
) else (
  python -m pip install Flask
)

set HOST=0.0.0.0
set PORT=5001
set NODE_NAME=Sucursal5001
set PUBLIC_HOST=26.39.171.184
set PEERS=26.60.177.15:5000,26.32.162.255:5002

where python
python -V

python run.py

pause
endlocal
