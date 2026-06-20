import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DeckConfig:
    slug: str
    name: str
    title: str
    moxfield_id: str
    notion_id: str
    colors: list[str]
    bracket: str
    notes: str


@dataclass
class Config:
    mongodb_uri: str
    mongodb_db: str
    notion_mcp_url: str = ""
    decks_path: str = ""
    decks: list[DeckConfig] = field(default_factory=list)
    decks_by_slug: dict[str, DeckConfig] = field(default_factory=dict)


def load_config() -> Config:
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db = os.getenv("MONGODB_DB", "mtg_agent")
    notion_mcp_url = os.getenv("NOTION_MCP_URL", "")

    decks_path = os.getenv(
        "DECKS_CONFIG",
        str(Path(__file__).parent.parent.parent / "decks.yaml"),
    )

    with open(decks_path) as f:
        raw = yaml.safe_load(f)

    decks = [DeckConfig(**d) for d in raw["decks"]]
    decks_by_slug = {d.slug: d for d in decks}

    return Config(
        mongodb_uri=mongodb_uri,
        mongodb_db=mongodb_db,
        notion_mcp_url=notion_mcp_url,
        decks_path=decks_path,
        decks=decks,
        decks_by_slug=decks_by_slug,
    )
