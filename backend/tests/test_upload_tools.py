"""Source parsing for the MCP upload_pdf tool (no network, no Neo4j)."""
import pytest

from tools.upload_tools import entry_for


@pytest.mark.parametrize("source,expected", [
    ("2210.02747", {"arxiv": "2210.02747"}),
    ("arXiv:2210.02747v2", {"arxiv": "2210.02747v2"}),
    ("10.1038/s41586-024-07487-w", {"doi": "10.1038/s41586-024-07487-w"}),
    ("https://doi.org/10.1038/s41586-024-07487-w", {"doi": "10.1038/s41586-024-07487-w"}),
    ("10.1101/2024.11.19.624167", {"biorxiv": "10.1101/2024.11.19.624167"}),
    ("https://example.org/paper.pdf", {"pdf_url": "https://example.org/paper.pdf"}),
    ("/home/niklas/code/x.pdf", {"pdf_path": "/home/niklas/code/x.pdf"}),
])
def test_entry_for(source, expected):
    assert entry_for(source) == expected
