@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title === ACTUALIZADOR LacteOps ERP ===
color 0A

echo ============================================================
echo    ACTUALIZADOR LacteOps ERP
echo    Lacteos El Cristo C.A.
echo ============================================================
echo.
echo ATENCION: El servidor se detendra durante la actualizacion.
echo.
echo Presione cualquier tecla para continuar o CTRL+C para cancelar...
pause >nul

set INSTALL_DIR=C:\LacteOps

if not exist "%INSTALL_DIR%" (
    color 0C
    echo ERROR: No se encontro la instalacion en %INSTALL_DIR%
    pause
    exit /b 1
)

cd /d "%INSTALL_DIR%"
call venv\Scripts\activate.bat

:: Cargar variables de entorno desde .env
for /f "usebackq tokens=1,* delims==" %%a in (".env") do set %%a=%%b
set DJANGO_SETTINGS_MODULE=erp_lacteo.settings.production

:: Detectar PostgreSQL
set PG_BIN=
for %%d in (15 16 14 17) do (
    if exist "C:\Program Files\PostgreSQL\%%d\bin\psql.exe" (
        set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
    )
)

:: ── [1/5] Respaldo previo ────────────────────────────────────
echo.
echo [1/5] Creando respaldo de seguridad...
set BACKUP_DIR=C:\Respaldos_LacteOps
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
set BACKUP_FILE=%BACKUP_DIR%\lacteops_previo_actualizacion_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%.backup
set PGPASSWORD=%DB_PASSWORD%
if not "!PG_BIN!"=="" (
    "!PG_BIN!\pg_dump" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -Fc %DB_NAME% -f "%BACKUP_FILE%" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo       [OK] Respaldo creado: %BACKUP_FILE%
    ) else (
        echo       AVISO: No se pudo crear el respaldo automatico.
        set /p CONTINUAR="  Desea continuar de todas formas? (S/N): "
        if /I not "!CONTINUAR!"=="S" (
            echo Actualizacion cancelada.
            pause
            exit /b 0
        )
    )
) else (
    echo       AVISO: PostgreSQL no detectado, se omite el respaldo automatico.
)
echo.

:: ── [2/5] Verificar lc_messages en PostgreSQL ────────────────
echo [2/5] Verificando configuracion de PostgreSQL...
if not "!PG_BIN!"=="" (
    for %%i in ("%PG_BIN%\..") do set PG_ROOT=%%~fi
    set PG_CONF=!PG_ROOT!\data\postgresql.conf
    powershell -Command "if((Get-Content '!PG_CONF!') -match 'lc_messages\s*=\s*''C'''){exit 0}else{exit 1}" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo       [OK] lc_messages verificado
    ) else (
        echo       Aplicando lc_messages = C...
        powershell -Command "$f='!PG_CONF!'; $lines=Get-Content $f; $found=$false; $new=@(); foreach($l in $lines){ if($l -match 'lc_messages' -and $l -notmatch '^#'){ $found=$true; $new+='lc_messages = ''C''' } else { $new+=$l } }; if(-not $found){ $new+='lc_messages = ''C''' }; Set-Content -Path $f -Value $new -Encoding UTF8"
        powershell -Command "Get-Service -Name 'postgresql*' | Restart-Service" >nul 2>&1
        echo       [OK] lc_messages corregido y servicio reiniciado
    )
) else (
    echo       AVISO: PostgreSQL no detectado, verifica lc_messages manualmente.
)
echo.

:: ── [3/5] Detener servidor ───────────────────────────────────
echo [3/5] Deteniendo servidor LacteOps...
taskkill /F /IM waitress-serve.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo       [OK] Servidor detenido
echo.

:: ── [4/5] Actualizar codigo y migraciones ────────────────────
echo [4/5] Actualizando codigo...
git fetch origin
git checkout sprint7
git pull origin sprint7
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: No se pudo obtener la actualizacion desde GitHub.
    echo Verifica tu conexion a internet y que el repositorio sea accesible.
    pause
    exit /b 1
)

echo       Instalando nuevas dependencias...
pip install -r requirements.txt >nul 2>&1

echo       Ejecutando migraciones...
python manage.py migrate --noinput
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Fallaron las migraciones.
    if not "%BACKUP_FILE%"=="" (
        echo Restaurando respaldo previo...
        "!PG_BIN!\pg_restore" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d %DB_NAME% -c "%BACKUP_FILE%" >nul 2>&1
    )
    pause
    exit /b 1
)

echo       Recopilando archivos estaticos...
python manage.py collectstatic --noinput >nul

echo       Actualizando permisos RBAC...
python manage.py loaddata fixtures/rbac.json 2>nul

echo       [OK] Codigo actualizado
echo.

:: ── [5/5] Reiniciar servidor ─────────────────────────────────
echo [5/5] Reiniciando servidor LacteOps...
start "" "%INSTALL_DIR%\iniciar_lacteops.bat"
timeout /t 3 /nobreak >nul
echo       [OK] Servidor reiniciado
echo.

echo ============================================================
color 0A
echo    ACTUALIZACION COMPLETADA EXITOSAMENTE
echo ============================================================
echo.
if not "%BACKUP_FILE%"=="" echo    Respaldo previo guardado en: %BACKUP_FILE%
echo.
pause
