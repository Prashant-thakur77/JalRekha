from __future__ import annotations

import asyncio

from jalrekha import mcp_server


def test_mcp_tools_cannot_approve_or_send_alerts():
    tools = asyncio.run(mcp_server.server.list_tools())
    names = {t.name for t in tools}
    assert {"river_status", "downstream_eta", "explain_reading", "pending_alerts", "run_replay", "cloud_insights"} <= names
    assert not any(w in n for n in names for w in ("approve", "decision", "send", "dispatch", "siren"))
    writes = [t.name for t in tools if not (t.annotations and t.annotations.read_only_hint)]
    assert writes == ["run_replay"]  # the only tool that changes anything starts a replay
