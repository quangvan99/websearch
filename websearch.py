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
import trafilatura
from openai import AsyncOpenAI

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888")
CLAUDIBLE_BASE_URL = "https://claudible.io/v1"
CLAUDIBLE_KEY = (
    os.environ.get("CLAUDIBLE_KEY")
    or "sk-6341fd2e6ac2e832574d06190f318f607f5cfe51011258b77cdc83e2aa144c87"
)
CLAUDIBLE_MODEL = os.environ.get("CLAUDIBLE_MODEL") or "gpt-5.4-mini"
SEARCH_CACHE_TTL = float(os.environ.get("SEARCH_CACHE_TTL", "600"))
FETCH_CACHE_TTL = float(os.environ.get("FETCH_CACHE_TTL", "3600"))
FETCH_TIMEOUT = float(os.environ.get("WEBSEARCH_FETCH_TIMEOUT", "8"))
FETCH_DEFAULT = os.environ.get("WEBSEARCH_FETCH", "1") not in ("0", "false", "False", "")
MAX_CHARS_DEFAULT = int(os.environ.get("WEBSEARCH_MAX_CHARS", "4000"))

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
_fetch_cache: dict[str, tuple[float, str | None]] = {}
_fetch_lock = asyncio.Lock()


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


async def fetch_page(url: str) -> str | None:
    now = time.monotonic()
    async with _fetch_lock:
        hit = _fetch_cache.get(url)
        if hit and now - hit[0] < FETCH_CACHE_TTL:
            return hit[1]
    text: str | None = None
    try:
        r = await _http.get(url, timeout=FETCH_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        text = trafilatura.extract(
            r.text,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
    except Exception as e:
        print(f"    fetch fail: {url} ({type(e).__name__})", file=sys.stderr)
        text = None
    async with _fetch_lock:
        _fetch_cache[url] = (time.monotonic(), text)
    return text


async def enrich_hits(hits: list[dict], max_chars: int) -> list[dict]:
    urls = [h.get("url", "") for h in hits]
    texts = await asyncio.gather(*(fetch_page(u) for u in urls if u))
    for h, t in zip(hits, texts):
        if t:
            h["full_text"] = t[:max_chars] if max_chars > 0 else t
        else:
            h["full_text"] = None
    return hits


def format_context(hits: list[dict]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        title = h.get("title", "")
        url = h.get("url", "")
        body = h.get("full_text") or (h.get("content") or "").strip().replace("\n", " ")
        lines.append(f"[{i}] {title}\n    URL: {url}\n    {body}")
    return "\n\n".join(lines)


async def ask(question: str, fetch: bool = FETCH_DEFAULT, max_chars: int = MAX_CHARS_DEFAULT) -> str:
    print(f"[1] search: {question}", file=sys.stderr)
    hits = await search(question)
    if not hits:
        return "Không tìm thấy kết quả search."
    print(f"    got {len(hits)} results", file=sys.stderr)

    if fetch:
        print(f"[1b] fetching pages (max_chars={max_chars})...", file=sys.stderr)
        await enrich_hits(hits, max_chars)
        ok = sum(1 for h in hits if h.get("full_text"))
        print(f"    fetched {ok}/{len(hits)} pages", file=sys.stderr)

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
    fetch = FETCH_DEFAULT
    max_chars = MAX_CHARS_DEFAULT
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--raw":
            raw = True
        elif a == "--fetch":
            fetch = True
        elif a == "--no-fetch":
            fetch = False
        elif a == "--max-chars":
            i += 1
            max_chars = int(args[i])
        elif a.startswith("--max-chars="):
            max_chars = int(a.split("=", 1)[1])
        else:
            rest.append(a)
        i += 1
    if not rest:
        print(__doc__)
        sys.exit(1)
    question = " ".join(rest)
    if raw:
        print(f"[1] search: {question}", file=sys.stderr)
        hits = await search(question)
        print(f"    got {len(hits)} results", file=sys.stderr)
        if fetch:
            print(f"[1b] fetching pages (max_chars={max_chars})...", file=sys.stderr)
            await enrich_hits(hits, max_chars)
            ok = sum(1 for h in hits if h.get("full_text"))
            print(f"    fetched {ok}/{len(hits)} pages", file=sys.stderr)
        print("\n===== RAW RESULTS =====\n")
        print(format_context(hits))
        return
    answer = await ask(question, fetch=fetch, max_chars=max_chars)
    print("\n===== ANSWER =====\n")
    print(answer)


if __name__ == "__main__":
    asyncio.run(_main())
