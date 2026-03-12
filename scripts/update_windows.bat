@echo off
setlocal enableextensions

REM ==================================================
REM Actualizacion de LacteOps en Windows
REM ==================================================

REM ---- Configuracion base ----
set "APP_DIR=C:\LacteOps"
set "VENV_DIR=%APP_DIR%\venv"
set "NSSM_EXE=C:\nssm\nssm.exe"

REM ---- Validar que existe la aplicacion ----
if not exist "%APP_DIR%\manage.py" (
  echo ERROR: No se encontro LacteOps en %APP_DIR%.
  exit /b 1
)

REM ---- Detener servicio ----
if not exist "%NSSM_EXE%" (
  echo ERROR: NSSM no encontrado en %NSSM_EXE%.
  exit /b 1
)
"%NSSM_EXE%" stop LacteOps

REM ---- Actualizar codigo ----
cd /d "%APP_DIR%"
git pull origin main
if errorlevel 1 (
  echo ERROR: Fallo git pull. Revise su conexion o credenciales.
  exit /b 1
)

REM ---- Instalar dependencias ----
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Fallo la instalacion de dependencias.
  exit /b 1
)

REM ---- Migraciones y archivos estaticos ----
"%VENV_DIR%\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
  echo ERROR: Fallo migrate.
  exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" manage.py collectstatic --noinput
if errorlevel 1 (
  echo ERROR: Fallo collectstatic.
  exit /b 1
)

REM ---- Iniciar servicio ----
"%NSSM_EXE%" start LacteOps
if errorlevel 1 (
  echo ERROR: No se pudo iniciar el servicio LacteOps.
  exit /b 1
)

REM ---- Verificar estado ----
timeout /t 5 /nobreak >nul
sc query LacteOps | find "RUNNING" >nul
if errorlevel 1 (
  echo ERROR: El servicio LacteOps no esta corriendo.
  exit /b 1
)

echo Actualizacion completada. Servicio LacteOps en ejecucion.
exit /b 0
