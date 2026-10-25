"""Region profiles (one per country) and river site graphs (one per basin).

A new region is one profile JSON plus one or more basin JSONs in ``data/``.
Nothing about Nepal or India is hard-coded in Python.

Travel time between two graph nodes, when the basin file does not give a
sourced value, is an **estimate**: along-river distance (great-circle distance
times a sinuosity factor) divided by a flood-wave celerity band. The method
string on every edge says which one was used, and the API passes it through.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).parent / "data"

# Flood-wave celerity band for large Himalayan rivers on the plains (m/s).
# Used only where no sourced travel time exists; always labelled an estimate.
CELERITY_MPS = {"min": 1.5, "typ": 2.5, "max": 3.5}
SINUOSITY = 1.3


class Bounds(BaseModel):
    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float

    def contains(self, lat: float, lng: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lng <= self.max_lon

    def as_guard_bounds(self) -> dict[str, float]:
        return self.model_dump()


class Language(BaseModel):
    code: str
    name: str
    native_name: str
    script: str
    cap_language: str
    tts: dict[str, Any] | None = None
    asr: dict[str, Any] | None = None
    needs_native_review: bool = False


class AuthorityRole(BaseModel):
    id: str
    name: str
    short: str | None = None
    level: str
    approves: list[str] = Field(default_factory=list)


class RegionProfile(BaseModel):
    id: str
    name: str
    country_code: str
    bounds: Bounds
    timezone: str
    languages: list[Language]
    public_languages: list[str]
    channels: list[str]
    authority_roles: list[AuthorityRole]
    levels: list[dict[str, Any]]
    level_basis: str
    alert_format: dict[str, Any]
    agencies: list[dict[str, Any]]
    admin_units: list[dict[str, Any]]

    def language(self, code: str) -> Language | None:
        return next((lang for lang in self.languages if lang.code == code), None)

    def role(self, role_id: str) -> AuthorityRole | None:
        return next((r for r in self.authority_roles if r.id == role_id), None)

    def summary(self) -> dict[str, Any]:
        return self.model_dump(include={"id", "name", "country_code", "languages", "channels", "authority_roles", "levels", "bounds", "public_languages"})


class BasinNode(BaseModel):
    id: str
    name: str
    country: str
    region_id: str
    admin_unit: str | None = None
    lat: float
    lng: float
    kind: str
    river: str
    agency: str | None = None
    site_id: str | None = None
    warning_m: float | None = None
    danger_m: float | None = None
    level_source: str | None = None
    coord_source: str | None = None
    gauge_note: str | None = None
    alert_targets: list[dict[str, Any]] = Field(default_factory=list)


class BasinEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    distance_km: float | None = None
    travel_time_h: dict[str, float] | None = None
    method: str | None = None
    source: str | None = None

    model_config = {"populate_by_name": True}

    def to_api(self) -> dict[str, Any]:
        d = self.model_dump(by_alias=True)
        return d


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Basin(BaseModel):
    id: str
    name: str
    countries: list[str]
    description: str = ""
    nodes: list[BasinNode]
    edges: list[BasinEdge]

    def model_post_init(self, _ctx: Any) -> None:
        by_id = {n.id: n for n in self.nodes}
        for e in self.edges:
            a, b = by_id[e.from_], by_id[e.to]
            if e.distance_km is None:
                e.distance_km = round(haversine_km(a.lat, a.lng, b.lat, b.lng) * SINUOSITY, 1)
            if e.travel_time_h is None:
                dist_m = e.distance_km * 1000
                e.travel_time_h = {
                    # fastest wave -> shortest time
                    "min": round(dist_m / CELERITY_MPS["max"] / 3600, 2),
                    "typ": round(dist_m / CELERITY_MPS["typ"] / 3600, 2),
                    "max": round(dist_m / CELERITY_MPS["min"] / 3600, 2),
                }
                e.method = (
                    f"estimate: great-circle distance x {SINUOSITY} sinuosity / flood-wave celerity "
                    f"{CELERITY_MPS['min']}-{CELERITY_MPS['max']} m/s"
                )
                e.source = e.source or "estimate (no published travel time found for this reach)"

    def node(self, node_id: str) -> BasinNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def node_for_site(self, site_id: str) -> BasinNode | None:
        return next((n for n in self.nodes if n.site_id == site_id), None)

    def downstream(self, from_node: str) -> list[dict[str, Any]]:
        """Every node reachable downstream of ``from_node`` with summed ETA bands."""
        out: list[dict[str, Any]] = []
        start = self.node(from_node)
        if start is None:
            return out
        stack: list[tuple[str, list[str], dict[str, float]]] = [(from_node, [from_node], {"min": 0.0, "typ": 0.0, "max": 0.0})]
        while stack:
            cur, path, eta = stack.pop()
            for e in (e for e in self.edges if e.from_ == cur):
                tt = e.travel_time_h or {"min": 0, "typ": 0, "max": 0}
                nxt = {k: round(eta[k] + tt[k], 2) for k in ("min", "typ", "max")}
                node = self.node(e.to)
                if node is None or e.to in path:
                    continue
                new_path = path + [e.to]
                out.append(
                    {
                        "node_id": node.id,
                        "name": node.name,
                        "country": node.country,
                        "region_id": node.region_id,
                        "admin_unit": node.admin_unit,
                        "eta_h": nxt,
                        "path": new_path,
                        "crosses_border": node.country != start.country,
                        "alert_targets": node.alert_targets,
                        "estimated": any(
                            (ed.method or "").startswith("estimate")
                            for ed in self.edges
                            if ed.from_ in new_path and ed.to in new_path
                        ),
                    }
                )
                stack.append((e.to, new_path, nxt))
        out.sort(key=lambda d: d["eta_h"]["typ"])
        return out

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "countries": self.countries,
            "description": self.description,
            "nodes": [n.model_dump() for n in self.nodes],
            "edges": [e.to_api() for e in self.edges],
        }


@lru_cache(maxsize=1)
def load_regions() -> dict[str, RegionProfile]:
    out = {}
    for p in sorted(DATA_DIR.glob("*.json")):
        prof = RegionProfile.model_validate(json.loads(p.read_text(encoding="utf-8")))
        out[prof.id] = prof
    return out


@lru_cache(maxsize=1)
def load_basins() -> dict[str, Basin]:
    out = {}
    for p in sorted((DATA_DIR / "rivers").glob("*.json")):
        basin = Basin.model_validate(json.loads(p.read_text(encoding="utf-8")))
        out[basin.id] = basin
    return out


def role_label(role_id: str | None) -> str:
    """Short human label for an authority role id ("ddma_control_room" -> "DDMA control room")."""
    for prof in load_regions().values():
        for r in prof.authority_roles:
            if r.id == role_id:
                return r.short or r.name
    return (role_id or "operator").replace("_", " ")


def region(region_id: str) -> RegionProfile | None:
    return load_regions().get(region_id)


def region_for_point(lat: float, lng: float) -> RegionProfile | None:
    # Smallest containing box wins (Nepal's box sits inside India's).
    hits = [r for r in load_regions().values() if r.bounds.contains(lat, lng)]
    if not hits:
        return None
    return min(hits, key=lambda r: (r.bounds.max_lat - r.bounds.min_lat) * (r.bounds.max_lon - r.bounds.min_lon))


def basin_for_site(site_id: str) -> tuple[Basin, BasinNode] | None:
    for b in load_basins().values():
        n = b.node_for_site(site_id)
        if n is not None:
            return b, n
    return None
