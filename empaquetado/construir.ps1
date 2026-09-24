# Construye Farmadex: ejecutable, zip portable e instalador.
#
#   powershell -ExecutionPolicy Bypass -File empaquetado\construir.ps1
#
# Deja todo en dist\ con su SHA-256. El instalador solo se genera si esta
# instalado Inno Setup 6; sin el, el zip portable sirve igual.

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No hay entorno virtual. Creandolo..." -ForegroundColor Yellow
    python -m venv .venv
    & $python -m pip install --upgrade pip
    & $python -m pip install -e ".[dev]" PySide6 httpx rapidfuzz rapidocr-onnxruntime mss pyinstaller pywebview
}

$version = (Select-String -Path (Join-Path $raiz "src\farmadex\__init__.py") -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "== Farmadex $version ==" -ForegroundColor Cyan

Write-Host "`n[1/5] Pruebas" -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = "offscreen"
& $python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas no pasan: no se empaqueta" }
Remove-Item Env:\QT_QPA_PLATFORM

Write-Host "`n[2/5] PyInstaller" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $python -m PyInstaller --noconfirm --distpath dist --workpath build empaquetado\farmadex.spec
if ($LASTEXITCODE -ne 0) { throw "Fallo el empaquetado" }

Write-Host "`n[3/5] Poda de lo que no se usa" -ForegroundColor Cyan
$interno = "dist\Farmadex\_internal"
$sobra = @(
    "$interno\cv2\data",                    # clasificadores Haar: no se usan
    "$interno\PySide6\translations",
    "$interno\PySide6\qml",
    "$interno\PySide6\resources",
    "$interno\PIL\Tk"
)
foreach ($ruta in $sobra) {
    if (Test-Path $ruta) {
        $mb = [math]::Round((Get-ChildItem $ruta -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
        Remove-Item -Recurse -Force $ruta
        Write-Host "  quitado $ruta ($mb MB)"
    }
}

Write-Host "`n[4/5] Zip portable" -ForegroundColor Cyan
$zip = "dist\Farmadex-$version-portable.zip"
Compress-Archive -Path "dist\Farmadex\*" -DestinationPath $zip -Force

Write-Host "`n[5/5] Instalador" -ForegroundColor Cyan
# Qt y ONNX Runtime necesitan el runtime de Visual C++ 2015-2022. El instalador lo
# mete solo si el fichero esta aqui; si no esta, se descarga de Microsoft. Sin el,
# en un Windows recien instalado el programa no llega ni a abrir la ventana.
$redist = Join-Path $raiz "empaquetado\vc_redist.x64.exe"
if (-not (Test-Path $redist)) {
    Write-Host "  Descargando vc_redist.x64.exe (runtime de Visual C++)..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $redist -UseBasicParsing
    } catch {
        Remove-Item $redist -Force -ErrorAction SilentlyContinue
        Write-Host "  No se pudo descargar: el instalador saldra SIN el runtime de Visual C++." -ForegroundColor Red
        Write-Host "  Bajalo a mano de https://aka.ms/vs/17/release/vc_redist.x64.exe y dejalo en empaquetado\." -ForegroundColor Red
    }
}
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"   # instalacion por usuario (winget)
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = "no-instalado" }
if (Test-Path $iscc) {
    & $iscc /Qp "/DVersionApp=$version" empaquetado\instalador.iss
    if ($LASTEXITCODE -ne 0) { throw "Fallo la compilacion del instalador" }
} else {
    Write-Host "  Inno Setup 6 no esta instalado: se omite el instalador." -ForegroundColor Yellow
    Write-Host "  Descargalo de https://jrsoftware.org/isdl.php y vuelve a lanzar esto." -ForegroundColor Yellow
}

Write-Host "`nCopiando a la carpeta de actualizaciones" -ForegroundColor Cyan
# Farmadex mira esta carpeta al arrancar y ofrece instalar lo que encuentre.
$destino = Join-Path $env:LOCALAPPDATA "Farmadex" | Join-Path -ChildPath "actualizaciones"
New-Item -ItemType Directory -Force -Path $destino | Out-Null
Copy-Item "dist\*.exe", "dist\*.zip" -Destination $destino -Force -ErrorAction SilentlyContinue
Copy-Item "CHANGELOG.md" -Destination $destino -Force
Write-Host "  $destino"

Write-Host "`n== Resultado ==" -ForegroundColor Cyan
$tamano = [math]::Round((Get-ChildItem "dist\Farmadex" -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "Instalado: $tamano MB"
Get-ChildItem dist -File | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    Write-Host ("{0}  {1} MB`n  SHA-256 {2}" -f $_.Name, [math]::Round($_.Length / 1MB, 1), $hash)
}
