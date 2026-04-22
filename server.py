"""
FastAPI server wrap websearch.ask() thành HTTP API.

Run:
    ./start.sh
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from websearch import ask, search

app = FastAPI(title="websearch")


class SearchReq(BaseModel):
    question: str
    raw: bool = False  # True -> chỉ trả hits từ SearXNG, không gọi LLM


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
        return SearchResp(question=q, hits=await search(q))
    return SearchResp(question=q, answer=await ask(q))
