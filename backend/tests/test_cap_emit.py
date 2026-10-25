from __future__ import annotations

from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from jalrekha.main import app
from jalrekha.services.cap import CAP_NS, build_cap_xml


def test_cap_xml_has_required_oasis_and_sinagir_fields():
    xml = build_cap_xml(
        {
            "site_id": "test-site",
            "lat": -34.6,
            "lon": -58.38,
            "severity": "severe",
            "headline": "Alerta por inundacion en zona baja",
            "instruction": "Evitar cruces bajos y esperar instrucciones de Defensa Civil.",
            "summary": "Nodo y reporte ciudadano coinciden.",
        }
    )
    root = ET.fromstring(xml)
    ns = {"cap": CAP_NS}
    assert root.tag == f"{{{CAP_NS}}}alert"
    assert root.findtext("cap:status", namespaces=ns) == "Actual"
    assert root.findtext("cap:info/cap:severity", namespaces=ns) == "Severe"
    assert root.findtext("cap:info/cap:language", namespaces=ns) == "es-AR"
    assert root.findtext("cap:info/cap:area/cap:geocode/cap:valueName", namespaces=ns) == "SINAGIR/SINAME sitio"
    assert root.findtext("cap:info/cap:parameter/cap:valueName", namespaces=ns) == "node-signature-sha256"


def test_cap_emit_endpoint_returns_xml():
    client = TestClient(app)
    response = client.post("/cap/emit", json={"site_id": "test-site", "severity": "moderate"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/cap+xml")
    assert ET.fromstring(response.text).findtext(f"{{{CAP_NS}}}info/{{{CAP_NS}}}severity") == "Moderate"
