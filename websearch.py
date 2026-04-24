from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx


class Config:
    SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888").rstrip("/")
    SEARCH_TIMEOUT_S = float(os.environ.get("WEBSEARCH_SEARCH_TIMEOUT_S", "8"))
    HTTP_TIMEOUT_S = float(os.environ.get("WEBSEARCH_HTTP_TIMEOUT_S", "12"))
    SEARCH_CACHE_TTL_S = float(os.environ.get("WEBSEARCH_CACHE_TTL_S", "180"))
    DEFAULT_LIMIT = int(os.environ.get("WEBSEARCH_DEFAULT_LIMIT", "8"))
    MAX_LIMIT = int(os.environ.get("WEBSEARCH_MAX_LIMIT", "10"))
    DEFAULT_LANGUAGE = os.environ.get("WEBSEARCH_DEFAULT_LANGUAGE", "all").strip() or "all"
    USER_AGENT = os.environ.get("WEBSEARCH_USER_AGENT", "vecura-web-search/2.0")
    DEFAULT_ENGINES = tuple(
        item.strip()
        for item in os.environ.get("WEBSEARCH_DEFAULT_ENGINES", "startpage,bing").split(",")
        if item.strip()
    )
    FALLBACK_ENGINES = tuple(
        item.strip()
        for item in os.environ.get("WEBSEARCH_FALLBACK_ENGINES", "bing,wikipedia").split(",")
        if item.strip()
    )


_http = httpx.AsyncClient(
    headers={"User-Agent": Config.USER_AGENT, "Accept": "application/json"},
    timeout=Config.HTTP_TIMEOUT_S,
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
)
_cache_lock = asyncio.Lock()
_search_cache: dict[tuple[str, int, str, str, str, str, str, str, str], tuple[float, dict[str, Any]]] = {}
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "by",
    "docs",
    "for",
    "from",
    "how",
    "in",
    "is",
    "latest",
    "new",
    "of",
    "official",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "with",
}


async def search(
    question: str,
    *,
    limit: int = Config.DEFAULT_LIMIT,
    engines: list[str] | None = None,
    categories: list[str] | None = None,
    time_range: str | None = None,
    language: str | None = None,
    prefer_official: bool = False,
    allowed_domains: list[str] | None = None,
    preferred_domains: list[str] | None = None,
) -> dict[str, Any]:
    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise ValueError("question is empty")

    normalized_limit = max(1, min(int(limit or Config.DEFAULT_LIMIT), Config.MAX_LIMIT))
    normalized_engines = _clean_list(engines) or list(Config.DEFAULT_ENGINES)
    normalized_categories = _clean_list(categories)
    normalized_time_range = _normalize_time_range(time_range)
    normalized_language = _normalize_language(language)
    normalized_allowed_domains = _clean_domains(allowed_domains)
    normalized_preferred_domains = _clean_domains([*normalized_allowed_domains, *_clean_domains(preferred_domains)])
    cache_key = (
        normalized_question.lower(),
        normalized_limit,
        ",".join(normalized_engines),
        ",".join(normalized_categories),
        normalized_time_range or "",
        normalized_language or "",
        ",".join(normalized_allowed_domains),
        ",".join(normalized_preferred_domains),
        "official" if prefer_official else "",
    )

    now = time.monotonic()
    async with _cache_lock:
        cached = _search_cache.get(cache_key)
        if cached and now - cached[0] < Config.SEARCH_CACHE_TTL_S:
            return dict(cached[1])

    t0 = time.monotonic()
    payload = await _run_search_strategy(
        normalized_question,
        engines=normalized_engines,
        categories=normalized_categories,
        time_range=normalized_time_range,
        language=normalized_language,
        preferred_domains=normalized_preferred_domains,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    raw_results = list(payload.get("results") or []) if isinstance(payload, dict) else []
    hits = [_normalize_hit(item) for item in raw_results]
    hits = [hit for hit in hits if hit["url"]]
    hits = _filter_and_rank_hits(
        hits,
        question=normalized_question,
        allowed_domains=normalized_allowed_domains,
        preferred_domains=normalized_preferred_domains,
        prefer_official=prefer_official,
    )[:normalized_limit]
    result = {
        "question": normalized_question,
        "provider": "searxng",
        "total": int(len(hits))
        if isinstance(payload, dict)
        else len(hits),
        "latency_ms": latency_ms,
        "prefer_official": bool(prefer_official),
        "allowed_domains": normalized_allowed_domains,
        "preferred_domains": normalized_preferred_domains,
        "hits": hits,
    }

    async with _cache_lock:
        _search_cache[cache_key] = (time.monotonic(), dict(result))
    return result


async def _run_search_strategy(
    question: str,
    *,
    engines: list[str],
    categories: list[str],
    time_range: str | None,
    language: str,
    preferred_domains: list[str],
) -> dict[str, Any]:
    queries = [question]
    for domain in preferred_domains[:2]:
        queries.append(f"{question} site:{domain}")

    engine_variants: list[list[str]] = []
    primary_engines = _clean_list(engines)
    if primary_engines:
        engine_variants.append(primary_engines)

    fallback_engines = _clean_list(list(Config.FALLBACK_ENGINES))
    if fallback_engines and fallback_engines != primary_engines:
        engine_variants.append(fallback_engines)

    if [] not in engine_variants:
        engine_variants.append([])

    merged_payload: dict[str, Any] = {"results": []}
    seen_urls: set[str] = set()

    for query_index, query_text in enumerate(queries):
        for engine_variant in engine_variants:
            payload = await _request_search(
                query_text,
                engines=engine_variant,
                categories=categories,
                time_range=time_range,
                language=language,
            )
            if not isinstance(payload, dict):
                continue

            raw_results = list(payload.get("results") or [])
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or item.get("link") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                merged_payload["results"].append(item)

            if query_index == 0 and raw_results:
                break
            if query_index > 0 and any(
                _domain_matches(str(item.get("url") or item.get("link") or ""), domain)
                for item in raw_results
                for domain in preferred_domains
            ):
                break

    return merged_payload


async def _request_search(
    question: str,
    *,
    engines: list[str],
    categories: list[str],
    time_range: str | None,
    language: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {"q": question, "format": "json"}
    if engines:
        params["engines"] = ",".join(engines)
    if categories:
        params["categories"] = ",".join(categories)
    if time_range:
        params["time_range"] = time_range
    if language and language != "all":
        params["language"] = language

    try:
        response = await _http.get(
            f"{Config.SEARXNG_URL}/search",
            params=params,
            timeout=Config.SEARCH_TIMEOUT_S,
        )
        response.raise_for_status()
        return response.json() if response.content else {}
    except httpx.HTTPError:
        return {}


def _normalize_hit(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "title": "",
            "url": "",
            "snippet": "",
            "content": "",
            "score": None,
            "published_date": None,
            "engine": None,
            "category": None,
            "domain": None,
            "is_preferred_source": False,
            "is_official_candidate": False,
        }

    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or item.get("link") or "").strip()
    snippet = str(item.get("content") or item.get("snippet") or "").strip()
    score = item.get("score")
    published_date = str(
        item.get("publishedDate")
        or item.get("published_date")
        or item.get("published")
        or ""
    ).strip()
    engine = str(item.get("engine") or "").strip() or None
    category = str(item.get("category") or "").strip() or None
    domain = _extract_domain(url)
    return {
        "title": title or url,
        "url": url,
        "snippet": snippet,
        "content": snippet,
        "score": float(score) if isinstance(score, (int, float)) else None,
        "published_date": published_date or None,
        "engine": engine,
        "category": category,
        "domain": domain or None,
        "is_preferred_source": False,
        "is_official_candidate": False,
    }


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(value).strip() for value in list(values or []) if str(value).strip()]


def _clean_domains(values: list[str] | None) -> list[str]:
    domains: list[str] = []
    for value in list(values or []):
        domain = _extract_domain(str(value or ""))
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _normalize_time_range(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized == "all":
        return None
    aliases = {
        "d": "day",
        "day": "day",
        "w": "week",
        "week": "week",
        "m": "month",
        "month": "month",
        "y": "year",
        "year": "year",
    }
    return aliases.get(normalized)


def _normalize_language(value: str | None) -> str:
    normalized = str(value or Config.DEFAULT_LANGUAGE).strip().lower()
    if normalized in {"", "auto"}:
        return Config.DEFAULT_LANGUAGE
    if normalized in {"vi", "vi-vn", "vietnamese"}:
        return "vi"
    if normalized in {"en", "en-us", "en-gb", "english"}:
        return "en"
    if normalized in {"all", "any"}:
        return "all"
    return normalized


def _filter_and_rank_hits(
    hits: list[dict[str, Any]],
    *,
    question: str,
    allowed_domains: list[str],
    preferred_domains: list[str],
    prefer_official: bool,
) -> list[dict[str, Any]]:
    query_terms = _query_terms(question)
    candidates = list(hits)
    if allowed_domains:
        filtered = [
            hit
            for hit in candidates
            if any(_domain_matches(hit.get("domain") or hit.get("url") or "", domain) for domain in allowed_domains)
        ]
        if filtered:
            candidates = filtered

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, hit in enumerate(candidates):
        score = float(hit.get("score") or 0.0) if isinstance(hit.get("score"), (int, float)) else 0.0
        domain = _extract_domain(str(hit.get("domain") or hit.get("url") or ""))
        lexical_score = _lexical_score(hit, query_terms)
        is_preferred_source = bool(
            preferred_domains
            and any(_domain_matches(domain, preferred) for preferred in preferred_domains)
        )
        is_official_candidate = bool(
            is_preferred_source or (prefer_official and _looks_official(domain, hit))
        )

        quality = lexical_score + score
        if is_preferred_source:
            quality += 1_000.0
        if is_official_candidate:
            quality += 100.0

        scored.append(
            (
                quality,
                index,
                {
                    **hit,
                    "domain": domain or None,
                    "is_preferred_source": is_preferred_source,
                    "is_official_candidate": is_official_candidate,
                },
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _query_terms(question: str) -> list[str]:
    terms: list[str] = []
    for token in _TOKEN_RE.findall(str(question or "").lower()):
        if token in _STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def _lexical_score(hit: dict[str, Any], query_terms: list[str]) -> float:
    if not query_terms:
        return 0.0

    title = str(hit.get("title") or "").lower()
    snippet = str(hit.get("snippet") or hit.get("content") or "").lower()
    url = str(hit.get("url") or "").lower()
    text = " ".join([title, snippet, url])
    text_terms = set(_TOKEN_RE.findall(text))

    overlap = sum(1 for term in query_terms if term in text_terms)
    score = float(overlap * 25)
    if overlap == len(query_terms):
        score += 15.0
    if title:
        title_terms = set(_TOKEN_RE.findall(title))
        title_overlap = sum(1 for term in query_terms if term in title_terms)
        score += float(title_overlap * 20)
    if overlap == 0:
        score -= 25.0
    return score


def _extract_domain(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").strip().lower()
    return host[4:] if host.startswith("www.") else host


def _domain_matches(value: str, expected: str) -> bool:
    host = _extract_domain(value)
    domain = _extract_domain(expected)
    if not host or not domain:
        return False
    return host == domain or host.endswith(f".{domain}")


def _looks_official(domain: str, hit: dict[str, Any]) -> bool:
    if domain.endswith((".gov", ".edu", ".int")):
        return True
    if domain in {
        "nodejs.org",
        "python.org",
        "docs.python.org",
        "postgresql.org",
        "kubernetes.io",
        "redis.io",
        "opensearch.org",
        "kernel.org",
        "docs.astral.sh",
        "pip.pypa.io",
        "aws.amazon.com",
        "nvidia.com",
        "sec.gov",
        "faa.gov",
        "cisa.gov",
        "bls.gov",
        "bea.gov",
        "esa.int",
        "nasa.gov",
        "who.int",
        "cdc.gov",
        "nist.gov",
        "easa.europa.eu",
        "europa.eu",
        "eur-lex.europa.eu",
        "travel.state.gov",
        "cbp.gov",
        "dhs.gov",
        "collegeboard.org",
        "apstudents.collegeboard.org",
        "satsuite.collegeboard.org",
        "firecrawl.dev",
        "tavily.com",
    }:
        return True

    text = " ".join(
        str(value or "")
        for value in (
            hit.get("title"),
            hit.get("snippet"),
            hit.get("content"),
        )
    ).lower()
    return any(
        token in text
        for token in (
            "official",
            "documentation",
            "release notes",
            "what's new",
            "whats new",
            "announcement",
            "fact sheet",
        )
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Query the SearXNG-backed Vecura web search plugin.")
    parser.add_argument("question", nargs="+", help="Search question")
    parser.add_argument("--limit", type=int, default=Config.DEFAULT_LIMIT)
    parser.add_argument("--time-range", default=None)
    parser.add_argument("--language", default=None)
    parser.add_argument("--engines", nargs="*", default=None)
    parser.add_argument("--categories", nargs="*", default=None)
    args = parser.parse_args()

    payload = await search(
        " ".join(args.question),
        limit=args.limit,
        time_range=args.time_range,
        language=args.language,
        engines=args.engines,
        categories=args.categories,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
