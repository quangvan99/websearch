# Vecura Web Search Plugin

`web_search` is the discovery-only search plugin used by `vecura-agents-core`.
It does one thing: query SearXNG and return normalized hits fast.

What it does:
- Provider: `searxng`
- Output: `title`, `url`, `snippet`, `published_date`, `score`, `latency_ms`
- Endpoint: `POST /search`

What it does not do:
- No LLM answer generation
- No page fetching
- No content extraction

That split is intentional: full-page fetching belongs to `web_fetch` in core.

## Run

```bash
./start.sh
./log.sh -f
```

Services:
- SearXNG: `http://localhost:8888`
- API: `http://localhost:18899`

## Query

```bash
./run.sh "latest PostgreSQL 17 release notes"
```

Or call the API directly:

```bash
curl -s http://localhost:18899/search \
  -H "Content-Type: application/json" \
  -d '{
    "question": "latest PostgreSQL 17 release notes official",
    "limit": 5,
    "language": "en"
  }' | jq .
```

Example response:

```json
{
  "question": "latest PostgreSQL 17 release notes official",
  "provider": "searxng",
  "total": 5,
  "latency_ms": 412,
  "hits": [
    {
      "title": "PostgreSQL: Documentation: 17: Release 17",
      "url": "https://www.postgresql.org/docs/17/release-17.html",
      "snippet": "Release notes for PostgreSQL 17...",
      "content": "Release notes for PostgreSQL 17...",
      "score": 12.4,
      "published_date": null,
      "engine": "google",
      "category": "general"
    }
  ]
}
```

## Request Shape

```json
{
  "question": "required string",
  "limit": 8,
  "engines": ["optional", "engine", "filters"],
  "categories": ["optional", "category", "filters"],
  "time_range": "day | week | month | year",
  "language": "vi | en | all | ..."
}
```

## Env

- `SEARXNG_URL`
- `WEBSEARCH_SEARCH_TIMEOUT_S`
- `WEBSEARCH_HTTP_TIMEOUT_S`
- `WEBSEARCH_CACHE_TTL_S`
- `WEBSEARCH_DEFAULT_LANGUAGE`
