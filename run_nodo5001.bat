@echo off
title Nodo Sucursal5001 (5001)
echo ===============================
echo Iniciando Sucursal5001 en 26.39.171.184:5001
echo ===============================

call .venv_win\Scripts\activate

set HOST=0.0.0.0
set PORT=5001
set NODE_NAME=Sucursal5001
set PUBLIC_HOST=26.39.171.184
set PEERS=26.60.177.15:5000,26.39.171.184:5001,26.32.162.255:5002

python run.py

pause
