# Manual del Administrador - LacteOps

1. ARRANQUE Y PARADA DEL SISTEMA

Para iniciar o detener el sistema desde Windows:
1. Presione la tecla Windows y escriba: servicios
2. Abra "Servicios" (services.msc).
3. Busque el servicio llamado "LacteOps".
4. Para iniciar: clic derecho en LacteOps -> Iniciar.
5. Para detener: clic derecho en LacteOps -> Detener.

[CAPTURA: ventana de servicios con LacteOps]

2. ACCESO DESDE OTRAS COMPUTADORAS DE LA RED

Como encontrar la IP del servidor:
1. Abra "CMD" (Simbolo del sistema).
2. Escriba: ipconfig
3. Busque la linea "IPv4" y anote el numero (por ejemplo 192.168.1.100).

Que escribir en el navegador de cada PC cliente:
1. Abra el navegador.
2. Escriba: http://IP_DEL_SERVIDOR:8000/admin
   Ejemplo: http://192.168.1.100:8000/admin

Como agregar "lacteops.local" al archivo hosts para no recordar la IP:
1. Abra el Bloc de notas como Administrador.
2. Abra el archivo: C:\Windows\System32\drivers\etc\hosts
3. Agregue una linea al final:
   192.168.1.100 lacteops.local
4. Guarde el archivo.
5. Ahora puede entrar con: http://lacteops.local:8000/admin

3. BACKUP MANUAL

Como correr el backup manualmente:
1. Abra la carpeta del sistema.
2. Haga doble clic en: scripts\backup_windows.bat

Donde quedan los archivos:
C:\Backups\LacteOps\

4. BACKUP AUTOMATICO

Verificar que la tarea esta programada:
1. Abra "Programador de tareas".
2. Busque la tarea "LacteOps_Backup".

Que hacer si la tarea no aparece:
1. Ejecutar nuevamente: scripts\install_windows.bat

5. ACCESO REMOTO FUERA DE LA OFICINA (TAILSCALE)

Instalar Tailscale en el servidor:
1. Abra el navegador y vaya a https://tailscale.com/download
2. Descargue e instale Tailscale para Windows.
3. Inicie sesion con la cuenta que le asignaron.
4. Verifique que el servidor aparece como conectado.

Instalar Tailscale en la PC del usuario remoto:
1. En la PC remota, descargue e instale Tailscale.
2. Inicie sesion con la misma cuenta.
3. Verifique que la PC aparece como conectada.

Como acceder al sistema desde fuera:
1. Abra el navegador en la PC remota.
2. Escriba: http://IP_TAILSCALE_DEL_SERVIDOR:8000/admin
   (La IP Tailscale se ve en la app de Tailscale.)

6. SOLUCION DE PROBLEMAS COMUNES

El sistema no abre en el navegador:
- Verifique que el servicio LacteOps esta corriendo en servicios (services.msc).
- Verifique que el Firewall de Windows permite el puerto 8000.
  Puede ejecutar: scripts\abrir_firewall.bat (solo una vez).

La pagina carga pero dice error 500:
- Revise el log de errores en: C:\LacteOps\logs\service_err.log

Se lleno el disco:
- Revise C:\Backups\LacteOps\ y elimine backups antiguos.
- Revise C:\LacteOps\logs\ y elimine logs viejos.
