# Deterministic: call the completion function outside ZLE with stubs (no pty).
PROTO=$1
compdef() { :; }                          # registration is a no-op here
source $PROTO
_describe() { local n=$4; print -r -- "describe: ${(P)n}"; }   # _describe -t tag descr arrayname
compadd() { local a; while [[ $1 == -* ]]; do [[ $1 == -a ]] && { a=$2; shift; }; shift; done; print -r -- "compadd: ${(P)a} $@"; }
compset() { [[ $1 == -P ]] && PREFIX=${PREFIX#*=}; }
_files() { print -r -- "files"; }
t() { words=("$@"); CURRENT=${#words}; PREFIX=${words[CURRENT]}; print -rn -- "[$*] -> "; _local_delegate; }
t local-delegate ''
t local-delegate backend-params set --role ''
t local-delegate backend-params set --role=v
t local-delegate backend-params set -- 
t local-delegate install --config ''
