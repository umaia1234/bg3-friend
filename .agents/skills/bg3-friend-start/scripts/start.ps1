[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'Check')][string]$Action = 'Start',
    [switch]$HelperOnly,
    [string]$ConfigPath,
    [ValidateRange(0, 45)][int]$WaitSeconds = 25
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

function Resolve-Bg3WindowsPath([string]$Path) {
    if (-not $Path -or $Path -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)') { throw 'An absolute Windows path is required.' }
    if ($Path.IndexOfAny([char[]]"`"`r`n`0") -ge 0) { throw 'Invalid characters in a Windows path.' }
    $resolved = [IO.Path]::GetFullPath($Path).Replace('\\wsl$\', '\\wsl.localhost\')
    if ($resolved.Length -gt [IO.Path]::GetPathRoot($resolved).Length) { $resolved = $resolved.TrimEnd([char[]]'\/') }
    return $resolved
}

function Test-Bg3SamePath([string]$Left, [string]$Right) {
    try { return [string]::Equals((Resolve-Bg3WindowsPath $Left), (Resolve-Bg3WindowsPath $Right), [StringComparison]::OrdinalIgnoreCase) }
    catch { return $false }
}

function Get-Bg3UserSavedGames {
    # Read FOLDERID_SavedGames without creating it or redirecting into an app
    # package. Its registry value can be absent until the folder is first used.
    # https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid
    if (-not ('Bg3FriendKnownFolders' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Bg3FriendKnownFolders {
    [DllImport("shell32.dll")]
    public static extern int SHGetKnownFolderPath(ref Guid folderId, uint flags, IntPtr token, out IntPtr path);
}
'@
    }
    $folderId = [Guid]'4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4'
    $pointer = [IntPtr]::Zero
    try {
        # KF_FLAG_NO_PACKAGE_REDIRECTION | KF_FLAG_DONT_VERIFY; no CREATE.
        $result = [Bg3FriendKnownFolders]::SHGetKnownFolderPath([ref]$folderId, 0x00014000, [IntPtr]::Zero, [ref]$pointer)
        if ($result -eq 0 -and $pointer -ne [IntPtr]::Zero) {
            return Resolve-Bg3WindowsPath ([Runtime.InteropServices.Marshal]::PtrToStringUni($pointer))
        }
    }
    finally { if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::FreeCoTaskMem($pointer) } }
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders')
    try {
        if ($key) {
            $value = [string]$key.GetValue('{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}', '')
            if ($value -and $value -notmatch '%[^%]+%') { return Resolve-Bg3WindowsPath $value }
        }
    }
    finally { if ($key) { $key.Dispose() } }
    throw 'The Windows Saved Games folder could not be resolved. Register an explicit nativeConfigRoot; do not use a redirected app cache.'
}

function Read-Bg3Json([string]$Path) {
    if (-not $Path) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $null }
}

function Get-Bg3FileAge([string]$Path) {
    try { return ([DateTime]::UtcNow - (Get-Item -LiteralPath $Path).LastWriteTimeUtc).TotalSeconds }
    catch { return $null }
}

function Get-Bg3ArgumentLine([string[]]$Arguments) {
    $quoted = foreach ($argument in $Arguments) {
        if ($argument.Length -gt 0 -and $argument -notmatch '[\s"]') { $argument }
        else {
            $escaped = [regex]::Replace($argument, '(\\*)"', '$1$1\"')
            $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
            '"' + $escaped + '"'
        }
    }
    return $quoted -join ' '
}

function ConvertFrom-Bg3DiagnosticBytes([byte[]]$Bytes) {
    if ($Bytes.Length -eq 0) { return '' }
    # WSL Linux output is UTF-8; Windows-side WSL errors can be UTF-16LE.
    $encoding = if ($Bytes -contains 0 -or ($Bytes.Length -ge 2 -and $Bytes[0] -eq 255 -and $Bytes[1] -eq 254)) {
        [Text.Encoding]::Unicode
    } else { [Text.Encoding]::UTF8 }
    return $encoding.GetString($Bytes).TrimStart([char]0xFEFF)
}

function Invoke-Bg3Diagnostic([string]$FilePath, [string[]]$Arguments) {
    $command = Get-Command -Name $FilePath -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { return @{ exit_code = 127; output = @('Required command is missing: ' + $FilePath) } }
    $process = [Diagnostics.Process]::new()
    $stdout = [IO.MemoryStream]::new()
    $stderr = [IO.MemoryStream]::new()
    try {
        $process.StartInfo.FileName = $command.Source
        $process.StartInfo.Arguments = Get-Bg3ArgumentLine $Arguments
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        $null = $process.Start()
        $outTask = $process.StandardOutput.BaseStream.CopyToAsync($stdout)
        $errTask = $process.StandardError.BaseStream.CopyToAsync($stderr)
        if (-not $process.WaitForExit(30000)) {
            # This is our read-only diagnostic process, never the app/runner.
            $process.Kill()
            $process.WaitForExit()
            return @{ exit_code = 124; output = @('The read-only diagnostic timed out after 30 seconds.') }
        }
        $null = $outTask.GetAwaiter().GetResult()
        $null = $errTask.GetAwaiter().GetResult()
        $outText = ConvertFrom-Bg3DiagnosticBytes $stdout.ToArray()
        $errText = ConvertFrom-Bg3DiagnosticBytes $stderr.ToArray()
        return @{ exit_code = $process.ExitCode; output = @(($outText + "`n" + $errText) -split '\r?\n' | Where-Object { $_.Length -gt 0 }) }
    }
    catch { return @{ exit_code = 1; output = @($_.Exception.Message) } }
    finally { $process.Dispose(); $stdout.Dispose(); $stderr.Dispose() }
}

function Get-Bg3ProcessArgument([string]$CommandLine, [string]$Name) {
    $match = [regex]::Match($CommandLine, '(?i)(?:^|\s)' + [regex]::Escape($Name) + '(?:=|\s+)(?:"([^"]+)"|(\S+))')
    if ($match.Success) {
        if ($match.Groups[1].Success) { return $match.Groups[1].Value }
        return $match.Groups[2].Value
    }
    return $null
}

function Select-Bg3Processes($Processes, [string]$NativeExe, [string]$NativeRoot, [string]$DefaultNativeRoot, [string]$Io) {
    $apps = @(); $workers = @(); $overlays = @(); $sourceOverlays = @()
    foreach ($process in $Processes) {
        $line = [string]$process.CommandLine
        if (-not $line) { continue }
        $executable = [string]$process.ExecutablePath
        if (-not $executable) {
            $match = [regex]::Match($line, '^\s*(?:"([^"]+)"|(\S+))')
            $executable = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
        }
        $overlay = $line -match '(?i)(?:^|\s)--overlay(?:\s|$)'
        $worker = $line -match '(?i)(?:^|\s)--worker(?:\s|$)'
        $ioArgument = Get-Bg3ProcessArgument $line '--io'
        $sourceGui = $line -match '(?i)companion[\\/]gui\.py(?:"|\s|$)'
        # Match the actual profile, including helpers from another checkout.
        # A native main window alone is never an overlay or a live runner.
        if ($Io -and (Test-Bg3SamePath $ioArgument $Io)) {
            if ($sourceGui) { $overlays += $process; $sourceOverlays += $process }
            elseif ($overlay -and ([IO.Path]::GetFileName($executable) -ieq 'BG3Friend.exe' -or (Test-Bg3SamePath $executable $NativeExe))) { $overlays += $process }
        }
        if ($NativeExe -and (Test-Bg3SamePath $executable $NativeExe)) {
            $rootArgument = Get-Bg3ProcessArgument $line '--config-root'
            if (-not $rootArgument) { $rootArgument = $DefaultNativeRoot }
            if (-not (Test-Bg3SamePath $rootArgument $NativeRoot)) { continue }
            if ($worker) { $workers += $process }
            elseif (-not $overlay -and $line -notmatch '(?i)(?:^|\s)--(?:diagnose|smoke-test|status|stop)(?:\s|$)') { $apps += $process }
        }
    }
    return @{ apps = $apps; workers = $workers; overlays = $overlays; source_overlays = $sourceOverlays }
}

function Resolve-Bg3RuntimeState($Runner, $Snapshot, $RunnerAge, $SnapshotAge, $Game, $Launcher, $Processes, $OwnerAlive, [string]$Backend) {
    $liveStates = @('waiting_game','waiting_save','waiting_companion','game_disconnected','ready','paused','thinking','acting','cancelling','retrying','error','call_limit')
    $heartbeat = $null -ne $RunnerAge -and $RunnerAge -ge 0 -and $RunnerAge -lt 8 -and $Runner.runner -in $liveStates
    $runnerLive = [bool]($heartbeat -and $OwnerAlive -ne $false)
    $runnerProven = $OwnerAlive -eq $true -or $Processes.workers.Count -gt 0 -or $Processes.source_overlays.Count -gt 0
    $freshGame = $Game.Count -gt 0 -and $Snapshot.protocol -eq 1 -and $Snapshot.session -and
        $null -ne $SnapshotAge -and $SnapshotAge -ge 0 -and $SnapshotAge -lt 4
    $connected = [bool]($freshGame -and $runnerLive -and $Runner.session -eq $Snapshot.session -and ($Backend -ne 'native' -or $runnerProven))
    $helperRunning = [bool]($runnerLive -and $Processes.overlays.Count -gt 0)
    $modelErrors = @('cli_missing','cli_unavailable','login_required','usage_limit','unsupported_model','cli_outdated','connection_failed','timeout','invalid_response','decision_failed')
    $modelError = $runnerLive -and ($Runner.error_code -in $modelErrors -or ($Runner.error -and $Runner.runner -ne 'error'))
    $mode = 'stopped'
    if ($modelError) { $mode = 'model_error' }
    elseif ($runnerLive -and $Runner.runner -eq 'error') { $mode = 'runner_error' }
    elseif ($runnerLive -xor ($Processes.overlays.Count -gt 0)) { $mode = 'partial' }
    elseif ($helperRunning -and $Game.Count -eq 0) { $mode = 'waiting_game' }
    elseif ($helperRunning -and -not $connected) { $mode = 'waiting_save' }
    elseif ($connected) { $mode = [string]$Runner.runner }
    elseif ($Processes.apps.Count -gt 0) { $mode = 'app_ready' }
    return [ordered]@{
        mode = $mode; backend = $Backend
        game_running = ($Game.Count -gt 0); game_pids = @($Game | ForEach-Object { $_.Id })
        launcher_running = ($Launcher.Count -gt 0)
        app_running = ($Processes.apps.Count -gt 0); app_pids = @($Processes.apps | ForEach-Object { $_.ProcessId })
        worker_pids = @($Processes.workers | ForEach-Object { $_.ProcessId })
        helper_running = $helperRunning; gui_pids = @($Processes.overlays | ForEach-Object { $_.ProcessId })
        runner_alive = $runnerLive; runner_process_confirmed = $OwnerAlive
        runner_state = $(if ($runnerLive) { $Runner.runner } else { $null })
        runner_age_seconds = $(if ($null -ne $RunnerAge) { [math]::Round($RunnerAge, 1) } else { $null })
        snapshot_age_seconds = $(if ($null -ne $SnapshotAge) { [math]::Round($SnapshotAge, 1) } else { $null })
        game_connected = $connected
        game_connection = $(if ($connected) { 'connected' } elseif ($Game.Count -eq 0) { 'waiting_game' } else { 'waiting_save' })
        model_connection = $(if ($modelError) { if ($Runner.runner -eq 'retrying') { 'retrying' } else { 'error' } } else { 'not_verified' })
        companion = $(if ($connected) { $Snapshot.companion.name } else { $null })
        blocked = $(if ($connected) { $Snapshot.blocked } else { $null })
        model = $(if ($runnerLive) { $Runner.model } else { $null }); calls = $(if ($runnerLive) { $Runner.calls } else { $null })
        runner_error = $(if ($runnerLive) { $Runner.error } else { $null }); error_code = $(if ($runnerLive) { $Runner.error_code } else { $null })
    }
}

function Get-Bg3State {
    $runner = $null; $snapshot = $null; $runnerAge = $null; $snapshotAge = $null; $ownerAlive = $null
    if ($bg3Io) {
        $runner = Read-Bg3Json (Join-Path $bg3Io 'runner.json')
        $snapshot = Read-Bg3Json (Join-Path $bg3Io 'snapshot.json')
        if ($runner) { $runnerAge = Get-Bg3FileAge (Join-Path $bg3Io 'runner.json') }
        if ($snapshot) { $snapshotAge = Get-Bg3FileAge (Join-Path $bg3Io 'snapshot.json') }
        $owner = Read-Bg3Json (Join-Path $bg3Io 'runner-claim/owner.json')
        if (($owner.pid -is [int] -or $owner.pid -is [long]) -and $owner.pid -gt 0 -and $null -ne $runnerAge -and $runnerAge -lt 8) {
            if ($owner.platform -eq 'nt') {
                $ownerProcess = Get-Process -Id $owner.pid -ErrorAction SilentlyContinue
                $ownerAlive = $null -ne $ownerProcess
                if ($ownerAlive -and $owner.process_start) {
                    try { $ownerAlive = $ownerProcess.StartTime.ToFileTimeUtc().ToString() -eq [string]$owner.process_start }
                    catch { $ownerAlive = $null }
                }
            }
            elseif ($owner.platform -eq 'posix' -and $owner.distro -match '^[A-Za-z0-9_.-]+$') {
                $check = Invoke-Bg3Diagnostic 'wsl.exe' @('-d',$owner.distro,'--exec','python3','-c',"import os,sys`ntry: os.kill(int(sys.argv[1]),0)`nexcept ProcessLookupError: sys.exit(3)",[string]$owner.pid)
                if ($check.exit_code -eq 0) { $ownerAlive = $true } elseif ($check.exit_code -eq 3) { $ownerAlive = $false }
            }
        }
    }
    $processFilter = "Name='BG3Friend.exe' OR Name='pythonw.exe' OR Name='python.exe'"
    if ($bg3Config.nativeExe) {
        $nativeName = [IO.Path]::GetFileName($bg3Config.nativeExe).Replace("'", "\'")
        $processFilter += " OR Name='$nativeName'"
    }
    $processes = @(Get-CimInstance Win32_Process -Filter $processFilter)
    $selected = Select-Bg3Processes $processes $bg3Config.nativeExe $bg3NativeRoot $bg3DefaultNativeRoot $bg3Io
    $game = @(Get-Process -Name 'bg3','bg3_dx11' -ErrorAction SilentlyContinue)
    $launcher = @(Get-Process -Name 'LariLauncher' -ErrorAction SilentlyContinue)
    return Resolve-Bg3RuntimeState $runner $snapshot $runnerAge $snapshotAge $game $launcher $selected $ownerAlive $bg3Backend
}

function Test-Bg3NativePrerequisites {
    $missing = @(); $setup = @(); $report = $null; $diagnostic = @{ exit_code = 127; output = @() }
    if (-not (Test-Path -LiteralPath $bg3Config.nativeExe -PathType Leaf)) {
        $missing += [ordered]@{ item = 'native_executable'; path = $bg3Config.nativeExe }
    }
    else {
        # The only write performed by Check is its disposable diagnostic report.
        $reportPath = Join-Path ([IO.Path]::GetTempPath()) ('BG3Friend-skill-' + [guid]::NewGuid().ToString('N') + '.json')
        try {
            $diagnostic = Invoke-Bg3Diagnostic $bg3Config.nativeExe @('--config-root',$bg3NativeRoot,'--diagnose','--report',$reportPath)
            $report = Read-Bg3Json $reportPath
        }
        finally { if (Test-Path -LiteralPath $reportPath -PathType Leaf) { Remove-Item -LiteralPath $reportPath -Force } }
        $expected = @('game','profile','extender','codex','package','installed','login','consent')
        $valid = $null -ne $report -and @($report.checks).Count -gt 0
        foreach ($id in $expected) {
            $entry = @($report.checks | Where-Object { $_.id -eq $id })
            if ($entry.Count -ne 1 -or $entry[0].ok -isnot [bool]) { $valid = $false }
        }
        if (-not $valid) { $setup += 'native_diagnostic_report' }
        else {
            foreach ($entry in $report.checks) {
                if ($entry.ok -ne $true -and $entry.required -ne $false) { $setup += [string]$entry.id }
            }
        }
        if ($diagnostic.exit_code -notin @(0,2)) { $setup += 'native_diagnostic_failed' }
        elseif ($diagnostic.exit_code -eq 2 -and $setup.Count -eq 0) { $setup += 'native_configuration' }
    }
    if ($bg3NativeSettingsError) { $setup += 'native_settings' }
    return [ordered]@{
        ready = ($missing.Count -eq 0 -and $setup.Count -eq 0 -and $diagnostic.exit_code -eq 0)
        backend = 'native'; missing = $missing; setup_required = @($setup | Select-Object -Unique)
        config_root = $bg3NativeRoot; settings_error = $bg3NativeSettingsError
        doctor_exit_code = $diagnostic.exit_code; doctor = $diagnostic.output; native_diagnostics = $report
    }
}

function Test-Bg3SourcePrerequisites {
    $required = [ordered]@{
        launch_script = (Join-Path $bg3Config.projectWindows 'scripts/launch.py')
        doctor_script = (Join-Path $bg3Config.projectWindows 'scripts/doctor.py')
        installed_mod = (Join-Path $bg3Config.profileWindows 'Mods/BG3Friend.pak')
        mod_registration_file = (Join-Path $bg3Config.profileWindows 'PlayerProfiles/Public/modsettings.lsx')
        script_extender = (Join-Path $bg3Config.gameWindows 'bin/DWrite.dll'); steam = $bg3Config.steamExe
    }
    $missing = @($required.GetEnumerator() | Where-Object { -not (Test-Path -LiteralPath $_.Value -PathType Leaf) } | ForEach-Object { [ordered]@{ item = $_.Key; path = $_.Value } })
    if (-not (Test-Path -LiteralPath (Join-Path $bg3Config.gameWindows 'bin/bg3_dx11.exe') -PathType Leaf) -and
        -not (Test-Path -LiteralPath (Join-Path $bg3Config.gameWindows 'bin/bg3.exe') -PathType Leaf)) {
        $missing += [ordered]@{ item = 'game'; path = $bg3Config.gameWindows }
    }
    $doctor = @{ exit_code = 127; output = @() }
    if (Test-Path -LiteralPath $required.doctor_script -PathType Leaf) {
        $doctor = Invoke-Bg3Diagnostic 'wsl.exe' @('-d',$bg3Config.distro,'--cd',$bg3Config.projectLinux,'--exec','python3','scripts/doctor.py','--scope','account')
    }
    $python = [string]$bg3Config.windowsPython; $pythonDiagnostic = @()
    if (-not $python -and (Test-Path -LiteralPath $required.launch_script -PathType Leaf)) {
        $discovery = Invoke-Bg3Diagnostic 'wsl.exe' @('-d',$bg3Config.distro,'--cd',$bg3Config.projectLinux,'--exec','python3','-c',"from scripts.launch import gui_python,wsl_path; print(wsl_path(gui_python(), '-w'))")
        $pythonDiagnostic = $discovery.output
        if ($discovery.exit_code -eq 0) {
            $candidates = @($discovery.output | Where-Object {
                $_ -match '^(?:[A-Za-z]:[\\/]|\\\\)' -and (Test-Path -LiteralPath $_ -PathType Leaf)
            })
            if ($candidates.Count -eq 1) { $python = $candidates[0] }
        }
    }
    $tk = @{ exit_code = 127; output = $pythonDiagnostic }
    if ($python) {
        $console = Join-Path (Split-Path -Parent $python) 'python.exe'
        if (Test-Path -LiteralPath $console -PathType Leaf) {
            $tk = Invoke-Bg3Diagnostic $console @('-c',"import sys,tkinter; assert sys.version_info >= (3,11), 'Python 3.11 or later is required'; print(tkinter.Tcl().call('info','patchlevel'))")
        }
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $missing += [ordered]@{ item = 'windows_python'; path = $python } }
    }
    $profile = Invoke-Bg3Diagnostic 'wsl.exe' @('-d',$bg3Config.distro,'--exec','wslpath','-w',$bg3Config.ioLinux)
    $profileMatches = $profile.exit_code -eq 0 -and $profile.output.Count -eq 1 -and (Test-Bg3SamePath $profile.output[0] $bg3Io)
    $registered = $false
    try {
        [xml]$settings = Get-Content -LiteralPath $required.mod_registration_file -Raw -Encoding UTF8
        $registered = $null -ne $settings.SelectSingleNode('//node[@id="Mods"]//attribute[@id="UUID" and @value="cfd9c54e-3884-47ed-9b40-82b8747194de"]')
    }
    catch { $registered = $false }
    $setup = @()
    if (-not $profileMatches) { $setup += 'source_profile_mapping' }
    if ($tk.exit_code -ne 0) { $setup += 'windows_python_tk' }
    if (-not $registered) { $setup += 'bg3_friend_mod_registration' }
    if ($doctor.exit_code -ne 0) { $setup += 'wsl_python_or_codex_login' }
    return [ordered]@{
        ready = ($missing.Count -eq 0 -and $setup.Count -eq 0); backend = 'source'; missing = $missing; setup_required = $setup
        launcher_profile_matches = [bool]$profileMatches; launcher_python_matches = ($tk.exit_code -eq 0)
        windows_python = $python; windows_tk_available = ($tk.exit_code -eq 0); windows_tk_diagnostics = $tk.output
        mod_registered = $registered; doctor_exit_code = $doctor.exit_code; doctor = $doctor.output
    }
}

function Start-Bg3Process([string]$Executable, [string[]]$Arguments, [switch]$Visible) {
    $style = if ($Visible) { 'Normal' } else { 'Hidden' }
    $null = Start-Process -FilePath $Executable -ArgumentList (Get-Bg3ArgumentLine $Arguments) -WindowStyle $style -PassThru
}

$bg3SkillRoot = Split-Path -Parent $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bg3SkillRoot 'project.local.json' }
$bg3DefaultNativeRoot = $null
try { $bg3DefaultNativeRoot = Join-Path (Get-Bg3UserSavedGames) 'BG3Friend' } catch { $bg3DefaultRootError = $_.Exception.Message }
$bg3NativeRoot = $null; $bg3Io = $null; $bg3NativeSettingsError = $null
try {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'Local project configuration is missing.' }
    $bg3Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $bg3Backend = if ($bg3Config.nativeExe) { 'native' } else { 'source' }
    $fields = @('steamAppId')
    if ($bg3Backend -eq 'source') { $fields += @('distro','projectLinux','projectWindows','ioLinux','profileWindows','gameWindows','steamExe') }
    foreach ($field in $fields) {
        if ($bg3Config.$field -isnot [string] -or -not $bg3Config.$field.Trim()) { throw ('Missing configuration field: ' + $field) }
    }
    if ($bg3Config.steamAppId -ne '1086940') { throw 'This skill only starts Steam app 1086940.' }
    foreach ($field in @('projectWindows','profileWindows','windowsPython','gameWindows','steamExe','nativeExe','nativeConfigRoot')) {
        if ($bg3Config.$field) { $bg3Config.$field = Resolve-Bg3WindowsPath $bg3Config.$field }
    }
    if ($bg3Backend -eq 'native') {
        $bg3NativeRoot = if ($bg3Config.nativeConfigRoot) { $bg3Config.nativeConfigRoot } else { $bg3DefaultNativeRoot }
        if (-not $bg3NativeRoot) { throw $bg3DefaultRootError }
        $settingsPath = Join-Path $bg3NativeRoot 'settings.json'
        $nativeSettings = Read-Bg3Json $settingsPath
        if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
            try {
                if (-not $nativeSettings -or $nativeSettings.version -ne 1) { throw 'The native settings file is invalid or unsupported.' }
                if ($nativeSettings.profile) { $bg3Io = Join-Path (Resolve-Bg3WindowsPath $nativeSettings.profile) 'Script Extender/BG3Friend' }
            }
            catch { $bg3NativeSettingsError = $_.Exception.Message }
        }
        else { $bg3NativeSettingsError = 'Native settings have not been saved. Use the BG3 Friend settings window.' }
    }
    else {
        if ($bg3Config.distro -notmatch '^[A-Za-z0-9_.-]+$' -or $bg3Config.projectLinux -notlike '/*' -or $bg3Config.ioLinux -notlike '/*') { throw 'Invalid WSL distribution or absolute Linux path.' }
        $bg3Io = Join-Path $bg3Config.profileWindows 'Script Extender/BG3Friend'
    }
}
catch {
    [ordered]@{ action = $Action.ToLowerInvariant(); actions = @(); needs_configuration = $true; config_path = $ConfigPath;
        error = $_.Exception.Message; next = 'Read SKILL.md and docs/CODEX-SKILL.ko.md; ask before configuring missing setup.' } | ConvertTo-Json
    exit 2
}

$bg3Result = [ordered]@{ action = $Action.ToLowerInvariant(); backend = $bg3Backend; actions = @() }
if ($bg3Backend -eq 'native') {
    $bg3Result.config_root = $bg3NativeRoot
    if ($bg3NativeSettingsError) { $bg3Result.needs_configuration = $true; $bg3Result.settings_error = $bg3NativeSettingsError }
}
try {
    if ($Action -ne 'Status') { $bg3Result.preflight = if ($bg3Backend -eq 'native') { Test-Bg3NativePrerequisites } else { Test-Bg3SourcePrerequisites } }
    $bg3Result.state = Get-Bg3State
    if ($Action -eq 'Start') {
        if ($bg3Result.state.mode -in @('partial','runner_error','model_error')) {
            throw 'The existing helper needs attention. Inspect game_connection, model_connection and error_code; no duplicate was started.'
        }
        if ($bg3Backend -eq 'native' -and -not $bg3Result.preflight.ready) {
            if (Test-Path -LiteralPath $bg3Config.nativeExe -PathType Leaf) {
                if (-not $bg3Result.state.app_running -and -not $bg3Result.state.helper_running) {
                    Start-Bg3Process $bg3Config.nativeExe @('--config-root',$bg3NativeRoot) -Visible
                    $bg3Result.actions += 'setup_app_open_requested'
                }
                $bg3Result.next = 'Use the existing BG3 Friend settings window. Ask about missing setup, complete approved changes in the UI, then Check again.'
            }
        }
        elseif (-not $bg3Result.preflight.ready) { throw 'Preflight failed. Read preflight.missing and setup_required before starting.' }
        else {
            if (-not $HelperOnly -and -not $bg3Result.state.game_running -and -not $bg3Result.state.launcher_running) {
                if ($bg3Config.steamExe) { Start-Bg3Process $bg3Config.steamExe @('-applaunch','1086940') -Visible }
                else { $null = Start-Process -FilePath 'steam://rungameid/1086940' -PassThru }
                $bg3Result.actions += 'game_launch_requested'
            }
            if (-not $bg3Result.state.helper_running) {
                if ($bg3Backend -eq 'native') {
                    if ($bg3Result.state.app_running) { $bg3Result.next = 'Use the existing BG3 Friend window and its party-chat start button. Do not open another app instance.' }
                    else {
                        Start-Bg3Process $bg3Config.nativeExe @('--config-root',$bg3NativeRoot,'--start') -Visible
                        $bg3Result.actions += 'helper_launch_requested'
                    }
                }
                else {
                    $arguments = @('-d',$bg3Config.distro,'--cd',$bg3Config.projectLinux,'--exec','python3','scripts/launch.py','--io',$bg3Config.ioLinux)
                    if ($bg3Result.preflight.windows_python) { $arguments += @('--gui-python',$bg3Result.preflight.windows_python) }
                    Start-Bg3Process 'wsl.exe' $arguments
                    $bg3Result.actions += 'helper_launch_requested'
                }
            }
            if ($bg3Result.actions -contains 'helper_launch_requested') {
                $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
                do {
                    $bg3Result.state = Get-Bg3State
                    if ($bg3Result.state.helper_running -or [DateTime]::UtcNow -ge $deadline) { break }
                    Start-Sleep -Milliseconds 800
                } while ($true)
                if (-not $bg3Result.state.helper_running) { throw 'Helper launch was not verified. Inspect the existing app and state before retrying.' }
            }
        }
    }
    $bg3Result | ConvertTo-Json -Depth 10
    if ($Action -ne 'Status' -and -not $bg3Result.preflight.ready) { exit 1 }
}
catch {
    $bg3Result.error = $_.Exception.Message
    $bg3Result | ConvertTo-Json -Depth 10
    exit 1
}
