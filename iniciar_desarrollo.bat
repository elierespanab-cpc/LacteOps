@echo off
chcp 65001 >nul
title LacteOps ERP - Desarrollo
color 0A

cd /d C:\Users\elier\Documents\Desarollos\LacteOps
call venv\Scripts\activate.bat
set DJANGO_SETTINGS_MODULE=erp_lacteo.settings.development

echo.
echo  LacteOps - Servidor de Desarrollo
echo  Acceso: http://localhost:8000/admin/
echo  Detener: CTRL+C
echo.

python manage.py runserver
pause