"""
Lightweight keyword retrieval over the knowledge base.

Given the small corpus (~9 markdown docs), BM25 over heading-aware chunks is
sufficient and avoids embedding-API latency, cost, and network dependency.
A vector store (embeddings + FAISS/pgvector) is the natural next step at
scale, once the corpus grows past what keyword search handles well.

Chunking strategy (per DATA_SCHEMA.md's recommendation):
- Split each doc on `---` horizontal rules (major section boundaries).
- Track heading hierarchy (H1 > H2 > H3) as metadata for each chunk.
- Additionally split out markdown table rows as their own atomic chunks,
  tagged with the row's first column (typically an error code), so an
  error-code lookup like "AUTH_TOKEN_EXPIRED" can match precisely instead of
  being diluted inside a whole table's worth of text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class KBChunk:
    doc_path: str          # path relative to knowledge-base/, e.g. "products/databridge-pro.md"
    heading_path: str      # e.g. "DataBridge Pro — Product Reference > Core Modules > Data Ingestion"
    text: str
    kind: str = "section"  # "section" | "table_row"

    def display_section(self) -> str:
        return self.heading_path or self.doc_path


def _split_doc_into_chunks(doc_path: str, raw_text: str) -> list[KBChunk]:
    chunks: list[KBChunk] = []
    heading_stack: list[tuple[int, str]] = []  # (level, text)

    # First split on '---' horizontal rules to get major sections.
    sections = re.split(r"\n-{3,}\n", raw_text)

    for section in sections:
        lines = section.split("\n")
        section_heading_path = None
        table_buffer: list[str] = []
        body_lines: list[str] = []

        for line in lines:
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack = [h for h in heading_stack if h[0] < level]
                heading_stack.append((level, title))
                section_heading_path = " > ".join(t for _, t in heading_stack)
                continue

            row_match = _TABLE_ROW_RE.match(line.strip())
            if row_match and "---" not in row_match.group(1):
                table_buffer.append(line.strip())
                continue

            body_lines.append(line)

        heading_path = section_heading_path or " > ".join(t for _, t in heading_stack)
        body_text = "\n".join(body_lines).strip()
        if body_text:
            chunks.append(KBChunk(doc_path=doc_path, heading_path=heading_path, text=body_text))

        # Table rows: skip the header row and the separator row, keep data rows
        # as individual atomic chunks (good for exact error-code lookups).
        data_rows = [r for r in table_buffer if not re.match(r"^\|[\s:|-]+\|$", r)]
        for row in data_rows[1:]:  # [0] is the header row
            row_text = row.strip("| ").strip()
            if row_text:
                chunks.append(
                    KBChunk(doc_path=doc_path, heading_path=heading_path, text=row_text, kind="table_row")
                )

    return chunks


class KBRetriever:
    def __init__(self, kb_dir: str | Path):
        self.kb_dir = Path(kb_dir)
        self.chunks: list[KBChunk] = []
        self._bm25: BM25Okapi | None = None
        self._load()

    def _load(self) -> None:
        for path in sorted(self.kb_dir.rglob("*.md")):
            rel = path.relative_to(self.kb_dir).as_posix()  # forward slashes on every OS
            text = path.read_text(encoding="utf-8")
            self.chunks.extend(_split_doc_into_chunks(rel, text))

        if self.chunks:
            tokenized = [_tokenize(c.text) for c in self.chunks]
            self._bm25 = BM25Okapi(tokenized)

    def search(self, query: str, top_k: int = 3, min_score: float = 4.0) -> list[dict]:
        """Return up to `top_k` matching chunks with score >= min_score.

        `min_score` is a deliberately conservative threshold: the task brief
        requires we return `null` rather than force a match when there isn't
        a confident one (see Task 1 requirements). BM25 scores aren't
        bounded [0,1], so this is tuned empirically against this corpus
        rather than derived analytically.
        """
        if not self._bm25 or not query.strip():
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for i in ranked:
            if scores[i] < min_score:
                continue
            chunk = self.chunks[i]
            results.append(
                {
                    "doc_path": chunk.doc_path,
                    "section": chunk.display_section(),
                    "text": chunk.text,
                    "kind": chunk.kind,
                    "score": round(float(scores[i]), 3),
                }
            )
        return results

    def best_match(self, query: str, min_score: float = 4.0) -> dict | None:
        results = self.search(query, top_k=1, min_score=min_score)
        return results[0] if results else None


_retriever: KBRetriever | None = None


def get_retriever(kb_dir: str | Path = "knowledge-base") -> KBRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KBRetriever(kb_dir)
    return _retriever
