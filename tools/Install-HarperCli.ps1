param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DownloadDir = Join-Path $Root ".downloads\harper-cli"
$Archive = Join-Path $DownloadDir "harper-cli-x86_64-pc-windows-msvc.zip"
$ExtractDir = Join-Path $DownloadDir "extracted"
$InstallDir = Join-Path $Root "integrations\english_review\bin"
$Target = Join-Path $InstallDir "harper-cli.exe"
$LogsDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogsDir "english_review_harper.install.log"
$StatusFile = Join-Path $LogsDir "english_review_harper.status.json"
$DisplayName = "ContentResearch-Harper-CLI-v2.7.0"
$Url = "https://github.com/Automattic/harper/releases/download/v2.7.0/harper-cli-x86_64-pc-windows-msvc.zip"
$ExpectedSize = [int64]12241550
$ExpectedSha256 = "6a0557d1390297850fe0a5dec610989bef7ddb1c464d19dc7bfc84a398cfc906"

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
    [ordered]@{
        component = "Harper CLI"
        state = $State
        message = $Message
        percent = $Percent
        process_id = $PID
        target = $Target
        updated_at = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
}

function Get-DownloadJob {
    return Get-BitsTransfer -AllUsers:$false -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq $DisplayName } |
        Select-Object -First 1
}

function Test-Archive {
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
        return $false
    }
    $item = Get-Item -LiteralPath $Archive
    if ($item.Length -ne $ExpectedSize) {
        return $false
    }
    return (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSha256
}

$host.UI.RawUI.WindowTitle = "ContentResearch - Harper CLI download"
New-Item -ItemType Directory -Force -Path $DownloadDir, $InstallDir, $LogsDir | Out-Null
Write-Host "ContentResearch Harper CLI installer" -ForegroundColor Cyan
Write-Host "Official GitHub release: v2.7.0 (11.7 MiB)" -ForegroundColor Cyan
Write-Host "BITS provides visible progress and resumable download state." -ForegroundColor DarkCyan

try {
    if (-not (Test-Archive)) {
        if (Test-Path -LiteralPath $Archive -PathType Leaf) {
            Remove-Item -LiteralPath $Archive -Force
        }
        $job = Get-DownloadJob
        if (-not $job) {
            Write-InstallLog "Creating resumable BITS download from the official Harper GitHub release."
            Start-BitsTransfer `
                -Source $Url `
                -Destination $Archive `
                -DisplayName $DisplayName `
                -Description "ContentResearch Harper CLI runtime" `
                -Priority Foreground `
                -Asynchronous | Out-Null
        }
        $lastBytes = -1
        $lastProgressAt = Get-Date
        while ($true) {
            $job = Get-DownloadJob
            if (-not $job) {
                throw "BITS job disappeared before the archive was completed."
            }
            if ($job.JobState -in @("TransientError", "Suspended")) {
                Resume-BitsTransfer -BitsJob $job -Asynchronous | Out-Null
            }
            if ($job.JobState -eq "Error") {
                throw "BITS download failed: $($job.ErrorDescription)"
            }
            if ($job.JobState -eq "Transferred") {
                Complete-BitsTransfer -BitsJob $job
                break
            }
            $total = if ($job.BytesTotal -gt 0) { $job.BytesTotal } else { $ExpectedSize }
            $percent = [math]::Min(99, [int](100 * $job.BytesTransferred / $total))
            $message = "Downloaded {0:N1}/{1:N1} MiB" -f ($job.BytesTransferred / 1MB), ($total / 1MB)
            Write-Progress -Activity "Downloading Harper CLI v2.7.0" -Status "$percent%  $message" -PercentComplete $percent
            Write-InstallStatus -State "downloading" -Message $message -Percent $percent
            if ($job.BytesTransferred -ne $lastBytes) {
                $lastBytes = $job.BytesTransferred
                $lastProgressAt = Get-Date
            }
            elseif (((Get-Date) - $lastProgressAt).TotalSeconds -ge 180) {
                throw "Harper CLI download made no progress for 180 seconds; the BITS job was retained for resume."
            }
            Start-Sleep -Seconds 1
        }
        Write-Progress -Activity "Downloading Harper CLI v2.7.0" -Completed
    }

    Write-InstallStatus -State "verifying" -Message "Verifying archive size and SHA-256." -Percent 100
    if (-not (Test-Archive)) {
        throw "Downloaded Harper CLI archive failed size or SHA-256 verification."
    }
    Write-InstallLog "Archive SHA-256 verified."

    if (Test-Path -LiteralPath $ExtractDir) {
        Remove-Item -LiteralPath $ExtractDir -Recurse -Force
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractDir -Force
    $executable = Get-ChildItem -LiteralPath $ExtractDir -Recurse -Filter "harper-cli.exe" -File |
        Select-Object -First 1
    if (-not $executable) {
        throw "The official archive does not contain harper-cli.exe."
    }
    Copy-Item -LiteralPath $executable.FullName -Destination $Target -Force
    $version = (& $Target --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Harper CLI smoke test failed: $version"
    }
    if (Test-Path -LiteralPath $ExtractDir) {
        Remove-Item -LiteralPath $ExtractDir -Recurse -Force
    }
    $completeMessage = "Harper release v2.7.0 installed and verified ($version)"
    Write-InstallStatus -State "complete" -Message $completeMessage -Percent 100
    Write-InstallLog $completeMessage
    Write-Host "Completed. This window will close in 20 seconds." -ForegroundColor Green
    Start-Sleep -Seconds 20
}
catch {
    Write-InstallStatus -State "failed" -Message $_.Exception.Message
    Write-InstallLog "Installation failed: $($_.Exception.Message)"
    Write-Host "Failed. The resumable BITS state and archive cache were retained." -ForegroundColor Red
    Write-Host "This window will close in 30 seconds." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
}
