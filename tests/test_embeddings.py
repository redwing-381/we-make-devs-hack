from types import SimpleNamespace

from whygraph.embeddings import Embedder


class FakeVoyage:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, model, input_type, output_dimension):
        self.calls += 1
        return SimpleNamespace(embeddings=[[float(len(t))] * 2 for t in texts])


def test_cache_avoids_repeat_calls(tmp_path):
    fake = FakeVoyage()
    emb = Embedder(cache_path=tmp_path / "cache.json", client=fake)
    first = emb.embed(["a", "bb", "a"])
    assert first == [[1.0, 1.0], [2.0, 2.0], [1.0, 1.0]]
    assert fake.calls == 1

    reloaded = Embedder(cache_path=tmp_path / "cache.json", client=fake)
    assert reloaded.embed(["bb"]) == [[2.0, 2.0]]
    assert fake.calls == 1  # served from disk


def test_query_and_document_are_cached_separately(tmp_path):
    fake = FakeVoyage()
    emb = Embedder(cache_path=tmp_path / "c.json", client=fake)
    emb.embed(["x"], "document")
    emb.embed(["x"], "query")
    assert fake.calls == 2
