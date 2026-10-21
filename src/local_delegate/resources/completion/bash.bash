@@HEADER@@
# Static script: loading it or pressing Tab runs nothing else. bash 3.2 and later: no associative
# arrays, compopt, mapfile or case conversion; the data are `case` functions.
#
# Keys: "<path>" and "<path>|<name>" ("<path>|#<index>" for positionals), where <path> is the
# subcommand path joined with spaces ("" is the root). Each function leaves its answer in
# `_ld_reply`, a local of `_local_delegate`.
@@TABLES@@

_local_delegate() {
    local cur word key route positional expect skip eqkey i words _ld_reply
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    route=''
    positional=0
    expect=''
    skip=''
    eqkey=''
    i=1
    # Only the words before the cursor. readline splits '--option=value' into '--option' '='
    # 'value' (COMP_WORDBREAKS), so '=' is a word of its own.
    while [ "$i" -lt "$COMP_CWORD" ]; do
        word="${COMP_WORDS[i]}"
        i=$((i + 1))
        if [ -n "$skip" ]; then
            skip=''
            eqkey=''
            continue
        fi
        if [ "$word" = '=' ]; then
            skip=1
            eqkey="$expect"
            expect=''
            continue
        fi
        if [ -n "$expect" ]; then
            __local_delegate_arity "$expect"
            expect=''
            case "$_ld_reply|$word" in
                optional\|-*) ;;
                *) continue ;;
            esac
        fi
        case "$word" in
            --*=*) continue ;;
            -*)
                __local_delegate_arity "$route|$word"
                if [ -n "$_ld_reply" ]; then expect="$route|$word"; fi
                continue ;;
        esac
        __local_delegate_subs "$route"
        case " $_ld_reply " in
            *" $word "*)
                route="${route:+$route }$word"
                positional=0
                continue ;;
        esac
        positional=$((positional + 1))
    done

    key=''
    if [ -n "$skip" ]; then
        key="$eqkey"
    elif [ -n "$expect" ] && [ "$cur" = '=' ]; then
        key="$expect"
        cur=''
    elif [ -n "$expect" ]; then
        __local_delegate_arity "$expect"
        case "$_ld_reply|$cur" in
            optional\|-*) ;;
            *) key="$expect" ;;
        esac
    fi
    if [ -n "$key" ]; then
        # An empty answer leaves the free value to readline (`complete -o default`).
        __local_delegate_values "$key"
        if [ -n "$_ld_reply" ]; then
            COMPREPLY=($(compgen -W "$_ld_reply" -- "$cur"))
        fi
        return 0
    fi
    case "$cur" in
        --*=*)
            key="$route|${cur%%=*}"
            __local_delegate_values "$key"
            if [ -n "$_ld_reply" ]; then
                COMPREPLY=($(compgen -P "${cur%%=*}=" -W "$_ld_reply" -- "${cur#*=}"))
            fi
            return 0 ;;
        -*)
            __local_delegate_opts "$route"
            if [ -n "$_ld_reply" ]; then
                COMPREPLY=($(compgen -W "$_ld_reply" -- "$cur"))
            fi
            return 0 ;;
    esac
    __local_delegate_subs "$route"
    words="$_ld_reply"
    __local_delegate_values "$route|#$positional"
    words="$words $_ld_reply"
    COMPREPLY=($(compgen -W "$words" -- "$cur"))
    return 0
}
complete -o default -F _local_delegate local-delegate local-delegate-mcp
