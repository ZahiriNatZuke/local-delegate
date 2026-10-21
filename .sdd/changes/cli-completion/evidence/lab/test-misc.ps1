param([string]$Script)
. $Script
"PS " + $PSVersionTable.PSVersion
$t = (TabExpansion2 'local-delegate ins' 18).CompletionMatches[0].ToolTip
"tooltip codepoints: " + (($t.ToCharArray() | Select-Object -Last 3 | ForEach-Object { '{0:X4}' -f [int]$_ }) -join ' ')
"free value (dir with files): " + ((TabExpansion2 'local-delegate install --config pro' 35).CompletionMatches.CompletionText -join ',')
"unknown sub falls to files?: " + ((TabExpansion2 'local-delegate completion powershell pro' 40).CompletionMatches.CompletionText -join ',')
