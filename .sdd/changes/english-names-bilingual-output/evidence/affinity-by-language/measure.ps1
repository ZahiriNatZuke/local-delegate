param(
    [ValidateSet('run','restore','stop')][string]$Step,
    [ValidateSet('gemma3-4b','qwen35-2b','gemma4-26b-a4b','qwen36-35b-a3b')][string]$Model = 'gemma3-4b',
    [ValidateSet('es','en')][string]$Lang = 'es',
    [int]$Repeat = 3
)
# affinity-by-language (2026-10-18): copy of B2-affinity's b2affinity-measure.ps1 for the worktree,
# results in reevaluation-lint-counts/ and logs here. Original note:
# B2-affinity (2026-10-18): copy of the b2e-measure.ps1 pattern. One window per (model, language):
# the launcher gets LOCAL_DELEGATE_MODEL_MECHANICAL=<model>, LOCAL_DELEGATE_FALLBACK=0 and, for en,
# LOCAL_DELEGATE_LANG=en; the daemon restarts, a test window opens (its id is kept and closed by
# id) and run_affinity_live.py measures. 'restore' puts back the launcher from launcher-backup.ps1
# and checks its sha256. The install step is NOT here: it runs from the Bash tool (pesado.sh).
$ErrorActionPreference = 'Stop'
$launcher = 'D:\Projects\llms\llama-swap\start-local-delegate-secure.ps1'
$backup = 'C:\Users\Yohan\.claude\relevos\launcher-backup.ps1'
$expected = 'c96f022aeb1b2570fc273419203f2f870d7a13022c373e35f7ae6af7ae69f69a'
$E = '.sdd/changes/english-names-bilingual-output/evidence'
Set-Location 'D:\Projects\ld-wt-lint'

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
    'run' {
        $lines = @(
            "`$env:LOCAL_DELEGATE_MODEL_MECHANICAL = '$Model'",
            "`$env:LOCAL_DELEGATE_FALLBACK = '0'"
        )
        if ($Lang -eq 'en') { $lines += "`$env:LOCAL_DELEGATE_LANG = 'en'" }
        $os = Get-CimInstance Win32_OperatingSystem
        $freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        "free RAM before window $Lang/$Model : $freeGb GB of $([math]::Round($os.TotalVisibleMemorySize / 1MB, 1))"
        if ($freeGb -lt 4) { throw "less than 4 GB of RAM free ($freeGb GB): not measuring" }
        Stop-Daemon
        Set-LauncherEnv $lines
        Start-Daemon
        $out = local-delegate test-window start --label "affinity-by-language lint $Lang/$Model x$Repeat"
        $out
        $id = ([regex]::Match(($out -join "`n"), 'w-\d{8}T\d{6}Z')).Value
        if (-not $id) { throw 'no test window id' }
        try {
            $log = "$E/affinity-by-language/logs/$Lang-$Model.log"
            New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
            $p = Start-Process uv -ArgumentList @('run', 'python', "$E/B2-affinity/run_affinity_live.py", '--model', $Model, '--lang', $Lang, '--repeat', $Repeat, '--results', 'benchmarks/afinidad-2026-10/reevaluation-lint-counts/results') `
                -NoNewWindow -PassThru -RedirectStandardOutput $log -RedirectStandardError "$log.err"
            $minFree = 99.0
            while (-not $p.HasExited) {
                Start-Sleep -Seconds 2
                $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)
                if ($free -lt $minFree) { $minFree = $free }
                if ($free -lt 1.5) {
                    taskkill /T /F /PID $p.Id | Out-Null
                    throw "free RAM fell to $free GB during the window: stopped"
                }
            }
            $p.WaitForExit()
            Get-Content $log
            Get-Content "$log.err" -ErrorAction SilentlyContinue | Select-Object -Last 15
            "exit=$($p.ExitCode) min free RAM during window: $minFree GB"
        } finally {
            local-delegate test-window stop $id
            $os = Get-CimInstance Win32_OperatingSystem
            "free RAM after window: $([math]::Round($os.FreePhysicalMemory / 1MB, 1)) GB"
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
