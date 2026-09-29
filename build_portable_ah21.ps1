#Requires -Version 5.1
<#
.SYNOPSIS
  Build ah21 portable package: Python + app + models + launcher.

.DESCRIPTION
  Output: <repo>\output_portable_ah21\  (ignored by existing output*/ gitignore)

  Steps:
  1. Copy base Python (from .venv pyvenv.cfg home) into Python\ (includes tkinter)
  2. Copy .venv Lib\site-packages into portable Python (fast; freeze file kept for reference)
  3. Copy runtime sources into app\
  4. Create models\, copy RapidDoc_ah21.bat

  Upstream sync: keep only *ah21* files; do not PR ah21 customizations upstream.

.PARAMETER SkipPipInstall
  Skip copying site-packages (refresh app/ and bat only).

.PARAMETER SourceModelsDir
  If set and exists, copy into models\; otherwise create empty models\.
#>
param(
    [switch]$SkipPipInstall,
    [string]$SourceModelsDir = $env:RAPID_MODELS_DIR
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $RepoRoot "gui_ah21.py"))) {
    throw "Run this script from the repo root (gui_ah21.py not found)."
}

$OutRoot = Join-Path $RepoRoot "output_portable_ah21"
$PythonOut = Join-Path $OutRoot "Python"
$AppOut = Join-Path $OutRoot "app"
$ModelsOut = Join-Path $OutRoot "models"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvPip = Join-Path $RepoRoot ".venv\Scripts\pip.exe"
$PyvenvCfg = Join-Path $RepoRoot ".venv\pyvenv.cfg"

Write-Host "==> Output: $OutRoot"

if (-not (Test-Path $VenvPython)) {
    throw ".venv not found. Create venv and install deps first."
}
if (-not (Test-Path $PyvenvCfg)) {
    throw ".venv\pyvenv.cfg not found."
}

# Resolve base Python home
$homeLine = Get-Content $PyvenvCfg | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
if (-not $homeLine) { throw "No home= in pyvenv.cfg" }
$BasePythonHome = ($homeLine -split "=", 2)[1].Trim()
$BasePythonExe = Join-Path $BasePythonHome "python.exe"
if (-not (Test-Path $BasePythonExe)) {
    throw "Base Python missing: $BasePythonExe"
}
Write-Host "==> Base Python: $BasePythonHome"

New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

# Copy full Python tree (tkinter needs tcl/tk)
$PortablePy = Join-Path $PythonOut "python.exe"
if ($SkipPipInstall -and (Test-Path $PortablePy)) {
    Write-Host "==> Keep existing Python (-SkipPipInstall): $PythonOut"
} else {
    Write-Host "==> Copying Python to $PythonOut (may take a while)"
    if (Test-Path $PythonOut) {
        Remove-Item -Recurse -Force $PythonOut
    }
    New-Item -ItemType Directory -Force -Path $PythonOut | Out-Null
    robocopy $BasePythonHome $PythonOut /E /NFL /NDL /NJH /NJS /nc /ns /np /XD __pycache__ .git | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        throw "robocopy Python failed, exit code $rc"
    }
}
if (-not (Test-Path $PortablePy)) {
    throw "Missing after copy: $PortablePy"
}

# Prefer copying .venv site-packages (fast, offline-friendly) over pip reinstall.
# Also write a freeze file for reference / rebuild on another machine.
$VenvSite = Join-Path $RepoRoot ".venv\Lib\site-packages"
$PortableSite = Join-Path $PythonOut "Lib\site-packages"
if (-not (Test-Path $PortableSite)) {
    New-Item -ItemType Directory -Force -Path $PortableSite | Out-Null
}

Write-Host "==> Ensuring pip on portable Python"
& $PortablePy -m ensurepip --upgrade 2>$null

$ReqFile = Join-Path $OutRoot "requirements_ah21_freeze.txt"
if (Test-Path $VenvPip) {
    $raw = & $VenvPip freeze
    $filtered = foreach ($line in $raw) {
        if ($line -match '^\s*#') { continue }
        if ($line -match '^-e\s+') { continue }
        if ($line -match '(?i)^(rapid-doc|rapid\.doc)\s*==') { continue }
        if ($line -match '(?i)^rapid-doc\s*@') { continue }
        $line
    }
    $filtered | Set-Content -Encoding UTF8 $ReqFile
    Write-Host "==> Wrote freeze ref: $ReqFile ($($filtered.Count) lines)"
}

if (-not $SkipPipInstall) {
    if (-not (Test-Path $VenvSite)) {
        throw ".venv\Lib\site-packages not found"
    }
    Write-Host "==> Copying site-packages from .venv (may take a while)"
    robocopy $VenvSite $PortableSite /E /NFL /NDL /NJH /NJS /nc /ns /np `
        /XD __pycache__ /XF *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy site-packages failed: $LASTEXITCODE"
    }
    # Drop editable / local rapid-doc links so app\ on PYTHONPATH is used
    Get-ChildItem $PortableSite -Force | Where-Object {
        $_.Name -match '(?i)^(rapid.doc|rapid-doc)' -or
        $_.Name -match '(?i)\.egg-link$' -or
        $_.Name -match '(?i)^__editable__'
    } | ForEach-Object {
        Write-Host "    remove local link: $($_.Name)"
        Remove-Item -Recurse -Force $_.FullName
    }
} else {
    Write-Host "==> Skip site-packages copy (-SkipPipInstall)"
}

Write-Host "==> Copying sources to $AppOut"
if (Test-Path $AppOut) {
    Remove-Item -Recurse -Force $AppOut
}
New-Item -ItemType Directory -Force -Path $AppOut | Out-Null

$copyItems = @(
    "rapid_doc",
    "gui_ah21.py",
    "demo_ah21.py",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "magic.json",
    "LICENSE"
)
foreach ($name in $copyItems) {
    $src = Join-Path $RepoRoot $name
    if (-not (Test-Path $src)) {
        Write-Host "    skip (missing): $name"
        continue
    }
    $dst = Join-Path $AppOut $name
    if (Test-Path $src -PathType Container) {
        # Do NOT exclude "models": magika ships models under rapid_doc/model/magika/models/
        robocopy $src $dst /E /NFL /NDL /NJH /NJS /nc /ns /np /XD __pycache__ .git /XF *.pyc | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy $name failed: $LASTEXITCODE" }
    } else {
        Copy-Item -Force $src $dst
    }
}

New-Item -ItemType Directory -Force -Path $ModelsOut | Out-Null
$srcModelsFull = if ($SourceModelsDir) { [System.IO.Path]::GetFullPath($SourceModelsDir) } else { $null }
$dstModelsFull = [System.IO.Path]::GetFullPath($ModelsOut)
if ($srcModelsFull -and (Test-Path $srcModelsFull) -and ($srcModelsFull -ne $dstModelsFull)) {
    Write-Host "==> Copying models: $srcModelsFull -> $dstModelsFull"
    robocopy $srcModelsFull $dstModelsFull /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy models failed: $LASTEXITCODE" }
} else {
    Write-Host "==> Empty models\ ready. Pass -SourceModelsDir or set RAPID_MODELS_DIR to bundle models."
    Write-Host "    Or copy models later into: $ModelsOut"
}

$BatSrc = Join-Path $RepoRoot "RapidDoc_ah21.bat"
$BatDst = Join-Path $OutRoot "RapidDoc_ah21.bat"
Copy-Item -Force $BatSrc $BatDst

Write-Host ""
Write-Host "Done: $OutRoot"
Write-Host "Launch: double-click RapidDoc_ah21.bat"
Write-Host "Dev: RapidDoc_ah21.bat at repo root uses .venv"
