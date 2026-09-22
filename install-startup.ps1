# Makes text-snip start automatically when Windows starts, and starts it now.
# Run with -Uninstall to remove it from startup and stop it.
param([switch]$Uninstall)

$shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'text-snip.lnk'
$script = Join-Path $PSScriptRoot 'text_snip.py'

# Stop any copy that is already running.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*text_snip.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

if ($Uninstall) {
    Remove-Item $shortcut -ErrorAction SilentlyContinue
    Write-Host 'text-snip removed from startup and stopped.'
    return
}

$python = & python -c "import sys; print(sys.executable)"
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'  # pythonw = no console window

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $pythonw
$link.Arguments = "`"$script`""
$link.WorkingDirectory = $PSScriptRoot
$link.Description = 'text-snip: Ctrl+Alt+T to copy text from the screen'
$link.Save()

Start-Process $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $PSScriptRoot
Write-Host 'text-snip is running and will start with Windows. Press Ctrl+Alt+T to try it.'
