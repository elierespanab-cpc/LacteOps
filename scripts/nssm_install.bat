@echo off
setlocal enableextensions

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

echo Servicio LacteOps registrado correctamente.
endlocal
