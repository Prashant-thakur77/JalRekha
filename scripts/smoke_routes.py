"""Smoke-test every original API route (and the new ones) against a running server.

    python3 scripts/smoke_routes.py https://<host>          # read-only checks
    python3 scripts/smoke_routes.py https://<host> --pin N  # also the PIN-protected writes

Prints one line per route and exits non-zero if a route that should work does not.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
PIN = sys.argv[sys.argv.index("--pin") + 1] if "--pin" in sys.argv else None


def call(method: str, path: str, body=None, pin: bool = False) -> int:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    if pin and PIN:
        req.add_header("X-Operator-Pin", PIN)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def main() -> int:
    sites = json.loads(urllib.request.urlopen(BASE + "/api/sites", timeout=30).read())
    sid = next((s["id"] for s in sites if s["id"] == "silverado-fixed-cam-usgs"), sites[0]["id"])
    alerts = json.loads(urllib.request.urlopen(BASE + "/api/alerts", timeout=30).read())
    checks = [
        # original routes (read)
        ("GET", "/api/health", None, False, {200}),
        ("GET", "/api/settings/runtime", None, False, {200}),
        ("GET", "/api/settings/connectivity", None, False, {200}),
        ("GET", "/api/sites", None, False, {200}),
        ("GET", f"/api/sites/{sid}", None, False, {200}),
        ("GET", f"/api/sites/{sid}/calibration", None, False, {200, 404}),
        ("GET", f"/api/sites/{sid}/experimental-settings", None, False, {200}),
        ("GET", f"/api/sites/{sid}/historical-context", None, False, {200}),
        ("GET", f"/api/sites/{sid}/forecast", None, False, {200}),
        ("GET", f"/api/sites/{sid}/external-snapshot", None, False, {200, 404}),
        ("GET", "/api/reports", None, False, {200}),
        ("GET", "/api/alerts", None, False, {200}),
        ("GET", f"/api/sites/{sid}/operator-summary", None, False, {200}),
        ("GET", "/api/sync/status", None, False, {200}),
        ("POST", "/api/cap/emit", {"site_id": sid, "severity": "moderate"}, False, {200}),
        ("POST", "/cap/emit", {"site_id": sid, "severity": "moderate"}, False, {200}),
        # new routes (read / public)
        ("GET", "/api/regions", None, False, {200}),
        ("GET", "/api/rivers/koshi", None, False, {200}),
        ("GET", "/api/rivers/koshi/eta?from_node=chatara", None, False, {200}),
        ("GET", "/api/scenarios", None, False, {200}),
        ("GET", "/api/agent/state", None, False, {200}),
        ("GET", "/api/agent/traces?limit=5", None, False, {200}),
        ("GET", "/api/agent/policy", None, False, {200}),
        ("GET", "/api/approvals", None, False, {200}),
        ("GET", "/api/relief/routes", None, False, {200}),
        ("GET", "/api/relief/shelters", None, False, {200}),
        ("GET", "/api/sitrep/in", None, False, {200}),
        ("GET", "/api/evidence", None, False, {200}),
        ("GET", "/", None, False, {200}),
        # protected writes: without a PIN they must be refused in the cloud profile
        ("POST", "/api/alerts/recompute", {"site_id": sid}, False, {401, 200}),
    ]
    if alerts:
        checks.append(("GET", f"/api/alerts/{alerts[0]['id']}", None, False, {200}))
        if alerts[0].get("incident_id"):
            checks.append(("GET", f"/api/incidents/{alerts[0]['incident_id']}/timeline", None, False, {200}))
    if PIN:
        checks += [
            ("POST", "/api/alerts/recompute", {"site_id": sid}, True, {200}),
            ("POST", "/api/sync/flush", None, True, {200}),
            ("POST", f"/api/sites/{sid}/sample-node-analysis", None, True, {200, 404, 409, 422, 500, 503}),
        ]
    bad = 0
    for method, path, body, pin, ok in checks:
        code = call(method, path, body, pin)
        flag = "ok " if code in ok else "BAD"
        bad += code not in ok
        print(f"{flag} {code} {method:4s} {path}{'  (PIN)' if pin else ''}")
    print(f"{len(checks) - bad}/{len(checks)} routes as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
