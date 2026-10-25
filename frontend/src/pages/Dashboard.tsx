/* Dashboard.tsx — Persona C Backend & Fusion command center.
 *
 * Single-view "tablero de comando" optimized for 1440x900 screen recording:
 *
 *   ┌─────────────────────────────────────────────────────────────────┐
 *   │ RiskBanner (level · score · site · summary)                    │   <- 5-second read
 *   ├──────────────────────────────────────┬──────────────────────────┤
 *   │ Fusión de señales (3 tiles)          │ Estado CAP v1.2          │
 *   │ Frame de evidencia                   │ Acciones del operador    │
 *   │ Razonamiento de Gemma                │ Cola offline · sync      │
 *   │ Traza de auditoría determinística    │                          │
 *   ├──────────────────────────────────────┴──────────────────────────┤
 *   │ Línea de tiempo del incidente                                  │
 *   └─────────────────────────────────────────────────────────────────┘
 *
 * When there is no active alert from the backend, we render a clearly-labeled
 * demo-safe sample state so the recording always has something to show.
 * The demo state is rendered with a "DEMO · sample state" badge — this is
 * not a fake backend, it's clearly-labeled mock data for screen capture.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Database, TrendingUp } from 'lucide-react';
import { useAppStore } from '../store';
import type { FusedAlert, HistoricalContextHit, Site, SiteForecast } from '../store';
import {
  ActionRail,
  AuditTrace,
  CapStatusCard,
  EmptyCommandCenter,
  EvidencePanel,
  GemmaReasoning,
  IncidentTimeline,
  OfflineSyncCard,
  RiskBanner,
  SectionPanel,
  SignalFusionRow,
} from '../components/CommandCenter';

const CENTRAL_NODE_MODEL = 'claude-opus-5-5';

const EVIDENCE_BY_LEVEL: Record<FusedAlert['level'], { frameUrl: string; frameLabel: string; description: string; confidence: number }> = {
  green: {
    frameUrl: '/demo_persona_c/nominal.png',
    frameLabel: 'cv_node/nominal_frame.png',
    description:
      'Calm channel conditions. Water remains low against the retaining wall, with dry grass and clear banks visible across the scene.',
    confidence: 0.82,
  },
  yellow: {
    frameUrl: '/demo_persona_c/watch.png',
    frameLabel: 'cv_node/watch_frame.png',
    description:
      'Water level has risen across the channel and surface flow is stronger, but the bank and access path remain mostly clear.',
    confidence: 0.84,
  },
  orange: {
    frameUrl: '/demo_persona_c/watch.png',
    frameLabel: 'cv_node/watch_frame.png',
    description:
      'Elevated water covers most of the channel and is approaching the bank. Continued rise would compromise the access path.',
    confidence: 0.86,
  },
  red: {
    frameUrl: '/demo_persona_c/critical.png',
    frameLabel: 'cv_node/critical_frame.png',
    description:
      'Floodwater has overtopped the bank and spread into the foreground access area. Street-level structures and low ground are exposed.',
    confidence: 0.91,
  },
};
import type {
  ActionCall,
  AuditEntry,
  SignalInput,
  TimelineEvent,
} from '../components/CommandCenter';

// ──────────────────────────────────────────────────────────────────────────
// Demo-safe sample state. Used only when the backend has no active alert.
// Clearly labeled in the UI with a "DEMO · sample state" badge. This is
// not a hidden mock — it's the screen-recording fallback.
// ──────────────────────────────────────────────────────────────────────────
/** Loose shape of the decision-trace-v2 JSON; every field is validated where it is read. */
type RawRecord = Record<string, unknown>;
interface LiveTrace {
  evidence?: RawRecord[];
  rules_fired?: unknown[];
  historical_context?: { hits?: RawRecord[] };
  forecast?: RawRecord & { projected_points?: RawRecord[]; uncertainty_band?: RawRecord[] };
}

/** Wall-clock read kept outside render-time memos (react-hooks/purity). */
const nowMs = () => Date.now();

const DEMO_SITE: Site = {
  id: 'silverado-fixed-cam-usgs',
  name: 'Silverado Fixed Cam (USGS)',
  region: 'Demo · public USGS clip · sample state',
  lat: 33.74,
  lng: -117.65,
  description:
    'Bundled repo site. Serves as E2E reference for the OpenCV and agent pipeline on a real clip.',
  is_active: true,
};

const DEMO_ALERT: FusedAlert = {
  id: 9001,
  site_id: 'silverado-fixed-cam-usgs',
  level: 'red',
  score: 0.87,
  summary:
    'Critical line crossed at t=078s. Corroborated by brigade report and 68% 12h rain probability.',
  created_at: new Date(Date.now() - 1000 * 60 * 3).toISOString(),
  trigger_source: 'fused',
  reasoning_summary:
    'The mid-lower band of the frame went from dry to turbid over 12 consecutive frames. ' +
    'Rise velocity 0.0034/frame exceeds internal threshold (0.0020). ' +
    'Volunteer report confirms crossing of the critical mark. Confidence 78%.',
  reasoning_chain: JSON.stringify([
    'observation.crossed_critical_line = true (waterline_ratio 0.42 > 0.30)',
    'rise_velocity 0.0034/frame > threshold 0.0020 → sustained rise signal',
    'volunteer report lexically matches "crossed the critical mark"',
    'hydromet 12h probability = 68% → corroborates event hypothesis',
    'fused_score = 0.87 -> RED level, emit_cap_xml enabled',
  ]),
  reasoning_model: CENTRAL_NODE_MODEL,
};

const DEMO_FUSION: SignalInput[] = [
  { source: 'camera',    score: 0.87, status: 'ok',    detail: 'Crossed critical line · 126 frames analyzed', ageSeconds: 8 },
  { source: 'volunteer', score: 0.62, status: 'ok',    detail: '"Water already crossed the critical mark and carries mud" · 1 report', ageSeconds: 92 },
  { source: 'hydromet',  score: 0.45, status: 'ok',    detail: 'Open-Meteo · 12.4 mm/h · prob 12h 68%',          ageSeconds: 240 },
];

const DEMO_AUDIT: AuditEntry[] = [
  { rule: 'RULE_CRITICAL_LINE_CROSSED',     outcome: 'fired',     detail: 'CV node observation: waterline_ratio 0.42 crossed calibrated line y=120.' },
  { rule: 'RULE_RISE_VELOCITY',             outcome: 'fired',     detail: 'rise_velocity 0.0034/frame > threshold 0.0020/frame.' },
  { rule: 'RULE_VOLUNTEER_CORROBORATION',   outcome: 'fired',     detail: '1 volunteer report classified by Claude with urgency=high in last 5 min.' },
  { rule: 'RULE_HYDROMET_AGREEMENT',        outcome: 'fired',     detail: 'Open-Meteo 12h probability 68% exceeds threshold 50%.' },
  { rule: 'RULE_DUPLICATE_SUPPRESSION',     outcome: 'not_fired', detail: 'No prior active alert found for this site in 30 min window.' },
  { rule: 'RULE_MANUAL_OVERRIDE',           outcome: 'not_fired', detail: 'Operator did not apply manual override.' },
];

const DEMO_TIMELINE_FACTORY = (): TimelineEvent[] => {
  const now = Date.now();
  const t = (deltaSec: number) => new Date(now + deltaSec * 1000).toISOString();
  return [
    { at: t(-240), kind: 'detect',    label: 'CV detection',            detail: 'Silverado node: rise_velocity > threshold', done: true },
    { at: t(-185), kind: 'volunteer', label: 'Volunteer report',       detail: 'Brigade member Maria G. (JalRekha Volunteer Android)', done: true },
    { at: t(-145), kind: 'fuse',      label: 'Signal fusion',          detail: 'fused_score = 0.87 · level = red',        done: true },
    { at: t(-90),  kind: 'cap',       label: 'CAP v1.2 emitted',       detail: 'receipt CAP-2026-05-16-0042',             done: true },
    { at: t(-70),  kind: 'siren',     label: 'Siren triggered',        detail: 'GPIO relay low zone',                     done: true },
    { at: t(-30),  kind: 'notify',    label: 'Civil Defense notified', detail: 'Municipal webhook acknowledged',          done: true },
    { at: t(60),   kind: 'sync',      label: 'Next CV window',         detail: 'Automatic re-analysis in 60s',            done: false },
  ];
};

const DEMO_CAP = {
  status: 'emitted' as const,
  lastEmit: new Date(Date.now() - 1000 * 90).toLocaleString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', day: '2-digit', month: '2-digit',
  }),
  receiptId: 'CAP-2026-05-16-0042',
  schemaVersion: 'CAP v1.2',
  recipientCount: 3,
};

// ──────────────────────────────────────────────────────────────────────────
// Dashboard (Persona C command center)
// ──────────────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const {
    sites,
    alerts,
    fetchSites,
    fetchAlerts,
    fetchSiteExperimentalSettings,
    updateSiteExperimentalSettings,
    fetchSiteHistoricalContext,
    fetchSiteForecast,
    isOnline,
    queueCount,
    siteSettings,
    siteForecasts,
    siteHistoricalContext,
  } = useAppStore();

  // Local state for the action rail. The buttons fire deterministic UI feedback
  // so the recording shows the loop closing — they do NOT silently invent
  // backend behavior; clicking dispatches an explicit "demo action" log line.
  const [actionState, setActionState] = useState<Record<ActionCall['fn'], { busy: boolean }>>({
    emit_cap_xml:         { busy: false },
    trigger_siren:        { busy: false },
    send_lora_alert:      { busy: false },
    notify_civil_defense: { busy: false },
  });
  const [actionLog, setActionLog] = useState<string[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>(() => DEMO_TIMELINE_FACTORY());

  useEffect(() => {
    if (isOnline) {
      fetchSites();
      fetchAlerts();
    }
  }, [fetchSites, fetchAlerts, isOnline]);

  // Top-priority alert: the highest-level live alert, falling back to demo.
  const { activeAlert, activeSite, isDemo } = useMemo(() => {
    if (alerts.length > 0) {
      const order: Record<FusedAlert['level'], number> = { red: 0, orange: 1, yellow: 2, green: 3 };
      const sorted = [...alerts].sort((a, b) => order[a.level] - order[b.level] || b.score - a.score);
      const top = sorted[0];
      const site = sites.find((s) => s.id === top.site_id) ?? null;
      return { activeAlert: top, activeSite: site, isDemo: false };
    }
    return { activeAlert: DEMO_ALERT, activeSite: DEMO_SITE, isDemo: true };
  }, [alerts, sites]);

  const activeSiteId = activeSite?.id ?? activeAlert.site_id;
  const currentSettings = siteSettings[activeSiteId];
  const historicalContextEnabled = Boolean(currentSettings?.historical_context_enabled);

  useEffect(() => {
    if (!isOnline || !activeSiteId) return;
    fetchSiteExperimentalSettings(activeSiteId);
    fetchSiteForecast(activeSiteId);
  }, [activeSiteId, fetchSiteExperimentalSettings, fetchSiteForecast, isOnline]);

  useEffect(() => {
    if (!isOnline || !activeSiteId || !historicalContextEnabled) return;
    const query = `${activeAlert.level} ${activeAlert.trigger_source ?? ''} ${activeAlert.summary ?? ''}`;
    fetchSiteHistoricalContext(activeSiteId, { waterLevel: activeAlert.score, query });
  }, [activeAlert.level, activeAlert.score, activeAlert.summary, activeAlert.trigger_source, activeSiteId, fetchSiteHistoricalContext, historicalContextEnabled, isOnline]);

  const reasoningChain = useMemo(() => {
    if (!activeAlert?.reasoning_chain) return undefined;
    try {
      const parsed = JSON.parse(activeAlert.reasoning_chain);
      return Array.isArray(parsed) ? parsed.map(String) : undefined;
    } catch {
      return undefined;
    }
  }, [activeAlert]);

  // Parse the live decision_trace (decision-trace-v2 schema) once. The fusion
  // tiles and audit panel both consume this — for demo fallback (no live alert)
  // we still use DEMO_FUSION / DEMO_AUDIT.
  const liveTrace = useMemo<LiveTrace | null>(() => {
    if (isDemo || !activeAlert?.decision_trace) return null;
    try { return JSON.parse(activeAlert.decision_trace) as LiveTrace; } catch { return null; }
  }, [activeAlert, isDemo]);

  const liveSignals = useMemo<SignalInput[]>(() => {
    if (!liveTrace?.evidence) return DEMO_FUSION;
    const ev: RawRecord[] = Array.isArray(liveTrace.evidence) ? liveTrace.evidence : [];
    type Best = { score: number; weighted: number; summary: string; observed: number };
    const best: Record<'camera'|'volunteer'|'hydromet', Best | null> = {
      camera: null, volunteer: null, hydromet: null,
    };
    for (const e of ev) {
      const src = e.source === 'node' ? 'camera' : (e.source as 'volunteer'|'hydromet'|'camera');
      if (!(src in best)) continue;
      const w = Number(e.weighted_score) || 0;
      const prev = best[src];
      if (!prev || w > prev.weighted) {
        best[src] = {
          score: Number(e.raw_score) || 0,
          weighted: w,
          summary: String(e.summary || '').slice(0, 140),
          observed: Date.parse(String(e.observed_at)) || nowMs(),
        };
      }
    }
    const now = nowMs();
    const MODEL_BY_SRC: Record<'camera'|'volunteer'|'hydromet', string> = {
      camera:    'gemma4:e4b',
      volunteer: 'gemma4:e2b',
      hydromet:  'open-meteo',
    };
    return (['camera','volunteer','hydromet'] as const).map((src) => {
      const b = best[src];
      if (!b) return {
        source: src, score: 0, status: 'missing' as const,
        detail: 'no signal in 45 min window', model: MODEL_BY_SRC[src],
      };
      const ageSec = Math.max(0, Math.round((now - b.observed) / 1000));
      return {
        source: src,
        score: b.score,
        status: ageSec > 1800 ? ('stale' as const) : ('ok' as const),
        detail: b.summary || `score=${b.score.toFixed(2)}`,
        ageSeconds: ageSec,
        model: MODEL_BY_SRC[src],
      };
    });
  }, [liveTrace]);

  const liveAudit = useMemo<AuditEntry[]>(() => {
    if (!liveTrace?.rules_fired) return DEMO_AUDIT;
    const fired: string[] = Array.isArray(liveTrace.rules_fired) ? liveTrace.rules_fired.map(String) : [];
    const has = (needle: string) => fired.some((r) => r.includes(needle));
    const entries: AuditEntry[] = [
      { rule: 'RULE_NODE_CRITICAL_LINE',     outcome: has('node_critical_line_crossed') ? 'fired' : 'not_fired', detail: 'Fixed camera crossed calibrated critical line.' },
      { rule: 'RULE_NODE_FAST_RISE',         outcome: has('node_fast_rise') ? 'fired' : 'not_fired',           detail: 'rise_velocity exceeds threshold 0.08/frame.' },
      { rule: 'RULE_VOLUNTEER_MARK_EXCEEDED', outcome: has('volunteer_mark_exceeded') ? 'fired' : 'not_fired', detail: 'Human report confirms water mark exceeded.' },
      { rule: 'RULE_VOLUNTEER_ROAD_CUT',     outcome: has('volunteer_road_cut') ? 'fired' : 'not_fired',       detail: 'Citizen report: road cut / impassable.' },
      { rule: 'RULE_VOLUNTEER_HOMES_AFFECTED', outcome: has('volunteer_homes_affected') ? 'fired' : 'not_fired', detail: 'Citizen report: water inside homes.' },
      { rule: 'RULE_CORROBORATION_MULTI_SRC', outcome: has('corroboration_sources') ? 'fired' : 'not_fired',   detail: 'Two or more sources with score >= 0.35.' },
      { rule: 'RULE_TWO_MEDIUM_TO_ORANGE',   outcome: has('two_medium_sources_escalate_to_orange') ? 'fired' : 'not_fired', detail: 'Two sources in mid band -> escalated to orange.' },
    ];
    return entries;
  }, [liveTrace]);

  const historicalContext = useMemo<HistoricalContextHit[]>(() => {
    const stored = siteHistoricalContext[activeSiteId];
    if (historicalContextEnabled && stored?.length) return stored;
    const hits = liveTrace?.historical_context?.hits;
    if (Array.isArray(hits) && hits.length > 0) {
      return hits.map((hit: RawRecord) => ({
        id: Number(hit.id ?? 0),
        title: String(hit.title ?? 'Historical context'),
        source: String(hit.source ?? 'edge-rag-sqlite'),
        summary: String(hit.summary ?? ''),
        threshold_level: typeof hit.threshold_level === 'number' ? hit.threshold_level : null,
        jurisdiction: hit.jurisdiction ? String(hit.jurisdiction) : null,
        effective_from: hit.effective_from ? String(hit.effective_from) : null,
        effective_to: hit.effective_to ? String(hit.effective_to) : null,
        source_uri: hit.source_uri ? String(hit.source_uri) : null,
        rank: Number(hit.rank ?? 0),
      }));
    }
    if (!historicalContextEnabled) return [];
    return [
      {
        id: 0,
        title: '2015 flood analogue',
        source: 'edge-rag-sqlite',
        summary: 'At a similar bridge mark, low access roads were cut within roughly 45 minutes.',
        threshold_level: 0.78,
        jurisdiction: 'demo',
        rank: 0.75,
      },
      {
        id: 0,
        title: 'Evacuation trigger',
        source: 'civil_defense_manual',
        summary: 'Fast rise above the local mark requires early evacuation messaging before overtopping.',
        threshold_level: 0.7,
        jurisdiction: 'demo',
        rank: 0.72,
      },
    ];
  }, [activeSiteId, historicalContextEnabled, liveTrace, siteHistoricalContext]);

  const forecast = useMemo<SiteForecast>(() => {
    const stored = siteForecasts[activeSiteId];
    if (stored) return stored;
    const raw = liveTrace?.forecast;
    if (raw?.projected_points && Array.isArray(raw.projected_points)) {
      return {
        horizon_minutes: Number(raw.horizon_minutes) || 60,
        expected_level: Number(raw.expected_level) || 0,
        trend_per_hour: Number(raw.trend_per_hour) || 0,
        acceleration_per_hour2: Number(raw.acceleration_per_hour2) || 0,
        risk: String(raw.risk || 'unknown'),
        status: String(raw.status || 'ok'),
        confidence: Number(raw.confidence) || 0.45,
        critical_threshold: Number(raw.critical_threshold) || 0.8,
        minutes_to_threshold: typeof raw.minutes_to_threshold === 'number' ? raw.minutes_to_threshold : null,
        warning: raw.warning ? String(raw.warning) : null,
        projected_points: raw.projected_points.map((point: RawRecord) => ({
          minute: Number(point.minute) || 0,
          level: Number(point.level) || 0,
        })),
        uncertainty_band: Array.isArray(raw.uncertainty_band) ? raw.uncertainty_band.map((point: RawRecord) => ({
          minute: Number(point.minute) || 0,
          low: Number(point.low) || 0,
          high: Number(point.high) || 0,
        })) : [],
      };
    }
    const base = activeAlert.level === 'red' ? 0.82 : activeAlert.level === 'orange' ? 0.68 : activeAlert.level === 'yellow' ? 0.52 : 0.35;
    const trend = activeAlert.level === 'red' ? 0.18 : activeAlert.level === 'orange' ? 0.14 : 0.08;
    return {
      horizon_minutes: 60,
      expected_level: Math.min(1, base + trend),
      trend_per_hour: trend,
      acceleration_per_hour2: activeAlert.level === 'red' ? 0.07 : 0.03,
      risk: activeAlert.level === 'green' ? 'low' : activeAlert.level === 'yellow' ? 'moderate' : 'high',
      status: 'demo',
      confidence: 0.42,
      critical_threshold: 0.8,
      minutes_to_threshold: activeAlert.level === 'red' ? 0 : activeAlert.level === 'orange' ? 45 : null,
      warning: 'Demo projection until enough site measurements are available.',
      projected_points: [0, 15, 30, 45, 60].map((minute) => ({
        minute,
        level: Math.min(1, base + trend * (minute / 60) + 0.5 * 0.05 * (minute / 60) ** 2),
      })),
      uncertainty_band: [0, 15, 30, 45, 60].map((minute) => {
        const level = Math.min(1, base + trend * (minute / 60) + 0.5 * 0.05 * (minute / 60) ** 2);
        return { minute, low: Math.max(0, level - 0.08), high: level + 0.08 };
      }),
    };
  }, [activeAlert.level, activeSiteId, liveTrace, siteForecasts]);

  const toggleHistoricalContext = async (enabled: boolean) => {
    const updated = await updateSiteExperimentalSettings(activeSiteId, {
      historical_context_enabled: enabled,
    });
    if (updated?.historical_context_enabled) {
      const query = `${activeAlert.level} ${activeAlert.trigger_source ?? ''} ${activeAlert.summary ?? ''}`;
      await fetchSiteHistoricalContext(activeSiteId, { waterLevel: activeAlert.score, query });
    }
  };

  const invokeAction = (fn: ActionCall['fn']) => {
    setActionState((prev) => ({ ...prev, [fn]: { busy: true } }));
    const at = new Date().toLocaleTimeString('en-US');
    setActionLog((prev) => [`${at}  function_call → ${fn}(...)`, ...prev].slice(0, 5));

    setTimeout(() => {
      setActionState((prev) => ({ ...prev, [fn]: { busy: false } }));
      setActionLog((prev) => [`${new Date().toLocaleTimeString('en-US')}  ✓ ${fn} ok`, ...prev].slice(0, 5));
      // mirror the action into the timeline so the demo loop closes visibly
      const at2 = new Date().toISOString();
      const map: Partial<Record<ActionCall['fn'], TimelineEvent>> = {
        emit_cap_xml:         { at: at2, kind: 'cap',    label: 'CAP v1.2 emitted',          detail: 'Manual operator re-emission',        done: true },
        trigger_siren:        { at: at2, kind: 'siren',  label: 'Siren triggered',           detail: 'Operator triggered relay',           done: true },
        send_lora_alert:      { at: at2, kind: 'notify', label: 'LoRa alert sent',           detail: 'Broadcast to sibling nodes',         done: true },
        notify_civil_defense: { at: at2, kind: 'notify', label: 'Civil Defense notified',    detail: 'Manual webhook re-send',             done: true },
      };
      const event = map[fn];
      if (event) {
        setTimeline((prev) => [...prev, event]);
      }
    }, 900);
  };

  const actions: ActionCall[] = [
    { fn: 'emit_cap_xml',         arg: `site=${activeSite?.name ?? activeAlert.site_id}`, busy: actionState.emit_cap_xml.busy },
    { fn: 'trigger_siren',        arg: 'zone=low',                     busy: actionState.trigger_siren.busy },
    { fn: 'send_lora_alert',      arg: 'broadcast',                    busy: actionState.send_lora_alert.busy },
    { fn: 'notify_civil_defense', arg: 'webhook=municipal',            busy: actionState.notify_civil_defense.busy },
  ];

  // The "all-clear" state: no active alert AND no demo fallback wanted —
  // currently we always show demo when alerts is empty, so this branch only
  // fires if alerts.length > 0 and somehow no top alert (defensive only).
  if (!activeAlert) {
    return (
      <div className="space-y-6 pb-20">
        <EmptyCommandCenter />
        <SitesGrid sites={sites} isOnline={isOnline} />
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-20">
      {/* ── 5-second read ────────────────────────────────────────────── */}
      <RiskBannerForAlert alert={activeAlert} site={activeSite} isDemo={isDemo} />

      {/* ── Main two-column command grid ────────────────────────────── */}
      <div className="cc-grid">
        {/* Left column: signals → evidence → reasoning → audit */}
        <div className="space-y-4">
          <SectionPanel title="Signal fusion" meta={`fused_score = ${activeAlert.score.toFixed(2)}`}>
            <SignalFusionRow inputs={liveSignals} />
          </SectionPanel>

          <ExperimentalControls
            historicalContextEnabled={historicalContextEnabled}
            onToggleHistoricalContext={toggleHistoricalContext}
            settingsLoaded={Boolean(currentSettings)}
          />

          <SectionPanel title="Evidence frame · Claude narration" meta={CENTRAL_NODE_MODEL}>
            <EvidencePanel
              frameUrl={EVIDENCE_BY_LEVEL[activeAlert.level].frameUrl}
              frameLabel={EVIDENCE_BY_LEVEL[activeAlert.level].frameLabel}
              description={EVIDENCE_BY_LEVEL[activeAlert.level].description}
              model={CENTRAL_NODE_MODEL}
              confidence={EVIDENCE_BY_LEVEL[activeAlert.level].confidence}
            />
          </SectionPanel>

          {activeAlert.reasoning_summary && (
            <GemmaReasoning
              summary={activeAlert.reasoning_summary}
              chain={reasoningChain}
              model={CENTRAL_NODE_MODEL}
            />
          )}

          {historicalContextEnabled && historicalContext.length > 0 && (
            <HistoricalContextPanel hits={historicalContext} />
          )}

          <AuditTrace entries={liveAudit} />
        </div>

        {/* Right column: CAP, action rail, offline sync */}
        <div className="space-y-4">
          <CapStatusCard {...DEMO_CAP} />

          <ActionRail actions={actions} onInvoke={invokeAction} />

          {actionLog.length > 0 && (
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-300 leading-snug space-y-1">
              <div className="text-slate-500 uppercase tracking-wider text-xs font-bold mb-1">
                stdout · function_call log
              </div>
              {actionLog.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}

          <OfflineSyncCard
            isOnline={isOnline}
            queueCount={queueCount}
            lastSync={isOnline ? new Date().toLocaleTimeString('en-US') : null}
          />

          <ForecastPanel forecast={forecast} />
        </div>
      </div>

      {/* ── Lifecycle timeline (full width) ────────────────────────── */}
      <IncidentTimeline events={timeline} />

      {/* ── Auxiliary: sites grid for navigation ───────────────────── */}
      <SitesGrid sites={sites} isOnline={isOnline} />
    </div>
  );
}

function ExperimentalControls({
  historicalContextEnabled,
  onToggleHistoricalContext,
  settingsLoaded,
}: {
  historicalContextEnabled: boolean;
  onToggleHistoricalContext: (value: boolean) => void;
  settingsLoaded: boolean;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <Database className="w-5 h-5 text-amber-300 flex-shrink-0" />
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
            Experimental roadmap
          </div>
          <div className="text-sm text-slate-200 font-semibold">
            Activar Contexto Historico
          </div>
        </div>
      </div>
      <button
        type="button"
        aria-pressed={historicalContextEnabled}
        disabled={!settingsLoaded}
        onClick={() => onToggleHistoricalContext(!historicalContextEnabled)}
        className={`relative inline-flex h-7 w-12 flex-shrink-0 items-center rounded-full border transition-colors disabled:opacity-50 ${
          historicalContextEnabled
            ? 'bg-amber-400 border-amber-300'
            : 'bg-slate-800 border-slate-700'
        }`}
      >
        <span
          className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${
            historicalContextEnabled ? 'translate-x-5' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  );
}

function HistoricalContextPanel({
  hits,
}: {
  hits: HistoricalContextHit[];
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          Edge RAG offline
        </div>
        <span className="text-xs font-mono text-amber-300">sqlite/local</span>
      </div>
      <div className="space-y-2">
        {hits.map((hit, index) => (
          <div key={`${hit.title}-${index}`} className="border border-slate-800 rounded-md p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-white">{hit.title}</div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500 font-mono">
                ctx:{hit.id || '--'} · {hit.source}
              </span>
            </div>
            <p className="text-xs text-slate-400 leading-snug mt-1">{hit.summary}</p>
            <div className="mt-2 flex items-center justify-between gap-2 text-[10px] font-mono text-slate-500">
              <span>{hit.jurisdiction ?? 'local'} · rank {(hit.rank * 100).toFixed(0)}%</span>
              <span>{hit.threshold_level == null ? 'threshold --' : `threshold ${hit.threshold_level.toFixed(2)}`}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ForecastPanel({
  forecast,
}: {
  forecast: SiteForecast;
}) {
  const width = 320;
  const height = 120;
  const maxMinute = Math.max(60, ...forecast.projected_points.map((point) => point.minute));
  const path = forecast.projected_points
    .map((point, index) => {
      const x = (point.minute / maxMinute) * width;
      const y = height - Math.min(1, point.level) * height;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  const bandPath = forecast.uncertainty_band.length
    ? [
        ...forecast.uncertainty_band.map((point, index) => {
          const x = (point.minute / maxMinute) * width;
          const y = height - Math.min(1.2, point.high) * height;
          return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
        }),
        ...[...forecast.uncertainty_band].reverse().map((point) => {
          const x = (point.minute / maxMinute) * width;
          const y = height - Math.min(1.2, point.low) * height;
          return `L ${x.toFixed(1)} ${y.toFixed(1)}`;
        }),
        'Z',
      ].join(' ')
    : '';
  const eta = forecast.minutes_to_threshold == null
    ? '>60m'
    : forecast.minutes_to_threshold === 0
      ? 'crossed'
      : `${forecast.minutes_to_threshold}m`;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-amber-300" />
          <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
            Proyeccion a 60 min
          </div>
        </div>
        <span className="text-xs font-mono text-amber-300">{forecast.status} · {forecast.risk}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-32" role="img" aria-label="Water level forecast">
        <line
          x1="0"
          y1={height - Math.min(1.2, forecast.critical_threshold) * height}
          x2={width}
          y2={height - Math.min(1.2, forecast.critical_threshold) * height}
          stroke="#ef4444"
          strokeWidth="1.5"
          strokeDasharray="5 5"
        />
        {bandPath && <path d={bandPath} fill="rgba(245, 158, 11, 0.18)" />}
        <path d={path} fill="none" stroke="#f59e0b" strokeWidth="3" strokeDasharray="6 5" strokeLinecap="round" />
        {forecast.projected_points.map((point) => (
          <circle
            key={point.minute}
            cx={(point.minute / maxMinute) * width}
            cy={height - Math.min(1, point.level) * height}
            r="3"
            fill="#fbbf24"
          />
        ))}
      </svg>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="cc-metric">
          <span className="cc-k">level_60m</span>
          <span className="cc-v">{forecast.expected_level.toFixed(2)}</span>
        </div>
        <div className="cc-metric">
          <span className="cc-k">conf</span>
          <span className="cc-v">{(forecast.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="cc-metric">
          <span className="cc-k">eta</span>
          <span className="cc-v">{eta}</span>
        </div>
      </div>
      {forecast.warning && (
        <p className="mt-3 text-xs text-slate-400 leading-snug">{forecast.warning}</p>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// RiskBannerForAlert — thin wrapper that maps a FusedAlert + Site into the
// generic RiskBanner. Lives here so the dashboard owns the mapping.
// ──────────────────────────────────────────────────────────────────────────
function RiskBannerForAlert({
  alert,
  site,
  isDemo,
}: {
  alert: FusedAlert;
  site: Site | null;
  isDemo: boolean;
}) {
  return (
    <RiskBanner
      level={alert.level}
      score={alert.score}
      siteName={site?.name ?? alert.site_id}
      region={site?.region}
      summary={alert.summary}
      isDemo={isDemo}
    />
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SitesGrid — preserves the dashboard's original "Monitored Sites" affordance
// so the operator can navigate into a SiteDetail mid-recording.
// ──────────────────────────────────────────────────────────────────────────
function SitesGrid({ sites, isOnline }: { sites: Site[]; isOnline: boolean }) {
  if (sites.length === 0) {
    return null;
  }
  return (
    <section>
      <h2 className="text-sm font-bold uppercase tracking-widest text-slate-800 mb-3">
        Monitored sites
      </h2>
      <div className="grid gap-3 md:grid-cols-2">
        {sites.map((site) => (
          <Link
            key={site.id}
            to={`/sites/${site.id}`}
            className="p-4 bg-white border border-gray-200 rounded-lg shadow-sm hover:border-blue-300 transition-colors"
          >
            <div className="flex justify-between items-start gap-4">
              <div>
                <h3 className="font-semibold text-gray-900">{site.name}</h3>
                <p className="text-sm text-gray-500">{site.region}</p>
              </div>
              <span
                className={`px-2 py-1 text-xs rounded-full font-medium ${
                  site.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
                }`}
              >
                {site.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
            <div className="mt-3 text-sm text-blue-600 font-medium inline-flex items-center gap-1">
              Open site <ArrowRight className="w-4 h-4" />
            </div>
            {!isOnline && (
              <div className="text-xs text-gray-400 mt-2">
                Offline — data from last available cache
              </div>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}
