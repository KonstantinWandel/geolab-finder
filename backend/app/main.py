from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import os
from app.services.search import SearchService
from app.services.data_fetch_agent import DataFetchAgentService
from app.services.execution_service import ExecutionService
from app.services.harmonizer import HarmonizerService
from app.services.soep_aggregator import SOEPAggregatorService
from app.services.soep_search import SOEPSearchService
from app.services.soep_rag_advisor import SOEPRagAdvisorService

app = FastAPI(title="Destatis Local RAG", version="1.0.0")

ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DESTATIS_RAG_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Services (Singletons for now)
DATA_ROOT = os.getenv("DESTATIS_RAG_DATA_ROOT", "/app/data")
# The SOEP-only and INKAR-only deployments don't ship the Destatis table index, so its
# bulky e5-large model + FAISS load is gated off there via GEOLAB_ENABLE_DESTATIS=0.
ENABLE_DESTATIS = os.getenv("GEOLAB_ENABLE_DESTATIS", "1").strip().lower() not in {"0", "false", "no"}
search_service = (
    SearchService(
        index_path=os.getenv("DESTATIS_RAG_INDEX_PATH", f"{DATA_ROOT}/destatis_advanced.faiss"),
        mapping_path=os.getenv("DESTATIS_RAG_MAPPING_PATH", f"{DATA_ROOT}/destatis_full_metadata.json"),
        metadata_dir=os.getenv("DESTATIS_RAG_METADATA_DIR", f"{DATA_ROOT}/genesis_metadata"),
        api_data_path=os.getenv("DESTATIS_RAG_API_DATA_PATH", f"{DATA_ROOT}/curated_apis.json"),
    )
    if ENABLE_DESTATIS
    else None
)
fetch_agent = DataFetchAgentService()
execution_service = ExecutionService()
harmonizer = HarmonizerService()
soep_aggregator = SOEPAggregatorService()
soep_search_service = SOEPSearchService()
soep_rag_advisor = SOEPRagAdvisorService()

class SearchRequest(BaseModel):
    query: str
    k: int = 5

class SearchResult(BaseModel):
    code: str
    title: str
    score: float

class AnalyzeRequest(BaseModel):
    table_code: str
    user_query: str

class AnalyzeResponse(BaseModel):
    sql_or_code: str
    result: Optional[List[dict]] = None
    explanation: str
    type: str = "table" # 'table' or 'api'

@app.on_event("startup")
async def startup_event():
    print("Loading models...")
    if search_service is not None:
        search_service.load_resources()
    # Warm the metadata advisor (bi-encoder + cached embeddings + reranker) so the
    # first user query isn't slow.
    try:
        soep_rag_advisor.load()
        soep_rag_advisor._get_reranker()
        print(f"Advisor ready (mode={soep_rag_advisor.app_mode}, rows={len(soep_rag_advisor._rows)}).")
    except Exception as exc:  # pragma: no cover
        print(f"Advisor warmup failed: {exc}")
    print("Models loaded.")

@app.post("/api/search", response_model=List[SearchResult])
async def search_tables(req: SearchRequest):
    if search_service is None:
        return []
    return search_service.search(req.query, req.k)

@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_data(req: AnalyzeRequest):
    if search_service is None:
        return AnalyzeResponse(
            sql_or_code="",
            explanation="Destatis table search is disabled in this deployment.",
            type="table",
        )
    # Determine context
    item_type = "table"
    if req.table_code.startswith("API-"):
        item_type = "api"
        context = search_service.get_api_context(req.table_code)
    else:
        context = search_service.get_metadata_context(req.table_code)

    # Generate Download Code
    code = await fetch_agent.generate_download_code(req.user_query, context, item_type)
    
    return AnalyzeResponse(
        sql_or_code=code,
        result=[], 
        explanation=f"Generated {item_type.upper()} download script. Ready for harmonization.",
        type=item_type
    )

class ExecuteRequest(BaseModel):
    code: str

class HarmonizeRequest(BaseModel):
    raw_data: List[dict]
    source_type: str

@app.post("/api/execute")
async def execute_code(req: ExecuteRequest):
    return {"error": "Execution endpoint is disabled for security reasons."}
    # result = execution_service.execute_script(req.code)
    # return result

@app.post("/api/harmonize")
async def harmonize_data(req: HarmonizeRequest):
    cdm_data = harmonizer.harmonize(req.raw_data, req.source_type)
    return {"cdm": cdm_data}

class SOEPRequest(BaseModel):
    variable: str
    year: int


class SOEPAdviceRequest(BaseModel):
    question: str
    top_k: int = 12
    dataset_scope: str = "all"
    dataset_label: Optional[str] = None
    nuts_level: Optional[str] = None
    spatial_level: Optional[str] = None
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    theme: Optional[str] = None
    regional_only: bool = False

@app.post("/api/soep")
async def aggregate_soep(req: SOEPRequest):
    return {"error": "SOEP raw data endpoint is disabled for security reasons."}
    # data = soep_aggregator.aggregate_variable(req.variable, req.year)
    # return {"data": data}

@app.get("/api/search_soep")
async def search_soep(q: str):
    return soep_search_service.search(q)


@app.post("/api/soep/advice")
async def soep_advice(req: SOEPAdviceRequest):
    soep_rag_advisor.load()
    filters = {
        "dataset_scope": req.dataset_scope,
        "dataset_label": req.dataset_label,
        "nuts_level": req.nuts_level,
        "spatial_level": req.spatial_level,
        "year_start": req.year_start,
        "year_end": req.year_end,
        "theme": req.theme,
        "regional_only": req.regional_only,
    }
    return soep_rag_advisor.answer_research_question(req.question, req.top_k, filters)


@app.get("/api/soep/filter-options")
async def soep_filter_options():
    return soep_rag_advisor.get_filter_options()

@app.get("/health")
def health_check():
    return {"status": "ok"}
