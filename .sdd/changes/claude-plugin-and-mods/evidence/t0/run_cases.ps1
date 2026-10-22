# T0 (claude-plugin-and-mods): run the B-1 case plugins with `claude -p` and record the raw outcome.
# Run ONLY from PowerShell (Git Bash rewrites paths), inside a local-delegate test window.
#
#   .\run_cases.ps1 -T0 <t0_dir> -Exe <claude.exe> -Event ups|read -ConfigDir <dir> [-Filter <regex>] [-Tag <name>]
#
# -ConfigDir: CLAUDE_CONFIG_DIR for the child (always pass an isolated one). `read` needs no login:
#   the t0-driver mod (make_driver.py) fires the Read with $.tool.call from the `/t0read` command.
# Output: <t0>/runs/<tag>/<plugin>.json (raw stdout/stderr) and a summary line per case.
param(
  [Parameter(Mandatory)] [string] $T0,
  [Parameter(Mandatory)] [string] $Exe,
  [Parameter(Mandatory)] [ValidateSet('ups', 'read')] [string] $Event,
  [string] $Filter = '.',
  [Parameter(Mandatory)] [string] $ConfigDir,
  [string] $Tag = 'run'
)
$ErrorActionPreference = 'Continue'
$env:DISABLE_AUTOUPDATER = '1'
$env:CLAUDE_CONFIG_DIR = $ConfigDir
$work = Join-Path $T0 'work'
New-Item -ItemType Directory -Force $work | Out-Null
# Sentinel file: if its content shows up in a tool_result, the Read went through.
Set-Content -Path (Join-Path $work 'sentinel.txt') -Value 'T0-SENTINEL-7f3a' -NoNewline
$outDir = Join-Path $T0 "runs\$Tag"
New-Item -ItemType Directory -Force $outDir | Out-Null
$cases = Get-Content (Join-Path $T0 'cases.json') -Raw | ConvertFrom-Json |
  Where-Object { $_.event -eq $Event -and $_.case -match $Filter }
Push-Location $work
try {
  foreach ($c in $cases) {
    $name = Split-Path $c.plugin -Leaf
    $markerDir = Join-Path $T0 'markers'
    Remove-Item -Recurse -Force $markerDir -ErrorAction SilentlyContinue
    $common = @('--max-turns', '1', '--plugin-dir', $c.plugin, '--strict-mcp-config',
      '--debug-file', (Join-Path $outDir "$name.debug.log"))
    if ($Event -eq 'ups') {
      $prompt = 'Reply with the single word OK.'
      $args2 = @('-p', $prompt, '--output-format', 'json') + $common
    } else {
      # No model turn: the t0-driver mod fires the Read through $.tool.call (see make_driver.py).
      $args2 = @('-p', '/t0read', '--plugin-dir', (Join-Path $T0 'plugins\t0-driver')) + $common
    }
    $raw = & $Exe @args2 2>&1 | Out-String
    $rc = $LASTEXITCODE
    Set-Content -Path (Join-Path $outDir "$name.out.txt") -Value $raw
    $marker = if (Test-Path $markerDir) { (Get-ChildItem $markerDir -Name) -join ',' } else { '' }
    if ($Event -eq 'ups') {
      $j = $null; try { $j = ($raw -split "`n" | Where-Object { $_ -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json } catch {}
      # Blocked prompt: no turn and no API attempt. Passed prompt: reaches the API (a reply when
      # logged in, `api_error` / "Not logged in" when not).
      $blocked = $j -and $j.num_turns -eq 0 -and $j.terminal_reason -ne 'api_error'
      $obs = if ($blocked) { 'block' } else { 'pass' }
      $detail = if ($j) { "turns=$($j.num_turns) term=$($j.terminal_reason) err=$($j.is_error)" } else { 'no-json' }
    } else {
      $sawSentinel = $raw -match 'T0-SENTINEL-7f3a'
      $driverRan = $raw -match 'T0READ'
      $obs = if (-not $driverRan) { 'no-driver' } elseif ($sawSentinel) { 'pass' } else { 'block' }
      $msg = ($raw -replace '\s+', ' ')
      $i = $msg.IndexOf('T0READ'); if ($i -ge 0) { $msg = $msg.Substring($i, [Math]::Min(140, $msg.Length - $i)) }
      $detail = "driver=$driverRan sentinel=$sawSentinel :: $msg"
    }
    $verdict = if ($obs -eq $c.expected) { 'OK' } else { 'FAIL' }
    '{0,-22} via={1,-8} expected={2,-5} observed={3,-12} {4} rc={5} marker=[{6}] {7}' -f $name, $c.via, $c.expected, $obs, $verdict, $rc, $marker, $detail
  }
} finally { Pop-Location }
