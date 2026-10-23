# F4-live: Bash call overhead of the read mod (read_mod_enabled true vs false), same plugin, real
# config (no CLAUDE_CONFIG_DIR), options passed per arm with --settings. Run inside a test window.
#   .\run_overhead.ps1 -Repeat 3            (C = con mod, S = sin mod; interleaved C,S,C,S)
param([int] $Repeat = 3, [string[]] $Arms = @('C', 'S'), [string] $Sub = 'overhead', [int] $Pairs = 2, [string] $Drv = 'drv', [string] $Cmd = '/f4bash')
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$env:DISABLE_AUTOUPDATER = '1'
Remove-Item Env:CLAUDE_CONFIG_DIR, Env:LD_HOOK_READ_ENABLED -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$S\runs\$Sub" | Out-Null
Push-Location 'D:\Projects\local-delegate'
try {
  foreach ($r in 1..$Repeat) {
    foreach ($k in 1..$Pairs) {
      foreach ($arm in $Arms) {
        $tag = "r$r-$arm$k"
        $set = if ($arm -eq 'C') { "$S\settings-con.json" } else { "$S\settings-sin.json" }
        $argv = @('-p', $Cmd, '--max-turns', '1', '--strict-mcp-config', '--settings', $set,
          '--plugin-dir', "$S\$Drv", '--allowedTools', 'Bash', '--debug-file', "$S\runs\$Sub\$tag.debug.log")
        $out = $null | & claude @argv 2>&1 | Out-String
        Set-Content -Path "$S\runs\$Sub\$tag.out.txt" -Value $out
        $line = ($out -split "`n" | Where-Object { $_ -match 'F4BASH' } | Select-Object -First 1)
        '{0} rc={1} {2}' -f $tag, $LASTEXITCODE, ($line -replace '"last".*', '')
      }
    }
  }
} finally { Pop-Location }
