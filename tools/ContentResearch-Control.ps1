param(
    [ValidateSet("menu", "start", "start-only", "stop", "restart", "status", "open", "logs", "diagnose", "gpu", "kb", "advanced")]
    [string]$Action = "menu"
)

$ErrorActionPreference = "Stop"
$ControlVersion = "2026.07.25.2"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

try {
    & "$env:SystemRoot\System32\chcp.com" 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    [Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
    $Host.UI.RawUI.WindowTitle = "Content Research 程序控制台"
}
catch {
    # Non-interactive hosts do not expose a console UI.
}

$Root = Split-Path -Parent $PSScriptRoot
$WebUiScript = Join-Path $Root "web_ui.py"
$MainScript = Join-Path $Root "main.py"
$HostName = "127.0.0.1"
$PreferredPort = 7860
$MaxPort = 7869
$LogsDir = Join-Path $Root "logs"
$PidFile = Join-Path $LogsDir "web_ui.pid"
$UrlFile = Join-Path $LogsDir "web_ui.url"
$StdoutLog = Join-Path $LogsDir "web_ui.out.log"
$StderrLog = Join-Path $LogsDir "web_ui.err.log"
$WhisperGpuInstaller = Join-Path $PSScriptRoot "Install-WhisperGpuRuntime.ps1"
$WhisperGpuStatusFile = Join-Path $LogsDir "whisper_gpu_install.status.json"
$WhisperGpuPidFile = Join-Path $LogsDir "whisper_gpu_install.pid"
$WhisperGpuStdoutLog = Join-Path $LogsDir "whisper_gpu_installer.out.log"
$WhisperGpuStderrLog = Join-Path $LogsDir "whisper_gpu_installer.err.log"

function Write-Title {
    param([string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("=" * [Math]::Max(12, $Text.Length)) -ForegroundColor DarkGray
}

function Write-Result {
    param(
        [string]$Label,
        [string]$Value,
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )
    Write-Host (("{0,-14}" -f ($Label + "："))) -NoNewline -ForegroundColor DarkGray
    Write-Host $Value -ForegroundColor $Color
}

function Normalize-ProcessPathEnvironment {
    $pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
    if (-not $pathValue) {
        $pathValue = [Environment]::GetEnvironmentVariable("PATH", "Process")
    }
    if ($pathValue) {
        [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
        [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
    }
}

function Get-PythonPath {
    $commandPython = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
    $candidates = @(
        $env:CONTENT_RESEARCH_PYTHON,
        "D:\develop\python\python.exe",
        $commandPython
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "没有找到 Python。可将 CONTENT_RESEARCH_PYTHON 设置为 python.exe 的完整路径。"
}

function Get-SavedUrl {
    if (Test-Path -LiteralPath $UrlFile) {
        $saved = (Get-Content -LiteralPath $UrlFile -Raw -Encoding UTF8).Trim()
        $uri = $null
        if ($saved -and [Uri]::TryCreate($saved, [UriKind]::Absolute, [ref]$uri)) {
            return $saved
        }
    }
    return ("http://{0}:{1}" -f $HostName, $PreferredPort)
}

function Get-WebHealth {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 2
    )
    try {
        $healthUrl = $Url.TrimEnd("/") + "/api/health"
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec $TimeoutSeconds
        if ([bool]$health.ok) {
            return $health
        }
    }
    catch {
        return $null
    }
    return $null
}

function Test-WebUi {
    param([string]$Url)
    return $null -ne (Get-WebHealth -Url $Url)
}

function Get-WebUiProcesses {
    $items = @()
    if (Test-Path -LiteralPath $PidFile) {
        $savedPid = (Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8).Trim()
        if ($savedPid -match "^\d+$") {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
            if ($process -and $process.CommandLine -like "*web_ui.py*") {
                $items += $process
            }
        }
    }

    $pythonProcesses = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("python.exe", "pythonw.exe") }
    )
    foreach ($process in $pythonProcesses) {
        $commandLine = [string]$process.CommandLine
        $belongsToProject = $commandLine.IndexOf($WebUiScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
        if ($belongsToProject -and -not ($items | Where-Object { $_.ProcessId -eq $process.ProcessId })) {
            $items += $process
        }
    }
    return @($items)
}

function Test-PortAvailable {
    param([int]$Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Get-AvailablePort {
    for ($port = $PreferredPort; $port -le $MaxPort; $port++) {
        if (Test-PortAvailable -Port $port) {
            return $port
        }
    }
    throw "端口 $PreferredPort 到 $MaxPort 均被占用，请关闭占用程序后重试。"
}

function Open-WebUi {
    $url = Get-SavedUrl
    if (-not (Test-WebUi -Url $url)) {
        Write-Host "服务尚未运行，正在启动。" -ForegroundColor Yellow
        Start-WebUi -OpenBrowser $true
        return
    }
    Start-Process $url
    Write-Result "已打开" $url Green
}

function Start-WebUi {
    param([bool]$OpenBrowser = $true)

    if (-not (Test-Path -LiteralPath $WebUiScript -PathType Leaf)) {
        throw "找不到 Web UI 启动文件：$WebUiScript"
    }
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

    $savedUrl = Get-SavedUrl
    $existingHealth = Get-WebHealth -Url $savedUrl
    if ($existingHealth) {
        Write-Result "服务状态" "已运行" Green
        Write-Result "访问地址" $savedUrl Cyan
        if ($OpenBrowser) {
            Start-Process $savedUrl
        }
        return
    }

    $staleProcesses = @(Get-WebUiProcesses)
    foreach ($process in $staleProcesses) {
        Write-Host "正在清理无响应的旧进程 PID $($process.ProcessId)..." -ForegroundColor Yellow
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($staleProcesses.Count -gt 0) {
        Start-Sleep -Milliseconds 500
    }

    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StdoutLog -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StderrLog -Force -ErrorAction SilentlyContinue

    $python = Get-PythonPath
    $port = Get-AvailablePort
    $url = "http://${HostName}:$port"
    Normalize-ProcessPathEnvironment
    $env:CONTENT_RESEARCH_URL_FILE = $UrlFile

    $arguments = ('"{0}" --host {1} --port {2}' -f $WebUiScript, $HostName, $port)
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding UTF8
    Set-Content -LiteralPath $UrlFile -Value $url -Encoding UTF8
    Write-Host "正在启动 Content Research，PID $($process.Id)" -ForegroundColor Cyan
    Write-Host "等待健康检查" -NoNewline -ForegroundColor DarkGray

    $health = $null
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) {
            break
        }
        $health = Get-WebHealth -Url $url -TimeoutSeconds 2
        if ($health) {
            break
        }
        if ($i % 4 -eq 0) {
            Write-Host "." -NoNewline -ForegroundColor DarkGray
        }
    }
    Write-Host ""

    if (-not $health) {
        Write-Host "服务启动失败。" -ForegroundColor Red
        Show-RecentLogs -Lines 30
        throw "未通过健康检查。错误日志：$StderrLog"
    }

    Write-Result "服务状态" "运行中" Green
    Write-Result "访问地址" $url Cyan
    Write-Result "程序版本" ([string]$health.version) Gray
    if ($health.llm) {
        $llmStatus = if ([bool]$health.llm.configured) { "已配置 / $($health.llm.model)" } else { "未配置" }
        Write-Result "AI 分析" $llmStatus $(if ([bool]$health.llm.configured) { "Green" } else { "Yellow" })
    }
    if ($health.whisper) {
        $whisperStatus = "$($health.whisper.device) / $($health.whisper.compute_type) / batch $($health.whisper.batch_size)"
        Write-Result "Whisper" $whisperStatus $(if ($health.whisper.device -eq "cuda") { "Green" } else { "Yellow" })
        if ($health.whisper.reason) {
            Write-Result "识别策略" ([string]$health.whisper.reason) DarkGray
        }
    }
    if ($OpenBrowser) {
        Start-Process $url
    }
}

function Stop-WebUi {
    $processes = @(Get-WebUiProcesses)
    if ($processes.Count -eq 0) {
        Write-Host "未发现 Content Research 服务进程。" -ForegroundColor Yellow
    }
    else {
        foreach ($process in $processes) {
            Write-Host "正在停止 PID $($process.ProcessId)..." -ForegroundColor Yellow
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 500
        Write-Host "服务已停止。" -ForegroundColor Green
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue
}

function Show-KnowledgeSummary {
    $lexicalPath = Join-Path $Root "cache\knowledge_base\index.json"
    $vectorManifestPath = Join-Path $Root "cache\knowledge_base\chroma\manifest.json"
    $creatorManifestPath = Join-Path $Root "output\creator_knowledge_base\manifest.json"
    $gapPath = Join-Path $Root "output\gap_analysis\latest.json"

    $lexicalState = if (Test-Path -LiteralPath $lexicalPath) {
        "已建立 / $((Get-Item -LiteralPath $lexicalPath).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    } else { "未建立" }
    Write-Result "词法知识库" $lexicalState $(if (Test-Path -LiteralPath $lexicalPath) { "Green" } else { "Yellow" })

    if (Test-Path -LiteralPath $vectorManifestPath) {
        try {
            $manifest = Get-Content -LiteralPath $vectorManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Result "向量知识库" "已建立 / $($manifest.document_count) 个分块" Green
        }
        catch {
            Write-Result "向量知识库" "清单读取失败" Yellow
        }
    }
    else {
        Write-Result "向量知识库" "未建立" Yellow
    }

    $creatorState = if (Test-Path -LiteralPath $creatorManifestPath) { "已建立" } else { "未建立" }
    Write-Result "创作者知识库" $creatorState $(if (Test-Path -LiteralPath $creatorManifestPath) { "Green" } else { "Yellow" })

    if (Test-Path -LiteralPath $gapPath) {
        try {
            $gap = Get-Content -LiteralPath $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Result "能力健康度" "$($gap.knowledge_health.overall_score) / 缺失 $($gap.knowledge_health.missing_count) 项" Gray
        }
        catch {
            Write-Result "能力健康度" "数据读取失败" Yellow
        }
    }
}

function Show-Status {
    Write-Title "服务状态"
    $url = Get-SavedUrl
    $health = Get-WebHealth -Url $url
    $processes = @(Get-WebUiProcesses)

    if ($health) {
        Write-Result "运行状态" "正常" Green
        Write-Result "访问地址" $url Cyan
        Write-Result "程序版本" ([string]$health.version) Gray
        if ($processes.Count -gt 0) {
            Write-Result "进程 PID" (($processes | ForEach-Object { $_.ProcessId }) -join ", ") Gray
        }
        if ($health.llm) {
            $llmStatus = if ([bool]$health.llm.configured) { "已配置 / $($health.llm.model)" } else { "未配置" }
            Write-Result "AI 分析" $llmStatus $(if ([bool]$health.llm.configured) { "Green" } else { "Yellow" })
        }
        if ($health.whisper) {
            $whisperStatus = "$($health.whisper.device) / $($health.whisper.compute_type) / batch $($health.whisper.batch_size)"
            Write-Result "Whisper" $whisperStatus $(if ($health.whisper.device -eq "cuda") { "Green" } else { "Yellow" })
            if ($health.whisper.reason) {
                Write-Result "识别策略" ([string]$health.whisper.reason) DarkGray
            }
        }
        if ($health.features) {
            $featureCount = @($health.features.PSObject.Properties | Where-Object { [bool]$_.Value }).Count
            Write-Result "可用模块" "$featureCount 项" Gray
        }
    }
    else {
        Write-Result "运行状态" "未启动" Yellow
        if ($processes.Count -gt 0) {
            Write-Result "异常进程" (($processes | ForEach-Object { $_.ProcessId }) -join ", ") Red
        }
    }

    Write-Title "知识库状态"
    Show-KnowledgeSummary

    if (Test-Path -LiteralPath $WhisperGpuStatusFile) {
        Write-Title "后台任务"
        try {
            $gpuInstall = Get-Content -LiteralPath $WhisperGpuStatusFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $color = switch ([string]$gpuInstall.state) {
                "complete" { "Green" }
                "failed" { "Red" }
                default { "Cyan" }
            }
            Write-Result "Whisper GPU" "$($gpuInstall.percent)% / $($gpuInstall.message)" $color
        }
        catch {
            Write-Result "Whisper GPU" "状态文件读取失败" Yellow
        }
    }
}

function Show-RecentLogs {
    param([int]$Lines = 45)
    Write-Title "最近运行日志"
    if (Test-Path -LiteralPath $StderrLog) {
        $content = @(Get-Content -LiteralPath $StderrLog -Encoding UTF8 -Tail $Lines)
        if ($content.Count -gt 0) {
            $content | ForEach-Object { Write-Host $_ }
        }
        else {
            Write-Host "错误日志为空。" -ForegroundColor Green
        }
    }
    else {
        Write-Host "尚未生成运行日志。" -ForegroundColor Yellow
    }
    Write-Result "日志文件" $StderrLog DarkGray
}

function Show-Diagnostics {
    Write-Title "运行诊断"
    Write-Result "项目目录" $Root $(if (Test-Path -LiteralPath $Root) { "Green" } else { "Red" })
    Write-Result "Web UI" $WebUiScript $(if (Test-Path -LiteralPath $WebUiScript) { "Green" } else { "Red" })
    $python = Get-PythonPath
    Write-Result "Python" $python Green

    $url = Get-SavedUrl
    $health = Get-WebHealth -Url $url
    Write-Result "HTTP 健康检查" $(if ($health) { "通过" } else { "服务未运行" }) $(if ($health) { "Green" } else { "Yellow" })

    Write-Host ""
    Write-Host "正在检查核心 Python 模块..." -ForegroundColor Cyan
    $moduleCheck = "import cv2, chromadb, faster_whisper, langgraph, scenedetect, sentence_transformers, spacy, yt_dlp; print('核心模块导入正常')"
    & $python -c $moduleCheck
    if ($LASTEXITCODE -ne 0) {
        Write-Host "核心模块检查失败。" -ForegroundColor Red
    }

    Write-Host "正在检查依赖一致性..." -ForegroundColor Cyan
    & $python -m pip check
    if ($LASTEXITCODE -eq 0) {
        Write-Host "诊断完成，未发现依赖冲突。" -ForegroundColor Green
    }
}

function Start-WhisperGpuInstall {
    if (-not (Test-Path -LiteralPath $WhisperGpuInstaller -PathType Leaf)) {
        throw "找不到 Whisper GPU 安装器：$WhisperGpuInstaller"
    }
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

    if (Test-Path -LiteralPath $WhisperGpuPidFile) {
        $savedPid = (Get-Content -LiteralPath $WhisperGpuPidFile -Raw -Encoding UTF8).Trim()
        if ($savedPid -match "^\d+$" -and (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)) {
            Write-Result "GPU 安装" "正在后台运行 / PID $savedPid" Green
            if (Test-Path -LiteralPath $WhisperGpuStatusFile) {
                $status = Get-Content -LiteralPath $WhisperGpuStatusFile -Raw -Encoding UTF8 | ConvertFrom-Json
                Write-Result "下载进度" "$($status.percent)% / $($status.message)" Cyan
            }
            return
        }
        Remove-Item -LiteralPath $WhisperGpuPidFile -Force -ErrorAction SilentlyContinue
    }

    Remove-Item -LiteralPath $WhisperGpuStdoutLog -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $WhisperGpuStderrLog -Force -ErrorAction SilentlyContinue
    $arguments = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Wait' -f $WhisperGpuInstaller)
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $arguments `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $WhisperGpuStdoutLog `
        -RedirectStandardError $WhisperGpuStderrLog `
        -PassThru
    Write-Result "GPU 安装" "已在后台启动 / PID $($process.Id)" Green
    Write-Result "说明" "支持断点续传；完成后会自动校验、安装、清理安装包并重启服务。" DarkGray
}

function Open-Folder {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
    Start-Process explorer.exe -ArgumentList ('"{0}"' -f $Path)
}

function Invoke-KnowledgeBuild {
    param([bool]$Advanced)
    $python = Get-PythonPath
    if (-not (Test-Path -LiteralPath $MainScript)) {
        throw "找不到主程序：$MainScript"
    }

    if ($Advanced) {
        Write-Title "完整知识系统更新"
        Write-Host "将更新词法索引、向量索引、创作者库、模板库、能力缺口和项目报告。" -ForegroundColor Yellow
        $confirm = Read-Host "输入 Y 继续"
        if ($confirm.ToUpperInvariant() -ne "Y") {
            Write-Host "已取消。" -ForegroundColor Yellow
            return
        }
        & $python $MainScript --advanced-kb
    }
    else {
        Write-Title "基础知识库重建"
        & $python $MainScript --build-kb
    }

    if ($LASTEXITCODE -ne 0) {
        throw "知识库更新失败，退出码：$LASTEXITCODE"
    }
    Write-Host "知识库更新完成。" -ForegroundColor Green
}

function Invoke-Safely {
    param([scriptblock]$Operation)
    try {
        & $Operation
    }
    catch {
        Write-Host ""
        Write-Host "操作失败：$($_.Exception.Message)" -ForegroundColor Red
        Write-Host "错误日志：$StderrLog" -ForegroundColor DarkGray
    }
}

function Wait-ForMenu {
    Write-Host ""
    Read-Host "按 Enter 返回主菜单" | Out-Null
}

function Show-CompactHeader {
    $url = Get-SavedUrl
    $health = Get-WebHealth -Url $url -TimeoutSeconds 1
    if ($health) {
        Write-Host "● 服务运行中" -ForegroundColor Green
        Write-Host "  $url  |  $($health.version)" -ForegroundColor DarkGray
        if ($health.llm -and [bool]$health.llm.configured) {
            Write-Host "  AI: $($health.llm.model)" -ForegroundColor DarkGray
        }
        if (Test-Path -LiteralPath $WhisperGpuStatusFile) {
            try {
                $gpuInstall = Get-Content -LiteralPath $WhisperGpuStatusFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ([string]$gpuInstall.state -in @("downloading", "installing")) {
                    Write-Host "  Whisper GPU 运行库: $($gpuInstall.percent)%" -ForegroundColor DarkGray
                }
            }
            catch {
                # The full status page reports malformed status files.
            }
        }
    }
    else {
        Write-Host "● 服务未启动" -ForegroundColor Yellow
        Write-Host "  选择 1 可启动并打开工作台" -ForegroundColor DarkGray
    }
}

function Show-Menu {
    while ($true) {
        Clear-Host
        Write-Host "Content Research 程序控制台" -ForegroundColor Cyan
        Write-Host "版本 $ControlVersion" -ForegroundColor DarkGray
        Write-Host "================================" -ForegroundColor DarkGray
        Show-CompactHeader
        Write-Host ""
        Write-Host "  1. 启动并打开工作台" -ForegroundColor White
        Write-Host "  2. 仅启动服务" -ForegroundColor White
        Write-Host "  3. 重启并打开工作台" -ForegroundColor White
        Write-Host "  4. 停止服务" -ForegroundColor White
        Write-Host "  5. 打开工作台" -ForegroundColor White
        Write-Host ""
        Write-Host "  6. 查看完整状态" -ForegroundColor White
        Write-Host "  7. 运行环境诊断" -ForegroundColor White
        Write-Host "  8. 查看最近日志" -ForegroundColor White
        Write-Host "  9. 打开日志目录" -ForegroundColor White
        Write-Host ""
        Write-Host "  G. 安装/继续 Whisper GPU 运行库" -ForegroundColor White
        Write-Host "  A. 重建基础知识库" -ForegroundColor White
        Write-Host "  B. 更新完整知识系统" -ForegroundColor White
        Write-Host "  F. 打开项目目录" -ForegroundColor White
        Write-Host "  Q. 退出控制台" -ForegroundColor White
        Write-Host ""

        $choice = (Read-Host "请选择").Trim().ToUpperInvariant()
        switch ($choice) {
            "1" { Invoke-Safely { Start-WebUi -OpenBrowser $true }; Wait-ForMenu }
            "2" { Invoke-Safely { Start-WebUi -OpenBrowser $false }; Wait-ForMenu }
            "3" { Invoke-Safely { Stop-WebUi; Start-WebUi -OpenBrowser $true }; Wait-ForMenu }
            "4" { Invoke-Safely { Stop-WebUi }; Wait-ForMenu }
            "5" { Invoke-Safely { Open-WebUi }; Wait-ForMenu }
            "6" { Invoke-Safely { Show-Status }; Wait-ForMenu }
            "7" { Invoke-Safely { Show-Diagnostics }; Wait-ForMenu }
            "8" { Invoke-Safely { Show-RecentLogs }; Wait-ForMenu }
            "9" { Invoke-Safely { Open-Folder -Path $LogsDir }; Wait-ForMenu }
            "G" { Invoke-Safely { Start-WhisperGpuInstall }; Wait-ForMenu }
            "A" { Invoke-Safely { Invoke-KnowledgeBuild -Advanced $false }; Wait-ForMenu }
            "B" { Invoke-Safely { Invoke-KnowledgeBuild -Advanced $true }; Wait-ForMenu }
            "F" { Invoke-Safely { Open-Folder -Path $Root }; Wait-ForMenu }
            "Q" { return }
            default {
                Write-Host "无效选项，请重新选择。" -ForegroundColor Yellow
                Start-Sleep -Milliseconds 700
            }
        }
    }
}

switch ($Action) {
    "start" { Invoke-Safely { Start-WebUi -OpenBrowser $true } }
    "start-only" { Invoke-Safely { Start-WebUi -OpenBrowser $false } }
    "stop" { Invoke-Safely { Stop-WebUi } }
    "restart" { Invoke-Safely { Stop-WebUi; Start-WebUi -OpenBrowser $true } }
    "status" { Invoke-Safely { Show-Status } }
    "open" { Invoke-Safely { Open-WebUi } }
    "logs" { Invoke-Safely { Show-RecentLogs } }
    "diagnose" { Invoke-Safely { Show-Diagnostics } }
    "gpu" { Invoke-Safely { Start-WhisperGpuInstall } }
    "kb" { Invoke-Safely { Invoke-KnowledgeBuild -Advanced $false } }
    "advanced" { Invoke-Safely { Invoke-KnowledgeBuild -Advanced $true } }
    default { Show-Menu }
}
