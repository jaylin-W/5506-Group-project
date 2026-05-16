[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:5000",
    [string]$DeviceToken = "5506-local-device-token",
    [string]$DeviceId = "xiao-esp32s3-sense-5506123",
    [string]$ProductCode = "5506123",
    [switch]$ResetWithFaceSuccess
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    throw "BaseUrl is required. Use the ngrok HTTPS URL or http://127.0.0.1:5000."
}

if ([string]::IsNullOrWhiteSpace($DeviceToken)) {
    throw "DeviceToken is required and must match DEVICE_API_TOKEN in the Flask .env file."
}

$BaseUrl = $BaseUrl.TrimEnd("/")
$headers = @{
    "X-Device-Token" = $DeviceToken
    "ngrok-skip-browser-warning" = "true"
}

function Invoke-DevicePost {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [hashtable]$ExtraBody = @{}
    )

    $payload = @{
        device_id = $DeviceId
        product_code = $ProductCode
    }

    foreach ($key in $ExtraBody.Keys) {
        $payload[$key] = $ExtraBody[$key]
    }

    $uri = "$BaseUrl$Path"
    $bodyJson = $payload | ConvertTo-Json -Compress

    Write-Host ""
    Write-Host "POST $uri" -ForegroundColor Cyan
    Write-Host $bodyJson -ForegroundColor DarkGray

    try {
        $response = Invoke-RestMethod `
            -Method Post `
            -Uri $uri `
            -Headers $headers `
            -ContentType "application/json" `
            -Body $bodyJson

        $response | ConvertTo-Json -Depth 10
        return $response
    }
    catch {
        Write-Host "Request failed. Check Flask, ngrok URL, DEVICE_API_TOKEN, product_code, and device_id." -ForegroundColor Red
        throw
    }
}

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Pill Box ngrok / Device API Flow Test" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "BaseUrl: $BaseUrl"
Write-Host "DeviceId: $DeviceId"
Write-Host "ProductCode: $ProductCode"

Write-Host ""
Write-Host "1. Poll reminder state. This simulates ESP checking the database-backed medication schedule." -ForegroundColor Yellow
Invoke-DevicePost "/api/device/reminder-state" @{ event = "poll_reminder" } | Out-Null

Write-Host ""
Write-Host "2. Report three face recognition failures. The third failure should require website PIN unlock." -ForegroundColor Yellow
for ($i = 1; $i -le 3; $i += 1) {
    Write-Host ""
    Write-Host "Face failure attempt $i / 3" -ForegroundColor Yellow
    Invoke-DevicePost "/api/face-unlock/failure" @{ event = "face_failed"; attempt = $i } | Out-Null
}

Write-Host ""
Write-Host "3. Poll device status. Expected device_action is wait_for_pin after three failures." -ForegroundColor Yellow
Invoke-DevicePost "/api/face-unlock/device-status" @{ event = "status" } | Out-Null

if ($ResetWithFaceSuccess) {
    Write-Host ""
    Write-Host "4. Resetting failure state through face success because -ResetWithFaceSuccess was provided." -ForegroundColor Yellow
    Invoke-DevicePost "/api/face-unlock/success" @{ event = "face_success" } | Out-Null
}
else {
    Write-Host ""
    Write-Host "Next manual step:" -ForegroundColor Green
    Write-Host "Open $BaseUrl/unlock while logged in, enter the pill box unlock password, then let ESP poll /api/face-unlock/device-status again."
    Write-Host "To reset by script instead, rerun with -ResetWithFaceSuccess."
}

