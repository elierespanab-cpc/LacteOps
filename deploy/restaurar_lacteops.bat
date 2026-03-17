@echo off
chcp 65001 >nul
title Restaurar LacteOps
color 0E

echo ============================================================
echo    RESTAURAR BASE DE DATOS LacteOps ERP
echo ============================================================
echo.
echo ADVERTENCIA: Esto reemplazara TODA la data actual.
echo.
set /p CONFIRMAR="  Esta seguro? Escriba SI para continuar: "
if /I not "%CONFIRMAR%"=="SI" (
    echo Restauracion cancelada.
    pause
    exit /b 0
)

:: Leer configuracion del .env
cd /d C:\LacteOps
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if "%%a"=="DB_NAME" set DB_NAME=%%b
    if "%%a"=="DB_USER" set PG_USER=%%b
    if "%%a"=="DB_PASSWORD" set PGPASSWORD=%%b
    if "%%a"=="DB_HOST" set PG_HOST=%%b
    if "%%a"=="DB_PORT" set PG_PORT=%%b
)

:: Buscar ruta de PostgreSQL
set PG_BIN=
for %%d in (15 16 14 17) do (
    if exist "C:\Program Files\PostgreSQL\%%d\bin\pg_restore.exe" (
        set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
    )
)

:: Listar respaldos disponibles
echo.
echo Respaldos disponibles:
echo ──────────────────────
dir /b /o-d "C:\Respaldos_LacteOps\*.backup" 2>nul
echo.
set /p ARCHIVO="  Nombre del archivo a restaurar: "
set RUTA=C:\Respaldos_LacteOps\%ARCHIVO%

if not exist "%RUTA%" (
    echo ERROR: No se encontro el archivo %RUTA%
    pause
    exit /b 1
)

echo.
echo Restaurando desde: %RUTA%
echo.

:: Cerrar conexiones, borrar y recrear BD
"%PG_BIN%\psql" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='%DB_NAME%' AND pid <> pg_backend_pid();" postgres >nul 2>&1
"%PG_BIN%\dropdb" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% %DB_NAME% 2>nul
"%PG_BIN%\createdb" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% %DB_NAME%
"%PG_BIN%\pg_restore" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% -d %DB_NAME% "%RUTA%"

if %ERRORLEVEL% EQU 0 (
    color 0A
    echo ============================================================
    echo    RESTAURACION COMPLETADA EXITOSAMENTE
    echo ============================================================
) else (
    color 0C
    echo ============================================================
    echo    Restauracion completada con advertencias (revisar arriba)
    echo ============================================================
)

echo.
pause
