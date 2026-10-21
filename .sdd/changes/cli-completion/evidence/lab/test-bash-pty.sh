# Drive a real interactive bash (readline) through a pty with `script`; keystrokes from stdin.
P=$1
{ sleep 0.5; printf 'source %s/proto.bash; bind "set show-all-if-ambiguous on"; bind "set bell-style none"\n' "$P"; sleep 0.3
  printf 'echo X local-delegate backend-params set --role=v\t\n'; sleep 0.3   # never runs the CLI: "echo X" prefix? no -> see below
  printf 'exit\n'; } | true
for line in 'local-delegate backend-params set --role=v' 'local-delegate backend-params set --role=' 'local-delegate ba' 'local-delegate install --mcp-mode '; do
  { sleep 0.4; printf 'source %s/proto.bash; bind "set show-all-if-ambiguous on" 2>/dev/null; bind "set bell-style none"; PS1="$ "\n' "$P"; sleep 0.4
    printf '%s\t' "$line"; sleep 0.4; printf '\025'; sleep 0.1; printf 'exit\n'; sleep 0.2; } \
  | TERM=dumb script -qec 'bash --norc --noprofile -i' /dev/null 2>&1 | tr -d '\r' | grep -a -v '^source\|^exit\|^$' | sed -n '1,6p' | sed "s/^/[$line] /"
done
