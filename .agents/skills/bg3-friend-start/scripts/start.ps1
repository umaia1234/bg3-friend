[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'Check')][string]$Action = 'Start',
    [switch]$HelperOnly,
    [string]$ConfigPath,
    [ValidateRange(0, 45)][int]$WaitSeconds = 25
)

$ErrorActionPreference = 'Stop'
# WSL reads this process output as UTF-8, including Korean game diagnostics.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$bg3SkillRoot = Split-Path -Parent $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bg3SkillRoot 'project.local.json' }
try {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'Local project configuration is missing.' }
    $bg3Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($bg3Field in @('distro','projectLinux','projectWindows','ioLinux','profileWindows','windowsPython','gameWindows','steamExe','steamAppId')) {
        if (-not ($bg3Config.$bg3Field -is [string]) -or -not $bg3Config.$bg3Field.Trim()) {
            throw ('Missing configuration field: ' + $bg3Field)
        }
    }
    # Equivalent C:/ and C:\ paths must identify the same profile and process.
    foreach ($bg3Field in @('projectWindows','profileWindows','windowsPython','gameWindows','steamExe')) {
        $bg3ResolvedPath = [IO.Path]::GetFullPath($bg3Config.$bg3Field)
        if ($bg3ResolvedPath.Length -gt [IO.Path]::GetPathRoot($bg3ResolvedPath).Length) {
            $bg3ResolvedPath = $bg3ResolvedPath.TrimEnd([char[]]'\/')
        }
        $bg3Config.$bg3Field = $bg3ResolvedPath
    }
}
catch {
    [ordered]@{ action = $Action.ToLowerInvariant(); actions = @(); needs_configuration = $true;
        config_path = $ConfigPath; error = $_.Exception.Message; next = 'Read SKILL.md and the repository docs/CODEX-SKILL.ko.md; ask before configuring missing setup.' } | ConvertTo-Json
    exit 2
}
$bg3Io = Join-Path $bg3Config.profileWindows 'Script Extender/BG3Friend'
$bg3GuiPath = Join-Path $bg3Config.projectWindows 'companion/gui.py'
$bg3GuiLegacyPath = $bg3GuiPath.Replace('\\wsl.localhost\', '\\wsl$\')

function Read-Bg3Json([string]$Path) {
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $null }
}

function Get-Bg3FileAge([string]$Path) {
    try {
        $written = (Get-Item -LiteralPath $Path).LastWriteTimeUtc
        return ([DateTime]::UtcNow - $written).TotalSeconds
    }
    catch { return $null }
}

function Get-Bg3State {
    $runnerPath = Join-Path $bg3Io 'runner.json'
    $runner = Read-Bg3Json $runnerPath
    $snapshotPath = Join-Path $bg3Io 'snapshot.json'
    $snapshot = Read-Bg3Json $snapshotPath
    # DrvFS file writes use host timestamps. The WSL JSON clock can drift from Windows.
    $runnerAge = if ($null -ne $runner.updated) { Get-Bg3FileAge $runnerPath } else { $null }
    $snapshotAge = if ($snapshot) { Get-Bg3FileAge $snapshotPath } else { $null }
    $runnerLive = $null -ne $runnerAge -and $runnerAge -ge 0 -and $runnerAge -lt 8 -and $runner.runner -ne 'stopped'
    $game = @(Get-Process -Name 'bg3', 'bg3_dx11' -ErrorAction SilentlyContinue)
    $launcher = @(Get-Process -Name 'LariLauncher' -ErrorAction SilentlyContinue)
    $gui = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
        $_.CommandLine -and (
            $_.CommandLine.IndexOf($bg3GuiPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $_.CommandLine.IndexOf($bg3GuiLegacyPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
        )
    })
    $freshGame = $game.Count -gt 0 -and $snapshot.protocol -eq 1 -and $snapshot.session -and
        $null -ne $snapshotAge -and $snapshotAge -ge 0 -and $snapshotAge -lt 4
    $connected = [bool]($freshGame -and $runnerLive -and $runner.session -eq $snapshot.session -and $runner.runner -ne 'error')
    $helperRunning = [bool]($runnerLive -and $gui.Count -gt 0)
    $mode = 'stopped'
    if ($runnerLive -and $runner.runner -eq 'error') { $mode = 'runner_error' }
    elseif ($runnerLive -and $runner.error) { $mode = 'model_error' }
    elseif ($runnerLive -xor ($gui.Count -gt 0)) { $mode = 'partial' }
    elseif ($helperRunning -and $game.Count -eq 0) { $mode = 'waiting_game' }
    elseif ($helperRunning -and -not $connected) { $mode = 'waiting_save' }
    elseif ($connected) { $mode = [string]$runner.runner }
    return [ordered]@{
        mode = $mode
        game_running = ($game.Count -gt 0)
        game_pids = @($game | ForEach-Object { $_.Id })
        launcher_running = ($launcher.Count -gt 0)
        helper_running = $helperRunning
        gui_pids = @($gui | ForEach-Object { $_.ProcessId })
        runner_alive = [bool]$runnerLive
        runner_state = $(if ($runnerLive) { $runner.runner } else { $null })
        runner_age_seconds = $(if ($null -ne $runnerAge) { [math]::Round($runnerAge, 1) } else { $null })
        snapshot_age_seconds = $(if ($null -ne $snapshotAge) { [math]::Round($snapshotAge, 1) } else { $null })
        game_connected = $connected
        companion = $(if ($connected) { $snapshot.companion.name } else { $null })
        blocked = $(if ($connected) { $snapshot.blocked } else { $null })
        model = $(if ($runnerLive) { $runner.model } else { $null })
        calls = $(if ($runnerLive) { $runner.calls } else { $null })
        runner_error = $(if ($runnerLive) { $runner.error } else { $null })
    }
}

function ConvertFrom-Bg3DiagnosticBytes([byte[]]$Bytes) {
    if ($Bytes.Length -eq 0) { return '' }
    # WSL writes Linux output as UTF-8 but Windows-side errors as UTF-16LE.
    $encoding = if ($Bytes -contains 0 -or ($Bytes.Length -ge 2 -and $Bytes[0] -eq 255 -and $Bytes[1] -eq 254)) {
        [Text.Encoding]::Unicode
    } else { [Text.Encoding]::UTF8 }
    return $encoding.GetString($Bytes).TrimStart([char]0xFEFF)
}

function Invoke-Bg3Diagnostic([string]$FilePath, [string[]]$Arguments) {
    $command = Get-Command -Name $FilePath -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) {
        return @{ exit_code = 127; output = @('Required command is missing: ' + $FilePath) }
    }
    # Quote argv for Windows without a shell. Keep simple distro names bare.
    $quotedArguments = foreach ($argument in $Arguments) {
        if ($argument.Length -gt 0 -and $argument -notmatch '[\s"]') { $argument }
        else {
            $escaped = [regex]::Replace($argument, '(\\*)"', '$1$1\"')
            $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
            '"' + $escaped + '"'
        }
    }
    $process = [Diagnostics.Process]::new()
    $stdout = [IO.MemoryStream]::new()
    $stderr = [IO.MemoryStream]::new()
    try {
        $process.StartInfo.FileName = $command.Source
        $process.StartInfo.Arguments = $quotedArguments -join ' '
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        $null = $process.Start()
        # Capture both streams concurrently as bytes before choosing encoding.
        $outTask = $process.StandardOutput.BaseStream.CopyToAsync($stdout)
        $errTask = $process.StandardError.BaseStream.CopyToAsync($stderr)
        $process.WaitForExit()
        $null = $outTask.GetAwaiter().GetResult()
        $null = $errTask.GetAwaiter().GetResult()
        $outText = ConvertFrom-Bg3DiagnosticBytes $stdout.ToArray()
        $errText = ConvertFrom-Bg3DiagnosticBytes $stderr.ToArray()
        $lines = @(($outText + "`n" + $errText) -split '\r?\n' | Where-Object { $_.Length -gt 0 })
        return @{ exit_code = $process.ExitCode; output = $lines }
    }
    catch { return @{ exit_code = 1; output = @($_.Exception.Message) } }
    finally {
        $process.Dispose()
        $stdout.Dispose()
        $stderr.Dispose()
    }
}

function Test-Bg3Prerequisites {
    $required = [ordered]@{
        launcher = (Join-Path $bg3Config.projectWindows 'Start-Friend.vbs')
        launch_script = (Join-Path $bg3Config.projectWindows 'scripts/launch.py')
        doctor_script = (Join-Path $bg3Config.projectWindows 'scripts/doctor.py')
        windows_python = $bg3Config.windowsPython
        windows_python_console = (Join-Path (Split-Path -Parent $bg3Config.windowsPython) 'python.exe')
        installed_mod = (Join-Path $bg3Config.profileWindows 'Mods/BG3Friend.pak')
        mod_registration_file = (Join-Path $bg3Config.profileWindows 'PlayerProfiles/Public/modsettings.lsx')
        script_extender = (Join-Path $bg3Config.gameWindows 'bin/DWrite.dll')
        game = (Join-Path $bg3Config.gameWindows 'bin/bg3_dx11.exe')
        steam = $bg3Config.steamExe
    }
    $missing = @($required.GetEnumerator() | Where-Object { -not (Test-Path -LiteralPath $_.Value -PathType Leaf) } |
        ForEach-Object { [ordered]@{ item = $_.Key; path = $_.Value } })
    $doctor = @()
    $doctorExit = $null
    if (Test-Path -LiteralPath $required.doctor_script -PathType Leaf) {
        $doctorResult = Invoke-Bg3Diagnostic 'wsl.exe' @('-d', $bg3Config.distro, '--cd', $bg3Config.projectLinux, '--exec', 'python3', 'scripts/doctor.py', '--io', $bg3Config.ioLinux)
        $doctor = $doctorResult.output
        $doctorExit = $doctorResult.exit_code
    }
    $profiles = @(Get-ChildItem -LiteralPath 'C:/Users' -Directory | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName "AppData/Local/Larian Studios/Baldur's Gate 3")
    })
    $profileMatches = $profiles.Count -eq 1 -and
        (Join-Path $profiles[0].FullName "AppData/Local/Larian Studios/Baldur's Gate 3") -eq $bg3Config.profileWindows
    $expectedPython = Join-Path (Split-Path -Parent (Split-Path -Parent $bg3Config.profileWindows)) 'Programs/Python/Python311/pythonw.exe'
    $pythonMatches = [string]::Equals([IO.Path]::GetFullPath($expectedPython), [IO.Path]::GetFullPath($bg3Config.windowsPython), [StringComparison]::OrdinalIgnoreCase)
    $tkAvailable = $false
    $tkOutput = @()
    if (Test-Path -LiteralPath $required.windows_python_console -PathType Leaf) {
        $tkResult = Invoke-Bg3Diagnostic $required.windows_python_console @('-c', "import tkinter; print(tkinter.Tcl().call('info', 'patchlevel'))")
        $tkOutput = $tkResult.output
        $tkAvailable = $tkResult.exit_code -eq 0
    }
    $modRegistered = $false
    try {
        [xml]$modSettings = Get-Content -LiteralPath $required.mod_registration_file -Raw
        $modRegistered = $null -ne $modSettings.SelectSingleNode('//node[@id="Mods"]//attribute[@id="UUID" and @value="cfd9c54e-3884-47ed-9b40-82b8747194de"]')
    }
    catch { $modRegistered = $false }
    $setupRequired = @()
    if (-not $profileMatches) { $setupRequired += 'launcher_profile_selection' }
    if (-not $pythonMatches) { $setupRequired += 'launcher_python_path' }
    if (-not $tkAvailable) { $setupRequired += 'windows_python_tk' }
    if (-not $modRegistered) { $setupRequired += 'bg3_friend_mod_registration' }
    if ($doctorExit -ne 0) { $setupRequired += 'wsl_python_or_codex_login' }
    return [ordered]@{
        ready = ($missing.Count -eq 0 -and $setupRequired.Count -eq 0)
        missing = $missing
        setup_required = $setupRequired
        launcher_profile_matches = [bool]$profileMatches
        launcher_python_matches = $pythonMatches
        windows_tk_available = $tkAvailable
        windows_tk_diagnostics = $tkOutput
        mod_registered = $modRegistered
        doctor_exit_code = $doctorExit
        doctor = $doctor
    }
}

$bg3Result = [ordered]@{ action = $Action.ToLowerInvariant(); actions = @() }
try {
    if ($Action -ne 'Status') { $bg3Result.preflight = Test-Bg3Prerequisites }
    $bg3Result.state = Get-Bg3State
    if ($Action -eq 'Start') {
        if (-not $bg3Result.preflight.ready) {
            throw 'Preflight failed. Read preflight.missing, doctor, and launcher_profile_matches before starting.'
        }
        if ($bg3Result.state.mode -in @('partial', 'runner_error', 'model_error')) {
            throw 'An existing helper needs attention. It was left running; no duplicate helper was started.'
        }
        if (-not $HelperOnly -and -not $bg3Result.state.game_running -and -not $bg3Result.state.launcher_running) {
            Start-Process -FilePath $bg3Config.steamExe -ArgumentList @('-applaunch', $bg3Config.steamAppId)
            $bg3Result.actions += 'game_launch_requested'
        }
        if (-not $bg3Result.state.helper_running) {
            $vbs = Join-Path $bg3Config.projectWindows 'Start-Friend.vbs'
            $wscript = Join-Path $env:SystemRoot 'System32/wscript.exe'
            Start-Process -FilePath $wscript -ArgumentList ('"' + $vbs + '"') -WindowStyle Hidden
            $bg3Result.actions += 'helper_launch_requested'
        }
        $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
        do {
            $bg3Result.state = Get-Bg3State
            if ($bg3Result.state.helper_running -and ($HelperOnly -or $bg3Result.state.game_running -or $bg3Result.state.launcher_running)) { break }
            if ([DateTime]::UtcNow -ge $deadline) { break }
            Start-Sleep -Milliseconds 800
        } while ($true)
        if (-not $bg3Result.state.helper_running) {
            throw 'Helper launch was not verified within the wait window. Inspect state before retrying.'
        }
    }
    $bg3Result | ConvertTo-Json -Depth 8
    if ($Action -eq 'Check' -and -not $bg3Result.preflight.ready) { exit 1 }
}
catch {
    $bg3Result.error = $_.Exception.Message
    $bg3Result | ConvertTo-Json -Depth 8
    exit 1
}
