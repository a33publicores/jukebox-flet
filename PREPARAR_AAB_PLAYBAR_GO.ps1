# ============================================================
# PLAYBAR GO - PREPARAR AAB PARA GOOGLE PLAY
# ============================================================
# Basado en el flujo de publicación de Flet:
#   flet build aab
#
# Esta aplicación YA existe en Google Play:
#   application/bundle ID: com.a33.daleplay
#
# Última versión indicada por el registro aportado:
#   Version 1.0.9 / Code 9
#
# Esta preparación usa:
#   Version 1.0.10 / Code 10
#
# IMPORTANTE:
# - NO genera una nueva clave de firma.
# - Para actualizar la aplicación existente en Google Play debes
#   usar la misma clave de firma/upload key utilizada anteriormente.
# - El script busca esa clave mediante FLET_ANDROID_SIGNING_KEY_STORE
#   y las variables FLET_ANDROID_SIGNING_KEY_PASSWORD /
#   FLET_ANDROID_SIGNING_KEY_ALIAS.
# ============================================================

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Message -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    Write-Host ""
    Read-Host "Presiona ENTER para cerrar"
    exit 1
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

Write-Step "1. VERIFICANDO PROYECTO PLAYBAR GO"

if (-not (Test-Path "main.py")) { Fail "No se encontró main.py." }
if (-not (Test-Path "pyproject.toml")) { Fail "No se encontró pyproject.toml." }
if (-not (Test-Path "assets\logo.png")) { Fail "No se encontró assets\logo.png." }
if (-not (Test-Path "assets\splash.png")) { Fail "No se encontró assets\splash.png." }

Write-Host "Proyecto: $projectRoot"
Write-Host "Bundle ID: com.a33.daleplay"
Write-Host "Versión: 1.0.10"
Write-Host "Código: 10"

Write-Step "2. VERIFICANDO FLET"

$flet = Get-Command flet -ErrorAction SilentlyContinue
if (-not $flet) {
    Fail "No se encontró 'flet' en PATH. Instala/actualiza Flet antes de continuar."
}

flet --version

Write-Step "3. VERIFICANDO JAVA"

$java = Get-Command java -ErrorAction SilentlyContinue
if (-not $java) {
    Fail "No se encontró Java. Flet requiere un JDK compatible para Android."
}

java -version

Write-Step "4. VERIFICANDO FIRMA DE GOOGLE PLAY"

if (-not $env:FLET_ANDROID_SIGNING_KEY_STORE) {
    Write-Host ""
    Write-Host "No se configuró FLET_ANDROID_SIGNING_KEY_STORE." -ForegroundColor Yellow
    Write-Host "El AAB puede compilarse sin firma personalizada, pero NO debes subirlo"
    Write-Host "como actualización de la aplicación existente si requiere la clave de carga anterior."
    Write-Host ""
    $seguir = Read-Host "¿Deseas continuar solamente con la compilación de prueba? (S/N)"
    if ($seguir -notmatch '^[sS]$') {
        Fail "Proceso cancelado para proteger la firma de Google Play."
    }
}
else {
    if (-not (Test-Path $env:FLET_ANDROID_SIGNING_KEY_STORE)) {
        Fail "No existe el keystore configurado en FLET_ANDROID_SIGNING_KEY_STORE."
    }

    Write-Host "Keystore: $env:FLET_ANDROID_SIGNING_KEY_STORE"
    if (-not $env:FLET_ANDROID_SIGNING_KEY_ALIAS) {
        Fail "Falta FLET_ANDROID_SIGNING_KEY_ALIAS."
    }
    if (-not $env:FLET_ANDROID_SIGNING_KEY_PASSWORD) {
        Fail "Falta FLET_ANDROID_SIGNING_KEY_PASSWORD."
    }
    Write-Host "Alias configurado: $env:FLET_ANDROID_SIGNING_KEY_ALIAS"
}

Write-Step "5. LIMPIANDO BUILD ANTERIOR"

if (Get-Command flet -ErrorAction SilentlyContinue) {
    flet clean
    if ($LASTEXITCODE -ne 0) {
        Fail "flet clean falló."
    }
}

Write-Step "6. CONSTRUYENDO AAB"

$buildArgs = @(
    "build", "aab",
    ".",
    "--project", "playbar_go",
    "--product", "PlayBar GO",
    "--org", "com.a33",
    "--bundle-id", "com.a33.daleplay",
    "--build-version", "1.0.10",
    "--build-number", "10",
    "--splash-color", "#020617",
    "--splash-dark-color", "#020617",
    "--python-version", "3.13",
    "--output", "build\aab"
)

if ($env:FLET_ANDROID_SIGNING_KEY_STORE) {
    $buildArgs += "--android-signing-key-store"
    $buildArgs += $env:FLET_ANDROID_SIGNING_KEY_STORE
    $buildArgs += "--android-signing-key-alias"
    $buildArgs += $env:FLET_ANDROID_SIGNING_KEY_ALIAS
    $buildArgs += "--android-signing-key-password"
    $buildArgs += $env:FLET_ANDROID_SIGNING_KEY_PASSWORD
}

Write-Host ""
Write-Host "Ejecutando flet build aab..." -ForegroundColor White
& flet @buildArgs

if ($LASTEXITCODE -ne 0) {
    Fail "Flet no pudo generar el AAB."
}

Write-Step "7. LOCALIZANDO AAB"

$aabFiles = Get-ChildItem -Path (Join-Path $projectRoot "build\aab") -Recurse -Filter "*.aab" -File -ErrorAction SilentlyContinue

if (-not $aabFiles -or $aabFiles.Count -eq 0) {
    Fail "No se encontró ningún archivo .aab en build\aab."
}

$aab = $aabFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Host ""
Write-Host "AAB generado correctamente:" -ForegroundColor Green
Write-Host $aab.FullName -ForegroundColor Yellow
Write-Host ("Tamaño: {0:N2} MB" -f ($aab.Length / 1MB))

Write-Step "8. RESUMEN"

Write-Host "Aplicación : PlayBar GO"
Write-Host "Bundle ID  : com.a33.daleplay"
Write-Host "Versión    : 1.0.10"
Write-Host "Código     : 10"
Write-Host "AAB        : $($aab.FullName)"
Write-Host ""
Write-Host "El siguiente paso es validar el AAB en Google Play Console."
Write-Host ""

Start-Process explorer.exe -ArgumentList "/select,`"$($aab.FullName)`""

Read-Host "Presiona ENTER para cerrar"
