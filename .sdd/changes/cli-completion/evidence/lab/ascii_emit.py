import sys


def ps_dq(s):
    out = []
    for ch in s:
        if ch in '`"$':
            out.append("`" + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            for unit in ch.encode("utf-16-le").hex(" ", 2).split():  # handles surrogate pairs
                cp = int(unit[2:4] + unit[0:2], 16)
                out.append(f"$([char]0x{cp:04X})")
    return '"' + "".join(out) + '"'


sys.stdout.write("$__t = " + ps_dq('Parámetro "x" $HOME `n 🚀 ñ') + "\n")
