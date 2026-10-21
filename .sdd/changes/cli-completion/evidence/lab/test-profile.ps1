$env:LD_LAB_APPDATA = (Resolve-Path ./fakeappdata).Path
. ./temp_profile.ps1
"PS " + $PSVersionTable.PSVersion.Major
"vars leaked: " + (@(Get-Variable __ld* -ErrorAction SilentlyContinue).Count)
$r = (TabExpansion2 'local-delegate ins' 18).CompletionMatches[0]
"ins -> " + $r.CompletionText + " tip codes: " + (($r.ToolTip.ToCharArray() | Select-Object -Last 3 | ForEach-Object { '{0:X4}' -f [int]$_ }) -join ' ')
"BACKEND-PARAMS (case) -> " + ((TabExpansion2 'local-delegate BACKEND-PARAMS ' 30).CompletionMatches.CompletionText -join ',')
"role= -> " + ((TabExpansion2 'local-delegate backend-params set --role=' 41).CompletionMatches.CompletionText -join ',')
