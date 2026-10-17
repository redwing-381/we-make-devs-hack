"""Voyage embeddings with an on-disk cache.

The cache lets the seed reload offline and keeps us far from the free-tier rate limit (3 RPM / 10K TPM until a
card is added). Cache keys include model + dimension + input_type, so changing any of them re-embeds.
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from whygraph.config import REPO_ROOT, get_settings

InputType = Literal["document", "query"]
DEFAULT_CACHE = REPO_ROOT / "seed" / "embeddings_cache.json"
BATCH = 128


class Embedder:
    def __init__(self, cache_path: Path | None = DEFAULT_CACHE, client=None) -> None:
        s = get_settings()
        self.model, self.dim = s.embed_model, s.embed_dim
        self.cache_path = cache_path
        self._client = client
        self._cache: dict[str, list[float]] = {}
        if cache_path and cache_path.exists():
            self._cache = json.loads(cache_path.read_text(encoding="utf-8"))

    @property
    def client(self):
        if self._client is None:
            import voyageai

            self._client = voyageai.Client(api_key=get_settings().voyage_api_key)
        return self._client

    def _key(self, text: str, input_type: InputType) -> str:
        raw = f"{self.model}|{self.dim}|{input_type}|{text}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def embed(self, texts: list[str], input_type: InputType = "document") -> list[list[float]]:
        keys = [self._key(t, input_type) for t in texts]
        missing = list({k: t for k, t in zip(keys, texts, strict=True) if k not in self._cache}.items())
        for i in range(0, len(missing), BATCH):
            chunk = missing[i : i + BATCH]
            res = self.client.embed(
                [t for _, t in chunk],
                model=self.model,
                input_type=input_type,
                output_dimension=self.dim,
            )
            for (k, _), vec in zip(chunk, res.embeddings, strict=True):
                self._cache[k] = vec
        if missing:
            self.save()
        return [self._cache[k] for k in keys]

    def embed_one(self, text: str, input_type: InputType = "query") -> list[float]:
        return self.embed([text], input_type)[0]

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
