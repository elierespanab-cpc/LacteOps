@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title === DESPLIEGUE PRODUCCION - LacteOps Sprint 7 ===
color 0B

echo ============================================================
echo    DESPLIEGUE LacteOps ERP - Sprint 7
echo    Importacion de datos + Actualizacion de codigo
echo ============================================================
echo.
echo  ADVERTENCIA: Este proceso reemplaza los datos del servidor
echo  con los datos exportados desde desarrollo.
echo  Se creara un respaldo de seguridad ANTES de cualquier cambio.
echo.
echo  Presione cualquier tecla para continuar o CTRL+C para cancelar...
pause >nul

set INSTALL_DIR=C:\LacteOps
set BACKUP_DIR=C:\Respaldos_LacteOps

if not exist "%INSTALL_DIR%\manage.py" (
    color 0C
    echo ERROR: No se encontro LacteOps en %INSTALL_DIR%
    pause
    exit /b 1
)

cd /d "%INSTALL_DIR%"
call venv\Scripts\activate.bat

:: Cargar .env de produccion
for /f "usebackq tokens=1,* delims==" %%a in (".env") do set %%a=%%b
set DJANGO_SETTINGS_MODULE=erp_lacteo.settings.production

:: Detectar PostgreSQL
set PG_BIN=
for %%d in (15 16 14 17) do (
    if exist "C:\Program Files\PostgreSQL\%%d\bin\psql.exe" (
        if "!PG_BIN!"=="" set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
    )
)

if "!PG_BIN!"=="" (
    color 0C
    echo ERROR: No se encontro PostgreSQL instalado.
    pause
    exit /b 1
)

:: Buscar el dump importado (el mas reciente en backups\)
set DUMP_FILE=
for /f "delims=" %%f in ('dir "%INSTALL_DIR%\backups\lacteops_para_produccion_*.dump" /b /o-d 2^>nul') do (
    if "!DUMP_FILE!"=="" set DUMP_FILE=%INSTALL_DIR%\backups\%%f
)

if "!DUMP_FILE!"=="" (
    color 0C
    echo ERROR: No se encontro ningun archivo lacteops_para_produccion_*.dump
    echo        en %INSTALL_DIR%\backups\
    echo.
    echo        Copia el archivo exportado desde desarrollo a esa carpeta
    echo        y vuelve a ejecutar este script.
    pause
    exit /b 1
)

echo    Dump a importar: !DUMP_FILE!
echo.

:: ── [1/5] Respaldo de seguridad de produccion actual ──────────
echo [1/5] Creando respaldo de seguridad de produccion actual...
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

for /f "tokens=1-3 delims=/ " %%a in ("%DATE%") do set DIA=%%a&set MES=%%b&set ANO=%%c
for /f "tokens=1-2 delims=:." %%a in ("%TIME: =0%") do set HORA=%%a%%b
set SAFETY_BACKUP=%BACKUP_DIR%\produccion_ANTES_SPRINT7_%ANO%%MES%%DIA%_%HORA%.backup

set PGPASSWORD=%DB_PASSWORD%
"!PG_BIN!\pg_dump" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -Fc %DB_NAME% -f "%SAFETY_BACKUP%" >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo       [OK] Respaldo guardado en: %SAFETY_BACKUP%
) else (
    echo       AVISO: No se pudo crear el respaldo automatico.
    set /p CONTINUAR="  Desea continuar sin respaldo? (S/N): "
    if /I not "!CONTINUAR!"=="S" (
        echo Despliegue cancelado.
        pause
        exit /b 0
    )
)
echo.

:: ── [2/5] Detener servidor ─────────────────────────────────────
echo [2/5] Deteniendo servidor LacteOps...
taskkill /F /IM waitress-serve.exe >nul 2>&1
:: Intentar tambien con NSSM por si acaso
if exist "C:\nssm\nssm.exe" "C:\nssm\nssm.exe" stop LacteOps >nul 2>&1
timeout /t 2 /nobreak >nul
echo       [OK] Servidor detenido
echo.

:: ── [3/5] Reemplazar base de datos ────────────────────────────
echo [3/5] Importando datos desde desarrollo...
echo       Eliminando BD actual y recreando...

set PGPASSWORD=%DB_PASSWORD%

:: Cerrar conexiones activas
"!PG_BIN!\psql" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d postgres ^
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='%DB_NAME%' AND pid <> pg_backend_pid();" >nul 2>&1

"!PG_BIN!\psql" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d postgres ^
    -c "DROP DATABASE IF EXISTS %DB_NAME%;" >nul 2>&1
"!PG_BIN!\psql" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d postgres ^
    -c "CREATE DATABASE %DB_NAME% OWNER %DB_USER% ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;" >nul 2>&1

echo       Restaurando dump...
"!PG_BIN!\pg_restore" ^
    -U %DB_USER% ^
    -h %DB_HOST% ^
    -p %DB_PORT% ^
    -d %DB_NAME% ^
    --no-owner ^
    --no-acl ^
    -v ^
    "!DUMP_FILE!" >"%INSTALL_DIR%\backups\restore_log.txt" 2>&1

if %ERRORLEVEL% GTR 1 (
    color 0C
    echo ERROR: Fallo la restauracion del dump.
    echo        Revisa el log en: %INSTALL_DIR%\backups\restore_log.txt
    echo.
    echo        Restaurando respaldo de produccion original...
    "!PG_BIN!\pg_restore" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d %DB_NAME% -c "!SAFETY_BACKUP!" >nul 2>&1
    echo        Respaldo restaurado. Revisa el error antes de reintentar.
    pause
    exit /b 1
)

echo       [OK] Datos importados correctamente

:: Garantizar permisos completos al usuario de produccion sobre todos los objetos
echo       Ajustando permisos al usuario %DB_USER%...
"!PG_BIN!\psql" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d %DB_NAME% -c ^
    "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %DB_USER%;" >nul 2>&1
"!PG_BIN!\psql" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d %DB_NAME% -c ^
    "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO %DB_USER%;" >nul 2>&1
"!PG_BIN!\psql" -U %DB_USER% -h %DB_HOST% -p %DB_PORT% -d %DB_NAME% -c ^
    "GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO %DB_USER%;" >nul 2>&1
echo.

:: ── [4/5] Actualizar codigo ────────────────────────────────────
echo [4/5] Actualizando codigo desde GitHub (sprint7)...

git fetch origin
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: No se pudo conectar a GitHub. Verifica la red.
    pause
    exit /b 1
)

git checkout sprint7
git pull origin sprint7

echo       Instalando dependencias...
pip install -r requirements.txt >nul 2>&1

echo       Ejecutando migraciones...
python manage.py migrate --noinput
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Fallaron las migraciones.
    pause
    exit /b 1
)

echo       Recopilando archivos estaticos...
python manage.py collectstatic --noinput >nul 2>&1

echo       Verificando integridad del sistema...
python manage.py check >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: manage.py check reporto problemas. Revisa la configuracion.
    python manage.py check
    pause
    exit /b 1
)

echo       [OK] Codigo actualizado y verificado
echo.

:: ── [5/5] Reiniciar servidor ───────────────────────────────────
echo [5/5] Reiniciando servidor LacteOps...
if exist "C:\nssm\nssm.exe" (
    "C:\nssm\nssm.exe" start LacteOps
) else (
    start "" "%INSTALL_DIR%\deploy\iniciar_lacteops.bat"
)

timeout /t 4 /nobreak >nul

:: Verificar que el servidor responde
powershell -Command "try { $r=(Invoke-WebRequest -Uri 'http://localhost:8000/admin/login/' -TimeoutSec 5 -UseBasicParsing).StatusCode; if($r -eq 200){exit 0}else{exit 1} } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo       [OK] Servidor respondiendo en http://localhost:8000
) else (
    echo       AVISO: El servidor puede tardar unos segundos mas en arrancar.
    echo              Verifica manualmente en http://localhost:8000
)
echo.

echo ============================================================
color 0A
echo    DESPLIEGUE COMPLETADO EXITOSAMENTE
echo ============================================================
echo.
echo    Respaldo de seguridad: %SAFETY_BACKUP%
echo    Dump importado       : !DUMP_FILE!
echo    Log de restauracion  : %INSTALL_DIR%\backups\restore_log.txt
echo.
echo    Verifica en el navegador:
echo    - Login y sidebar
echo    - Reporte de Ventas (cifras en USD correctas)
echo    - Reporte de Produccion consolidado
echo    - Reporte de Gastos (filtro por categoria)
echo.
pause