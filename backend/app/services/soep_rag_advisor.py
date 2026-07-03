import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None


# Canonical, analysis-ready SOEP datasets (generated + tracking files) vs. the
# age/group-specific subsample instruments. Used by the dataset-authority
# precision prior so the analysis-ready variable wins ties over chattier
# subsample items (the original "pglabnet buried under refugee/child panels" bug).
CORE_DATASETS = {"pgen", "pequiv", "ppathl", "hgen", "hpathl", "hpath"}      # generated/tracking
CORE_SURVEY_DATASETS = {"pl", "hl"}                                          # main person/HH survey
# Gross/administrative/exit-sample + employer-side families: almost never the
# canonical answer for a plain value/status query, but they leak to the top
# because they are large and lexically similar. Penalized for plain queries.
NOISE_DATASETS = {
    "pbrutto", "pbr_exit", "hbrutt", "hbrutto", "selfempl", "lee2estab",
    # Fieldwork/methodology files. `interviewer` (248 vars) is the worst offender: it
    # re-uses the person-questionnaire's variable names/labels (the interviewer answers
    # the same items about themselves, e.g. plh0172-0174 "Zufriedenheit ..."), plus
    # interviewer-characteristic items ("Geschlecht des Interviewers"). These clutter
    # substantive queries and, being duplicates, can win the dedup survivor slot over the
    # real `pl` item. Penalizing them fixes both (they sink, and the pl copy survives).
    "interviewer", "instrumentation", "design",
}
BIOGRAPHY_DATASETS = {"biol", "bioagel"}                                     # biography spells (mild)
SUBSAMPLE_DATASETS = {
    "jugendl", "youthl", "childl", "kidlong", "biopupil", "p_pupil", "refugspell",
}
# If the query itself is about a subsample, the subsample penalty is skipped so a
# genuinely relevant youth/child/refugee variable is never buried.
SUBSAMPLE_QUERY_TOKENS = {
    "youth", "adolescent", "adolescents", "teen", "teenager", "teenage", "pupil", "pupils",
    "school", "jugend", "jugendliche", "jugendlich", "schüler", "schueler",
    "child", "children", "childhood", "kind", "kinder", "kita",
    "refugee", "refugees", "geflüchtet", "geflüchtete", "flucht", "migrant", "migration",
}

# --- Sample / questionnaire groups ----------------------------------------
# A user-facing facet so one can narrow to "the adult Core person questionnaire"
# without knowing which dataset a variable lives in ("Geschlechterrollen" should
# be findable in pl without wading through jugendl/childl copies).
#
# IMPORTANT — this is a POPULATION / QUESTIONNAIRE grouping DERIVED FROM THE
# DATASET, not true SOEP sample membership. Real sample membership (Samples A-N;
# IAB-SOEP Migration M1/M2; IAB-BAMF-SOEP Refugee M3-M6) is a *respondent*
# attribute living in the psample/hsample VALUES inside tracking files
# (ppathl/hpathl/design), never a field on every variable. A single dataset
# (e.g. pl) pools respondents from all samples, so a group narrows the
# questionnaire/topic/population-role, not the sampling frame. Mapping grounded
# against paneldata.org / SOEPcompanion + inspected variable labels (2026-07).
SAMPLE_GROUP_LABELS = [
    ("core_person",          "Core - Individual (adult)"),
    ("core_household",       "Core - Household"),
    ("youth",                "Youth (16-17)"),
    ("children_parenting",   "Children & parenting"),
    ("biography_lifehistory","Biography & life-history"),
    ("migration_refugee",    "Migration & refugee"),
    ("employer_employee_lee","Employer-employee (SOEP-LEE2)"),
    ("regional_context",     "Regional context"),
    ("specialized_modules",  "Specialized modules & tests"),
    ("fieldwork_sampling",   "Fieldwork & sampling"),
    ("other",                "Other / unclassified"),
]
SAMPLE_GROUP_ORDER = {key: i for i, (key, _) in enumerate(SAMPLE_GROUP_LABELS)}
_SAMPLE_GROUP_MEMBERS = {
    "core_person":           {"pl", "pgen", "pequiv", "ppathl", "pkal", "pwealth", "selfempl", "plueckel", "gkal"},
    "core_household":        {"hl", "hgen", "hpathl", "hconsum", "hwealth", "housing", "mihinc"},
    "youth":                 {"jugendl", "youthl"},
    "children_parenting":    {"childl", "kidlong", "biopupil", "bioagel"},
    "biography_lifehistory": {"biol", "lkal", "artkalen", "pbiospe", "biobirth", "bioparen", "biojob",
                              "biosib", "bioedu", "biocouplm", "biocouply", "biomarsm", "biomarsy",
                              "biotwin", "lifespell", "vpl"},
    "migration_refugee":     {"migspell", "refugspell", "bioimmig", "cog_refu", "abroad", "more_local", "more_docu"},
    "employer_employee_lee": {"lee2estab", "lee2person", "lee2brutto"},
    "regional_context":      {"regionl"},
    "fieldwork_sampling":    {"pbrutto", "hbrutt", "hbrutto", "pbr_exit", "pbr_hhch", "interviewer",
                              "instrumentation", "design"},
    "specialized_modules":   {"health", "gripstr", "pflege", "cognit", "cogdj", "timepref", "trust", "camces"},
}
DATASET_SAMPLE_GROUP = {ds: grp for grp, members in _SAMPLE_GROUP_MEMBERS.items() for ds in members}

# Human-readable dataset names for display (instead of bare `{dataset}.rds` filenames).
# Distilled from the paneldata.org-grounded taxonomy notes (2026-07); the raw dataset id is
# still shown in parentheses and used for filtering/URLs. Descriptive, not verbatim official
# labels — swap in exact paneldata labels here if a canonical list is preferred.
DATASET_TITLE = {
    # Core - individual (person)
    "pl": "Individual questionnaire (long)", "pgen": "Person: generated variables",
    "pequiv": "Cross-National Equivalent File (person)", "ppathl": "Person tracking file (path)",
    "pkal": "Individual activity calendar", "pwealth": "Individual wealth (imputed)",
    "selfempl": "Self-employment module", "plueckel": "Catch-up (Lücke) individual questionnaire",
    "gkal": "Catch-up questionnaire calendar",
    # Core - household
    "hl": "Household questionnaire (long)", "hgen": "Household: generated variables",
    "hpathl": "Household tracking file (path)", "hconsum": "Household consumption",
    "hwealth": "Household wealth (imputed)", "housing": "Housing / dwelling module",
    "mihinc": "Household net income (imputed)",
    # Youth
    "jugendl": "Youth questionnaire (long)", "youthl": "Youth questionnaire (harmonized)",
    # Children & parenting
    "childl": "Child questionnaire (parent-reported)", "kidlong": "Child longitudinal file",
    "biopupil": "Pupil / school-child questionnaire", "bioagel": "Child development by age",
    # Biography & life-history
    "biol": "Biography questionnaire", "lkal": "Biography life-course calendar",
    "artkalen": "Activity-spell calendar (Artkalender)", "pbiospe": "Biography spell file",
    "biobirth": "Birth / fertility biography", "bioparen": "Parents' biography",
    "biojob": "First-job biography", "biosib": "Siblings file", "bioedu": "Educational biography",
    "biocouplm": "Partnership spells (monthly)", "biocouply": "Partnership spells (yearly)",
    "biomarsm": "Marriage spells (monthly)", "biomarsy": "Marriage spells (yearly)",
    "biotwin": "Twins file", "lifespell": "Life / participation spells",
    "vpl": "Deceased-person questionnaire",
    # Migration & refugee
    "migspell": "Migration spells", "refugspell": "Refugee migration spells",
    "bioimmig": "Immigration biography", "cog_refu": "Refugee cognition tests",
    "abroad": "Life outside Germany (emigrants)", "more_local": "MORE refugee-mentoring (mentors)",
    "more_docu": "MORE refugee-mentoring (process)",
    # Employer-employee (SOEP-LEE2)
    "lee2estab": "SOEP-LEE2 establishment survey", "lee2person": "SOEP-LEE2 person-establishment link",
    "lee2brutto": "SOEP-LEE2 sampling frame",
    # Regional
    "regionl": "Regional context indicators",
    # Fieldwork & sampling
    "pbrutto": "Person fieldwork file (gross)", "hbrutt": "Household address / fieldwork file",
    "hbrutto": "Household fieldwork file (gross)", "pbr_exit": "Person fieldwork: leavers",
    "pbr_hhch": "Person fieldwork: household changes", "interviewer": "Interviewer characteristics",
    "instrumentation": "Survey mode / instrumentation", "design": "Sampling design & weights",
    # Specialized modules
    "health": "SF-12 health indices", "gripstr": "Grip-strength measurement",
    "pflege": "Care / nursing module", "cognit": "Cognitive-ability tests (adults)",
    "cogdj": "Cognitive tests (youth)", "timepref": "Time-preference experiment",
    "trust": "Trust-game experiment", "camces": "Education-qualification coding (CAMCES)",
}

# How SOEP result rows collapse duplicate variables (env-configurable):
#   "name_label" (default) - collapse only rows with the SAME variable_name AND label.
#       Safe: `sex`="Geschlecht" (respondent) and `sex`="Geschlecht des Kindes" (child)
#       share a name across datasets but differ in meaning, so they stay separate.
#       (430 variable_names recur across datasets here; 272 of them differ in label.)
#   "name"    - collapse purely by variable_name (aggressive; merges the 272 above).
#   "item_id" - no cross-dataset collapse (legacy: keyed on soep:{dataset}:{variable}).
SOEP_DEDUP_MODE = os.getenv("SOEP_RAG_SOEP_DEDUP", "name_label").strip().lower()


class SOEPRagAdvisorService:
    """Semantic metadata advisor for SOEP variables and regionalized INKAR indicators."""

    def __init__(self) -> None:
        # App mode: "all" (default), "soep", or "inkar". Controls which metadata
        # source(s) this instance loads and exposes, so one codebase can back both
        # the SOEP-only and the INKAR-only deployments.
        self.app_mode = os.getenv("GEOLAB_APP_MODE", "all").strip().lower()
        if self.app_mode not in {"all", "soep", "inkar"}:
            self.app_mode = "all"
        self.load_soep = self.app_mode in {"all", "soep"}
        self.load_inkar = self.app_mode in {"all", "inkar"}

        self.metadata_path = self._resolve_soep_metadata_path() if self.load_soep else None
        self.inkar_metadata_path = self._resolve_inkar_metadata_path() if self.load_inkar else None
        self.bbsr_reference_path = self._resolve_bbsr_reference_path() if self.load_inkar else None
        # Default bi-encoder: multilingual-e5-large-instruct. An A/B over the corpus
        # (bge-m3, e5-instruct, Qwen3-Embedding-4B, arctic-embed-l-v2.0) showed e5 is the
        # only model that surfaces terse German concept queries (e.g. "Geschlechterrollen"
        # -> adult-Core gender-role battery, dense rank 2 vs 203 for bge-m3). e5 needs an
        # instruction prefix on queries (see _format_query); documents are embedded raw.
        self.model_name = os.getenv("SOEP_EMBEDDING_MODEL", "intfloat/multilingual-e5-large-instruct")
        self.embedding_max_seq_length = int(os.getenv("SOEP_EMBEDDING_MAX_SEQ_LENGTH", "512"))
        self.top_k_default = 8

        retrieval_device = os.getenv("SOEP_RAG_DEVICE", "cpu")
        self.retrieval_device = retrieval_device if retrieval_device == "cpu" or torch.cuda.is_available() else "cpu"
        llm_device = os.getenv("SOEP_RAG_LLM_DEVICE", os.getenv("DESTATIS_RAG_DEVICE", "cuda"))
        self.llm_device = llm_device if llm_device == "cpu" or torch.cuda.is_available() else "cpu"

        self._rows: List[Dict[str, Any]] = []
        self._docs: List[str] = []
        self._embeddings: Optional[np.ndarray] = None
        self._embedder: Optional[SentenceTransformer] = None
        self._faiss_index = None
        self._loaded = False
        self._cache_dir = Path(os.getenv("SOEP_RAG_CACHE_DIR", "/app/cache/soep"))
        self._bbsr_reference: Dict[str, Any] = {}

        self._use_llm = os.getenv("SOEP_RAG_LOAD_LLM", "0").lower() not in {"0", "false", "no"}
        self._llm_model_name = os.getenv("SOEP_RAG_LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
        self._llm_local_only = os.getenv("SOEP_RAG_LLM_LOCAL_ONLY", "1").lower() not in {"0", "false", "no"}
        self._llm_use_4bit = os.getenv("SOEP_RAG_LLM_USE_4BIT", "1").lower() not in {"0", "false", "no"}
        self._llm_attn_implementation = os.getenv("SOEP_RAG_LLM_ATTN_IMPLEMENTATION", "sdpa").strip() or None
        self._llm_max_new_tokens = int(os.getenv("SOEP_RAG_LLM_MAX_NEW_TOKENS", "420"))
        self._llm_pipe = None

        # Multilingual cross-encoder reranker, paired with the multilingual bge-m3
        # bi-encoder. The previous English-only ms-marco model rewarded literal English
        # matches in the enriched descriptions and could not read the terse German
        # variable labels, so canonical German-labelled variables (e.g. pgen/pglabnet)
        # were buried under chatty subsample items. Loaded lazily so embedding-build
        # jobs and process startup stay cheap.
        self._reranker_name = os.getenv("SOEP_RAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
        self._cross_enc: Optional[CrossEncoder] = None

        # Dataset-authority + exact-code precision prior. Small additive terms on
        # top of the fused [0,1] score; tune or disable via env.
        self._precision_boost = os.getenv("GEOLAB_PRECISION_BOOST", "1").lower() not in {"0", "false", "no"}
        self._auth_core = float(os.getenv("GEOLAB_AUTHORITY_CORE_BONUS", "0.06"))
        self._auth_survey = float(os.getenv("GEOLAB_AUTHORITY_SURVEY_BONUS", "0.05"))
        self._auth_noise = float(os.getenv("GEOLAB_AUTHORITY_NOISE_PENALTY", "0.10"))
        self._auth_bio = float(os.getenv("GEOLAB_AUTHORITY_BIO_PENALTY", "0.05"))
        self._auth_sub = float(os.getenv("GEOLAB_AUTHORITY_SUBSAMPLE_PENALTY", "0.06"))
        self._flag_penalty = float(os.getenv("GEOLAB_FLAG_PENALTY", "0.12"))
        self._exact_code_bonus = float(os.getenv("GEOLAB_EXACT_CODE_BONUS", "0.5"))
        self._code_token_bonus = float(os.getenv("GEOLAB_CODE_TOKEN_BONUS", "0.2"))

    def _new_embedder(self) -> SentenceTransformer:
        embedder = SentenceTransformer(self.model_name, device=self.retrieval_device)
        if self.embedding_max_seq_length > 0:
            embedder.max_seq_length = self.embedding_max_seq_length
        return embedder

    def _resolve_soep_metadata_path(self) -> Path:
        explicit_path = os.getenv("SOEP_RAG_METADATA_PATH")
        if explicit_path and os.path.exists(explicit_path):
            return Path(explicit_path)

        metadata_root = os.getenv("SOEP_METADATA_ROOT", "/app/data/soep")
        candidates = [
            os.path.join(metadata_root, "soep_metadata_enriched.json"),
            os.path.join(metadata_root, "soep_metadata_registry.json"),
            os.path.join(metadata_root, "soep_metadata_pdf.json"),
            os.path.join(metadata_root, "soep_metadata_manual.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return Path(candidate)
        raise FileNotFoundError("No SOEP metadata JSON found for RAG service.")

    def _resolve_inkar_metadata_path(self) -> Optional[Path]:
        explicit_path = os.getenv("INKAR_RAG_METADATA_PATH")
        if explicit_path and os.path.exists(explicit_path):
            return Path(explicit_path)

        metadata_root = os.getenv("INKAR_METADATA_ROOT", os.getenv("SOEP_METADATA_ROOT", "/app/data/soep"))
        candidate = Path(metadata_root) / "inkar_metadata_2025.json"
        return candidate if candidate.exists() else None

    def _resolve_bbsr_reference_path(self) -> Optional[Path]:
        explicit_path = os.getenv("BBSR_RAG_REFERENCE_PATH")
        if explicit_path and os.path.exists(explicit_path):
            return Path(explicit_path)

        metadata_root = os.getenv("INKAR_METADATA_ROOT", os.getenv("SOEP_METADATA_ROOT", "/app/data/soep"))
        candidate = Path(metadata_root) / "bbsr_geography_reference_2023.json"
        return candidate if candidate.exists() else None

    @staticmethod
    def _as_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and np.isnan(value):
            return ""
        return re.sub(r"\s+", " ", str(value)).strip()

    # --- Boilerplate stripping ------------------------------------------------
    # Every SOEP variable carries the same ~400-char block of standard missing-value
    # labels (codes -1..-9). Embedding that block makes ~56% of each SOEP document
    # byte-for-byte identical, collapsing the bi-encoder's ability to separate
    # variables. We drop those negative-coded entries (keeping any substantive
    # positive-coded categories) before building documents.
    @staticmethod
    def _strip_missing_value_labels(text: str) -> str:
        if not text:
            return ""
        kept = []
        for part in str(text).split(";"):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(-?\d+)\s*:", part)
            if m and int(m.group(1)) < 0:
                continue
            kept.append(part)
        return "; ".join(kept)

    @classmethod
    def _clean_embedding_context(cls, text: str) -> str:
        if not text:
            return ""
        out = []
        for line in str(text).splitlines():
            if line.startswith("Categories:"):
                cleaned = cls._strip_missing_value_labels(line[len("Categories:"):])
                if cleaned.strip():
                    out.append("Categories: " + cleaned)
                continue
            out.append(line)
        return "\n".join(out)

    @staticmethod
    def _extract_generated_description(text: str) -> str:
        """Keep the factual opening of the enriched description and drop generic
        use-case/related-concepts boilerplate that made subsample variables sound
        artificially broad."""
        if not text:
            return ""
        desc = re.sub(r"^Variable:\s*.*?\bDescription:\s*", "", str(text), flags=re.IGNORECASE | re.DOTALL)
        desc = re.split(r"\bLevel:|\bUse cases:|\bRelated concepts:|\bSource:", desc, flags=re.IGNORECASE)[0]
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", desc).strip())
        filtered = []
        generic = re.compile(
            r"economic well-being|financial situation|policy intervention|demographic groups|"
            r"life satisfaction|health outcomes|socio-economic outcomes|key indicator",
            re.IGNORECASE,
        )
        for sentence in sentences:
            if not sentence:
                continue
            if generic.search(sentence) and len(filtered) >= 1:
                continue
            filtered.append(sentence)
            if len(" ".join(filtered)) > 260 or len(filtered) >= 2:
                break
        return " ".join(filtered).strip()

    @staticmethod
    def _dataset_scope_note(dataset: str) -> str:
        dataset = (dataset or "").lower()
        core_generated = {
            "pgen": "Generated person-level SOEP-Core variable; usually preferred for standard individual labor, income, employment, and education measures.",
            "pequiv": "Generated equivalent-income file with standardized annual household and individual income, taxes, benefits, transfers, work hours, weights, and imputation flags.",
            "hgen": "Generated household-level SOEP-Core variable; usually preferred for standard household measures.",
            "ppathl": "Longitudinal person tracking file for stable person characteristics and sample information.",
            "pkal": "Person-year calendar/spell file; use for calendarized activity or employment histories.",
        }
        special = {
            "jugendl": "Youth/young-adult questionnaire instrument; use when the target population is adolescents or young adults, not as the default adult panel measure.",
            "childl": "Child questionnaire/instrument; use for child-focused analyses, not as the default adult panel measure.",
            "kidlong": "Child longitudinal file; use for child-focused analyses, not as the default adult panel measure.",
            "biopupil": "Pupil/child biography file; use for school-age child information, not as the default adult panel measure.",
            "refugspell": "Refugee/migration spell file; use for refugee or migration spell histories, not as the default SOEP-Core measure.",
        }
        return core_generated.get(dataset) or special.get(dataset) or ""

    @staticmethod
    def _soep_aliases(dataset: str, variable: str, label: str) -> str:
        text = f"{dataset} {variable} {label}".lower()
        aliases = []
        if dataset == "pequiv":
            aliases.append("SOEP equivalent income file, annual generated CNEF-style person and household variables")
        if "i11102" in text or "post-government income" in text:
            aliases.append("disposable household income after taxes and transfers, post-government household income")
        if "i11101" in text or "pre-government income" in text:
            aliases.append("pre-government household income before taxes and transfers")
        if "i11103" in text or "hh labor income" in text:
            aliases.append("annual household labor income")
        if "i11110" in text or "individual labor earnings" in text:
            aliases.append("annual individual labor earnings")
        if "w111" in text or "weight" in text or "hochrechnungsfaktor" in text:
            aliases.append("survey weight, sampling weight, cross-sectional or longitudinal analysis weight")
        if "pglabnet" in text or "nettoerwerb" in text:
            aliases.append("net labor earnings, net employment income, take-home pay from work")
        if "pglabgro" in text or "bruttoerwerb" in text:
            aliases.append("gross labor earnings, gross employment income before taxes and deductions")
        if "isced" in text:
            aliases.append("education classification, highest educational attainment, ISCED")
        return "; ".join(dict.fromkeys(aliases))

    @classmethod
    def _build_search_description(cls, row: Dict[str, Any], dataset: str, label: str) -> str:
        explicit = cls._as_text(row.get("search_description") or row.get("llm_search_description"))
        if explicit:
            return explicit
        factual = cls._extract_generated_description(row.get("rich_description", ""))
        scope_note = cls._dataset_scope_note(dataset)
        aliases = cls._soep_aliases(dataset, cls._as_text(row.get("variable_name")), label)
        parts = [
            f"SOEP variable {cls._as_text(row.get('variable_name'))}: {label}.",
            f"Dataset {dataset}. {scope_note}".strip(),
            f"Aliases: {aliases}." if aliases else "",
            factual,
        ]
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _inkar_aliases(row: Dict[str, Any]) -> str:
        text = " ".join(
            str(row.get(key, ""))
            for key in ("indicator_code", "m_id", "short_name", "name", "theme_path", "theme", "notes", "statistical_basis")
        ).lower()
        aliases = []
        patterns = [
            (r"pendlersaldo", "commuting, commuter balance, net commuter flow"),
            (r"einpend", "commuting, commuter inflow, inbound commuters"),
            (r"auspend", "commuting, commuter outflow, outbound commuters"),
            (r"\bpend|pendler", "commuting, commuters"),
            (r"ausländer|einbürger|schutzsuch", "foreign population, foreign residents, migration, asylum seekers, refugees, naturalization"),
            (r"miet|wohngeld|wohnung|wohnfläche|wohngebäude|wohnungs|leerstand", "housing, rent, asking rent, residential buildings, dwellings, vacancy"),
            (r"siedlungs- und verkehrsfläche|suv|flächennutzung|flächeninanspruchnahme", "land use, settlement and transport area, land take, built-up area"),
            (r"arbeitslos|alo", "unemployment, unemployment rate, unemployed people"),
            (r"bruttoinlandsprodukt|bip", "gross domestic product, GDP, economic output"),
            (r"breitband|mbit", "broadband, internet availability, digital infrastructure"),
            (r"betreuungsquote|kinderbetreuung", "childcare, child day care, children under 3, preschool care"),
            (r"ärzte|arzt|hausarzt|internist", "physicians, doctors, medical care, general practitioners"),
            (r"schulabgänger|schulabbrecher", "school leavers, school dropouts, without certificate"),
        ]
        aliases.extend(alias for pattern, alias in patterns if re.search(pattern, text, re.IGNORECASE))
        if re.search(r"bev65|65 jahre|abhängigenquote alte", text, re.IGNORECASE) and not re.search(
            r"arbeitslos|beschäftig|erwerbstätig|svw|alo", text, re.IGNORECASE
        ):
            aliases.append("older population, aged 65 and older, old-age dependency")
        return "; ".join(dict.fromkeys(aliases))


    @staticmethod
    def _parse_years(text: str) -> Tuple[Optional[int], Optional[int], List[int]]:
        years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", text or "")]
        if not years:
            return None, None, []
        return min(years), max(years), sorted(set(years))

    def _infer_inkar_spatial(self, spatial_coverage: Dict[str, str]) -> Tuple[List[str], List[str], Optional[int], Optional[int], str]:
        spatial_levels: List[str] = []
        nuts_levels: List[str] = []
        year_values: List[int] = []

        for level, year_text in (spatial_coverage or {}).items():
            clean_level = self._as_text(level)
            if not clean_level:
                continue
            spatial_levels.append(clean_level)
            start, end, years = self._parse_years(self._as_text(year_text))
            year_values.extend(years)
            if clean_level.lower() == "nuts2":
                nuts_levels.append("NUTS2")
            elif clean_level.lower() == "kreise":
                nuts_levels.extend(["Kreise", "NUTS3"])
            elif clean_level.lower() == "gemeinden":
                nuts_levels.extend(["Gemeinden", "LAU"])

        year_start = min(year_values) if year_values else None
        year_end = max(year_values) if year_values else None
        year_text = "; ".join(f"{level}: {years}" for level, years in (spatial_coverage or {}).items())
        return sorted(set(spatial_levels)), sorted(set(nuts_levels)), year_start, year_end, year_text

    def _normalise_soep_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        dataset = self._as_text(row.get("dataset"))
        variable = self._as_text(row.get("variable_name"))
        label = self._as_text(row.get("label"))
        rich_description = self._as_text(row.get("rich_description"))
        source_url = f"https://paneldata.org/soep-core/datasets/{dataset}/{variable}" if dataset and variable else ""
        spatial_levels: List[str] = []
        nuts_levels: List[str] = []
        lower_text = f"{dataset} {variable} {label} {rich_description}".lower()
        if dataset in {"regionl", "more_local"} or any(term in lower_text for term in ["regional", "county", "kreis", "gemeinde", "bundesland"]):
            spatial_levels.append("SOEP regional/linkage metadata")

        return {
            "source_key": "soep",
            "source_label": "SOEP-Core metadata",
            "item_type": "survey_variable",
            "item_id": f"soep:{dataset}:{variable}",
            "variable_name": variable,
            "label": label,
            "dataset": dataset,
            "dataset_label": (
                f"{DATASET_TITLE[dataset]} ({dataset})" if dataset in DATASET_TITLE
                else (f"{dataset}.rds" if dataset else "SOEP dataset")
            ),
            "sample_group": DATASET_SAMPLE_GROUP.get(dataset.lower(), "other"),
            "score": 0.0,
            "data_type": self._as_text(row.get("data_type")),
            "value_labels": self._strip_missing_value_labels(row.get("value_labels", "") or ""),
            "stats_summary": self._as_text(row.get("stats_summary")),
            "sample_values": self._as_text(row.get("sample_values")),
            "rich_description": rich_description,
            "search_description": self._build_search_description(row, dataset, label),
            "source_url": source_url,
            "theme": "SOEP survey variable",
            "sheet": "",
            "spatial_levels": spatial_levels,
            "nuts_levels": nuts_levels,
            "year_start": 1984,
            "year_end": 2023,
            "available_years_text": "SOEP-Core panel waves; verify exact variable-wave availability in the codebook.",
            "geography_reference": "",
            "embedding_context": self._clean_embedding_context(row.get("embedding_context", "") or ""),
        }

    def _normalise_inkar_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        spatial_coverage = row.get("spatial_coverage") or {}
        if isinstance(spatial_coverage, str):
            try:
                spatial_coverage = json.loads(spatial_coverage)
            except Exception:
                spatial_coverage = {}
        spatial_levels, nuts_levels, year_start, year_end, year_text = self._infer_inkar_spatial(spatial_coverage)
        indicator_code = self._as_text(row.get("indicator_code"))
        m_id = self._as_text(row.get("m_id"))
        short_name = self._as_text(row.get("short_name"))
        name = self._as_text(row.get("name"))
        theme = self._as_text(row.get("theme_path")) or self._as_text(row.get("theme"))
        aliases = self._inkar_aliases(row)

        return {
            "source_key": "inkar",
            "source_label": "INKAR 2025 indicators",
            "item_type": "regional_indicator",
            "item_id": f"inkar:{self._as_text(row.get('sheet'))}:{indicator_code or m_id}",
            "variable_name": indicator_code or m_id,
            "label": short_name or name,
            "dataset": "INKAR 2025",
            "dataset_label": self._as_text(row.get("sheet")) or "INKAR",
            "score": 0.0,
            "data_type": "regional indicator",
            "value_labels": "",
            "stats_summary": self._as_text(row.get("statistical_basis")),
            "sample_values": "",
            "rich_description": self._as_text(row.get("notes")) or name or short_name,
            "search_description": " ".join(
                part
                for part in [
                    self._as_text(row.get("search_description")) or self._as_text(row.get("embedding_context")),
                    f"Aliases: {aliases}." if aliases else "",
                ]
                if part
            ),
            "source_url": self._as_text(row.get("source_url")) or "https://www.inkar.de/",
            "selector_url": self._as_text(row.get("selector_url")) or "https://www.inkar.de/SelectOrder",
            "indicator_url": self._as_text(row.get("indicator_url")) or "https://www.inkar.de/",
            "api_hint": self._as_text(row.get("api_hint")),
            "theme": theme,
            "sheet": self._as_text(row.get("sheet")),
            "spatial_levels": spatial_levels,
            "nuts_levels": nuts_levels,
            "year_start": year_start,
            "year_end": year_end,
            "available_years_text": year_text or self._as_text(row.get("spatial_coverage_text")),
            "geography_reference": "BBSR Raumgliederungssystem 2023; includes municipalities, districts/NUTS3, NUTS2 and BBSR urban-rural typologies.",
            "embedding_context": row.get("embedding_context", ""),
        }

    def _build_doc(self, row: Dict[str, Any]) -> str:
        return "\n".join(
            part
            for part in [
                f"Source: {row.get('source_label', '')}",
                f"Type: {row.get('item_type', '')}",
                f"Identifier: {row.get('variable_name', '')}",
                f"Label: {row.get('label', '')}",
                f"Dataset: {row.get('dataset_label', row.get('dataset', ''))}",
                f"Theme: {row.get('theme', '')}",
                f"Spatial levels: {', '.join(row.get('spatial_levels') or [])}",
                f"NUTS/geography: {', '.join(row.get('nuts_levels') or [])}",
                f"Years: {row.get('available_years_text', '')}",
                f"Stats/basis: {row.get('stats_summary', '')}",
                f"Value labels: {row.get('value_labels', '')}",
                f"Context: {row.get('embedding_context', '')}",
                f"Description: {row.get('search_description') or row.get('rich_description', '')}",
                f"Geography reference: {row.get('geography_reference', '')}",
            ]
            if self._as_text(part)
        )

    def _load_json_rows(self, path: Path) -> List[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list in {path}")
        return data

    def _load_cached_embeddings(self, candidates: List[Path], expected_rows: int) -> Optional[np.ndarray]:
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                embeddings = np.load(candidate).astype("float32")
                if embeddings.shape[0] == expected_rows:
                    print(f"Loaded metadata embeddings from {candidate}")
                    return embeddings
            except Exception:
                continue
        return None

    def load(self) -> None:
        if self._loaded:
            return

        soep_rows: List[Dict[str, Any]] = []
        if self.load_soep and self.metadata_path is not None:
            raw_soep_rows = self._load_json_rows(self.metadata_path)
            soep_rows = [self._normalise_soep_row(row) for row in raw_soep_rows]
            print(f"Loaded {len(soep_rows)} SOEP metadata rows from {self.metadata_path}")

        inkar_rows: List[Dict[str, Any]] = []
        if self.load_inkar and self.inkar_metadata_path and self.inkar_metadata_path.exists():
            raw_inkar_rows = self._load_json_rows(self.inkar_metadata_path)
            inkar_rows = [self._normalise_inkar_row(row) for row in raw_inkar_rows]
            print(f"Loaded {len(inkar_rows)} INKAR metadata rows from {self.inkar_metadata_path}")

        if self.bbsr_reference_path and self.bbsr_reference_path.exists():
            try:
                with self.bbsr_reference_path.open("r", encoding="utf-8") as handle:
                    self._bbsr_reference = json.load(handle)
            except Exception:
                self._bbsr_reference = {}

        self._rows = soep_rows + inkar_rows
        self._docs = [self._build_doc(row) for row in self._rows]
        self._embedder = self._new_embedder()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        source_embeddings: List[np.ndarray] = []
        if soep_rows and self.metadata_path is not None:
            soep_embeddings = self._load_cached_embeddings(
                [
                    self.metadata_path.parent / "soep_rag_embeddings.npy",
                    self._cache_dir / "soep_rag_embeddings.npy",
                ],
                len(soep_rows),
            )
            if soep_embeddings is None:
                soep_docs = [self._build_doc(row) for row in soep_rows]
                soep_embeddings = self._embedder.encode(
                    soep_docs,
                    batch_size=32,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).astype("float32")
                try:
                    np.save(self._cache_dir / "soep_rag_embeddings.npy", soep_embeddings)
                except OSError:
                    pass
            source_embeddings.append(soep_embeddings)

        if inkar_rows:
            inkar_embeddings = self._load_cached_embeddings(
                [
                    self.inkar_metadata_path.parent / "inkar_rag_embeddings.npy" if self.inkar_metadata_path else Path(""),
                    self._cache_dir / "inkar_rag_embeddings.npy",
                ],
                len(inkar_rows),
            )
            if inkar_embeddings is None:
                inkar_docs = [self._build_doc(row) for row in inkar_rows]
                inkar_embeddings = self._embedder.encode(
                    inkar_docs,
                    batch_size=8,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).astype("float32")
                try:
                    np.save(self._cache_dir / "inkar_rag_embeddings.npy", inkar_embeddings)
                except OSError:
                    pass
            source_embeddings.append(inkar_embeddings)

        self._embeddings = np.vstack(source_embeddings).astype("float32")
        if faiss is not None:
            index = faiss.IndexFlatIP(self._embeddings.shape[1])
            index.add(self._embeddings)
            self._faiss_index = index

        self._loaded = True

    def build_and_save_embeddings(self, batch_size: int = 64) -> Dict[str, Any]:
        """Recompute bi-encoder embeddings for the active source(s) using the current
        document construction (including boilerplate stripping) and save them next to
        the metadata JSON, so serving containers load them from cache instead of
        embedding the full corpus on first query. Run inside the backend image so the
        model and code exactly match the runtime."""
        if self._embedder is None:
            self._embedder = self._new_embedder()
        summary: Dict[str, Any] = {
            "model": self.model_name,
            "device": self.retrieval_device,
            "max_seq_length": self.embedding_max_seq_length,
        }
        if self.load_soep and self.metadata_path is not None:
            rows = [self._normalise_soep_row(r) for r in self._load_json_rows(self.metadata_path)]
            docs = [self._build_doc(r) for r in rows]
            emb = self._embedder.encode(
                docs, batch_size=batch_size, convert_to_numpy=True,
                normalize_embeddings=True, show_progress_bar=True,
            ).astype("float32")
            out_path = self.metadata_path.parent / "soep_rag_embeddings.npy"
            np.save(out_path, emb)
            summary["soep"] = {"rows": len(rows), "dim": int(emb.shape[1]), "path": str(out_path)}
        if self.load_inkar and self.inkar_metadata_path and self.inkar_metadata_path.exists():
            rows = [self._normalise_inkar_row(r) for r in self._load_json_rows(self.inkar_metadata_path)]
            docs = [self._build_doc(r) for r in rows]
            emb = self._embedder.encode(
                docs, batch_size=batch_size, convert_to_numpy=True,
                normalize_embeddings=True, show_progress_bar=True,
            ).astype("float32")
            out_path = self.inkar_metadata_path.parent / "inkar_rag_embeddings.npy"
            np.save(out_path, emb)
            summary["inkar"] = {"rows": len(rows), "dim": int(emb.shape[1]), "path": str(out_path)}
        return summary

    def get_filter_options(self) -> Dict[str, Any]:
        self.load()
        all_sources = [
            {"value": "all", "label": "All metadata sources"},
            {"value": "soep", "label": "SOEP-Core variables"},
            {"value": "inkar", "label": "INKAR regional indicators"},
        ]
        if self.app_mode in {"soep", "inkar"}:
            sources = [s for s in all_sources if s["value"] == self.app_mode]
        else:
            sources = all_sources
        years = [
            year
            for row in self._rows
            for year in [row.get("year_start"), row.get("year_end")]
            if isinstance(year, int)
        ]
        return {
            "app_mode": self.app_mode,
            "sources": sources,
            "nuts_levels": sorted({level for row in self._rows for level in row.get("nuts_levels", [])}),
            "spatial_levels": sorted({level for row in self._rows for level in row.get("spatial_levels", [])}),
            "themes": sorted({row.get("theme", "") for row in self._rows if row.get("theme") and row.get("source_key") == "inkar"}),
            "datasets": sorted({row.get("dataset_label", row.get("dataset", "")) for row in self._rows if row.get("dataset_label") or row.get("dataset")}),
            # Sample/questionnaire groups present among SOEP rows, in display order.
            "sample_groups": [
                {"value": key, "label": label}
                for key, label in SAMPLE_GROUP_LABELS
                if key in {row.get("sample_group") for row in self._rows if row.get("source_key") == "soep"}
            ],
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "bbsr_reference": self._bbsr_reference,
        }

    def _passes_filters(self, row: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
        filters = filters or {}
        source = self._as_text(filters.get("dataset_scope") or filters.get("source") or "all").lower()
        if source and source != "all" and row.get("source_key") != source:
            return False

        dataset_label = self._as_text(filters.get("dataset_label"))
        if dataset_label and dataset_label != "All datasets" and dataset_label not in {
            row.get("dataset", ""),
            row.get("dataset_label", ""),
            row.get("sheet", ""),
        }:
            return False

        # Sample/questionnaire group (SOEP only). Accepts a list (multi-select) or
        # a scalar; INKAR rows have no sample group and are gated by source above.
        sample_groups = filters.get("sample_groups")
        if sample_groups:
            if isinstance(sample_groups, str):
                sample_groups = [sample_groups]
            wanted = {self._as_text(g) for g in sample_groups if self._as_text(g) and self._as_text(g) != "Any"}
            if wanted and row.get("source_key") == "soep" and row.get("sample_group") not in wanted:
                return False

        nuts_level = self._as_text(filters.get("nuts_level"))
        if nuts_level and nuts_level != "Any":
            if nuts_level not in (row.get("nuts_levels") or []) and nuts_level not in (row.get("spatial_levels") or []):
                return False

        spatial_level = self._as_text(filters.get("spatial_level"))
        if spatial_level and spatial_level != "Any":
            if spatial_level not in (row.get("spatial_levels") or []) and spatial_level not in (row.get("nuts_levels") or []):
                return False

        theme = self._as_text(filters.get("theme"))
        if theme and theme != "Any" and row.get("theme") != theme:
            return False

        if filters.get("regional_only") and not (row.get("spatial_levels") or row.get("nuts_levels")):
            return False

        year_start = filters.get("year_start")
        year_end = filters.get("year_end")
        try:
            year_start = int(year_start) if year_start not in {None, ""} else None
            year_end = int(year_end) if year_end not in {None, ""} else None
        except Exception:
            year_start = None
            year_end = None

        row_start = row.get("year_start")
        row_end = row.get("year_end")
        if isinstance(row_start, int) and isinstance(row_end, int):
            if year_start is not None and row_end < year_start:
                return False
            if year_end is not None and row_start > year_end:
                return False

        return True

    def _format_query(self, query: str) -> str:
        # e5-instruct models require an instruction prefix on QUERIES only (documents stay
        # raw). Without it e5 retrieval degrades sharply; bge-m3 and most others take the
        # raw query, so this is a no-op unless the configured model is an e5 variant.
        if "e5" in self.model_name.lower():
            task = os.getenv(
                "SOEP_RAG_E5_QUERY_TASK",
                "Given a search query, retrieve relevant survey-variable descriptions",
            )
            return f"Instruct: {task}\nQuery: {query}"
        return query

    def _search(self, query: str, k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self._rows or self._embedder is None or self._embeddings is None:
            raise RuntimeError("Metadata RAG advisor not loaded.")

        candidate_idx = [idx for idx, row in enumerate(self._rows) if self._passes_filters(row, filters)]
        if not candidate_idx:
            return []

        q_vec = self._embedder.encode(
            [self._format_query(query)],
            batch_size=1,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        candidates = self._embeddings[candidate_idx]
        score_vec = (candidates @ q_vec[0]).astype("float32")
        best_local_idx = np.argsort(score_vec)[::-1][: min(k, len(candidate_idx))]

        out = []
        for local_idx in best_local_idx:
            row_index = candidate_idx[int(local_idx)]
            row = dict(self._rows[row_index])
            row["score"] = float(score_vec[int(local_idx)])
            out.append(row)
        return out

    def _fallback_answer(self, splits: List[str], recommended: List[Dict[str, Any]], datasets_found: List[str]) -> str:
        rationale_lines = []
        for row in recommended:
            ident = row.get("variable_name", "")
            source = row.get("source_label", "")
            dataset = row.get("dataset_label") or row.get("dataset", "")
            label = row.get("label", "")
            rationale_lines.append(f"- `{ident}` ({source}, {dataset}): {label}")

        d_str = ", ".join(datasets_found) if datasets_found else "N/A"
        return (
            f"Detected {len(set(splits))} concepts and searched the selected metadata source(s).\n\n"
            "Suggested records are ranked below by semantic relevance and then reranked with a cross-encoder:\n"
            + "\n".join(rationale_lines)
            + "\n\n### GeoLAB Research Guide:\n"
            + "1. Use the source links to verify definitions, measurement level, and availability.\n"
            + f"2. Candidate data families involved: **{d_str}**.\n"
            + "3. For regional indicators, check the reported spatial level and year coverage before merging with survey or administrative data.\n"
        )

    def _get_reranker(self) -> CrossEncoder:
        if self._cross_enc is None:
            print(f"Loading reranker {self._reranker_name} on {self.retrieval_device}...")
            self._cross_enc = CrossEncoder(
                self._reranker_name, max_length=int(os.getenv("SOEP_RAG_RERANKER_MAX_LENGTH", "256")), device=self.retrieval_device
            )
        return self._cross_enc

    @staticmethod
    def _minmax(values: List[float]) -> List[float]:
        if not values:
            return []
        lo = min(values)
        hi = max(values)
        if hi <= lo:
            return [0.5 for _ in values]
        return [(v - lo) / (hi - lo) for v in values]

    @staticmethod
    def _tokens(text: str) -> set:
        return {
            token
            for token in re.findall(r"[\wäöüÄÖÜß]+", (text or "").lower())
            if len(token) > 2 or token.isdigit()
        }

    def _lexical_overlap_score(self, query: str, row: Dict[str, Any]) -> float:
        q_tokens = self._tokens(query)
        if not q_tokens:
            return 0.0
        doc = " ".join(
            self._as_text(row.get(key))
            for key in (
                "variable_name",
                "label",
                "dataset",
                "dataset_label",
                "theme",
                "search_description",
                "rich_description",
                "available_years_text",
            )
        )
        d_tokens = self._tokens(doc)
        if not d_tokens:
            return 0.0
        return len(q_tokens & d_tokens) / len(q_tokens)

    def _authority_delta(self, query: str, row: Dict[str, Any]) -> float:
        """Small additive precision prior on top of the fused [0,1] score.

        - Exact / token match on the variable code is decisive (typing ``pglabnet``
          should surface it first).
        - For SOEP survey variables, nudge canonical generated/tracking datasets
          (pgen, pequiv, ppathl, hgen, ...) up and age/group-specific subsample
          instruments (jugendl, childl, kidlong, biopupil, refugspell, ...) down,
          so the analysis-ready variable wins ties over chattier subsample items.

        Disabled via GEOLAB_PRECISION_BOOST=0.
        """
        if not self._precision_boost:
            return 0.0
        delta = 0.0
        var = self._as_text(row.get("variable_name")).lower()
        q_tokens = self._tokens(query)

        # 1) Exact / token code match (decisive).
        if var:
            if (query or "").strip().lower() == var:
                delta += self._exact_code_bonus
            elif var in q_tokens:
                delta += self._code_token_bonus

        # 2) De-prioritize imputation/flag variables on plain value queries
        #    (so e.g. pgimpnet doesn't outrank the value variable pglabnet),
        #    unless the user explicitly asked for imputation/flags.
        if not (q_tokens & {"imputation", "imputed", "imputiert", "flag", "imp"}):
            ds_core = row.get("source_key") == "soep" and self._as_text(row.get("dataset")).lower() in CORE_DATASETS
            text = f"{self._as_text(row.get('label'))} {self._as_text(row.get('search_description'))}".lower()
            if "imput" in text or ("imp" in var and ds_core):
                delta -= self._flag_penalty

        # 3) Dataset-authority prior (SOEP only; INKAR is a single source).
        if row.get("source_key") == "soep":
            ds = self._as_text(row.get("dataset")).lower()
            subsample_relevant = bool(q_tokens & SUBSAMPLE_QUERY_TOKENS)
            if ds in CORE_DATASETS:
                delta += self._auth_core
            elif ds in CORE_SURVEY_DATASETS:
                delta += self._auth_survey
            elif ds in NOISE_DATASETS:
                delta -= self._auth_noise
            elif ds in BIOGRAPHY_DATASETS:
                delta -= self._auth_bio
            elif ds in SUBSAMPLE_DATASETS and not subsample_relevant:
                delta -= self._auth_sub
        return delta

    @staticmethod
    def _dedup_key(cand: Dict[str, Any]):
        """One ranked slot per logical variable.

        INKAR: collapse the same indicator across sheets (keyed on the code).
        SOEP: collapse duplicate variables that recur across datasets. Default
        keys on (variable_name, label) so genuinely-different variables that
        merely share a name (e.g. `sex`="Geschlecht" vs "Geschlecht des Kindes")
        stay separate; configurable via SOEP_RAG_SOEP_DEDUP (see SOEP_DEDUP_MODE)."""
        if cand.get("source_key") == "inkar":
            return ("inkar", (cand.get("variable_name") or "").lower())
        variable = (cand.get("variable_name") or "").lower()
        if SOEP_DEDUP_MODE == "item_id":
            return cand.get("item_id")
        if SOEP_DEDUP_MODE == "name":
            return ("soep", variable)
        return ("soep", variable, (cand.get("label") or "").strip().lower())

    def _get_llm_pipe(self):
        if not self._use_llm:
            return None
        if self._llm_pipe is not None:
            return self._llm_pipe

        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

        tokenizer = AutoTokenizer.from_pretrained(
            self._llm_model_name,
            local_files_only=self._llm_local_only,
        )
        if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
            tokenizer.pad_token_id = tokenizer.eos_token_id

        model_kwargs: Dict[str, Any] = {
            "local_files_only": self._llm_local_only,
            "device_map": "auto" if self.llm_device != "cpu" else None,
        }
        if self.llm_device != "cpu":
            model_kwargs["torch_dtype"] = torch.bfloat16
            if self._llm_use_4bit:
                from transformers import BitsAndBytesConfig

                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                )
            if self._llm_attn_implementation:
                model_kwargs["attn_implementation"] = self._llm_attn_implementation
        else:
            model_kwargs["torch_dtype"] = torch.float32

        try:
            model = AutoModelForCausalLM.from_pretrained(self._llm_model_name, **model_kwargs)
        except Exception:
            if model_kwargs.pop("attn_implementation", None) is None:
                raise
            model = AutoModelForCausalLM.from_pretrained(self._llm_model_name, **model_kwargs)

        self._llm_pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)
        return self._llm_pipe

    def _render_llm_answer(
        self,
        question: str,
        splits: List[str],
        recommended: List[Dict[str, Any]],
        datasets_found: List[str],
    ) -> Optional[str]:
        llm_pipe = self._get_llm_pipe()
        if llm_pipe is None:
            return None

        concept_lines = "\n".join(f"- {split}" for split in splits)
        variable_lines = "\n".join(
            (
                f"- {row.get('variable_name', '')} ({row.get('source_label', '')}, "
                f"{row.get('dataset_label', row.get('dataset', ''))}): {row.get('label', '')} | "
                f"score={row.get('score', 0.0):.3f} | years={row.get('available_years_text', '')} | "
                f"spatial={', '.join(row.get('spatial_levels') or [])}"
            )
            for row in recommended
        )
        dataset_str = ", ".join(datasets_found) if datasets_found else "N/A"

        system_prompt = (
            "You are GeoLAB's local research advisor. Answer only from the retrieved metadata below. "
            "Do not invent datasets, variables, indicators, years, or geography levels."
        )
        user_prompt = (
            f"Research question: {question}\n\n"
            f"Detected concepts:\n{concept_lines}\n\n"
            f"Recommended metadata records:\n{variable_lines}\n\n"
            f"Data families involved: {dataset_str}\n\n"
            "Write four short sections with headings:\n"
            "1. Best measurement strategy\n"
            "2. Strongest records and what they capture\n"
            "3. Recommended merge/join logic\n"
            "4. Main caveats or missing pieces\n"
        )

        tokenizer = llm_pipe.tokenizer
        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            prompt = f"{system_prompt}\n\n{user_prompt}\n\nAnswer:"

        output = llm_pipe(
            prompt,
            max_new_tokens=self._llm_max_new_tokens,
            do_sample=False,
            return_full_text=False,
            pad_token_id=tokenizer.pad_token_id,
        )
        return output[0]["generated_text"].strip()

    def answer_research_question(
        self,
        question: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        k = top_k or self.top_k_default
        filters = filters or {}

        splits = re.split(r"\band\b|\bvs\b|\bversus\b|&|,", question, flags=re.IGNORECASE)
        splits = [s.strip() for s in splits if len(s.strip()) > 3]
        if not splits:
            splits = [question]

        all_unique_cands: Dict[str, Dict[str, Any]] = {}
        split_cand_map = {q: [] for q in set(splits)}

        for q in set(splits):
            cands = self._search(q, max(k, int(os.getenv("SOEP_RAG_RERANK_CANDIDATES", "24"))), filters)
            for cand in cands:
                item_id = cand["item_id"]
                if item_id not in all_unique_cands:
                    all_unique_cands[item_id] = cand
                split_cand_map[q].append(item_id)

        for q, ids in split_cand_map.items():
            pairs = []
            rerank_ids = []
            for item_id in ids:
                cand = all_unique_cands[item_id]
                doc_text = (
                    f"{cand.get('variable_name', '')} - {cand.get('label', '')}. "
                    f"{cand.get('theme', '')}. {cand.get('search_description') or cand.get('rich_description', '')}. "
                    f"{cand.get('available_years_text', '')}. {', '.join(cand.get('spatial_levels') or [])}"
                )
                pairs.append((q, doc_text))
                rerank_ids.append(item_id)
            if pairs:
                scores = self._get_reranker().predict(pairs)
                dense_scores = [float(all_unique_cands[item_id].get("score", 0.0)) for item_id in rerank_ids]
                rerank_scores = [float(s) for s in scores]
                lexical_scores = [
                    self._lexical_overlap_score(q, all_unique_cands[item_id]) for item_id in rerank_ids
                ]
                dense_norm = self._minmax(dense_scores)
                rerank_norm = self._minmax(rerank_scores)
                for i, item_id in enumerate(rerank_ids):
                    cand = all_unique_cands[item_id]
                    # Fuse normalized dense retrieval, reranker, and generic lexical
                    # overlap. The old max(cosine, cross) mixed incomparable scales;
                    # pure reranking later proved brittle on short structured INKAR
                    # metadata. This keeps all components on [0, 1] and lets exact
                    # aliased metadata terms rescue cases where the reranker is flat.
                    cand.setdefault("retrieval_score", cand.get("score", 0.0))
                    cand["rerank_score"] = max(cand.get("rerank_score", float("-inf")), rerank_scores[i])
                    cand["dense_norm_score"] = max(cand.get("dense_norm_score", 0.0), dense_norm[i])
                    cand["rerank_norm_score"] = max(cand.get("rerank_norm_score", 0.0), rerank_norm[i])
                    cand["lexical_score"] = max(cand.get("lexical_score", 0.0), lexical_scores[i])
                    fused = 0.35 * dense_norm[i] + 0.50 * rerank_norm[i] + 0.15 * lexical_scores[i]
                    cand["fused_score"] = max(cand.get("fused_score", float("-inf")), fused)
                    # Dataset-authority + exact-code prior (max across split-queries).
                    delta = self._authority_delta(q, cand)
                    cand["authority_delta"] = max(cand.get("authority_delta", float("-inf")), delta)
                    cand["score"] = cand["fused_score"] + cand["authority_delta"]

        recommended: List[Dict[str, Any]] = []
        seen_final = set()
        for q in split_cand_map:
            split_cand_map[q].sort(key=lambda item_id: all_unique_cands[item_id].get("score", -999.0), reverse=True)

        idx = 0
        max_candidates_per_split = max((len(lst) for lst in split_cand_map.values()), default=0)
        while len(recommended) < k and idx < max_candidates_per_split:
            added_in_round = False
            for q in set(splits):
                lst = split_cand_map[q]
                if idx < len(lst):
                    item_id = lst[idx]
                    dedup_key = self._dedup_key(all_unique_cands[item_id])
                    if dedup_key not in seen_final:
                        seen_final.add(dedup_key)
                        recommended.append(all_unique_cands[item_id])
                        added_in_round = True
                        if len(recommended) == k:
                            break
            idx += 1

        recommended.sort(key=lambda x: x.get("score", -999), reverse=True)

        # Annotate each surviving row with the OTHER datasets (among the retrieved
        # candidates) that shared its dedup key, so a collapse never hides the fact
        # that the same variable also occurs in, e.g., the Core dataset one wants.
        key_datasets: Dict[Any, set] = {}
        for cand in all_unique_cands.values():
            key_datasets.setdefault(self._dedup_key(cand), set()).add(cand.get("dataset"))
        for cand in recommended:
            others = sorted(
                d for d in key_datasets.get(self._dedup_key(cand), set())
                if d and d != cand.get("dataset")
            )
            if others:
                cand["also_in_datasets"] = others

        datasets_found = sorted(
            {
                row.get("dataset_label") or row.get("dataset")
                for row in recommended
                if row.get("dataset_label") or row.get("dataset")
            }
        )
        answer_text = self._render_llm_answer(question, splits, recommended, datasets_found)
        response_mode = "local-llm+rtrvr" if answer_text else "retrieval-only"
        if not answer_text:
            answer_text = self._fallback_answer(splits, recommended, datasets_found)

        return {
            "answer": answer_text,
            "embedding_model": f"{self.model_name} + {self._reranker_name}",
            "llm_model": self._llm_model_name if response_mode != "retrieval-only" else "disabled",
            "index_type": "faiss" if self._faiss_index is not None else "numpy",
            "response_mode": response_mode,
            "recommended_variables": recommended,
            "metadata_source": str(self.metadata_path),
            "inkar_metadata_source": str(self.inkar_metadata_path) if self.inkar_metadata_path else None,
            "filters_applied": filters,
        }
