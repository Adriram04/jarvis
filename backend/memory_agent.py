"""
Semantic (RAG) memory for J.A.R.V.I.S.

Gives Jarvis a long-term, searchable memory: arbitrary text, notes, documents
(txt/md/code/PDF) and chat history are split into chunks, embedded with Google's
`gemini-embedding-001` model and stored in a lightweight local vector store
(numpy + JSON, no external DB). At query time the most semantically similar
chunks are retrieved so Jarvis can ground its answers on what it actually knows.

Design goals:
- No heavy native dependencies: the vector store is just a numpy matrix on disk.
- Resilient: a missing API key, an unreadable file or a bad PDF never crashes
  Jarvis; the relevant call just returns a friendly message.
- Demonstrable: exposes clear primitives (remember / ingest_file / search) that
  map directly to voice tools and a REST endpoint.
"""

import os
import re
import json
import time
import hashlib
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any

import numpy as np

from google import genai
from google.genai import types

# gemini-embedding-001 is the embedding model available on the v1beta API used
# across the project. 768 dims keeps the store small while preserving quality.
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_EMBEDDING_DIM = 768
# How big each text chunk is (characters) and how much consecutive chunks
# overlap, so a fact split across a boundary is still retrievable.
DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 150
# The embedding endpoint accepts batches; keep them modest to stay well within
# request limits and to surface partial failures early.
EMBED_BATCH_SIZE = 32

TEXT_FILE_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".jsonl",
    ".html", ".css", ".csv", ".log", ".yaml", ".yml",
}


class SemanticMemory:
    def __init__(
        self,
        storage_dir: str,
        api_key: Optional[str] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.vectors_path = self.storage_dir / "vectors.npy"
        self.records_path = self.storage_dir / "records.json"

        self.embedding_model = os.getenv("JARVIS_EMBEDDING_MODEL", embedding_model)
        self.embedding_dim = int(os.getenv("JARVIS_EMBEDDING_DIM", str(embedding_dim)))

        api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._client = None
        if api_key:
            try:
                self._client = genai.Client(
                    http_options={"api_version": "v1beta"}, api_key=api_key
                )
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[Memory] [ERR] Could not init embedding client: {exc}")

        # In-memory index. `vectors` is (N, dim) float32 L2-normalized so that a
        # dot product equals cosine similarity. `records[i]` describes row i.
        self.vectors: np.ndarray = np.zeros((0, self.embedding_dim), dtype=np.float32)
        self.records: List[Dict[str, Any]] = []
        self._hashes: set = set()
        self._lock = asyncio.Lock()

        self._load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _load(self):
        try:
            if self.records_path.exists():
                with open(self.records_path, "r", encoding="utf-8") as f:
                    self.records = json.load(f)
            if self.vectors_path.exists():
                vectors = np.load(self.vectors_path)
                if vectors.ndim == 2 and vectors.shape[0] == len(self.records):
                    self.vectors = vectors.astype(np.float32)
                    self.embedding_dim = vectors.shape[1]
            self._hashes = {r["hash"] for r in self.records if "hash" in r}
            if self.records:
                print(f"[Memory] Loaded {len(self.records)} chunks from {self.storage_dir}")
        except Exception as exc:
            print(f"[Memory] [WARN] Failed to load store ({exc}); starting empty.")
            self.vectors = np.zeros((0, self.embedding_dim), dtype=np.float32)
            self.records = []
            self._hashes = set()

    def _save(self):
        try:
            np.save(self.vectors_path, self.vectors)
            with open(self.records_path, "w", encoding="utf-8") as f:
                json.dump(self.records, f, ensure_ascii=False)
        except Exception as exc:
            print(f"[Memory] [ERR] Failed to persist store: {exc}")

    # ------------------------------------------------------------------ #
    # Chunking
    # ------------------------------------------------------------------ #
    @staticmethod
    def _chunk_text(
        text: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []

        # Split on blank lines first so chunks respect paragraph boundaries when
        # possible, then pack paragraphs up to the size budget.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: List[str] = []
        current = ""

        for para in paragraphs:
            if len(para) > chunk_size:
                # Flush whatever we have, then hard-split the long paragraph.
                if current:
                    chunks.append(current)
                    current = ""
                start = 0
                while start < len(para):
                    chunks.append(para[start:start + chunk_size])
                    start += max(1, chunk_size - overlap)
                continue

            if not current:
                current = para
            elif len(current) + len(para) + 2 <= chunk_size:
                current += "\n\n" + para
            else:
                chunks.append(current)
                # Carry a tail of the previous chunk for context overlap.
                tail = current[-overlap:] if overlap else ""
                current = (tail + "\n\n" + para).strip() if tail else para

        if current:
            chunks.append(current)

        return [c.strip() for c in chunks if c.strip()]

    # ------------------------------------------------------------------ #
    # Embedding
    # ------------------------------------------------------------------ #
    def _embed_sync(self, texts: List[str], task_type: str) -> Optional[np.ndarray]:
        if not self._client or not texts:
            return None
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self.embedding_dim,
        )
        out: List[List[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i:i + EMBED_BATCH_SIZE]
            resp = self._client.models.embed_content(
                model=self.embedding_model, contents=batch, config=config
            )
            out.extend(e.values for e in resp.embeddings)

        arr = np.asarray(out, dtype=np.float32)
        # L2-normalize so dot product == cosine similarity. gemini-embedding-001
        # does not return normalized vectors when output_dimensionality < 3072.
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    async def _embed(self, texts: List[str], task_type: str) -> Optional[np.ndarray]:
        return await asyncio.to_thread(self._embed_sync, texts, task_type)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def available(self) -> bool:
        return self._client is not None

    async def add_text(
        self,
        text: str,
        source: str = "note",
        project: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Chunk, embed and store a piece of text. Returns a small summary."""
        if not self.available:
            return {"success": False, "added": 0, "error": "Embedding API not configured (missing GEMINI_API_KEY)."}

        chunks = self._chunk_text(text)
        if not chunks:
            return {"success": False, "added": 0, "error": "Empty text, nothing to remember."}

        # Skip chunks we have already stored (idempotent ingestion).
        new_chunks, new_hashes = [], []
        for c in chunks:
            h = hashlib.sha256(c.encode("utf-8")).hexdigest()
            if h in self._hashes or h in new_hashes:
                continue
            new_chunks.append(c)
            new_hashes.append(h)

        if not new_chunks:
            return {"success": True, "added": 0, "skipped": len(chunks), "note": "Already in memory."}

        try:
            vectors = await self._embed(new_chunks, task_type="RETRIEVAL_DOCUMENT")
        except Exception as exc:
            return {"success": False, "added": 0, "error": f"Embedding failed: {str(exc)[:200]}"}

        if vectors is None or len(vectors) != len(new_chunks):
            return {"success": False, "added": 0, "error": "Embedding returned no data."}

        async with self._lock:
            ts = time.time()
            for chunk, h in zip(new_chunks, new_hashes):
                self.records.append({
                    "id": h[:16],
                    "hash": h,
                    "text": chunk,
                    "source": source,
                    "project": project,
                    "timestamp": ts,
                    "metadata": metadata or {},
                })
                self._hashes.add(h)
            self.vectors = np.vstack([self.vectors, vectors]) if len(self.vectors) else vectors
            self._save()

        return {"success": True, "added": len(new_chunks), "skipped": len(chunks) - len(new_chunks)}

    async def add_file(self, file_path: str, project: Optional[str] = None) -> Dict[str, Any]:
        """Read a file (txt/md/code/json/PDF) and store its contents."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return {"success": False, "added": 0, "error": f"File not found: {file_path}"}

        ext = path.suffix.lower()
        try:
            if ext == ".pdf":
                text = self._extract_pdf_text(path)
            elif ext in TEXT_FILE_EXTENSIONS or ext == "":
                text = path.read_text(encoding="utf-8", errors="ignore")
            else:
                return {"success": False, "added": 0, "error": f"Unsupported file type '{ext}'. Supported: text, code, markdown, json, pdf."}
        except Exception as exc:
            return {"success": False, "added": 0, "error": f"Could not read file: {str(exc)[:200]}"}

        if not (text or "").strip():
            return {"success": False, "added": 0, "error": "No extractable text in file."}

        result = await self.add_text(text, source=path.name, project=project, metadata={"path": str(path)})
        result["file"] = path.name
        return result

    @staticmethod
    def _extract_pdf_text(path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("PDF support requires the 'pypdf' package (pip install pypdf).")
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    async def search(
        self,
        query: str,
        k: int = 5,
        project: Optional[str] = None,
        min_score: float = 0.35,
    ) -> List[Dict[str, Any]]:
        """Return the top-k most semantically similar stored chunks."""
        if not self.available or len(self.records) == 0 or not (query or "").strip():
            return []

        try:
            q = await self._embed([query], task_type="RETRIEVAL_QUERY")
        except Exception as exc:
            print(f"[Memory] [ERR] Query embedding failed: {exc}")
            return []
        if q is None:
            return []

        scores = self.vectors @ q[0]  # cosine similarity (vectors are normalized)

        # Optionally restrict to a project namespace.
        if project:
            mask = np.array([r.get("project") == project for r in self.records])
            scores = np.where(mask, scores, -1.0)

        k = max(1, min(k, len(self.records)))
        top_idx = np.argsort(-scores)[:k]

        results = []
        for idx in top_idx:
            score = float(scores[idx])
            if score < min_score:
                continue
            rec = self.records[idx]
            results.append({
                "text": rec["text"],
                "source": rec.get("source"),
                "project": rec.get("project"),
                "score": round(score, 4),
                "timestamp": rec.get("timestamp"),
            })
        return results

    async def search_as_context(self, query: str, k: int = 5, **kwargs) -> str:
        """Search and format the hits as a text block for grounding an answer."""
        hits = await self.search(query, k=k, **kwargs)
        if not hits:
            return ""
        lines = ["Relevant information from your memory:"]
        for i, h in enumerate(hits, 1):
            src = h.get("source") or "memory"
            lines.append(f"[{i}] (source: {src}, relevance: {h['score']:.2f})\n{h['text']}")
        return "\n\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        sources: Dict[str, int] = {}
        for r in self.records:
            s = r.get("source") or "unknown"
            sources[s] = sources.get(s, 0) + 1
        return {
            "available": self.available,
            "chunks": len(self.records),
            "sources": sources,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
        }

    async def clear(self) -> Dict[str, Any]:
        async with self._lock:
            self.vectors = np.zeros((0, self.embedding_dim), dtype=np.float32)
            self.records = []
            self._hashes = set()
            self._save()
        return {"success": True, "chunks": 0}
