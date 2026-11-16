"""A date-time: the one reader of every field the specs type `date-time` (ecp_evaluate_spec.md "A date-time is read by
RFC 3339's grammar"; HTL-29 review, condition 5). Mirrors typescript/packages/core/src/date-time.ts: both read the value
by RFC 3339 §5.6's grammar and §5.7's ranges, and one table of written values holds them to one answer
(tests/conformance/date_time/).

A refusal names the element and its range; the field it was read for prefixes it with its name. The elements are
checked in the order they are written, so the first out of its range is the one named.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator, PlainValidator, PlainSerializer, ValidationInfo, TypeAdapter, WithJsonSchema

# §5.6: full-date "T" full-time, the offset "Z" or numeric; its note lets T and Z be lower case. A digit is DIGIT, 0-9
# (RFC 5234's core rules), which `\d` is not: Python's takes every Unicode decimal digit
_FORM = re.compile(r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})[Tt]"
                   r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})(?:\.(?P<fraction>[0-9]+))?"
                   r"(?:[Zz]|(?P<sign>[+-])(?P<offset_hour>[0-9]{2}):(?P<offset_minute>[0-9]{2}))")
_EXAMPLE = "2026-11-10T12:00:00Z"
FORM = ("is not in RFC 3339's date-time form: a full date, T, a full time and its offset (Z, or +hh:mm or -hh:mm), "
        f"e.g. {_EXAMPLE}")
NOT_A_STRING = f"is not a string: a date-time is written in RFC 3339's form, e.g. {_EXAMPLE}"
NO_OFFSET = ("has no offset: a date-time carries its offset (RFC 3339 §5.6); give the datetime one, e.g. "
             "datetime.now(timezone.utc)")
LEAP_SECOND = "has second 60, a leap second: no core holds one, so it is refused rather than moved"
# What a core holds: Python's datetime holds the years 1 to 9999, and the instant is read in UTC
HELD = (f"is outside the instants a core holds, {datetime.min.year:04d}-01-01T00:00:00Z to "
        f"{datetime.max.year:04d}-12-31T23:59:59Z in UTC")
# What is held is the instant with its offset as written, so a date written in a year no core holds is refused whatever
# its offset: hiitl's limit, not RFC 3339's, whose grammar writes the year 0000 (HTL-29 second review, condition 5)
YEAR = (f"has year 0000; a core holds the years {datetime.min.year:04d} to {datetime.max.year:04d} as written, "
        "whatever the offset")

# §5.6's ranges, each element's (what it is, low, high); a day's high is §5.7's table, a second's 60 a leap second
_ELEMENTS = (("month", "a month", 1, 12), ("hour", "an hour", 0, 23), ("minute", "a minute", 0, 59),
             ("second", "a second", 0, 59), ("offset hour", "an offset's hour", 0, 23),
             ("offset minute", "an offset's minute", 0, 59))
_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_LEAP_SECOND = 60
_MICRO = 6                                  # a datetime holds a second's fraction to the microsecond


class _NativeDateText(str):
    """Existing JSON text beside an admitted native instant; neither replaces the other."""

    def __new__(cls, text: str, instant: datetime):
        value = super().__new__(cls, text)
        value._instant = instant
        return value

    def __getnewargs__(self):
        return str(self), self._instant


def _days(year: int, month: int) -> int:
    """§5.7: February has 29 days in a year divisible by 4, and not by 100 unless by 400."""
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return 29 if month == 2 and leap else _DAYS[month - 1]


def _outside(element: str, written: str) -> Optional[str]:
    (what, low, high), = ((w, lo, hi) for e, w, lo, hi in _ELEMENTS if e == element)
    return None if low <= int(written) <= high else f"has {element} {written}; {what} is {low:02d} to {high:02d}"


def _held(instant: datetime) -> Optional[str]:
    try:
        instant.astimezone(timezone.utc)
    except OverflowError:
        return HELD
    return None


def _refused(m: re.Match) -> Optional[str]:
    """The first element written outside its range, in the order written."""
    year, month = int(m["year"]), int(m["month"])
    if year < datetime.min.year:
        return YEAR
    if refused := _outside("month", m["month"]):
        return refused
    if not 1 <= int(m["day"]) <= _days(year, month):
        return f"has day {m['day']}; {m['year']}-{m['month']} has days 01 to {_days(year, month):02d}"
    for element in ("hour", "minute"):
        if refused := _outside(element, m[element]):
            return refused
    if int(m["second"]) == _LEAP_SECOND:
        return LEAP_SECOND
    if refused := _outside("second", m["second"]):
        return refused
    if m["sign"]:
        for element in ("offset hour", "offset minute"):
            if refused := _outside(element, m[element.replace(" ", "_")]):
                return refused
    return None


def _read(value: Any) -> tuple[Optional[datetime], Optional[str]]:
    """The held native instant or the instant a plain string writes, with its offset; else its refusal."""
    if isinstance(value, _NativeDateText):
        instant = value._instant
        refused = NO_OFFSET if instant.utcoffset() is None else _held(instant)
        return (None, refused) if refused else (instant, None)
    if not isinstance(value, str):
        return None, NOT_A_STRING
    m = _FORM.fullmatch(value)
    if m is None:
        return None, FORM
    if refused := _refused(m):
        return None, refused
    offset = timedelta(hours=int(m["offset_hour"] or 0), minutes=int(m["offset_minute"] or 0))
    zone = timezone(-offset if m["sign"] == "-" else offset) if offset else timezone.utc
    micro = int((m["fraction"] or "")[:_MICRO].ljust(_MICRO, "0"))       # truncated, never rounded
    instant = datetime(int(m["year"]), int(m["month"]), int(m["day"]), int(m["hour"]), int(m["minute"]),
                       int(m["second"]), micro, zone)
    refused = _held(instant)
    return (None, refused) if refused else (instant, None)


def refusal(value: Any) -> Optional[str]:
    """The sentence naming the element that refuses `value` and its range, or None when it is a date-time."""
    return _read(value)[1]


def read(value: Any) -> datetime:
    """Read a held native instant, or a plain string's written instant; ValueError carries its refusal."""
    instant, refused = _read(value)
    if refused:
        raise ValueError(refused)
    return instant


def _field(value: Any, info: ValidationInfo) -> datetime:
    """A core model's date-time field: a string read by the grammar, or, in Python, a datetime that carries its
    offset."""
    if isinstance(value, datetime):
        refused = NO_OFFSET if value.utcoffset() is None else _held(value)
        if refused is None:
            return value
    else:
        instant, refused = _read(value)
        if refused is None:
            return instant
    name = info.field_name or (info.context or {}).get("field_name") or "<root>"
    raise ValueError(f"{name} {refused}")


DateTime = Annotated[datetime, BeforeValidator(_field)]


_NATIVE_JSON = TypeAdapter(datetime)


def _text_field(value: Any, info: ValidationInfo) -> str:
    """Validate an envelope date without replacing its supplied JSON text.

    ecp_evaluate_spec.md: comparison, recorded JSON and the signed form carry one
    text. Native aware datetimes have no supplied spelling and use the existing
    Pydantic JSON form. Instant consumers explicitly call read().
    """
    instant = _field(value, info)
    return value if isinstance(value, str) else _NativeDateText(_NATIVE_JSON.dump_python(instant, mode="json"), instant)


DateText = Annotated[str, PlainValidator(_text_field), PlainSerializer(str, return_type=str, when_used="json"),
                     WithJsonSchema({"type": "string", "format": "date-time"})]
