"""
Download the current Magic: The Gathering Comprehensive Rules and upsert into MongoDB.

The .txt download link is dated (e.g. MagicCompRules 20260619.txt) and changes with
every rules update, so it's always re-derived from the rules landing page rather than
hardcoded. Populates two collections:
  rules_numbered — one document per addressable rule/subrule (e.g. "903.5c") plus
                   section/rule-group headers (e.g. "903", "9"), keyed by number
  rules_glossary — one document per glossary term, keyed by term

Run:               python -m mtg_agent.scripts.refresh_comprehensive_rules
Stale check only:  python -m mtg_agent.scripts.refresh_comprehensive_rules --if-stale
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import ReplaceOne

from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db

RULES_INDEX_URL = "https://magic.wizards.com/en/rules"
STALE_AFTER_DAYS = 56  # ~8 weeks
BATCH_SIZE = 500
META_COLLECTION = "rules_meta"

_TXT_LINK_RE = re.compile(r"https://media\.wizards\.com/\d{4}/downloads/MagicCompRules[ %20]*\d{8}\.txt")
_EFFECTIVE_DATE_RE = re.compile(r"effective as of (\w+ \d{1,2}, \d{4})", re.IGNORECASE)
_SECTION_RE = re.compile(r"^([1-9])\.\s+(.+)$")
_RULE_RE = re.compile(r"^(\d{3}(?:\.\d+[a-z]?)?)\.?\s*(.*)$", re.DOTALL)
_GLOSSARY_HEADER = "Glossary"
_CREDITS_HEADER = "Credits"


def _last_updated() -> datetime | None:
    meta = get_db()[META_COLLECTION].find_one({"_id": "last_updated"})
    return meta["timestamp"] if meta else None


def _is_stale() -> bool:
    last = _last_updated()
    if last is None:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return last < now - timedelta(days=STALE_AFTER_DAYS)


def _find_current_txt_url() -> str:
    """Scrape the rules landing page for the current dated .txt download link."""
    resp = httpx.get(RULES_INDEX_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    match = _TXT_LINK_RE.search(resp.text)
    if not match:
        raise RuntimeError("Could not find Comprehensive Rules .txt link on rules page")
    return match.group(0).replace(" ", "%20")


def _download_rules_text(url: str) -> str:
    print(f"  Downloading {url.split('/')[-1]}...", flush=True)
    with httpx.stream("GET", url, timeout=60.0) as resp:
        resp.raise_for_status()
        raw = b"".join(resp.iter_bytes())
    return raw.decode("utf-8-sig").replace("\r\n", "\n")


def _parse_effective_date(text: str) -> str | None:
    match = _EFFECTIVE_DATE_RE.search(text[:500])
    return match.group(1) if match else None


def _parse_numbered_rules(text: str, effective_date: str | None) -> list[dict]:
    """
    Each addressable rule (top-level section header, rule group header, or
    numbered subrule) is its own blank-line-separated block in the source text,
    with any "Example:" lines glued to the same block.
    """
    # "Glossary" also appears in the table of contents, so use the last occurrence.
    glossary_start = text.rindex(f"\n{_GLOSSARY_HEADER}\n")
    body = text[:glossary_start]

    docs: list[dict] = []
    current_section = None
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue

        section_match = _SECTION_RE.match(block)
        if section_match and "." not in section_match.group(1):
            current_section = section_match.group(1)
            docs.append({
                "number": current_section,
                "title": section_match.group(2).strip(),
                "text": "",
                "section": current_section,
                "effective_date": effective_date,
            })
            continue

        rule_match = _RULE_RE.match(block)
        if not rule_match:
            continue
        number, rest = rule_match.group(1), rule_match.group(2).strip()
        section = number[0]
        # Bare 3-digit rule-group headers (e.g. "903. Commander") have only a title.
        is_group_header = "." not in number and rest and "\n" not in rest and len(rest.split()) <= 8
        docs.append({
            "number": number,
            "title": rest if is_group_header else None,
            "text": "" if is_group_header else rest,
            "section": section,
            "effective_date": effective_date,
        })
    return docs


def _parse_glossary(text: str, effective_date: str | None) -> list[dict]:
    glossary_start = text.rindex(f"\n{_GLOSSARY_HEADER}\n") + len(_GLOSSARY_HEADER) + 2
    credits_start = text.rindex(f"\n{_CREDITS_HEADER}\n")
    body = text[glossary_start:credits_start]

    docs: list[dict] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.strip().split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        term, definition = lines[0].strip(), "\n".join(lines[1:]).strip()
        docs.append({"term": term, "definition": definition, "effective_date": effective_date})
    return docs


def _upsert_batch(collection: str, key: str, batch: list[dict]) -> None:
    ops = [ReplaceOne({key: doc[key]}, doc, upsert=True) for doc in batch]
    if ops:
        get_db()[collection].bulk_write(ops, ordered=False)


def _upsert_all(collection: str, key: str, docs: list[dict]) -> None:
    for i in range(0, len(docs), BATCH_SIZE):
        _upsert_batch(collection, key, docs[i:i + BATCH_SIZE])


def refresh(force: bool = False) -> None:
    if not force and not _is_stale():
        print(f"Rules are fresh (checked within the last {STALE_AFTER_DAYS} days) — nothing to do.", flush=True)
        return

    print("Finding current Comprehensive Rules link...", flush=True)
    url = _find_current_txt_url()
    text = _download_rules_text(url)
    effective_date = _parse_effective_date(text)
    print(f"  Effective date: {effective_date}", flush=True)

    rules = _parse_numbered_rules(text, effective_date)
    print(f"  Parsed {len(rules)} rule entries.", flush=True)
    _upsert_all("rules_numbered", "number", rules)

    glossary = _parse_glossary(text, effective_date)
    print(f"  Parsed {len(glossary)} glossary terms.", flush=True)
    _upsert_all("rules_glossary", "term", glossary)

    get_db()[META_COLLECTION].update_one(
        {"_id": "last_updated"},
        {"$set": {"timestamp": datetime.now(timezone.utc), "effective_date": effective_date, "source_url": url}},
        upsert=True,
    )
    print("Done.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help=f"Only refresh if the last update was more than {STALE_AFTER_DAYS} days ago.",
    )
    args = parser.parse_args()

    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)

    try:
        refresh(force=not args.if_stale)
    except Exception as e:
        print(f"Error refreshing Comprehensive Rules: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
