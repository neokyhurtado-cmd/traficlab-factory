# Integracion pendiente en el servidor compartido

Paquete revisable; no se declara instalado ni scheduler conectado.
Autoridad de mantenimiento: traficlab-factory#56. Un servidor, cuentas David y
Ashley separadas. Care es una herramienta propia, no un modulo de SUINI.

1. Revisar SHA exacto y ejecutar `python -m unittest discover -s tests -v` en
   Windows con el Python existente. Parsear `install.ps1` antes de ejecutarlo.
2. Confirmar hostname, SID de la cuenta actual, rutas reales de repos y
   DAVID_OS compartido, permisos de lectura/escritura de su namespace y auth gh
   propia. No copiar home, tokens o credenciales del otro usuario.
3. Desde la cuenta de David, instalar `-Owner david -Scheduler Existing`,
   pasando paths verificados. Ashley puede instalar `-Owner ashley` desde su
   propia cuenta si lo desea. No activar su perfil desde la cuenta de David.
4. Conectar adapters existentes de Guardian, Housekeeper y sesiones usando sus
   reportes JSON recientes. Confirmar salud por los endpoints reales, sin
   asumir puertos. Care no ejecuta limpieza del sistema.
5. Integrar `scheduler-hook.json` en el scheduler/poller existente, respetando
   `required_windows_user_sid` y `host_name`. No ejecutar un hook de Ashley bajo
   David ni introducir un daemon/task/foreman paralelo. Si el scheduler no
   puede usar esa cuenta sin recopilar credenciales, registrar ese bloqueo.
6. Probar un ciclo y un tick real: PID, cuenta, inicio/fin, timestamp, estado
   `NOT_DUE` al repetir antes de una hora. Verificar ausencia de workers
   simultaneos, primera escritura y reinicio, nota original y nota editada
   conservadas, namespaces David/Ashley separados y lock residual preservado.
7. Publicar evidencia compacta sin secretos en #56: SHA, host/cuenta, adapters,
   scheduler binding, ultimo tick, nota/reporte y gaps. El resumen diario de
   ChatGPT solo puede conocer salud local si esa evidencia queda disponible.

Limpieza de sistema: mantener el manifest actual, analisis de dependencias y
runtime, review independiente y salud posterior de Housekeeper/Storage Guardian.
UNKNOWN, sesiones activas, state.db, videos/modelos y originales se conservan.
El flag de limpieza de Care alcanza solo su cache propia marcada y caducada.

Rollback: retirar exclusivamente el hook de Care del coordinador. En modo
Existing el paquete no creo una tarea Windows. Conservar reportes/notas y
retirar sus archivos propios solo tras comprobar ausencia de worker vivo.
