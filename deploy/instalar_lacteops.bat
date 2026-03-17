@echo off
chcp 65001 >nul
title === INSTALADOR LacteOps ERP ===
color 0A

echo ============================================================
echo    INSTALADOR LacteOps ERP
echo    Lacteos El Cristo C.A.
echo ============================================================
echo.
echo REQUISITOS PREVIOS:
echo   1. Python 3.11 instalado (con "Add to PATH" marcado)
echo   2. PostgreSQL 15 instalado
echo.
echo Presione cualquier tecla para continuar o CTRL+C para cancelar...
pause >nul

:: ── Verificar Python ─────────────────────────────────────────
echo.
echo [1/8] Verificando Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Python no esta instalado o no esta en el PATH.
    echo Instale Python 3.11 desde python.org y marque "Add to PATH".
    pause
    exit /b 1
)
python --version
echo       OK
echo.

:: ── Pedir datos de PostgreSQL ────────────────────────────────
echo [2/8] Configuracion de PostgreSQL...
echo.
set /p PG_USER="  Usuario PostgreSQL (por defecto: postgres): "
if "%PG_USER%"=="" set PG_USER=postgres
set /p PG_PASS="  Contrasena PostgreSQL: "
set /p PG_HOST="  Host (por defecto: localhost): "
if "%PG_HOST%"=="" set PG_HOST=localhost
set /p PG_PORT="  Puerto (por defecto: 5432): "
if "%PG_PORT%"=="" set PG_PORT=5432
set DB_NAME=lacteops
echo.

:: ── Determinar ruta de instalacion ───────────────────────────
:: ── Clonar proyecto desde GitHub ─────────────────────────────
echo [3/8] Descargando proyecto desde GitHub...
set INSTALL_DIR=C:\LacteOps
set GITHUB_REPO=https://github.com/elierespanab-cpc/LacteOps.git
 
:: Verificar que Git este instalado
git --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Git no esta instalado o no esta en el PATH.
    echo Descargue Git desde https://git-scm.com e instalelo.
    pause
    exit /b 1
)

if exist "%INSTALL_DIR%" (
    echo       La carpeta %INSTALL_DIR% ya existe.
    set /p OVERWRITE="  Desea sobreescribir? (S/N): "
    if /I not "%OVERWRITE%"=="S" (
        echo Instalacion cancelada.
        pause
        exit /b 0
    )
    rmdir /s /q "%INSTALL_DIR%"
)
 
echo       Clonando repositorio... (requiere internet)
git clone %GITHUB_REPO% "%INSTALL_DIR%"
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: No se pudo clonar el repositorio.
    echo Verifica que la URL sea correcta y tengas acceso a internet.
    pause
    exit /b 1
)
echo       Proyecto descargado en %INSTALL_DIR%
echo.


:: ── Crear entorno virtual ────────────────────────────────────
echo [4/8] Creando entorno virtual...
cd /d "%INSTALL_DIR%"
python -m venv venv
call venv\Scripts\activate.bat
echo       Entorno virtual creado y activado
echo.

:: ── Instalar dependencias ────────────────────────────────────
echo [5/8] Instalando dependencias (esto puede tardar unos minutos)...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo       Dependencias instaladas
echo.

:: ── Crear archivo .env ───────────────────────────────────────
echo [6/8] Configurando variables de entorno...

:: Generar SECRET_KEY aleatorio
for /f "delims=" %%i in ('python -c "import secrets; print(secrets.token_urlsafe(50))"') do set SECRET_KEY=%%i

:: Detectar IP local del servidor
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do set SERVER_IP=%%b
)

(
echo SECRET_KEY=%SECRET_KEY%
echo ALLOWED_HOSTS=localhost,127.0.0.1,%SERVER_IP%
echo DJANGO_SETTINGS_MODULE=erp_lacteo.settings.production
echo DB_NAME=%DB_NAME%
echo DB_USER=%PG_USER%
echo DB_PASSWORD=%PG_PASS%
echo DB_HOST=%PG_HOST%
echo DB_PORT=%PG_PORT%
echo CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://%SERVER_IP%:8000
) > "%INSTALL_DIR%\.env"
echo       Archivo .env creado
echo       IP del servidor detectada: %SERVER_IP%
echo.

:: ── Crear BD en PostgreSQL ───────────────────────────────────
echo [7/8] Creando base de datos PostgreSQL...
set PGPASSWORD=%PG_PASS%

:: Buscar ruta de PostgreSQL
set PG_BIN=
for %%d in (15 16 14 17) do (
    if exist "C:\Program Files\PostgreSQL\%%d\bin\psql.exe" (
        set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
    )
)

if "%PG_BIN%"=="" (
    echo AVISO: No se encontro psql.exe automaticamente.
    set /p PG_BIN="  Ingrese la ruta de la carpeta bin de PostgreSQL: "
)

:: Crear BD si no existe
"%PG_BIN%\psql" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% -tc "SELECT 1 FROM pg_database WHERE datname='%DB_NAME%'" postgres | findstr "1" >nul
if %ERRORLEVEL% NEQ 0 (
    "%PG_BIN%\createdb" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% %DB_NAME%
    echo       Base de datos '%DB_NAME%' creada
) else (
    echo       Base de datos '%DB_NAME%' ya existe
)
echo.

:: ── Migraciones, collectstatic, superusuario ─────────────────
echo [8/8] Configurando Django...
set DJANGO_SETTINGS_MODULE=erp_lacteo.settings.production

echo       Ejecutando migraciones...
python manage.py migrate --noinput
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Fallaron las migraciones.
    pause
    exit /b 1
)

echo       Cargando datos iniciales...
python manage.py loaddata deploy/datos_iniciales.json
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Fallo la carga de datos iniciales.
    pause
    exit /b 1
)

echo       Recopilando archivos estaticos...
python manage.py collectstatic --noinput >nul

echo       Cargando permisos RBAC...
python manage.py loaddata fixtures/rbac.json 2>nul

echo.
echo       Creando usuario administrador...
echo       (Ingrese usuario, email y contrasena)
python manage.py createsuperuser

:: ── Crear carpeta de respaldos ───────────────────────────────
if not exist "C:\Respaldos_LacteOps" mkdir "C:\Respaldos_LacteOps"

:: ── Copiar scripts de operacion ──────────────────────────────
copy "%INSTALL_DIR%\deploy\iniciar_lacteops.bat" "%INSTALL_DIR%\iniciar_lacteops.bat" >nul 2>&1
copy "%INSTALL_DIR%\deploy\respaldo_lacteops.bat" "%INSTALL_DIR%\respaldo_lacteops.bat" >nul 2>&1
copy "%INSTALL_DIR%\deploy\restaurar_lacteops.bat" "%INSTALL_DIR%\restaurar_lacteops.bat" >nul 2>&1
copy "%INSTALL_DIR%\deploy\desinstalar_lacteops.bat" "%INSTALL_DIR%\desinstalar_lacteops.bat" >nul 2>&1

:: ── Crear acceso directo en escritorio ───────────────────────
echo.
echo Creando acceso directo en el Escritorio...
python -c "import os, pathlib; desktop=pathlib.Path.home()/'Desktop'; f=open(desktop/'LacteOps ERP.bat','w'); f.write('@echo off\ncd /d C:\\LacteOps\ncall iniciar_lacteops.bat\n'); f.close(); print('       Acceso directo creado en:', desktop)"

:: ── Programar respaldo automatico diario ─────────────────────
echo.
echo Programando respaldo automatico diario a las 11:00 PM...
schtasks /create /tn "LacteOps - Respaldo Diario" /tr "\"%INSTALL_DIR%\respaldo_lacteops.bat\"" /sc daily /st 23:00 /rl HIGHEST /f >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo       Tarea programada creada: todos los dias a las 11:00 PM
) else (
    echo       AVISO: No se pudo crear la tarea programada.
    echo       Puede programarla manualmente desde el Programador de Tareas.
)

:: ── Agregar inicio automatico con Windows ────────────────────
echo.
echo Configurando inicio automatico con Windows...
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy "%INSTALL_DIR%\iniciar_lacteops.bat" "%STARTUP_DIR%\LacteOps_Servidor.bat" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo       El servidor arrancara automaticamente al encender la PC
) else (
    echo       AVISO: No se pudo configurar inicio automatico.
    echo       Copie iniciar_lacteops.bat a la carpeta Inicio manualmente.
)

echo.
echo ============================================================
color 0A
echo    INSTALACION COMPLETADA EXITOSAMENTE
echo ============================================================
echo.
echo    Proyecto instalado en: %INSTALL_DIR%
echo    Base de datos: %DB_NAME% (PostgreSQL)
echo    IP del servidor: %SERVER_IP%
echo.
echo    Los demas equipos acceden desde:
echo    http://%SERVER_IP%:8000/admin/
echo.
echo    Automatizado:
echo      - El servidor arranca solo al encender la PC
echo      - Respaldo automatico todos los dias a las 11:00 PM
echo      - Respaldos viejos (+30 dias) se eliminan automaticamente
echo      - Se guardan en: C:\Respaldos_LacteOps\
echo.
echo    Scripts disponibles en %INSTALL_DIR%:
echo      iniciar_lacteops.bat    - Arranca el servidor
echo      respaldo_lacteops.bat   - Respaldo manual
echo      restaurar_lacteops.bat  - Restaurar un respaldo
echo      desinstalar_lacteops.bat - Quitar todo
echo.
echo ============================================================
pause
