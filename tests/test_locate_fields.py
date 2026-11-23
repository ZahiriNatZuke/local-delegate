"""REQ-008 and REQ-002: what a location field name asks for, and the shape of its value.

`locate.classify_field` reads a field name by PRESENCE: the categories of a closed vocabulary are
taken first, and an unknown word never cancels them (#697: `lista_de_ficheros_con_sus_lineas` went
to the model because «sus» was not in the subject words of `asks_for_diff_files`).
"""

from __future__ import annotations

import pytest

from local_delegate import line_check, locate

FUNCTIONS = frozenset({"function", "method", "function_property"})


@pytest.mark.parametrize(
    ("name", "categories", "singular", "kinds", "residual"),
    [
        ("lista_de_ficheros_con_sus_lineas", {"files"}, False, set(), ()),
        ("ficheros_con_lineas", {"files"}, False, set(), ()),
        ("files_with_lines", {"files"}, False, set(), ()),
        ("ficheros_que_cambian_con_sus_lineas", {"files"}, False, set(), ()),
        ("changed_files_with_lines", {"files"}, False, set(), ()),
        ("fichero_con_lineas", {"files"}, True, set(), ()),
        ("files_and_hunks_with_lines", {"files", "hunks"}, False, set(), ()),
        ("ficheros_y_hunks_con_lineas", {"files", "hunks"}, False, set(), ()),
        ("hunks_with_lines", {"hunks"}, False, set(), ()),
        ("funciones_con_lineas", {"declarations"}, False, FUNCTIONS, ()),
        ("metodos_y_computed_con_lineas", {"declarations"}, False, FUNCTIONS, ()),
        ("funcion_con_lineas", {"declarations"}, True, FUNCTIONS, ()),
        ("clases_con_lineas", {"declarations"}, False, {"class"}, ()),
        ("tipos_con_lineas", {"declarations"}, False, {"type"}, ()),
        ("constantes_con_lineas", {"declarations"}, False, {"variable"}, ()),
        ("declaraciones_con_lineas", {"declarations"}, False, set(), ()),
        ("secciones_con_lineas", {"sections"}, False, set(), ()),
        ("sections_with_lines", {"sections"}, False, set(), ()),
        ("heading_line", {"sections"}, True, set(), ()),
        ("section_line", {"sections"}, True, set(), ()),
        ("ids_con_lineas", {"ids"}, False, set(), ()),
        ("requisitos_con_lineas", {"ids"}, False, set(), ()),
        ("orden_local_y_barra_con_lineas", set(), False, set(), ("orden", "local", "barra")),
        (
            "funciones_que_validan_entrada_con_lineas",
            {"declarations"},
            False,
            FUNCTIONS,
            ("validan", "entrada"),
        ),
    ],
)
def test_categories_by_presence(name, categories, singular, kinds, residual):
    assert line_check.is_location_field(name), name  # the names are all location fields
    req = locate.classify_field(name)
    assert req.name == name
    assert req.categories == frozenset(categories)
    assert req.singular is singular
    assert req.kinds == frozenset(kinds)
    assert req.residual == residual
    assert req.hunks == ("hunks" in categories)


@pytest.mark.parametrize(
    ("name", "ids"),
    [
        ("REQ_012_linea", ("REQ-012",)),
        ("req_012_linea", ("REQ-012",)),
        ("D7_linea", ("D-7",)),
        ("REQ012_line_number", ("REQ-012",)),
    ],
)
def test_an_id_in_the_name_is_taken_before_the_short_words(name, ids):
    req = locate.classify_field(name)
    assert req.ids == ids
    assert req.categories == frozenset({"ids"})
    assert req.singular is True
    assert req.residual == ()


def test_an_unknown_word_never_cancels_a_category():
    # #697: under the old rule (every subject word in a vocabulary) «sus» sent it to the model.
    req = locate.classify_field("lista_de_ficheros_con_sus_lineas")
    assert "files" in req.categories
    req = locate.classify_field("ficheros_raros_con_lineas")
    assert req.categories == frozenset({"files"})
    assert req.residual == ("raros",)


def _items():
    return [
        locate.Item("b", 20, 25, hunks=((20, 22), (23, 25))),
        locate.Item("lost", None, None, reason="not_found"),
        locate.Item("a", 3, 9),
        locate.Item("other lost", None, None, reason="ambiguous", candidates=(4, 8)),
        locate.Item("a2", 3, 4),
    ]


def test_to_value_orders_by_line_and_puts_unlocated_last():
    req = locate.classify_field("funciones_con_lineas")
    value = locate.to_value(req, _items())
    assert value == [
        {"name": "a2", "start": 3, "end": 4},
        {"name": "a", "start": 3, "end": 9},
        {"name": "b", "start": 20, "end": 25},
        {"name": "lost", "start": None, "end": None},
        {"name": "other lost", "start": None, "end": None},
    ]


def test_to_value_of_no_item_is_none():
    req = locate.classify_field("funciones_con_lineas")
    assert locate.to_value(req, []) is None


def test_to_value_has_hunks_only_when_the_field_asks_for_them():
    with_hunks = locate.to_value(locate.classify_field("ficheros_y_hunks_con_lineas"), _items())
    assert with_hunks[2] == {"name": "b", "start": 20, "end": 25, "hunks": [[20, 22], [23, 25]]}
    assert with_hunks[3]["hunks"] == []
    without = locate.to_value(locate.classify_field("ficheros_con_lineas"), _items())
    assert all("hunks" not in entry for entry in without)


def test_a_half_located_item_is_unlocated():
    req = locate.classify_field("funciones_con_lineas")
    value = locate.to_value(req, [locate.Item("x", 5, None), locate.Item("y", 2, 2)])
    assert value == [
        {"name": "y", "start": 2, "end": 2},
        {"name": "x", "start": None, "end": None},
    ]
