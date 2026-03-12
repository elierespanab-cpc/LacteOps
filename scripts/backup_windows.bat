@echo off
setlocal enableextensions

REM ==================================================
REM Backup manual y automatico de LacteOps (PostgreSQL)
REM ==================================================

REM ---- Variables configurables ----
set "PG_USER=lacteops_user"
set "DB_NAME=lacteops"
set "BACKUP_DIR=C:\Backups\LacteOps"

REM ---- Crear carpeta de backups ----
if not exist "%BACKUP_DIR%" (
  mkdir "%BACKUP_DIR%"
  if errorlevel 1 (
    echo ERROR: No se pudo crear %BACKUP_DIR%.
    exit /b 1
  )
)

REM ---- Generar timestamp seguro ----
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "TS=%%i"
set "SQL_FILE=%BACKUP_DIR%\lacteops_%TS%.sql"
set "ZIP_FILE=%BACKUP_DIR%\lacteops_%TS%.zip"

REM ---- Ejecutar pg_dump ----
pg_dump -U %PG_USER% %DB_NAME% > "%SQL_FILE%"
if errorlevel 1 (
  echo ERROR: Fallo pg_dump. Verifique usuario, base de datos o contrasena.
  echo [%DATE% %TIME%] ERROR pg_dump >> "%BACKUP_DIR%\backup.log"
  exit /b 1
)

REM ---- Comprimir backup ----
powershell -NoProfile -Command "Compress-Archive -Path '%SQL_FILE%' -DestinationPath '%ZIP_FILE%'"
if errorlevel 1 (
  echo ERROR: Fallo al comprimir el backup.
  echo [%DATE% %TIME%] ERROR compress >> "%BACKUP_DIR%\backup.log"
  exit /b 1
)

REM ---- Eliminar archivo .sql ----
del /f /q "%SQL_FILE%"

REM ---- Limpiar backups antiguos (30 dias) ----
powershell -NoProfile -Command "Get-ChildItem -Path '%BACKUP_DIR%' -Filter 'lacteops_*.zip' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force"

REM ---- Registrar en log ----
echo [%DATE% %TIME%] Backup OK: %ZIP_FILE% >> "%BACKUP_DIR%\backup.log"

REM ---- Programar tarea si no existe ----
schtasks /Query /TN "LacteOps_Backup" >nul 2>&1
if errorlevel 1 (
  schtasks /Create /TN "LacteOps_Backup" /TR "C:\LacteOps\scripts\backup_windows.bat" /SC DAILY /ST 02:00 /RL HIGHEST /F
  if errorlevel 1 (
    echo ERROR: No se pudo crear la tarea programada LacteOps_Backup.
    exit /b 1
  )
)

echo Backup completado correctamente.
exit /b 0
