@echo off
setlocal enableextensions
REM Agregar pg_dump al PATH del sistema
setx PATH "%PATH%;C:\Program Files\PostgreSQL\15\bin" /M
echo PATH actualizado — reiniciar PowerShell para efecto inmediato.


REM ==================================================
REM Registrar LacteOps como servicio Windows con NSSM
REM ==================================================

REM Rutas basadas en variables de entorno (no hardcode)
set "APP_DIR=%~dp0.."

REM NSSM debe estar definido como variable de entorno
if "%NSSM_EXE%"=="" (
  echo ERROR: Defina la variable de entorno NSSM_EXE con la ruta completa a nssm.exe.
  echo Ejemplo: setx NSSM_EXE "C:\\nssm\\nssm.exe"
  exit /b 1
)

REM Verificar NSSM
if not exist "%NSSM_EXE%" (
  echo ERROR: NSSM no encontrado en %NSSM_EXE%.
  exit /b 1
)

REM Crear servicio
"%NSSM_EXE%" install LacteOps "cmd.exe"
"%NSSM_EXE%" set LacteOps AppParameters "/c \"%APP_DIR%\scripts\start_production.bat\""
"%NSSM_EXE%" set LacteOps AppDirectory "%APP_DIR%"
"%NSSM_EXE%" set LacteOps Start SERVICE_AUTO_START

REM Logs opcionales
"%NSSM_EXE%" set LacteOps AppStdout "%APP_DIR%\logs\service_out.log"
"%NSSM_EXE%" set LacteOps AppStderr "%APP_DIR%\logs\service_err.log"

REM Task Scheduler: Notificaciones diarias
schtasks /Create /TN "LacteOps-Notificaciones" ^
  /TR "C:\Desarollos\LacteOps\venv\Scripts\python.exe manage.py generar_notificaciones" ^
  /SC DAILY /ST 07:00 /F

echo Servicio LacteOps registrado correctamente.
endlocal
