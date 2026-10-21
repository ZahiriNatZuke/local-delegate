Register-ArgumentCompleter -Native -CommandName 'zz' -ScriptBlock { param($w,$a,$c) $els = ($a.CommandElements | ForEach-Object { $_.GetType().Name + ':' + $_.Extent.Text }) -join ' '; [System.Management.Automation.CompletionResult]::new("W=[$w]", "x", 'ParameterValue', "els=$els") }
"PS " + $PSVersionTable.PSVersion.Major
foreach ($l in 'zz a --', 'zz a --r', 'zz a -', 'zz a --role=', 'zz a --role=v') { $r = (TabExpansion2 $l $l.Length).CompletionMatches; "{0,-14} -> {1} {2}" -f $l, ($r.CompletionText -join ','), ($r.ToolTip -join ',') }
