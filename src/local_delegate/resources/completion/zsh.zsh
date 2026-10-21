#compdef local-delegate local-delegate-mcp
@@HEADER@@
# Static script: loading it or pressing Tab runs nothing else. It works sourced (after compinit,
# or it loads compinit itself) and as a `_local-delegate` file in `fpath`.
#
# Keys: "<path>" and "<path>|<name>" ("<path>|#<index>" for positionals), where <path> is the
# subcommand path joined with spaces ("" is the root). Each function leaves its answer in the
# array `_ld_reply`, a local of `_local_delegate`; `describe` gives `name:description` items.
@@TABLES@@

_local_delegate() {
    local cur word key route expect
    local -a _ld_reply _ld_subs
    integer i positional=0 ret=1
    cur="${words[CURRENT]}"
    route=''
    expect=''
    # Only the words before the cursor; zsh keeps '--option=value' as one word.
    for (( i = 2; i < CURRENT; i++ )); do
        word="${words[i]}"
        if [[ -n "$expect" ]]; then
            __local_delegate_arity "$expect"
            expect=''
            if [[ "${_ld_reply[1]}" != optional || "$word" != -* ]]; then
                continue
            fi
        fi
        case "$word" in
            --*=*) continue ;;
            -*)
                __local_delegate_arity "$route|$word"
                if (( ${#_ld_reply} )); then expect="$route|$word"; fi
                continue ;;
        esac
        __local_delegate_subs "$route"
        if (( ${_ld_reply[(Ie)$word]} )); then
            route="${route:+$route }$word"
            positional=0
            continue
        fi
        positional=$(( positional + 1 ))
    done

    key=''
    if [[ -n "$expect" ]]; then
        __local_delegate_arity "$expect"
        if [[ "${_ld_reply[1]}" != optional || "$cur" != -* ]]; then
            key="$expect"
        fi
    fi
    if [[ -z "$key" && "$cur" == --*=* ]]; then
        __local_delegate_arity "$route|${cur%%=*}"
        if (( ${#_ld_reply} )); then
            key="$route|${cur%%=*}"
            compset -P '*='
        fi
    fi
    if [[ -n "$key" ]]; then
        __local_delegate_values "$key"
        if (( ${#_ld_reply} )); then
            compadd -a _ld_reply && ret=0
        else
            _files && ret=0
        fi
        return ret
    fi
    if [[ "$cur" == -* ]]; then
        __local_delegate_describe "$route|opts"
        if (( ${#_ld_reply} )); then
            _describe -t options 'option' _ld_reply && ret=0
        fi
        return ret
    fi
    __local_delegate_describe "$route|subs"
    _ld_subs=("${_ld_reply[@]}")
    __local_delegate_values "$route|#$positional"
    if (( ${#_ld_subs} )); then
        _describe -t commands 'subcommand' _ld_subs && ret=0
    fi
    if (( ${#_ld_reply} )); then
        compadd -a _ld_reply && ret=0
    fi
    if (( ! ${#_ld_subs} && ! ${#_ld_reply} )); then
        # A free positional: zsh's own file completion.
        _files && ret=0
    fi
    return ret
}

if [[ "${zsh_eval_context[-1]}" == loadautofunc ]]; then
    # Autoloaded from `fpath` by compinit: this call is already a completion.
    _local_delegate "$@"
else
    # Sourced: register, loading compinit first if the shell has not.
    (( $+functions[compdef] )) || { autoload -Uz compinit && compinit -i; }
    compdef _local_delegate local-delegate local-delegate-mcp
fi
