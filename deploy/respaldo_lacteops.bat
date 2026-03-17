@echo off
chcp 65001 >nul
title Respaldo LacteOps
color 0E

echo ============================================================
echo    RESPALDO LacteOps ERP
echo ============================================================
echo.

:: Leer configuracion del .env
cd /d C:\LacteOps
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if "%%a"=="DB_NAME" set DB_NAME=%%b
    if "%%a"=="DB_USER" set PG_USER=%%b
    if "%%a"=="DB_PASSWORD" set PGPASSWORD=%%b
    if "%%a"=="DB_HOST" set PG_HOST=%%b
    if "%%a"=="DB_PORT" set PG_PORT=%%b
)

:: Generar nombre con fecha y hora
set FECHA=%date:~6,4%-%date:~3,2%-%date:~0,2%
set HORA=%time:~0,2%%time:~3,2%
set HORA=%HORA: =0%
set ARCHIVO=C:\Respaldos_LacteOps\lacteops_%FECHA%_%HORA%.backup

:: Buscar ruta de PostgreSQL
set PG_BIN=
for %%d in (15 16 14 17) do (
    if exist "C:\Program Files\PostgreSQL\%%d\bin\pg_dump.exe" (
        set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
    )
)

if "%PG_BIN%"=="" (
    echo ERROR: No se encontro pg_dump.exe
    pause
    exit /b 1
)

if not exist "C:\Respaldos_LacteOps" mkdir "C:\Respaldos_LacteOps"

echo Creando respaldo...
echo   Base de datos: %DB_NAME%
echo   Archivo: %ARCHIVO%
echo.

"%PG_BIN%\pg_dump" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% -F c -b -f "%ARCHIVO%" %DB_NAME%

if %ERRORLEVEL% EQU 0 (
    color 0A
    echo ============================================================
    echo    RESPALDO COMPLETADO EXITOSAMENTE
    echo    Archivo: %ARCHIVO%
    echo ============================================================

    :: Eliminar respaldos de mas de 30 dias
    forfiles /p "C:\Respaldos_LacteOps" /m "*.backup" /d -30 /c "cmd /c del @path" 2>nul
) else (
    color 0C
    echo ============================================================
    echo    ERROR: El respaldo fallo
    echo ============================================================
)

echo.
pause
