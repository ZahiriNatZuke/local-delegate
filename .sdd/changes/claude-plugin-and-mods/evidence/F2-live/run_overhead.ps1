# F2-live: Bash call overhead with the plugin vs without it. Run from PowerShell, inside a test window.
#   .\run_overhead.ps1 -Repeat 3 -Calls 10
#   -Arms P,N (default) | A,N  (A = plugin with the read layer on: LD_HOOK_READ_ENABLED=1)
param([int] $Repeat = 3, [int] $Calls = 10, [string[]] $Arms = @('P', 'N'), [string] $Sub = 'overhead')
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$plugin = 'D:\Projects\ld-wt-f2-live\src\local_delegate\resources\claude-plugin\local-delegate'
$env:DISABLE_AUTOUPDATER = '1'
New-Item -ItemType Directory -Force "$S\cfg-n", "$S\runs\$Sub" | Out-Null
if (-not (Test-Path "$S\cfg-n\settings.json")) { Set-Content "$S\cfg-n\settings.json" '{}' }
Push-Location "$S\work"
try {
  foreach ($r in 1..$Repeat) {
    foreach ($k in 1..2) {
      foreach ($arm in $Arms) {
        $tag = "r$r-$arm$k"
        $common = @('-p', "/f2bash $Calls", '--max-turns', '1', '--strict-mcp-config', '--mcp-config', "$S\mcp.json",
          '--allowedTools', 'Bash', '--debug-file', "$S\runs\$Sub\$tag.debug.log")
        Remove-Item Env:LD_HOOK_READ_ENABLED -ErrorAction SilentlyContinue
        if ($arm -eq 'A') { $env:LD_HOOK_READ_ENABLED = '1' }
        if ($arm -ne 'N') {
          $env:CLAUDE_CONFIG_DIR = "$S\cfg-a"
          $argv = $common + @('--plugin-dir', $plugin, '--plugin-dir', "$S\drv")
        } else {
          $env:CLAUDE_CONFIG_DIR = "$S\cfg-n"
          $argv = $common + @('--plugin-dir', "$S\drv")
        }
        $out = & claude @argv 2>&1 | Out-String
        Set-Content -Path "$S\runs\$Sub\$tag.out.txt" -Value $out
        $line = ($out -split "`n" | Where-Object { $_ -match 'F2BASH' } | Select-Object -First 1)
        '{0} rc={1} {2}' -f $tag, $LASTEXITCODE, ($line -replace '"last".*', '')
      }
    }
  }
} finally { Pop-Location; Remove-Item Env:CLAUDE_CONFIG_DIR, Env:LD_HOOK_READ_ENABLED -ErrorAction SilentlyContinue }
