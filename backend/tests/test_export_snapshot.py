import io
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from starlette.datastructures import UploadFile

from routers.export import export_snapshot, import_snapshot


class _FakeResult:
    def consume(self):
        return None


class _FakeReadSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query: str):
        compact = " ".join(query.split())
        if "RETURN elementId(n) AS export_id" in compact:
            # User accounts (password hashes, API keys) are never exported.
            assert "WHERE NOT any(l IN labels(n) WHERE l IN ['User'])" in compact
            return [
                {
                    "export_id": "node-1",
                    "labels": ["Paper", "Imported"],
                    "props": {
                        "id": "paper-1",
                        "title": "Snapshot Test",
                        "raw_text": "full raw text",
                        "drive_file_id": "drive-123",
                        "bookmarked": True,
                        "anthropic_api_key": "must-not-leak",
                    },
                }
            ]
        if "MATCH (a)-[r]->(b) RETURN elementId(r) AS export_id" in compact:
            return [
                {
                    "export_id": "rel-1",
                    "start_export_id": "node-1",
                    "end_export_id": "node-2",
                    "type": "AUTHORED_BY",
                    "props": {"confidence": 0.75, "source": "manual"},
                }
            ]
        raise AssertionError(f"Unexpected query: {query}")


class _FakeReadDriver:
    def session(self):
        return _FakeReadSession()


class _FakeWriteTx:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((query, params))
        return _FakeResult()


class _FakeWriteSession:
    def __init__(self, tx: _FakeWriteTx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_write(self, fn):
        return fn(self.tx)


class _FakeWriteDriver:
    def __init__(self):
        self.tx = _FakeWriteTx()

    def session(self):
        return _FakeWriteSession(self.tx)


def test_export_snapshot_preserves_all_properties():
    response = export_snapshot(driver=_FakeReadDriver())
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["format"] == "papermanager-graph-snapshot"
    assert payload["nodes"][0]["labels"] == ["Paper", "Imported"]
    assert payload["nodes"][0]["properties"]["raw_text"] == "full raw text"
    assert payload["nodes"][0]["properties"]["drive_file_id"] == "drive-123"
    assert "anthropic_api_key" not in payload["nodes"][0]["properties"]
    assert payload["relationships"][0]["properties"] == {"confidence": 0.75, "source": "manual"}


async def test_import_snapshot_recreates_nodes_and_relationships_with_all_properties():
    driver = _FakeWriteDriver()
    upload = UploadFile(
        filename="snapshot.json",
        file=io.BytesIO(
            json.dumps(
                {
                    "format": "papermanager-graph-snapshot",
                    "version": 1,
                    "nodes": [
                        {
                            "export_id": "node-1",
                            "labels": ["Paper", "Imported"],
                            "properties": {
                                "id": "paper-1",
                                "title": "Snapshot Test",
                                "raw_text": "full raw text",
                                "drive_file_id": "drive-123",
                            },
                        },
                        {
                            "export_id": "node-2",
                            "labels": ["Person"],
                            "properties": {"id": "person-1", "name": "Ada"},
                        },
                    ],
                    "relationships": [
                        {
                            "export_id": "rel-1",
                            "start_export_id": "node-1",
                            "end_export_id": "node-2",
                            "type": "AUTHORED_BY",
                            "properties": {"confidence": 0.75},
                        }
                    ],
                }
            ).encode("utf-8")
        ),
    )

    with patch("routers.export.is_user_admin", return_value=True):
        result = await import_snapshot(file=upload, replace=True, current_user="admin", driver=driver)

    assert result["replaced"] is True
    assert result["imported"]["nodes"] == 2
    assert result["imported"]["relationships"] == 1
    queries = [query for query, _ in driver.tx.calls]
    params = [call_params for _, call_params in driver.tx.calls]

    # Replacing clears the graph but keeps the user accounts.
    assert queries[0].strip() == "MATCH (n) WHERE NOT n:User DETACH DELETE n"
    assert any("SET n = $properties" in query for query in queries)
    assert any("SET n.__pm_export_id = $export_id" in query for query in queries)
    assert any("MATCH (a:`__PMImport`" in query for query in queries)
    assert any("SET r = $properties" in query for query in queries)
    assert any(call.get("properties", {}).get("raw_text") == "full raw text" for call in params)
    assert any(call.get("properties", {}).get("drive_file_id") == "drive-123" for call in params)


async def test_import_snapshot_requires_admin():
    upload = UploadFile(filename="snapshot.json", file=io.BytesIO(b"{}"))
    with patch("routers.export.is_user_admin", return_value=False):
        with pytest.raises(HTTPException) as exc:
            await import_snapshot(file=upload, replace=True, current_user="reader", driver=_FakeWriteDriver())
    assert exc.value.status_code == 403
