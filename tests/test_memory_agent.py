"""
Tests for the semantic (RAG) memory engine.

The store/ranking/persistence logic is tested deterministically by injecting a
fake embedder, so these run without network or an API key. One end-to-end test
exercises the real Gemini embedding API and is skipped when no key is present.
"""
import os
import numpy as np
import pytest

from memory_agent import SemanticMemory


def _fake_embedder(memory, vocab):
    """Replace the network embedder with a deterministic bag-of-words one.

    Each text becomes a vector over a fixed vocabulary, so texts that share
    words are close in cosine space — enough to test retrieval ranking.
    """
    def embed(texts, task_type):
        rows = []
        for t in texts:
            low = t.lower()
            rows.append([float(low.count(w)) for w in vocab])
        arr = np.asarray(rows, dtype=np.float32)
        if arr.shape[1] < memory.embedding_dim:
            pad = np.zeros((arr.shape[0], memory.embedding_dim - arr.shape[1]), dtype=np.float32)
            arr = np.hstack([arr, pad])
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    memory._embed_sync = embed
    # Pretend the client exists so `available` is True.
    memory._client = object()


# --------------------------------------------------------------------------- #
# Chunking (pure, no embedder needed)
# --------------------------------------------------------------------------- #
class TestChunking:
    def test_empty_text_yields_no_chunks(self):
        assert SemanticMemory._chunk_text("") == []
        assert SemanticMemory._chunk_text("   \n  ") == []

    def test_short_text_is_single_chunk(self):
        chunks = SemanticMemory._chunk_text("Una nota corta sobre el TFG.")
        assert len(chunks) == 1

    def test_long_text_splits_into_multiple_chunks(self):
        text = "\n\n".join(f"Parrafo numero {i} " * 40 for i in range(6))
        chunks = SemanticMemory._chunk_text(text, chunk_size=300, overlap=50)
        assert len(chunks) > 1
        assert all(len(c) <= 400 for c in chunks)  # size + a little slack


# --------------------------------------------------------------------------- #
# Store / search / persistence (deterministic fake embedder)
# --------------------------------------------------------------------------- #
class TestStore:
    @pytest.fixture
    def memory(self, tmp_path):
        mem = SemanticMemory(storage_dir=str(tmp_path / "mem"), embedding_dim=16)
        _fake_embedder(mem, vocab=["impresora", "filamento", "calendario", "reunion", "movil", "soporte"])
        return mem

    async def test_add_and_search_returns_relevant_chunk(self, memory):
        await memory.add_text("El soporte para el movil necesita una base plana.", source="nota")
        await memory.add_text("La reunion del calendario es el lunes.", source="nota")

        hits = await memory.search("donde imprimo el soporte del movil", k=1, min_score=0.0)
        assert hits
        assert "soporte" in hits[0]["text"].lower()

    async def test_deduplicates_identical_text(self, memory):
        r1 = await memory.add_text("filamento PLA para la impresora", source="nota")
        r2 = await memory.add_text("filamento PLA para la impresora", source="nota")
        assert r1["added"] == 1
        assert r2["added"] == 0

    async def test_persists_across_reload(self, tmp_path):
        path = str(tmp_path / "mem")
        mem = SemanticMemory(storage_dir=path, embedding_dim=16)
        _fake_embedder(mem, vocab=["impresora", "filamento", "movil", "soporte"])
        await mem.add_text("soporte para el movil", source="nota")

        reloaded = SemanticMemory(storage_dir=path, embedding_dim=16)
        assert len(reloaded.records) == 1
        assert reloaded.vectors.shape[0] == 1

    async def test_add_file_reads_text(self, memory, tmp_path):
        f = tmp_path / "apuntes.md"
        f.write_text("# Apuntes\n\nEl soporte del movil va con filamento.", encoding="utf-8")
        result = await memory.add_file(str(f))
        assert result["success"]
        assert result["added"] >= 1

    async def test_add_missing_file_fails_gracefully(self, memory):
        result = await memory.add_file("no_existe_12345.txt")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    async def test_stats(self, memory):
        await memory.add_text("soporte movil", source="nota")
        s = memory.stats()
        assert s["chunks"] == 1
        assert s["available"] is True


class TestNoApiKey:
    async def test_add_text_without_client_is_graceful(self, tmp_path):
        mem = SemanticMemory(storage_dir=str(tmp_path / "mem"), api_key="")
        mem._client = None  # force unavailable
        result = await mem.add_text("algo")
        assert result["success"] is False
        assert mem.available is False


# --------------------------------------------------------------------------- #
# Real embedding API (skipped without key)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="requires GEMINI_API_KEY")
class TestRealEmbeddings:
    async def test_end_to_end_semantic_search(self, tmp_path):
        mem = SemanticMemory(storage_dir=str(tmp_path / "mem"))
        assert mem.available
        await mem.add_text(
            "Para imprimir el soporte del movil uso filamento PLA y una base de 80mm.",
            source="nota",
        )
        await mem.add_text("La reunion con el tutor del TFG es el martes a las 10.", source="nota")

        hits = await mem.search("que filamento uso para el soporte", k=1)
        assert hits
        assert "filamento" in hits[0]["text"].lower()
