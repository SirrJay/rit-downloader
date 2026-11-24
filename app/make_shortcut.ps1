# Creates "Rit Downloader" shortcuts on the Desktop and in the Start menu.
$root = Split-Path -Parent $PSScriptRoot
$sh = New-Object -ComObject WScript.Shell
$targets = @(
  [Environment]::GetFolderPath('Desktop'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) '')
)
foreach ($dir in $targets) {
  $lnk = $sh.CreateShortcut((Join-Path $dir 'Rit Downloader.lnk'))
  $lnk.TargetPath = Join-Path $root '.venv\Scripts\pythonw.exe'
  $lnk.Arguments = '"' + (Join-Path $root 'app\server.py') + '"'
  $lnk.WorkingDirectory = $root
  $lnk.IconLocation = (Join-Path $root 'app\static\icon.ico') + ',0'
  $lnk.Description = 'Search and download videos and audio in bulk'
  $lnk.Save()
}
Write-Host "Shortcuts created."
