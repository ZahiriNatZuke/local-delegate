# local-delegate completion (static, generated). bash >= 3.2.
_local_delegate() {
    local cur path i w expect
    cur="${COMP_WORDS[COMP_CWORD]}"
    path=''; expect=''
    COMPREPLY=()
    i=1
    while [ $i -lt $COMP_CWORD ]; do
        w="${COMP_WORDS[i]}"
        i=$((i+1))
        # COMP_WORDBREAKS contains '=': '--opt=val' arrives as '--opt' '=' 'val'
        if [ "$w" = '=' ]; then continue; fi
        if [ -n "$expect" ]; then expect=''; continue; fi
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
    local opt=''
    if [ -n "$expect" ]; then opt="$expect"; [ "$cur" = '=' ] && cur=''
    else case "$cur" in --*=*) opt="${cur%%=*}"; cur="${cur#*=}" ;; esac
    fi
    if [ -n "$opt" ]; then
        case "$path|$opt" in
            'install|--mcp-mode') COMPREPLY=($(compgen -W 'stdio http' -- "$cur")) ;;
            'install|--lang') COMPREPLY=($(compgen -W 'es en' -- "$cur")) ;;
            'install|--config') COMPREPLY=($(compgen -f -- "$cur")) ;;
            'backend-params set|--role') COMPREPLY=($(compgen -W 'mechanical long code vision' -- "$cur")) ;;
            'backend-params set|--param') COMPREPLY=($(compgen -W 'temperature top_p' -- "$cur")) ;;
        esac
        return 0
    fi
    case "$cur" in
        -*)
            case "$path" in
                '') COMPREPLY=($(compgen -W '--help --version' -- "$cur")) ;;
                'install') COMPREPLY=($(compgen -W '--mcp-mode --lang --agents --config --help' -- "$cur")) ;;
                'backend-params') COMPREPLY=($(compgen -W '--help' -- "$cur")) ;;
                'backend-params set') COMPREPLY=($(compgen -W '--role --param --help' -- "$cur")) ;;
                'backend-params show') COMPREPLY=($(compgen -W '--json --help' -- "$cur")) ;;
                'backend-params reset') COMPREPLY=($(compgen -W '--help' -- "$cur")) ;;
                'completion') COMPREPLY=($(compgen -W '--help' -- "$cur")) ;;
            esac ;;
        *)
            case "$path" in
                '') COMPREPLY=($(compgen -W 'install backend-params completion' -- "$cur")) ;;
                'install') COMPREPLY=($(compgen -W '' -- "$cur")) ;;
                'backend-params') COMPREPLY=($(compgen -W 'set show reset' -- "$cur")) ;;
                'backend-params set') COMPREPLY=($(compgen -W '' -- "$cur")) ;;
                'backend-params show') COMPREPLY=($(compgen -W '' -- "$cur")) ;;
                'backend-params reset') COMPREPLY=($(compgen -W '' -- "$cur")) ;;
                'completion') COMPREPLY=($(compgen -W 'powershell zsh bash' -- "$cur")) ;;
            esac ;;
    esac
    return 0
}
complete -F _local_delegate local-delegate local-delegate-mcp
