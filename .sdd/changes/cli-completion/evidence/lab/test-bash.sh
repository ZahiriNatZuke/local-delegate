# usage: bash --norc --noprofile test-bash.sh <script>
source "$1"
t() { # words... ; last word is the one under the cursor
  COMP_WORDS=("$@"); COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))
  COMPREPLY=(); _local_delegate "${COMP_WORDS[0]}" "${COMP_WORDS[COMP_CWORD]}" "${COMP_WORDS[COMP_CWORD-1]}"
  printf '%-55s -> %s\n' "[$*]" "${COMPREPLY[*]}"
}
echo "bash $BASH_VERSION"; complete -p local-delegate
t local-delegate ''
t local-delegate ba
t local-delegate backend-params ''
t local-delegate backend-params set --
t local-delegate backend-params set --role ''
t local-delegate backend-params set --role c
t local-delegate backend-params set --role =
t local-delegate backend-params set --role = v
t local-delegate backend-params set --role = code --param ''
t local-delegate install --mcp-mode http --lang ''
t local-delegate completion ''
t local-delegate-mcp ins
t local-delegate install --config pro
