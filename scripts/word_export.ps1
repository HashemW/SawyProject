<#
.SYNOPSIS
  Reads every .doc/.docx in a folder through Microsoft Word and writes Word's own view of it,
  as a trusted baseline for checking other text conversions.

  For each source file <name>, under OutDir:
    text\<name>.txt       main text as Word reads it: tracked changes accepted, list numbers
                          as text, hidden text and field codes left out. Footnote/endnote
                          references stay as U+0002, Word's own reference character.
    notes\<name>.txt      footnote then endnote texts, one per line: "<n><TAB><text>"
    frames\<name>.txt     text inside text boxes/frames (only if there is any)
    xml\<name>.xml.gz     the document's WordprocessingML (flat OPC), for structure audits
  plus inventory\<name>.json per file, merged into word_inventory.json. Files that already
  have an inventory entry are skipped unless -Force, so the script can be re-run as more
  source files arrive.

  Nothing is ever saved: files open read-only and close without saving. (Word's SaveAs hangs
  on these documents; everything here is read from memory instead.) Macros never run.
  A watchdog stops Word if one file takes longer than -TimeoutSeconds; only Word processes
  this script started are ever stopped.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_export.ps1 -InputDir data\raw\sawi_material -OutDir data\work\word
#>
param(
    [Parameter(Mandatory = $true)] [string] $InputDir,
    [Parameter(Mandatory = $true)] [string] $OutDir,
    [int] $TimeoutSeconds = 300,
    [switch] $Force
)
$ErrorActionPreference = 'Stop'

$wdDoNotSaveChanges = 0
$wdAlertsNone = 0
$wdTextFrameStory = 5
$msoAutomationSecurityForceDisable = 3
$missing = [Reflection.Missing]::Value
$utf8 = New-Object System.Text.UTF8Encoding($false)

$InputDir = (Resolve-Path -LiteralPath $InputDir).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path
$dirs = @{}
foreach ($d in 'text', 'notes', 'frames', 'xml', 'inventory') {
    $dirs[$d] = Join-Path $OutDir $d
    New-Item -ItemType Directory -Force -Path $dirs[$d] | Out-Null
}

function Start-Word {
    $before = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $w = New-Object -ComObject Word.Application
    $script:wordPid = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | ForEach-Object { $_.Id }) | Select-Object -First 1
    $w.Visible = $false
    $w.DisplayAlerts = $wdAlertsNone
    $w.AutomationSecurity = $msoAutomationSecurityForceDisable
    $w.ScreenUpdating = $false
    return $w
}

# Word's interop wants SaveChanges by reference on some objects and by value on others.
function Close-Doc($d) {
    try { $d.Close([ref]$wdDoNotSaveChanges) } catch { try { $d.Close($wdDoNotSaveChanges) } catch { } }
}

function Stop-Word($w) {
    try {
        foreach ($d in @($w.Documents)) { Close-Doc $d }
        try { $w.Quit([ref]$wdDoNotSaveChanges) } catch { $w.Quit($wdDoNotSaveChanges) }
    } catch { }
    Start-Sleep -Seconds 2
    if ($script:wordPid -and (Get-Process -Id $script:wordPid -ErrorAction SilentlyContinue)) { Stop-Process -Id $script:wordPid -Force }
}

function Write-Gzip($path, $text) {
    $fs = [IO.File]::Create($path)
    $gz = New-Object IO.Compression.GZipStream($fs, [IO.Compression.CompressionMode]::Compress)
    $bytes = $utf8.GetBytes($text)
    $gz.Write($bytes, 0, $bytes.Length)
    $gz.Dispose(); $fs.Dispose()
}

function Get-StoryText($story) {
    $sb = New-Object System.Text.StringBuilder
    while ($story) { [void]$sb.Append($story.Text); $story = $story.NextStoryRange }
    return $sb.ToString()
}

# Watchdog: if the current file has been running longer than the limit, stop that Word process.
$heartbeat = Join-Path $OutDir '.heartbeat'
Set-Content -LiteralPath $heartbeat -Value 'idle'
$watchdog = Start-Job -ArgumentList $heartbeat, $TimeoutSeconds -ScriptBlock {
    param($hb, $limit)
    while ($true) {
        Start-Sleep -Seconds 5
        $parts = ((Get-Content -LiteralPath $hb -Raw -ErrorAction SilentlyContinue) + '').Trim() -split '\|'
        if ($parts[0] -eq 'done') { break }
        if ($parts.Count -ne 2 -or $parts[0] -notmatch '^\d+$') { continue }
        $since = [datetime]::FromBinary([long]$parts[1])
        if (((Get-Date) - $since).TotalSeconds -gt $limit) {
            Stop-Process -Id ([int]$parts[0]) -Force -ErrorAction SilentlyContinue
            Set-Content -LiteralPath $hb -Value 'idle'
        }
    }
}

$files = @(Get-ChildItem -LiteralPath $InputDir -File | Where-Object { $_.Extension -in '.doc', '.docx' } | Sort-Object Name)
if (-not $Force) {
    $files = @($files | Where-Object { -not (Test-Path -LiteralPath (Join-Path $dirs.inventory ($_.Name + '.json'))) })
}
$word = Start-Word
try {
    $i = 0
    foreach ($f in $files) {
        $i++
        $info = [ordered]@{ file = $f.Name; bytes = $f.Length }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        Set-Content -LiteralPath $heartbeat -Value ('{0}|{1}' -f $script:wordPid, (Get-Date).ToBinary())
        $doc = $null
        try {
            # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument, PasswordTemplate,
            #      Revert, WritePasswordDocument, WritePasswordTemplate, Format, Encoding, Visible, OpenAndRepair,
            #      DocumentDirection, NoEncodingDialog). A dummy password makes protected files fail instead of prompting.
            $doc = $word.Documents.Open($f.FullName, $false, $true, $false, 'x', 'x', $false, '', '', 0, $missing, $false, $false, $missing, $true)
            $info.paragraphs = $doc.Paragraphs.Count
            $info.footnotes = $doc.Footnotes.Count
            $info.endnotes = $doc.Endnotes.Count
            $info.comments = $doc.Comments.Count
            $info.revisions = $doc.Revisions.Count
            $info.tables = $doc.Tables.Count
            $info.shapes = $doc.Shapes.Count
            $info.inline_shapes = $doc.InlineShapes.Count
            $info.fields = $doc.Fields.Count
            $info.list_paragraphs = $doc.ListParagraphs.Count

            Write-Gzip (Join-Path $dirs.xml ($f.Name + '.xml.gz')) $doc.WordOpenXML

            $all = $doc.Content
            $all.TextRetrievalMode.IncludeFieldCodes = $false
            $all.TextRetrievalMode.IncludeHiddenText = $true
            $info.chars_with_hidden = $all.Text.Length

            # In memory only; the document is closed without saving.
            if ($info.revisions -gt 0) { $doc.Revisions.AcceptAll() }
            if ($info.list_paragraphs -gt 0) { $doc.ConvertNumbersToText() }

            $main = $doc.Content
            $main.TextRetrievalMode.IncludeFieldCodes = $false
            $main.TextRetrievalMode.IncludeHiddenText = $false
            $text = $main.Text
            $info.chars = $text.Length
            $info.note_refs = $text.Length - $text.Replace([string][char]2, '').Length
            [IO.File]::WriteAllText((Join-Path $dirs.text ($f.Name + '.txt')), $text, $utf8)

            $notes = New-Object System.Text.StringBuilder
            $n = 0
            foreach ($coll in @($doc.Footnotes, $doc.Endnotes)) {
                for ($k = 1; $k -le $coll.Count; $k++) {
                    $n++
                    [void]$notes.Append($n).Append("`t").Append(($coll.Item($k).Range.Text -replace '[\r\n]+', ' ')).Append("`n")
                }
            }
            [IO.File]::WriteAllText((Join-Path $dirs.notes ($f.Name + '.txt')), $notes.ToString(), $utf8)
            $info.note_chars = $notes.Length

            $frames = ''
            foreach ($story in $doc.StoryRanges) {
                if ($story.StoryType -eq $wdTextFrameStory) { $frames += Get-StoryText $story }
            }
            $info.frame_chars = $frames.Length
            if ($frames.Length) { [IO.File]::WriteAllText((Join-Path $dirs.frames ($f.Name + '.txt')), $frames, $utf8) }
            $info.status = 'ok'
        } catch {
            $info.status = 'error'
            $info.error = $_.Exception.Message
        } finally {
            if ($doc) { Close-Doc $doc }
            Set-Content -LiteralPath $heartbeat -Value 'idle'
        }
        $info.seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        [IO.File]::WriteAllText((Join-Path $dirs.inventory ($f.Name + '.json')), (ConvertTo-Json -InputObject ([pscustomobject]$info) -Depth 4), $utf8)
        Write-Output ('[{0}/{1}] {2} {3} ({4}s)' -f $i, $files.Count, $info.status, $f.Name, $info.seconds)
        if ($info.status -ne 'ok') {
            # Word may be dead (watchdog) or wedged; start a fresh one for the next file.
            Stop-Word $word
            $word = Start-Word
        }
    }
} finally {
    Stop-Word $word
    Set-Content -LiteralPath $heartbeat -Value 'done'
    Start-Sleep -Seconds 6
    Remove-Job -Job $watchdog -Force
    Remove-Item -LiteralPath $heartbeat -ErrorAction SilentlyContinue
}

$rows = @(Get-ChildItem -LiteralPath $dirs.inventory -Filter '*.json' | Sort-Object Name | ForEach-Object { [IO.File]::ReadAllText($_.FullName, $utf8) | ConvertFrom-Json })
[IO.File]::WriteAllText((Join-Path $OutDir 'word_inventory.json'), (ConvertTo-Json -InputObject $rows -Depth 4), $utf8)
Write-Output ('inventory: {0} files' -f $rows.Count)
