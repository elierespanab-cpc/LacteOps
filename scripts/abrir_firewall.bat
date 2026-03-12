@echo off
setlocal enableextensions

REM ==================================================
REM Abrir puerto 8000 en el Firewall de Windows
REM Ejecutar una sola vez como Administrador
REM ==================================================

netsh advfirewall firewall add rule name="LacteOps" dir=in action=allow protocol=TCP localport=8000
if errorlevel 1 (
  echo ERROR: No se pudo abrir el puerto 8000. Ejecute este script como Administrador.
  exit /b 1
)

echo Regla creada correctamente. Este script se ejecuta una sola vez durante la instalacion.
exit /b 0
