"""El módulo que decide si la salida de un comando va a fichero, y cómo se reescribe.

Es puro a propósito —sin E/S ni entorno— porque su criterio se va a medir contra un corpus de
comandos reales antes de creérselo, y eso solo se puede hacer llamándolo en un bucle.

El listón de estos tests es más alto que el de un hook consultivo: aquí un fallo no es un consejo
malo, es **un comando distinto del que el usuario autorizó**, porque el permiso se evaluó sobre
el original. De ahí que haya controles negativos en casi todos.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = _load("output_policy")

RUTA = "/tmp/local-delegate/bash-abc123.log"


# --- Normalización del ejecutable --------------------------------------------


def test_el_ejecutable_es_el_comando_real_y_no_su_envoltorio():
    casos = {
        "make": "make",
        "sudo make": "make",
        "FOO=1 make": "make",
        "env FOO=1 npm test": "npm",
        "nice -n 10 make": "make",
        "timeout 30 make": "make",
        # Contar argumentos por posición daba `30` aquí: `-s` lleva valor y `-v` no.
        "timeout -s KILL 30 pytest": "pytest",
        "./node_modules/.bin/eslint .": "eslint",
        # Con barras normales: la tool corre un shell POSIX, donde la barra invertida es un
        # escape, y una ruta de Windows escrita a pelo se lee como `C:toolsgradlew.bat`. El
        # tokenizador es fiel al shell a propósito, así que el caso realista es este.
        "C:/tools/gradlew.bat build": "gradlew",
        "make | tee log": "make",
        # `cd X && cmd` son dos segmentos y `cd X` es un comando entero, no un envoltorio:
        # tratarlo como `sudo` hacía que el ejecutable saliera `build`.
        "cd build && make": "make",
        "cd app && npm run build": "npm",
        "cd a && cd b && cargo test": "cargo",
    }
    for comando, esperado in casos.items():
        assert policy.ejecutable_principal(comando) == esperado, comando


def test_un_comando_que_solo_cambia_de_directorio_no_es_de_nadie():
    assert policy.ejecutable_principal("cd build") == ""
    assert policy.es_candidato("cd build") is False


def test_unas_comillas_sin_cerrar_no_se_adivinan():
    """El fallo seguro es no tocar: ante un comando que no se puede leer con certeza, nada."""
    roto = "make 'sin cerrar"
    assert policy.ejecutable_principal(roto) == ""
    assert policy.debe_saltarse(roto) is True
    assert policy.reescribir(roto, RUTA) is None


# --- Cuándo NO se toca -------------------------------------------------------


def test_no_se_toca_lo_que_ya_manda_su_salida_a_algun_sitio():
    for comando in ("make > out.log", "make >> out.log 2>&1", "pytest > /dev/null"):
        assert policy.debe_saltarse(comando) is True, comando
        assert policy.reescribir(comando, RUTA) is None, comando


def test_no_se_toca_lo_que_ya_acota_su_salida():
    for comando in ("make | head -50", "pytest | tail -n 20", "git log | less"):
        assert policy.debe_saltarse(comando) is True, comando


def test_no_se_toca_un_heredoc():
    """El cuerpo va detrás en líneas siguientes: reescribir la primera lo parte por la mitad."""
    assert policy.debe_saltarse("cat <<'EOF'\nhola\nEOF") is True


def test_los_lectores_de_fichero_no_se_reescriben_nunca():
    """REQ-007: aunque escupan y aunque el aprendizaje los proponga.

    El aprendizaje se le pasa al máximo —diez de diez grandes— justo para que el test discrimine:
    sin la guarda, esa estadística los haría candidatos.
    """
    a_tope = policy.Estadistica(muestras=10, grandes=10, truncadas=10)
    for comando in ("cat enorme.log", "sed -n '1,2000p' x.py", "cd x && cat f", "awk '{print}' f"):
        assert policy.debe_saltarse(comando) is True, comando
        assert policy.es_candidato(comando, a_tope) is False, comando


def test_el_control_de_que_esa_estadistica_haria_candidato_a_otro():
    """Sin esto, el test de arriba pasaría igual con una estadística que no convence a nadie."""
    a_tope = policy.Estadistica(muestras=10, grandes=10, truncadas=10)
    assert policy.es_candidato("mi-binario-raro --todo", a_tope) is True


# --- Candidatura -------------------------------------------------------------


def test_la_semilla_cubre_todos_los_ecosistemas_mayores():
    """REQ-011: no se limita a los que usa el autor, que es lo que hundió al hook anterior."""
    esperados = {
        "js",
        "python",
        "jvm",
        "dotnet",
        "go",
        "rust",
        "ruby",
        "php",
        "movil",
        "infra",
        "contenedores",
        "cloud",
        "construccion",
        "paquetes",
        "logs",
    }
    assert esperados <= set(policy.SEMILLA_POR_ECOSISTEMA)
    assert all(policy.SEMILLA_POR_ECOSISTEMA[nombre] for nombre in esperados)


def test_sin_aprendizaje_manda_la_semilla():
    assert policy.es_candidato("cargo build") is True
    assert policy.es_candidato("mi-script-propio") is False


def test_con_pocas_muestras_el_aprendizaje_todavia_no_opina():
    """Cuatro muestras no son un patrón. Manda la semilla, y en los dos sentidos."""
    pocas = policy.Estadistica(muestras=4, grandes=0, truncadas=0)
    assert policy.es_candidato("cargo build", pocas) is True
    pocas_grandes = policy.Estadistica(muestras=4, grandes=4, truncadas=0)
    assert policy.es_candidato("mi-script-propio", pocas_grandes) is False


def test_lo_que_esta_maquina_ha_visto_puede_contradecir_a_la_semilla():
    """REQ-012: en los dos sentidos, que es lo que lo hace un aprendizaje y no un adorno."""
    calla = policy.Estadistica(muestras=20, grandes=1, truncadas=0)
    assert policy.es_candidato("docker ps", calla) is False  # está en la semilla y aun así no

    escupe = policy.Estadistica(muestras=20, grandes=18, truncadas=0)
    assert policy.es_candidato("mi-script-propio", escupe) is True  # no está y aun así sí


def test_una_salida_truncada_pesa_mas_que_una_grande():
    """REQ-016: truncada es información ya perdida, no solo cara.

    Las dos estadísticas tienen el mismo número de muestras y la misma cuenta de «grandes»; lo
    único que cambia es que en una llegaron truncadas. Si el peso no existiera, las dos darían
    igual y el test no distinguiría nada.
    """
    umbrales = policy.Umbrales(minimo_muestras=5, proporcion=0.5, peso_truncada=2)
    solo_grandes = policy.Estadistica(muestras=10, grandes=3, truncadas=0)
    con_truncadas = policy.Estadistica(muestras=10, grandes=3, truncadas=3)
    assert policy.es_candidato("mi-script", solo_grandes, umbrales=umbrales) is False
    assert policy.es_candidato("mi-script", con_truncadas, umbrales=umbrales) is True


# --- Reescritura -------------------------------------------------------------


def _partes(reescrito: str) -> tuple[str, str, str]:
    """`prefijo`, `cuerpo` (lo del usuario) y `andamiaje` (lo nuestro)."""
    prefijo, marca, resto = reescrito.partition("( ")
    assert marca, reescrito
    cuerpo, marca, andamiaje = resto.partition(" ) > ")
    assert marca, reescrito
    return prefijo, cuerpo, andamiaje


def test_el_comando_del_usuario_va_dentro_de_un_subshell_y_no_de_unas_llaves():
    """Medido a través de la tool real: con `{ }` un `exit` del comando mata el script entero y
    **el extracto no llega a producirse**. En el intérprete a mano no se ve."""
    salida = policy.reescribir("make", RUTA)
    assert salida.startswith("( make ) > ")
    assert "{ make" not in salida


def test_la_redireccion_envuelve_el_compuesto_entero():
    """Sin el paréntesis, un `>` al final de un `&&` solo captura el último tramo."""
    _prefijo, cuerpo, _andamiaje = _partes(policy.reescribir("npm ci && npm run build", RUTA))
    assert cuerpo == "npm ci && npm run build"


def test_el_codigo_de_salida_del_comando_original_se_preserva():
    salida = policy.reescribir("make", RUTA)
    assert "__ld_ec=$?" in salida
    assert salida.endswith("exit $__ld_ec")


def test_el_prefijo_cd_se_queda_fuera_del_subshell():
    """REQ-002b: el cwd persiste entre llamadas de la tool (medido) y 23 de los 42 casos de
    salida grande del corpus empiezan por `cd`. Envolverlo cambiaría el comportamiento de hoy."""
    salida = policy.reescribir("cd build && make -j4", RUTA)
    prefijo, cuerpo, _andamiaje = _partes(salida)
    assert prefijo == "cd build && "
    assert cuerpo == "make -j4"


def test_el_prefijo_cd_encadenado_tambien():
    prefijo, cuerpo, _ = _partes(policy.reescribir("cd a && cd b && cargo test", RUTA))
    assert prefijo == "cd a && cd b && "
    assert cuerpo == "cargo test"


def test_un_operador_dentro_de_comillas_no_es_un_prefijo_cd():
    """Control: `cd "a && b"` tiene un `&&` textual que NO separa nada."""
    prefijo, cuerpo, _ = _partes(policy.reescribir('make "a && b"', RUTA))
    assert prefijo == ""
    assert cuerpo == 'make "a && b"'


def test_el_extracto_es_mas_largo_cuando_el_comando_falla():
    """REQ-005: en éxito basta saber que fue bien; en fallo hay que ver el error."""
    andamiaje = _partes(policy.reescribir("make", RUTA))[2]
    assert f"tail -n {policy.LINEAS_EN_EXITO}" in andamiaje
    assert f"tail -n {policy.LINEAS_EN_FALLO}" in andamiaje
    assert policy.LINEAS_EN_FALLO > policy.LINEAS_EN_EXITO


def test_la_ruta_viaja_por_la_salida_del_propio_comando():
    """Medido: el modelo desconfía del `additionalContext` de un hook y puede no seguir la pista.
    La salida de la tool sí la lee como resultado normal, así que la ruta tiene que ir ahí."""
    andamiaje = _partes(policy.reescribir("make", RUTA))[2]
    assert RUTA in andamiaje
    assert "local_lint_summary" in andamiaje


def test_el_andamiaje_es_identico_venga_el_comando_que_venga():
    """REQ-003: ninguna parte del comando del usuario puede acabar construyendo el andamiaje.

    Es la forma de comprobarlo que de verdad discrimina: si algo del comando se colara en la
    maquinaria, dos comandos distintos darían andamiajes distintos. Buscar marcas concretas no
    valdría, porque solo encontraría las que se me ocurrieran a mí.
    """
    a = _partes(policy.reescribir("make MARCA_DEL_USUARIO=si objetivo-raro", RUTA))[2]
    b = _partes(policy.reescribir("npm run build -- --flag='x y'", RUTA))[2]
    assert a == b
    assert a, "sin andamiaje, la igualdad de arriba sería trivialmente cierta"


def test_el_andamiaje_solo_usa_utilidades_de_la_lista_cerrada():
    andamiaje = _partes(policy.reescribir("make", RUTA))[2]
    usadas = {palabra for palabra in policy.UTILIDADES_DEL_ANDAMIAJE if palabra in andamiaje}
    assert usadas == set(policy.UTILIDADES_DEL_ANDAMIAJE)
    # La ruta se saca antes de buscar intrusos: lleva dentro el nombre de la tool (`bash-…`) y
    # buscar subcadenas sobre ella daba un positivo que no era tal.
    sin_ruta = andamiaje.replace(RUTA, "<ruta>")
    for intruso in ("python", "curl", "bash", "sh ", "grep", "sed", "awk", "cat"):
        assert intruso not in sin_ruta, intruso


def test_una_ruta_que_no_hayamos_construido_nosotros_se_rechaza():
    """Esa cadena se pega dentro de una línea de shell: un carácter suelto ahí es ejecución."""
    for mala in ("/tmp/a; rm -rf /", "/tmp/$(whoami).log", "/tmp/../etc/passwd", "", "/tmp/a b"):
        assert policy.reescribir("make", mala) is None, mala


def test_reescribir_no_se_aplica_dos_veces():
    """REQ-002c: los escapes se evalúan sobre el original. Un reescrito ya lleva redirección, así
    que volver a pasarlo tiene que dar `None` en vez de anidar otra envoltura."""
    una_vez = policy.reescribir("make", RUTA)
    assert policy.reescribir(una_vez, RUTA) is None
