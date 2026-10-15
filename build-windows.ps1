param(
    [string]$Python = "python",
    [string]$InnoCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
$ErrorActionPreference = "Stop"
$sourceDir = $PSScriptRoot
$buildDir = Join-Path $sourceDir ".build"
$distDir = Join-Path $sourceDir "dist"
$releaseDir = Join-Path $sourceDir "release"
New-Item -ItemType Directory -Force $buildDir, $distDir, $releaseDir | Out-Null
# Use a Windows x64 Python 3.12+ with Tkinter and PyInstaller installed.
& $Python -m PyInstaller --noconfirm --clean --windowed --onedir --noupx --name SpireLens --icon (Join-Path $sourceDir "spirelens.ico") --add-data "$(Join-Path $sourceDir 'spirelens.ico');." --distpath $distDir --workpath $buildDir --specpath $buildDir (Join-Path $sourceDir "desktop.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Copy-Item -LiteralPath (Join-Path $sourceDir "WINDOWS-README.txt") -Destination (Join-Path $distDir "SpireLens\WINDOWS-README.txt")
Copy-Item -LiteralPath (Join-Path $sourceDir "licenses") -Destination (Join-Path $distDir "SpireLens\licenses") -Recurse -Force
& $InnoCompiler "/DAppDist=$(Join-Path $distDir 'SpireLens')" "/O$releaseDir" (Join-Path $sourceDir "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Compress-Archive -Path (Join-Path $distDir "SpireLens") -DestinationPath (Join-Path $releaseDir "SpireLens-1.1.0-Windows-x64-Portable.zip") -Force
