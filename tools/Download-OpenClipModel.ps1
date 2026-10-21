param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$CacheDir = Join-Path $Root "cache\models\openclip"
$ModelFile = Join-Path $CacheDir "open_clip_model.safetensors"
$LogsDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogsDir "openclip_model_download.log"
$StatusFile = Join-Path $LogsDir "openclip_model_download.status.json"
$PidFile = Join-Path $LogsDir "openclip_model_download.pid"

$DisplayName = "ContentResearch-OpenCLIP-ViT-B-32"
$SourceUrl = "https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K/resolve/main/open_clip_model.safetensors?download=true"
$ExpectedSize = [int64]605143316
$ExpectedSha256 = "ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6"

function Write-DownloadLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Get-DownloadJob {
    return Get-BitsTransfer -AllUsers:$false -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq $DisplayName } |
        Select-Object -First 1
}

function Get-DownloadedBytes {
    if (Test-Path -LiteralPath $ModelFile -PathType Leaf) {
        return [int64](Get-Item -LiteralPath $ModelFile).Length
    }
    $job = Get-DownloadJob
    if ($job) {
        return [int64]$job.BytesTransferred
    }
    return [int64]0
}

function Write-DownloadStatus {
    param(
        [string]$State,
        [string]$Message,
        [int]$Percent
    )
    @{
        state = $State
        message = $Message
        percent = $Percent
        downloaded_bytes = Get-DownloadedBytes
        total_bytes = $ExpectedSize
        transport = "BITS"
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
}

function Ensure-DownloadJob {
    if (Test-Path -LiteralPath $ModelFile -PathType Leaf) {
        return
    }
    $job = Get-DownloadJob
    if (-not $job) {
        Write-DownloadLog "Creating a resumable Windows BITS download."
        Start-BitsTransfer `
            -Source $SourceUrl `
            -Destination $ModelFile `
            -DisplayName $DisplayName `
            -Description "ContentResearch OpenCLIP model" `
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
}

New-Item -ItemType Directory -Force -Path $CacheDir, $LogsDir | Out-Null
Set-Content -LiteralPath $PidFile -Value $PID -Encoding ASCII
$Host.UI.RawUI.WindowTitle = "ContentResearch - OpenCLIP BITS download"

try {
    if (Test-Path -LiteralPath $ModelFile -PathType Leaf) {
        if ((Get-Item -LiteralPath $ModelFile).Length -ne $ExpectedSize) {
            throw "A model file exists with an unexpected size: $ModelFile"
        }
    }
    else {
        Write-DownloadStatus -State "downloading" -Message "Starting Windows BITS download." -Percent 0
        Write-DownloadLog "Starting OpenCLIP model download (577.1 MiB) with Windows BITS."
        Write-Host "This window shows system-managed, resumable download progress." -ForegroundColor Cyan
        Write-Host "Target: $ModelFile" -ForegroundColor DarkGray
        Ensure-DownloadJob

        $lastBytes = [int64]-1
        $lastProgressAt = Get-Date
        $lastLoggedPercent = -10
        while (-not (Test-Path -LiteralPath $ModelFile -PathType Leaf)) {
            $job = Get-DownloadJob
            if (-not $job) {
                Ensure-DownloadJob
                $job = Get-DownloadJob
            }
            if (-not $job) {
                throw "BITS did not create a download job."
            }
            if ($job.JobState -eq "Error") {
                throw "BITS error: $($job.ErrorDescription)"
            }
            if ($job.JobState -in @("Suspended", "TransientError")) {
                Resume-BitsTransfer -BitsJob $job -Asynchronous | Out-Null
            }
            elseif ($job.JobState -eq "Transferred") {
                Complete-BitsTransfer -BitsJob $job
                break
            }

            $downloaded = [int64]$job.BytesTransferred
            if ($downloaded -gt $lastBytes) {
                $lastBytes = $downloaded
                $lastProgressAt = Get-Date
            }
            elseif (((Get-Date) - $lastProgressAt).TotalSeconds -ge 120) {
                throw "BITS received no new data for 120 seconds. Job state: $($job.JobState)."
            }
            $reportedTotal = [uint64]$job.BytesTotal
            $total = if ($reportedTotal -gt 0 -and $reportedTotal -lt [uint64]::MaxValue) {
                [int64]$reportedTotal
            }
            else {
                $ExpectedSize
            }
            $percent = [Math]::Min(99, [int][Math]::Floor(($downloaded * 100.0) / $total))
            $message = "Downloaded {0:N1}/{1:N1} MiB; BITS state: {2}" -f ($downloaded / 1MB), ($total / 1MB), $job.JobState
            Write-Progress -Activity "Downloading OpenCLIP ViT-B-32 with BITS" -Status "$percent%  $message" -PercentComplete $percent
            Write-DownloadStatus -State "downloading" -Message $message -Percent $percent
            if ($percent -ge ($lastLoggedPercent + 10)) {
                Write-DownloadLog "Progress $percent% ($message)."
                $lastLoggedPercent = $percent
            }
            Start-Sleep -Seconds 2
        }
        Write-Progress -Activity "Downloading OpenCLIP ViT-B-32 with BITS" -Completed
    }

    if (-not (Test-Path -LiteralPath $ModelFile -PathType Leaf)) {
        throw "BITS completed without producing the model file."
    }
    if ((Get-Item -LiteralPath $ModelFile).Length -ne $ExpectedSize) {
        throw "Downloaded model size does not match the expected size."
    }
    Write-DownloadStatus -State "verifying" -Message "Download complete; verifying SHA-256." -Percent 99
    Write-DownloadLog "Download complete; verifying SHA-256."
    $actualHash = (Get-FileHash -LiteralPath $ModelFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedSha256) {
        throw "Model SHA-256 verification failed."
    }
    Write-DownloadStatus -State "complete" -Message "OpenCLIP model is downloaded and verified." -Percent 100
    Write-DownloadLog "OpenCLIP model downloaded and verified: $ModelFile"
    Write-Host "Complete. You can close this window now." -ForegroundColor Green
}
catch {
    $downloaded = Get-DownloadedBytes
    $percent = [Math]::Min(99, [int][Math]::Floor(($downloaded * 100.0) / $ExpectedSize))
    Write-DownloadStatus -State "failed" -Message $_.Exception.Message -Percent $percent
    Write-DownloadLog "Download failed: $($_.Exception.Message)"
    Write-Host "The BITS job is preserved for inspection or resume." -ForegroundColor Red
    throw
}
finally {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}
