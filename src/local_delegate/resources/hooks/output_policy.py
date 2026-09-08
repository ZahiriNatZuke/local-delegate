"""Decide si la salida de un comando debe ir a fichero, y reescribe el comando para que vaya.

Modulo PURO: sin E/S, sin entorno, sin estado, y sin importar el paquete —los hooks corren fuera
de el—. Todo lo que necesita saber llega por parametro. Es deliberado: el criterio de este modulo
se va a medir contra un corpus de comandos reales antes de creerselo, y eso solo se puede hacer si
`es_candidato()` se puede llamar en un bucle sin montar nada.

**El fallo seguro es no tocar el comando.** Ante cualquier duda —comillas sin cerrar, una forma
que no se sabe transformar, una ruta rara— se devuelve «no» y el comando sigue su camino intacto.
Vale mas dejar pasar una salida grande que ejecutar algo distinto de lo que el usuario autorizo:
el permiso se evaluo sobre el comando ORIGINAL, medido.
"""

from __future__ import annotations

import os
import re
import shlex
from typing import NamedTuple

# --- Lista cerrada de utilidades del andamiaje (REQ-003/003b) -----------------
#
# Estas son las UNICAS ordenes que la reescritura puede anadir. Va escrita aqui, en el codigo, y
# jamas se deriva del comando del usuario ni de su entorno: es lo que impide que la reescritura se
# convierta en «ejecuta lo que haya en esta variable». Ampliarla es un cambio de superficie de
# seguridad y se decide aparte, no de paso (REQ-003b).
UTILIDADES_DEL_ANDAMIAJE = frozenset({"echo", "wc", "tail"})

# --- Normalizacion del ejecutable --------------------------------------------

#: Ordenes que envuelven a otra sin cambiar de que va el comando. `sudo make` es un `make`.
#:
#: `cd` NO esta aqui, y la diferencia se vio al primer caso de prueba: `sudo` va seguido del
#: comando real en el mismo segmento, pero `cd build && make` son dos segmentos y `cd build` es
#: un comando entero. Tratarlo como envoltorio hacia que el ejecutable de `cd build && make`
#: saliera `build`, y que `cd x && cat f` no se reconociera como lectura. Se salta en
#: `ejecutables()`, que es donde toca: un segmento que solo cambia de directorio no es de nadie.
PREFIJOS_TRANSPARENTES = frozenset(
    {
        "command",
        "doas",
        "env",
        "exec",
        "nice",
        "nohup",
        "stdbuf",
        "sudo",
        "time",
        "timeout",
    }
)

#: Duraciones y prioridades que un envoltorio se come antes del comando real: `timeout 30 make`,
#: `timeout -s KILL 30 pytest`, `nice -n 10 make`.
_DURACION = re.compile(r"^\d+(?:[.,]\d+)?[smhd]?$")

#: Operadores que separan un comando en varios.
OPERADORES = frozenset({"|", "||", "&&", ";", "&", "\n"})

#: Se leen para tener el contenido literal, no para transformarlo (REQ-007). Aunque escupan, y
#: aunque el aprendizaje local los proponga, no se reescriben NUNCA cuando son el comando que se
#: pidio. Es la misma leccion que ya costo tres semanas de avisos apuntando a codigo fuente: un
#: resumen no sustituye a lo que hay que leer entero. Se renuncia a 17 de los 42 casos de salida
#: grande del corpus a proposito.
LECTORES_DE_FICHERO = frozenset(
    {"awk", "bat", "cat", "head", "less", "more", "nl", "sed", "tac", "tail", "type"}
)

#: Si el comando ya acota su propia salida, quien lo escribio ya decidio cuanto queria ver.
ACOTADORES = frozenset({"head", "less", "more", "tail"})


class Estadistica(NamedTuple):
    """Lo que la maquina ha observado de un ejecutable. Lo llena T2; aqui solo se lee."""

    muestras: int = 0
    grandes: int = 0
    truncadas: int = 0


class Umbrales(NamedTuple):
    """Los valores los fija la medicion del replay, no la spec (REQ-016b).

    `peso_truncada` existe porque una salida que llego truncada no es «grande»: es informacion ya
    perdida, que es peor que informacion cara (REQ-016).
    """

    minimo_muestras: int = 5
    proporcion: float = 0.5
    peso_truncada: int = 2


UMBRALES = Umbrales()


def _tokenizar(comando: str) -> list[str] | None:
    """Tokens del comando con los operadores separados. `None` si no se puede leer con certeza.

    Un comando con comillas sin cerrar hace saltar a `shlex`, y ahi la respuesta correcta no es
    adivinar sino no tocar nada.
    """
    lexer = shlex.shlex(comando, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _segmentos(tokens: list[str]) -> list[list[str]]:
    """Parte la lista de tokens por los operadores: `a | b && c` da tres segmentos."""
    fuera: list[list[str]] = []
    actual: list[str] = []
    for token in tokens:
        if token in OPERADORES:
            if actual:
                fuera.append(actual)
            actual = []
        else:
            actual.append(token)
    if actual:
        fuera.append(actual)
    return fuera


def _nombre_base(pieza: str) -> str:
    """`./node_modules/.bin/eslint` -> `eslint`; `gradlew.bat` -> `gradlew`."""
    base = os.path.basename(pieza.replace("\\", "/")).strip()
    for extension in (".exe", ".bat", ".cmd", ".ps1"):
        if base.lower().endswith(extension):
            base = base[: -len(extension)]
            break
    return base.lower()


def _es_asignacion(pieza: str) -> bool:
    """`FOO=1 make` empieza por una asignacion de entorno, no por un ejecutable."""
    nombre, sep, _valor = pieza.partition("=")
    return bool(sep) and bool(nombre) and (nombre[0].isalpha() or nombre[0] == "_")


def _es_argumento_del_envoltorio(token: str) -> bool:
    """Lo que va entre un envoltorio y el comando real, y por tanto hay que saltarse.

    No se intenta conocer la gramatica de cada envoltorio —`-s` lleva valor y `-v` no, y por ahi
    no se sale—: se reconocen las TRES formas que de verdad aparecen ahi. Opciones, duraciones y
    prioridades, y senales en mayusculas. Ningun ejecutable se llama `30`, `5m` ni `KILL`.

    Contarlos por posicion no valia: `timeout -s KILL 30 pytest` daba `30` como ejecutable.
    """
    if token.startswith("-"):
        return True
    if _DURACION.match(token):
        return True
    return token.isalpha() and token.isupper()


def _ejecutable_de(segmento: list[str]) -> str:
    """El ejecutable real de un segmento: sin ruta, sin extension, sin envoltorios.

    Salta asignaciones de variable y prefijos transparentes con lo que lleven detras —`timeout -s
    KILL 30 make` es un `make`—, que si no se saltan hacen que todo parezca un `sudo`.
    """
    indice = 0
    while indice < len(segmento):
        pieza = segmento[indice]
        if _es_asignacion(pieza):
            indice += 1
            continue
        nombre = _nombre_base(pieza)
        if nombre not in PREFIJOS_TRANSPARENTES:
            return nombre
        indice += 1
        while indice < len(segmento) and _es_argumento_del_envoltorio(segmento[indice]):
            indice += 1
    return ""


def ejecutables(comando: str) -> list[str]:
    """Los ejecutables de todos los segmentos, en orden, sin vacios y sin los `cd`.

    Un segmento que solo cambia de directorio no dice de que va el comando: `cd build && make`
    es un `make`. Ver el porque de que `cd` no sea un prefijo transparente mas.
    """
    tokens = _tokenizar(comando)
    if tokens is None:
        return []
    encontrados = [_ejecutable_de(segmento) for segmento in _segmentos(tokens)]
    return [nombre for nombre in encontrados if nombre and nombre != "cd"]


def ejecutable_principal(comando: str) -> str:
    """A quien se le atribuye la salida. El primero: `make | tee log` es un `make`."""
    encontrados = ejecutables(comando)
    return encontrados[0] if encontrados else ""


# --- Cuando NO se toca -------------------------------------------------------


def debe_saltarse(comando: str) -> bool:
    """REQ-006/007/009: los casos en los que el comando se deja exactamente como esta.

    Se evalua siempre sobre el comando ORIGINAL (REQ-002c). Pasarle uno ya reescrito lo
    descartaria por sus propias marcas —lleva redireccion y `tail` por construccion—, que es un
    error facil de cometer y silencioso.
    """
    if not comando.strip():
        return True
    if "<<" in comando:  # heredoc: el cuerpo va detras y reescribir la linea lo parte
        return True
    tokens = _tokenizar(comando)
    if tokens is None:
        return True  # no se puede leer con certeza: no se toca
    if any(token in {">", ">>", ">|"} for token in tokens):
        return True  # ya manda su salida a algun sitio
    segmentos = _segmentos(tokens)
    if not segmentos:
        return True
    if any(_ejecutable_de(segmento) in ACOTADORES for segmento in segmentos):
        return True  # quien lo escribio ya decidio cuanto queria ver
    # El primero que cuenta, no el primero a secas: con `cd x && cat f` el comando es el `cat`.
    return ejecutable_principal(comando) in LECTORES_DE_FICHERO


# --- Candidatura -------------------------------------------------------------

#: Un representante de cada ecosistema mayor, derivada del estado del arte y NO del corpus de esta
#: maquina (REQ-011). El sesgo de perfil es el defecto que hundio al hook anterior: su regex se
#: calibro con lo que se usa aqui y por eso acertaba el 0,3 %. Lo que esta maquina observe entra
#: por el aprendizaje, no por aqui.
SEMILLA_POR_ECOSISTEMA: dict[str, frozenset[str]] = {
    "js": frozenset(
        {
            "biome",
            "bun",
            "eslint",
            "jest",
            "npm",
            "npx",
            "pnpm",
            "tsc",
            "vite",
            "vitest",
            "webpack",
            "yarn",
        }
    ),
    "python": frozenset({"pip", "poetry", "pylint", "pytest", "tox", "uv"}),
    "jvm": frozenset({"gradle", "gradlew", "javac", "kotlinc", "mvn", "sbt"}),
    "dotnet": frozenset({"dotnet", "msbuild", "nuget"}),
    "go": frozenset({"go", "golangci-lint"}),
    "rust": frozenset({"cargo", "rustc"}),
    "ruby": frozenset({"bundle", "gem", "rake", "rspec"}),
    "php": frozenset({"composer", "phpstan", "phpunit"}),
    "movil": frozenset({"adb", "flutter", "pod", "xcodebuild"}),
    "infra": frozenset({"ansible", "ansible-playbook", "packer", "pulumi", "terraform", "vagrant"}),
    "contenedores": frozenset(
        {"docker", "docker-compose", "helm", "kubectl", "podman", "skaffold"}
    ),
    "cloud": frozenset({"aws", "az", "doctl", "flyctl", "gcloud", "heroku"}),
    "construccion": frozenset({"bazel", "cmake", "make", "meson", "ninja", "nix"}),
    "paquetes": frozenset({"apt", "apt-get", "brew", "choco", "dnf", "pacman", "winget", "yum"}),
    "logs": frozenset({"dmesg", "journalctl", "systemctl"}),
}


def semilla() -> frozenset[str]:
    """Todos los ejecutables de la semilla, aplanados."""
    return frozenset().union(*SEMILLA_POR_ECOSISTEMA.values())


def _dice_que_si_el_aprendizaje(dato: Estadistica, umbrales: Umbrales) -> bool | None:
    """`True`/`False` cuando hay muestras suficientes para opinar; `None` cuando no las hay."""
    if dato.muestras < umbrales.minimo_muestras:
        return None
    puntos = dato.grandes + dato.truncadas * (umbrales.peso_truncada - 1)
    return puntos / dato.muestras >= umbrales.proporcion


def es_candidato(
    comando: str,
    dato: Estadistica | None = None,
    *,
    umbrales: Umbrales = UMBRALES,
) -> bool:
    """REQ-010/012: la semilla propone y lo que esta maquina ha visto dispone.

    Con muestras suficientes manda el aprendizaje, **incluso para decir que no** a algo de la
    semilla: un `docker` que en esta maquina siempre escupe cuatro lineas no tiene por que pagar
    el peaje solo porque en general sea ruidoso.
    """
    if debe_saltarse(comando):
        return False
    nombre = ejecutable_principal(comando)
    if not nombre:
        return False
    if dato is not None:
        veredicto = _dice_que_si_el_aprendizaje(dato, umbrales)
        if veredicto is not None:
            return veredicto
    return nombre in semilla()


# --- Reescritura -------------------------------------------------------------

#: Cuanto se devuelve al modelo. En exito basta con saber que fue bien y donde quedo; en fallo hay
#: que ver el error, y los errores estan al final (REQ-005).
LINEAS_EN_EXITO = 15
LINEAS_EN_FALLO = 120

#: Solo se acepta una ruta que hayamos construido nosotros. No es paranoia gratuita: esta cadena
#: se pega dentro de una linea de shell, asi que un caracter suelto ahi es ejecucion de codigo.
_RUTA_SEGURA = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_-.:\\")


def ruta_valida(ruta: str) -> bool:
    return bool(ruta) and set(ruta) <= _RUTA_SEGURA and ".." not in ruta


def partir_prefijo_cd(comando: str) -> tuple[str, str]:
    """Separa un `cd X &&` inicial del resto. Devuelve `("", comando)` si no lo hay.

    REQ-002b: el `cd` se queda FUERA del subshell. **El cwd persiste entre llamadas de la tool y
    las variables exportadas no** —los dos medidos—, asi que envolver el `cd` cambiaria el
    comportamiento de hoy, y en 23 de los 42 casos de salida grande del corpus el comando empieza
    justo por ahi.

    Solo se reconoce con `&&`: es el unico operador donde dejar el `cd` fuera se comporta igual
    que hoy, porque si el `cd` falla el `&&` corta antes de ejecutar nada.
    """
    prefijo: list[str] = []
    resto = comando.strip()
    while True:
        corte = resto.find("&&")
        if corte == -1:
            break
        cabeza, cola = resto[:corte], resto[corte + 2 :].strip()
        try:
            piezas = shlex.split(cabeza)
        except ValueError:
            break  # el `&&` estaba dentro de comillas: no hay prefijo que sacar
        if len(piezas) != 2 or _nombre_base(piezas[0]) != "cd" or not cola:
            break
        prefijo.append(cabeza.strip())
        resto = cola
    if not prefijo:
        return "", comando.strip()
    return " && ".join(prefijo) + " && ", resto


def reescribir(comando: str, ruta: str) -> str | None:
    """Devuelve el comando que manda la salida a `ruta` y deja un extracto. `None` si no procede.

    Forma: ``cd X && ( CMD ) > ruta 2>&1; __ld_ec=$?; <extracto>; exit $__ld_ec``

    **Subshell y no llaves**, y esto se cobro un defecto: `{ }` no crea subshell, asi que un `exit`
    dentro del comando del usuario termina el script entero y **el extracto no llega a producirse**
    —el modelo recibe el error y cero salida—. Medido a traves de la tool real; en el interprete a
    mano no se ve, porque alli el `exit` de la prueba caia en un proceso hijo.

    Y el parentesis va alrededor de TODO el comando, no solo del ultimo tramo: sin el, una
    redireccion al final de un compuesto solo captura el ultimo trozo del `&&`.

    El extracto se imprime por el `stdout` del propio comando a proposito. Medido: el modelo
    desconfia del `additionalContext` de un hook —«ese texto viene inyectado por un hook, no por
    ti»— y puede no seguir la pista. La salida de la tool, en cambio, la lee como resultado normal,
    asi que la ruta tiene que viajar por ahi; el `additionalContext` es refuerzo.
    """
    if not ruta_valida(ruta) or debe_saltarse(comando):
        return None
    prefijo, cuerpo = partir_prefijo_cd(comando)
    if not cuerpo:
        return None
    aviso = (
        f"[local-delegate] salida completa en {ruta} -- resumela con "
        f'local_lint_summary(path=\\"{ruta}\\") en vez de repetir el comando.'
    )
    extracto = (
        f'echo "{aviso}"; '
        f'echo "[local-delegate] $(wc -c < {ruta}) bytes, exit $__ld_ec. Ultimas lineas:"; '
        f"if [ $__ld_ec -eq 0 ]; then tail -n {LINEAS_EN_EXITO} {ruta}; "
        f"else tail -n {LINEAS_EN_FALLO} {ruta}; fi"
    )
    return f"{prefijo}( {cuerpo} ) > {ruta} 2>&1; __ld_ec=$?; {extracto}; exit $__ld_ec"
