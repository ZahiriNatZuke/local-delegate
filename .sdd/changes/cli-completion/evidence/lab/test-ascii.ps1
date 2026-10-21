py -I ascii_emit.py | Out-String | Invoke-Expression
"PS " + $PSVersionTable.PSVersion.Major + ": " + $__t + " | codes: " + (($__t.ToCharArray() | ForEach-Object { '{0:X4}' -f [int]$_ }) -join ' ')
