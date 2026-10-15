"""Control positivo: con el mutante «el reduce sin la orden» (se quita reduce_extra), A1 debe fallar."""

import pytest
import test_chunking_language_investigation as inv

from local_delegate import server


@pytest.fixture(autouse=True)
def mutant(monkeypatch):
    real = server._chat_map_reduce

    def mutated(*a, **kw):
        kw["reduce_extra"] = ""
        return real(*a, **kw)

    monkeypatch.setattr(server, "_chat_map_reduce", mutated)


test_A1 = inv.test_A1_map_reduce_and_regroup_carry_the_order
backend = inv.backend
