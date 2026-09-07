param(
    [ValidateSet('capture','click','key','focus')][string]$Action = 'capture',
    [string]$Output = "$env:TEMP\bg3-friend-screen.png",
    [int]$X = 0,
    [int]$Y = 0,
    [string]$Keys = '',
    [string]$Process = 'bg3_dx11'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential)]
public struct FriendPoint { public int X; public int Y; public FriendPoint(int x,int y) { X=x; Y=y; } }
public static class FriendDesktop {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr handle, int command);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(FriendPoint point);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
}
'@
[FriendDesktop]::SetProcessDPIAware() | Out-Null
if ($Action -eq 'key' -or $Action -eq 'click') {
 $targetProcesses = @(Get-Process $Process -ErrorAction Stop | Where-Object MainWindowHandle -ne 0)
 [uint32]$foregroundProcessId = 0
 $inputWindow = [FriendDesktop]::GetForegroundWindow()
 if ($Action -eq 'click') { $inputWindow = [FriendDesktop]::WindowFromPoint([FriendPoint]::new($X,$Y)) }
 [FriendDesktop]::GetWindowThreadProcessId($inputWindow, [ref]$foregroundProcessId) | Out-Null
 if ($foregroundProcessId -notin $targetProcesses.Id) { throw "Input refused: target window is not $Process" }
}
switch ($Action) {
 'capture' {
  $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  try {
   $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
   $bitmap.Save($Output, [System.Drawing.Imaging.ImageFormat]::Png)
   Write-Output "$Output ($($bounds.Width)x$($bounds.Height); origin $($bounds.X),$($bounds.Y))"
  } finally { $graphics.Dispose(); $bitmap.Dispose() }
 }
 'focus' {
  $target = Get-Process $Process | Where-Object MainWindowHandle -ne 0 | Select-Object -First 1
  if (!$target) { throw "No window for $Process" }
  [FriendDesktop]::ShowWindowAsync($target.MainWindowHandle, 9) | Out-Null
  [FriendDesktop]::SetForegroundWindow($target.MainWindowHandle) | Out-Null
 }
 'click' {
  [FriendDesktop]::SetCursorPos($X, $Y) | Out-Null
  [FriendDesktop]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
  [System.Threading.Thread]::Sleep(90)
  [FriendDesktop]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
 }
 'key' {
  $scan = @{ '{ENTER}'=28; '{ESC}'=1; '{F1}'=59; '{F2}'=60; '{F3}'=61; '{F4}'=62; '{SPACE}'=57 }
  if ($scan.ContainsKey($Keys)) {
   [FriendDesktop]::keybd_event(0, $scan[$Keys], 8, [UIntPtr]::Zero)
   [System.Threading.Thread]::Sleep(90)
   [FriendDesktop]::keybd_event(0, $scan[$Keys], 10, [UIntPtr]::Zero)
  } else { [System.Windows.Forms.SendKeys]::SendWait($Keys) }
 }
}
