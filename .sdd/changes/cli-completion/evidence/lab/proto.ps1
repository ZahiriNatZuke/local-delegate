# local-delegate completion (static, generated). Compatible with Windows PowerShell 5.1 and pwsh 7.
Register-ArgumentCompleter -Native -CommandName @("local-delegate", "local-delegate.exe", "local-delegate-mcp", "local-delegate-mcp.exe") -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
$__ldSubs = @{
    "" = @("install", "backend-params", "completion")
    "install" = @()
    "backend-params" = @("set", "show", "reset")
    "backend-params set" = @()
    "backend-params show" = @()
    "backend-params reset" = @()
    "completion" = @()
}
$__ldOpts = @{
    "" = @("--help", "--version")
    "install" = @("--mcp-mode", "--lang", "--agents", "--config", "--help")
    "backend-params" = @("--help")
    "backend-params set" = @("--role", "--param", "--help")
    "backend-params show" = @("--json", "--help")
    "backend-params reset" = @("--help")
    "completion" = @("--help")
}
# option -> fixed values; @() = takes a free value (fall back to file completion)
$__ldValues = @{
    "install --mcp-mode" = @("stdio", "http")
    "install --lang" = @("es", "en")
    "install --config" = @()
    "backend-params set --role" = @("mechanical", "long", "code", "vision")
    "backend-params set --param" = @("temperature", "top_p")
}
$__ldPositional = @{
    "completion" = @("powershell", "zsh", "bash")
}
$__ldHelp = @{
    "|install" = "Instala la integraci$([char]0x00F3)n"
    "|backend-params" = "Par$([char]0x00E1)metros por rol"
    "|completion" = "Script de autocompletado"
    "|--help" = "Muestra la ayuda"
    "|--version" = "Muestra la versi$([char]0x00F3)n"
    "install|--mcp-mode" = "Modo del MCP"
    "install|--lang" = "Idioma"
    "install|--agents" = "Instala agentes"
    "install|--config" = "Ruta de configuraci$([char]0x00F3)n"
    "install|--help" = "Muestra la ayuda"
    "backend-params|set" = "Fija un par$([char]0x00E1)metro"
    "backend-params|show" = "Muestra los par$([char]0x00E1)metros"
    "backend-params|reset" = "Restablece"
    "backend-params|--help" = "Muestra la ayuda"
    "backend-params set|--role" = "Rol"
    "backend-params set|--param" = "Par$([char]0x00E1)metro"
    "backend-params set|--help" = "Muestra la ayuda"
    "backend-params show|--json" = "Salida JSON"
    "backend-params show|--help" = "Muestra la ayuda"
    "backend-params reset|--help" = "Muestra la ayuda"
    "completion|--help" = "Muestra la ayuda"
}

    $path = ''
    $expectValue = $null
    $elements = $commandAst.CommandElements
    for ($i = 1; $i -lt $elements.Count; $i++) {
        $el = $elements[$i]
        # only words fully before the cursor; the one under the cursor is $wordToComplete
        if ($el.Extent.EndOffset -ge $cursorPosition) { break }
        if ($el -is [System.Management.Automation.Language.StringConstantExpressionAst]) { $w = $el.Value } else { $w = $el.Extent.Text }
        if ($expectValue) { $expectValue = $null; continue }
        if ($w.StartsWith('-')) {
            if ($w.Contains('=')) { continue }
            $key = ($path + ' ' + $w).Trim()
            if ($__ldValues.ContainsKey($key)) { $expectValue = $key }
            continue
        }
        if ($__ldSubs.ContainsKey($path) -and ($__ldSubs[$path] -ccontains $w)) {
            $path = ($path + ' ' + $w).Trim()
        }
    }
    $prefix = ''
    $current = $wordToComplete
    $candidates = @()
    $kind = [System.Management.Automation.CompletionResultType]::ParameterValue
    if ($expectValue) {
        $candidates = $__ldValues[$expectValue]
    } elseif ($current -match '^(--[^=]+)=(.*)$') {
        $key = ($path + ' ' + $Matches[1]).Trim()
        if ($__ldValues.ContainsKey($key)) { $candidates = $__ldValues[$key]; $prefix = $Matches[1] + '='; $current = $Matches[2] }
    } elseif ($current.StartsWith('-')) {
        $candidates = $__ldOpts[$path]
        $kind = [System.Management.Automation.CompletionResultType]::ParameterName
    } else {
        $candidates = @($__ldSubs[$path]) + @($__ldPositional[$path])
    }
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        if ($c.StartsWith($current, [System.StringComparison]::OrdinalIgnoreCase)) {
            $tip = $__ldHelp[$path + '|' + $c]
            if (-not $tip) { $tip = $c }
            New-Object System.Management.Automation.CompletionResult ($prefix + $c), $c, $kind, $tip
        }
    }
}

