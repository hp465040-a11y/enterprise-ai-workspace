# Ordinary PowerShell entry. Preflight is read only; -Run is one model attempt.
param(
    [ValidateSet('A','B','B2','C')]
    [string]$Case,
    [switch]$PreflightAll,
    [switch]$UpgradeB,
    [switch]$RepairB,
    [switch]$Run
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($UpgradeB -and ($PreflightAll -or $Run -or $Case -or $RepairB)) { throw 'UpgradeB cannot be combined with other modes.' }
if ($RepairB -and ($PreflightAll -or $Run -or $Case)) { throw 'RepairB cannot be combined with Case, Run, or PreflightAll.' }
if ($PreflightAll -and ($Run -or $Case)) { throw 'PreflightAll cannot be combined with Case or Run.' }
if (-not $PreflightAll -and -not $Case -and -not $UpgradeB -and -not $RepairB) { throw 'Choose one Case, PreflightAll, UpgradeB, or RepairB.' }
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$previousUser = [Environment]::GetEnvironmentVariable('POSTGRES_USER', 'Process')
$previousPassword = [Environment]::GetEnvironmentVariable('POSTGRES_PASSWORD', 'Process')
$previousDatabase = [Environment]::GetEnvironmentVariable('DATABASE_URL', 'Process')
$pgPassword = $null
try {
    $containerId = (& docker compose ps -q postgres 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Project postgres container unavailable; no evaluation run.' }
    $inspectJson = & docker inspect $containerId 2>$null | Out-String
    if ($LASTEXITCODE -ne 0 -or -not $inspectJson) { throw 'Container inspection unavailable; no evaluation run.' }
    $pgInfo = @($inspectJson | ConvertFrom-Json)
    if ($pgInfo.Count -ne 1 -or $pgInfo[0].Id -ne $containerId) {
        throw 'Docker container identity differs; no evaluation run.'
    }
    if (-not @($pgInfo[0].NetworkSettings.Ports.'5432/tcp' | Where-Object { $_.HostPort -eq '5433' }).Count) {
        throw 'Project postgres host mapping is not 5433; no evaluation run.'
    }
    $pgEnvironment = @{}
    foreach ($entry in $pgInfo[0].Config.Env) {
        $parts = [string]$entry -split '=', 2
        if ($parts.Count -ne 2 -or -not $parts[0] -or $pgEnvironment.ContainsKey($parts[0])) {
            throw 'Container environment entry is invalid; no evaluation run.'
        }
        $pgEnvironment[$parts[0]] = $parts[1]
    }
    if (-not $pgEnvironment['POSTGRES_USER'] -or -not $pgEnvironment['POSTGRES_PASSWORD']) {
        throw 'Container PG login configuration is missing; no evaluation run.'
    }
    $env:POSTGRES_USER = $pgEnvironment['POSTGRES_USER']
    $pgPassword = $pgEnvironment['POSTGRES_PASSWORD']
    $env:POSTGRES_PASSWORD = $pgPassword
    $python = (Resolve-Path -LiteralPath '.\.venv-d4\Scripts\python.exe').Path
    if ($UpgradeB -or $RepairB) {
        $repairCommand = if ($RepairB) { 'repair-b' } else { 'upgrade-b' }
        & $python 'scripts/investigation_minieval_once.py' $repairCommand
        if ($LASTEXITCODE -ne 0) { throw 'B isolated schema repair failed; original evidence retained; no evaluation run.' }
        foreach ($caseKey in @('A','B','C')) {
            & $python 'scripts/investigation_minieval_once.py' 'preflight' '--case' $caseKey
            if ($LASTEXITCODE -ne 0) { throw "Post-repair preflight for $caseKey failed; no evaluation run." }
        }
        return
    }
    $command = if ($Run) { 'run' } else { 'preflight' }
    $cases = if ($PreflightAll) { @('A','B','C') } else { @($Case) }
    foreach ($caseKey in $cases) {
        & $python 'scripts/investigation_minieval_once.py' $command '--case' $caseKey
        if ($LASTEXITCODE -ne 0) { throw "Evaluation $command for $caseKey failed; evidence retained and no retry." }
    }
} finally {
    [Environment]::SetEnvironmentVariable('POSTGRES_USER', $previousUser, 'Process')
    [Environment]::SetEnvironmentVariable('POSTGRES_PASSWORD', $previousPassword, 'Process')
    [Environment]::SetEnvironmentVariable('DATABASE_URL', $previousDatabase, 'Process')
    $pgPassword = $null
    $pgEnvironment = $null
    $pgInfo = $null
    $inspectJson = $null
}
