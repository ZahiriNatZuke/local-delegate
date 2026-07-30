"""Tests de `local-delegate update`.

Ningún test sale a la red, escribe fuera de `tmp_path` ni lanza un proceso: el ejecutor de
comandos, el estado del daemon, el reloj y el `spawn` se inyectan por `Options`. Lo que más se
vigila aquí no es que una reparación funcione, sino **que no ocurra cuando no debe**: `unknown`
nunca repara, `warn` solo repara donde significa «es nuestro y está viejo», y un pid que no
confirmó `/api/daemon` no recibe ninguna señal.
"""

from __future__ import annotations

import subprocess

import pytest
from conftest import make_home, snapshot

from local_delegate import checks, install, update


def fake_run(returncode=0, stdout="", stderr=""):
    """Runner doble que registra lo que se le pidió ejecutar."""
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def opts_for(home, **kwargs):
    """Options con todo doblado: sin red, sin procesos y sin esperas reales."""
    defaults = {
        "runner": fake_run(),
        "daemon_status": lambda host, port: None,
        "sleep": lambda seconds: None,
        "clock": _fake_clock(),
        "spawn": lambda argv: None,
    }
    defaults.update(kwargs)
    return update.Options(home=home, **defaults)


def _fake_clock():
    """Reloj que avanza solo: sin esto, `wait_until_up` esperaría de verdad en los tests."""
    ticks = iter(range(10_000))

    def clock():
        return float(next(ticks))

    return clock


def results_from(**statuses):
    """Lista (Check, Result) con el estado que se pida por id; el resto en `ok`."""
    return [
        (check, checks.Result(statuses.get(check.id, checks.OK), f"detalle de {check.id}"))
        for check in checks.CHECKS
    ]


# --- La regla que ordena toda la tabla: `unknown` no repara -------------------


def test_unknown_no_repara_ninguno_de_los_doce_checks(tmp_path):
    """La regla que hereda de `checks`: lo que no se pudo comprobar no se toca.

    Se recorren los doce, no solo los reparables: si mañana entra un check nuevo a la tabla
    con `unknown` entre sus estados, este test lo caza.
    """
    home = make_home(tmp_path, complete=False)
    todos_unknown = {check.id: checks.UNKNOWN for check in checks.CHECKS}
    actions, _notes = update.plan_repairs(results_from(**todos_unknown), opts_for(home))
    assert actions == []


def test_warn_de_mcp_codex_no_produce_ninguna_accion(tmp_path):
    """Ese `warn` dice «entrada puesta a mano»: es configuración del usuario, no basura nuestra."""
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.mcp_codex": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert [a for a in actions if a.kind == "toml"] == []


def test_warn_de_hook_settings_si_repara(tmp_path):
    """Aquí `warn` significa «hooks nuestros en formato viejo», y reinstalarlos es lo correcto."""
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.hook_settings": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert any(a.kind == "settings" for a in actions)


def test_warn_de_skill_si_repara(tmp_path):
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.skill": checks.WARN})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert any(a.kind == "copy" and "skills" in str(a.target) for a in actions)


def test_no_se_repara_un_cliente_que_no_existe(tmp_path):
    """Con Codex ausente, un `missing` suyo no crea `~/.codex` de la nada."""
    home = make_home(tmp_path, claude=True, codex=False, complete=False)
    results = results_from(**{"scaffold.mcp_codex": checks.MISSING})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    assert [a for a in actions if "codex" in str(a.target).lower()] == []


# --- Deduplicación: dos borrados del mismo directorio serían un desastre ------


def test_hooks_incompletos_no_planifican_dos_borrados_del_mismo_directorio(tmp_path):
    """`plan_install` emite copia + registro, y la copia hace `rmtree` antes de copiar.

    Con `hook_files` y `hook_settings` los dos en `missing` se invoca dos veces, así que sin
    deduplicar habría **dos** acciones `copy` sobre el mismo destino: la segunda borraría lo
    que acababa de escribir la primera.
    """
    home = make_home(tmp_path, complete=False)
    results = results_from(
        **{"scaffold.hook_files": checks.MISSING, "scaffold.hook_settings": checks.MISSING}
    )
    actions, _notes = update.plan_repairs(results, opts_for(home))
    copias = [a for a in actions if a.kind == "copy" and "hooks" in str(a.target)]
    assert len(copias) == 1


# --- Idempotencia: sale del diseño, se comprueba contando acciones ------------


def test_un_home_completo_no_planifica_nada(tmp_path):
    home = make_home(tmp_path, complete=True)
    actions, _notes = update.plan_repairs(results_from(), opts_for(home))
    assert actions == []


def test_segunda_pasada_sobre_el_mismo_home_no_planifica_nada(tmp_path):
    """La prueba de la idempotencia de verdad: se repara y se vuelve a diagnosticar."""
    home = make_home(tmp_path, complete=False)
    ctx = _ctx(home)
    actions, _notes = update.plan_repairs(checks.run_all(ctx), opts_for(home))
    assert actions, "la primera pasada debía tener algo que reparar"
    install.apply(actions, dry_run=False, out=lambda *a: None)

    segunda, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
    assert segunda == []


def _ctx(home):
    return checks.Context(
        home=home,
        daemon_status=lambda host, port: None,
        backend_models=lambda: (True, ""),
        version_of=lambda component, cfg: ("v238", None),
        latest_release=checks.SKIP_PYPI,
    )


# --- `--dry-run` no escribe ni reinicia --------------------------------------


def test_dry_run_deja_el_arbol_byte_a_byte_igual(tmp_path):
    home = make_home(tmp_path, complete=False)
    antes = snapshot(home)
    opts = opts_for(home, dry_run=True)
    update.run_update(opts, out=lambda *a: None)
    assert snapshot(home) == antes


def test_dry_run_no_reinicia_el_daemon(tmp_path):
    runner = fake_run()
    opts = opts_for(make_home(tmp_path, complete=False), dry_run=True, runner=runner)
    update.run_update(opts, out=lambda *a: None)
    assert runner.calls == []


# --- Cómo está instalado esto -------------------------------------------------
# `update` actualiza el pin, el andamiaje y el daemon, pero NO el ejecutable de `uv tool`. Y no
# puede hacerlo: probado en Windows, reinstalar el entorno desde el que corre el proceso falla al
# borrar `Scripts/` y deja la instalación destruida (ya había borrado el paquete).


def _finge_prefix(monkeypatch, tmp_path, receipt: str | None):
    """Un `sys.prefix` de mentira, con o sin `uv-receipt.toml` dentro."""
    monkeypatch.setattr(update, "editable_origin", lambda: None)
    monkeypatch.setattr(update.sys, "prefix", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)
    if receipt is not None:
        (tmp_path / "uv-receipt.toml").write_text(receipt, encoding="utf-8")
    return tmp_path


def test_reconoce_una_instalacion_de_uv_tool(monkeypatch, tmp_path):
    _finge_prefix(
        monkeypatch, tmp_path, f'[tool]\nrequirements = [{{ name = "{update.PACKAGE}" }}]'
    )
    assert update.install_kind() == update.UV_TOOL
    assert update.upgrade_command() == update.UV_TOOL_UPGRADE


def test_sin_receipt_no_se_afirma_nada(monkeypatch, tmp_path):
    """`pip`, `pipx`, conda… no se adivina: comando genérico, no uno que podría fallar."""
    _finge_prefix(monkeypatch, tmp_path, None)
    assert update.install_kind() == update.OTHER
    assert update.upgrade_command() == update.GENERIC_UPGRADE


def test_un_receipt_de_otro_paquete_no_es_el_nuestro(monkeypatch, tmp_path):
    _finge_prefix(monkeypatch, tmp_path, '[tool]\nrequirements = [{ name = "otra-cosa" }]')
    assert update.install_kind() == update.OTHER


def test_la_editable_gana_sobre_el_receipt(monkeypatch, tmp_path):
    """Si se dieran los dos, manda la editable: es lo que gobierna de dónde sale el código."""
    _finge_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update, "editable_origin", lambda: tmp_path / "repo")
    assert update.install_kind() == update.EDITABLE
    assert "git -C" in update.upgrade_command()


def test_un_prefix_ilegible_no_revienta_la_deteccion(monkeypatch):
    monkeypatch.setattr(update, "editable_origin", lambda: None)
    monkeypatch.setattr(update.sys, "prefix", "\x00 ruta imposible \x00")
    assert update.install_kind() == update.OTHER


def test_el_aviso_de_uv_tool_da_la_version_y_el_comando(monkeypatch, tmp_path):
    _finge_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    texto = "\n".join(update.uv_tool_lines("0.18.0"))
    assert "0.17.0" in texto
    assert update.UV_TOOL_UPGRADE in texto
    assert "reinstalaría el entorno" in texto, "tiene que decir POR QUÉ no lo hace él"


@pytest.mark.parametrize("publicada", ["0.17.0", "0.16.0", None])
def test_sin_nada_que_avisar_el_bloque_no_aparece(monkeypatch, tmp_path, publicada):
    """Al día, por delante, o sin red: un aviso que sale siempre deja de leerse."""
    _finge_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    assert update.uv_tool_lines(publicada) == []


def test_una_editable_no_recibe_el_aviso_de_uv_tool(monkeypatch, tmp_path):
    """Ya tiene el suyo, con `git pull` + `uv sync`. Dos avisos serían uno de más."""
    monkeypatch.setattr(update, "editable_origin", lambda: tmp_path)
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    assert update.uv_tool_lines("0.18.0") == []


def test_el_aviso_de_uv_tool_cabe_en_la_consola_de_windows(monkeypatch, tmp_path):
    _finge_prefix(monkeypatch, tmp_path, f'[tool]\nname = "{update.PACKAGE}"')
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    "\n".join(update.uv_tool_lines("0.18.0")).encode("cp1252")
    update.GENERIC_UPGRADE.encode("cp1252")


def test_el_aviso_de_uv_tool_no_cambia_el_plan_ni_el_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda timeout=0: ("0.18.0", None))
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    home = make_home(tmp_path, complete=False)

    _finge_prefix(monkeypatch, tmp_path / "pref", f'[tool]\nname = "{update.PACKAGE}"')
    con: list[str] = []
    code_con = update.run_update(opts_for(home, dry_run=True), out=con.append)
    extra = update.uv_tool_lines("0.18.0")

    monkeypatch.setattr(update, "install_kind", lambda: update.OTHER)
    sin: list[str] = []
    code_sin = update.run_update(opts_for(home, dry_run=True), out=sin.append)

    assert code_con == code_sin
    assert extra, "el caso de uv tool debería aportar líneas"

    # Se ignoran las vacías: son maquetación, y el aviso añade una de separación. Lo que se
    # compara es el contenido — si el plan de acciones cambiara, aquí se vería.
    def sin_aviso(salida):
        return [x for x in salida if x.strip() and x not in extra]

    assert sin_aviso(con) == sin_aviso(sin)


# --- De dónde salió la versión, y el desfase tras publicar --------------------
# Justo después de publicar, `update` anuncia como «última» la anterior. Desde el comando no se
# puede distinguir «PyPI sirve caché» de «la publicación no ha terminado» —eso pediría medir
# durante una publicación real—, pero sí se puede detectar la firma del caso y decirla.


def test_la_version_pedida_a_mano_no_se_presenta_como_la_ultima_publicada():
    """`--version 0.17.0` no comprueba nada de PyPI; decir que es «la última» era mentira."""
    lineas = update.version_lines("0.17.0", None, from_user=True)
    assert lineas == ["Versión pedida con --version: 0.17.0"]
    assert not any("publicada" in line for line in lineas)


def test_la_version_consultada_dice_de_donde_salio(monkeypatch):
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    (linea,) = update.version_lines("0.17.0", None, from_user=False)
    assert "0.17.0" in linea
    assert update.PYPI_SOURCE in linea


def test_instalada_mas_nueva_que_la_publicada_avisa_y_recuerda_el_flag(monkeypatch):
    """La firma exacta de una release recién publicada que PyPI todavía no anuncia."""
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    texto = "\n".join(update.version_lines("0.16.0", None, from_user=False))
    assert "0.16.0" in texto and "0.17.0" in texto
    # La versión ya sustituida, no un placeholder: quien lee esto acaba de publicar y algo no le
    # cuadra; traducir `X.Y.Z` mentalmente es justo lo que no debe tener que hacer.
    assert "--version 0.17.0" in texto


def test_sin_desfase_no_hay_aviso(monkeypatch):
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    assert len(update.version_lines("0.17.0", None, from_user=False)) == 1
    assert len(update.version_lines("0.18.0", None, from_user=False)) == 1


@pytest.mark.parametrize("instalada", [None, "sin-numeros"])
def test_sin_con_que_comparar_se_calla(monkeypatch, instalada):
    """`unknown` no inventa: sin versión instalada utilizable, no hay aviso que dar."""
    monkeypatch.setattr(update.checks, "_installed_version", lambda: instalada)
    assert len(update.version_lines("0.16.0", None, from_user=False)) == 1


def test_sin_red_se_conserva_el_aviso_de_siempre():
    (linea,) = update.version_lines(None, "no se pudo consultar PyPI (URLError)", from_user=False)
    assert "no se pudo consultar PyPI" in linea
    assert "sin tocar los pines" in linea


def test_las_lineas_caben_en_la_consola_de_windows(monkeypatch):
    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    for args in [("0.16.0", None, True), ("0.16.0", None, False), (None, "motivo", False)]:
        version, reason, from_user = args
        "\n".join(update.version_lines(version, reason, from_user=from_user)).encode("cp1252")


def test_el_aviso_de_desfase_no_cambia_el_plan_ni_el_exit_code(tmp_path, monkeypatch):
    """Es información, no un cambio de comportamiento: `update` hace exactamente lo mismo."""
    monkeypatch.setattr(update, "latest_version", lambda timeout=0: ("0.16.0", None))
    home = make_home(tmp_path, complete=False)

    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.17.0")
    salida_con: list[str] = []
    code_con = update.run_update(opts_for(home, dry_run=True), out=salida_con.append)
    # Las líneas que aporta el aviso, tomadas **con la instalada todavía en 0.17.0**.
    extra = update.version_lines("0.16.0", None, from_user=False)[1:]

    monkeypatch.setattr(update.checks, "_installed_version", lambda: "0.16.0")
    salida_sin: list[str] = []
    code_sin = update.run_update(opts_for(home, dry_run=True), out=salida_sin.append)

    assert code_con == code_sin
    assert any("MÁS NUEVA" in line for line in salida_con), "no salió el aviso"
    assert not any("MÁS NUEVA" in line for line in salida_sin)

    # Y lo único que cambia es ese bloque: quitadas sus líneas exactas —las que `version_lines`
    # añade de más, no las que casen con un substring— las dos salidas son idénticas.
    assert extra, "el caso de desfase debería aportar líneas"
    assert [line for line in salida_con if line not in extra] == salida_sin


def test_pypi_se_consulta_una_sola_vez_en_todo_el_comando(tmp_path, monkeypatch):
    """`update` ya pregunta por la última versión; el check del registro no debe repetirlo.

    Se cuentan las consultas en vez de prohibirlas: la de `run_update` es legítima y necesaria,
    y lo que se vigila es que no aparezca una **segunda** por correr el diagnóstico.
    """
    consultas: list[float] = []

    def _espia(timeout=0.0):
        consultas.append(timeout)
        return "9.9.9", None

    monkeypatch.setattr(update, "latest_version", _espia)
    opts = opts_for(make_home(tmp_path, complete=False), dry_run=True)

    update.run_update(opts, out=lambda *a: None)

    assert len(consultas) == 1, f"PyPI se consultó {len(consultas)} veces en un solo comando"


# --- Los mecanismos de arranque ----------------------------------------------


@pytest.mark.parametrize(
    ("platform", "esperado", "comando"),
    [
        ("win32", update.SCHTASKS, "schtasks"),
        ("darwin", update.LAUNCHCTL, "launchctl"),
        ("linux", update.SYSTEMD, "systemctl"),
    ],
)
def test_detecta_el_mecanismo_registrado_de_cada_sistema(
    tmp_path, monkeypatch, platform, esperado, comando
):
    monkeypatch.setattr(update.sys, "platform", platform)
    runner = fake_run(returncode=0)
    assert update.detect_mechanism(opts_for(tmp_path, runner=runner)) == esperado
    assert runner.calls[0][0] == comando


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_sin_servicio_registrado_cae_al_fallback(tmp_path, monkeypatch, platform):
    """Estar en Windows no implica que la tarea exista: se pregunta de verdad."""
    monkeypatch.setattr(update.sys, "platform", platform)
    runner = fake_run(returncode=1)
    assert update.detect_mechanism(opts_for(tmp_path, runner=runner)) == update.FALLBACK


def test_el_mecanismo_que_falla_cae_al_fallback_y_relanza(tmp_path, monkeypatch):
    monkeypatch.setattr(update.sys, "platform", "linux")
    lanzados: list[list[str]] = []
    # `systemctl cat` responde (existe la unidad) pero `restart` falla.
    respuestas = iter([0, 1])

    def runner(argv):
        return subprocess.CompletedProcess(argv, next(respuestas), "", "unit failed")

    opts = opts_for(
        tmp_path,
        runner=runner,
        spawn=lanzados.append,
        daemon_status=lambda host, port: {"pid": 999, "version": "0.16.0"},
    )
    update.restart_daemon(opts, out=lambda *a: None)
    assert lanzados, "tras fallar el mecanismo registrado hay que relanzar por el fallback"


def test_el_pid_que_sobrevive_al_stop_del_servicio_recibe_la_senal(tmp_path, monkeypatch):
    """Parar el SERVICIO no siempre para el PROCESO, y se descubrió ejecutándolo en Windows.

    La tarea programada lanza `conhost -> powershell -> launcher`, y el launcher crea el daemon
    con `Start-Process`, o sea desacoplado. `schtasks /End` termina la cadena de la tarea y el
    nieto sobrevive con el puerto tomado: el `/Run` siguiente arranca una instancia que no puede
    escuchar y el reinicio se da por fallido con el daemon viejo todavía sirviendo.
    """
    monkeypatch.setattr(update.sys, "platform", "win32")
    matados: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: matados.append(pid))
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=0),
        # Siempre el mismo pid: el `/End` no lo mató.
        daemon_status=lambda host, port: {"pid": 41176, "version": "0.16.0"},
        spawn=lambda argv: None,
    )
    update.restart_daemon(opts, out=lambda *a: None)
    assert 41176 in matados


def test_el_mecanismo_que_si_para_el_proceso_no_recibe_senal_extra(tmp_path, monkeypatch):
    """`systemctl restart` para y arranca en un solo comando: ahí no hay nada que rematar."""
    monkeypatch.setattr(update.sys, "platform", "linux")
    matados: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: matados.append(pid))
    pids = iter([{"pid": 7, "version": "v"}, {"pid": 8, "version": "v"}])
    ultimo = {}

    def daemon_status(host, port):
        ultimo["v"] = next(pids, ultimo.get("v"))
        return ultimo["v"]

    opts = opts_for(tmp_path, runner=fake_run(0), daemon_status=daemon_status, spawn=lambda a: None)
    assert update.restart_daemon(opts, out=lambda *a: None) == 0
    assert matados == []


# --- REQ-008: el pid solo sale de /api/daemon --------------------------------


def test_sin_daemon_vivo_no_se_envia_ninguna_senal(tmp_path, monkeypatch):
    """El caso del pid reciclado: `daemon.json` puede tener un pid ajeno, y nunca se lee.

    Si `/api/daemon` no responde, no hay pid que señalar: se trata como caído y se levanta.
    """
    matados: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: matados.append(pid))
    monkeypatch.setattr(update.sys, "platform", "linux")
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=1),  # sin servicio registrado -> fallback
        daemon_status=lambda host, port: None,
        spawn=lambda argv: None,
    )
    update.restart_daemon(opts, out=lambda *a: None)
    assert matados == []


def test_el_daemon_que_no_vuelve_sale_con_codigo_distinto_de_cero(tmp_path, monkeypatch):
    monkeypatch.setattr(update.sys, "platform", "linux")
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=0),
        daemon_status=lambda host, port: None,
        spawn=lambda argv: None,
    )
    assert update.restart_daemon(opts, out=lambda *a: None) == 1


def test_se_exige_que_el_pid_cambie_tras_reiniciar(tmp_path, monkeypatch):
    """REQ-005: si vuelve el MISMO pid, el servicio no reinició y no vale darlo por bueno."""
    monkeypatch.setattr(update.sys, "platform", "linux")
    opts = opts_for(
        tmp_path,
        runner=fake_run(returncode=0),
        daemon_status=lambda host, port: {"pid": 7, "version": "0.16.0"},
        spawn=lambda argv: None,
    )
    assert update.restart_daemon(opts, out=lambda *a: None) == 1


def test_el_reinicio_correcto_devuelve_cero(tmp_path, monkeypatch):
    monkeypatch.setattr(update.sys, "platform", "linux")
    pids = iter([{"pid": 7, "version": "0.16.0"}, {"pid": 8, "version": "0.16.0"}])
    ultimo = {}

    def daemon_status(host, port):
        ultimo["v"] = next(pids, ultimo.get("v"))
        return ultimo["v"]

    opts = opts_for(
        tmp_path, runner=fake_run(returncode=0), daemon_status=daemon_status, spawn=lambda a: None
    )
    assert update.restart_daemon(opts, out=lambda *a: None) == 0


# --- El pin: paridad con el bash ---------------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_el_pin_conserva_el_terminador_de_linea(tmp_path, newline):
    """Escribir con el terminador de la plataforma marcaría el fichero entero como modificado."""
    path = tmp_path / ".claude.json"
    raw = '{{"mcpServers": {{"local-delegate": {{"args": ["--from", "local-delegate-mcp==0.13.0"]}}}}}}'
    path.write_bytes(raw.format().replace("\n", newline).encode("utf-8"))
    original = path.read_bytes()

    actions = update.plan_pin(update.Options(home=tmp_path), "0.16.0")
    assert len(actions) == 1
    install.apply(actions, dry_run=False, out=lambda *a: None)

    escrito = path.read_bytes()
    assert b"local-delegate-mcp==0.16.0" in escrito
    assert (b"\r\n" in escrito) == (b"\r\n" in original)
    assert (tmp_path / ".claude.json.bak").is_file()


def test_sin_pin_no_hay_nada_que_cambiar(tmp_path):
    """Sin `==X.Y.Z`, uvx ya resuelve la última en cada arranque."""
    (tmp_path / ".claude.json").write_text(
        '{"mcpServers": {"local-delegate": {"args": ["--from", "local-delegate-mcp"]}}}',
        encoding="utf-8",
    )
    assert update.plan_pin(update.Options(home=tmp_path), "0.16.0") == []


def test_un_pin_ya_al_dia_no_se_toca(tmp_path):
    (tmp_path / ".claude.json").write_text("local-delegate-mcp==0.16.0", encoding="utf-8")
    assert update.plan_pin(update.Options(home=tmp_path), "0.16.0") == []


def test_sin_entrada_del_paquete_no_se_toca(tmp_path):
    (tmp_path / ".claude.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    assert update.plan_pin(update.Options(home=tmp_path), "0.16.0") == []


def test_sin_red_se_avisa_y_se_sigue_con_exito(tmp_path, monkeypatch):
    """Edge case de la spec: PyPI caído no impide completar el andamiaje ni reiniciar."""
    monkeypatch.setattr(update, "latest_version", lambda *a, **k: (None, "sin red"))
    salida: list[str] = []
    opts = opts_for(make_home(tmp_path, complete=True), no_restart=True)
    assert update.run_update(opts, out=salida.append) == 0
    assert any("sin red" in line for line in salida)


# --- El backend no se toca salvo que se pida ---------------------------------


def test_sin_la_flag_no_hay_ni_una_invocacion_al_backend(tmp_path, monkeypatch):
    """REQ-012: reiniciar el daemon no puede descargar los modelos de la VRAM."""
    llamado = []
    monkeypatch.setattr(update, "restart_backend", lambda *a, **k: llamado.append(1) or 0)
    opts = opts_for(make_home(tmp_path, complete=True), no_restart=True)
    update.run_update(opts, out=lambda *a: None)
    assert llamado == []


def test_con_backend_remoto_no_se_intenta_nada(tmp_path, monkeypatch):
    """El caso de la Mac apuntando a la PC: no hay backend local que reiniciar, y no es error."""
    monkeypatch.setattr(update.config, "backend_origin", lambda *a: "remote")
    runner = fake_run()
    salida: list[str] = []
    assert update.restart_backend(opts_for(tmp_path, runner=runner), out=salida.append) == 0
    assert runner.calls == []
    assert any("remoto" in line for line in salida)


def test_un_puerto_ocupado_por_otro_proceso_no_recibe_senal(tmp_path, monkeypatch):
    """Dos confirmaciones antes de señalar: el host dice «local», pero el proceso manda."""
    monkeypatch.setattr(update.config, "backend_origin", lambda *a: "local")
    monkeypatch.setattr(update, "_port_owner", lambda opts, port: 1234)
    monkeypatch.setattr(update, "_process_name", lambda opts, pid: "nginx.exe")
    matados: list[int] = []
    monkeypatch.setattr(update.os, "kill", lambda pid, sig: matados.append(pid))
    assert update.restart_backend(opts_for(tmp_path), out=lambda *a: None) == 1
    assert matados == []


# --- Instalación editable (PEP 610) ------------------------------------------


class _FakeDistribution:
    def __init__(self, payload):
        self.payload = payload

    def read_text(self, name):
        return self.payload


@pytest.mark.parametrize(
    ("payload", "espera_ruta"),
    [
        ('{"url": "file:///repo", "dir_info": {"editable": true}}', True),
        ('{"url": "file:///repo", "dir_info": {"editable": false}}', False),
        ('{"url": "https://pypi.org/x.whl"}', False),
        (None, False),
        ("no es json", False),
    ],
)
def test_deteccion_de_instalacion_editable(monkeypatch, payload, espera_ruta):
    monkeypatch.setattr(
        update.metadata.Distribution,
        "from_name",
        staticmethod(lambda name: _FakeDistribution(payload)),
    )
    assert (update.editable_origin() is not None) is espera_ruta


def test_sin_metadatos_no_se_asume_editable(monkeypatch):
    def boom(name):
        raise update.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(update.metadata.Distribution, "from_name", staticmethod(boom))
    assert update.editable_origin() is None


# --- El HOME simulado no toca servicios --------------------------------------


def test_home_simulado_no_reinicia_el_daemon_real(tmp_path):
    """B-3: el daemon no se deriva de `ctx.home`, así que sin esta regla `--home /tmp` reiniciaría
    el servicio de verdad de la máquina."""
    runner = fake_run()
    opts = opts_for(make_home(tmp_path, complete=True), runner=runner)
    assert opts.simulated_home is True
    update.run_update(opts, out=lambda *a: None)
    assert runner.calls == []


def test_home_simulado_no_registra_el_mcp_por_la_cli_del_cliente(tmp_path):
    """`claude mcp add-json --scope user` escribe en el `~/.claude.json` REAL, ignorando `home`.

    Se descubrió ejecutando `update --home <tmp>` dos veces: la segunda volvía a planificar la
    misma acción —el probe seguía viendo vacío el árbol simulado— mientras la configuración de
    verdad sí se había reescrito. Con HOME simulado hay que escribir el fichero a mano.
    """
    home = make_home(tmp_path, complete=False)
    results = results_from(**{"scaffold.mcp_claude": checks.MISSING})
    actions, _notes = update.plan_repairs(results, opts_for(home))
    mcp = [a for a in actions if a.kind == "mcp"]
    assert len(mcp) == 1
    install.apply(mcp, dry_run=False, out=lambda *a: None)
    # La prueba de que no salió del árbol: la entrada quedó en el .claude.json simulado.
    assert (home / ".claude.json").is_file()
    assert install.SERVER_NAME in (home / ".claude.json").read_text(encoding="utf-8")


# --- Los nombres canónicos viven en un solo sitio ----------------------------


def test_los_nombres_del_servicio_coinciden_con_la_wiki():
    """Si el módulo y la receta se separan, `update` busca un servicio que nadie registró."""
    from pathlib import Path as _Path

    wiki = _Path(__file__).resolve().parents[1] / "docs" / "wiki" / "Daemon.md"
    texto = wiki.read_text(encoding="utf-8")
    for nombre in (update.TASK_NAME, update.LAUNCH_LABEL, update.SYSTEMD_UNIT):
        assert nombre in texto, f"{nombre} no aparece en docs/wiki/Daemon.md"
