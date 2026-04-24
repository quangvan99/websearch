from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from websearch import search

app = FastAPI(title="vecura-web-search", version="2.0.0")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=10)
    engines: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    time_range: str | None = None
    language: str | None = None
    prefer_official: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)


class SearchHitDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    snippet: str = ""
    content: str = ""
    score: float | None = None
    published_date: str | None = None
    engine: str | None = None
    category: str | None = None
    domain: str | None = None
    is_preferred_source: bool = False
    is_official_candidate: bool = False


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    provider: str = "searxng"
    total: int = 0
    latency_ms: int = 0
    prefer_official: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    hits: list[SearchHitDTO] = Field(default_factory=list)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def do_search(req: SearchRequest) -> SearchResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is empty")

    payload = await search(
        question,
        limit=req.limit,
        engines=req.engines,
        categories=req.categories,
        time_range=req.time_range,
        language=req.language,
        prefer_official=req.prefer_official,
        allowed_domains=req.allowed_domains,
        preferred_domains=req.preferred_domains,
    )
    return SearchResponse.model_validate(payload)
