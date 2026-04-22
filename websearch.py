"""
Web search qua SearXNG local + trả lời bằng claudible.io.

Usage:
    ./start.sh                   # chạy 1 lần để up container
    python3 websearch.py "<câu hỏi>"
    e.g. python3 websearch.py "giá vàng SJC hôm nay"
         python3 websearch.py "giá xăng RON 95 hôm nay ở Việt Nam"
"""

import os
import sys
import httpx
from openai import OpenAI

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888")
CLAUDIBLE_BASE_URL = "https://claudible.io/v1"
CLAUDIBLE_KEY = os.environ.get(
    "CLAUDIBLE_KEY",
    "sk-6341fd2e6ac2e832574d06190f318f607f5cfe51011258b77cdc83e2aa144c87",
)
CLAUDIBLE_MODEL = os.environ.get("CLAUDIBLE_MODEL", "gpt-5.4-mini")

_http = httpx.Client(
    headers={"User-Agent": "curl/8.5.0", "Accept": "*/*"},
    timeout=120.0,
)
client = OpenAI(
    base_url=CLAUDIBLE_BASE_URL,
    api_key=CLAUDIBLE_KEY,
    http_client=_http,
)


def search(q: str, n: int = 6) -> list[dict]:
    r = httpx.get(
        f"{SEARXNG_URL}/search",
        params={"q": q, "format": "json", "language": "vi"},
        headers={"User-Agent": "curl/8.5.0"},
        timeout=30.0,
    )
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[:n]


def format_context(hits: list[dict]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        title = h.get("title", "")
        url = h.get("url", "")
        snippet = (h.get("content") or "").strip().replace("\n", " ")
        lines.append(f"[{i}] {title}\n    URL: {url}\n    {snippet}")
    return "\n\n".join(lines)


def ask(question: str) -> str:
    print(f"[1] search: {question}", file=sys.stderr)
    hits = search(question)
    if not hits:
        return "Không tìm thấy kết quả search."
    print(f"    got {len(hits)} results", file=sys.stderr)

    ctx = format_context(hits)
    sources_block = "\n".join(
        f"[{i}] {h.get('title','')} - {h.get('url','')}"
        for i, h in enumerate(hits, 1)
    )
    system = (
        "Bạn trả lời dựa vào KẾT QUẢ SEARCH dưới đây. "
        "Trích nguồn bằng [n] tương ứng trong câu trả lời. "
        "CUỐI câu trả lời BẮT BUỘC in mục '## Nguồn' liệt kê đầy đủ "
        "các [n] đã dùng kèm title và URL đầy đủ (https://...). "
        "Nếu dữ liệu không đủ/mâu thuẫn, nói rõ.\n\n"
        f"=== KẾT QUẢ SEARCH ===\n{ctx}\n=== END ==="
    )

    print("[2] calling claudible.io...", file=sys.stderr)
    resp = client.chat.completions.create(
        model=CLAUDIBLE_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        max_tokens=4096,
    )
    return resp.choices[0].message.content


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    answer = ask(question)
    print("\n===== ANSWER =====\n")
    print(answer)


if __name__ == "__main__":
    main()
