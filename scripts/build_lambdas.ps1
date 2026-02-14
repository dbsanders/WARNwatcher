$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BuildDir = Join-Path $RootDir "build"
$DistDir = Join-Path $RootDir "dist"

if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }

New-Item -ItemType Directory -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Path $DistDir | Out-Null

function Build-Lambda($Name) {
    $SrcDir = Join-Path $RootDir "lambda\$Name"
    $OutDir = Join-Path $BuildDir $Name

    New-Item -ItemType Directory -Path $OutDir | Out-Null
    Copy-Item (Join-Path $SrcDir "app.py") (Join-Path $OutDir "app.py")

    $ReqFile = Join-Path $SrcDir "requirements.txt"
    if (Test-Path $ReqFile) {
        python -m pip install -r $ReqFile -t $OutDir --upgrade
    }

    $ZipPath = Join-Path $DistDir "$Name.zip"
    Compress-Archive -Path (Join-Path $OutDir "*") -DestinationPath $ZipPath -Force
}

Build-Lambda "ingest"
Build-Lambda "match_notify"

Write-Output "Built:"
Write-Output " - $DistDir\ingest.zip"
Write-Output " - $DistDir\match_notify.zip"
