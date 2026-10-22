# Run in ordinary PowerShell. Reads this Compose project's existing PG environment
# in memory; never prints it or changes .env, containers, or retained demo data.
param(
    [switch]$VerifyOnly,
    [switch]$ControlledRefresh,
    [switch]$ControlledRefreshSecond,
    [ValidateSet('test_failure_deadline_and_unsaved_report')]
    [string]$TestMethod
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($TestMethod -and -not $VerifyOnly) { throw '单方法选择只能与 -VerifyOnly 一起使用。' }
if ($VerifyOnly -and $ControlledRefresh) { throw '受控页面入口与专项验证不能同时启动。' }
if ($ControlledRefreshSecond -and -not $ControlledRefresh) { throw '第二次受控入口须与 -ControlledRefresh 一起使用。' }
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$previousUser = [Environment]::GetEnvironmentVariable('POSTGRES_USER', 'Process')
$previousPassword = [Environment]::GetEnvironmentVariable('POSTGRES_PASSWORD', 'Process')
$previousBackend = [Environment]::GetEnvironmentVariable('BACKEND_INTERNAL_URL', 'Process')
$previousPublic = [Environment]::GetEnvironmentVariable('NEXT_PUBLIC_API_URL', 'Process')
$previousDist = [Environment]::GetEnvironmentVariable('NEXT_DIST_DIR', 'Process')
$previousControlled = [Environment]::GetEnvironmentVariable('NEXT_PUBLIC_INVESTIGATION_CONTROLLED_REFRESH', 'Process')
$pgPassword = $null
try {
    $containerId = (& docker compose ps -q postgres 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw '本项目 postgres 容器不可读；未准备演示数据。' }
    $inspectJson = & docker inspect $containerId 2>$null | Out-String
    if ($LASTEXITCODE -ne 0 -or -not $inspectJson) {
        throw '无法读取本项目 postgres 容器信息；未准备演示数据。'
    }
    $pgInfo = @($inspectJson | ConvertFrom-Json)
    if ($pgInfo.Count -ne 1 -or $pgInfo[0].Id -ne $containerId) {
        throw '容器身份与本项目 postgres 不一致；未准备演示数据。'
    }
    $ports = $pgInfo[0].NetworkSettings.Ports
    if (-not @($ports.'5432/tcp' | Where-Object { $_.HostPort -eq '5433' }).Count) {
        throw '本项目 postgres 未映射到宿主 5433；未准备演示数据。'
    }
    $pgEnvironment = @{}
    foreach ($entry in $pgInfo[0].Config.Env) {
        $parts = [string]$entry -split '=', 2
        if ($parts.Count -ne 2 -or -not $parts[0]) {
            throw '容器环境条目格式无效；未准备演示数据。'
        }
        if ($pgEnvironment.ContainsKey($parts[0])) {
            throw '容器环境存在重复键；未准备演示数据。'
        }
        $pgEnvironment[$parts[0]] = $parts[1]
    }
    if (-not $pgEnvironment.ContainsKey('POSTGRES_USER') -or
        -not $pgEnvironment.ContainsKey('POSTGRES_PASSWORD')) {
        throw '容器未提供唯一的 PG 用户和密码；未准备演示数据。'
    }
    $env:POSTGRES_USER = $pgEnvironment['POSTGRES_USER']
    $pgPassword = $pgEnvironment['POSTGRES_PASSWORD']
    if (-not $env:POSTGRES_USER -or -not $pgPassword) { throw 'PG 凭据为空；未准备演示数据。' }
    $env:POSTGRES_PASSWORD = $pgPassword
    $python = (Resolve-Path -LiteralPath '.\.venv-d4\Scripts\python.exe').Path
    if ($VerifyOnly) {
        $verifyArguments = @('scripts/investigation_run_verify.py')
        if ($TestMethod) { $verifyArguments += $TestMethod }
        $previousErrorPreference = $ErrorActionPreference
        try {
            # PowerShell 5.1 otherwise turns Python's first traceback line into a
            # terminating NativeCommandError and hides the remaining stack.
            $ErrorActionPreference = 'Continue'
            & $python @verifyArguments 2>&1 | ForEach-Object { Write-Output ($_.ToString()) }
            $verifyExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorPreference
        }
        if ($verifyExitCode -ne 0) { throw '隔离调查生命周期测试失败；保留测试输出。' }
        return
    }

    if ($ControlledRefresh) {
        $apiPort = if ($ControlledRefreshSecond) { 8127 } else { 8126 }
        $webPort = if ($ControlledRefreshSecond) { 3113 } else { 3112 }
        $waitSeconds = if ($ControlledRefreshSecond) { 90 } else { 20 }
        $suffix = if ($ControlledRefreshSecond) { '_second' } else { '' }
        $statusPath = 'scripts/investigation_refresh_controlled_processes' + $suffix + '.json'
        if (-not (Test-Path -LiteralPath 'scripts/action_request_demo_state.json') -or
            -not (Test-Path -LiteralPath 'scripts/investigation_allocation_demo_state.json')) {
            throw '既有隔离演示状态缺失；未新建资源或启动服务。'
        }
        & $python 'scripts/action_request_demo.py' inspect
        if ($LASTEXITCODE -ne 0) { throw '既有隔离身份检查失败；未启动服务。' }
        & $python 'scripts/investigation_allocation_demo.py' upgrade-runs
        if ($LASTEXITCODE -ne 0) { throw '隔离调查记录表检查失败；未启动服务。' }
        if (Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue) {
            throw "受控 API 端口 $apiPort 已占用；未启动第二个服务。"
        }
        if (Get-NetTCPConnection -LocalPort $webPort -State Listen -ErrorAction SilentlyContinue) {
            throw "受控页面端口 $webPort 已占用；未启动第二个服务。"
        }
        $api = Start-Process -FilePath $python `
            -ArgumentList 'scripts/investigation_refresh_controlled.py','--port',([string]$apiPort),'--wait-seconds',([string]$waitSeconds) `
            -WorkingDirectory $root `
            -RedirectStandardOutput (Join-Path $root ('scripts/investigation_refresh_controlled_api' + $suffix + '.stdout.log')) `
            -RedirectStandardError (Join-Path $root ('scripts/investigation_refresh_controlled_api' + $suffix + '.stderr.log')) `
            -WindowStyle Hidden -PassThru
        $status = @{ api_pid = $api.Id; web_pid = $null; api_port = $apiPort; web_port = $webPort;
                     mode = 'controlled_provider_isolated_pg' }
        $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
        $env:BACKEND_INTERNAL_URL = 'http://127.0.0.1:' + $apiPort
        $env:NEXT_PUBLIC_API_URL = ''
        $env:NEXT_DIST_DIR = '.next-controlled-refresh' + $suffix
        $env:NEXT_PUBLIC_INVESTIGATION_CONTROLLED_REFRESH = '1'
        $node = (Get-Command node -ErrorAction Stop).Source
        $web = Start-Process -FilePath $node `
            -ArgumentList 'node_modules/next/dist/bin/next','dev','-p',([string]$webPort),'-H','127.0.0.1' `
            -WorkingDirectory (Join-Path $root 'frontend') `
            -RedirectStandardOutput (Join-Path $root ('scripts/investigation_refresh_controlled_web' + $suffix + '.stdout.log')) `
            -RedirectStandardError (Join-Path $root ('scripts/investigation_refresh_controlled_web' + $suffix + '.stderr.log')) `
            -WindowStyle Hidden -PassThru
        $status.web_pid = $web.Id
        $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
        $ready = $false
        for ($attempt = 0; $attempt -lt 4; $attempt++) {
            Start-Sleep -Seconds 5
            try {
                $apiCheck = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $apiPort + '/__controlled_refresh_status') -TimeoutSec 5
                $webCheck = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:' + $webPort + '/login') -TimeoutSec 10
                $ready = $apiCheck.mode -eq 'controlled_provider_isolated_pg' -and $webCheck.StatusCode -eq 200
                if ($ready) { break }
            } catch { }
        }
        if (-not $ready) { throw '受控 API 或页面未就绪；保留日志和进程状态。' }
        $allocationState = Get-Content -LiteralPath 'scripts/investigation_allocation_demo_state.json' `
            -Raw -Encoding UTF8 | ConvertFrom-Json
        $demoState = Get-Content -LiteralPath 'scripts/action_request_demo_state.json' -Raw -Encoding UTF8 | ConvertFrom-Json
        $auth = Invoke-RestMethod -Method Post -Uri ('http://127.0.0.1:' + $webPort + '/api/v1/auth/login') `
            -ContentType 'application/x-www-form-urlencoded' `
            -Body @{ username = $demoState.emails.member; password = $demoState.password } -TimeoutSec 15
        if (-not $auth.access_token) { throw '受控页面成员登录未返回令牌。' }
        $headers = @{ Authorization = 'Bearer ' + $auth.access_token }
        $orgs = @(Invoke-RestMethod -Uri ('http://127.0.0.1:' + $webPort + '/api/v1/organizations') -Headers $headers -TimeoutSec 15)
        if (-not @($orgs | Where-Object { $_.id -eq $allocationState.organization_id }).Count) {
            throw '受控页面用户无隔离企业权限。'
        }
        $auth = $null
        $headers = $null
        $demoState = $null
        Write-Output ('READY CONTROLLED_PROVIDER_ISOLATED_PG page=http://127.0.0.1:' + $webPort + '/investigations' +
                      ' case=' + $apiCheck.case_id + ' organization=' + $allocationState.organization_id +
                      ' status=http://127.0.0.1:' + $apiPort + '/__controlled_refresh_status' +
                      ' wait_seconds=' + $waitSeconds)
        return
    }

    if (-not (Test-Path -LiteralPath 'scripts/action_request_demo_state.json')) {
        & $python 'scripts/action_request_demo.py' prepare
        if ($LASTEXITCODE -ne 0) { throw '隔离身份准备失败；保留现场，不重复创建。' }
    } else {
        & $python 'scripts/action_request_demo.py' inspect
        if ($LASTEXITCODE -ne 0) { throw '既有隔离身份检查失败；未启动服务。' }
    }

    & $python 'scripts/investigation_allocation_demo.py' preflight
    if ($LASTEXITCODE -ne 0) { throw '依赖预检失败；未运行模型。' }
    $statePath = 'scripts/investigation_allocation_demo_state.json'
    if (-not (Test-Path -LiteralPath $statePath)) {
        & $python 'scripts/investigation_allocation_demo.py' prepare
        if ($LASTEXITCODE -ne 0) { throw '隔离数据准备失败；保留状态供定向核查。' }
    } elseif (-not (Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json).prepared) {
        throw '发现未完成的本轮隔离数据；停止，避免重复准备。'
    }
    & $python 'scripts/investigation_allocation_demo.py' inspect
    if ($LASTEXITCODE -ne 0) { throw '隔离调查数据检查失败，未启动服务。' }
    & $python 'scripts/investigation_allocation_demo.py' upgrade-runs
    if ($LASTEXITCODE -ne 0) { throw '隔离调查记录表升级失败，未启动服务。' }

    if ((Get-NetTCPConnection -LocalPort 8125 -State Listen -ErrorAction SilentlyContinue)) {
        throw '8125 已被占用；未启动第二个 API。'
    }
    if ((Get-NetTCPConnection -LocalPort 3110 -State Listen -ErrorAction SilentlyContinue)) {
        throw '3110 已被占用；未启动第二个页面服务。'
    }
    $api = Start-Process -FilePath $python -ArgumentList 'scripts/investigation_allocation_demo.py','serve' `
        -WorkingDirectory $root -RedirectStandardOutput 'scripts/investigation_allocation_api.stdout.log' `
        -RedirectStandardError 'scripts/investigation_allocation_api.stderr.log' -WindowStyle Hidden -PassThru
    $status = @{ api_pid = $api.Id; web_pid = $null; api_port = 8125; web_port = 3110 }
    $status | ConvertTo-Json | Set-Content -LiteralPath 'scripts/investigation_allocation_processes.json' -Encoding UTF8

    $env:BACKEND_INTERNAL_URL = 'http://127.0.0.1:8125'
    $env:NEXT_PUBLIC_API_URL = ''
    $env:NEXT_DIST_DIR = '.next-allocation'
    $node = (Get-Command node -ErrorAction Stop).Source
    $web = Start-Process -FilePath $node -ArgumentList 'node_modules/next/dist/bin/next','dev','-p','3110','-H','127.0.0.1' `
        -WorkingDirectory (Join-Path $root 'frontend') `
        -RedirectStandardOutput (Join-Path $root 'scripts/investigation_allocation_web.stdout.log') `
        -RedirectStandardError (Join-Path $root 'scripts/investigation_allocation_web.stderr.log') `
        -WindowStyle Hidden -PassThru
    $status.web_pid = $web.Id
    $status | ConvertTo-Json | Set-Content -LiteralPath 'scripts/investigation_allocation_processes.json' -Encoding UTF8
    $servicesReady = $false
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        Start-Sleep -Seconds 10
        try {
            $apiCheck = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8125/openapi.json' -TimeoutSec 8
            $webCheck = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3110/login' -TimeoutSec 15
            $servicesReady = $apiCheck.StatusCode -eq 200 -and $webCheck.StatusCode -eq 200
            if ($servicesReady) { break }
        } catch { } # Both new processes may still be starting; never submit an investigation.
    }
    if (-not $servicesReady) {
        throw '隔离 API 或页面未就绪；查看本轮日志。'
    }
    $demoState = Get-Content -LiteralPath 'scripts/action_request_demo_state.json' -Raw -Encoding UTF8 | ConvertFrom-Json
    $allocationState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $auth = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3110/api/v1/auth/login' `
        -ContentType 'application/x-www-form-urlencoded' `
        -Body @{ username = $demoState.emails.member; password = $demoState.password } -TimeoutSec 15
    if (-not $auth.access_token) { throw '演示成员登录未返回访问令牌。' }
    $headers = @{ Authorization = 'Bearer ' + $auth.access_token }
    $orgs = @(Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:3110/api/v1/organizations' `
        -Headers $headers -TimeoutSec 15)
    $workspaces = @(Invoke-RestMethod -Method Get `
        -Uri ('http://127.0.0.1:3110/api/v1/organizations/' + $allocationState.organization_id + '/workspaces') `
        -Headers $headers -TimeoutSec 15)
    if (-not @($orgs | Where-Object { $_.id -eq $allocationState.organization_id }).Count -or
        -not @($workspaces | Where-Object { $_.id -eq $allocationState.workspace_id }).Count) {
        throw 'JWT 登录成功，但隔离企业或 SOP 工作区不可见。'
    }
    $auth = $null
    $headers = $null
    $demoState = $null
    Write-Output ('READY http://127.0.0.1:3110/investigations API=8125 case=' +
                  $allocationState.case_id + ' workspace=' + $allocationState.workspace_id +
                  ' as_of=' + $allocationState.as_of + ' jwt_scope=ok')
}
finally {
    [Environment]::SetEnvironmentVariable('POSTGRES_USER', $previousUser, 'Process')
    [Environment]::SetEnvironmentVariable('POSTGRES_PASSWORD', $previousPassword, 'Process')
    [Environment]::SetEnvironmentVariable('BACKEND_INTERNAL_URL', $previousBackend, 'Process')
    [Environment]::SetEnvironmentVariable('NEXT_PUBLIC_API_URL', $previousPublic, 'Process')
    [Environment]::SetEnvironmentVariable('NEXT_DIST_DIR', $previousDist, 'Process')
    [Environment]::SetEnvironmentVariable('NEXT_PUBLIC_INVESTIGATION_CONTROLLED_REFRESH', $previousControlled, 'Process')
    $pgPassword = $null
    $inspectJson = $null
    $pgInfo = $null
    $pgEnvironment = $null
    $auth = $null
    $headers = $null
    $demoState = $null
}
