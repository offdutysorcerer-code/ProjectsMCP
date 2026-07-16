param(
    [string]$Color = '#00E5FF',
    [int]$Size = 64
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class OverlayNativeMethods
{
    [DllImport("user32.dll", SetLastError = true)]
    public static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
}
"@

$Size = [Math]::Max(24, [Math]::Min($Size, 240))
try { $ringColor = [System.Drawing.ColorTranslator]::FromHtml($Color) }
catch { $ringColor = [System.Drawing.Color]::Cyan }

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::Magenta
$form.TransparencyKey = [System.Drawing.Color]::Magenta
$form.Width = $Size
$form.Height = $Size
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual

$script:pressed = $false
$form.Add_Paint({
    param($sender, $eventArgs)
    $graphics = $eventArgs.Graphics
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $inset = if ($script:pressed) { 11 } else { 7 }
    $width = if ($script:pressed) { 7 } else { 4 }
    $alpha = if ($script:pressed) { 255 } else { 220 }
    $drawColor = [System.Drawing.Color]::FromArgb($alpha, $ringColor.R, $ringColor.G, $ringColor.B)
    $pen = New-Object System.Drawing.Pen($drawColor, $width)
    try {
        $graphics.DrawEllipse($pen, $inset, $inset, $form.ClientSize.Width - (2 * $inset), $form.ClientSize.Height - (2 * $inset))
    } finally { $pen.Dispose() }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 16
$timer.Add_Tick({
    $position = [System.Windows.Forms.Cursor]::Position
    $form.Location = New-Object System.Drawing.Point([int]($position.X - ($form.Width / 2)), [int]($position.Y - ($form.Height / 2)))
    $newPressed = ([System.Windows.Forms.Control]::MouseButtons -band [System.Windows.Forms.MouseButtons]::Left) -ne 0
    if ($newPressed -ne $script:pressed) {
        $script:pressed = $newPressed
        $form.Invalidate()
    }
})

$form.Add_Shown({
    $GWL_EXSTYLE = -20
    $WS_EX_TRANSPARENT = 0x20
    $WS_EX_TOOLWINDOW = 0x80
    $WS_EX_NOACTIVATE = 0x08000000
    $style = [OverlayNativeMethods]::GetWindowLong($form.Handle, $GWL_EXSTYLE)
    [void][OverlayNativeMethods]::SetWindowLong($form.Handle, $GWL_EXSTYLE, $style -bor $WS_EX_TRANSPARENT -bor $WS_EX_TOOLWINDOW -bor $WS_EX_NOACTIVATE)
    $timer.Start()
})
$form.Add_FormClosed({ $timer.Stop(); $timer.Dispose() })
[System.Windows.Forms.Application]::Run($form)
