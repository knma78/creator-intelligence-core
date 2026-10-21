param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$Deck,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Preview directory already exists.' }
[void](New-Item -ItemType Directory -Path $OutputDirectory)
$taskBundle = Get-Content -Raw -LiteralPath $Bundle -Encoding UTF8 | ConvertFrom-Json
$taskApp = $null
$taskDeck = $null
$taskHadDecks = $true
try {
    $taskApp = New-Object -ComObject PowerPoint.Application
    $taskHadDecks = $taskApp.Presentations.Count -gt 0
    $taskDeck = $taskApp.Presentations.Open([IO.Path]::GetFullPath($Deck), -1, 0, 0)
    for ($taskIndex = 0; $taskIndex -lt $taskBundle.pages.Count; $taskIndex++) {
        $taskRecord = $taskBundle.pages[$taskIndex]
        $taskSlide = $taskDeck.Slides.Item($taskIndex + 1)
        foreach ($taskFrame in $taskRecord.scene.preview_frames) {
            foreach ($taskProperty in $taskRecord.scene.visibility.PSObject.Properties) {
                $taskVisible = $false
                foreach ($taskInterval in $taskProperty.Value) {
                    if ($taskFrame -ge $taskInterval[0] -and $taskFrame -lt $taskInterval[1]) { $taskVisible = $true }
                }
                $taskSlide.Shapes.Item([string]$taskProperty.Name).Visible = if ($taskVisible) { -1 } else { 0 }
            }
            foreach ($taskRotation in $taskRecord.scene.rotations) {
                $taskProgress = [Math]::Max(0.0, [Math]::Min(1.0, [double]($taskFrame - $taskRotation.start_frame) / ($taskRotation.end_frame - $taskRotation.start_frame)))
                $taskSlide.Shapes.Item([string]$taskRotation.target).Rotation = $taskProgress * $taskRotation.degrees
            }
            $taskName = $taskRecord.page.id + '-f' + $taskFrame + '.png'
            $taskSlide.Export((Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) $taskName), 'PNG', 1280, 720)
        }
        Write-Output ('Native state previews: ' + $taskRecord.page.id)
    }
} finally {
    if ($null -ne $taskDeck) {
        $taskDeck.Saved = -1
        $taskDeck.Close()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($taskDeck)
    }
    if ($null -ne $taskApp) {
        if (-not $taskHadDecks) { $taskApp.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($taskApp)
    }
}
