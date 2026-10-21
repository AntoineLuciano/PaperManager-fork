"""Coordinates for the chat's 3D structure cards (```structure blocks).

Two public sources, each fetched once and cached on disk:

- an RCSB entry by PDB id (``6SC6``): its mmCIF from files.rcsb.org;
- an AlphaFold DB prediction by UniProt accession (``P69905``): the model's
  mmCIF, whose URL the AFDB prediction API names. Its B-factor column holds
  pLDDT, which the card can colour by.

The browser never talks to these hosts itself; the frontend asks
``GET /knowledge-chat/structures`` and gets ``{name, format, data}``.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import httpx

PDB_ID = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
UNIPROT = re.compile(r"^(?:AF-)?([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-F1)?$")

RCSB_URL = "https://files.rcsb.org/download/{id}.cif"
AFDB_API = "https://alphafold.ebi.ac.uk/api/prediction/{acc}"
MAX_BYTES = 40 * 1024 * 1024
TIMEOUT = 30.0


class StructureError(ValueError):
    """Bad id, or the source does not have it."""


def cache_dir() -> Path:
    """``STRUCTURE_CACHE_DIR``, else ``/data/structures`` (the backend's volume), else a temp dir."""
    configured = os.environ.get("STRUCTURE_CACHE_DIR")
    candidates = [Path(configured)] if configured else []
    candidates += [Path("/data/structures"), Path(tempfile.gettempdir()) / "papermanager-structures"]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                return path
        except OSError:
            continue
    raise StructureError("No writable cache directory for structures.")


def _get(url: str) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        return client.get(url)


def _cached(name: str, fetch) -> str:
    path = cache_dir() / name
    if path.exists():
        return path.read_text()
    data = fetch()
    if len(data) > MAX_BYTES:
        raise StructureError(f"{name} is larger than {MAX_BYTES // 2**20} MB.")
    tmp = path.with_suffix(".part")
    tmp.write_text(data)
    tmp.replace(path)
    return data


def rcsb_entry(pdb_id: str) -> dict:
    if not PDB_ID.match(pdb_id or ""):
        raise StructureError(f"Not a PDB id: {pdb_id!r}")
    pid = pdb_id.upper()

    def fetch() -> str:
        r = _get(RCSB_URL.format(id=pid))
        if r.status_code != 200:
            raise StructureError(f"RCSB has no entry {pid} (HTTP {r.status_code}).")
        return r.text

    return {"name": pid, "format": "cif", "data": _cached(f"{pid}.cif", fetch)}


def alphafold_model(accession: str) -> dict:
    m = UNIPROT.match((accession or "").upper())
    if not m:
        raise StructureError(f"Not a UniProt accession: {accession!r}")
    acc = m.group(1)

    def fetch() -> str:
        r = _get(AFDB_API.format(acc=acc))
        if r.status_code != 200:
            raise StructureError(f"AlphaFold DB has no prediction for {acc} (HTTP {r.status_code}).")
        entries = r.json()
        url = next((e.get("cifUrl") for e in entries if isinstance(e, dict) and e.get("cifUrl")), None)
        if not url or not url.startswith("https://alphafold.ebi.ac.uk/"):
            raise StructureError(f"AlphaFold DB gave no model file for {acc}.")
        cif = _get(url)
        if cif.status_code != 200:
            raise StructureError(f"AlphaFold DB model download failed (HTTP {cif.status_code}).")
        return cif.text

    return {"name": f"AF-{acc}", "format": "cif", "data": _cached(f"AF-{acc}.cif", fetch)}
