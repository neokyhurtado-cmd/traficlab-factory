# TraficLab Care 0.1.0

Herramienta propia de mantenimiento, independiente de SUINI e IA-VISION.
Python 3.10+; libreria estandar; sin modelo local, base de datos adicional ni
servicio residente. Git y GitHub CLI (`gh`, con tu sesion ya autenticada) son
opcionales: cuando faltan, se muestra la limitacion.

David y Ashley estan en **el mismo servidor con cuentas Windows distintas**.
El estado/configuracion vive en el LOCALAPPDATA de cada cuenta, con identidad
owner + SID Windows. El worker rechaza ejecutarse bajo la otra cuenta. Los
tokens/permisos de GitHub siguen en la sesion propia de cada usuario. Ambos
usan el DAVID_OS compartido autorizado, con namespaces separados; el scheduler
y la autoridad de limpieza del servidor siguen siendo los existentes.

## Que hace ahora

- Observa espacio de C:/X: y consumo global de RAM; en Windows lista los ocho
  procesos con mayor working set, sin cerrarlos.
- Consulta main, PRs y carriers GitHub; conserva timestamps y diferencia
  metadatos observados de claims de ejecucion.
- Revisa codigo Python tracked de los repos configurados y produce candidatos
  de optimizacion. No ejecuta tests de los productos ni aplica refactors.
- Guarda reporte Markdown/JSON/HTML y un contexto compacto para retomar trabajo.
- Publica notas generadas en el **DAVID_OS existente**, bajo
  `99_SYSTEM/traficlab_care/<owner>/`. Si editaste una nota, la conserva.
- Reutiliza reportes de Storage Guardian, Housekeeper y registro de sesiones;
  marca datos viejos o sin timestamp. No vuelve a escanear millones de archivos.
- Limpia automaticamente solo su propia cache temporal marcada, mayor de siete
  dias y con limite de 128 MiB por ciclo. Lo desconocido se conserva.
- Es un worker de una ejecucion: el scheduler existente puede invocarlo cada
  tick con `--due-only`; nunca repite antes de una hora.

## Que queda en Housekeeper/Hermes

La limpieza de disco del sistema exige manifest actual, dependencias/runtime,
revision independiente y comprobacion posterior en `traficlab-factory#56`.
Care nunca llama `delete --i-have-reviewed`, no cierra sesiones, no elimina
state.db, no modifica repos/productos y no vacia RAM a la fuerza.
La compactacion es de su propio contexto generado; no borra chats de ChatGPT
ni historiales de Hermes/Obsidian. Las sesiones ajenas se inventarian mediante
un adapter; su conciliacion y limpieza siguen en la autoridad existente.

## Instalar en Windows

1. Descomprime el paquete. Necesitas Python 3.10+ disponible como `python.exe`.
2. Ejecuta PowerShell en esa carpeta:

```powershell
.\install.ps1 -Owner david -VaultPath '<ruta del DAVID_OS existente>' -IaVisionPath '<repo IA-VISION>' -SuiniPath '<repo SUINI>'
```

Ashley usa la misma herramienta con `-Owner ashley`, los repos a los que tiene
acceso y **la misma autoridad DAVID_OS autorizada**, sin crear un vault rival.
Tambien hay accesos `Instalar-David.cmd` e `Instalar-Ashley.cmd` que aceptan los
mismos parametros.
Cada persona ejecuta el instalador desde **su propia sesion Windows**. Si Python
esta en un entorno virtual existente, usa `-PythonPath '<ruta a python.exe>'`.
No se instala el perfil de Ashley usando la cuenta de David. El hook incluye
`required_windows_user_sid`: el coordinador debe invocarlo en esa cuenta, sin
recopilar contrasenas ni copiar credenciales.

El modo predeterminado `-Scheduler Existing` instala y ejecuta un primer ciclo;
genera `scheduler-hook.json` para integrarlo con el poller/Hermes existente.
**La automatizacion local no esta activa hasta conectar ese hook y comprobar un
tick real.** El resumen diario de ChatGPT es independiente y ya puede funcionar
sin el worker local.

En una maquina sin orquestador, puedes instalar con `-Scheduler Standalone`:
crea una unica tarea Windows por owner, con privilegios limitados y sin guardar
contrasenas. El installer rechaza ese modo si detecta una tarea activa de
Hermes/poller/Housekeeper/Guardian. La tarea requiere una sesion Windows iniciada.
Respeta la politica de ejecucion PowerShell del equipo; el paquete no la cambia.

Instalacion por defecto: `%LOCALAPPDATA%\TraficLabCare\<owner>`. La configuracion
existente se preserva durante una reinstalacion. Abre `state\LATEST.html` para
ver el reporte. Ajusta paths/puertos de `config.json` a la realidad del host.

## Comandos

```powershell
python care.py doctor --config '<config.json>'
python care.py run --config '<config.json>' --due-only
python care.py run --config '<config.json>' --offline
python care.py audit --config '<config.json>'
python care.py cleanup-cache --config '<config.json>'
python care.py cleanup-cache --config '<config.json>' --apply
```

Sin `--apply`, cleanup-cache solo calcula el plan. El flag no habilita borrados
fuera de la cache propia. Una identidad incorrecta, symlink o solapamiento con
fuentes protegidas impide la mutacion. Un lock residual tras un crash se reporta
como `BUSY_OR_STALE_LOCK`: confirmar que el PID/host ya no esta activo antes de
retirarlo; nunca deshabilitar la regla para un writer vivo.
Junctions y reparse points desconocidos se conservan. Los tags Cloud Files de
OneDrive se distinguen de enlaces de rutas; validar el DAVID_OS real en el canary.

## Adapters

Configura `storage_guardian_report`, `housekeeper_manifest` y `session_registry`
con archivos JSON producidos por esas autoridades. Se espera `generated_at`,
`created_at` o `scanned_at` ISO-8601 con timezone; sin fecha, `UNKNOWN_FRESHNESS`;
mas de seis horas, `STALE`. El contenido es evidencia reportada, no ejecucion
independientemente certificada. No se ejecutan comandos de esos JSON.

El worker local no envia mensajes ni guarda tokens. El resumen al despertar usa
la tarea diaria existente de ChatGPT. Hermes puede publicar evidencia compacta
en GitHub para que ese resumen conozca la salud local; sin esa publicacion,
ChatGPT debe declarar que no observa el PC.

## Verificacion

```powershell
python -m unittest discover -s tests -v
```

Hay pruebas de reinicio, contexto, single-writer, preservacion de notas originales
y editadas, identidades David/Ashley, limpieza acotada, UNKNOWN/symlink, fuentes
viejas, HTML escapado, analisis estatico y CLI offline.
El primer paquete se verifica en Linux. Instalador, Windows RAM/task y binding
con el host real quedan pendientes de canary Windows + review independiente.

## Fuentes tecnicas

- Windows RAM: https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex
- Task Scheduler: https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask
- Housekeeper: https://github.com/neokyhurtado-cmd/traficlab-factory/issues/56
- Windows Cloud Files/reparse tags: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4
- Python st_reparse_tag: https://docs.python.org/3.10/library/os.html#os.stat_result.st_reparse_tag
- No se declara mejora de rendimiento sin benchmark antes/despues y mismas entradas.
