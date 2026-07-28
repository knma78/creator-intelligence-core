param(
    [switch]$Wait
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DownloadDir = Join-Path $Root ".downloads"
$LogsDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogsDir "whisper_gpu_install.log"
$StatusFile = Join-Path $LogsDir "whisper_gpu_install.status.json"
$PidFile = Join-Path $LogsDir "whisper_gpu_install.pid"
$ControlScript = Join-Path $PSScriptRoot "ContentResearch-Control.ps1"

$Packages = @(
    @{
        Name = "cuBLAS"
        DisplayName = "Codex-cuBLAS-12.8.5.5"
        Url = "https://files.pythonhosted.org/packages/74/65/d9db5b0754559f6ed279c4a6cf1192dbf581f7d01e5d3d2882f577936049/nvidia_cublas_cu12-12.8.5.5-py3-none-win_amd64.whl"
        FileName = "nvidia_cublas_cu12-12.8.5.5-py3-none-win_amd64.whl"
        Size = 567543364
        Sha256 = "1e272895b82946b4db6f592d9080291fb60f78c9fe253a5c71ba5ebb74864c3e"
    },
    @{
        Name = "cuDNN"
        DisplayName = "Codex-cuDNN-9.17.1.4"
        Url = "https://files.pythonhosted.org/packages/56/67/e4b10d08c0658bb7e42766fe5cd5c450d0524425e70d12b5eb85a979318e/nvidia_cudnn_cu12-9.17.1.4-py3-none-win_amd64.whl"
        FileName = "nvidia_cudnn_cu12-9.17.1.4-py3-none-win_amd64.whl"
        Size = 634329630
        Sha256 = "0760c843fb109631edf5bd4234f2a260a13a05c18ee2a20783fbb4eb04d56645"
    },
    @{
        Name = "NVRTC"
        DisplayName = "Codex-NVRTC-12.8.93"
        Url = "https://files.pythonhosted.org/packages/45/51/52a3d84baa2136cc8df15500ad731d74d3a1114d4c123e043cb608d4a32b/nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-win_amd64.whl"
        FileName = "nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-win_amd64.whl"
        Size = 73586838
        Sha256 = "7a4b6b2904850fe78e0bd179c4b655c404d4bb799ef03ddc60804247099ae909"
    }
)

function Write-InstallLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Write-InstallStatus {
    param(
        [string]$State,
        [string]$Message,
        [int]$Percent = 0
    )
    @{
        state = $State
        message = $Message
        percent = $Percent
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
}

function Get-PythonPath {
    $commandPython = Get-Command python -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
    foreach ($candidate in @($env:CONTENT_RESEARCH_PYTHON, "D:\develop\python\python.exe", $commandPython)) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "没有找到项目 Python。"
}

function Get-PackagePath {
    param([hashtable]$Package)
    return Join-Path $DownloadDir $Package.FileName
}

function Get-DownloadJob {
    param([hashtable]$Package)
    return Get-BitsTransfer -AllUsers:$false -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq $Package.DisplayName } |
        Select-Object -First 1
}

function Ensure-DownloadJob {
    param([hashtable]$Package)
    $destination = Get-PackagePath $Package
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        return
    }

    $job = Get-DownloadJob $Package
    if (-not $job) {
        Write-InstallLog "开始下载 $($Package.Name)。"
        Start-BitsTransfer `
            -Source $Package.Url `
            -Destination $destination `
            -DisplayName $Package.DisplayName `
            -Description "ContentResearch Whisper GPU runtime" `
            -Priority Foreground `
            -Asynchronous | Out-Null
        return
    }

    if ($job.JobState -in @("Suspended", "TransientError")) {
        Resume-BitsTransfer -BitsJob $job -Asynchronous | Out-Null
    }
    elseif ($job.JobState -eq "Error") {
        Remove-BitsTransfer -BitsJob $job
        Start-BitsTransfer `
            -Source $Package.Url `
            -Destination $destination `
            -DisplayName $Package.DisplayName `
            -Description "ContentResearch Whisper GPU runtime" `
            -Priority Foreground `
            -Asynchronous | Out-Null
    }
    elseif ($job.JobState -eq "Transferred") {
        Complete-BitsTransfer -BitsJob $job
    }
}

function Complete-TransferredJobs {
    foreach ($package in $Packages) {
        $job = Get-DownloadJob $package
        if ($job -and $job.JobState -eq "Transferred") {
            Complete-BitsTransfer -BitsJob $job
            Write-InstallLog "$($package.Name) 下载完成。"
        }
    }
}

function Get-DownloadProgress {
    $total = [int64]0
    $transferred = [int64]0
    foreach ($package in $Packages) {
        $path = Get-PackagePath $package
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $length = (Get-Item -LiteralPath $path).Length
            $total += $length
            $transferred += $length
            continue
        }
        $job = Get-DownloadJob $package
        if ($job) {
            $total += [int64]$package.Size
            $transferred += [int64]$job.BytesTransferred
        }
    }
    $percent = if ($total -gt 0) { [int][Math]::Floor(($transferred * 100.0) / $total) } else { 0 }
    return @{
        Total = $total
        Transferred = $transferred
        Percent = $percent
    }
}

function Test-AllPackagesReady {
    foreach ($package in $Packages) {
        if (-not (Test-Path -LiteralPath (Get-PackagePath $package) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

function Invoke-GpuSmokeTest {
    param([string]$Python)
    $smokeAudio = Join-Path $DownloadDir "whisper-gpu-smoke.wav"
    $smokeOutput = Join-Path $DownloadDir "whisper-gpu-smoke-output"
    $previousFallback = $env:WHISPER_GPU_FALLBACK
    try {
        $ffmpeg = (& $Python -c "from config import SETTINGS; print(SETTINGS.ffmpeg_path)" | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ffmpeg -PathType Leaf)) {
            throw "无法找到 FFmpeg，不能执行 Whisper GPU 冒烟测试。"
        }
        & $ffmpeg `
            -hide_banner `
            -loglevel error `
            -f lavfi `
            -i "sine=frequency=440:duration=3" `
            -ar 16000 `
            -ac 1 `
            -y $smokeAudio
        if ($LASTEXITCODE -ne 0) {
            throw "GPU 冒烟测试音频生成失败。"
        }

        $env:WHISPER_GPU_FALLBACK = "false"
        Write-InstallStatus -State "installing" -Message "正在执行真实 Whisper GPU 转写测试。" -Percent 99
        Write-InstallLog "正在执行禁止 CPU 回退的 Whisper GPU 转写测试。"
        & $Python -m processor.whisper $smokeAudio --video-id gpu-smoke --output-dir $smokeOutput
        if ($LASTEXITCODE -ne 0) {
            throw "Whisper GPU 转写测试失败。"
        }
        Write-InstallLog "Whisper GPU 转写测试通过。"
    }
    finally {
        $env:WHISPER_GPU_FALLBACK = $previousFallback
        Remove-Item -LiteralPath $smokeAudio -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $smokeOutput -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Install-Packages {
    $paths = @()
    foreach ($package in $Packages) {
        $path = Get-PackagePath $package
        $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $package.Sha256) {
            throw "$($package.Name) 安装包校验失败。"
        }
        Write-InstallLog "$($package.Name) SHA-256 校验通过。"
        $paths += $path
    }

    $python = Get-PythonPath
    Write-InstallStatus -State "installing" -Message "正在安装 CUDA 运行库。" -Percent 99
    Write-InstallLog "正在安装 CUDA 12/cuDNN 9 Python 运行库。"
    & $python -m pip install --no-index --no-deps @paths
    if ($LASTEXITCODE -ne 0) {
        throw "pip 安装失败，退出码 $LASTEXITCODE。"
    }
    $pipCheck = @(& $python -m pip check 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "CUDA 运行库安装后出现 Python 依赖冲突：$(($pipCheck -join ' ').Trim())"
    }

    $statusJson = & $python -m processor.whisper --status
    if ($LASTEXITCODE -ne 0) {
        throw "Whisper 运行状态检查失败。"
    }
    $runtime = ($statusJson -join [Environment]::NewLine) | ConvertFrom-Json
    if (-not [bool]$runtime.cuda_ready) {
        throw "CUDA 运行库安装完成，但 Whisper 未通过 CUDA 组件检查：$($runtime.reason)"
    }

    while ([string]$runtime.device -ne "cuda") {
        Write-InstallStatus -State "waiting_gpu" -Message "运行库已安装，正在等待 GPU 资源低于保护线。" -Percent 99
        Write-InstallLog "CUDA 组件检查通过，但 GPU 当前繁忙；60 秒后重新检查。"
        Start-Sleep -Seconds 60
        $statusJson = & $python -m processor.whisper --status
        if ($LASTEXITCODE -ne 0) {
            throw "等待 GPU 时运行状态检查失败。"
        }
        $runtime = ($statusJson -join [Environment]::NewLine) | ConvertFrom-Json
        if (-not [bool]$runtime.cuda_ready) {
            throw "等待 GPU 时 CUDA 组件检查失败：$($runtime.reason)"
        }
    }
    Invoke-GpuSmokeTest -Python $python

    foreach ($package in $Packages) {
        Remove-Item -LiteralPath (Get-PackagePath $package) -Force
    }
    if ((Test-Path -LiteralPath $DownloadDir) -and -not (Get-ChildItem -LiteralPath $DownloadDir -Force)) {
        Remove-Item -LiteralPath $DownloadDir -Force
    }

    if (Test-Path -LiteralPath $ControlScript -PathType Leaf) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ControlScript -Action stop
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ControlScript -Action start-only
    }
    Write-InstallStatus -State "complete" -Message "Whisper GPU 运行库已安装并通过检查。" -Percent 100
    Write-InstallLog "Whisper GPU 运行库已安装并通过检查，服务已重启。"
}

New-Item -ItemType Directory -Force -Path $DownloadDir, $LogsDir | Out-Null
Set-Content -LiteralPath $PidFile -Value $PID -Encoding ASCII

try {
    foreach ($package in $Packages) {
        Ensure-DownloadJob $package
    }
    Complete-TransferredJobs

    if (-not $Wait -and -not (Test-AllPackagesReady)) {
        $progress = Get-DownloadProgress
        Write-InstallStatus -State "downloading" -Message "CUDA 运行库正在后台下载。" -Percent $progress.Percent
        Write-InstallLog ("当前下载进度 {0}% ({1:N1}/{2:N1} MB)。" -f $progress.Percent, ($progress.Transferred / 1MB), ($progress.Total / 1MB))
        exit 0
    }

    while (-not (Test-AllPackagesReady)) {
        Complete-TransferredJobs
        $progress = Get-DownloadProgress
        Write-InstallStatus -State "downloading" -Message "CUDA 运行库正在后台下载。" -Percent $progress.Percent
        Write-InstallLog ("当前下载进度 {0}% ({1:N1}/{2:N1} MB)。" -f $progress.Percent, ($progress.Transferred / 1MB), ($progress.Total / 1MB))
        Start-Sleep -Seconds 60
        foreach ($package in $Packages) {
            Ensure-DownloadJob $package
        }
    }

    Install-Packages
}
catch {
    $failedPercent = 0
    if (Test-Path -LiteralPath $StatusFile) {
        try {
            $previousStatus = Get-Content -LiteralPath $StatusFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $failedPercent = [int]$previousStatus.percent
        }
        catch {
            $failedPercent = 0
        }
    }
    Write-InstallStatus -State "failed" -Message $_.Exception.Message -Percent $failedPercent
    Write-InstallLog "安装失败：$($_.Exception.Message)"
    throw
}
finally {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}
