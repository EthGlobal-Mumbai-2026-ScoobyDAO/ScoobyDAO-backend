# Dot-source this script so settings remain in the current service shell.
[CmdletBinding()]
param(
    [switch]$PersistUser,
    [switch]$IncludeWorld,
    [switch]$LoadOnly
)

$scoobyProviderNames = @('SEARCHAPI_API_KEY', 'PUBLICNODE_TOKEN', 'OPENAI_API_KEY')
$scoobyWorldNames = @('WORLD_ISSUER', 'WORLD_CLIENT_ID', 'WORLD_CLIENT_KEY_PATH', 'WORLD_CLIENT_KEY_ID')
$scoobyDefaults = [ordered]@{
    SCOOBY_WEB_ORIGIN = 'http://127.0.0.1:3000'
    SCOOBY_MODEL_CALL_BUDGET = '0'
    SCOOBY_CASE_SYNC_ENABLED = 'false'
    SCOOBY_PUBLISH_ENABLED = 'false'
    SCOOBY_DEMO_AUTOPUBLISH = 'false'
    NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000/web/v1'
    NEXT_PUBLIC_REPORT_API_URL = 'http://127.0.0.1:8000'
    NEXT_PUBLIC_SCOUTING_API_URL = 'http://127.0.0.1:8000'
    NEXT_PUBLIC_USE_FIXTURES = 'false'
}

function Set-ScoobyEnvironmentValue {
    param([string]$Name, [string]$Value)
    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
    if ($PersistUser) {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
    }
}

function Read-ScoobyExistingValue {
    param([string]$Name)
    $scoobyExisting = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ([string]::IsNullOrWhiteSpace($scoobyExisting)) {
        $scoobyExisting = [Environment]::GetEnvironmentVariable($Name, 'User')
    }
    return $scoobyExisting
}

foreach ($scoobyEntry in $scoobyDefaults.GetEnumerator()) {
    # Explicit local setup keeps paid model calls, network sync and publication off.
    Set-ScoobyEnvironmentValue -Name $scoobyEntry.Key -Value $scoobyEntry.Value
}

foreach ($scoobyName in $scoobyProviderNames) {
    $scoobyValue = Read-ScoobyExistingValue -Name $scoobyName
    if (-not $LoadOnly) {
        $scoobySecret = Read-Host "$scoobyName (Enter keeps existing, or skips if absent)" -AsSecureString
        $scoobyTyped = [System.Net.NetworkCredential]::new('', $scoobySecret).Password
        if (-not [string]::IsNullOrWhiteSpace($scoobyTyped)) { $scoobyValue = $scoobyTyped }
        Remove-Variable scoobySecret, scoobyTyped
    }
    if (-not [string]::IsNullOrWhiteSpace($scoobyValue)) {
        Set-ScoobyEnvironmentValue -Name $scoobyName -Value $scoobyValue
    }
    Write-Host ($scoobyName + ': ' + $(if ($scoobyValue) { 'configured' } else { 'not configured' }))
    Remove-Variable scoobyValue
}

if ($IncludeWorld) {
    foreach ($scoobyName in $scoobyWorldNames) {
        $scoobyValue = Read-ScoobyExistingValue -Name $scoobyName
        if ($scoobyName -eq 'WORLD_ISSUER' -and -not $scoobyValue) { $scoobyValue = 'https://auth.world.org' }
        if (-not $LoadOnly) {
            $scoobyTyped = Read-Host "$scoobyName (Enter keeps existing/default, or skips)"
            if (-not [string]::IsNullOrWhiteSpace($scoobyTyped)) { $scoobyValue = $scoobyTyped }
            Remove-Variable scoobyTyped
        }
        if ($scoobyName -eq 'WORLD_CLIENT_KEY_PATH' -and $scoobyValue -and -not (Test-Path -LiteralPath $scoobyValue -PathType Leaf)) {
            throw 'WORLD_CLIENT_KEY_PATH must point to an existing private signing-key file.'
        }
        if ($scoobyValue) { Set-ScoobyEnvironmentValue -Name $scoobyName -Value $scoobyValue }
        Write-Host ($scoobyName + ': ' + $(if ($scoobyValue) { 'configured' } else { 'not configured' }))
        Remove-Variable scoobyValue
    }
}

$scoobyOperator = Read-ScoobyExistingValue -Name 'SCOOBY_OPERATOR_TOKEN'
if (-not $scoobyOperator -and -not $LoadOnly) {
    $scoobyBytes = New-Object byte[] 32
    $scoobyRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $scoobyRng.GetBytes($scoobyBytes) } finally { $scoobyRng.Dispose() }
    $scoobyOperator = [Convert]::ToBase64String($scoobyBytes)
    Remove-Variable scoobyBytes, scoobyRng
}
if ($scoobyOperator) { Set-ScoobyEnvironmentValue -Name 'SCOOBY_OPERATOR_TOKEN' -Value $scoobyOperator }
Remove-Variable scoobyOperator

Write-Host 'Local environment loaded. Start/restart API, worker and frontend from configured shells.'
Write-Host 'This script makes no provider/model/World/chain requests and writes no secret files.'
