param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$Draft,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Output) { throw 'Output already exists; refusing to overwrite.' }
$taskBundle = Get-Content -Raw -LiteralPath $Bundle -Encoding UTF8 | ConvertFrom-Json
$taskApp = $null
$taskDeck = $null
$taskHadDecks = $true
try {
    $taskApp = New-Object -ComObject PowerPoint.Application
    $taskHadDecks = $taskApp.Presentations.Count -gt 0
    $taskDeck = $taskApp.Presentations.Open([IO.Path]::GetFullPath($Draft), 0, 0, 0)
    if ($taskDeck.Slides.Count -ne $taskBundle.pages.Count) { throw 'Slide count mismatch.' }
    $taskReports = @()
    for ($taskIndex = 0; $taskIndex -lt $taskBundle.pages.Count; $taskIndex++) {
        $taskPage = $taskBundle.pages[$taskIndex]
        $taskSlide = $taskDeck.Slides.Item($taskIndex + 1)
        foreach ($taskTextShape in $taskSlide.Shapes) {
            if ($taskTextShape.HasTextFrame -and $taskTextShape.TextFrame.HasText) {
                $taskTextShape.TextFrame.TextRange.Font.Name = 'Microsoft YaHei'
                $taskTextShape.TextFrame.TextRange.Font.NameFarEast = 'Microsoft YaHei'
            }
        }
        $taskSequence = $taskSlide.TimeLine.MainSequence
        if ($taskSequence.Count -ne 0) { throw 'Draft must not contain pre-existing animations.' }
        foreach ($taskGroup in $taskPage.scene.groups) {
            $taskMembers = [object[]]@($taskGroup.members | ForEach-Object { [string]$_ })
            $taskGrouped = $taskSlide.Shapes.Range($taskMembers).Group()
            $taskGrouped.Name = [string]$taskGroup.name
        }
        $taskEvents = @()
        foreach ($taskProperty in $taskPage.scene.visibility.PSObject.Properties) {
            $taskIntervals = $taskProperty.Value
            foreach ($taskInterval in $taskIntervals) {
                $taskStart = [int]$taskInterval[0]
                $taskEnd = [int]$taskInterval[1]
                if ($taskStart -gt 0) {
                    $taskEvents += [pscustomobject]@{frame=$taskStart; name=$taskProperty.Name; exit=$false; rotation=$null}
                }
                if ($taskEnd -lt [int]$taskPage.scene.duration_frames) {
                    $taskEvents += [pscustomobject]@{frame=$taskEnd; name=$taskProperty.Name; exit=$true; rotation=$null}
                }
            }
        }
        foreach ($taskRotation in $taskPage.scene.rotations) {
            $taskEvents += [pscustomobject]@{frame=$taskRotation.start_frame; name=$taskRotation.target; exit=$false; rotation=$taskRotation}
        }
        $taskEvents = @($taskEvents | Sort-Object frame, name, exit)
        foreach ($taskEvent in $taskEvents) {
            $taskShape = $taskSlide.Shapes.Item([string]$taskEvent.name)
            # Appear effect; Exit turns it into a discrete disappearance.
            $taskTrigger = if ($taskSequence.Count -eq 0) { 3 } else { 2 }
            if ($null -eq $taskEvent.rotation) {
                $taskEffect = $taskSequence.AddEffect($taskShape, 1, 0, $taskTrigger)
                $taskEffect.Exit = if ($taskEvent.exit) { -1 } else { 0 }
                $taskEffect.Timing.Duration = 0.001
            } else {
                $taskEffect = $taskSequence.AddEffect($taskShape, 61, 0, $taskTrigger)
                $taskEffect.EffectParameters.Amount = [single]$taskEvent.rotation.degrees
                $taskEffect.Timing.Duration = ($taskEvent.rotation.end_frame - $taskEvent.rotation.start_frame) / 30.0
                $taskEffect.Timing.Accelerate = 0
                $taskEffect.Timing.Decelerate = 0
            }
            # All WithPrevious effects share one automatic group. PowerPoint
            # serializes each delay relative to that group's start, not the
            # preceding sibling's delay. Package audit checks the saved values.
            $taskEffect.Timing.TriggerDelayTime = $taskEvent.frame / 30.0
        }
        if ($taskBundle.mode -eq 'production') {
            $taskAudio = $taskPage.page.narration.audio
            if ($null -eq $taskAudio) { throw 'Production requires embedded narration.' }
            if ((Get-FileHash -LiteralPath $taskAudio.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskAudio.sha256) {
                throw 'Audio changed after compilation.'
            }
            $taskMedia = $taskSlide.Shapes.AddMediaObject2($taskAudio.path, 0, -1, 0, 0, 1, 1)
            $taskMedia.Name = 'narration_audio'
            $taskMedia.AnimationSettings.PlaySettings.PlayOnEntry = -1
            $taskMedia.AnimationSettings.PlaySettings.HideWhileNotPlaying = -1
            $taskMedia.AnimationSettings.PlaySettings.StopAfterSlides = 1
        }
        $taskSlide.SlideShowTransition.AdvanceOnClick = 0
        $taskSlide.SlideShowTransition.AdvanceOnTime = -1
        $taskSlide.SlideShowTransition.AdvanceTime = $taskPage.scene.duration_frames / 30.0
        $taskSlide.SlideShowTransition.EntryEffect = 0
        $taskReports += [pscustomobject]@{id=$taskPage.page.id; shapes=$taskSlide.Shapes.Count; effects=$taskSequence.Count}
        Write-Output ('Animation ready: ' + $taskPage.page.id + ' / effects ' + $taskSequence.Count)
    }
    $taskDeck.SlideShowSettings.AdvanceMode = 2
    $taskDeck.SaveAs([IO.Path]::GetFullPath($Output), 24)
    $taskReports | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ($Output + '.powerpoint.json') -Encoding UTF8
} finally {
    if ($null -ne $taskDeck) {
        $taskDeck.Close()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($taskDeck)
    }
    if ($null -ne $taskApp) {
        if (-not $taskHadDecks) { $taskApp.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($taskApp)
    }
}
