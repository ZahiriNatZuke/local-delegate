# F2-live, REQ-016: pieces off by userConfig, and a register.js that throws at load. PowerShell only.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$plugin = 'D:\Projects\ld-wt-f2-live\src\local_delegate\resources\claude-plugin\local-delegate'
$tiny = "$S\work\tiny.txt"
$env:DISABLE_AUTOUPDATER = '1'
New-Item -ItemType Directory -Force "$S\runs\req016" | Out-Null
$cases = [ordered]@{ 'off' = @("$S\cfg-off", $plugin); 'throw' = @("$S\cfg-a", "$S\plugin-throw") }
Push-Location "$S\work"
try {
  foreach ($name in $cases.Keys) {
    $env:CLAUDE_CONFIG_DIR = $cases[$name][0]
    $base = @('--max-turns', '1', '--strict-mcp-config', '--mcp-config', "$S\mcp.json",
      '--allowedTools', 'mcp__local-delegate__local_summarize', '--plugin-dir', $cases[$name][1], '--plugin-dir', "$S\drv")
    $o1 = & claude -p "/f2mcp $tiny" --output-format json @base --debug-file "$S\runs\req016\$name-mcp.debug.log" 2>&1 | Out-String
    Set-Content "$S\runs\req016\$name-mcp.out.txt" $o1
    $o2 = & claude -p '/local-summarize tiny.txt' --output-format json @base --debug-file "$S\runs\req016\$name-cmd.debug.log" 2>&1 | Out-String
    Set-Content "$S\runs\req016\$name-cmd.out.txt" $o2
    "== $name"
  }
} finally { Pop-Location; Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue }
