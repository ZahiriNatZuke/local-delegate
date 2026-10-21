Register-ArgumentCompleter -Native -CommandName 'local-delegate' -ScriptBlock { param($w,$a,$c) [System.Management.Automation.CompletionResult]::new('HIT','HIT','ParameterValue','t') }
"PS " + $PSVersionTable.PSVersion
"only 'local-delegate' registered, typed .exe: " + ((TabExpansion2 'local-delegate.exe x' 20).CompletionMatches.CompletionText -join ',')
"typed full path no ext: " + ((TabExpansion2 'C:\Users\Yohan\.local\bin\local-delegate x' 42).CompletionMatches.CompletionText -join ',')
"typed .\local-delegate: " + ((TabExpansion2 '.\local-delegate x' 18).CompletionMatches.CompletionText -join ',')
