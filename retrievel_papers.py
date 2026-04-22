"""
Biomedical Literature Retrieval Pipeline
=========================================

Pipeline:
    User input (any language)
         → [0] LLM dịch sang English Boolean query
         → [1] Search song song 3 nguồn (EuropePMC, PubMed, OpenAlex)
         → [2] Deduplicate + merge metadata theo DOI > PMCID > PMID > title
         → [3] Fetch full-text JATS XML/JSON song song (qua IDs, KHÔNG qua link)
         → [4] Output dict {title: {metadata + fulltext + sections}}

SEARCH vs FETCH:
    - Search API = index metadata (không có full-text).
    - Fetch API  = retrieve-by-ID từ kho full-text structured.
    → Fetch dùng IDs (doi/pmid/pmcid) làm chuẩn chung, KHÔNG dùng `link` từ search.

Nguồn SEARCH (metadata + IDs):
    - EuropePMC search: superset của PubMed + PMC + preprint (30+ servers, ~1.1M preprint
      từ bioRxiv/medRxiv/ChemRxiv/arXiv... index từ 7/2018). Filter OA: `AND OPEN_ACCESS:y`,
      preprint: `AND SRC:PPR`. Không cần key.
    - PubMed (NCBI Entrez): esearch → efetch. 35M+ bài, CHỈ metadata+abstract.
      MeSH Automatic Term Mapping (ATM) expand query thông minh.
      Rate limit: 3 req/s (no key), 10 req/s (có api_key).
    - OpenAlex: 250M+ bài đa ngành. Abstract lưu inverted index → reconstruct client.
      Không full-text (chỉ có oa_url trỏ publisher). Cross-reference IDs tốt.
      Khuyên gửi `User-Agent: mailto:{email}` để vào polite pool.

Nguồn FETCH (full-text structured) — thứ tự ưu tiên:
    1. eLife API (DOI 10.7554/eLife.*): JSON structured, clean nhất.
       `https://api.elifesciences.org/articles/{id}`
    2. NCBI ID Converter: enrich pmcid từ DOI/PMID → tăng hit rate ~15-20%.
       `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/`
    3. EuropePMC fullTextXML (pmcid): `/{pmcid}/fullTextXML` → JATS XML.
    4. PMC efetch (pmcid, fallback): `efetch.fcgi?db=pmc&id={num}&rettype=xml`.
    5. bioRxiv/medRxiv API (DOI 10.1101/*): `api.biorxiv.org/details/{server}/{doi}/na/json`.
       Cover preprint mới <3 ngày, luôn trả version mới nhất; medRxiv non-CC license chỉ
       full-text qua nguồn này.
    6. CORE v3 (cần API key): fallback cuối cho OA ngoài PMC/preprint. Text thô, no sections.

Độ trễ index: bioRxiv post → EuropePMC ingest 1-3 ngày, PubMed vài tuần/tháng.

Hit rate thực tế (query biomedical typical):
    ~40-50% có JATS XML (PMC + preprint) + ~15-20% nhờ ID Converter = ~60-70% OA.
    Phần còn lại (paywall) chỉ giữ link.

Tham khảo: europepmc.org/Preprints, ncbi.nlm.nih.gov/books/NBK25501 (E-utilities),
           docs.openalex.org, api.biorxiv.org, api.elifesciences.org, api.core.ac.uk/docs/v3.
"""

import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import aiohttp


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class Config:
    LLM_API_URL    = "https://claudible.io/v1/chat/completions"
    LLM_API_KEY    = "sk-6341fd2e6ac2e832574d06190f318f607f5cfe51011258b77cdc83e2aa144c87"
    LLM_MODEL      = "gpt-5.4"
    LLM_MAX_TOKENS = 1024

    UNPAYWALL_EMAIL = "duy@nanyangbiologics.com"
    ENTREZ_BASE     = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    IDCONV_URL      = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"

    # Tuỳ chọn — để trống nếu không có
    CORE_API_KEY = ""   # đăng ký tại core.ac.uk/services/api

    DEFAULT_MAX_RESULTS = 10
    FETCH_WORKERS       = 5


# ---------------------------------------------------------------------------
# Step 0 — LLM: translate any language → Boolean query
# ---------------------------------------------------------------------------
async def translate_to_search_query(session, user_input: str) -> str:
    prompt = (
        "You are a biomedical search expert. Convert the following user input "
        "(in any language) into an English Boolean search query suitable for "
        "biomedical databases (supports AND, OR, NOT, parentheses, quoted phrases). "
        "Return ONLY the query string, no explanation, no markdown, no extra text.\n\n"
        f"User input: {user_input}"
    )
    payload = {
        "model": Config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": Config.LLM_MAX_TOKENS,
    }
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {Config.LLM_API_KEY}",
    }
    try:
        async with session.post(Config.LLM_API_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
        msg = data["choices"][0]["message"]
        query = (msg.get("content") or msg.get("reasoning") or user_input).strip()
        print(f"[LLM] Query: {query}")
        return query
    except Exception as e:
        print(f"[LLM] Lỗi: {e}. Dùng nguyên từ khóa gốc.")
        return user_input


# ---------------------------------------------------------------------------
# Step 1 — Search 3 nguồn song song (metadata + link)
# ---------------------------------------------------------------------------
async def search_europepmc(session, query: str, max_results: int) -> list[dict]:
    params = {
        "query":      f"{query} AND OPEN_ACCESS:y",
        "format":     "json",
        "resultType": "core",
        "pageSize":   max_results,
    }
    try:
        async with session.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                               params=params) as resp:
            data = await resp.json()
        results = []
        for a in data.get("resultList", {}).get("result", []):
            pmcid = a.get("pmcid") or None
            authors = [au.get("fullName") for au in (a.get("authorList", {}) or {}).get("author", []) if au.get("fullName")]
            results.append({
                "title":    a.get("title") or None,
                "doi":      a.get("doi") or None,
                "pmid":     str(a["pmid"]) if a.get("pmid") else None,
                "pmcid":    pmcid,
                "authors":  authors or None,
                "journal":  a.get("journalTitle") or None,
                "year":     a.get("pubYear") or None,
                "abstract": a.get("abstractText") or None,
                "link":     f"https://europepmc.org/article/MED/{a['pmid']}" if a.get("pmid") else
                            (f"https://doi.org/{a['doi']}" if a.get("doi") else None),
                "source":   "EuropePMC",
            })
        return results
    except Exception as e:
        print(f"[EuropePMC] Lỗi: {e}")
        return []


async def search_pubmed(session, query: str, max_results: int) -> list[dict]:
    try:
        async with session.get(Config.ENTREZ_BASE + "esearch.fcgi",
                               params={"db": "pubmed", "term": query,
                                       "retmax": max_results, "retmode": "json"}) as resp:
            data = await resp.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"[PubMed] esearch lỗi: {e}")
        return []
    if not id_list:
        return []

    try:
        async with session.get(Config.ENTREZ_BASE + "efetch.fcgi",
                               params={"db": "pubmed", "id": ",".join(id_list),
                                       "rettype": "abstract", "retmode": "xml"}) as resp:
            content = await resp.read()
        root = ET.fromstring(content)
    except Exception as e:
        print(f"[PubMed] efetch lỗi: {e}")
        return []

    results = []
    for article in root.findall(".//PubmedArticle"):
        title_el = article.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else None

        # IDs
        pmid = pmcid = doi = None
        for aid in article.findall(".//ArticleId"):
            t, v = aid.get("IdType", "").lower(), (aid.text or "").strip()
            if t == "pubmed":  pmid = v
            elif t == "pmc":   pmcid = v if v.upper().startswith("PMC") else f"PMC{v}"
            elif t == "doi":   doi = v
        if pmid is None:
            el = article.find(".//MedlineCitation/PMID")
            if el is not None: pmid = (el.text or "").strip()

        # Abstract (có thể có nhiều section)
        abs_parts = []
        for el in article.findall(".//Abstract/AbstractText"):
            label = el.get("Label")
            text = "".join(el.itertext()).strip()
            if text:
                abs_parts.append(f"{label}: {text}" if label else text)
        abstract = "\n".join(abs_parts) if abs_parts else None

        # Authors
        authors = []
        for au in article.findall(".//AuthorList/Author"):
            last = au.findtext("LastName") or ""
            initials = au.findtext("Initials") or ""
            name = (last + " " + initials).strip()
            if name: authors.append(name)

        journal = article.findtext(".//Journal/Title")
        year    = article.findtext(".//PubDate/Year") or article.findtext(".//PubDate/MedlineDate")

        results.append({
            "title":    title,
            "doi":      doi or None,
            "pmid":     pmid or None,
            "pmcid":    pmcid or None,
            "authors":  authors or None,
            "journal":  journal or None,
            "year":     year or None,
            "abstract": abstract,
            "link":     f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            "source":   "PubMed",
        })
    return results


async def search_openalex(session, query: str, max_results: int) -> list[dict]:
    try:
        async with session.get("https://api.openalex.org/works",
                               params={"search": query,
                                       "filter": "open_access.is_oa:true",
                                       "per-page": max_results},
                               headers={"User-Agent": f"mailto:{Config.UNPAYWALL_EMAIL}"}) as resp:
            data = await resp.json()
        results = []
        for w in data.get("results", []):
            ids = w.get("ids", {})
            doi = w.get("doi", "") or ""
            if doi.startswith("https://doi.org/"): doi = doi[16:]
            pmid = ids.get("pmid", "") or ""
            if pmid.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
                pmid = pmid[32:].rstrip("/")
            pmcid = ids.get("pmcid", "") or ""
            if pmcid.startswith("https://www.ncbi.nlm.nih.gov/pmc/articles/"):
                pmcid = pmcid[42:].rstrip("/")

            authors = [a.get("author", {}).get("display_name")
                       for a in w.get("authorships", []) if a.get("author")]

            # Reconstruct abstract from inverted index
            abs_inv = w.get("abstract_inverted_index") or {}
            abstract = None
            if abs_inv:
                positions = []
                for word, pos_list in abs_inv.items():
                    for p in pos_list:
                        positions.append((p, word))
                positions.sort()
                abstract = " ".join(w for _, w in positions) or None

            results.append({
                "title":    w.get("title") or None,
                "doi":      doi or None,
                "pmid":     pmid or None,
                "pmcid":    pmcid or None,
                "authors":  [a for a in authors if a] or None,
                "journal":  (w.get("primary_location") or {}).get("source", {}).get("display_name") if w.get("primary_location") else None,
                "year":     str(w["publication_year"]) if w.get("publication_year") else None,
                "abstract": abstract,
                "link":     (w.get("open_access") or {}).get("oa_url") or w.get("id"),
                "source":   "OpenAlex",
            })
        return results
    except Exception as e:
        print(f"[OpenAlex] Lỗi: {e}")
        return []


# ---------------------------------------------------------------------------
# Step 2 — Deduplicate by DOI > PMCID > PMID > title
#          Merge metadata từ nhiều nguồn (field nào rỗng thì điền)
# ---------------------------------------------------------------------------
def deduplicate_merge(papers: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    order: list[str] = []

    def keys_of(p: dict) -> list[str]:
        ks = []
        if p.get("doi"):   ks.append(f"doi:{p['doi'].lower()}")
        if p.get("pmcid"): ks.append(f"pmcid:{p['pmcid'].upper()}")
        if p.get("pmid"):  ks.append(f"pmid:{p['pmid']}")
        title_norm = (p.get("title") or "").strip().lower()[:80]
        if title_norm: ks.append(f"title:{title_norm}")
        return ks

    for p in papers:
        ks = keys_of(p)
        existing_key = next((k for k in ks if k in by_key), None)
        if existing_key:
            merged = by_key[existing_key]
            for field, val in p.items():
                if val and not merged.get(field):
                    merged[field] = val
            # Register new keys to alias this paper
            for k in ks:
                by_key.setdefault(k, merged)
        else:
            for k in ks:
                by_key[k] = p
            if ks:
                order.append(ks[0])

    seen_ids = set()
    unique = []
    for k in order:
        p = by_key.get(k)
        if p is None: continue
        pid = id(p)
        if pid in seen_ids: continue
        seen_ids.add(pid)
        unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Step 3 — Fetch full-text JATS XML (KHÔNG download PDF)
# ---------------------------------------------------------------------------
def _clean_text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def parse_jats(xml_bytes: bytes | str) -> dict | None:
    """Parse JATS XML → {abstract, sections{section_name: text}, references, full_text}."""
    try:
        if isinstance(xml_bytes, str):
            xml_bytes = xml_bytes.encode("utf-8", errors="ignore")
        root = ET.fromstring(xml_bytes)
    except Exception:
        return None

    # Abstract
    abstract = None
    abs_el = root.find(".//abstract")
    if abs_el is not None:
        abstract = _clean_text(abs_el)

    # Body sections
    sections: dict[str, str] = {}
    body = root.find(".//body")
    if body is not None:
        for idx, sec in enumerate(body.findall(".//sec")):
            sec_type = sec.get("sec-type") or ""
            title = sec.findtext("title") or ""
            key = (sec_type or title or f"section_{idx}").strip().lower().replace(" ", "_")
            text = _clean_text(sec)
            if text:
                sections[key] = text

    # References
    references = []
    for ref in root.findall(".//back//ref"):
        text = _clean_text(ref)
        if text: references.append(text)

    # Full text = abstract + body concatenated
    full_parts = []
    if abstract: full_parts.append(abstract)
    if body is not None:
        full_parts.append(_clean_text(body))
    full_text = "\n\n".join(full_parts) if full_parts else None

    if not full_text:
        return None

    return {
        "abstract":   abstract,
        "sections":   sections or None,
        "references": references or None,
        "full_text":  full_text,
    }


async def _try_europepmc_fulltext(session, pmcid: str) -> dict | None:
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    try:
        async with session.get(url) as resp:
            if resp.status != 200: return None
            xml = await resp.read()
        parsed = parse_jats(xml)
        if parsed: parsed["fulltext_source"] = "EuropePMC"
        return parsed
    except Exception as e:
        print(f"    [EuropePMC fulltext] {e}")
        return None


async def _try_pmc_efetch(session, pmcid: str) -> dict | None:
    pmc_id = pmcid.upper().replace("PMC", "")
    try:
        async with session.get(Config.ENTREZ_BASE + "efetch.fcgi",
                               params={"db": "pmc", "id": pmc_id, "rettype": "xml"}) as resp:
            if resp.status != 200: return None
            xml = await resp.read()
        if b"<article" not in xml: return None
        parsed = parse_jats(xml)
        if parsed: parsed["fulltext_source"] = "PMC"
        return parsed
    except Exception as e:
        print(f"    [PMC efetch] {e}")
        return None


async def _try_biorxiv(session, doi: str) -> dict | None:
    for server in ("biorxiv", "medrxiv"):
        try:
            async with session.get(
                f"https://api.biorxiv.org/details/{server}/{doi}/na/json"
            ) as resp:
                if resp.status != 200: continue
                data = await resp.json()
            coll = data.get("collection") or []
            if not coll: continue
            jats_url = coll[0].get("jatsxml")
            if not jats_url: continue
            async with session.get(jats_url) as resp:
                if resp.status != 200: continue
                xml = await resp.read()
            parsed = parse_jats(xml)
            if parsed:
                parsed["fulltext_source"] = server
                return parsed
        except Exception as e:
            print(f"    [{server}] {e}")
    return None


async def _lookup_pmcid(session, doi: str | None, pmid: str | None) -> str | None:
    """NCBI ID Converter: DOI/PMID → PMCID. Mở khóa thêm bài có trong PMC."""
    ids = doi or pmid
    if not ids: return None
    try:
        async with session.get(
            Config.IDCONV_URL + "?format=json&ids=" + quote(ids),
            headers={"User-Agent": f"mailto:{Config.UNPAYWALL_EMAIL}"}
        ) as resp:
            if resp.status != 200: return None
            data = await resp.json()
        for rec in data.get("records", []):
            pmcid = rec.get("pmcid")
            if pmcid: return pmcid
    except Exception as e:
        print(f"    [IDConverter] {e}")
    return None


async def _try_elife(session, doi: str) -> dict | None:
    """eLife JSON API — trả về full-text structured."""
    if not doi.startswith("10.7554/eLife."): return None
    article_id = doi.split("eLife.")[-1].lstrip("0") or "0"
    url = f"https://api.elifesciences.org/articles/{article_id}"
    try:
        async with session.get(url, headers={"Accept": "application/vnd.elife.article-vor+json;version=8"}) as resp:
            if resp.status != 200: return None
            data = await resp.json()
        # Body là list các section JSON — gom text
        sections: dict[str, str] = {}
        full_parts = []
        for block in data.get("body", []):
            sec_title = (block.get("title") or f"section_{len(sections)}").lower().replace(" ", "_")
            txt_parts = []
            for sub in block.get("content", []):
                if isinstance(sub, dict) and sub.get("text"):
                    txt_parts.append(re.sub(r"<[^>]+>", "", sub["text"]))
            text = " ".join(txt_parts).strip()
            if text:
                sections[sec_title] = text
                full_parts.append(text)
        if not full_parts: return None
        abstract = None
        abs_content = (data.get("abstract") or {}).get("content") or []
        if abs_content:
            abstract = " ".join(re.sub(r"<[^>]+>", "", c.get("text", "")) for c in abs_content if isinstance(c, dict))
        return {
            "abstract":        abstract,
            "sections":        sections,
            "references":      None,
            "full_text":       "\n\n".join(full_parts),
            "fulltext_source": "eLife",
        }
    except Exception as e:
        print(f"    [eLife] {e}")
    return None


async def _try_core(session, doi: str | None, title: str | None) -> dict | None:
    """CORE v3 — text fulltext (chất lượng thấp hơn JATS, fallback cuối)."""
    if not Config.CORE_API_KEY: return None
    headers = {"Authorization": f"Bearer {Config.CORE_API_KEY}"}
    q = f'doi:"{doi}"' if doi else f'title:"{title}"'
    try:
        async with session.get("https://api.core.ac.uk/v3/search/works",
                               params={"q": q, "limit": 1}, headers=headers) as resp:
            if resp.status != 200: return None
            data = await resp.json()
        items = data.get("results") or []
        if not items: return None
        full_text = items[0].get("fullText")
        if not full_text: return None
        return {
            "abstract":        items[0].get("abstract"),
            "sections":        None,  # CORE không tách section
            "references":      None,
            "full_text":       full_text,
            "fulltext_source": "CORE",
        }
    except Exception as e:
        print(f"    [CORE] {e}")
    return None


async def fetch_fulltext(session, paper: dict) -> dict | None:
    """Ưu tiên: eLife → EuropePMC → PMC efetch → bioRxiv/medRxiv → CORE.
    Nếu chưa có pmcid, thử lookup qua NCBI ID Converter trước."""
    pmcid = paper.get("pmcid")
    doi   = paper.get("doi")
    pmid  = paper.get("pmid")
    title = paper.get("title")

    # eLife (DOI-based) — có JSON API riêng, structured đẹp
    if doi:
        result = await _try_elife(session, doi)
        if result: return result

    # Enrich pmcid nếu thiếu (mở khóa thêm full-text PMC)
    if not pmcid and (doi or pmid):
        pmcid = await _lookup_pmcid(session, doi, pmid)
        if pmcid:
            paper["pmcid"] = pmcid  # ghi ngược lại để output phản ánh
            print(f"    [IDConverter] {doi or pmid} → {pmcid}")

    if pmcid:
        result = await _try_europepmc_fulltext(session, pmcid)
        if result: return result
        result = await _try_pmc_efetch(session, pmcid)
        if result: return result

    if doi:
        result = await _try_biorxiv(session, doi)
        if result: return result

    # CORE fallback cuối (chỉ khi có API key)
    if Config.CORE_API_KEY and (doi or title):
        result = await _try_core(session, doi, title)
        if result: return result

    return None


# ---------------------------------------------------------------------------
# Step 4 — Main pipeline: trả về dict {title: {...}}
# ---------------------------------------------------------------------------
async def retrieve_papers(user_input: str,
                          max_results: int = Config.DEFAULT_MAX_RESULTS) -> dict:
    connector = aiohttp.TCPConnector(limit=20)
    timeout   = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        print(f"\n[Input] {user_input}")
        query = await translate_to_search_query(session, user_input)

        print(f"[Search] Đang tìm từ 3 nguồn song song...")

        async def timed(name, coro):
            t0 = time.perf_counter()
            res = await coro
            elapsed = time.perf_counter() - t0
            print(f"  [{name}] {len(res)} bài trong {elapsed:.2f}s")
            return res, elapsed

        t_total = time.perf_counter()
        (epmc, t_epmc), (pm, t_pm), (oa, t_oa) = await asyncio.gather(
            timed("EuropePMC", search_europepmc(session, query, max_results)),
            timed("PubMed",    search_pubmed(session, query, max_results)),
            timed("OpenAlex",  search_openalex(session, query, max_results)),
        )
        t_wall = time.perf_counter() - t_total
        print(f"  [Wall time song song] {t_wall:.2f}s "
              f"(tuần tự sẽ tốn ~{t_epmc + t_pm + t_oa:.2f}s)")
        raw = [epmc, pm, oa]
        all_papers = [p for lst in raw for p in lst]
        papers = deduplicate_merge(all_papers)
        print(f"[Dedup] {len(all_papers)} bài → còn {len(papers)} bài duy nhất")

        # Fetch full-text song song (có giới hạn)
        sem = asyncio.Semaphore(Config.FETCH_WORKERS)

        async def process(idx: int, paper: dict):
            async with sem:
                tag = f"[{idx+1}/{len(papers)}] {(paper.get('title') or 'Unknown')[:60]}..."
                ft = await fetch_fulltext(session, paper)
                if ft:
                    print(f"  {tag} -> full-text từ {ft['fulltext_source']} ({len(ft['full_text'])} chars)")
                else:
                    print(f"  {tag} -> KHÔNG có full-text (chỉ có link)")
                return ft

        fulltexts = await asyncio.gather(*(process(i, p) for i, p in enumerate(papers)))

        # Build output dict
        output: dict[str, dict] = {}
        for paper, ft in zip(papers, fulltexts):
            title = paper.get("title") or f"untitled_{paper.get('pmid') or paper.get('doi')}"
            # Tránh key trùng
            base_title = title
            dup_i = 2
            while title in output:
                title = f"{base_title} [{dup_i}]"
                dup_i += 1

            entry = {
                "title":    paper.get("title"),
                "authors":  paper.get("authors"),
                "journal":  paper.get("journal"),
                "year":     paper.get("year"),
                "doi":      paper.get("doi"),
                "pmid":     paper.get("pmid"),
                "pmcid":    paper.get("pmcid"),
                "link":     paper.get("link"),
                "source":   paper.get("source"),
                "abstract": paper.get("abstract"),
            }
            if ft:
                entry["fulltext"]        = ft["full_text"]
                entry["sections"]        = ft["sections"]
                entry["references"]      = ft["references"]
                entry["fulltext_source"] = ft["fulltext_source"]
                if ft.get("abstract") and not entry["abstract"]:
                    entry["abstract"] = ft["abstract"]
            else:
                entry["fulltext"]        = None
                entry["fulltext_source"] = None

            output[title] = entry

        got_ft = sum(1 for e in output.values() if e["fulltext"])
        print(f"\n[Kết quả] {got_ft}/{len(output)} bài có full-text structured.")
        return output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import sys

    user_query = sys.argv[1] if len(sys.argv) > 1 else "hợp chất chống ung thư"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "papers.json"

    result = asyncio.run(retrieve_papers(user_query, max_results=Config.DEFAULT_MAX_RESULTS))

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[Output] Đã ghi {len(result)} bài vào {output_file}")
