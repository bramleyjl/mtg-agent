"""
Shared scraping logic for magic.wizards.com news announcement articles.

Article pages are server-rendered with a single <article> tag (whose actual
body content is scoped to a "class=\"article-body\"" container, after nav
breadcrumbs and the byline header) and an embedded NewsArticle JSON-LD block
(data-hid="article-json-ld") carrying headline/author/publish date.

New announcements for a given topic are discovered via WotC's own article
search (magic.wizards.com/en/news/announcements?search=...), confirmed
server-side filtered — a plain httpx GET (no JS execution) returns only the
matching articles. If a topic ever outgrows one page of search results, this
will need pagination handling.
"""

import html as htmllib
import json
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from mtg_agent.chunking import chunk_text

BASE_URL = "https://magic.wizards.com"

_ANNOUNCEMENT_HREF_RE = re.compile(r'href="(/en/news/announcements/[a-z0-9-]+)"')
_ARTICLE_JSON_LD_RE = re.compile(
    r'<script data-n-head="ssr" data-hid="article-json-ld"[^>]*>(.*?)</script>', re.DOTALL
)


def discover_announcement_urls(search_url: str) -> list[str]:
    resp = httpx.get(search_url, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    paths = dict.fromkeys(_ANNOUNCEMENT_HREF_RE.findall(resp.text))  # dedupe, preserve order
    return [urljoin(BASE_URL, path) for path in paths]


def _clean_text(article_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", article_html)
    text = htmllib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_announcement(url: str) -> dict:
    resp = httpx.get(url, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    page_html = resp.text

    div_start = page_html.index('class="article-body')
    start = page_html.index(">", div_start) + 1
    end = page_html.index("</article>")
    article_html = page_html[start:end]

    meta_match = _ARTICLE_JSON_LD_RE.search(page_html)
    meta = json.loads(meta_match.group(1)) if meta_match else {}
    authors = [a.get("name") for a in meta.get("author", []) if a.get("name")]

    return {
        "url": url,
        "title": meta.get("headline"),
        "published_date": meta.get("datePublished"),
        "modified_date": meta.get("dateModified"),
        "authors": authors,
        "text": _clean_text(article_html),
    }


def chunk_announcement(doc: dict[str, Any], category: str) -> list[dict[str, Any]]:
    """Paragraph-chunk a fetch_announcement() doc into content_chunks records (article tier)."""
    return [
        {
            "source_url": doc["url"],
            "title": doc["title"],
            "published_date": doc["published_date"],
            "category": category,
            "chunk_index": i,
            "text": chunk,
        }
        for i, chunk in enumerate(chunk_text(doc["text"]))
    ]
