# Start Flask with Python 3.11, then expose it through an HTTPS ngrok tunnel.

$ErrorActionPreference = "Stop"

$Port = 5000
$AppDir = Join-Path $PSScriptRoot "Pill_box_V2_01_English\Pill_box_V2_01_English"
$OutLog = Join-Path $PSScriptRoot "flask-ngrok.out.log"
$ErrLog = Join-Path $PSScriptRoot "flask-ngrok.err.log"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Pill Box PWA Notification Test" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path (Join-Path $AppDir "app.py"))) {
    Write-Host "Cannot find Flask app at: $AppDir" -ForegroundColor Red
    exit 1
}

Write-Host "Checking Python 3.11 app environment..." -ForegroundColor Yellow
Push-Location $AppDir
try {
    & py -3.11 -c "import app; print('web_push_configured=' + str(app.can_send_web_push()))"
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Checking ngrok..." -ForegroundColor Yellow
& ngrok --version

$existingPort = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingPort) {
    Write-Host ""
    Write-Host "Port $Port is already in use. Stop that server first, then run this script again." -ForegroundColor Red
    $existingPort | Select-Object LocalAddress, LocalPort, State, OwningProcess
    exit 1
}

Write-Host ""
Write-Host "Starting Flask on http://127.0.0.1:$Port ..." -ForegroundColor Yellow
$flaskArgs = @("-3.11", "-m", "flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", "$Port")
$flaskProcess = Start-Process -WindowStyle Hidden -FilePath "py" -ArgumentList $flaskArgs -WorkingDirectory $AppDir -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru

try {
    Start-Sleep -Seconds 3
    Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/service-worker.js" | Out-Null

    Write-Host "Flask is ready." -ForegroundColor Green
    Write-Host ""
    Write-Host "ngrok will print an HTTPS URL. Open that HTTPS URL on your phone." -ForegroundColor Green
    Write-Host "After phone login, tap Enable Phone Alerts once, then close the phone browser." -ForegroundColor Green
    Write-Host "Use Send Test Notification from the desktop page to test background push." -ForegroundColor Green
    Write-Host ""

    & ngrok http "http://127.0.0.1:$Port"
} finally {
    if ($flaskProcess -and -not $flaskProcess.HasExited) {
        Write-Host ""
        Write-Host "Stopping Flask process..." -ForegroundColor Yellow
        Stop-Process -Id $flaskProcess.Id -Force
    }
}
