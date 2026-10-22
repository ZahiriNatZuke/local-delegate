# F2-live, REQ-003: the prompt and a Bash call with ld_bin broken. PowerShell only, inside a test window.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$plugin = 'D:\Projects\ld-wt-f2-live\src\local_delegate\resources\claude-plugin\local-delegate'
$tool = Join-Path (& uv tool dir) 'local-delegate-mcp\Scripts'
$cases = [ordered]@{
  'good'     = 'D:/Projects/ld-wt-f2-live/.venv/Scripts/python.exe'
  'missing'  = 'D:/does-not-exist/python.exe'
  'py039'    = ($tool + '\python.exe') -replace '\\', '/'
  'ctl-exe039' = ($tool + '\local-delegate.exe') -replace '\\', '/'   # positive control: argparse exits 2
}
$env:DISABLE_AUTOUPDATER = '1'
New-Item -ItemType Directory -Force "$S\runs\ldbin" | Out-Null
Push-Location "$S\work"
try {
  foreach ($name in $cases.Keys) {
    $cfg = "$S\cfg-ldbin-$name"
    New-Item -ItemType Directory -Force $cfg | Out-Null
    $settings = @{ pluginConfigs = @{ 'local-delegate@inline' = @{ options = @{ ld_bin = $cases[$name]; language = 'es' } } } }
    $settings | ConvertTo-Json -Depth 6 | Set-Content "$cfg\settings.json"
    $env:CLAUDE_CONFIG_DIR = $cfg
    $base = @('--max-turns', '1', '--strict-mcp-config', '--mcp-config', "$S\mcp.json", '--allowedTools', 'Bash',
      '--plugin-dir', $plugin, '--plugin-dir', "$S\drv")
    $o1 = & claude -p 'Reply with the single word OK.' --output-format json @base --debug-file "$S\runs\ldbin\$name-prompt.debug.log" 2>&1 | Out-String
    Set-Content "$S\runs\ldbin\$name-prompt.out.txt" $o1
    $o2 = & claude -p '/f2bash 1' @base --debug-file "$S\runs\ldbin\$name-bash.debug.log" 2>&1 | Out-String
    Set-Content "$S\runs\ldbin\$name-bash.out.txt" $o2
    $short1 = ($o1 -replace '\s+', ' '); if ($short1.Length -gt 220) { $short1 = $short1.Substring(0, 220) }
    $short2 = ($o2 -replace '\s+', ' '); if ($short2.Length -gt 160) { $short2 = $short2.Substring(0, 160) }
    "{0}`n  prompt: {1}`n  bash:   {2}" -f $name, $short1, $short2
  }
} finally { Pop-Location; Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue }
