param(
    [ValidateSet('david','ashley')][string]$Owner = 'david',
    [string]$VaultPath = '',
    [string]$IaVisionPath = '',
    [string]$SuiniPath = '',
    [string]$InstallRoot = '',
    [string]$PythonPath = '',
    [ValidateSet('Existing','Standalone')][string]$Scheduler = 'Existing'
)
$ErrorActionPreference = 'Stop'
$windowsIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$windowsSid = $windowsIdentity.User.Value
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA "TraficLabCare\$Owner" }
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
function Assert-PlainPath([string]$PathValue) {
    $cursor = [System.IO.Path]::GetFullPath($PathValue)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw 'La instalacion no modifica rutas enlazadas/reparse points.' }
        }
        $cursor = Split-Path $cursor -Parent
    }
}
Assert-PlainPath $InstallRoot
foreach ($protectedPath in @($VaultPath,$IaVisionPath,$SuiniPath)) {
    if (-not $protectedPath) { continue }
    $protectedFull = [System.IO.Path]::GetFullPath($protectedPath).TrimEnd('\','/') + '\'
    $installFull = $InstallRoot.TrimEnd('\','/') + '\'
    if ($installFull.StartsWith($protectedFull,[System.StringComparison]::OrdinalIgnoreCase) -or $protectedFull.StartsWith($installFull,[System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'InstallRoot debe estar separado del vault y de los repositorios.'
    }
}
if ($VaultPath) {
    if (-not (Test-Path -LiteralPath $VaultPath -PathType Container)) { throw 'El vault existente no se encuentra.' }
    if ((Split-Path $VaultPath -Leaf) -ne 'DAVID_OS') { throw 'Indica el DAVID_OS existente; no se creara otro vault.' }
}
$python = if ($PythonPath) { Get-Command $PythonPath -ErrorAction SilentlyContinue } else { Get-Command python.exe -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Necesitas Python 3.10+ instalado y disponible como python.exe. No se descargara automaticamente.' }
$version = & $python.Source -c "import sys; print(int(sys.version_info >= (3,10)))"
if ($version -ne '1') { throw 'Necesitas Python 3.10 o posterior.' }
$application = Join-Path $InstallRoot 'app'
$configuration = Join-Path $InstallRoot 'config.json'
$installationMarker = Join-Path $InstallRoot '.traficlab-care-install.json'
foreach ($targetPath in @($application,$configuration,$installationMarker,(Join-Path $application 'care.py'),(Join-Path $InstallRoot 'scheduler-hook.json'))) { Assert-PlainPath $targetPath }
if (Test-Path -LiteralPath $installationMarker) {
    $installedIdentity = Get-Content -LiteralPath $installationMarker -Raw | ConvertFrom-Json
    if ($installedIdentity.app -ne 'TraficLab Care' -or $installedIdentity.owner -ne $Owner -or $installedIdentity.windows_user_sid -ne $windowsSid) {
        throw 'La instalacion pertenece a otro perfil/cuenta Windows; se conserva.'
    }
} elseif ((Test-Path -LiteralPath $InstallRoot) -and (Get-ChildItem -LiteralPath $InstallRoot -Force | Select-Object -First 1)) {
    throw 'InstallRoot ya contiene archivos sin identidad de Care; se conserva.'
}
New-Item -ItemType Directory -Path $application -Force | Out-Null
@{app='TraficLab Care';owner=$Owner;windows_user_sid=$windowsSid;host_name=$env:COMPUTERNAME} | ConvertTo-Json | Set-Content -LiteralPath $installationMarker -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'care.py') -Destination (Join-Path $application 'care.py') -Force
if (-not (Test-Path -LiteralPath $configuration)) {
    $cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.example.json') -Raw | ConvertFrom-Json
    $cfg.owner = $Owner
    $cfg.windows_user_sid = $windowsSid
    $cfg.host_name = $env:COMPUTERNAME
    $cfg.state_dir = Join-Path $InstallRoot 'state'
    $cfg.vault_path = $VaultPath
    $cfg.projects[0].local_path = $IaVisionPath
    $cfg.projects[1].local_path = $SuiniPath
    $cfg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configuration -Encoding UTF8
}
$existingCfg = Get-Content -LiteralPath $configuration -Raw | ConvertFrom-Json
if ($existingCfg.owner -ne $Owner -or $existingCfg.windows_user_sid -ne $windowsSid) { throw 'config.json pertenece a otro perfil/cuenta Windows.' }
$script = Join-Path $application 'care.py'
& $python.Source $script doctor --config $configuration
if ($LASTEXITCODE -ne 0) { throw 'La configuracion no paso doctor. Se conservan los archivos existentes.' }
$hook = @{
    schema_version = 1; owner = $Owner; name = "traficlab-care-$Owner";
    executable = $python.Source;
    arguments = @($script,'run','--config',$configuration,'--due-only');
    minimum_interval_seconds = 3600; resident_daemon = $false;
    integration_status = 'PENDING_EXISTING_ORCHESTRATOR_BINDING';
    required_windows_user_sid = $windowsSid; host_name = $env:COMPUTERNAME;
    execution_scope = 'WINDOWS_USER'; requires_user_context = $true;
    source = 'traficlab-factory#56'
}
$hook | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $InstallRoot 'scheduler-hook.json') -Encoding UTF8
if ($Scheduler -eq 'Standalone') {
    $active = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        $_.TaskName -match 'Hermes|Github.Poller|Storage.Guardian|Housekeeper' -and $_.State -ne 'Disabled'
    }
    if ($active) { throw 'Hay un orquestador existente: usa Scheduler Existing y conecta scheduler-hook.json. No se creo otra tarea.' }
    $taskName = "TraficLabCare-$Owner"
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'La tarea ya existe: no se reemplaza automaticamente.' }
    $arguments = '"' + $script + '" run --config "' + $configuration + '" --due-only'
    $action = New-ScheduledTaskAction -Execute $python.Source -Argument $arguments -WorkingDirectory $application
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    $user = $windowsIdentity.Name
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Worker ligero TraficLab Care; sin limpieza externa ni segundo foreman.' | Out-Null
    Write-Host "Tarea registrada: $taskName. Funciona al iniciar sesion; no necesita guardar contrasenas."
} else {
    Write-Host 'Instalado en modo integracion: el scheduler existente debe consumir scheduler-hook.json.'
}
& $python.Source $script run --config $configuration
if ($LASTEXITCODE -ne 0) { throw 'El primer ciclo fallo; revisa la salida. No se certifica instalacion operativa.' }
Write-Host "Reporte: $(Join-Path $InstallRoot 'state\LATEST.html')"
Write-Host 'La limpieza del sistema sigue siendo autoridad de Housekeeper. Configura sus reportes y el de Storage Guardian en config.json.'
