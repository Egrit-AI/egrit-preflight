"""The small part of JSON Schema (2020-12) that schema/report.schema.json uses, so CI needs no extra package.

Supported: type (name or list), const, enum, pattern, required, properties, items, minItems, maxItems, minLength,
maxLength, and $ref to #/$defs/<name>. Anything else in a schema is ignored, which is why the real `jsonschema` package
is also run over the schema and fixtures by hand when the schema changes (see docs/report-contract.md).
"""

import re

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is(value, name):
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name]) and not (name != "boolean" and isinstance(value, bool))


def validate(doc, schema, root=None, path="$"):
    """A list of problems; empty if the document satisfies the schema."""
    root = root or schema
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return validate(doc, target, root, path)
    problems = []
    if "type" in schema:
        names = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
        if not any(_is(doc, n) for n in names):
            return [f"{path}: expected {names}"]
    if "const" in schema and (doc != schema["const"] or type(doc) is not type(schema["const"])):
        problems.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and doc not in schema["enum"]:
        problems.append(f"{path}: {doc!r} is not one of {schema['enum']}")
    if isinstance(doc, str):
        if "pattern" in schema and not re.search(schema["pattern"], doc):
            problems.append(f"{path}: does not match {schema['pattern']}")
        if "minLength" in schema and len(doc) < schema["minLength"]:
            problems.append(f"{path}: too short")
        if "maxLength" in schema and len(doc) > schema["maxLength"]:
            problems.append(f"{path}: too long")
    if isinstance(doc, dict):
        problems += [f"{path}: missing {k}" for k in schema.get("required", []) if k not in doc]
        for key, sub in schema.get("properties", {}).items():
            if key in doc:
                problems += validate(doc[key], sub, root, f"{path}.{key}")
    if isinstance(doc, list):
        if len(doc) < schema.get("minItems", 0):
            problems.append(f"{path}: too few items")
        if len(doc) > schema.get("maxItems", len(doc)):
            problems.append(f"{path}: too many items")
        if "items" in schema:
            for i, item in enumerate(doc):
                problems += validate(item, schema["items"], root, f"{path}[{i}]")
    return problems
