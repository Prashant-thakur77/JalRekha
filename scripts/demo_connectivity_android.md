# Android connectivity-loss demo (manual)

Runs the same narrative as `scripts/demo_connectivity.py`, but from the Android
volunteer app. Keeps the backend the source of truth for `central.db`.

## Prereqs

- Backend running on LAN (e.g. `http://192.168.1.20:8000/api/`).
- Android device or emulator with the app installed.
- Seed applied (`python3 -m jalrekha.scripts.seed`).

## Steps

1. Open app → Settings → set backend base URL to your machine LAN IP.
2. Settings → confirm **Backend online** indicator is green.
3. Go to Sites → `Silverado Fixed Cam (USGS)` → note current alert level.
4. Create an online report: "Agua en cauce normal, subida leve." Expect success toast.
5. **Disconnect the device from wifi** (airplane mode or toggle wifi off).
6. Dashboard should show a red persistent banner *SIN CONECTIVIDAD — operación local activa* and a queue counter.
7. Create a second report: "El agua ya paso la marca critica y cortamos la ruta." App queues locally (Room DB).
8. Queue page: observe 1 pending item.
9. **Reconnect to wifi.**
10. Queue page → tap `Flush`. Observe counter return to 0; a green transient "Sincronizado" flash.
11. Backend /api/alerts now contains both reports + the escalated alert.

## Acceptance checklist

- [ ] Red banner visible during offline state.
- [ ] Queue counter increments for the offline-created report.
- [ ] Green flash on sync completion.
- [ ] `curl /api/reports` shows both reports after flush.
