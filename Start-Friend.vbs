Option Explicit
Dim shell, fso, folder, parts, distro, linuxFolder, wsl, command, namePattern, i, code
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
parts = Split(folder, "\")
distro = ""
wsl = Quote(shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wsl.exe")
If UBound(parts) >= 3 Then
    If LCase(parts(2)) = "wsl.localhost" Or LCase(parts(2)) = "wsl$" Then
        distro = parts(3)
        linuxFolder = ""
        For i = 4 To UBound(parts)
            linuxFolder = linuxFolder & "/" & parts(i)
        Next
    End If
End If
If distro <> "" Then
    ' WSL's distribution argument must be unquoted on the tested Windows build.
    Set namePattern = New RegExp
    namePattern.Pattern = "^[A-Za-z0-9_.-]+$"
    If Not namePattern.Test(distro) Then
        MsgBox "Open this project's WSL terminal and run: python3 scripts/launch.py", 48, "BG3 Friend"
        WScript.Quit 1
    End If
    command = wsl & " -d " & distro & " --cd " & Quote(linuxFolder)
Else
    command = wsl & " --cd " & Quote(folder)
End If
command = command & " python3 scripts/launch.py"
code = shell.Run(command, 0, True)
If code <> 0 Then
    MsgBox "BG3 Friend could not start. If it is already running, switch back to the game. Otherwise run scripts/doctor.py from WSL.", 48, "BG3 Friend"
End If

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
