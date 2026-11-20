# Build the standalone Windows package of GeoHydro Pro.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Produces in dist\:
#   GeoHydroPro\                         the application folder (run GeoHydroPro.exe)
#   GeoHydroPro-<version>-win64.zip      portable zip of that folder
#   GeoHydroPro-<version>-Setup.exe      installer (if Inno Setup 6 is available)
#   GeoHydroPro-<version>-selftest.txt   self-test report of the frozen build
# Run from the repository root in a Python 3.12 (64-bit) environment.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install --upgrade pip
pip install -r requirements.txt "pyinstaller>=6.10,<7" "pillow>=10"
$version = python -c "import geohydro; print(geohydro.__version__)"
Write-Host "Building GeoHydro Pro $version"

$env:QT_QPA_PLATFORM = "offscreen"
python packaging\make_icon.py
python packaging\make_version_info.py
Remove-Item -Recurse -Force build, dist\GeoHydroPro -ErrorAction SilentlyContinue
pyinstaller packaging\geohydro_pro.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Self-test the frozen build (windowed exe: wait for it and read the report file)
$report = Join-Path (Resolve-Path dist) "GeoHydroPro-$version-selftest.txt"
$p = Start-Process -FilePath "dist\GeoHydroPro\GeoHydroPro.exe" `
     -ArgumentList "--selftest", "--report", "`"$report`"" -Wait -PassThru
Get-Content $report
if ($p.ExitCode -ne 0) { throw "Frozen self-test failed (exit $($p.ExitCode))" }

$zip = "dist\GeoHydroPro-$version-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path dist\GeoHydroPro -DestinationPath $zip -CompressionLevel Optimal

$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
  foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $c) { $iscc = $c }
  }
}
if ($iscc) {
  & $iscc "/DAppVersion=$version" packaging\installer.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
  Write-Warning "Inno Setup 6 not found: installer not built (the zip is still usable)."
}
Get-ChildItem dist -File | Format-Table Name, Length
$size = (Get-ChildItem dist\GeoHydroPro -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("Application folder size: {0:N0} MB" -f ($size / 1MB))
