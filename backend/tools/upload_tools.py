import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

from db.connection import get_driver
from services.pdf_import import api_headers, import_entry, project_id_for

# Host directory bind-mounted read-only at the same path in the backend container
# (docker-compose.yml), so a host path given to upload_pdf resolves unchanged.
HOST_IMPORT_ROOT = os.environ.get("HOST_IMPORT_ROOT", "")

ARXIV_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)$", re.IGNORECASE)
DOI_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)$", re.IGNORECASE)


def entry_for(source: str) -> dict:
    """Manifest entry (see services.pdf_import) for a path, URL, arXiv id or DOI."""
    s = source.strip()
    if m := ARXIV_RE.match(s):
        return {"arxiv": m.group(1)}
    if m := DOI_RE.match(s):
        doi = m.group(1)
        # bioRxiv/medRxiv DOIs are fetched from the preprint server, others via Unpaywall
        return {"biorxiv": doi} if doi.startswith(("10.1101/", "10.64898/")) else {"doi": doi}
    if s.startswith(("http://", "https://")):
        return {"pdf_url": s}
    return {"pdf_path": os.path.abspath(os.path.expanduser(s))}


def register(mcp: FastMCP):
    @mcp.tool()
    def upload_pdf(source: str, project: str = "") -> dict:
        """Add a paper WITH its PDF through the full upload pipeline (same as a
        drag-and-drop upload: full text, Drive, AI summary, topics, claims,
        references, figures). Takes a few minutes per paper.

        source is one of:
          - an absolute local PDF path under the host import root
            (HOST_IMPORT_ROOT, e.g. /home/niklas/code/...),
          - a direct PDF URL,
          - an arXiv id ("2210.02747" or "arXiv:2210.02747"),
          - a DOI ("10.1038/..." or a doi.org URL); bioRxiv DOIs are fetched from
            bioRxiv, others via Unpaywall, falling back to metadata-only.
        project is an optional project name or id to link the paper to.

        If the paper is already in the library with full text it is only linked.
        Returns status (uploaded | already-in-library | already-complete |
        metadata-only | no-pdf | error), the paper id and title."""
        entry = entry_for(source)
        path = entry.get("pdf_path")
        if path and not os.path.isfile(path):
            hint = (f"Only files under {HOST_IMPORT_ROOT} are visible to the server."
                    if HOST_IMPORT_ROOT else "No host directory is mounted (HOST_IMPORT_ROOT unset).")
            return {"status": "error", "error": f"File not found: {path}. {hint}"}

        driver = get_driver()
        project_id = ""
        if project:
            project_id = project_id_for(driver, project)
            if not project_id:
                return {"status": "error", "error": f"Project not found: {project}"}

        with httpx.Client() as client:
            # Short rate-limit backoff: a tool call should not sit for many minutes
            res = import_entry(client, api_headers(), driver, entry, project_id,
                               attempts=2, backoff=30)
        res.pop("at", None)
        return res
