import pytest

from polybot.persistence.json_codec import NonFiniteJsonNumberError, loads_json


@pytest.mark.parametrize("literal", ("NaN", "Infinity", "-Infinity"))
def test_loads_json_rejects_nonfinite_numbers(literal: str) -> None:
    with pytest.raises(NonFiniteJsonNumberError, match="must be finite"):
        loads_json(f'{{"value":{literal}}}')


def test_loads_json_keeps_finite_numbers() -> None:
    assert loads_json('{"value":1.25}') == {"value": 1.25}
