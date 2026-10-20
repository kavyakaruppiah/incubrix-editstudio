"""Deterministic human time-expression parser with integer source ticks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

TICKS_PER_SECOND = 90_000

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90,
}
_UNIT_SECONDS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}


@dataclass(frozen=True, slots=True)
class TimeExpression:
    start_tick: int
    end_tick: int
    kind: str = "point"


def _word_number(value: str) -> Decimal:
    words = value.lower().replace("-", " ").split()
    if words in (["a"], ["an"]):
        return Decimal(1)
    total = 0
    current = 0
    for word in words:
        if word in {"and", "a", "an"}:
            if word in {"a", "an"}:
                current += 1
            continue
        if word not in _NUMBER_WORDS:
            raise ValueError(f"Unknown number word: {word}")
        number = _NUMBER_WORDS[word]
        if number >= 20 and current and current < 10:
            current += number
        elif number >= 20:
            current += number
        else:
            current += number
    total += current
    return Decimal(total)


def _number(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        return _word_number(value)


def duration_ticks(expression: str) -> int:
    """Parse a duration such as ``1:20``, ``1h02m``, or ``a minute twenty``."""
    text = expression.strip().lower()
    if not text:
        raise ValueError("time expression is empty")
    text = re.sub(r"\b(?:about|approximately|exactly)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if re.fullmatch(r"\d+(?:\.\d+)?(?::\d+(?:\.\d+)?){1,2}", text):
        parts = [Decimal(part) for part in text.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            if seconds >= 60:
                raise ValueError("seconds in a clock time must be less than 60")
            seconds_total = minutes * 60 + seconds
        else:
            hours, minutes, seconds = parts
            if minutes >= 60 or seconds >= 60:
                raise ValueError("minutes and seconds in a clock time must be less than 60")
            seconds_total = hours * 3600 + minutes * 60 + seconds
        return int((seconds_total * TICKS_PER_SECOND).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Normalize spoken cardinal values to digits while retaining unit words.
    text = re.sub(r"\b(?:a|an)\b", "1", text)
    tokens = re.findall(r"\d+(?:\.\d+)?|[a-z]+", text)
    if not tokens:
        raise ValueError(f"Could not parse time expression: {expression!r}")

    groups: list[tuple[Decimal, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "and":
            index += 1
            continue
        if token.isdigit() or re.fullmatch(r"\d+\.\d+", token):
            value = Decimal(token)
            index += 1
        elif token in _NUMBER_WORDS:
            number_words = [token]
            index += 1
            while index < len(tokens) and tokens[index] in _NUMBER_WORDS:
                number_words.append(tokens[index])
                index += 1
            value = _word_number(" ".join(number_words))
        else:
            raise ValueError(f"Could not parse time expression: {expression!r}")

        unit = ""
        if index < len(tokens) and tokens[index] in _UNIT_SECONDS:
            unit = tokens[index]
            index += 1
        groups.append((value, unit))

    if not groups:
        raise ValueError(f"Could not parse time expression: {expression!r}")
    seconds_total = Decimal(0)
    for value, unit in groups:
        seconds_total += value * _UNIT_SECONDS.get(unit, 1)
    if seconds_total < 0:
        raise ValueError("duration cannot be negative")
    return int((seconds_total * TICKS_PER_SECOND).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_time_expression(expression: str, duration_tick: int) -> TimeExpression:
    """Resolve a point/range expression against a known current duration."""
    if duration_tick < 0:
        raise ValueError("duration_tick cannot be negative")
    text = expression.strip().lower()
    if text.startswith("the "):
        text = text[4:].strip()

    match = re.fullmatch(r"first\s+(.+)", text)
    if match:
        end = min(duration_tick, duration_ticks(match.group(1)))
        return TimeExpression(0, end, "range")
    match = re.fullmatch(r"last\s+(.+)", text)
    if match:
        length = duration_ticks(match.group(1))
        return TimeExpression(max(0, duration_tick - length), duration_tick, "range")
    match = re.fullmatch(r"from\s+(.+?)\s+to\s+(.+)", text)
    if match:
        start = duration_ticks(match.group(1))
        end = duration_ticks(match.group(2))
        if start >= end:
            raise ValueError("time range start must be before its end")
        if end > duration_tick:
            raise ValueError("time range exceeds the current duration")
        return TimeExpression(start, end, "range")
    match = re.fullmatch(r"at\s+(.+)", text)
    if match:
        point = duration_ticks(match.group(1))
        if point > duration_tick:
            raise ValueError("time point exceeds the current duration")
        return TimeExpression(point, point, "point")

    point = duration_ticks(text)
    if point > duration_tick:
        raise ValueError("time point exceeds the current duration")
    return TimeExpression(point, point, "point")
