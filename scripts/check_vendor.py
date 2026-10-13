"""Vigila el JavaScript vendorizado: integridad, CVEs conocidos y versión publicada.

`src/local_delegate/resources/vendor/` guarda 205 KB de Chart.js de terceros que **nadie audita**:
Dependabot no ve un blob, CodeQL no lo analiza y Socket cubre dependencias declaradas, no ficheros
sueltos. Vendorizar fue correcto —el dashboard tiene que funcionar sin internet— pero hasta ahora
no había ni un hash registrado: un cambio en ese fichero no dejaba rastro y un CVE publicado
mañana no avisaba a nadie.

Este script cierra ese hueco leyendo `vendor.json`, que es la fuente de verdad.

**El reparto entre lo que rompe el CI y lo que solo avisa no es arbitrario**: lo que puede poner
un job en rojo tiene que ser determinista.

    Rompe   integridad (hash y sincronía manifiesto/directorio) -> offline, siempre fiable
    Rompe   vulnerabilidad confirmada por OSV                   -> es un problema real
    Avisa   existe una versión más nueva en npm                 -> que alguien publique no es un fallo nuestro
    Avisa   OSV o npm no responden, o responden cualquier cosa  -> un servicio ajeno caído no bloquea PRs

Códigos de salida:

    0  todo en orden (puede haber avisos)
    1  integridad rota: hash que no cuadra, fichero ausente, manifiesto y directorio desincronizados
    2  OSV reporta al menos una vulnerabilidad de la versión vendorizada
    3  el manifiesto no existe o no se puede leer

Uso:

    python scripts/check_vendor.py              # completo
    python scripts/check_vendor.py --offline    # solo integridad, sin tocar la red

Con `GITHUB_STEP_SUMMARY` en el entorno, el informe se escribe **también** ahí: un aviso enterrado
en el log de un job verde no lo lee nadie, que es justo por lo que Chart.js llegó a estar dos
minors atrasado sin que nadie se enterara.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "src" / "local_delegate" / "resources" / "vendor" / "vendor.json"

OSV_URL = "https://api.osv.dev/v1/query"
NPM_URL = "https://registry.npmjs.org/{name}/latest"
TIMEOUT_S = 15

OK = 0
INTEGRITY_FAILURE = 1
VULNERABILITY_FAILURE = 2
MANIFEST_FAILURE = 3


class ServiceUnavailable(Exception):
    """La red falló, o el servicio devolvió algo que no se puede interpretar.

    Se trata igual una caída que una respuesta malformada: en ambos casos no sabemos nada, y no
    saber nada no puede tumbar un PR.
    """


# --- red ---------------------------------------------------------------------------------------
# Toda la salida a internet pasa por aquí. Los tests sustituyen esta función y por eso nunca tocan
# la red de verdad.
def _fetch_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    # Las URLs son constantes https de este módulo, nunca entrada de usuario.
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "local-delegate-vendor-audit"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ServiceUnavailable(str(exc)) from exc
    try:
        body = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ServiceUnavailable(f"respuesta que no es JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ServiceUnavailable("respuesta JSON que no es un objeto")
    return body


def query_osv(name: str, version: str, ecosystem: str) -> list[dict]:
    """Vulnerabilidades conocidas de esa versión. Lanza `ServiceUnavailable` si no se sabe."""
    response = _fetch_json(
        OSV_URL, {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
    )
    vulns = response.get("vulns", [])
    if not isinstance(vulns, list):
        raise ServiceUnavailable("OSV devolvió un campo `vulns` que no es una lista")
    return vulns


def query_npm(name: str) -> str:
    """Última versión publicada. Lanza `ServiceUnavailable` si no se sabe."""
    response = _fetch_json(NPM_URL.format(name=name))
    version = response.get("version")
    if not isinstance(version, str) or not version:
        raise ServiceUnavailable("npm no devolvió un campo `version` utilizable")
    return version


def _version_key(version: str) -> tuple[int, ...] | None:
    """`4.4.1` -> `(4, 4, 1)`. `None` si no es comparable (prerelease, formato raro)."""
    parts = version.split("-")[0].split(".")
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


# --- integridad (offline) ----------------------------------------------------------------------
def load_manifest(path: Path) -> dict:
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or not isinstance(content.get("files"), list):
        # ValueError y no TypeError (TRY004): quien llama recibe un fichero, no un objeto de un
        # tipo equivocado — el problema es que su *contenido* no sirve, y `main` lo trata igual
        # que un JSON roto o un fichero ilegible.
        raise ValueError("el manifiesto no tiene una lista `files`")  # noqa: TRY004
    return content


def check_integrity(manifest: dict, directory: Path) -> list[str]:
    """Errores de integridad. Lista vacía = todo cuadra. No toca la red."""
    errors: list[str] = []
    declared: set[str] = set()

    for entry in manifest["files"]:
        file_name = entry.get("file")
        if not file_name:
            errors.append("hay una entrada del manifiesto sin campo `file`")
            continue
        declared.add(file_name)
        # La licencia se declara para que el chequeo de sincronía no la vea como intrusa, pero su
        # contenido no se hashea: no es código que se sirva.
        if entry.get("licenseFile"):
            declared.add(entry["licenseFile"])

        path = directory / file_name
        if not path.is_file():
            errors.append(f"{file_name}: declarado en el manifiesto pero NO existe en disco")
            continue

        data = path.read_bytes()
        real = hashlib.sha256(data).hexdigest()
        expected = entry.get("sha256")
        if real != expected:
            message = (
                f"{file_name}: el sha256 no coincide.\n"
                f"    esperado: {expected}\n"
                f"    real:     {real}\n"
                f"    ({len(data)} bytes en disco, {entry.get('bytes')} declarados)"
            )
            # La causa más probable en Windows no es un fichero adulterado: es git convirtiendo
            # los LF en CRLF al hacer checkout (`core.autocrlf=true`, el valor por defecto de Git
            # for Windows). Decirlo aquí ahorra buscar un ataque donde solo hay un fin de línea.
            if b"\r\n" in data and len(data) > (entry.get("bytes") or 0):
                message += (
                    "\n    PISTA: el fichero tiene CRLF y pesa de más. Casi seguro que git te lo"
                    "\n    normalizó al clonar. Comprueba que `.gitattributes` marca este"
                    "\n    directorio con `-text` y vuelve a hacer checkout del fichero."
                )
            errors.append(message)
        elif entry.get("bytes") is not None and len(data) != entry["bytes"]:
            # Con el hash bueno el tamaño no puede diferir; si difiere, el manifiesto miente.
            errors.append(
                f"{file_name}: el hash cuadra pero el tamaño declarado no "
                f"({entry['bytes']} frente a {len(data)} reales)"
            )

    # Un fichero vendorizado sin declarar es exactamente el punto ciego que esto viene a cerrar.
    present = {p.name for p in directory.iterdir() if p.is_file()}
    intruders = sorted(present - declared - {"vendor.json"})
    for intruder in intruders:
        errors.append(f"{intruder}: está en `vendor/` pero NO figura en el manifiesto")

    return errors


# --- informe -----------------------------------------------------------------------------------
def _write_summary(lines: list[str]) -> None:
    """Vuelca el informe al summary del job, si estamos en Actions."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass  # el summary es un extra; no vale la pena tumbar el job por no poder escribirlo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline",
        action="store_true",
        help="solo la comprobación de integridad; no consulta OSV ni npm",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="ruta del manifiesto (por defecto, el del paquete)",
    )
    args = parser.parse_args(argv)

    manifest_path: Path = args.manifest
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FALLO: no se pudo leer el manifiesto {manifest_path}: {exc}")
        return MANIFEST_FAILURE

    directory = manifest_path.parent
    lines: list[str] = ["## Auditoría del vendorizado"]
    out = OK

    errors = check_integrity(manifest, directory)
    if errors:
        out = INTEGRITY_FAILURE
        lines.append("")
        lines.append("**INTEGRIDAD ROTA.** El contenido vendorizado no es el declarado:")
        lines.extend(f"- {e}" for e in errors)
        lines.append("")
        lines.append(
            "Si el cambio es intencionado, actualiza `vendor.json` siguiendo "
            "`docs/wiki/Repo-hardening.md`. Si no lo es, **investígalo antes de tocar nada**."
        )
    else:
        lines.append("")
        lines.append("- Integridad: OK, cada fichero coincide con su sha256 declarado.")

    if args.offline:
        lines.append("- Red: omitida (`--offline`).")
        for line in lines:
            print(line)
        _write_summary(lines)
        return out

    for entry in manifest["files"]:
        name = entry.get("name")
        version = entry.get("version")
        ecosystem = entry.get("ecosystem", "npm")
        if not name or not version:
            continue

        try:
            vulns = query_osv(name, version, ecosystem)
        except ServiceUnavailable as exc:
            lines.append(f"- AVISO: no se pudo consultar OSV para `{name}` {version}: {exc}")
        else:
            if vulns:
                # La integridad rota manda: es el diagnóstico más grave y el más fiable.
                if out == OK:
                    out = VULNERABILITY_FAILURE
                ids = ", ".join(str(v.get("id", "?")) for v in vulns)
                lines.append("")
                lines.append(
                    f"**VULNERABILIDAD.** OSV reporta {len(vulns)} para `{name}` {version}: {ids}"
                )
                lines.append("")
            else:
                lines.append(f"- CVEs: OSV no conoce ninguna para `{name}` {version}.")

        try:
            latest = query_npm(name)
        except ServiceUnavailable as exc:
            lines.append(f"- AVISO: no se pudo consultar npm para `{name}`: {exc}")
            continue

        current_k, latest_k = _version_key(version), _version_key(latest)
        if current_k is None or latest_k is None:
            lines.append(
                f"- AVISO: no se pudieron comparar las versiones de `{name}` "
                f"(vendorizada {version}, publicada {latest})."
            )
        elif latest_k > current_k:
            lines.append(
                f"- AVISO: `{name}` vendorizado en **{version}**, publicado **{latest}**. "
                "No rompe el CI; actualizarlo es un cambio aparte."
            )
        else:
            lines.append(f"- Versión: `{name}` {version} está al día.")

    for line in lines:
        print(line)
    _write_summary(lines)
    return out


if __name__ == "__main__":
    sys.exit(main())
