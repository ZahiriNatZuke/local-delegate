print "--- 1) source without compinit:"
zsh -f -c "source $1" 2>&1 | head -3
print "--- 2) fpath mode:"
mkdir -p /tmp/fp && cp $1 /tmp/fp/_local-delegate
zsh -f -c 'fpath=(/tmp/fp $fpath); autoload -U compinit && compinit -u -D; print -r -- "registered: ${_comps[local-delegate]} / ${_comps[local-delegate-mcp]}"'
print "--- 3) eval mode timing:"
zsh -f -c "autoload -U compinit && compinit -u -D; s=\$EPOCHREALTIME; zmodload zsh/datetime; s=\$EPOCHREALTIME; eval \"\$(cat $1)\"; print -r -- \"eval ms: \$(( (EPOCHREALTIME-s)*1000 ))  registered: \${_comps[local-delegate]}\""
