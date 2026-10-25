"""BAAI/bge-small-en-v1.5 on CPU: 384-dim unit vectors for papers and queries.

Runs through ``transformers`` + ``torch``, which the backend already has for Docling, so
the explorer needs no new dependency and no API key. The model (~130 MB) is downloaded
once into ``<data dir>/models``. Short queries get bge's retrieval instruction, as the
model card recommends; documents and long queries (a pasted abstract) do not.
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

log = logging.getLogger(__name__)

MODEL = os.environ.get("CONFERENCE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
DIM = 384
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_lock = threading.Lock()
# Fast (Rust) tokenizers refuse concurrent use from two threads ("Already borrowed");
# a build and a query can tokenise at the same time, so tokenising is serialised.
_tok_lock = threading.Lock()
_model = None
_tok = None


def _load():
    global _model, _tok
    if _model is not None:
        return _tok, _model
    with _lock:
        if _model is None:
            import torch
            from transformers import AutoModel, AutoTokenizer

            from services.conferences.store import data_dir

            cache = str(data_dir() / "models")
            threads = int(os.environ.get("CONFERENCE_EMBED_THREADS", "4"))
            torch.set_num_threads(max(1, threads))
            log.info("Loading %s (cache %s, %d threads)", MODEL, cache, threads)
            _tok = AutoTokenizer.from_pretrained(MODEL, cache_dir=cache)
            _model = AutoModel.from_pretrained(MODEL, cache_dir=cache).eval()
    return _tok, _model


def ready() -> bool:
    return _model is not None


def embed(texts: list[str], max_length: int = 256, batch: int = 64, progress=None) -> np.ndarray:
    """Unit-length CLS embeddings, shape (len(texts), 384), float32.

    Texts are processed shortest first so a batch pads to similar lengths, which on
    CPU is several times faster than the original order."""
    import torch

    tok, model = _load()
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    done = 0
    with torch.inference_mode():
        for s in range(0, len(order), batch):
            idx = order[s:s + batch]
            with _tok_lock:
                enc = tok([texts[i] or " " for i in idx], padding=True, truncation=True,
                          max_length=max_length, return_tensors="pt")
            cls = model(**enc).last_hidden_state[:, 0]
            cls = torch.nn.functional.normalize(cls, dim=-1)
            out[idx] = cls.numpy()
            done += len(idx)
            if progress:
                progress(done, len(texts))
    return out


def embed_query(text: str) -> np.ndarray:
    text = text.strip()
    q = _QUERY_PREFIX + text if len(text.split()) <= 24 else text
    return embed([q], max_length=512)[0]
