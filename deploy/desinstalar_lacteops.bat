@echo off
chcp 65001 >nul
title Desinstalar LacteOps
color 0C

echo ============================================================
echo    DESINSTALAR LacteOps ERP
echo ============================================================
echo.
echo Esto eliminara:
echo   - La carpeta C:\LacteOps
echo   - La base de datos 'lacteops' en PostgreSQL
echo   - El acceso directo del Escritorio
echo.
echo NO eliminara:
echo   - Python
echo   - PostgreSQL
echo   - Los respaldos en C:\Respaldos_LacteOps
echo.
set /p CONFIRMAR="  Escriba DESINSTALAR para confirmar: "
if /I not "%CONFIRMAR%"=="DESINSTALAR" (
    echo Cancelado.
    pause
    exit /b 0
)

:: Leer .env para datos de BD
cd /d C:\LacteOps 2>nul
if exist ".env" (
    for /f "tokens=1,2 delims==" %%a in (.env) do (
        if "%%a"=="DB_USER" set PG_USER=%%b
        if "%%a"=="DB_PASSWORD" set PGPASSWORD=%%b
        if "%%a"=="DB_HOST" set PG_HOST=%%b
        if "%%a"=="DB_PORT" set PG_PORT=%%b
    )

    set PG_BIN=
    for %%d in (15 16 14 17) do (
        if exist "C:\Program Files\PostgreSQL\%%d\bin\dropdb.exe" (
            set PG_BIN=C:\Program Files\PostgreSQL\%%d\bin
        )
    )

    if defined PG_BIN (
        echo.
        echo Eliminando base de datos...
        "%PG_BIN%\psql" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='lacteops' AND pid <> pg_backend_pid();" postgres >nul 2>&1
        "%PG_BIN%\dropdb" -U %PG_USER% -h %PG_HOST% -p %PG_PORT% lacteops 2>nul
        echo       Base de datos eliminada
    )
)

:: Eliminar acceso directo del escritorio
cd /d "%USERPROFILE%"
del "%USERPROFILE%\Desktop\LacteOps ERP.bat" 2>nul
echo       Acceso directo eliminado

:: Eliminar carpeta del proyecto
cd /d C:\
rmdir /s /q C:\LacteOps 2>nul
echo       Carpeta del proyecto eliminada

echo.
color 0A
echo ============================================================
echo    DESINSTALACION COMPLETADA
echo.
echo    Los respaldos se mantienen en C:\Respaldos_LacteOps
echo    Puede eliminarlos manualmente si lo desea.
echo ============================================================
echo.
pause
