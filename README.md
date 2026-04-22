# websearch

Tool hỏi đáp qua SearXNG local + LLM (claudible.io).

## Cài đặt

```bash
pip install httpx openai
```

Docker cần có sẵn để chạy SearXNG.

## Sử dụng

### 1. Khởi động SearXNG (chỉ cần chạy 1 lần)

```bash
./start.sh
```

**Output:**
```
[searxng] creating new container on :8888
[searxng] waiting for http://localhost:8888 ...
[searxng] ready: http://localhost:8888
```

### 2. Hỏi

Dùng `run.sh` (có câu mặc định `"giá vàng SJC hôm nay"`):

```bash
./run.sh
./run.sh "giá xăng RON 95 hôm nay"
```

Hoặc gọi trực tiếp:

```bash
python3 websearch.py "giá vàng SJC hôm nay"
```

**Input:** một câu hỏi bằng tiếng Việt (hoặc tiếng Anh).

**Output:** câu trả lời kèm mục `## Nguồn` liệt kê URL tham khảo.

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

### 3. Xem log SearXNG

```bash
./log.sh        # 200 dòng cuối
./log.sh -f     # follow live
```

### 4. Tắt SearXNG

```bash
./stop.sh
```

**Output:**
```
[searxng] stopping...
[searxng] removing...
[searxng] done
```

## Biến môi trường

| Var | Default | Ghi chú |
|---|---|---|
| `SEARXNG_URL` | `http://localhost:8888` | Endpoint SearXNG |
| `SEARXNG_PORT` | `8888` | Port khi chạy `start.sh` |
| `CLAUDIBLE_KEY` | hard-coded | API key claudible.io |
| `CLAUDIBLE_MODEL` | `gpt-5.4-mini` | Model dùng để trả lời |
