import pytest

from app.core.time_parser import TICKS_PER_SECOND, duration_ticks, parse_time_expression


@pytest.mark.parametrize("expression,seconds", [
    ("0", 0), ("1", 1), ("12", 12), ("80", 80), ("1.5", 1.5),
    ("1:00", 60), ("1:20", 80), ("10:05", 605), ("01:02:03", 3723),
    ("1:02:03.5", 3723.5), ("1h", 3600), ("1hr", 3600), ("1 hour", 3600),
    ("2 hours", 7200), ("1m", 60), ("1min", 60), ("1 minute", 60),
    ("2 minutes", 120), ("80s", 80), ("80 sec", 80), ("80 seconds", 80),
    ("1h02m", 3720), ("1h 2m", 3720), ("1 hour 2 minutes", 3720),
    ("1m20s", 80), ("1 minute 20 seconds", 80), ("a minute twenty", 80),
    ("a minute and twenty seconds", 80), ("one minute twenty", 80),
    ("one minute and twenty seconds", 80), ("two minutes thirty", 150),
    ("ninety seconds", 90), ("forty-five seconds", 45), ("twenty one seconds", 21),
    ("1h 2m 3s", 3723), ("2 hours 3 minutes 4 seconds", 7384),
    ("half", None),
])
def test_duration_parser(expression, seconds):
    if seconds is None:
        with pytest.raises(ValueError):
            duration_ticks(expression)
    else:
        assert duration_ticks(expression) == round(seconds * TICKS_PER_SECOND)


@pytest.mark.parametrize("expression,expected", [
    ("first 30 seconds", (0, 30)),
    ("the first 30 seconds", (0, 30)),
    ("last 10 seconds", (110, 120)),
    ("the last 10 seconds", (110, 120)),
    ("from 1:20 to 2:00", (80, 120)),
    ("from 80 seconds to a minute forty", (80, 100)),
    ("at 1h02m", (3720, 3720)),
    ("80 seconds", (80, 80)),
])
def test_time_expression_parser(expression, expected):
    duration = 4000 if "1h" in expression else 120
    parsed = parse_time_expression(expression, duration * TICKS_PER_SECOND)
    assert (parsed.start_tick, parsed.end_tick) == tuple(value * TICKS_PER_SECOND for value in expected)


@pytest.mark.parametrize("expression,duration", [
    ("from 2 to 2", 10),
    ("from 12 to 13", 12),
    ("at 13", 12),
])
def test_time_expression_rejects_invalid_or_out_of_range_values(expression, duration):
    with pytest.raises(ValueError):
        parse_time_expression(expression, duration * TICKS_PER_SECOND)


def test_clock_components_are_validated_without_floats():
    with pytest.raises(ValueError, match="less than 60"):
        duration_ticks("1:80")
    assert isinstance(duration_ticks("1.125 seconds"), int)
