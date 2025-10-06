echo ===============================

REM Ir a la carpeta del script
cd /d "%~dp0"

REM Crear venv si no existe
if not exist "venv_win\Scripts\python.exe" (
  echo [INFO] Creando entorno virtual venv_win...
  py -3 -m venv venv_win
)

REM Activar venv
call "%~dp0venv_win\Scripts\activate.bat"

REM Asegurar dependencias
if exist requirements.txt (
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
) else (
  python -m pip install Flask
)

REM Variables de entorno
set HOST=0.0.0.0
set PORT=5000
set NODE_NAME=Sucursal5000
set PUBLIC_HOST=26.60.177.15
REM (opción recomendada: no te incluyas a vos mismo)
set PEERS=26.39.171.184:5001,26.32.162.255:5002

REM Mostrar Python en uso (debug)
where python
python -V

REM Ejecutar
python run.py

pause
endlocal
