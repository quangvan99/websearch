"""
FastAPI server wrap websearch.ask() thành HTTP API.

Run:
    ./start.sh
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from websearch import ask, search, enrich_hits, FETCH_DEFAULT, MAX_CHARS_DEFAULT

app = FastAPI(title="websearch")


class SearchReq(BaseModel):
    question: str
    raw: bool = False  # True -> chỉ trả hits từ SearXNG, không gọi LLM
    fetch: bool = FETCH_DEFAULT  # True -> fetch full text bằng trafilatura
    max_chars: int = MAX_CHARS_DEFAULT  # cắt mỗi trang (0 = không cắt)


class SearchResp(BaseModel):
    question: str
    answer: str | None = None
    hits: list[dict] | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/", response_model=SearchResp)
async def do_search(req: SearchReq):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "question is empty")
    if req.raw:
        hits = await search(q)
        if req.fetch:
            await enrich_hits(hits, req.max_chars)
        return SearchResp(question=q, hits=hits)
    return SearchResp(question=q, answer=await ask(q, fetch=req.fetch, max_chars=req.max_chars))
