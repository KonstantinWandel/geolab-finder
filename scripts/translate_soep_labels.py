#!/usr/bin/env python3
"""Fill the missing half of a SOEP variable label pair, by machine translation.

Why this and not generated descriptions: the finder's own retrieval eval showed the failure
directly. `pgen/pgfamstd` carries the German label "Marital Status" and the whole wealth family
carries "HH Net Overall Wealth imp.a", so a German query for "Familienstand" or "Nettovermögen"
cannot match them at all; 1,973 analysis variables have no English label (SOEP marks them
"[de] ..."), so the same holds for English queries. Translating a label SOEP already published
is a restatement of an existing fact. Writing a description would be a new claim about a
variable's meaning, which is exactly what must not be invented.

Rules this follows:
  * the official label is never overwritten. Translations land in `label_de_mt` / `label_en_mt`
    and are marked as machine translation wherever they surface.
  * only the missing side is filled, and only when the source side's language is unambiguous.
    A label that could be either language ("Status", "Interviewer") is skipped rather than
    guessed at.
  * temperature 0 and a prompt that forbids adding words, so the output is a translation and
    not a paraphrase.

Runs on the local H200 with the cached Qwen2.5-32B-Instruct. Resumable: an existing output file
is loaded first and only missing keys are translated.

    setsid ~/miniconda3/envs/vllm/bin/python scripts/translate_soep_labels.py \\
        </dev/null >>logs/translate_labels.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA = REPO_ROOT / "soep_metadata_output" / "soep_v41_metadata.json"
OUT_PATH = REPO_ROOT / "soep_metadata_output" / "soep_label_translations.json"
MODEL = "Qwen/Qwen2.5-32B-Instruct"

# Tokens that exist in BOTH languages are in neither list: "in", "person", "status", "art" and
# above all "kind" (German for child), which classified "Kind gestillt" as English on the first
# run and would have had the model translate a German label into German.
GERMAN_MARKERS = re.compile(
    r"[äöüßÄÖÜ]|\b(der|die|das|und|oder|nicht|mit|ohne|für|von|dem|den|des|zur|zum|"
    r"jahr|jahre|monat|anzahl|höhe|bei|seit|nach|vor|über|unter|wie|ob|kein|keine|"
    r"kind|kinder|geschlecht|alter|zufriedenheit|erwerb|haushalt|beruf|arbeit|einkommen|"
    r"gesundheit|wohnung|befragte|befragten|angabe|angaben|sonstige|derzeit)\b", re.I)
ENGLISH_MARKERS = re.compile(
    r"\b(the|of|and|or|not|with|without|for|from|on|at|by|is|are|was|were|has|have|"
    r"number|year|years|month|amount|income|household|health|current|overall|net|"
    r"gross|first|last|other|child|children|survey|type|share|rate|been|does|about)\b", re.I)

PROMPT_SYSTEM = (
    "You translate variable labels from the German Socio-Economic Panel (SOEP). "
    "A label is a terse codebook caption, not a sentence. "
    "Translate it and output ONLY the translation, nothing else. "
    "Keep every code, abbreviation and bracketed part exactly as it is "
    "(imp.a, HH, gen., v1, [harmonisiert], [2019-2024], SGB II, ISCO-88). "
    "Do not add words, do not explain, do not expand abbreviations, do not add a final period "
    "that the source does not have. Keep the same order and the same brevity."
)
EXAMPLES: List[Tuple[str, str, str]] = [
    ("de->en", "Zufriedenheit HH-Einkommen", "Satisfaction with household income"),
    ("de->en", "Tatsächliche Arbeitszeit pro Woche", "Actual working hours per week"),
    ("de->en", "Wie oft Fleisch", "How often meat"),
    ("de->en", "Vereinbarte Arbeitszeit o. UeStd. Std./Wo. KA [harmonisiert]",
     "Agreed working hours excl. overtime hrs/week, no answer [harmonisiert]"),
    ("en->de", "HH Net Overall Wealth imp.a", "HH-Nettogesamtvermögen imp.a"),
    ("en->de", "Marital Status In Survey Year", "Familienstand im Erhebungsjahr"),
    ("en->de", "Number of Years of Education", "Anzahl der Bildungsjahre"),
    ("en->de", "Ch. is nervous, clinging in new situations",
     "Kind ist nervös, klammert in neuen Situationen"),
]


def language_of(text: str) -> str:
    """'de', 'en' or '' when the label is too short or too ambiguous to be sure."""
    text = (text or "").strip()
    if len(text) < 4:
        return ""
    german = len(GERMAN_MARKERS.findall(text))
    english = len(ENGLISH_MARKERS.findall(text))
    if re.search(r"[äöüßÄÖÜ]", text):
        german += 2
    if german and not english:
        return "de"
    if english and not german:
        return "en"
    if german > english + 1:
        return "de"
    if english > german + 1:
        return "en"
    return ""


def placeholder(text: str) -> bool:
    return bool(re.match(r"^\s*\[(de|en)\]", str(text or "")))


def gaps(records: List[Dict[str, Any]], include_raw: bool) -> List[Dict[str, str]]:
    """Which labels are missing a language, and in which direction."""
    todo: List[Dict[str, str]] = []
    for record in records:
        if record.get("is_raw") and not include_raw:
            continue
        label = str(record.get("label") or "").strip()
        label_en = str(record.get("label_en") or "").strip()
        key = f"{record.get('dataset')}/{record.get('variable_name')}"

        # English side missing: empty, a "[de] ..." placeholder, or a copy of the German label.
        english_missing = (not label_en or placeholder(label_en)
                           or (label_en == label and language_of(label) == "de"))
        # German side missing: the German field actually holds English. Language detection alone
        # is too timid for the short ones ("Marital Status" carries no marker either way, and
        # that is pgen/pgfamstd, one of the variables the eval showed as unfindable in German),
        # so a structural signal decides those: when the German field repeats the English one,
        # or is a prefix of it, there is no German label.
        repeats_english = bool(label and label_en and language_of(label_en) == "en" and (
            label == label_en or label_en.startswith(label) or label.startswith(label_en)))
        german_missing = bool(label) and (language_of(label) == "en" or repeats_english)

        if english_missing and language_of(label) == "de":
            todo.append({"key": key, "direction": "de->en", "source": label})
        elif german_missing:
            source = label_en if language_of(label_en) == "en" else label
            todo.append({"key": key, "direction": "en->de", "source": source})
    return todo


def build_prompt(direction: str, source: str) -> List[Dict[str, str]]:
    target = "English" if direction == "de->en" else "German"
    messages = [{"role": "system", "content": PROMPT_SYSTEM + f" Translate into {target}."}]
    for example_direction, source_text, target_text in EXAMPLES:
        if example_direction != direction:
            continue
        messages.append({"role": "user", "content": source_text})
        messages.append({"role": "assistant", "content": target_text})
    messages.append({"role": "user", "content": source})
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-raw", action="store_true",
                        help="also translate the raw questionnaire variables")
    parser.add_argument("--limit", type=int, default=0, help="translate at most N (smoke test)")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--dry-run", action="store_true", help="only report what is missing")
    args = parser.parse_args()

    records = json.loads(METADATA.read_text(encoding="utf-8"))
    todo = gaps(records, args.include_raw)
    done: Dict[str, Any] = {}
    if OUT_PATH.exists():
        done = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("translations") or {}
    pending = [item for item in todo if item["key"] not in done]
    counts: Dict[str, int] = {}
    for item in todo:
        counts[item["direction"]] = counts.get(item["direction"], 0) + 1
    print(json.dumps({"labels_missing_a_language": len(todo), "by_direction": counts,
                      "already_translated": len(done), "to_do": len(pending)}, indent=2),
          flush=True)
    if args.dry_run or not pending:
        for item in pending[:10]:
            print(f"   {item['direction']}  {item['key']:<28} {item['source'][:60]}")
        return
    if args.limit:
        pending = pending[: args.limit]

    from vllm import LLM, SamplingParams  # imported late so --dry-run needs no GPU

    # No explicit `quantization=`: this checkpoint is bf16, and forcing a quant kernel is the
    # documented way to make a 32B model crawl on this box.
    llm = LLM(model=args.model, dtype="auto", gpu_memory_utilization=0.85,
              max_model_len=1024, enforce_eager=False)
    sampling = SamplingParams(temperature=0.0, max_tokens=80, stop=["\n"])

    prompts = [build_prompt(item["direction"], item["source"]) for item in pending]
    print(f"[translate] {len(prompts)} labels on {args.model}", flush=True)
    outputs = llm.chat(prompts, sampling)

    for item, output in zip(pending, outputs):
        text = output.outputs[0].text.strip().strip('"').strip()
        # A translation that comes back longer than twice the source is a paraphrase, not a
        # translation; drop it rather than ship invented wording.
        if not text or len(text) > max(60, len(item["source"]) * 2.2):
            continue
        field = "label_en_mt" if item["direction"] == "de->en" else "label_de_mt"
        done[item["key"]] = {field: text, "source": item["source"],
                             "direction": item["direction"], "model": args.model}

    OUT_PATH.write_text(json.dumps({
        "model": args.model,
        "translated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Machine translation of the official SOEP label. The official label is never "
                "replaced; these are additional search text and must be shown as machine "
                "translation wherever they appear.",
        "translations": done,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"translated_total": len(done), "output": str(OUT_PATH)}, indent=2))


if __name__ == "__main__":
    main()
