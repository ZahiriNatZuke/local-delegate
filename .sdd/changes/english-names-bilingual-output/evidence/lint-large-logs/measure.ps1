param([ValidateSet('X','G','M','ME','restore','stop')][string]$Step, [string]$Tag = 'main', [int]$Repeat = 3)
# lint-large-logs: copy of lint-counts/measure.ps1 with this manifest, its runs/ and window X
# (chunked long role; its chunk notes go to runs/<tag>/notes via LOCAL_DELEGATE_DUMP_CHUNK_NOTES).
# Every window that can use the long role (G, GE, H, HE) gets no fallback
# (LOCAL_DELEGATE_FALLBACK_LONG=none: its chain ends in qwen36, ~18 GB). The step stops if less
# than 4 GB of RAM are free before starting. The install step is NOT here: it runs from the Bash
# tool (pesado.sh), from the checkout to measure.
$ErrorActionPreference = 'Stop'
$launcher = 'D:\Projects\llms\llama-swap\start-local-delegate-secure.ps1'
$backup = 'C:\Users\Yohan\.claude\relevos\launcher-backup.ps1'
$expected = 'c96f022aeb1b2570fc273419203f2f870d7a13022c373e35f7ae6af7ae69f69a'
$E = '.sdd/changes/english-names-bilingual-output/evidence'
Set-Location 'D:\Projects\ld-wt-biglog'

function Stop-Daemon {
    schtasks /End /TN LocalDelegateDaemon | Out-Null
    Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -like '*uv\tools\local-delegate-mcp*' -or $_.Path -like '*uv\python\cpython*'
    } | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}
function Start-Daemon {
    schtasks /Run /TN LocalDelegateDaemon | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', 9393); $c.Close(); Start-Sleep 3; return } catch {}
    }
    throw 'daemon did not come up on 9393'
}
function Set-LauncherEnv([string[]]$lines) {
    $text = [IO.File]::ReadAllText($backup)
    $anchor = "`$env:LOCAL_DELEGATE_STRUCTURED_SUMMARY = '1'"
    if (-not $text.Contains($anchor)) { throw 'anchor not found' }
    $nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $extra = ($lines | ForEach-Object { "    $_" }) -join $nl
    [IO.File]::WriteAllText($launcher, $text.Replace($anchor, $anchor + $nl + $extra))
}

switch ($Step) {
    { $_ -in 'X', 'G', 'M', 'ME' } {
        $m = Get-Content "$E/lint-large-logs/manifest.json" -Raw | ConvertFrom-Json
        $w = $m.windows.$Step
        $lines = @($w.env.PSObject.Properties | ForEach-Object { "`$env:$($_.Name) = '$($_.Value)'" })
        if ($Step -in 'X', 'G') { $lines += "`$env:LOCAL_DELEGATE_FALLBACK_LONG = 'none'" }
        if ($Step -eq 'X') { $lines += "`$env:LOCAL_DELEGATE_DUMP_CHUNK_NOTES = 'D:\Projects\ld-wt-biglog\.sdd\changes\english-names-bilingual-output\evidence\lint-large-logs\runs\$Tag\notes'" }
        $os = Get-CimInstance Win32_OperatingSystem
        $freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        "free RAM before window $Step [$Tag]: $freeGb GB of $([math]::Round($os.TotalVisibleMemorySize / 1MB, 1))"
        if ($freeGb -lt 4) { throw "less than 4 GB of RAM free ($freeGb GB): not measuring" }
        Stop-Daemon
        Set-LauncherEnv $lines
        Start-Daemon
        $out = local-delegate test-window start --label ("$($w.label) [$Tag x$Repeat]")
        $out
        $id = ([regex]::Match(($out -join ' '), 'w-\d{8}T\d{6}Z')).Value
        try {
            uv run python "$E/lint-large-logs/run_live.py" --window $Step --manifest "$E/lint-large-logs/manifest.json" --answers-dir "$E/lint-large-logs/runs/$Tag" --repeat $Repeat
        } finally {
            if ($id) { local-delegate test-window stop $id } else { local-delegate test-window stop }
        }
    }
    'stop' { Stop-Daemon }
    'restore' {
        Stop-Daemon
        Copy-Item $backup $launcher -Force
        $h = (Get-FileHash $launcher -Algorithm SHA256).Hash.ToLower()
        "launcher sha256 $h match=$($h -eq $expected)"
        Start-Daemon
    }
}
