# usage: zsh -f test-zsh.zsh <proto.zsh>
zmodload zsh/zpty
PROTO=$1
zpty -b z 'TERM=dumb PS1="%% " zsh -f -i'
zpty -w z 'autoload -U compinit && compinit -u -D'
zpty -w z "source $PROTO"
zpty -w z 'zstyle ":completion:*" list-separator ""; setopt nolistbeep; unsetopt menucomplete automenu; zstyle ":completion:*" verbose yes'
zpty -w z 'print READY'
zpty -r -m z out '*READY*READY*' ; out=''
t() {
  local line=$1 buf=''
  zpty -n -w z "$line"$'\t\t'
  zpty -w z $'\x15print -r -- @@END@@'   # ^U kills the line, then marker
  zpty -r -m z buf '*@@END@@*@@END@@*'
  buf=${buf//$'\r'/}
  print -r -- "=== [$line]"
  print -r -- "${${buf%%print -r -- @@END@@*}#*$line}" | grep -v '^\s*$' | head -8
}
print "zsh $ZSH_VERSION"
t 'local-delegate '
t 'local-delegate ba'
t 'local-delegate backend-params '
t 'local-delegate backend-params set --'
t 'local-delegate backend-params set --role '
t 'local-delegate backend-params set --role=v'
t 'local-delegate install --mcp-mode http --lang '
t 'local-delegate completion '
t 'local-delegate-mcp ins'
zpty -d z
