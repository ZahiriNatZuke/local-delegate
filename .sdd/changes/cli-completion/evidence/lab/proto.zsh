#compdef local-delegate local-delegate-mcp
# local-delegate completion (static, generated).
_local_delegate() {
    local cur path w expect opt i
    local -a cands
    cur="${words[CURRENT]}"
    path=''; expect=''
    for (( i = 2; i < CURRENT; i++ )); do
        w="${words[i]}"
        if [[ -n "$expect" ]]; then expect=''; continue; fi
        case "$w" in
            --*=*) continue ;;
            -*)
                case "$path|$w" in
                    'install|--mcp-mode') expect="$w" ;;
                    'install|--lang') expect="$w" ;;
                    'install|--config') expect="$w" ;;
                    'backend-params set|--role') expect="$w" ;;
                    'backend-params set|--param') expect="$w" ;;
                esac
                continue ;;
        esac
        case "$path|$w" in
            '|install') path='install' ;;
            '|backend-params') path='backend-params' ;;
            '|completion') path='completion' ;;
            'backend-params|set') path='backend-params set' ;;
            'backend-params|show') path='backend-params show' ;;
            'backend-params|reset') path='backend-params reset' ;;
        esac
    done
    opt=''
    if [[ -n "$expect" ]]; then opt="$expect"
    elif [[ "$cur" == --*=* ]]; then opt="${cur%%=*}"; compset -P '*='
    fi
    if [[ -n "$opt" ]]; then
        case "$path|$opt" in
            'install|--mcp-mode') cands=(stdio http); compadd -a cands ;;
            'install|--lang') cands=(es en); compadd -a cands ;;
            'install|--config') _files ;;
            'backend-params set|--role') cands=(mechanical long code vision); compadd -a cands ;;
            'backend-params set|--param') cands=(temperature top_p); compadd -a cands ;;
        esac
        return
    fi
    if [[ "$cur" == -* ]]; then
        case "$path" in
            '') cands=('--help:Muestra la ayuda' '--version:Muestra la versión') ;;
            'install') cands=('--mcp-mode:Modo del MCP' '--lang:Idioma' '--agents:Instala agentes' '--config:Ruta de configuración' '--help:Muestra la ayuda') ;;
            'backend-params') cands=('--help:Muestra la ayuda') ;;
            'backend-params set') cands=('--role:Rol' '--param:Parámetro' '--help:Muestra la ayuda') ;;
            'backend-params show') cands=('--json:Salida JSON' '--help:Muestra la ayuda') ;;
            'backend-params reset') cands=('--help:Muestra la ayuda') ;;
            'completion') cands=('--help:Muestra la ayuda') ;;
        esac
    else
        case "$path" in
            '') cands=('install:Instala la integración' 'backend-params:Parámetros por rol' 'completion:Script de autocompletado') ;;
            'install') cands=() ;;
            'backend-params') cands=('set:Fija un parámetro' 'show:Muestra los parámetros' 'reset:Restablece') ;;
            'backend-params set') cands=() ;;
            'backend-params show') cands=() ;;
            'backend-params reset') cands=() ;;
            'completion') cands=('powershell' 'zsh' 'bash') ;;
        esac
    fi
    (( ${#cands} )) && _describe -t commands 'local-delegate' cands
}
if [[ "${zsh_eval_context[-1]}" == loadautofunc ]]; then
    _local_delegate "$@"
else
    compdef _local_delegate local-delegate local-delegate-mcp
fi
