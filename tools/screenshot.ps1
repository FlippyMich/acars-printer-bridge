<#
    Development helper: capture a window to a PNG for UI review.

    Uses PrintWindow so the window is captured even when it is behind another
    application - it never steals focus from whatever you are doing.

        powershell -ExecutionPolicy Bypass -File tools\screenshot.ps1 -Out logs\ui.png
#>
param(
    [string]$Out = "logs\ui.png",
    [string]$TitleLike = "ACARS Printer Bridge*"
)

Add-Type -AssemblyName System.Drawing

$signature = @'
using System;
using System.Runtime.InteropServices;
public class WinCap {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
if (-not ("WinCap" -as [type])) { Add-Type -TypeDefinition $signature }

$proc = Get-Process | Where-Object { $_.MainWindowTitle -like $TitleLike } | Select-Object -First 1
if ($null -eq $proc) {
    Write-Host "No window matching '$TitleLike' found." -ForegroundColor Red
    exit 1
}
$handle = $proc.MainWindowHandle

if ([WinCap]::IsIconic($handle)) {
    [WinCap]::ShowWindow($handle, 9) | Out-Null   # SW_RESTORE, minimised windows cannot be captured
    Start-Sleep -Milliseconds 600
}

$rect = New-Object WinCap+RECT
[WinCap]::GetWindowRect($handle, [ref]$rect) | Out-Null
$width  = $rect.R - $rect.L
$height = $rect.B - $rect.T
if ($width -le 0 -or $height -le 0) {
    Write-Host "Window has no size yet." -ForegroundColor Red
    exit 1
}

$bitmap   = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc      = $graphics.GetHdc()
$ok       = [WinCap]::PrintWindow($handle, $hdc, 2)   # PW_RENDERFULLCONTENT
$graphics.ReleaseHdc($hdc)
$graphics.Dispose()

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$full = Join-Path (Resolve-Path -LiteralPath $dir).Path (Split-Path -Leaf $Out)
$bitmap.Save($full, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()

if (-not $ok) { Write-Host "PrintWindow reported a failure, the image may be blank." -ForegroundColor Yellow }
Write-Host "Saved $full ($width x $height)" -ForegroundColor Green
