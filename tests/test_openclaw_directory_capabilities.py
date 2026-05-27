from fastapi.testclient import TestClient

import server


class EmptyDirectoryBridge:
    async def directory_peers(self, channel="whatsapp", query=None, limit=50, account=None):
        return {"success": True, "raw": {"json": []}, "summary": "ok"}

    async def directory_groups(self, channel="whatsapp", query=None, limit=50, account=None):
        return {"success": True, "raw": {"json": []}, "summary": "ok"}


def test_empty_peers_and_groups_do_not_break_endpoints(monkeypatch):
    monkeypatch.setattr(server, "openclaw_bridge", EmptyDirectoryBridge())
    client = TestClient(server.app)

    peers = client.get("/api/openclaw/directory/peers").json()
    groups = client.get("/api/openclaw/directory/groups").json()

    assert peers["success"] is True
    assert groups["success"] is True
    assert peers["data"]["raw"]["json"] == []
    assert groups["data"]["raw"]["json"] == []
