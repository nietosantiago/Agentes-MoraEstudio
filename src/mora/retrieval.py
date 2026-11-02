"""Ingesta + retrieval de documentos del estudio (C5–C8).

Contrato `Retriever` independiente del backend. La implementación por defecto es BM25 en memoria
(sin dependencias); la Fase 2 del roadmap agrega Qdrant + embeddings detrás del mismo contrato.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

STOPWORDS = set(
    "a al algo como con de del el ella en es esta este hay la las lo los me mi muy no o para pero por que se si sin "
    "su sus un una y ya yo tu te le les nos ser son fue esta estan the hola gracias".split()
)


def normalizar(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", texto)
    return [t[:-1] if len(t) > 4 and t.endswith("s") else t for t in tokens if t not in STOPWORDS]


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: str
    section: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Hit:
    chunk: Chunk
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 3, filters: dict | None = None) -> list[Hit]: ...


def _frontmatter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        meta = {}
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, body
    return {}, raw


def chunk_markdown(path: Path) -> list[Chunk]:
    """Chunking por sección (## ...) preservando metadata del documento y título de sección."""
    meta, body = _frontmatter(path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    section, buf = "intro", []

    def flush():
        text = " ".join(" ".join(buf).split())
        if text:
            chunks.append(Chunk(f"{path.stem}#{len(chunks)}", text, path.name, section, dict(meta)))

    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            section, buf = line[3:].strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    flush()
    return chunks


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._docs = [normalizar(f"{c.section} {c.section} {c.text}") for c in chunks]
        self._avgdl = sum(map(len, self._docs)) / max(len(self._docs), 1)
        df = Counter(t for d in self._docs for t in set(d))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_dir(cls, docs_dir: Path) -> "BM25Retriever":
        chunks = [c for p in sorted(docs_dir.glob("*.md")) for c in chunk_markdown(p)]
        return cls(chunks)

    def search(self, query: str, k: int = 3, filters: dict | None = None) -> list[Hit]:
        q = normalizar(query)
        hits: list[Hit] = []
        for chunk, doc in zip(self.chunks, self._docs):
            if filters and any(chunk.metadata.get(fk) != fv for fk, fv in filters.items()):
                continue
            tf = Counter(doc)
            score = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    score += self._idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / self._avgdl))
            if score > 0:
                hits.append(Hit(chunk, score))
        hits.sort(key=lambda h: (-h.score, h.chunk.chunk_id))
        return hits[:k]
