function global:TabExpansion($line, $lastWord) { 'LEGACY-HIT' }
"PS " + $PSVersionTable.PSVersion.Major + " legacy TabExpansion (pip style): [" + ((TabExpansion2 'pip ins' 7).CompletionMatches.CompletionText -join ',') + "]"
