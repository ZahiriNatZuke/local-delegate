# T0 (claude-plugin-and-mods): plugin CLI lifecycle and engine checks in an isolated CLAUDE_CONFIG_DIR.
# Run ONLY from PowerShell, inside a local-delegate test window. Needs make_motor.py run first.
#   .\run_cli.ps1 -T0 <t0_dir> -Exe <claude.exe> -Tag <name>
param(
  [Parameter(Mandatory)] [string] $T0,
  [Parameter(Mandatory)] [string] $Exe,
  [Parameter(Mandatory)] [string] $Tag
)
$ErrorActionPreference = 'Continue'
$cfg = Join-Path $T0 "cfg-$Tag"
Remove-Item -Recurse -Force $cfg -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $cfg | Out-Null
$env:CLAUDE_CONFIG_DIR = $cfg
$env:DISABLE_AUTOUPDATER = '1'
$out = Join-Path $T0 "runs\$Tag"
New-Item -ItemType Directory -Force $out | Out-Null
$py = (Join-Path $T0 'env039\Scripts\python.exe') -replace '\\', '/'
$mkt = Join-Path $T0 'mkt'
$markers = Join-Path $T0 'markers'
$work = Join-Path $T0 'work'
New-Item -ItemType Directory -Force $work | Out-Null

function Step([string] $name, [string[]] $argv) {
  $raw = & $Exe @argv 2>&1 | Out-String
  $rc = $LASTEXITCODE
  Set-Content -Path (Join-Path $out "$name.txt") -Value $raw
  $short = ($raw -replace '\s+', ' ')
  if ($short.Length -gt 260) { $short = $short.Substring(0, 260) + '...' }
  '{0,-22} rc={1} {2}' -f $name, $rc, $short
}

& (Join-Path $T0 'env039\Scripts\python.exe') -I (Join-Path $PSScriptRoot 'make_motor.py') $T0 0.0.1 | Out-Null
Remove-Item -Recurse -Force $markers -ErrorAction SilentlyContinue
Step 'validate-mkt' @('plugin', 'validate', $mkt, '--strict', '--json')
Step 'validate-motor' @('plugin', 'validate', (Join-Path $mkt 'plugins\t0-motor'), '--strict', '--json')
Step 'validate-dyn' @('plugin', 'validate', (Join-Path $T0 'plugins\t0-motor-dyn'), '--strict', '--json')
Step 'validate-throw' @('plugin', 'validate', (Join-Path $T0 'plugins\t0-motor-throw'), '--strict', '--json')
Step 'mkt-add' @('plugin', 'marketplace', 'add', $mkt)
Step 'install' @('plugin', 'install', 't0-motor@t0-mkt', '--scope', 'user', '--config', "ld_bin=$py", '--json')
Step 'list-1' @('plugin', 'list', '--json')
Push-Location $work
try {
  Step 'p-report' @('-p', '/t0report', '--max-turns', '1', '--strict-mcp-config', '--debug-file', (Join-Path $out 'p-report.debug.log'))
  Step 'p-dyn' @('-p', '/t0report', '--max-turns', '1', '--strict-mcp-config', '--plugin-dir', (Join-Path $T0 'plugins\t0-motor-dyn'), '--debug-file', (Join-Path $out 'p-dyn.debug.log'))
  Step 'p-throw' @('-p', 'Reply with the single word OK.', '--max-turns', '1', '--strict-mcp-config', '--plugin-dir', (Join-Path $T0 'plugins\t0-motor-throw'), '--debug-file', (Join-Path $out 'p-throw.debug.log'))
} finally { Pop-Location }
'markers: ' + ((Get-ChildItem $markers -Name -ErrorAction SilentlyContinue) -join ',')
'plugin data: ' + ((Get-ChildItem (Join-Path $cfg 'plugins\data') -Recurse -Name -ErrorAction SilentlyContinue) -join ',')
& (Join-Path $T0 'env039\Scripts\python.exe') -I (Join-Path $PSScriptRoot 'make_motor.py') $T0 0.0.2 | Out-Null
Step 'update' @('plugin', 'update', 't0-motor@t0-mkt')
Step 'list-2' @('plugin', 'list', '--json')
Step 'uninstall' @('plugin', 'uninstall', 't0-motor@t0-mkt')
Step 'list-3' @('plugin', 'list', '--json')
'plugins dir: ' + ((Get-ChildItem (Join-Path $cfg 'plugins') -Name -ErrorAction SilentlyContinue) -join ',')
