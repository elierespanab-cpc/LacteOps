@echo off
chcp 65001 >nul
title LacteOps ERP - Servidor
color 0B

:: Detectar IP local
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do set SERVER_IP=%%b
)

echo ============================================================
echo    LacteOps ERP - Servidor Activo
echo ============================================================
echo.
echo    Acceso local:  http://localhost:8000/admin/
echo    Acceso en red: http://%SERVER_IP%:8000/admin/
echo.
echo    Para detener el servidor: cierre esta ventana o CTRL+C
echo ============================================================
echo.

cd /d C:\LacteOps
call venv\Scripts\activate.bat
set DJANGO_SETTINGS_MODULE=erp_lacteo.settings.production

waitress-serve --host=0.0.0.0 --port=8000 --threads=4 erp_lacteo.wsgi:application
