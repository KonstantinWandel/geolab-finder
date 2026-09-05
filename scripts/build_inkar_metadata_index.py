#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

try:
    import faiss  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("faiss is required to build the INKAR index") from exc

from sentence_transformers import SentenceTransformer


DEFAULT_INPUT = (
    "/home/ubuntu/destatis-rag/soep_metadata_output/"
    "Indikatorenübersicht (INKAR 2025).xlsx"
)
DEFAULT_BBSR_REFERENCE = (
    "/home/ubuntu/destatis-rag/soep_metadata_output/"
    "BBSR_Raumgliederungen_Referenz_2023.xlsx"
)
DEFAULT_OUTPUT_DIR = "/home/ubuntu/destatis-rag/soep_metadata_output"
INKAR_SOURCE_URL = "https://www.inkar.de/"
INKAR_SELECTOR_URL = "https://www.inkar.de/SelectOrder"
BBSR_REFERENCE_URL = (
    "https://www.bbsr.bund.de/BBSR/DE/forschung/raumbeobachtung/"
    "Raumabgrenzungen/raumabgrenzungen-uebersicht"
)
# What scripts/fetch_inkar_geodienste.py collected: the subset of INKAR indicators the BBSR also
# publishes as a WMS layer and as a metadata record in the national Geodatenkatalog.
GEODIENSTE_PATH = Path(__file__).resolve().parents[1] / "data_sources" / "22-inkar" / "raw" / "geodienste.json"


def normalise_title(text: str) -> str:
    lowered = clean_value(text).lower()
    for source, target in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        lowered = lowered.replace(source, target)
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def load_geodienste(path: Path = GEODIENSTE_PATH) -> Dict[str, Any]:
    """Title -> WMS layer and catalogue record. Missing file is not an error: the records then
    carry the portal link and nothing extra, which is what they carried before."""
    if not path.exists():
        return {"layers": {}, "records": {}, "meta": {}}
    document = json.loads(path.read_text(encoding="utf-8"))
    layers: Dict[str, List[Dict[str, str]]] = {}
    for layer in document.get("layers", []):
        layers.setdefault(normalise_title(layer.get("title", "")), []).append(layer)
    records = {normalise_title(r.get("title", "")): r
               for r in document.get("records", []) if r.get("resolves") is not False}
    return {"layers": layers, "records": records, "meta": document}


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def clean_mid(value: Any) -> str:
    text = clean_value(value)
    if not text:
        return ""
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except Exception:
        pass
    return text


def split_theme(label: str) -> Dict[str, str]:
    for sep in [" - ", " – ", " — "]:
        if sep in label:
            left, right = label.split(sep, 1)
            return {
                "theme": clean_value(left),
                "subtheme": clean_value(right),
                "theme_path": label,
            }
    return {"theme": label, "subtheme": "", "theme_path": label}


def format_spatial_levels(row: pd.Series) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for column in ["Gemeinden", "Kreise", "NUTS2"]:
        if column in row.index:
            value = clean_value(row.get(column))
            if value:
                out[column] = value
    return out


def parse_years(text: str) -> Dict[str, Any]:
    years = [int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", text or "")]
    if not years:
        return {"year_start": None, "year_end": None, "years": []}
    return {"year_start": min(years), "year_end": max(years), "years": sorted(set(years))}


def infer_nuts_levels(spatial_coverage: Dict[str, str]) -> List[str]:
    out: List[str] = []
    for level in spatial_coverage:
        level_lower = level.lower()
        if level_lower == "nuts2":
            out.append("NUTS2")
        elif level_lower == "kreise":
            out.extend(["Kreise", "NUTS3"])
        elif level_lower == "gemeinden":
            out.extend(["Gemeinden", "LAU"])
    return sorted(set(out))


def load_bbsr_reference(reference_path: Path) -> Dict[str, Any]:
    if not reference_path.exists():
        return {}

    reference: Dict[str, Any] = {
        "source": "BBSR Raumgliederungssystem 2023",
        "reference_year": 2023,
        "published": "2025-02-04",
        "source_url": BBSR_REFERENCE_URL,
        "sheets": [],
        "geography_fields": [],
    }

    excel = pd.ExcelFile(reference_path)
    reference["sheets"] = excel.sheet_names
    for sheet in ["Gemeindereferenz (inkl. Kreise)", "Kreisreferenz"]:
        if sheet not in excel.sheet_names:
            continue
        columns = pd.read_excel(reference_path, sheet_name=sheet, header=[0, 1], nrows=0).columns
        for short_name, description in columns:
            short_name = clean_value(short_name)
            description = clean_value(description)
            if not short_name or short_name.endswith("_NAME") is False:
                continue
            reference["geography_fields"].append(
                {
                    "sheet": sheet,
                    "field": short_name,
                    "description": description,
                }
            )

    return reference


def build_bbsr_context(reference: Dict[str, Any]) -> str:
    if not reference:
        return ""
    important_terms = [
        item["description"]
        for item in reference.get("geography_fields", [])
        if any(
            term in item.get("description", "")
            for term in [
                "NUTS2",
                "NUTS3",
                "Städtischer-Ländlicher Raum",
                "Siedlungsstruktureller",
                "RegioStaR",
                "Degree of Urbanisation",
                "Kreise",
                "Gemeinden",
            ]
        )
    ]
    important_terms = important_terms[:18]
    return join_nonempty(
        [
            "BBSR geography reference: Raumgliederungssystem 2023.",
            f"BBSR source URL: {reference.get('source_url', '')}",
            "Relevant geography vocabularies: " + "; ".join(important_terms),
        ]
    )


def join_nonempty(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if clean_value(line))


def build_embedding_context(row: Dict[str, Any]) -> str:
    spatial = row.get("spatial_coverage", {})
    spatial_text = "; ".join(f"{k}: {v}" for k, v in spatial.items())
    return join_nonempty(
        [
            "Source: INKAR 2025, BBSR Raum- und Stadtentwicklung",
            f"Sheet: {row.get('sheet', '')}",
            f"Theme: {row.get('theme_path', '')}",
            f"Indicator short name: {row.get('short_name', '')}",
            f"Indicator full name: {row.get('name', '')}",
            f"Indicator code / Kuerzel: {row.get('indicator_code', '')}",
            f"M_ID: {row.get('m_id', '')}",
            f"Algorithm: {row.get('algorithm', '')}",
            f"Notes and definition: {row.get('notes', '')}",
            f"Statistical basis: {row.get('statistical_basis', '')}",
            f"Spatial coverage and years: {spatial_text}",
            f"NUTS and geography aliases: {', '.join(row.get('nuts_levels', []))}",
            f"Geography reference: {row.get('geography_reference', '')}",
            f"BBSR vocabulary context: {row.get('bbsr_reference_context', '')}",
            f"BBSR reference URL: {row.get('bbsr_reference_url', '')}",
            f"Source URL: {row.get('source_url', '')}",
        ]
    )


def geodienste_for(record: Dict[str, Any], geodienste: Dict[str, Any]) -> Dict[str, Any]:
    """The BBSR service addresses for one indicator, matched on its name.

    About 80 of the 660 indicators are in the WMS and in the catalogue. They keep the portal as
    their link, because that is where the numbers are; what they gain is the exact layer name for
    a GIS client and a metadata page that describes this one indicator.
    """
    keys = [normalise_title(record.get("short_name", "")), normalise_title(record.get("name", ""))]
    layer = next((geodienste["layers"][k][0] for k in keys if k in geodienste["layers"]), None)
    entry = next((geodienste["records"][k] for k in keys if k in geodienste["records"]), None)
    fields: Dict[str, Any] = {}
    parts: List[str] = []
    if layer:
        fields["wms_layer"] = layer["layer"]
        fields["wms_level"] = layer["level"]
        fields["wms_url"] = geodienste["meta"].get("wms", "")
        parts.append(f"Als WMS-Ebene {layer['layer']} ({layer['level']}) im BBSR-Dienst "
                     f"{fields['wms_url']}?request=GetCapabilities&service=WMS abrufbar.")
    if entry:
        fields["catalogue_id"] = entry["id"]
        fields["catalogue_url"] = geodienste["meta"].get("catalogue_page", "") + entry["id"]
        parts.append(f"Metadaten zu diesem Indikator im Geodatenkatalog: {fields['catalogue_url']}")
    return {"fields": fields, "hint": " ".join(parts)}


def flatten_workbook(input_path: Path, bbsr_reference: Dict[str, Any]) -> List[Dict[str, Any]]:
    geodienste = load_geodienste()
    excel = pd.ExcelFile(input_path)
    rows: List[Dict[str, Any]] = []
    skipped_sheets = {"Nutzungshinweise"}
    bbsr_context = build_bbsr_context(bbsr_reference)

    for sheet in excel.sheet_names:
        if sheet in skipped_sheets:
            continue

        df = pd.read_excel(input_path, sheet_name=sheet, header=1)
        current_theme = ""
        current_subtheme = ""
        current_theme_path = ""

        for raw_index, row in df.iterrows():
            short_name = clean_value(row.get("Kurzname"))
            name = clean_value(row.get("Name"))
            m_id = clean_mid(row.get("M_ID"))
            indicator_code = clean_value(row.get("Kürzel"))

            is_indicator = bool(m_id or indicator_code) and bool(short_name or name)
            if not is_indicator:
                if short_name:
                    theme_parts = split_theme(short_name)
                    current_theme = theme_parts["theme"]
                    current_subtheme = theme_parts["subtheme"]
                    current_theme_path = theme_parts["theme_path"]
                continue

            spatial_coverage = format_spatial_levels(row)
            spatial_year_meta = parse_years(" ".join(spatial_coverage.values()))
            record: Dict[str, Any] = {
                "source": "INKAR 2025",
                "sheet": sheet,
                "row_number": int(raw_index) + 3,
                "theme": current_theme,
                "subtheme": current_subtheme,
                "theme_path": current_theme_path,
                "short_name": short_name,
                "name": name,
                "algorithm": clean_value(row.get("Algorithmus")),
                "m_id": m_id,
                "indicator_code": indicator_code,
                "notes": clean_value(row.get("Anmerkungen")),
                "statistical_basis": clean_value(row.get("Statistische Grundlagen")),
                "spatial_coverage": spatial_coverage,
                "spatial_levels": sorted(spatial_coverage.keys()),
                "nuts_levels": infer_nuts_levels(spatial_coverage),
                "year_start": spatial_year_meta["year_start"],
                "year_end": spatial_year_meta["year_end"],
                "available_years": spatial_year_meta["years"],
                "spatial_coverage_text": "; ".join(
                    f"{level}: {years}" for level, years in spatial_coverage.items()
                ),
                "geography_reference": (
                    "BBSR Raumgliederungssystem 2023: municipalities/Gemeinden, districts/Kreise-NUTS3, "
                    "NUTS2, BBSR settlement structure, RegioStaR, central-place and urban-rural typologies."
                ),
                "bbsr_reference_url": BBSR_REFERENCE_URL,
                "bbsr_reference_context": bbsr_context,
                "source_url": INKAR_SOURCE_URL,
                "selector_url": INKAR_SELECTOR_URL,
                "indicator_url": INKAR_SOURCE_URL,
                "portal_url": INKAR_SOURCE_URL,
                # INKAR keeps no state in its address: the table and map windows read their
                # selection from the window that opened them, and the only thing a URL can carry
                # is the id of a query stored on the BBSR server. So the link is the portal, and
                # saying so is what lets the finder show the reader which name to search for.
                "link_level": "portal",
                "link_verified": True,
                "api_hint": (
                    f"INKAR indicator code/Kuerzel={indicator_code}; M_ID={m_id}. "
                    f"In INKAR unter „{current_theme_path}“ nach „{short_name or name}“ suchen. "
                    "Use the INKAR UI or an INKAR API wrapper such as inkaR with this indicator identifier."
                ),
            }
            services = geodienste_for(record, geodienste)
            record.update(services["fields"])
            if services["hint"]:
                record["api_hint"] = record["api_hint"] + " " + services["hint"]
            record["embedding_context"] = build_embedding_context(record)
            rows.append(record)

    return rows


def write_metadata(rows: List[Dict[str, Any]], output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "inkar_metadata_2025.json"
    csv_path = output_dir / "inkar_metadata_2025.csv"
    parquet_path = output_dir / "inkar_metadata_2025.parquet"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)

    df = pd.DataFrame(rows)
    df["spatial_coverage"] = df["spatial_coverage"].apply(json.dumps, ensure_ascii=False)
    for column in ["spatial_levels", "nuts_levels", "available_years"]:
        df[column] = df[column].apply(json.dumps, ensure_ascii=False)
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)

    return {"json": json_path, "csv": csv_path, "parquet": parquet_path}


def write_bbsr_reference(reference: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    if not reference:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "bbsr_geography_reference_2023.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(reference, handle, ensure_ascii=False, indent=2)
    return path


def build_index(
    rows: List[Dict[str, Any]],
    output_dir: Path,
    model_name: str,
    device: str,
    batch_size: int,
) -> Dict[str, Path]:
    docs = [row["embedding_context"] for row in rows]
    model = SentenceTransformer(model_name, device=device)
    embeddings = model.encode(
        docs,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype("float32")

    embeddings_path = output_dir / "inkar_rag_embeddings.npy"
    index_path = output_dir / "inkar_rag_index.faiss"
    np.save(embeddings_path, embeddings)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, str(index_path))

    return {"embeddings": embeddings_path, "faiss": index_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten and vectorize INKAR 2025 metadata.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--bbsr-reference", default=DEFAULT_BBSR_REFERENCE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--model",
        default=os.getenv("INKAR_EMBEDDING_MODEL", os.getenv("SOEP_EMBEDDING_MODEL", "BAAI/bge-m3")),
    )
    parser.add_argument("--device", default=os.getenv("INKAR_RAG_DEVICE", "cuda"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("INKAR_BATCH_SIZE", "8")))
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    bbsr_reference = load_bbsr_reference(Path(args.bbsr_reference))
    rows = flatten_workbook(input_path, bbsr_reference)
    if not rows:
        raise RuntimeError("No INKAR indicator rows were parsed from the workbook.")

    metadata_paths = write_metadata(rows, output_dir)
    bbsr_reference_path = write_bbsr_reference(bbsr_reference, output_dir)
    index_paths = build_index(rows, output_dir, args.model, args.device, args.batch_size)

    summary = {
        "input": str(input_path),
        "output_dir": str(output_dir),
        "rows": len(rows),
        "model": args.model,
        "device": args.device,
        "metadata": {key: str(value) for key, value in metadata_paths.items()},
        "bbsr_reference": str(bbsr_reference_path) if bbsr_reference_path else None,
        "index": {key: str(value) for key, value in index_paths.items()},
    }
    summary_path = output_dir / "inkar_metadata_build_summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
