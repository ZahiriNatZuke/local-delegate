"""Utilidades stdlib para hooks de local-delegate.

Hay dos caminos, y la diferencia es el corazon de F1: ``emit()`` **sugiere** y ``deny()``
**bloquea**. Cuatro mediciones seguidas dijeron que sugerir no cambia la conducta —la ultima con
el aviso acertando ya el tipo de fichero—, asi que lo que tenga que delegarse se decide por regla
y no por consejo.

La telemetria es opt-in y nunca escribe prompts, comandos ni paths: solo evento, categoria,
tamaño y banda. El log se activa con ``LD_HOOK_TELEMETRY_LOG``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path


def enabled() -> bool:
    """Interruptor del EXPERIMENTO, no el de encendido de un hook. La diferencia importa.

    `LD_HOOK_ENABLED=0` es lo que pone una sesion en rama baseline de un A/B: ni sugiere ni
    registra, para que el log de la rama piloto sea solo del piloto. Por eso apaga tambien la
    telemetria, que en cualquier otro contexto seria un error.

    **Solo puede apagar, nunca encender.** Que un hook este activo lo decide el registro
    (`settings.json`), y de ahi no se sale: cuando la unica puerta era una variable de entorno,
    `install --enable-read-hook` registro el script sin ponerla y el hook quedo instalado e
    inerte, en silencio. Esa es la historia que hay detras de `esta_encendido()` en
    `suggest_delegate_read.py`, y la razon de que ningun hook nuevo deba mirar aqui para saber
    si nacio encendido.
    """
    return os.environ.get("LD_HOOK_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def nuevo_id() -> str:
    """Identificador corto de un aviso o un bloqueo, para poder cruzarlo con lo que pase despues.

    Es lo que hace medible el «aceptado» de la telemetria: el hook y el servidor MCP son procesos
    distintos que escriben en ficheros distintos, y hasta ahora la unica forma de saber si un aviso
    acabo en delegacion era cruzarlos a mano.
    """
    return uuid.uuid4().hex[:12]


def version_de(script: str) -> str:
    """Huella del script que REALMENTE corrio: los ocho primeros hex de su sha256.

    Es un numero de version que nadie tiene que acordarse de subir, y sobre todo no es una segunda
    fuente de verdad —el defecto que mas veces ha mordido en este repo—. Lo que hace falta saber al
    leer una medicion no es que release estaba instalada, sino si el script que corrio era el nuevo
    o el viejo, y eso lo dice el contenido.

    Devuelve `""` si el fichero no se puede leer: un evento sin huella es peor que ninguno, pero
    romperle la lectura al usuario por un hash es mucho peor.
    """
    try:
        return hashlib.sha256(Path(script).read_bytes()).hexdigest()[:8]
    except OSError:
        return ""


def contexto_de(payload: dict, script: str) -> dict:
    """Los campos que lleva TODO evento: que script corrio y en que sesion.

    Sin esto una medicion no se puede leer: el 2026-09-09 catorce lecturas se comportaron con el
    umbral viejo despues de cambiarlo, porque una sesion ya abierta hereda el entorno del lanzador,
    y la muestra mezclo dos politicas sin que se notara.

    La hora de arranque de la sesion no se inventa aqui: con ``session_id`` en cada evento, el
    primer evento de esa sesion en el log ya dice cuando empezo, y agrupar por sesion evita mezclar
    dos politicas en la misma muestra.
    """
    return {"version": version_de(script), "session_id": str(payload.get("session_id") or "")}


def record(event: str, **metadata: object) -> None:
    if not enabled():
        return
    destination = os.environ.get("LD_HOOK_TELEMETRY_LOG", "").strip()
    if not destination:
        return
    payload = {"ts": datetime.now(UTC).isoformat(), "event": event, **metadata}
    try:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # La telemetría es best-effort y corre dentro de un hook del agente: si el destino no se
        # puede crear o escribir (permisos, disco lleno, ruta inválida en LD_HOOK_TELEMETRY_LOG),
        # perder una línea de log es preferible a romperle la operación al usuario.
        pass


def emit(event: str, context: str, **metadata: object) -> None:
    """Camino CONSULTIVO: le pasa un texto al modelo y el modelo hace lo que quiera con el."""
    if not enabled():
        return
    record(event, suggested=True, **metadata)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


def deny(event: str, razon: str, **metadata: object) -> None:
    """Camino que BLOQUEA: la tool no llega a ejecutarse y el modelo lee ``motivo``.

    El contrato es el de ``PreToolUseHookSpecificOutput``: ``permissionDecision`` acepta
    ``allow``, ``deny``, ``ask`` y ``defer``, y ``permissionDecisionReason`` —aqui ``razon``— es el texto
    que ve quien recibe el bloqueo. Se llama asi, y no ``motivo``, porque ``motivo`` es el campo
    con el que la telemetria de los hooks etiqueta cada decision y los dos viajan juntos. Ese texto **tiene que nombrar la salida**: una regla que dice «no»
    sin decir por donde se pasa es una regla que se acaba apagando.

    No se usa ``updatedInput``, que seria la forma de reescribir la llamada en vez de rechazarla:
    el permiso del usuario se evalua sobre la entrada original, asi que cambiarla por debajo
    ejecuta algo distinto de lo que se autorizo. Esa puerta se cerro con datos en la 0.27.0.
    """
    if not enabled():
        return
    record(event, suggested=True, blocked=True, **metadata)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": razon,
                }
            },
            ensure_ascii=False,
        )
    )


# --- Salud del backend ------------------------------------------------------------------------
#
# Una regla que bloquea una lectura tiene que saber si hay a donde delegar: si el backend local no
# responde, bloquear deja al agente sin forma de leer el fichero, y eso se apaga el primer dia.
#
# El dato NO puede salir de las delegaciones anteriores, aunque seria lo barato. Seria un circulo
# cerrado: sin delegaciones no hay marca fresca, sin marca fresca no se bloquea, y sin bloqueo no
# hay delegaciones. Con adopcion cero medida cuatro veces, la regla no arrancaria nunca. Asi que el
# hook se lo pregunta el mismo al backend, y guarda la respuesta un rato para no pagarlo en cada
# lectura.


def _ruta_de_salud() -> Path:
    """Un fichero por endpoint, no uno global.

    Con uno solo, la marca de un backend valdria para otro: basta cambiar
    `LOCAL_DELEGATE_BASE_URL` —o correr un test contra un puerto muerto— para heredar el «esta
    vivo» del anterior. Lo caza un test de instalacion que apuntaba a un puerto donde no hay nadie
    y recibia un bloqueo, porque la marca del backend de verdad seguia fresca.
    """
    base = os.environ.get("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1")
    huella = hashlib.sha256(base.encode("utf-8", "replace")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"local-delegate-salud-{huella}.json"


def _sondear(timeout_s: float) -> bool:
    """¿Contesta alguien en el endpoint? Un GET a /models con un plazo muy corto.

    La pregunta es si el backend **esta escuchando**, no si nos autoriza a nosotros: quien delega
    es el servidor MCP, que si tiene la credencial. Por eso un 401 o un 403 cuentan como «si
    esta»: alguien contesto. El hook casi nunca tiene la clave —la tiene el lanzador del daemon,
    y el hook hereda el entorno del cliente—, asi que tratar el 401 como «no hay backend» dejaria
    el bloqueo permanentemente apagado en cualquier maquina con el backend protegido. Medido en
    vivo: aqui `GET /v1/models` sin credencial responde 401, y el backend estaba perfectamente.

    Solo es «no esta» lo que no llega a haber respuesta: conexion rechazada, plazo agotado, o una
    URL que ni siquiera se puede construir.
    """
    base = os.environ.get("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1").rstrip("/")
    clave = os.environ.get("LOCAL_DELEGATE_API_KEY", "").strip()
    try:
        # El `Request` se construye DENTRO del try: con una `LOCAL_DELEGATE_BASE_URL` mal escrita
        # lanza `ValueError` en el constructor, no al abrir, y eso reventaria el hook entero y con
        # el la lectura del usuario.
        peticion = urllib.request.Request(f"{base}/models", method="GET")
        if clave:
            peticion.add_header("Authorization", f"Bearer {clave}")
        with urllib.request.urlopen(peticion, timeout=timeout_s) as respuesta:
            return respuesta.status < 500
    except urllib.error.HTTPError:
        # 401, 403, 404... da igual cual: hubo respuesta, luego hay alguien escuchando.
        return True
    except Exception:
        # Cualquier cosa: conexion rechazada, plazo agotado, 401, una URL invalida en la variable.
        # Ninguna es motivo para romperle la lectura al usuario, y todas significan lo mismo aqui.
        return False


def backend_disponible(*, ttl_s: float = 60.0, timeout_s: float = 0.3, marca: Path | None = None):
    """¿Hay a donde delegar ahora mismo? Ante la duda, **False**, que es lo que no bloquea.

    La respuesta se cachea ``ttl_s`` segundos en un fichero, asi que el sondeo se paga como mucho
    una vez por minuto y no una vez por lectura. Una marca ilegible, corrupta o vieja no se
    interpreta: se vuelve a preguntar.
    """
    archivo = marca or _ruta_de_salud()
    ahora = time.time()
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        if ahora - float(datos["ts"]) < ttl_s:
            return bool(datos["ok"])
    except (OSError, ValueError, KeyError, TypeError):
        pass

    disponible = _sondear(timeout_s)
    try:
        archivo.write_text(json.dumps({"ts": ahora, "ok": disponible}), encoding="utf-8")
    except OSError:
        # Sin cache se sondea mas a menudo; es lento, no incorrecto.
        pass
    return disponible


# --- Cruce entre el bloqueo y la delegacion que venga despues -----------------------------------
#
# El hook y el servidor MCP son procesos distintos que escriben en ficheros distintos, asi que
# hasta ahora «cuantos avisos acabaron en delegacion» solo se podia responder cruzando los dos
# logs a mano. Aqui el hook deja una nota con el identificador del bloqueo y una huella de la
# ruta, y el servidor la recoge cuando le llega una tool con ese mismo `path`.
#
# El identificador NO viaja por el agente: pedirle que lo pase seria depender de que obedezca, y
# lo que se quiere medir es justamente cuanto obedece.
#
# Se guarda la HUELLA de la ruta, no la ruta: este fichero hereda la regla de la telemetria de
# hooks, que nunca escribe rutas ni contenido.

#: Cuantas notas se conservan. Son el rastro de los ultimos bloqueos, no un historial.
MAX_NOTAS = 200


def huella_de_ruta(ruta: str) -> str:
    """Huella estable de una ruta, para poder cruzarla sin guardarla.

    Normaliza may/minusculas y separadores porque Windows da la misma ruta de varias formas y el
    hook la recibe del cliente mientras que el servidor la recibe del agente.
    """
    normal = os.path.normcase(os.path.abspath(ruta))
    return hashlib.sha256(normal.encode("utf-8", "replace")).hexdigest()[:16]


def ruta_de_notas() -> Path:
    return Path(tempfile.gettempdir()) / "local-delegate-bloqueos.jsonl"


def anotar_bloqueo(identificador: str, ruta: str, notas: Path | None = None) -> None:
    """Deja la nota del bloqueo. Best-effort: si falla, se pierde la medicion, no la sesion."""
    archivo = notas or ruta_de_notas()
    linea = json.dumps(
        {"id": identificador, "sha": huella_de_ruta(ruta), "ts": time.time()},
        ensure_ascii=False,
    )
    try:
        previas = archivo.read_text(encoding="utf-8").splitlines()[-(MAX_NOTAS - 1) :]
    except OSError:
        previas = []
    try:
        archivo.write_text("\n".join([*previas, linea]) + "\n", encoding="utf-8")
    except OSError:
        # Best-effort a proposito: perder esta nota cuesta una correlacion en la medicion;
        # romperle la lectura al usuario por no poder escribir un fichero cuesta mucho mas.
        pass
