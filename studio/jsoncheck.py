"""Checks an AI answer against the small schema it was asked to follow, and keeps only the usable part.

Why: an AI answer is untrusted text. One item with a missing number used to make the whole 15-minute window of a
video fail without a word (audit experiments E3 and E4). Here a list keeps every item that is fine and drops each
item that is not; only an answer that is wrong as a whole (or has nothing usable in it) is refused.

The schema is the same small dialect the app already uses for Gemini: types ARRAY, OBJECT, STRING, NUMBER, INTEGER,
BOOLEAN, with `items`, `properties` and `required`. Lower-case type names work too.

Rules, kept deliberately forgiving about spelling and strict about meaning:
  * numbers may arrive as numeric text ("85") or as 85.0 for an integer; they are turned into real numbers
  * text may arrive as a number; it is turned into text
  * a required field that is missing or unusable makes that item unusable
  * an optional field that is unusable is removed from the item
  * fields the schema does not mention are removed, so nothing unexpected travels on
  * lists are cut to 200 items and nesting deeper than 6 levels is refused

Nothing here imports the rest of the app."""
import math

MAX_ITEMS = 200
MAX_DEPTH = 6


class BadAnswer(ValueError):
    """The answer does not have the shape that was asked for. The message says why, in words safe to show."""


def _type(schema) -> str:
    return str((schema or {}).get("type") or "").upper()


def _num(v):
    if isinstance(v, bool):
        raise BadAnswer("a number was expected")
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            raise BadAnswer("a number was expected")
    else:
        raise BadAnswer("a number was expected")
    if not math.isfinite(f):
        raise BadAnswer("a finite number was expected")
    return f


def _one(v, schema, depth):
    """The usable version of one value, or BadAnswer."""
    if depth > MAX_DEPTH:
        raise BadAnswer("the answer is nested too deeply")
    t = _type(schema)
    if t == "NUMBER":
        return _num(v)
    if t == "INTEGER":
        return int(round(_num(v)))
    if t == "STRING":
        if isinstance(v, str):
            return v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        raise BadAnswer("text was expected")
    if t == "BOOLEAN":
        if isinstance(v, bool):
            return v
        raise BadAnswer("true or false was expected")
    if t == "ARRAY":
        if not isinstance(v, list):
            raise BadAnswer("a list was expected")
        sub = schema.get("items") or {}
        out = []
        for item in v[:MAX_ITEMS]:
            try:
                out.append(_one(item, sub, depth + 1))
            except BadAnswer:
                continue
        return out
    if t == "OBJECT":
        if not isinstance(v, dict):
            raise BadAnswer("an object was expected")
        props = schema.get("properties") or {}
        if not props:
            return dict(v)                          # a free-form object: nothing to check
        required = set(schema.get("required") or [])
        out = {}
        for name, sub in props.items():
            if name in v and v[name] is not None:
                try:
                    out[name] = _one(v[name], sub, depth + 1)
                    continue
                except BadAnswer:
                    pass
            if name in required:
                raise BadAnswer(f"the required field '{name}' is missing or unusable")
        return out
    return v        # a schema without a type (or one we do not know) accepts the value as it is


def clean(value, schema) -> tuple:
    """(the usable answer, how many list items were dropped). Raises BadAnswer when the answer as a whole is not
    usable: the wrong kind of value, or a non-empty list in which no item is usable."""
    if _type(schema) == "ARRAY" and isinstance(value, dict) and isinstance(value.get("items"), list):
        value = value["items"]                      # some models wrap the list in {"items": [...]}
    if _type(schema) != "ARRAY":
        return _one(value, schema, 0), 0
    if not isinstance(value, list):
        raise BadAnswer("a list was expected")
    got = _one(value, schema, 0)
    dropped = min(len(value), MAX_ITEMS) - len(got)
    if value and not got:
        raise BadAnswer("no item in the list was usable")
    return got, dropped
