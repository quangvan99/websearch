"""
Web search qua SearXNG local + trả lời bằng claudible.io.

Usage:
    ./start.sh                   # chạy 1 lần để up container
    python3 websearch.py "<câu hỏi>"
    e.g. python3 websearch.py "giá vàng SJC hôm nay"
         python3 websearch.py "giá xăng RON 95 hôm nay ở Việt Nam"
"""

import asyncio
import os
import sys
import time
import httpx
from openai import AsyncOpenAI

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888")
CLAUDIBLE_BASE_URL = "https://claudible.io/v1"
CLAUDIBLE_KEY = (
    os.environ.get("CLAUDIBLE_KEY")
    or "sk-6341fd2e6ac2e832574d06190f318f607f5cfe51011258b77cdc83e2aa144c87"
)
CLAUDIBLE_MODEL = os.environ.get("CLAUDIBLE_MODEL") or "gpt-5.4-mini"
SEARCH_CACHE_TTL = float(os.environ.get("SEARCH_CACHE_TTL", "600"))

_http = httpx.AsyncClient(
    headers={"User-Agent": "curl/8.5.0", "Accept": "*/*"},
    timeout=300.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)
client = AsyncOpenAI(
    base_url=CLAUDIBLE_BASE_URL,
    api_key=CLAUDIBLE_KEY,
    http_client=_http,
)

_search_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}
_cache_lock = asyncio.Lock()


async def search(q: str, n: int = 6) -> list[dict]:
    key = (q.strip().lower(), n)
    now = time.monotonic()
    async with _cache_lock:
        hit = _search_cache.get(key)
        if hit and now - hit[0] < SEARCH_CACHE_TTL:
            return hit[1]

    r = await _http.get(
        f"{SEARXNG_URL}/search",
        params={"q": q, "format": "json", "language": "vi"},
        headers={"User-Agent": "curl/8.5.0"},
        timeout=30.0,
    )
    r.raise_for_status()
    results = (r.json().get("results") or [])[:n]

    async with _cache_lock:
        _search_cache[key] = (now, results)
    return results


def format_context(hits: list[dict]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        title = h.get("title", "")
        url = h.get("url", "")
        snippet = (h.get("content") or "").strip().replace("\n", " ")
        lines.append(f"[{i}] {title}\n    URL: {url}\n    {snippet}")
    return "\n\n".join(lines)


async def ask(question: str) -> str:
    print(f"[1] search: {question}", file=sys.stderr)
    hits = await search(question)
    if not hits:
        return "Không tìm thấy kết quả search."
    print(f"    got {len(hits)} results", file=sys.stderr)

    ctx = format_context(hits)
    system = (
        "Bạn trả lời dựa vào KẾT QUẢ SEARCH dưới đây. "
        "Trích nguồn bằng [n] tương ứng trong câu trả lời. "
        "CUỐI câu trả lời BẮT BUỘC in mục '## Nguồn' liệt kê đầy đủ "
        "các [n] đã dùng kèm title và URL đầy đủ (https://...). "
        "Nếu dữ liệu không đủ/mâu thuẫn, nói rõ.\n\n"
        f"=== KẾT QUẢ SEARCH ===\n{ctx}\n=== END ==="
    )

    print("[2] calling claudible.io...", file=sys.stderr)
    resp = await client.chat.completions.create(
        model=CLAUDIBLE_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        max_tokens=4096,
    )
    return resp.choices[0].message.content


async def _main():
    args = sys.argv[1:]
    raw = False
    if "--raw" in args:
        raw = True
        args = [a for a in args if a != "--raw"]
    if not args:
        print(__doc__)
        sys.exit(1)
    question = " ".join(args)
    if raw:
        print(f"[1] search: {question}", file=sys.stderr)
        hits = await search(question)
        print(f"    got {len(hits)} results", file=sys.stderr)
        print("\n===== RAW RESULTS =====\n")
        print(format_context(hits))
        return
    answer = await ask(question)
    print("\n===== ANSWER =====\n")
    print(answer)


if __name__ == "__main__":
    asyncio.run(_main())
