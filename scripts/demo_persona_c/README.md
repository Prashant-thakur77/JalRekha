# Persona C demo escalada — runbook

3-acto curl-driven escalada para grabar el Nodo Central + fusion engine en vivo.

## Requisitos

```bash
# backend con demo-inject habilitado (correr desde la raíz del repo)
export JALREKHA_ENABLE_DEMO_INJECT=1
cd "$(git rev-parse --show-toplevel)/backend"
PYTHONPATH=src python3 -m jalrekha.scripts.seed
PYTHONPATH=src python3 -m uvicorn jalrekha.main:app --host 127.0.0.1 --port 8000
```

Frontend dev server en `:5173`, ollama corriendo con `gemma4:e2b` o `gemma4:26b`.

## Toma

```bash
bash 00_reset.sh                 # DB limpia (verde)
bash 01_volunteer_verde.sh           # -> level=green, score ~0.35
sleep 8
bash 02_node_amarillo.sh     # -> level=yellow, score ~0.50
sleep 8
bash 03_fusion_rojo.sh           # -> level=red, score >=0.82, CAP XML emitido
```

Tras cada script, el dashboard `http://127.0.0.1:5173` debe reflejar el nuevo
`FusedAlert` (RiskBanner cambia de color, tiles de `Fusion de senales` se actualizan,
timeline gana un punto).

## Targets esperados (level_from_score)

| Acto | Source | Severity raw | Fused score | Level |
|------|--------|--------------|-------------|-------|
| 1    | JalRekha Volunteer mild | ~0.20 (unknown+ningun trigger) | ~0.20-0.35 | green |
| 2    | JalRekha Node synthetic | 0.52 | ~0.50 | yellow |
| 3    | 3x JalRekha Volunteer critical | 0.92 + corroboracion + node previo | >=0.82 | red |

Si Acto 3 cae en orange (0.62-0.82), reforzar transcript de R1 con "marca critica
del puente desbordada".

## Override variables

- `API` — base URL backend (default `http://127.0.0.1:8000`)
- `SITE` — site_id (default `puente-arroyo-01`)
- `BACKEND_DIR` — solo para `00_reset.sh` (default: `<repo-root>/backend`, resuelto desde la ubicación del script)
