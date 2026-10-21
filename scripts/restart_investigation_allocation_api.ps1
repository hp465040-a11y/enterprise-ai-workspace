# Run in ordinary PowerShell. Restart only this isolated 8125 API after read-only preflight.
# Docker PG credentials are held in process memory and never printed or persisted.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$oldUser = [Environment]::GetEnvironmentVariable('POSTGRES_USER', 'Process')
$oldPassword = [Environment]::GetEnvironmentVariable('POSTGRES_PASSWORD', 'Process')
$pgPassword = $null

try {
    $containerId = (& docker compose ps -q postgres 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw '本项目 postgres 容器不可读；8125 未重启。' }
    $inspectJson = & docker inspect $containerId 2>$null | Out-String
    if ($LASTEXITCODE -ne 0 -or -not $inspectJson) { throw '无法读取 postgres 容器；8125 未重启。' }
    $pgInfo = @($inspectJson | ConvertFrom-Json)
    if ($pgInfo.Count -ne 1 -or $pgInfo[0].Id -ne $containerId) {
        throw '容器身份不符；8125 未重启。'
    }
    if (-not @($pgInfo[0].NetworkSettings.Ports.'5432/tcp' |
              Where-Object { $_.HostPort -eq '5433' }).Count) {
        throw '本项目 postgres 未映射宿主 5433；8125 未重启。'
    }
    $pgEnvironment = @{}
    foreach ($entry in $pgInfo[0].Config.Env) {
        $parts = [string]$entry -split '=', 2
        if ($parts.Count -ne 2 -or -not $parts[0] -or $pgEnvironment.ContainsKey($parts[0])) {
            throw 'postgres 容器环境条目无效；8125 未重启。'
        }
        $pgEnvironment[$parts[0]] = $parts[1]
    }
    if (-not $pgEnvironment['POSTGRES_USER'] -or -not $pgEnvironment['POSTGRES_PASSWORD']) {
        throw 'postgres 容器未提供完整现有凭据；8125 未重启。'
    }
    $env:POSTGRES_USER = $pgEnvironment['POSTGRES_USER']
    $pgPassword = $pgEnvironment['POSTGRES_PASSWORD']
    $env:POSTGRES_PASSWORD = $pgPassword

    $python = (Resolve-Path -LiteralPath '.\.venv-d4\Scripts\python.exe').Path
    & $python 'scripts/investigation_allocation_demo.py' preflight
    if ($LASTEXITCODE -ne 0) { throw '隔离依赖预检失败；8125 未重启，也未运行模型。' }
    & $python 'scripts/investigation_allocation_demo.py' inspect
    if ($LASTEXITCODE -ne 0) { throw '保留数据只读核查失败；8125 未重启，也未运行模型。' }

    $statusPath = 'scripts/investigation_allocation_processes.json'
    $status = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($status.api_port -ne 8125 -or $status.web_port -ne 3110 -or -not $status.api_pid) {
        throw '本轮服务进程记录不符；8125 未重启。'
    }
    $listeners = @(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8125 -State Listen)
    if ($listeners.Count -ne 1) { throw '8125 监听者不唯一；未重启。' }
    $listenerPid = [int]$listeners[0].OwningProcess
    $recordedPid = [int]$status.api_pid
    $recorded = Get-Process -Id $recordedPid -ErrorAction Stop
    $listener = Get-Process -Id $listenerPid -ErrorAction Stop
    if ($recorded.Path -ne $python -or $listener.ProcessName -ne 'python') {
        throw '8125 与本轮已记录 Python 进程身份不符；未重启。'
    }
    if (@(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8125 -State Established `
          -ErrorAction SilentlyContinue).Count) {
        throw '8125 仍有活跃请求连接；未重启。'
    }

    Stop-Process -Id $listenerPid -ErrorAction Stop
    if ($recordedPid -ne $listenerPid) {
        Stop-Process -Id $recordedPid -ErrorAction SilentlyContinue
    }
    $released = $false
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 1
        if (-not @(Get-NetTCPConnection -LocalPort 8125 -State Listen -ErrorAction SilentlyContinue).Count) {
            $released = $true
            break
        }
    }
    if (-not $released) { throw '旧 8125 监听未释放；未启动第二个 API。' }

    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $stdout = "scripts/investigation_allocation_api_restart_$stamp.stdout.log"
    $stderr = "scripts/investigation_allocation_api_restart_$stamp.stderr.log"
    $api = Start-Process -FilePath $python -ArgumentList 'scripts/investigation_allocation_demo.py','serve' `
        -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    $status.api_pid = $api.Id
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    $ready = $false
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            $reply = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8125/openapi.json' `
                -TimeoutSec 3
            if ($reply.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw "新版 8125 启动后未就绪；查看 $stderr。" }
    Write-Output "READY api=8125 new_pid=$($api.Id) web=3110_preserved stdout=$stdout stderr=$stderr"
}
finally {
    [Environment]::SetEnvironmentVariable('POSTGRES_USER', $oldUser, 'Process')
    [Environment]::SetEnvironmentVariable('POSTGRES_PASSWORD', $oldPassword, 'Process')
    $pgPassword = $null
    $pgEnvironment = $null
    $inspectJson = $null
    $pgInfo = $null
}
