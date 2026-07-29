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

RAIZ = Path(__file__).resolve().parents[1]
MANIFIESTO_POR_DEFECTO = RAIZ / "src" / "local_delegate" / "resources" / "vendor" / "vendor.json"

OSV_URL = "https://api.osv.dev/v1/query"
NPM_URL = "https://registry.npmjs.org/{name}/latest"
TIMEOUT_S = 15

OK = 0
FALLO_INTEGRIDAD = 1
FALLO_VULNERABILIDAD = 2
FALLO_MANIFIESTO = 3


class ServicioNoDisponible(Exception):
    """La red falló, o el servicio devolvió algo que no se puede interpretar.

    Se trata igual una caída que una respuesta malformada: en ambos casos no sabemos nada, y no
    saber nada no puede tumbar un PR.
    """


# --- red ---------------------------------------------------------------------------------------
# Toda la salida a internet pasa por aquí. Los tests sustituyen esta función y por eso nunca tocan
# la red de verdad.
def _pedir_json(url: str, payload: dict | None = None) -> dict:
    datos = json.dumps(payload).encode("utf-8") if payload is not None else None
    # Las URLs son constantes https de este módulo, nunca entrada de usuario.
    peticion = urllib.request.Request(
        url,
        data=datos,
        headers={"Content-Type": "application/json", "User-Agent": "local-delegate-vendor-audit"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
            cuerpo = respuesta.read().decode("utf-8")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ServicioNoDisponible(str(exc)) from exc
    try:
        cuerpo = json.loads(cuerpo)
    except json.JSONDecodeError as exc:
        raise ServicioNoDisponible(f"respuesta que no es JSON: {exc}") from exc
    if not isinstance(cuerpo, dict):
        raise ServicioNoDisponible("respuesta JSON que no es un objeto")
    return cuerpo


def consultar_osv(nombre: str, version: str, ecosistema: str) -> list[dict]:
    """Vulnerabilidades conocidas de esa versión. Lanza `ServicioNoDisponible` si no se sabe."""
    respuesta = _pedir_json(
        OSV_URL, {"package": {"name": nombre, "ecosystem": ecosistema}, "version": version}
    )
    vulns = respuesta.get("vulns", [])
    if not isinstance(vulns, list):
        raise ServicioNoDisponible("OSV devolvió un campo `vulns` que no es una lista")
    return vulns


def consultar_npm(nombre: str) -> str:
    """Última versión publicada. Lanza `ServicioNoDisponible` si no se sabe."""
    respuesta = _pedir_json(NPM_URL.format(name=nombre))
    version = respuesta.get("version")
    if not isinstance(version, str) or not version:
        raise ServicioNoDisponible("npm no devolvió un campo `version` utilizable")
    return version


def _clave_version(version: str) -> tuple[int, ...] | None:
    """`4.4.1` -> `(4, 4, 1)`. `None` si no es comparable (prerelease, formato raro)."""
    partes = version.split("-")[0].split(".")
    if not partes:
        return None
    try:
        return tuple(int(p) for p in partes)
    except ValueError:
        return None


# --- integridad (offline) ----------------------------------------------------------------------
def cargar_manifiesto(ruta: Path) -> dict:
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(contenido, dict) or not isinstance(contenido.get("files"), list):
        # ValueError y no TypeError (TRY004): quien llama recibe un fichero, no un objeto de un
        # tipo equivocado — el problema es que su *contenido* no sirve, y `main` lo trata igual
        # que un JSON roto o un fichero ilegible.
        raise ValueError("el manifiesto no tiene una lista `files`")  # noqa: TRY004
    return contenido


def comprobar_integridad(manifiesto: dict, directorio: Path) -> list[str]:
    """Errores de integridad. Lista vacía = todo cuadra. No toca la red."""
    errores: list[str] = []
    declarados: set[str] = set()

    for entrada in manifiesto["files"]:
        nombre_fichero = entrada.get("file")
        if not nombre_fichero:
            errores.append("hay una entrada del manifiesto sin campo `file`")
            continue
        declarados.add(nombre_fichero)
        # La licencia se declara para que el chequeo de sincronía no la vea como intrusa, pero su
        # contenido no se hashea: no es código que se sirva.
        if entrada.get("licenseFile"):
            declarados.add(entrada["licenseFile"])

        ruta = directorio / nombre_fichero
        if not ruta.is_file():
            errores.append(f"{nombre_fichero}: declarado en el manifiesto pero NO existe en disco")
            continue

        datos = ruta.read_bytes()
        real = hashlib.sha256(datos).hexdigest()
        esperado = entrada.get("sha256")
        if real != esperado:
            mensaje = (
                f"{nombre_fichero}: el sha256 no coincide.\n"
                f"    esperado: {esperado}\n"
                f"    real:     {real}\n"
                f"    ({len(datos)} bytes en disco, {entrada.get('bytes')} declarados)"
            )
            # La causa más probable en Windows no es un fichero adulterado: es git convirtiendo
            # los LF en CRLF al hacer checkout (`core.autocrlf=true`, el valor por defecto de Git
            # for Windows). Decirlo aquí ahorra buscar un ataque donde solo hay un fin de línea.
            if b"\r\n" in datos and len(datos) > (entrada.get("bytes") or 0):
                mensaje += (
                    "\n    PISTA: el fichero tiene CRLF y pesa de más. Casi seguro que git te lo"
                    "\n    normalizó al clonar. Comprueba que `.gitattributes` marca este"
                    "\n    directorio con `-text` y vuelve a hacer checkout del fichero."
                )
            errores.append(mensaje)
        elif entrada.get("bytes") is not None and len(datos) != entrada["bytes"]:
            # Con el hash bueno el tamaño no puede diferir; si difiere, el manifiesto miente.
            errores.append(
                f"{nombre_fichero}: el hash cuadra pero el tamaño declarado no "
                f"({entrada['bytes']} frente a {len(datos)} reales)"
            )

    # Un fichero vendorizado sin declarar es exactamente el punto ciego que esto viene a cerrar.
    presentes = {p.name for p in directorio.iterdir() if p.is_file()}
    intrusos = sorted(presentes - declarados - {"vendor.json"})
    for intruso in intrusos:
        errores.append(f"{intruso}: está en `vendor/` pero NO figura en el manifiesto")

    return errores


# --- informe -----------------------------------------------------------------------------------
def _escribir_summary(lineas: list[str]) -> None:
    """Vuelca el informe al summary del job, si estamos en Actions."""
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    try:
        with open(destino, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lineas) + "\n")
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
        default=MANIFIESTO_POR_DEFECTO,
        help="ruta del manifiesto (por defecto, el del paquete)",
    )
    args = parser.parse_args(argv)

    manifiesto_ruta: Path = args.manifest
    try:
        manifiesto = cargar_manifiesto(manifiesto_ruta)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FALLO: no se pudo leer el manifiesto {manifiesto_ruta}: {exc}")
        return FALLO_MANIFIESTO

    directorio = manifiesto_ruta.parent
    lineas: list[str] = ["## Auditoría del vendorizado"]
    salida = OK

    errores = comprobar_integridad(manifiesto, directorio)
    if errores:
        salida = FALLO_INTEGRIDAD
        lineas.append("")
        lineas.append("**INTEGRIDAD ROTA.** El contenido vendorizado no es el declarado:")
        lineas.extend(f"- {e}" for e in errores)
        lineas.append("")
        lineas.append(
            "Si el cambio es intencionado, actualiza `vendor.json` siguiendo "
            "`docs/wiki/Repo-hardening.md`. Si no lo es, **investígalo antes de tocar nada**."
        )
    else:
        lineas.append("")
        lineas.append("- Integridad: OK, cada fichero coincide con su sha256 declarado.")

    if args.offline:
        lineas.append("- Red: omitida (`--offline`).")
        for linea in lineas:
            print(linea)
        _escribir_summary(lineas)
        return salida

    for entrada in manifiesto["files"]:
        nombre = entrada.get("name")
        version = entrada.get("version")
        ecosistema = entrada.get("ecosystem", "npm")
        if not nombre or not version:
            continue

        try:
            vulns = consultar_osv(nombre, version, ecosistema)
        except ServicioNoDisponible as exc:
            lineas.append(f"- AVISO: no se pudo consultar OSV para `{nombre}` {version}: {exc}")
        else:
            if vulns:
                # La integridad rota manda: es el diagnóstico más grave y el más fiable.
                if salida == OK:
                    salida = FALLO_VULNERABILIDAD
                ids = ", ".join(str(v.get("id", "?")) for v in vulns)
                lineas.append("")
                lineas.append(
                    f"**VULNERABILIDAD.** OSV reporta {len(vulns)} para `{nombre}` {version}: {ids}"
                )
                lineas.append("")
            else:
                lineas.append(f"- CVEs: OSV no conoce ninguna para `{nombre}` {version}.")

        try:
            ultima = consultar_npm(nombre)
        except ServicioNoDisponible as exc:
            lineas.append(f"- AVISO: no se pudo consultar npm para `{nombre}`: {exc}")
            continue

        actual_k, ultima_k = _clave_version(version), _clave_version(ultima)
        if actual_k is None or ultima_k is None:
            lineas.append(
                f"- AVISO: no se pudieron comparar las versiones de `{nombre}` "
                f"(vendorizada {version}, publicada {ultima})."
            )
        elif ultima_k > actual_k:
            lineas.append(
                f"- AVISO: `{nombre}` vendorizado en **{version}**, publicado **{ultima}**. "
                "No rompe el CI; actualizarlo es un cambio aparte."
            )
        else:
            lineas.append(f"- Versión: `{nombre}` {version} está al día.")

    for linea in lineas:
        print(linea)
    _escribir_summary(lineas)
    return salida


if __name__ == "__main__":
    sys.exit(main())
