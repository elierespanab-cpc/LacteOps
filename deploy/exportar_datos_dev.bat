@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title === EXPORTAR DATOS DE DESARROLLO - LacteOps ===
color 0B

echo ============================================================
echo    EXPORTAR DATOS DE DESARROLLO - LacteOps ERP
echo    Este script crea el dump de tu PC para llevar al servidor
echo ============================================================
echo.

set DEV_DIR=C:\Users\elier\Documents\Desarollos\LacteOps
set BACKUP_DIR=%DEV_DIR%\backups

:: Detectar PostgreSQL
set PG_BIN=
for %%d in (15 16 14 17) do (
    if exist "C:\Program Files\PostgreSQL\%%d\bin\pg_dump.exe" (
        if "!PG_BIN!"=="" set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
    )
)

if "!PG_BIN!"=="" (
    color 0C
    echo ERROR: No se encontro PostgreSQL instalado.
    pause
    exit /b 1
)

:: Cargar variables del .env de desarrollo
for /f "usebackq tokens=1,* delims==" %%a in ("%DEV_DIR%\.env") do set %%a=%%b

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

:: Nombre del archivo con timestamp
for /f "tokens=1-3 delims=/ " %%a in ("%DATE%") do set DIA=%%a&set MES=%%b&set ANO=%%c
for /f "tokens=1-2 delims=:." %%a in ("%TIME: =0%") do set HORA=%%a%%b
set DUMP_FILE=%BACKUP_DIR%\lacteops_para_produccion_%ANO%%MES%%DIA%_%HORA%.dump

echo [1/2] Exportando base de datos de desarrollo...
echo       DB: %DB_NAME% / Usuario: %DB_USER%
echo       Destino: %DUMP_FILE%
echo.

set PGPASSWORD=%DB_PASSWORD%
"!PG_BIN!\pg_dump" ^
    -U %DB_USER% ^
    -h %DB_HOST% ^
    -p %DB_PORT% ^
    -d %DB_NAME% ^
    --no-owner ^
    --no-acl ^
    -F c ^
    -f "%DUMP_FILE%"

if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo ERROR: Fallo la exportacion de la base de datos.
    pause
    exit /b 1
)

echo       [OK] Dump creado exitosamente
echo.

:: Mostrar tamaño del archivo
for %%f in ("%DUMP_FILE%") do set FILESIZE=%%~zf
set /a FILESIZE_KB=%FILESIZE% / 1024
echo [2/2] Resumen
echo       Archivo : %DUMP_FILE%
echo       Tamanio : %FILESIZE_KB% KB
echo.

echo ============================================================
color 0A
echo    EXPORTACION COMPLETADA
echo ============================================================
echo.
echo    Siguiente paso:
echo    Copia este archivo al servidor de produccion en:
echo    C:\LacteOps\backups\
echo    (puedes arrastrarlo por AnyDesk)
echo.
echo    Luego ejecuta en el servidor:
echo    deploy\despliegue_produccion.bat
echo.

:: Abrir la carpeta para que sea facil copiar el archivo
explorer "%BACKUP_DIR%"

pause