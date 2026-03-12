@echo off
setlocal enableextensions

REM ==================================================
REM Inicio de LacteOps en modo produccion (Waitress)
REM ==================================================

REM Carpeta base del proyecto (raiz)
set "APP_DIR=%~dp0.."

REM Activar entorno virtual
call "%APP_DIR%\venv\Scripts\activate"
if errorlevel 1 (
  echo ERROR: No se pudo activar el entorno virtual.
  exit /b 1
)

REM Usar settings de produccion
set "DJANGO_SETTINGS_MODULE=erp_lacteo.settings.production"

REM Ejecutar servidor WSGI con Waitress
waitress-serve --port=8000 erp_lacteo.wsgi:application

endlocal
