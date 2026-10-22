"""F2-live: drive `local-delegate desktop-bridge` over stdio as Claude Desktop would.

python bridge_client.py <local-delegate.exe>

The child gets ONLY Desktop's fixed list of variables (research r5: the SDK's getDefaultEnvironment
plus the Windows extras); the entry written by `install --desktop` has no `env`. The token is never
printed: it is read from HKCU only to check that no output carries it.
"""

import json
import os
import subprocess
import sys
import threading
import winreg

EXE = sys.argv[1]
SDK = [
    "APPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PROCESSOR_ARCHITECTURE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "USERNAME",
    "USERPROFILE",
    "PROGRAMFILES",
]
EXTRA = [
    "ComSpec",
    "SystemRoot",
    "windir",
    "PATHEXT",
    "TEMP",
    "TMP",
    "ALLUSERSPROFILE",
    "ProgramData",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "PUBLIC",
    "COMPUTERNAME",
    "OS",
    "NUMBER_OF_PROCESSORS",
]
upper = {k.upper(): k for k in os.environ}
env = {}
for name in SDK + EXTRA:
    if name.upper() in upper:
        env[name] = os.environ[upper[name.upper()]]
for k, v in os.environ.items():
    if k.upper().startswith(("COMMONPROGRAMFILES", "PROCESSOR_")):
        env[k] = v
assert not any(k.upper().startswith("LOCAL_DELEGATE") for k in env), (
    "token variable leaked into the env"
)

p = subprocess.Popen(
    [EXE, "desktop-bridge"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    cwd=env.get("USERPROFILE"),
)
err_lines: list[str] = []
threading.Thread(
    target=lambda: err_lines.extend(x.decode("utf-8", "replace") for x in p.stderr), daemon=True
).start()


def send(msg):
    p.stdin.write((json.dumps(msg) + "\n").encode())
    p.stdin.flush()


def recv():
    line = p.stdout.readline()
    if not line:
        raise SystemExit("bridge closed stdout")
    return json.loads(line)


report = {"env_names": sorted(env)}
send(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "f2live-desktop-sim", "version": "0"},
        },
    }
)
r = recv()
report["initialize"] = {
    "error": r.get("error"),
    "server": r.get("result", {}).get("serverInfo"),
    "protocol": r.get("result", {}).get("protocolVersion"),
}
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
r = recv()
tools = [t["name"] for t in r.get("result", {}).get("tools", [])]
report["tools_list"] = {"error": r.get("error"), "count": len(tools), "names": tools}
send(
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "local_status", "arguments": {}},
    }
)
r = recv()
res = r.get("result", {})
text = "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text")
report["local_status"] = {
    "error": r.get("error"),
    "isError": res.get("isError"),
    "chars": len(text),
    "head": text[:300],
}
p.stdin.close()
try:
    report["exit_code"] = p.wait(timeout=20)
except subprocess.TimeoutExpired:
    p.kill()
    report["exit_code"] = "killed after 20 s"
report["stderr"] = [x.rstrip() for x in err_lines][:10]
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
    token = winreg.QueryValueEx(key, "LOCAL_DELEGATE_WEB_TOKEN")[0]
blob = json.dumps(report, ensure_ascii=False)
report["token_in_any_output"] = bool(token) and token in (blob + text)
print(json.dumps(report, ensure_ascii=False, indent=1))
