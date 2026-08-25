#!/usr/bin/env python3
"""Read the layer and field schema out of a zipped GeoPackage without keeping the data.

The Gigabit-Grundbuch raster files are 0.3 to 1.8 GB uncompressed, and the finder only
needs to know which layers and attributes they contain. A GeoPackage is a SQLite file, so
this extracts the archive into a temporary directory under $HOME (the pod's /tmp is small),
reads `gpkg_contents` plus each table's columns, writes a small JSON next to the archive,
and deletes the extracted copy again.

Run:
  python scripts/extract_gpkg_schema.py data_sources/02-breitband-monitor/raw/*.zip
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List


def schema_of(gpkg_path: Path) -> Dict[str, Any]:
    connection = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        layers: List[Dict[str, Any]] = []
        try:
            rows = cursor.execute(
                "SELECT table_name, data_type, identifier, description FROM gpkg_contents"
            ).fetchall()
        except sqlite3.Error:
            rows = [(name, "table", name, "") for (name,) in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'gpkg_%'"
            ).fetchall()]
        for table_name, data_type, identifier, description in rows:
            columns = [
                {"name": row[1], "type": row[2]}
                for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            ]
            try:
                count = cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            except sqlite3.Error:
                count = None
            layers.append({
                "table": table_name, "data_type": data_type, "identifier": identifier,
                "description": description, "rows": count, "columns": columns,
            })
        return {"layers": layers}
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archives", nargs="+")
    args = parser.parse_args()

    workroot = Path.home() / "tmp"
    workroot.mkdir(exist_ok=True)

    for raw_path in args.archives:
        archive_path = Path(raw_path)
        with zipfile.ZipFile(archive_path) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".gpkg")]
            notes = [n for n in archive.namelist() if n.lower().endswith(".txt")]
            if not members:
                print(f"[skip] {archive_path.name}: no .gpkg inside")
                continue
            work_dir = Path(tempfile.mkdtemp(prefix="gpkg_", dir=workroot))
            try:
                extracted = Path(archive.extract(members[0], path=work_dir))
                payload = schema_of(extracted)
                payload["archive"] = archive_path.name
                payload["gpkg"] = members[0]
                payload["readme"] = {
                    name: archive.read(name).decode("utf-8", "replace")[:2000] for name in notes
                }
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

        out_path = archive_path.with_name(archive_path.stem.replace("_gpkg", "") + "_schema.json")
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] {out_path.name}: {len(payload['layers'])} layer(s), "
              f"{sum(len(l['columns']) for l in payload['layers'])} columns")


if __name__ == "__main__":
    main()
