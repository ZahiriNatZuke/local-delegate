@@HEADER@@
# Static script: loading it or pressing Tab runs nothing else. Windows PowerShell 5.1 and pwsh 7.
Register-ArgumentCompleter -Native -CommandName @("local-delegate", "local-delegate-mcp") -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    # Tables live inside the script block: loading the script leaves no variables in the session.
    # Case-sensitive tables, like argparse. Keys: "<path>" and "<path>|<name>", where <path> is
    # the subcommand path joined with spaces ("" is the root).
    $subs = New-Object System.Collections.Hashtable      # path -> visible subcommands
    $opts = New-Object System.Collections.Hashtable      # path -> option strings
    $arity = New-Object System.Collections.Hashtable     # path|option -> "required" or "optional"
    $values = New-Object System.Collections.Hashtable    # path|option or path|#index -> fixed values
    $help = New-Object System.Collections.Hashtable      # path|name -> description
@@TABLES@@

    $path = ''
    $positional = 0
    $expect = $null
    $elements = $commandAst.CommandElements
    for ($i = 1; $i -lt $elements.Count; $i++) {
        $element = $elements[$i]
        # Only the words before the cursor; the one under the cursor is $wordToComplete.
        if ($element.Extent.EndOffset -ge $cursorPosition) { break }
        if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
            $word = $element.Value
        } else {
            $word = $element.Extent.Text
        }
        if ($null -ne $expect) {
            $optional = $arity[$expect] -ceq 'optional'
            $expect = $null
            if (-not ($optional -and $word.StartsWith('-'))) { continue }
        }
        if ($word.StartsWith('-')) {
            if ($word.Contains('=')) { continue }
            $key = $path + '|' + $word
            if ($arity.ContainsKey($key)) { $expect = $key }
            continue
        }
        if ($subs.ContainsKey($path) -and ($subs[$path] -ccontains $word)) {
            $path = ($path + ' ' + $word).Trim()
            $positional = 0
            continue
        }
        $positional++
    }

    $prefix = ''
    $current = $wordToComplete
    $candidates = @()
    $kind = [System.Management.Automation.CompletionResultType]::ParameterValue
    if (($null -ne $expect) -and -not (($arity[$expect] -ceq 'optional') -and $current.StartsWith('-'))) {
        $candidates = @($values[$expect])
    } elseif ($current -match '^(--[^=]+)=(.*)$') {
        $key = $path + '|' + $Matches[1]
        if ($arity.ContainsKey($key)) {
            $candidates = @($values[$key])
            $prefix = $Matches[1] + '='
            $current = $Matches[2]
        }
    } elseif ($current.StartsWith('-')) {
        $candidates = @($opts[$path])
        $kind = [System.Management.Automation.CompletionResultType]::ParameterName
    } else {
        $candidates = @($subs[$path]) + @($values[$path + '|#' + $positional])
    }
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        if ($candidate.StartsWith($current, [System.StringComparison]::OrdinalIgnoreCase)) {
            $tip = $help[$path + '|' + $candidate]
            if (-not $tip) { $tip = $candidate }
            New-Object System.Management.Automation.CompletionResult ($prefix + $candidate), $candidate, $kind, $tip
        }
    }
}
