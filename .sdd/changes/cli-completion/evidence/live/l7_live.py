"""L7 del SDD cli-completion: verificación en vivo con el binario del wheel (REQ-040).

Se ejecuta con el python del venv temporal (`venv-cc/Scripts/python.exe -I l7_live.py <out_dir>`),
así importa el `local_delegate` instalado desde el wheel, no el del repo.

Pasos (plan §3 L7):
  3. solo lectura sobre el HOME real: sha256 antes, `install --shell-completion --dry-run ...`,
     sha256 después;
  4. instalado sobre un HOME temporal: perfiles sembrados, `install --shell-completion`, casos de
     REQ-012..015 en pwsh y powershell.exe (con PSModulePath vacío), `doctor`, `uninstall` y
     comparación de bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from local_delegate import backend_params, config, shell_profiles

OUT = Path(sys.argv[1])
SCRATCH = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
EXE = Path(sys.executable).with_name("local-delegate.exe")
TIMEOUT = 180
EMPTY = SCRATCH / "empty-cwd"
EMPTY.mkdir(exist_ok=True)

ROLES = list(backend_params.ROLES)
KEYS = list(backend_params.ALLOWED_KEYS)


def base_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("LOCAL_DELEGATE_LOG_DIR", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def ps_env(edition: str) -> dict[str, str]:
    # Mismo filtro que el producto (`shell_profiles.query_environment`), que compara en mayusculas:
    # en Windows `os.environ` guarda las claves en mayusculas y `pop("PSModulePath")` no quita nada.
    exe = shutil.which(edition)
    env = shell_profiles.query_environment(exe, base_env())
    if edition == "powershell":
        assert not any(k.upper() == "PSMODULEPATH" for k in env), "PSModulePath sigue en el entorno"
    return env


def run(cmd: list[str], env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=EMPTY,
        env=env or base_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=TIMEOUT,
    )
    return {
        "cmd": [str(c) for c in cmd],
        "returncode": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
    }


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def write(name: str, data) -> None:
    target = OUT / name
    if isinstance(data, str):
        target.write_bytes(data.encode("utf-8"))
    else:
        target.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# --- Paso 3: solo lectura sobre el HOME real -------------------------------------------------------


def real_targets() -> dict[str, dict]:
    """Ruta de `$PROFILE.CurrentUserAllHosts` y política de cada edición, preguntadas en solo lectura."""
    info = {}
    for edition in ("pwsh", "powershell"):
        exe = shutil.which(edition)
        # La misma consulta que hace `install` (REQ-025), en solo lectura.
        profile, policy = shell_profiles.query_powershell(exe)
        info[edition] = {
            "executable": exe,
            "profile": str(profile) if profile else None,
            "policy": policy,
            "policy_blocks": shell_profiles.policy_blocks(policy),
        }
    return info


def snapshot_real(targets: dict[str, dict], completion_dir: Path) -> dict:
    files: dict[str, str | None] = {}
    for item in targets.values():
        if not item["profile"]:
            continue
        folder = Path(item["profile"]).parent
        files[item["profile"]] = sha(Path(item["profile"]))
        if folder.is_dir():
            for p in sorted(folder.glob("*.ps1")):
                files[str(p)] = sha(p)
    files[f"{completion_dir} (existe)"] = str(completion_dir.exists())
    if completion_dir.is_dir():
        for p in sorted(completion_dir.rglob("*")):
            if p.is_file():
                files[str(p)] = sha(p)
    return files


def step3() -> dict:
    targets = real_targets()
    completion_dir = shell_profiles.completion_dir(Path.home())
    before = snapshot_real(targets, completion_dir)
    dry = run(
        [
            str(EXE),
            "install",
            "--shell-completion",
            "--dry-run",
            "--no-hooks",
            "--no-skill",
            "--no-memory",
            "--no-mcp",
            "--no-client-cli",
        ]
    )
    after = snapshot_real(targets, completion_dir)
    result = {
        "log_dir": str(config.LOG_DIR),
        "completion_dir": str(completion_dir),
        "targets": targets,
        "sha256_before": before,
        "sha256_after": after,
        "sha256_equal": before == after,
        "dry_run": dry,
    }
    write("step3-real-home-dry-run.json", result)
    write(
        "step3-dry-run-stdout.txt",
        dry["stdout"] + ("\n--- stderr ---\n" + dry["stderr"] if dry["stderr"] else ""),
    )
    return result


# --- Paso 4: instalado sobre un HOME temporal ------------------------------------------------------

RUNNER = r"""
param([string]$ProfilePath, [string]$SpecPath, [string]$OutPath)
$ErrorActionPreference = 'Stop'
$spec = Get-Content -Raw -LiteralPath $SpecPath | ConvertFrom-Json
. $ProfilePath
$rows = New-Object System.Collections.ArrayList
foreach ($case in $spec) {
    $result = TabExpansion2 -inputScript $case.line -cursorColumn $case.line.Length
    $found = New-Object System.Collections.ArrayList
    foreach ($m in $result.CompletionMatches) {
        [void]$found.Add(@{ text = $m.CompletionText; tip = $m.ToolTip; type = $m.ResultType.ToString() })
    }
    [void]$rows.Add(@{ id = $case.id; line = $case.line; matches = $found })
}
$report = @{ major = $PSVersionTable.PSVersion.Major; minor = $PSVersionTable.PSVersion.Minor; rows = $rows }
$json = $report | ConvertTo-Json -Depth 6 -Compress
[System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding $false))
"""

TOP = 13
BP_SUB = ["show", "set", "unset", "reset"]


def cases(edition: str) -> list[dict]:
    """(id, req, línea, comprobación). `exact` = lista exacta; `count` = n.º; `none_of` = excluye."""
    serve_line = "local-delegate serve --" if edition == "pwsh" else "local-delegate serve --l"
    serve_exp = (
        ["--host", "--port", "--log-level", "--help"] if edition == "pwsh" else ["--log-level"]
    )
    return [
        {
            "id": "root",
            "req": "REQ-012",
            "line": "local-delegate ",
            "count": TOP,
            "includes": ["completion"],
        },
        {
            "id": "root_ba",
            "req": "REQ-012",
            "line": "local-delegate ba",
            "exact": ["backend-params"],
        },
        {"id": "bp", "req": "REQ-012", "line": "local-delegate backend-params ", "exact": BP_SUB},
        {
            "id": "llamaswap",
            "req": "REQ-012",
            "line": "local-delegate llamaswap ",
            "exact": ["residency"],
        },
        {
            "id": "test_window",
            "req": "REQ-012",
            "line": "local-delegate test-window ",
            "exact": ["start", "stop", "add", "list"],
        },
        {
            "id": "case_sensitive",
            "req": "REQ-012",
            "line": "local-delegate BACKEND-PARAMS ",
            "none_of": BP_SUB,
        },
        {
            "id": "after_flag",
            "req": "REQ-012",
            "line": "local-delegate --version backend-params ",
            "exact": BP_SUB,
        },
        {
            "id": "install_mcp",
            "req": "REQ-013",
            "line": "local-delegate install --mcp",
            "exact": ["--mcp-mode"],
        },
        {"id": "serve_options", "req": "REQ-013", "line": serve_line, "exact": serve_exp},
        {
            "id": "append_again",
            "req": "REQ-013",
            "line": "local-delegate install --clients claude --cl",
            "exact": ["--clients"],
        },
        {
            "id": "mcp_mode",
            "req": "REQ-014",
            "line": "local-delegate install --mcp-mode ",
            "exact": ["stdio", "http"],
        },
        {
            "id": "mcp_mode_eq",
            "req": "REQ-014",
            "line": "local-delegate install --mcp-mode=h",
            "exact": ["--mcp-mode=http"],
        },
        {
            "id": "log_level",
            "req": "REQ-014",
            "line": "local-delegate serve --log-level w",
            "exact": ["warning"],
        },
        {
            "id": "benchmark_role",
            "req": "REQ-014",
            "line": "local-delegate benchmark --role ",
            "exact": ROLES,
        },
        {
            "id": "reset_calibration",
            "req": "REQ-014",
            "line": "local-delegate recompute-cost --reset-calibration ",
            "exact": ["five_hour", "seven_day"],
        },
        {
            "id": "shell_completion",
            "req": "REQ-014",
            "line": "local-delegate install --shell-completion ",
            "exact": ["auto", "powershell", "zsh", "bash"],
        },
        {
            "id": "shell_completion_d",
            "req": "REQ-014",
            "line": "local-delegate install --shell-completion --d",
            "exact": ["--dry-run"],
        },
        {
            "id": "set_role",
            "req": "REQ-015",
            "line": "local-delegate backend-params set ",
            "exact": ROLES,
        },
        {
            "id": "set_key",
            "req": "REQ-015",
            "line": "local-delegate backend-params set code ",
            "exact": KEYS,
            "count": 21,
        },
        {
            "id": "set_value",
            "req": "REQ-015",
            "line": "local-delegate backend-params set code top_p ",
            "exact": [],
        },
        {
            "id": "unset_t",
            "req": "REQ-015",
            "line": "local-delegate backend-params unset vision t",
            "exact": ["temperature", "top_k", "top_p", "typical_p"],
        },
        {
            "id": "reset_role",
            "req": "REQ-015",
            "line": "local-delegate backend-params reset ",
            "exact": ROLES,
        },
        {
            "id": "completion",
            "req": "REQ-015",
            "line": "local-delegate completion ",
            "exact": ["powershell", "zsh", "bash"],
        },
        {"id": "no_match", "req": "REQ-017 (control)", "line": "local-delegate zzz", "exact": []},
    ]


def judge(case: dict, texts: list[str]) -> tuple[bool, str]:
    reasons = []
    if "exact" in case and sorted(texts) != sorted(case["exact"]):
        reasons.append(f"esperado {sorted(case['exact'])}")
    if "count" in case and len(texts) != case["count"]:
        reasons.append(f"esperados {case['count']} candidatos")
    for item in case.get("includes", []):
        if item not in texts:
            reasons.append(f"falta {item}")
    for item in case.get("none_of", []):
        if item in texts:
            reasons.append(f"no debía ofrecer {item}")
    return (not reasons, "; ".join(reasons))


def seed(home: Path) -> dict[Path, bytes]:
    seeds = {
        home / "Documents" / "WindowsPowerShell" / "profile.ps1": (
            "# perfil del usuario: configuración\r\n$saludo = 'año'\r\n".encode("cp1252")
        ),
        home
        / "Documents"
        / "PowerShell"
        / "profile.ps1": "﻿# perfil de pwsh: canción\n$x = 1\n".encode(),
    }
    for path, data in seeds.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return seeds


def complete(edition: str, exe: str, profile: Path, bypass: bool, work: Path) -> dict:
    runner = work / "runner.ps1"
    runner.write_bytes(RUNNER.encode("ascii"))
    spec_cases = cases(edition)
    spec = work / f"cases-{edition}.json"
    spec.write_bytes(
        json.dumps([{"id": c["id"], "line": c["line"]} for c in spec_cases]).encode("ascii")
    )
    out = work / f"result-{edition}.json"
    out.unlink(missing_ok=True)
    cmd = [exe, "-NoProfile", "-NonInteractive"]
    if bypass:
        cmd += ["-ExecutionPolicy", "Bypass"]
    cmd += [
        "-Command",
        f"& '{runner}' -ProfilePath '{profile}' -SpecPath '{spec}' -OutPath '{out}'",
    ]
    proc = run(cmd, ps_env(edition))
    report = json.loads(out.read_bytes().decode("utf-8")) if out.is_file() else None
    rows = []
    all_ok = report is not None and proc["returncode"] == 0
    by_id = {r["id"]: r for r in (report or {}).get("rows", [])}
    for case in spec_cases:
        row = by_id.get(case["id"], {})
        matches = row.get("matches") or []
        if isinstance(matches, dict):  # ConvertTo-Json aplana una lista de uno
            matches = [matches]
        texts = [m["text"] for m in matches]
        ok, why = judge(case, texts)
        all_ok = all_ok and ok
        rows.append(
            {
                "id": case["id"],
                "req": case["req"],
                "line": case["line"],
                "ok": ok,
                "why": why,
                "matches": [{"CompletionText": m["text"], "ToolTip": m["tip"]} for m in matches],
            }
        )
    return {
        "edition": edition,
        "executable": exe,
        "ps_version": f"{report['major']}.{report['minor']}" if report else None,
        "execution_policy_bypass": bypass,
        "psmodulepath_cleared": edition == "powershell",
        "launch": proc,
        "all_ok": all_ok,
        "cases": rows,
    }


def as_text(result: dict) -> str:
    lines = [
        f"# {result['edition']} ({result['executable']}) PowerShell {result['ps_version']}",
        f"# -ExecutionPolicy Bypass: {result['execution_policy_bypass']}; PSModulePath vaciado: {result['psmodulepath_cleared']}",
        f"# todos OK: {result['all_ok']}",
        "",
    ]
    for case in result["cases"]:
        mark = "OK" if case["ok"] else f"KO ({case['why']})"
        lines.append(f"[{mark}] {case['req']} {case['id']}: «{case['line']}»")
        if not case["matches"]:
            lines.append("    (sin candidatos)")
        for m in case["matches"]:
            lines.append(f"    CompletionText={m['CompletionText']!s:<28} ToolTip={m['ToolTip']}")
    return "\n".join(lines) + "\n"


def step4(policies: dict[str, dict]) -> dict:
    home = SCRATCH / "home-cc"
    if home.exists():
        shutil.rmtree(home)
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    (home / ".config" / "opencode").mkdir(parents=True)
    seeds = seed(home)
    common = ["--home", str(home), "--no-client-cli"]
    data_dir = home / ".local" / "share" / "local-delegate" / "completion"
    install = run([str(EXE), "install", *common, "--shell-completion"])
    write(
        "step4-install.txt",
        install["stdout"]
        + "\n--- stderr ---\n"
        + install["stderr"]
        + f"\nreturncode={install['returncode']}\n",
    )
    installed_files = sorted(p.name for p in data_dir.iterdir()) if data_dir.is_dir() else []
    profiles_after_install = {str(p): p.read_bytes().decode("utf-8", "replace") for p in seeds}

    work = SCRATCH / "ps-work"
    work.mkdir(exist_ok=True)
    results = {}
    for edition in ("pwsh", "powershell"):
        exe = policies[edition]["executable"]
        profile = (
            home
            / "Documents"
            / ("PowerShell" if edition == "pwsh" else "WindowsPowerShell")
            / "profile.ps1"
        )
        bypass = bool(policies[edition]["policy_blocks"])
        results[edition] = complete(edition, exe, profile, bypass, work)
        write(f"step4-complete-{edition}.json", results[edition])
        write(f"step4-complete-{edition}.txt", as_text(results[edition]))

    doctor = run([str(EXE), "doctor", "--home", str(home)])
    doctor_line = [
        ln
        for ln in doctor["stdout"].splitlines()
        if "autocompletado del shell" in ln or "shell completion" in ln
    ]
    write(
        "step4-doctor.txt",
        doctor["stdout"]
        + "\n--- stderr ---\n"
        + doctor["stderr"]
        + f"\nreturncode={doctor['returncode']}\n",
    )

    uninstall = run([str(EXE), "uninstall", *common])
    write(
        "step4-uninstall.txt",
        uninstall["stdout"]
        + "\n--- stderr ---\n"
        + uninstall["stderr"]
        + f"\nreturncode={uninstall['returncode']}\n",
    )
    comparison = {
        str(p): {
            "seed_sha256": hashlib.sha256(data).hexdigest(),
            "after_uninstall_sha256": sha(p),
            "bytes_equal": p.is_file() and p.read_bytes() == data,
        }
        for p, data in seeds.items()
    }
    leftovers = sorted(str(p) for p in home.rglob("*.local-delegate.bak"))
    remaining = sorted(p.name for p in data_dir.iterdir()) if data_dir.is_dir() else []
    summary = {
        "home": str(home),
        "install_returncode": install["returncode"],
        "installed_completion_files": installed_files,
        "profiles_after_install": profiles_after_install,
        "completion": {
            e: {
                "all_ok": r["all_ok"],
                "bypass": r["execution_policy_bypass"],
                "ps_version": r["ps_version"],
                "ko": [c["id"] for c in r["cases"] if not c["ok"]],
            }
            for e, r in results.items()
        },
        "doctor_returncode": doctor["returncode"],
        "doctor_shell_completion_line": doctor_line,
        "uninstall_returncode": uninstall["returncode"],
        "uninstall_byte_comparison": comparison,
        "own_backup_leftovers": leftovers,
        "completion_dir_remaining": remaining,
    }
    write("step4-summary.json", summary)
    return summary


def main() -> int:
    s3 = step3()
    s4 = step4(s3["targets"])
    print(
        json.dumps(
            {
                "step3_sha_equal": s3["sha256_equal"],
                "dry_rc": s3["dry_run"]["returncode"],
                "targets": s3["targets"],
                "step4": {k: v for k, v in s4.items() if k != "profiles_after_install"},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
