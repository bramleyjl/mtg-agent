"""
Default chunking strategies for long-form CW/HD text content, keyed by category.

Three tiers, chosen per source rather than one universal strategy:
  structured_document — already atomic at ingestion (Comprehensive Rules numbered
                        entries, glossary terms) via the source's own numbering.
                        No chunking needed here; just full-text-index the field.
  article             — long-form prose with no inherent addressable structure
                        (WotC announcements, future primers/Discord/Reddit posts).
                        Chunked by paragraph via chunk_text() below, stored in the
                        shared content_chunks collection.
  reference_list       — small enough (a few dozen short entries) that whole-list
                        retrieval already works; no chunking needed.

chunk_text() is deliberately simple (paragraph merge/split, no embeddings) since
this is scaffolding for keyword search now — see the RAG roadmap memory for the
planned migration to embedding-based chunking once vector search is enabled.
"""

MIN_CHUNK_CHARS = 300
MAX_CHUNK_CHARS = 1500


def chunk_text(text: str, min_chars: int = MIN_CHUNK_CHARS, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    Split text into paragraph-aligned chunks. Merges consecutive short
    paragraphs up to max_chars; splits any single paragraph that alone
    exceeds max_chars on sentence boundaries.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        for piece in _split_oversized(para, max_chars):
            if buffer and len(buffer) + len(piece) + 2 > max_chars:
                chunks.append(buffer)
                buffer = piece
            else:
                buffer = f"{buffer}\n\n{piece}" if buffer else piece
            if len(buffer) >= min_chars and len(buffer) + 200 > max_chars:
                chunks.append(buffer)
                buffer = ""
    if buffer:
        chunks.append(buffer)

    # Merge a too-small trailing chunk into its predecessor rather than
    # leaving a fragment (e.g. a one-line closing paragraph).
    if len(chunks) > 1 and len(chunks[-1]) < min_chars:
        chunks[-2] = f"{chunks[-2]}\n\n{chunks[-1]}"
        chunks.pop()

    return chunks


def _split_oversized(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = paragraph.replace(". ", ".\x00").split("\x00")
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + len(sentence) + 1 > max_chars:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}" if buffer else sentence
    if buffer:
        pieces.append(buffer)
    return pieces
