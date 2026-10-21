param([string]$Script)
$sw = [Diagnostics.Stopwatch]::StartNew()
. $Script
"load ms: " + $sw.ElapsedMilliseconds
function T([string]$line, [int]$col = -1) {
    if ($col -lt 0) { $col = $line.Length }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = TabExpansion2 -inputScript $line -cursorColumn $col
    $ms = $sw.ElapsedMilliseconds
    $m = @($r.CompletionMatches | ForEach-Object { $_.CompletionText + '{' + $_.ToolTip + '}' })
    "[{0}] col={1} ({2} ms) -> {3}" -f $line, $col, $ms, ($m -join ' | ')
}
T 'local-delegate '
T 'local-delegate ba'
T 'local-delegate backend-params '
T 'local-delegate backend-params set --'
T 'local-delegate backend-params set --role '
T 'local-delegate backend-params set --role c'
T 'local-delegate backend-params set --role=v'
T 'local-delegate install --mcp-mode h'
T 'local-delegate install --mcp-mode http --lang '
T 'local-delegate completion '
T 'local-delegate.exe backend-params s'
T 'local-delegate-mcp ins'
T 'local-delegate backend-params set --role code' 29
T 'local-delegate BACKEND-PARAMS '
T 'local-delegate --version backend-params '
T 'local-delegate install --config '
T 'C:\x\local-delegate.exe ins'
T '& "C:\x y\local-delegate.exe" ins'
T 'ld ins'
