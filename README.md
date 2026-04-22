# websearch

Tool hỏi đáp qua SearXNG local + LLM (claudible.io), đóng gói bằng **docker compose** (2 service: `searxng` + `api`).

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
./run.sh                              # câu mặc định
./run.sh "giá xăng RON 95 hôm nay"   # câu tuỳ ý
```

**Input:** câu hỏi bằng tiếng Việt (hoặc tiếng Anh).

**Output:** câu trả lời kèm mục `## Nguồn`.

```
[1] search: giá vàng SJC hôm nay
    got 6 results
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

**Ví dụ 2 — raw hits (không qua LLM):**

```bash
curl -X POST http://localhost:8899/ \
  -H 'Content-Type: application/json' \
  -d '{"question":"giá vàng SJC hôm nay","raw":true}'
```

**Output:**
```json
{
  "question": "giá vàng SJC hôm nay",
  "answer": null,
  "hits": [
    {"title": "SJC: Trang Chủ ...", "url": "https://sjc.com.vn/", "content": "..."}
  ]
}
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

Trong container, `SEARXNG_URL` được compose set cứng thành `http://searxng:8080` (DNS nội bộ).
