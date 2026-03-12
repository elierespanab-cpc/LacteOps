@echo off
setlocal enableextensions

REM ==================================================
REM Instalacion inicial de LacteOps en Windows
REM ==================================================

REM ---- Configuracion base ----
set "APP_DIR=C:\LacteOps"
set "VENV_DIR=%APP_DIR%\venv"
set "PYTHON_EXE=python"
set "NSSM_EXE=C:\nssm\nssm.exe"

REM ---- Verificar Python 3.11 ----
where %PYTHON_EXE% >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.11 no esta instalado o no esta en PATH.
  echo Descargue e instale desde: https://www.python.org/downloads/release/python-3110/
  exit /b 1
)
for /f "tokens=2 delims= " %%v in ('%PYTHON_EXE% --version 2^>^&1') do set "PY_VER=%%v"
echo %PY_VER% | findstr /b "3.11" >nul
if errorlevel 1 (
  echo ERROR: Se requiere Python 3.11. Version detectada: %PY_VER%
  echo Descargue e instale desde: https://www.python.org/downloads/release/python-3110/
  exit /b 1
)

REM ---- Verificar PostgreSQL 15 ----
where psql >nul 2>&1
if errorlevel 1 (
  echo ERROR: PostgreSQL 15 no esta instalado o no esta en PATH.
  echo Descargue e instale desde: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
  exit /b 1
)
for /f "tokens=3 delims= " %%v in ('psql --version 2^>^&1') do set "PG_VER=%%v"
echo %PG_VER% | findstr /b "15." >nul
if errorlevel 1 (
  echo ERROR: Se requiere PostgreSQL 15. Version detectada: %PG_VER%
  echo Descargue e instale desde: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
  exit /b 1
)

REM ---- Crear carpetas necesarias ----
if not exist "%APP_DIR%" (
  mkdir "%APP_DIR%"
)
if not exist "%APP_DIR%\logs" (
  mkdir "%APP_DIR%\logs"
)

REM ---- Crear entorno virtual ----
if not exist "%VENV_DIR%" (
  %PYTHON_EXE% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo ERROR: No se pudo crear el entorno virtual en %VENV_DIR%.
    exit /b 1
  )
)

REM ---- Instalar dependencias ----
cd /d "%APP_DIR%"
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Fallo la instalacion de dependencias.
  exit /b 1
)

REM ---- Copiar .env.prod a .env si no existe ----
if not exist "%APP_DIR%\.env" (
  if exist "%APP_DIR%\.env.prod" (
    copy "%APP_DIR%\.env.prod" "%APP_DIR%\.env" >nul
  ) else (
    echo ERROR: No existe .env.prod en %APP_DIR%.
    exit /b 1
  )
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

"%VENV_DIR%\Scripts\python.exe" manage.py loaddata initial_data
if errorlevel 1 (
  echo ERROR: Fallo loaddata initial_data.
  exit /b 1
)

REM ---- Verificar NSSM ----
if not exist "%NSSM_EXE%" (
  echo ERROR: No se encontro NSSM en %NSSM_EXE%.
  echo Descargue desde: https://nssm.cc/download
  exit /b 1
)

REM ---- Crear servicio LacteOps ----
"%NSSM_EXE%" install LacteOps "%VENV_DIR%\Scripts\python.exe"
if errorlevel 1 (
  echo ERROR: No se pudo crear el servicio LacteOps.
  exit /b 1
)

"%NSSM_EXE%" set LacteOps AppParameters "manage.py runserver 0.0.0.0:8000"
"%NSSM_EXE%" set LacteOps AppDirectory "%APP_DIR%"
"%NSSM_EXE%" set LacteOps AppStdout "%APP_DIR%\logs\service_out.log"
"%NSSM_EXE%" set LacteOps AppStderr "%APP_DIR%\logs\service_err.log"
"%NSSM_EXE%" set LacteOps Start SERVICE_AUTO_START

REM ---- Iniciar servicio ----
"%NSSM_EXE%" start LacteOps
if errorlevel 1 (
  echo ERROR: No se pudo iniciar el servicio LacteOps.
  exit /b 1
)

REM ---- Mostrar IP local ----
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -notlike '127.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "LOCAL_IP=%%i"
if "%LOCAL_IP%"=="" set "LOCAL_IP=localhost"

echo.
echo Instalacion completada. Abra: http://%LOCAL_IP%:8000/admin
exit /b 0
