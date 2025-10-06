@echo off
title Nodo Sucursal5000 (5000)
echo ===============================
echo Iniciando Sucursal5000 en 26.60.177.15:5000
echo ===============================

REM Activar entorno virtual
call .venv_win\Scripts\activate

REM Variables de entorno
set HOST=0.0.0.0
set PORT=5000
set NODE_NAME=Sucursal5000
set PUBLIC_HOST=26.60.177.15
set PEERS=26.60.177.15:5000,26.39.171.184:5001,26.32.162.255:5002

REM Ejecutar Flask
python run.py

pause
