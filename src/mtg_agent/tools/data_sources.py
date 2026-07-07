import inspect
import io
from contextlib import redirect_stdout

from mtg_agent.scripts import (
    refresh_commander_banlist,
    refresh_commander_banr_announcements,
    refresh_commander_bracket_announcements,
    refresh_commander_brackets,
    refresh_commander_spellbook,
    refresh_comprehensive_rules,
    refresh_deck_working_notes,
    refresh_scryfall_bulk,
)

# Each entry: (label, callable taking force: bool). Order matches the cron layout
# in CLAUDE.md (Scryfall first, then the WotC-sourced group, then Spellbook).
# A source's callable may return a coroutine (see refresh_deck_working_notes,
# which needs async notion-mcp calls) — refresh_all_data_sources awaits it if so.
_SOURCES = [
    ("scryfall_bulk", lambda force: refresh_scryfall_bulk.refresh(force=force)),
    ("comprehensive_rules", lambda force: refresh_comprehensive_rules.refresh(force=force)),
    ("commander_banlist", lambda force: refresh_commander_banlist.refresh(force=force)),
    ("commander_brackets", lambda force: refresh_commander_brackets.refresh(force=force)),
    ("commander_bracket_announcements", lambda force: refresh_commander_bracket_announcements.refresh(force=force)),
    ("commander_banr_announcements", lambda force: refresh_commander_banr_announcements.refresh(force=force)),
    ("commander_spellbook_combos", lambda force: refresh_commander_spellbook.refresh(force=force)),
    ("commander_spellbook_templates", lambda force: refresh_commander_spellbook.refresh_templates(force=force)),
    ("deck_working_notes", lambda force: refresh_deck_working_notes.refresh(force=force)),
]


async def refresh_all_data_sources(force: bool = False) -> list[dict]:
    """
    Run every data-source refresh in-process and return a per-source result.
    force=False (default) mirrors the nightly cron behavior — each source only
    refreshes if past its own staleness window. force=True refreshes everything
    unconditionally, e.g. at the start of a session where fresh data matters.
    """
    results = []
    for label, run in _SOURCES:
        buf = io.StringIO()
        entry: dict = {"source": label}
        try:
            with redirect_stdout(buf):
                outcome = run(force)
                if inspect.isawaitable(outcome):
                    await outcome
            entry["status"] = "ok"
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
        entry["log"] = buf.getvalue().strip()
        results.append(entry)
    return results
