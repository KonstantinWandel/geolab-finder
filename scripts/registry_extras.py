"""Explicit API sources not carried by the predecessor's source workbook."""
import json


def supplement_sources(records, registry_dir):
    path = registry_dir / "additional_sources.json"
    if not path.exists():
        return records
    additions = json.loads(path.read_text())["sources"]
    extras = {r["slug"]: {**r, "source_origin": "additional"} for r in additions}
    if len(extras) != len(additions):
        raise ValueError("Duplicate additional source slug")
    result = []
    for record in records:
        if record["slug"] in extras:
            if record.get("source_origin") != "additional":
                raise ValueError("Additional source collides with a workbook source")
            result.append(extras.pop(record["slug"]))
        else:
            result.append(record)
    return result + list(extras.values())
