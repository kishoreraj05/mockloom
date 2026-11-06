"""Generate fake data by walking a JSON Schema, honouring its constraints."""

from __future__ import annotations

import datetime as dt
import json
import random
import re
import string
import uuid
from collections.abc import Callable
from typing import Any

import regex
import rstr
from faker import Faker

from .limits import GENERATION_NODE_BUDGET, MAX_CIRCULAR_REF_DEPTH, MAX_OPTIONAL_REF_DEPTH
from .schema import SchemaContext

_faker = Faker()
_CUT = object()  # Returned instead of a value when a cycle or the node budget stops descent.


class _Xeger(rstr.Rstr):
    """rstr's default of up to 100 repeats overflows most `maxLength`s, and reads badly."""

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self._max_repeat = 12

    def _handle_repeat(self, start_range: int, end_range: int, value: Any) -> str:
        return super()._handle_repeat(
            start_range, min(end_range, max(start_range, self._max_repeat)), value
        )


_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _fits_type(value: Any, schema: dict[str, Any]) -> bool:
    declared = schema.get("type")
    names = [declared] if isinstance(declared, str) else (declared or [])
    checks = [_JSON_TYPES[n] for n in names if n in _JSON_TYPES]
    return not checks or any(check(value) for check in checks)


def _normal(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


_STRING_NAMES: dict[str, Callable[[Faker], str]] = {
    "email": lambda f: f.email(),
    "emailaddress": lambda f: f.email(),
    "firstname": lambda f: f.first_name(),
    "givenname": lambda f: f.first_name(),
    "lastname": lambda f: f.last_name(),
    "surname": lambda f: f.last_name(),
    "familyname": lambda f: f.last_name(),
    "fullname": lambda f: f.name(),
    "displayname": lambda f: f.name(),
    "name": lambda f: f.name(),
    "username": lambda f: f.user_name(),
    "login": lambda f: f.user_name(),
    "phone": lambda f: f.phone_number(),
    "phonenumber": lambda f: f.phone_number(),
    "mobile": lambda f: f.phone_number(),
    "avatar": lambda f: f.image_url(),
    "avatarurl": lambda f: f.image_url(),
    "image": lambda f: f.image_url(),
    "imageurl": lambda f: f.image_url(),
    "photourl": lambda f: f.image_url(),
    "thumbnail": lambda f: f.image_url(),
    "url": lambda f: f.url(),
    "website": lambda f: f.url(),
    "homepage": lambda f: f.url(),
    "link": lambda f: f.url(),
    "href": lambda f: f.url(),
    "domain": lambda f: f.domain_name(),
    "hostname": lambda f: f.domain_name(),
    "ip": lambda f: f.ipv4(),
    "ipaddress": lambda f: f.ipv4(),
    "address": lambda f: f.street_address(),
    "street": lambda f: f.street_address(),
    "streetaddress": lambda f: f.street_address(),
    "city": lambda f: f.city(),
    "state": lambda f: f.state(),
    "country": lambda f: f.country(),
    "countrycode": lambda f: f.country_code(),
    "zip": lambda f: f.postcode(),
    "zipcode": lambda f: f.postcode(),
    "postcode": lambda f: f.postcode(),
    "postalcode": lambda f: f.postcode(),
    "company": lambda f: f.company(),
    "companyname": lambda f: f.company(),
    "organization": lambda f: f.company(),
    "jobtitle": lambda f: f.job(),
    "title": lambda f: f.sentence(nb_words=4).rstrip("."),
    "subject": lambda f: f.sentence(nb_words=5).rstrip("."),
    "headline": lambda f: f.sentence(nb_words=6).rstrip("."),
    "description": lambda f: f.sentence(nb_words=10),
    "summary": lambda f: f.sentence(nb_words=8),
    "bio": lambda f: f.sentence(nb_words=12),
    "body": lambda f: f.paragraph(nb_sentences=2),
    "content": lambda f: f.paragraph(nb_sentences=2),
    "text": lambda f: f.paragraph(nb_sentences=1),
    "message": lambda f: f.sentence(nb_words=8),
    "comment": lambda f: f.sentence(nb_words=8),
    "color": lambda f: f.color_name(),
    "colour": lambda f: f.color_name(),
    "currency": lambda f: f.currency_code(),
    "currencycode": lambda f: f.currency_code(),
    "locale": lambda f: f.locale(),
    "language": lambda f: f.language_code(),
    "slug": lambda f: f.slug(),
    "sku": lambda f: f.bothify("SKU-####-??").upper(),
    "token": lambda f: f.sha1(),
    "hash": lambda f: f.sha256(),
}

_INTEGER_NAMES: dict[str, tuple[int, int]] = {
    "age": (18, 90),
    "year": (2000, 2030),
    "month": (1, 12),
    "day": (1, 28),
    "hour": (0, 23),
    "minute": (0, 59),
    "second": (0, 59),
    "count": (0, 100),
    "total": (0, 1000),
    "totalcount": (0, 1000),
    "quantity": (1, 20),
    "qty": (1, 20),
    "page": (1, 10),
    "perpage": (10, 100),
    "pagesize": (10, 100),
    "limit": (10, 100),
    "offset": (0, 100),
    "rating": (1, 5),
    "stars": (0, 5),
    "score": (0, 100),
    "percent": (0, 100),
    "percentage": (0, 100),
}


class Generator:
    def __init__(
        self,
        context: SchemaContext,
        rng: random.Random,
        faker: Faker | None = None,
        use_examples: bool = True,
    ):
        self.use_examples = use_examples
        self.context = context
        self.rng = rng
        self.faker = faker or _faker
        self.faker.seed_instance(rng.getrandbits(64))
        self.budget = GENERATION_NODE_BUDGET

    def generate(self, schema: Any, name: str | None = None) -> Any:
        value = self._walk(schema, name, ())
        return None if value is _CUT else value

    def _walk(self, schema: Any, name: str | None, refs: tuple[str, ...]) -> Any:
        self.budget -= 1
        if self.budget <= 0 or not isinstance(schema, dict):
            return _CUT if self.budget <= 0 else self._string({}, name)

        ref = schema.get("$ref")
        if isinstance(ref, str):
            if refs.count(ref) >= MAX_CIRCULAR_REF_DEPTH:
                return _CUT
            return self._walk(self.context.resolve(schema), name, (*refs, ref))

        if self.use_examples:
            if "example" in schema:
                return schema["example"]
            examples = schema.get("examples")
            if isinstance(examples, list) and examples:
                return examples[0]
        if "const" in schema:
            return schema["const"]
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            # Specs do declare enums and defaults that contradict their own `type`; skip those.
            fitting = [v for v in enum if _fits_type(v, schema)]
            choices = [v for v in fitting if v is not None] or fitting
            if choices:
                return self.rng.choice(choices)
        if "default" in schema and _fits_type(schema["default"], schema):
            return schema["default"]

        if schema.get("type") == "null":
            return None
        if isinstance(schema.get("allOf"), list) and schema["allOf"]:
            merged, refs = self._merge_all_of(schema, refs)
            return self._walk(merged, name, refs)
        for key in ("oneOf", "anyOf"):
            options = schema.get(key)
            if isinstance(options, list) and options:
                non_null = [o for o in options if self.context.resolve(o).get("type") != "null"]
                rest = {k: v for k, v in schema.items() if k != key}
                # `allOf: [{nullable: true}, {$ref: X}]` puts the real type beside this anyOf.
                keep_rest = any(k in rest for k in ("properties", "required", "type"))
                for choice in non_null or options:
                    merged = {"allOf": [rest, choice]} if keep_rest else choice
                    value = self._walk(merged, name, refs)
                    if value is not _CUT:
                        return value
                return _CUT

        kind = self._kind(schema)
        if kind == "object":
            return self._object(schema, refs)
        if kind == "array":
            return self._array(schema, name, refs)
        if kind == "integer":
            return self._integer(schema, name)
        if kind == "number":
            return self._number(schema, name)
        if kind == "boolean":
            return self.rng.random() < 0.5
        if kind == "null":
            return None
        return self._string(schema, name)

    def _merge_all_of(
        self, schema: dict[str, Any], refs: tuple[str, ...]
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        merged: dict[str, Any] = {}
        properties: dict[str, Any] = {}
        required: list[str] = []

        def absorb(node: Any, depth: int = 0) -> None:
            nonlocal refs
            if depth > 16 or not isinstance(node, dict):
                return
            ref = node.get("$ref")
            if isinstance(ref, str):
                if refs.count(ref) >= MAX_CIRCULAR_REF_DEPTH:
                    return
                refs = (*refs, ref)
                node = self.context.resolve(node)
            for sub in node.get("allOf") or []:
                absorb(sub, depth + 1)
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    properties.update(value)
                elif key == "required" and isinstance(value, list):
                    required.extend(value)
                elif key != "allOf":
                    merged[key] = value

        absorb(schema)
        if properties:
            merged["properties"] = properties
        if required:
            merged["required"] = list(dict.fromkeys(required))
        return merged, refs

    def _kind(self, schema: dict[str, Any]) -> str:
        declared = schema.get("type")
        if isinstance(declared, list):
            options = [t for t in declared if t != "null"]
            declared = options[0] if options else "null"
        if isinstance(declared, str):
            return declared
        if "properties" in schema or "additionalProperties" in schema:
            return "object"
        if "items" in schema or "prefixItems" in schema:
            return "array"
        if "minimum" in schema or "maximum" in schema or "multipleOf" in schema:
            return "number"
        return "string"

    def _object(self, schema: dict[str, Any], refs: tuple[str, ...]) -> Any:
        result: dict[str, Any] = {}
        required = schema.get("required")
        required = required if isinstance(required, list) else []
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        # Past a few levels of nested refs, optional fields only add bulk: on a spec like Stripe's
        # they turn one response into megabytes.
        shallow = len(refs) < MAX_OPTIONAL_REF_DEPTH and self.budget > GENERATION_NODE_BUDGET // 2
        for prop, sub in properties.items():
            resolved = self.context.resolve(sub)
            if resolved.get("writeOnly") or (not shallow and prop not in required):
                continue
            value = self._walk(sub, prop, refs)
            if value is _CUT:
                if prop in required:
                    result[prop] = self._minimal(resolved, prop)
                continue
            result[prop] = value
        for prop in required:
            if isinstance(prop, str) and prop not in result and prop not in properties:
                result[prop] = self._string({}, prop)
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict) and extra and not properties:
            for index in range(1, 3):
                value = self._walk(extra, None, refs)
                if value is _CUT:
                    break
                result[f"key{index}"] = value
        return result

    def _minimal(self, schema: Any, name: str | None, depth: int = 0) -> Any:
        """The smallest valid value we can give for a required field after descent was cut."""
        schema = self.context.resolve(schema)
        if "const" in schema:
            return schema["const"]
        if isinstance(schema.get("enum"), list) and schema["enum"]:
            return schema["enum"][0]
        for key in ("anyOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list) and options:
                # Prefer an option that ends the recursion: null, then anything without a $ref.
                for option in options:
                    if self.context.resolve(option).get("type") == "null":
                        return None
                plain = [o for o in options if "$ref" not in o] if depth < 4 else []
                return self._minimal((plain or options)[0], name, depth + 1)
        if isinstance(schema.get("allOf"), list) and schema["allOf"] and depth < 4:
            merged, _ = self._merge_all_of(schema, ())
            return self._minimal(merged, name, depth + 1)
        kind = self._kind(schema)
        declared = schema.get("type")
        if isinstance(declared, list) and "null" in declared:
            return None
        if kind == "array":
            return []
        if kind == "object":
            required = schema.get("required")
            properties = schema.get("properties") or {}
            if depth >= 4 or not isinstance(required, list):
                return {}
            return {
                prop: self._minimal(properties.get(prop, {}), prop, depth + 1)
                for prop in required
                if isinstance(prop, str)
            }
        if kind == "integer":
            return self._integer(schema, name)
        if kind == "number":
            return self._number(schema, name)
        if kind == "boolean":
            return False
        if kind == "null":
            return None
        return self._string(schema, name)

    def _array(self, schema: dict[str, Any], name: str | None, refs: tuple[str, ...]) -> Any:
        low = schema.get("minItems", 0)
        high = schema.get("maxItems")
        low = low if isinstance(low, int) and low >= 0 else 0
        count = max(low, self.rng.randint(1, 3))
        if isinstance(high, int):
            count = min(count, high)
        items = schema.get("items")
        if not isinstance(items, dict):
            prefix = schema.get("prefixItems")
            if isinstance(prefix, list):
                values = [self._walk(p, None, refs) for p in prefix]
                return [v for v in values if v is not _CUT]
            items = {}
        singular = name[:-1] if name and name.endswith("s") else name
        output: list[Any] = []
        seen: set[str] = set()
        unique = bool(schema.get("uniqueItems"))
        attempts = 0
        while len(output) < count and attempts < count + 8:
            attempts += 1
            value = self._walk(items, singular, refs)
            if value is _CUT:
                break
            if unique:
                marker = json.dumps(value, sort_keys=True, default=str)
                if marker in seen:
                    continue
                seen.add(marker)
            output.append(value)
        return output

    def _bounds(self, schema: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        def number(key: str) -> Any:
            value = schema.get(key)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        return (
            number("minimum"),
            number("maximum"),
            number("exclusiveMinimum"),
            number("exclusiveMaximum"),
        )

    def _integer(self, schema: dict[str, Any], name: str | None) -> int:
        low, high, ex_low, ex_high = self._bounds(schema)
        if ex_low is not None:
            low = max(int(ex_low) + 1, low if low is not None else int(ex_low) + 1)
        if ex_high is not None:
            high = min(int(ex_high) - 1, high if high is not None else int(ex_high) - 1)
        normal = _normal(name)
        default_low, default_high = _INTEGER_NAMES.get(normal, (1, 1000))
        if normal == "id" or normal.endswith("id"):
            default_low, default_high = 1, 100_000
        if low is None and high is None:
            low, high = default_low, default_high
        elif low is None:
            low = min(default_low, int(high))
        elif high is None:
            high = max(default_high, int(low) + 100)
        low, high = int(_ceil(low)), int(_floor(high))
        if low > high:
            high = low
        step = schema.get("multipleOf")
        if isinstance(step, int) and step > 0:
            first = (low + step - 1) // step
            last = high // step
            if first <= last:
                return self.rng.randint(first, last) * step
            return first * step
        return self.rng.randint(low, high)

    def _number(self, schema: dict[str, Any], name: str | None) -> float:
        low, high, ex_low, ex_high = self._bounds(schema)
        epsilon = 0.01
        if ex_low is not None:
            low = max(ex_low + epsilon, low if low is not None else ex_low + epsilon)
        if ex_high is not None:
            high = min(ex_high - epsilon, high if high is not None else ex_high - epsilon)
        if low is None and high is None:
            low, high = 1.0, 1000.0
        elif low is None:
            low = min(0.0, float(high))
        elif high is None:
            high = float(low) + 1000.0
        if low > high:
            high = low
        step = schema.get("multipleOf")
        if isinstance(step, (int, float)) and step > 0:
            first = _ceil(low / step)
            last = _floor(high / step)
            multiple = self.rng.randint(first, max(first, last))
            return round(multiple * step, 10)
        value = round(self.rng.uniform(float(low), float(high)), 2)
        return min(max(value, float(low)), float(high))

    def _string(self, schema: dict[str, Any], name: str | None) -> str:
        fmt = schema.get("format")
        formatted = self._format(fmt) if isinstance(fmt, str) else None
        if formatted is not None:
            return formatted
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            from_pattern = self._from_pattern(schema, pattern)
            if from_pattern is not None:
                return from_pattern
        return self._fit_length(self._by_name(name), schema)

    def _format(self, fmt: str) -> str | None:
        f, rng = self.faker, self.rng
        if fmt == "uuid":
            return str(uuid.UUID(int=rng.getrandbits(128), version=4))
        if fmt == "date-time":
            return self._moment().isoformat().replace("+00:00", "Z")
        if fmt == "date":
            return self._moment().date().isoformat()
        if fmt == "time":
            return self._moment().strftime("%H:%M:%SZ")
        table: dict[str, Callable[[], str]] = {
            "email": f.email,
            "idn-email": f.email,
            "uri": f.url,
            "url": f.url,
            "uri-reference": f.url,
            "iri": f.url,
            "hostname": f.domain_name,
            "idn-hostname": f.domain_name,
            "ipv4": f.ipv4,
            "ipv6": f.ipv6,
            "password": lambda: f.password(length=12),
            "byte": lambda: "aGVsbG8gd29ybGQ=",
            "binary": lambda: "binary-data",
            "phone": f.phone_number,
        }
        return table[fmt]() if fmt in table else None

    def _moment(self) -> dt.datetime:
        # Anchored to a fixed date: basing this on the wall clock would break repeatable output.
        anchor = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        return (anchor + dt.timedelta(seconds=self.rng.randint(0, 31_536_000))).replace(
            microsecond=0
        )

    def _from_pattern(self, schema: dict[str, Any], pattern: str) -> str | None:
        low, high = schema.get("minLength"), schema.get("maxLength")
        try:
            for _ in range(6):
                candidate = _Xeger(self.rng).xeger(pattern)
                if isinstance(high, int) and len(candidate) > high:
                    continue
                if isinstance(low, int) and len(candidate) < low:
                    continue
                if regex.search(pattern, candidate, timeout=0.05):
                    return candidate
        except Exception:  # noqa: BLE001 - xeger raises many things on unusual syntax
            return None
        return None

    def _by_name(self, name: str | None) -> str:
        normal = _normal(name)
        maker = _STRING_NAMES.get(normal)
        if maker:
            return maker(self.faker)
        if normal == "id" or normal.endswith("id"):
            return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
        if normal.endswith(("at", "date", "time")) and len(normal) > 2:
            return self._moment().isoformat().replace("+00:00", "Z")
        if normal.endswith("url"):
            return self.faker.url()
        if normal.endswith("email"):
            return self.faker.email()
        if normal.endswith("name"):
            return self.faker.word().capitalize()
        return self.faker.word()

    def _fit_length(self, value: str, schema: dict[str, Any]) -> str:
        low, high = schema.get("minLength"), schema.get("maxLength")
        if isinstance(high, int) and high >= 0 and len(value) > high:
            value = value[:high]
        if isinstance(low, int) and len(value) < low:
            value += "".join(self.rng.choices(string.ascii_lowercase, k=low - len(value)))
        return value


def _ceil(value: float) -> int:
    whole = int(value)
    return whole if whole >= value else whole + 1


def _floor(value: float) -> int:
    whole = int(value)
    return whole if whole <= value else whole - 1
