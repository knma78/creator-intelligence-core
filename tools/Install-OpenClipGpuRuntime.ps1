param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DownloadDir = Join-Path $Root ".downloads\openclip-gpu"
$LogsDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogsDir "openclip_gpu_install.log"
$StatusFile = Join-Path $LogsDir "openclip_gpu_install.status.json"
$PidFile = Join-Path $LogsDir "openclip_gpu_install.pid"
$SmokeScript = Join-Path $PSScriptRoot "smoke_openclip_gpu.py"
$ModelFile = Join-Path $Root "cache\models\openclip\open_clip_model.safetensors"

$Packages = @(
    @{
        Name = "torch"
        DisplayName = "ContentResearch-OpenCLIP-torch-2.11.0-cu128"
        Url = "https://download-r2.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp313-cp313-win_amd64.whl"
        FileName = "torch-2.11.0+cu128-cp313-cp313-win_amd64.whl"
        Size = [int64]2753196039
        Sha256 = "6f367e62fd81b75cdf23ca4b75ced834d2db2cf98d1588ac935bde345de9de23"
    },
    @{
        Name = "torchvision"
        DisplayName = "ContentResearch-OpenCLIP-torchvision-0.26.0-cu128"
        Url = "https://download-r2.pytorch.org/whl/cu128/torchvision-0.26.0%2Bcu128-cp313-cp313-win_amd64.whl"
        FileName = "torchvision-0.26.0+cu128-cp313-cp313-win_amd64.whl"
        Size = [int64]9649962
        Sha256 = "0232cb219927a52d6c98ff202f32d1cdf4802c2195a85fc1f1a0c1b0b4983a4d"
    },
    @{
        Name = "setuptools"
        DisplayName = "ContentResearch-OpenCLIP-setuptools-81.0.0"
        Url = "https://files.pythonhosted.org/packages/e1/e3/c164c88b2e5ce7b24d667b9bd83589cf4f3520d97cad01534cd3c4f55fdb/setuptools-81.0.0-py3-none-any.whl"
        FileName = "setuptools-81.0.0-py3-none-any.whl"
        Size = [int64]1062021
        Sha256 = "fdd925d5c5d9f62e4b74b30d6dd7828ce236fd6ed998a08d81de62ce5a6310d6"
    }
)

function Write-InstallLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Get-PythonPath {
    $commandPython = Get-Command python -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
    foreach ($candidate in @($env:CONTENT_RESEARCH_PYTHON, "D:\develop\python\python.exe", $commandPython)) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "Project Python was not found."
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
        Write-InstallLog "Starting resumable BITS download for $($Package.Name)."
        Start-BitsTransfer `
            -Source $Package.Url `
            -Destination $destination `
            -DisplayName $Package.DisplayName `
            -Description "ContentResearch OpenCLIP GPU runtime" `
            -Priority Foreground `
            -Asynchronous | Out-Null
        return
    }
    if ($job.JobState -in @("Suspended", "TransientError")) {
        Resume-BitsTransfer -BitsJob $job -Asynchronous | Out-Null
    }
    elseif ($job.JobState -eq "Transferred") {
        Complete-BitsTransfer -BitsJob $job
    }
    elseif ($job.JobState -eq "Error") {
        throw "BITS error for $($Package.Name): $($job.ErrorDescription)"
    }
}

function Complete-TransferredJobs {
    foreach ($package in $Packages) {
        $job = Get-DownloadJob $package
        if ($job -and $job.JobState -eq "Transferred") {
            Complete-BitsTransfer -BitsJob $job
            Write-InstallLog "$($package.Name) download completed."
        }
    }
}

function Get-DownloadProgress {
    $total = [int64]0
    $transferred = [int64]0
    foreach ($package in $Packages) {
        $total += [int64]$package.Size
        $path = Get-PackagePath $package
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $transferred += [Math]::Min([int64](Get-Item -LiteralPath $path).Length, [int64]$package.Size)
            continue
        }
        $job = Get-DownloadJob $package
        if ($job) {
            $transferred += [Math]::Min([int64]$job.BytesTransferred, [int64]$package.Size)
        }
    }
    $percent = if ($total -gt 0) { [int][Math]::Floor(($transferred * 100.0) / $total) } else { 0 }
    return @{
        Total = $total
        Transferred = $transferred
        Percent = [Math]::Min($percent, 99)
    }
}

function Write-InstallStatus {
    param(
        [string]$State,
        [string]$Message,
        [int]$Percent
    )
    $progress = Get-DownloadProgress
    @{
        state = $State
        message = $Message
        percent = $Percent
        downloaded_bytes = $progress.Transferred
        total_bytes = $progress.Total
        transport = "BITS"
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
}

function Test-AllPackagesReady {
    foreach ($package in $Packages) {
        $path = Get-PackagePath $package
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            return $false
        }
        if ((Get-Item -LiteralPath $path).Length -ne [int64]$package.Size) {
            return $false
        }
    }
    return $true
}

function Test-CudaTorchReady {
    param([string]$Python)
    $result = & $Python -c "import torch; print(int(torch.cuda.is_available() and torch.version.cuda is not None))" 2>$null
    return $LASTEXITCODE -eq 0 -and ($result | Select-Object -Last 1).Trim() -eq "1"
}

function Invoke-OpenClipGpuSmokeTest {
    param([string]$Python)
    Write-InstallStatus -State "testing" -Message "Running a real OpenCLIP GPU inference test." -Percent 99
    Write-InstallLog "Running real OpenCLIP GPU inference smoke test."
    $smokeOutput = & $Python $SmokeScript 2>&1
    $smokeOutput | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "OpenCLIP GPU smoke test failed: $(($smokeOutput -join ' ').Trim())"
    }
    $jsonLine = $smokeOutput | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if (-not $jsonLine) {
        throw "OpenCLIP GPU smoke test did not return JSON."
    }
    $smoke = $jsonLine | ConvertFrom-Json
    if (-not [bool]$smoke.cuda_available -or [string]$smoke.device -notlike "cuda*") {
        throw "OpenCLIP smoke test did not use CUDA."
    }
    Write-InstallLog "GPU smoke test passed on $($smoke.gpu_name) in $($smoke.elapsed_seconds) seconds."
}

New-Item -ItemType Directory -Force -Path $DownloadDir, $LogsDir | Out-Null
Set-Content -LiteralPath $PidFile -Value $PID -Encoding ASCII
$Host.UI.RawUI.WindowTitle = "ContentResearch - OpenCLIP GPU runtime installer"

try {
    $python = Get-PythonPath
    if (-not (Test-Path -LiteralPath $ModelFile -PathType Leaf)) {
        throw "OpenCLIP model weights are missing: $ModelFile"
    }
    if (Test-CudaTorchReady -Python $python) {
        $existingCheck = @(& $python -m pip check 2>&1)
        if ($LASTEXITCODE -eq 0) {
            Write-InstallLog "CUDA-enabled PyTorch and dependencies are already available; running smoke test."
            Invoke-OpenClipGpuSmokeTest -Python $python
            foreach ($package in $Packages) {
                Remove-Item -LiteralPath (Get-PackagePath $package) -Force -ErrorAction SilentlyContinue
            }
            if ((Test-Path -LiteralPath $DownloadDir) -and -not (Get-ChildItem -LiteralPath $DownloadDir -Force)) {
                Remove-Item -LiteralPath $DownloadDir -Force
            }
            Write-InstallStatus -State "complete" -Message "OpenCLIP GPU runtime is ready." -Percent 100
            Write-InstallLog "OpenCLIP GPU runtime is already ready."
            exit 0
        }
        Write-InstallLog "CUDA PyTorch is installed, but dependency repair is required: $(($existingCheck -join ' ').Trim())"
    }

    $currentVersions = & $python -c "import torch, torchvision; print(f'torch={torch.__version__}, torchvision={torchvision.__version__}')"
    Write-InstallLog "Current runtime: $(($currentVersions -join ' ').Trim())"
    Write-InstallStatus -State "downloading" -Message "Downloading CUDA-enabled PyTorch with BITS." -Percent 0
    foreach ($package in $Packages) {
        Ensure-DownloadJob $package
    }

    $lastBytes = [int64]-1
    $lastProgressAt = Get-Date
    $lastLoggedPercent = -5
    while (-not (Test-AllPackagesReady)) {
        Complete-TransferredJobs
        if (Test-AllPackagesReady) {
            break
        }
        foreach ($package in $Packages) {
            Ensure-DownloadJob $package
        }
        $progress = Get-DownloadProgress
        if ($progress.Transferred -gt $lastBytes) {
            $lastBytes = $progress.Transferred
            $lastProgressAt = Get-Date
        }
        elseif (((Get-Date) - $lastProgressAt).TotalSeconds -ge 180) {
            throw "BITS received no new data for 180 seconds."
        }
        $message = "Downloaded {0:N1}/{1:N1} MiB" -f ($progress.Transferred / 1MB), ($progress.Total / 1MB)
        Write-Progress -Activity "Downloading OpenCLIP CUDA PyTorch" -Status "$($progress.Percent)%  $message" -PercentComplete $progress.Percent
        Write-InstallStatus -State "downloading" -Message $message -Percent $progress.Percent
        if ($progress.Percent -ge ($lastLoggedPercent + 5)) {
            Write-InstallLog "Progress $($progress.Percent)% ($message)."
            $lastLoggedPercent = $progress.Percent
        }
        Start-Sleep -Seconds 2
    }
    Write-Progress -Activity "Downloading OpenCLIP CUDA PyTorch" -Completed

    $paths = @()
    foreach ($package in $Packages) {
        $path = Get-PackagePath $package
        Write-InstallStatus -State "verifying" -Message "Verifying $($package.Name) SHA-256." -Percent 99
        Write-InstallLog "Verifying $($package.Name) SHA-256."
        $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $package.Sha256) {
            throw "$($package.Name) SHA-256 verification failed."
        }
        $paths += $path
    }

    Write-InstallStatus -State "installing" -Message "Installing CUDA-enabled PyTorch." -Percent 99
    Write-InstallLog "Installing torch 2.11.0+cu128, torchvision 0.26.0+cu128, and setuptools 81.0.0."
    & $python -m pip install --no-index --no-deps --force-reinstall @paths
    if ($LASTEXITCODE -ne 0) {
        throw "pip installation failed with exit code $LASTEXITCODE."
    }
    $pipCheck = @(& $python -m pip check 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency check failed: $(($pipCheck -join ' ').Trim())"
    }
    if (-not (Test-CudaTorchReady -Python $python)) {
        throw "PyTorch installed, but torch.cuda.is_available() is false."
    }

    Invoke-OpenClipGpuSmokeTest -Python $python
    foreach ($package in $Packages) {
        Remove-Item -LiteralPath (Get-PackagePath $package) -Force -ErrorAction SilentlyContinue
    }
    if ((Test-Path -LiteralPath $DownloadDir) -and -not (Get-ChildItem -LiteralPath $DownloadDir -Force)) {
        Remove-Item -LiteralPath $DownloadDir -Force
    }
    Write-InstallStatus -State "complete" -Message "OpenCLIP GPU runtime is installed and verified." -Percent 100
    Write-InstallLog "OpenCLIP GPU runtime installation and verification completed."
    Write-Host "Complete. You can close this window now." -ForegroundColor Green
}
catch {
    $progress = Get-DownloadProgress
    Write-InstallStatus -State "failed" -Message $_.Exception.Message -Percent $progress.Percent
    Write-InstallLog "Installation failed: $($_.Exception.Message)"
    Write-Host "Installation failed. Downloaded packages are retained for resume or inspection." -ForegroundColor Red
    throw
}
finally {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}
