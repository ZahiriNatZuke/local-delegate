"""Prototype: emit static completion scripts (powershell/bash/zsh) from a static command tree.

Lab only (SDD cli-completion research). Stdlib only. Usage: python gen.py powershell|bash|zsh
"""

import sys

PROG = "local-delegate"
ALIASES = ["local-delegate", "local-delegate-mcp"]

# path (space-joined, "" = root) -> node
TREE = {
    "": {
        "subs": [
            ("install", "Instala la integración"),
            ("backend-params", "Parámetros por rol"),
            ("completion", "Script de autocompletado"),
        ],
        "opts": [("--help", "Muestra la ayuda"), ("--version", "Muestra la versión")],
    },
    "install": {
        "subs": [],
        "opts": [
            ("--mcp-mode", "Modo del MCP"),
            ("--lang", "Idioma"),
            ("--agents", "Instala agentes"),
            ("--config", "Ruta de configuración"),
            ("--help", "Muestra la ayuda"),
        ],
        "values": {"--mcp-mode": ["stdio", "http"], "--lang": ["es", "en"], "--config": None},
    },
    "backend-params": {
        "subs": [
            ("set", "Fija un parámetro"),
            ("show", "Muestra los parámetros"),
            ("reset", "Restablece"),
        ],
        "opts": [("--help", "Muestra la ayuda")],
    },
    "backend-params set": {
        "subs": [],
        "opts": [("--role", "Rol"), ("--param", "Parámetro"), ("--help", "Muestra la ayuda")],
        "values": {
            "--role": ["mechanical", "long", "code", "vision"],
            "--param": ["temperature", "top_p"],
        },
    },
    "backend-params show": {
        "subs": [],
        "opts": [("--json", "Salida JSON"), ("--help", "Muestra la ayuda")],
    },
    "backend-params reset": {"subs": [], "opts": [("--help", "Muestra la ayuda")]},
    "completion": {
        "subs": [],
        "opts": [("--help", "Muestra la ayuda")],
        "positional": ["powershell", "zsh", "bash"],
    },
}


def ps_str(s):
    """ASCII-only PowerShell literal: works BOM-less in 5.1 and through Invoke-Expression."""
    out = []
    for ch in s:
        if ch in '`"$':
            out.append("`" + ch)
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            b = ch.encode("utf-16-le")
            for k in range(0, len(b), 2):
                out.append(f"$([char]0x{int.from_bytes(b[k : k + 2], 'little'):04X})")
    return '"' + "".join(out) + '"'


def gen_powershell():
    L = [
        "# local-delegate completion (static, generated). Compatible with Windows PowerShell 5.1 and pwsh 7.",
        "Register-ArgumentCompleter -Native -CommandName @("
        + ", ".join(ps_str(n) for a in ALIASES for n in (a, a + ".exe"))
        + ") -ScriptBlock {",
        "    param($wordToComplete, $commandAst, $cursorPosition)",
    ]
    L.append("$__ldSubs = @{")
    for p, n in TREE.items():
        L.append(f"    {ps_str(p)} = @({', '.join(ps_str(s) for s, _ in n['subs'])})")
    L.append("}")
    L.append("$__ldOpts = @{")
    for p, n in TREE.items():
        L.append(f"    {ps_str(p)} = @({', '.join(ps_str(o) for o, _ in n['opts'])})")
    L.append("}")
    L.append("# option -> fixed values; @() = takes a free value (fall back to file completion)")
    L.append("$__ldValues = @{")
    for p, n in TREE.items():
        for o, vals in n.get("values", {}).items():
            L.append(
                f"    {ps_str((p + ' ' + o).strip())} = @({', '.join(ps_str(v) for v in (vals or []))})"
            )
    L.append("}")
    L.append("$__ldPositional = @{")
    for p, n in TREE.items():
        if n.get("positional"):
            L.append(f"    {ps_str(p)} = @({', '.join(ps_str(v) for v in n['positional'])})")
    L.append("}")
    L.append("$__ldHelp = @{")
    for p, n in TREE.items():
        for w, d in n["subs"] + n["opts"]:
            L.append(f"    {ps_str(p + '|' + w)} = {ps_str(d)}")
    L.append("}")
    L.append(r"""
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
""")
    return "\n".join(L) + "\n"


def sh_words(ws):
    return " ".join(ws)


def gen_bash():
    # bash 3.2 compatible: no associative arrays, no compopt, no mapfile; case statements instead.
    L = [
        "# local-delegate completion (static, generated). bash >= 3.2.",
        "_local_delegate() {",
        "    local cur path i w expect",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        "    path=''; expect=''",
        "    COMPREPLY=()",
        "    i=1",
        "    while [ $i -lt $COMP_CWORD ]; do",
        '        w="${COMP_WORDS[i]}"',
        "        i=$((i+1))",
        "        # COMP_WORDBREAKS contains '=': '--opt=val' arrives as '--opt' '=' 'val'",
        "        if [ \"$w\" = '=' ]; then continue; fi",
        "        if [ -n \"$expect\" ]; then expect=''; continue; fi",
        '        case "$w" in',
        "            --*=*) continue ;;",
        "            -*)",
        '                case "$path|$w" in',
    ]
    for p, n in TREE.items():
        for o in n.get("values", {}):
            L.append(f"                    '{p}|{o}') expect=\"$w\" ;;")
    L += [
        "                esac",
        "                continue ;;",
        "        esac",
        '        case "$path|$w" in',
    ]
    for p, n in TREE.items():
        for s, _ in n["subs"]:
            L.append(f"            '{p}|{s}') path='{(p + ' ' + s).strip()}' ;;")
    L += [
        "        esac",
        "    done",
        "    local opt=''",
        '    if [ -n "$expect" ]; then opt="$expect"; [ "$cur" = \'=\' ] && cur=\'\'',
        '    else case "$cur" in --*=*) opt="${cur%%=*}"; cur="${cur#*=}" ;; esac',
        "    fi",
        '    if [ -n "$opt" ]; then',
        '        case "$path|$opt" in',
    ]
    for p, n in TREE.items():
        for o, vals in n.get("values", {}).items():
            if vals:
                L.append(
                    f"            '{p}|{o}') COMPREPLY=($(compgen -W '{sh_words(vals)}' -- \"$cur\")) ;;"
                )
            else:
                L.append(f"            '{p}|{o}') COMPREPLY=($(compgen -f -- \"$cur\")) ;;")
    L += [
        "        esac",
        "        return 0",
        "    fi",
        '    case "$cur" in',
        "        -*)",
        '            case "$path" in',
    ]
    for p, n in TREE.items():
        L.append(
            f"                '{p}') COMPREPLY=($(compgen -W '{sh_words(o for o, _ in n['opts'])}' -- \"$cur\")) ;;"
        )
    L += ["            esac ;;", "        *)", '            case "$path" in']
    for p, n in TREE.items():
        ws = [s for s, _ in n["subs"]] + list(n.get("positional", []))
        L.append(
            f"                '{p}') COMPREPLY=($(compgen -W '{sh_words(ws)}' -- \"$cur\")) ;;"
        )
    L += [
        "            esac ;;",
        "    esac",
        "    return 0",
        "}",
        "complete -F _local_delegate " + " ".join(ALIASES),
    ]
    return "\n".join(L) + "\n"


def zesc(s):
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")


def gen_zsh():
    # Hand-rolled walk + _describe/compadd (no _arguments state machine): mirrors the other shells.
    L = [
        "#compdef " + " ".join(ALIASES),
        "# local-delegate completion (static, generated).",
        "_local_delegate() {",
        "    local cur path w expect opt i",
        "    local -a cands",
        '    cur="${words[CURRENT]}"',
        "    path=''; expect=''",
        "    for (( i = 2; i < CURRENT; i++ )); do",
        '        w="${words[i]}"',
        "        if [[ -n \"$expect\" ]]; then expect=''; continue; fi",
        '        case "$w" in',
        "            --*=*) continue ;;",
        "            -*)",
        '                case "$path|$w" in',
    ]
    for p, n in TREE.items():
        for o in n.get("values", {}):
            L.append(f"                    '{p}|{o}') expect=\"$w\" ;;")
    L += [
        "                esac",
        "                continue ;;",
        "        esac",
        '        case "$path|$w" in',
    ]
    for p, n in TREE.items():
        for s, _ in n["subs"]:
            L.append(f"            '{p}|{s}') path='{(p + ' ' + s).strip()}' ;;")
    L += [
        "        esac",
        "    done",
        "    opt=''",
        '    if [[ -n "$expect" ]]; then opt="$expect"',
        '    elif [[ "$cur" == --*=* ]]; then opt="${cur%%=*}"; compset -P \'*=\'',
        "    fi",
        '    if [[ -n "$opt" ]]; then',
        '        case "$path|$opt" in',
    ]
    for p, n in TREE.items():
        for o, vals in n.get("values", {}).items():
            if vals:
                L.append(f"            '{p}|{o}') cands=({sh_words(vals)}); compadd -a cands ;;")
            else:
                L.append(f"            '{p}|{o}') _files ;;")
    L += [
        "        esac",
        "        return",
        "    fi",
        '    if [[ "$cur" == -* ]]; then',
        '        case "$path" in',
    ]
    for p, n in TREE.items():
        items = " ".join("'" + zesc(o) + ":" + zesc(d) + "'" for o, d in n["opts"])
        L.append(f"            '{p}') cands=({items}) ;;")
    L += ["        esac", "    else", '        case "$path" in']
    for p, n in TREE.items():
        items = [("'" + zesc(s) + ":" + zesc(d) + "'") for s, d in n["subs"]]
        items += ["'" + zesc(v) + "'" for v in n.get("positional", [])]
        L.append(f"            '{p}') cands=({' '.join(items)}) ;;")
    L += [
        "        esac",
        "    fi",
        "    (( ${#cands} )) && _describe -t commands 'local-delegate' cands",
        "}",
        'if [[ "${zsh_eval_context[-1]}" == loadautofunc ]]; then',
        '    _local_delegate "$@"',
        "else",
        "    compdef _local_delegate " + " ".join(ALIASES),
        "fi",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    out = {"powershell": gen_powershell, "bash": gen_bash, "zsh": gen_zsh}[sys.argv[1]]()
    sys.stdout.buffer.write(out.encode("utf-8"))
