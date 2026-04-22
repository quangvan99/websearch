# websearch

Tool hỏi đáp qua SearXNG local + LLM (claudible.io), đóng gói bằng **docker compose** (2 service: `searxng` + `api`).

Pipeline: `SearXNG → fetch trang (trafilatura) → LLM`. Việc fetch full text giúp ngữ cảnh phong phú hơn hẳn so với snippet ~1 dòng mà SearXNG trả về.

## Yêu cầu

- Docker + Docker Compose v2

## Sử dụng

### 1. Khởi động (`./start.sh`)

Build image và start cả 2 container. Code host được mount vào `/app` nên sửa là hot-reload.

```bash
./start.sh
```

**Output:**
```
 Image websearch-api Built
 Container searxng Started
 Container websearch-api Started
[wait] searxng http://localhost:8888 ...
[ok] searxng ready
[wait] api http://localhost:8899 ...
[ok] api ready: http://localhost:8899
```

### 2. Hỏi qua CLI (`./run.sh`)

Chạy `websearch.py` **bên trong container api** (qua `docker compose exec`). Mặc định: `"giá vàng SJC hôm nay"`.

```bash
./run.sh                                 # câu mặc định (fetch ON + LLM)
./run.sh "giá xăng RON 95 hôm nay"       # câu tuỳ ý
./run.sh --raw "..."                     # chỉ kết quả search, bỏ qua LLM
./run.sh --no-fetch "..."                # tắt trafilatura (chỉ snippet)
./run.sh --max-chars 8000 "..."          # cắt mỗi trang N ký tự (0 = không cắt)
./run.sh --raw --no-fetch "..."          # snippet thô nhất
```

**Các flag:**

| Flag | Default | Mô tả |
|---|---|---|
| `--raw` | off | Không gọi LLM, in thẳng kết quả search |
| `--fetch` / `--no-fetch` | `--fetch` (ON) | Bật/tắt lấy full text trang bằng trafilatura |
| `--max-chars N` | `4000` | Cắt mỗi trang N ký tự trước khi đưa vào context/LLM. `0` = giữ nguyên |

**Input:** câu hỏi bằng tiếng Việt (hoặc tiếng Anh).

**Output:** câu trả lời kèm mục `## Nguồn`.

```
[1] search: giá vàng SJC hôm nay
    got 6 results
[1b] fetching pages (max_chars=4000)...
    fetched 4/6 pages
[2] calling claudible.io...

===== ANSWER =====

- Vàng SJC 1L: mua 168.100.000đ/lượng, bán 170.600.000đ/lượng [2]
- Vàng SJC 5 chỉ: mua 168.100.000đ/lượng, bán 170.620.000đ/lượng [2]

## Nguồn
[2] Giá Vàng Online - SJC — https://sjc.com.vn/gia-vang-online
```

### 3. HTTP API

API chạy ở `http://localhost:8899`.

#### `GET /health`

```bash
curl http://localhost:8899/health
```

**Output:**
```json
{"status":"ok"}
```

#### `POST /`

Body JSON:

| Field | Type | Default | Mô tả |
|---|---|---|---|
| `question` | string | *required* | Câu hỏi |
| `raw` | bool | `false` | `true` → chỉ trả hits từ SearXNG (không gọi LLM) |
| `fetch` | bool | `true` | Lấy full text trang bằng trafilatura. Áp dụng cho cả `raw=true` (hits sẽ có field `full_text`) và chế độ LLM |
| `max_chars` | int | `4000` | Cắt mỗi trang N ký tự. `0` = giữ nguyên |

**Ví dụ 1 — có LLM trả lời:**

```bash
curl -X POST http://localhost:8899/ \
  -H 'Content-Type: application/json' \
  -d '{"question":"giá vàng SJC hôm nay"}'
```

**Output:**
```json
{
  "question": "giá vàng SJC hôm nay",
  "answer": "Theo SJC, vàng miếng SJC 1L: mua 168.100.000đ, bán 170.600.000đ/lượng [3]...\n\n## Nguồn\n[3] SJC — https://sjc.com.vn/gia-vang-online",
  "hits": null
}
```

**Ví dụ 2 — raw hits kèm full text (không qua LLM):**

```bash
curl -X POST http://localhost:8899/ \
  -H 'Content-Type: application/json' \
  -d '{"question":"giá vàng SJC hôm nay","raw":true,"fetch":true,"max_chars":3000}'
```

**Output:**
```json
{
  "question": "giá vàng SJC hôm nay",
  "answer": null,
  "hits": [
    {
      "title": "SJC: Trang Chủ ...",
      "url": "https://sjc.com.vn/",
      "content": "snippet ngắn...",
      "full_text": "Nội dung đầy đủ đã được trafilatura trích xuất (đã cắt 3000 ký tự)..."
    }
  ]
}
```

Site fetch fail (timeout/chặn bot/JS-only) → `full_text` = `null`, LLM/raw sẽ fallback về `content` snippet.

**Ví dụ 3 — tắt fetch, chỉ snippet:**

```bash
curl -X POST http://localhost:8899/ \
  -H 'Content-Type: application/json' \
  -d '{"question":"giá vàng SJC hôm nay","raw":true,"fetch":false}'
```

Question rỗng → `HTTP 400`.

### 4. Log (`./log.sh`)

Xem log qua `docker compose logs`.

```bash
./log.sh                 # tail 200 dòng, cả 2 service
./log.sh -f              # follow live
./log.sh api             # chỉ service api
./log.sh -f searxng      # follow service searxng
```

### 5. Tắt (`./stop.sh`)

```bash
./stop.sh
```

**Output:**
```
 Container websearch-api Removed
 Container searxng Removed
 Network websearch_default Removed
```

## Biến môi trường

| Var | Default | Ghi chú |
|---|---|---|
| `SEARXNG_PORT` | `8888` | Port SearXNG trên host |
| `API_PORT` | `8899` | Port FastAPI server trên host |
| `CLAUDIBLE_KEY` | hard-coded trong `websearch.py` | API key claudible.io |
| `CLAUDIBLE_MODEL` | `gpt-5.4-mini` | Model dùng để trả lời |
| `WEBSEARCH_FETCH` | `1` | `0` để mặc định tắt trafilatura |
| `WEBSEARCH_MAX_CHARS` | `4000` | Cắt mỗi trang N ký tự |
| `WEBSEARCH_FETCH_TIMEOUT` | `8` | Timeout (giây) cho mỗi URL fetch |
| `SEARCH_CACHE_TTL` | `600` | TTL (giây) cache kết quả SearXNG |
| `FETCH_CACHE_TTL` | `3600` | TTL (giây) cache HTML đã extract theo URL |

Trong container, `SEARXNG_URL` được compose set cứng thành `http://searxng:8080` (DNS nội bộ).
