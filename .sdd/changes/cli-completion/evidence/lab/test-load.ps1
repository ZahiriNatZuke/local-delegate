"PS " + $PSVersionTable.PSVersion + "  policy=" + (Get-ExecutionPolicy) + "  OutputEncoding=" + [Console]::OutputEncoding.WebName
function Get-TipCodes { $t = (TabExpansion2 'local-delegate ins' 18).CompletionMatches[0].ToolTip; (($t.ToCharArray() | Select-Object -Last 3 | ForEach-Object { '{0:X4}' -f [int]$_ }) -join ' ') }
. ./proto-bom.ps1
"BOM dot-source: " + (Get-TipCodes)
$sw = [Diagnostics.Stopwatch]::StartNew()
py -I gen.py powershell | Out-String | Invoke-Expression
"iex from process (" + $sw.ElapsedMilliseconds + " ms): " + (Get-TipCodes)
$sw = [Diagnostics.Stopwatch]::StartNew()
$null = & local-delegate --version
"local-delegate --version: " + $sw.ElapsedMilliseconds + " ms"
