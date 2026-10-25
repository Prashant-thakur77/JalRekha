/* CommandCenter.tsx
 *
 * Persona C operator-dashboard helpers. All visuals follow the "Defensa Civil
 * emergency operations center" style: dense, monospace metrics, hard-edged
 * panels on slate-900, severity colors carried verbatim from the FusedAlert
 * scale. None of these components hit the network — they render whatever the
 * parent passes in. The dashboard uses real store data when available and
 * falls back to clearly-labeled demo state.
 *
 * Components exposed:
 *   - RiskBanner          full-bleed severity strip (the "5-second read")
 *   - SignalFusionRow     three-input fusion tile row (camera / volunteer / hydromet)
 *   - EvidencePanel       evidence frame + Gemma narration overlay (placeholder OK)
 *   - GemmaReasoning      reasoning_summary block (Spanish, monospace meta)
 *   - AuditTrace          deterministic rule trace, numbered
 *   - ActionRail          four function-calling buttons (emit_cap_xml, …)
 *   - CapStatusCard       CAP v1.2 export state + last receipt
 *   - OfflineSyncCard     queue depth + last sync timestamp
 *   - IncidentTimeline    horizontal timeline of the alert lifecycle
 */

import type { ReactNode } from 'react';
import {
  Activity,
  Bell,
  CheckCircle2,
  Cloud,
  CloudRain,
  Eye,
  FileText,
  LoaderCircle,
  Megaphone,
  Radio,
  Siren,
  TriangleAlert,
  UserCheck,
  WifiOff,
} from 'lucide-react';
import type { FusedAlert } from '../store';

// ──────────────────────────────────────────────────────────────────────────
// Severity → strip color class. Risk level is the load-bearing visual.
// ──────────────────────────────────────────────────────────────────────────
export type Level = FusedAlert['level'];

// eslint-disable-next-line react-refresh/only-export-components
export const LEVEL_LABEL: Record<Level, string> = {
  green:  'NOMINAL',
  yellow: 'WATCH',
  orange: 'WARNING',
  red:    'CRITICAL',
};

// eslint-disable-next-line react-refresh/only-export-components
export const LEVEL_STRIP_CLASS: Record<Level, string> = {
  green:  'cc-strip-green',
  yellow: 'cc-strip-yellow',
  orange: 'cc-strip-orange',
  red:    'cc-strip-red',
};

// ──────────────────────────────────────────────────────────────────────────
// RiskBanner — full-bleed severity strip. Renders the active incident's
// level, score, and site at a glance. Pulses softly on red.
// ──────────────────────────────────────────────────────────────────────────
interface RiskBannerProps {
  level: Level;
  score: number;
  siteName: string;
  region?: string;
  summary?: string;
  isDemo?: boolean;
}

export function RiskBanner({ level, score, siteName, region, summary, isDemo }: RiskBannerProps) {
  return (
    <div
      className={`${LEVEL_STRIP_CLASS[level]} ${level === 'red' ? 'cc-strip-pulse' : ''} px-5 py-4 rounded-lg flex items-center gap-5 flex-wrap`}
    >
      <div className="flex items-center gap-3">
        {level === 'red' ? <TriangleAlert className="w-8 h-8" /> : <Activity className="w-8 h-8" />}
        <div>
          <div className="text-xs font-bold uppercase tracking-widest opacity-80">
            Active incident
          </div>
          <div className="text-3xl font-bold leading-none mt-1">{LEVEL_LABEL[level]}</div>
        </div>
      </div>

      <div className="border-l border-slate-200 self-stretch opacity-60" />

      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wide opacity-70">Site</div>
        <div className="text-lg font-semibold leading-tight">{siteName}</div>
        {region && <div className="text-xs opacity-80 mt-1">{region}</div>}
      </div>

      <div className="border-l border-slate-200 self-stretch opacity-60" />

      <div>
        <div className="text-xs uppercase tracking-wide opacity-70">Score</div>
        <div className="text-4xl font-bold tabular-nums leading-none mt-1">
          {Math.round(score * 100)}<span className="text-lg opacity-80">%</span>
        </div>
      </div>

      {summary && (
        <div className="w-full text-sm opacity-95 mt-1 leading-snug">{summary}</div>
      )}

      {isDemo && (
        <span className="cc-demo-badge">Demo · sample state</span>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SignalFusionRow — three tiles showing the inputs the decision engine fused.
// ──────────────────────────────────────────────────────────────────────────
export interface SignalInput {
  source: 'camera' | 'volunteer' | 'hydromet';
  score: number;             // 0..1 contribution to the fused score
  status: 'ok' | 'stale' | 'missing';
  detail: string;            // short ES descriptor
  ageSeconds?: number;
  model?: string;            // per-source model label (e.g., gemma4:e4b)
}

const SIGNAL_META: Record<SignalInput['source'], { label: string; icon: typeof Activity; mono: string }> = {
  camera:    { label: 'Fixed camera',      icon: Eye,        mono: 'cv_node' },
  volunteer: { label: 'Volunteer report',  icon: UserCheck,  mono: 'vol_report' },
  hydromet:  { label: 'Hydromet',          icon: CloudRain,  mono: 'hydromet' },
};

const STATUS_DOT: Record<SignalInput['status'], string> = {
  ok:      'bg-green-500',
  stale:   'bg-yellow-500',
  missing: 'bg-slate-700',
};

function formatAge(s?: number): string {
  if (s == null) return '—';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

export function SignalFusionRow({ inputs }: { inputs: SignalInput[] }) {
  return (
    <div className="cc-fusion">
      {inputs.map((sig) => {
        const meta = SIGNAL_META[sig.source];
        const IconComp = meta.icon;
        return (
          <div key={sig.source} className="bg-slate-900 text-slate-300 rounded-lg p-4 border border-slate-800">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <IconComp className="w-4 h-4 text-slate-400" />
                <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
                  {meta.label}
                </div>
              </div>
              <span className={`w-2 h-2 rounded-full ${STATUS_DOT[sig.status]}`} />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <div className="text-3xl font-bold tabular-nums text-white">
                {(sig.score * 100).toFixed(0)}
              </div>
              <div className="text-sm text-slate-400">/ 100</div>
            </div>
            <div className="mt-2 text-xs text-slate-400 leading-snug min-h-0">
              {sig.detail}
            </div>
            <div className="mt-3 flex items-center justify-between text-xs">
              <span className="font-mono text-slate-500">{meta.mono}</span>
              <span className="text-slate-500">{formatAge(sig.ageSeconds)}</span>
            </div>
            {sig.model && (
              <div className="mt-1 text-[10px] font-mono text-slate-600 truncate">
                model: {sig.model}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// EvidencePanel — frame + Gemma narration. Falls back to a labeled placeholder.
// ──────────────────────────────────────────────────────────────────────────
interface EvidencePanelProps {
  frameUrl?: string | null;
  description?: string | null;
  model?: string | null;
  confidence?: number | null;
  frameLabel?: string | null;
}

export function EvidencePanel({ frameUrl, description, model, confidence, frameLabel }: EvidencePanelProps) {
  return (
    <div className="rounded-lg overflow-hidden border border-slate-800 bg-slate-950 relative">
      <div className="px-4 py-2 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          Evidence frame
        </div>
        <span className="text-xs font-mono text-slate-500">
          {frameLabel ?? (frameUrl ? 'cv_node/last_frame.jpg' : 'sample/demo - no real frame')}
        </span>
      </div>

      <div className="relative" style={{ aspectRatio: '16 / 9', minHeight: 260 }}>
        {frameUrl ? (
          <img src={frameUrl} alt="Evidence frame" className="w-full h-full object-cover" />
        ) : (
          /* Placeholder frame: muddy turbid-water gradient + ROI + critical line */
          <>
            <div
              className="absolute"
              style={{
                inset: 0,
                background:
                  'linear-gradient(180deg, #4a5568 0%, #2d3748 35%, #5b5234 60%, #6b5b3a 100%)',
              }}
            />
            <svg
              viewBox="0 0 700 280"
              preserveAspectRatio="none"
              className="absolute"
              style={{ inset: 0, width: '100%', height: '100%' }}
            >
              <polygon
                points="60,150 640,150 620,260 80,260"
                fill="none"
                stroke="#22C55E"
                strokeWidth="2"
                strokeDasharray="6 4"
              />
              <line x1="40" y1="120" x2="660" y2="120" stroke="#EF4444" strokeWidth="2" />
              <text
                x="48"
                y="112"
                fontFamily="Consolas, Monaco, monospace"
                fontSize="11"
                fill="#EF4444"
                fontWeight="600"
              >
                critical line · y=120
              </text>
              <text x="68" y="172" fontFamily="Consolas, Monaco, monospace" fontSize="10" fill="#22C55E">
                ROI
              </text>
            </svg>
            <div
              className="absolute"
              style={{ top: 8, right: 12 }}
            >
              <span className="cc-demo-badge">placeholder</span>
            </div>
          </>
        )}

        {description && (
          <div className="absolute" style={{ left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.72)' }}>
            <div className="px-4 py-2 text-white">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold uppercase tracking-wider text-amber-300">
                  Gemma · {model ?? 'local'}
                </span>
                {typeof confidence === 'number' && (
                  <span className="text-xs font-mono text-amber-300">
                    conf {(confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              <p className="text-sm leading-snug mt-1">{description}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// GemmaReasoning — reasoning_summary block + optional numbered chain.
// ──────────────────────────────────────────────────────────────────────────
interface GemmaReasoningProps {
  summary: string;
  chain?: string[];
  model?: string | null;
}

export function GemmaReasoning({ summary, chain, model }: GemmaReasoningProps) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          Gemma reasoning
        </div>
        <span className="text-xs font-mono text-amber-300">{model ?? 'local'}</span>
      </div>
      <p className="text-sm text-slate-300 leading-snug whitespace-pre-wrap">{summary}</p>
      {chain && chain.length > 0 && (
        <ol className="mt-3 list-decimal pl-5 text-xs text-slate-400 space-y-1">
          {chain.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// AuditTrace — deterministic rule trace. Numbered, monospace, ops-grade.
// ──────────────────────────────────────────────────────────────────────────
export interface AuditEntry {
  rule: string;        // e.g. "RULE_WATERLINE_CROSSED"
  outcome: 'fired' | 'not_fired' | 'override';
  detail: string;      // human-readable Spanish detail
}

const OUTCOME_DOT: Record<AuditEntry['outcome'], string> = {
  fired:     'bg-red-600',
  not_fired: 'bg-slate-700',
  override:  'bg-amber-400',
};

const OUTCOME_LABEL: Record<AuditEntry['outcome'], string> = {
  fired:     'fired',
  not_fired: 'not fired',
  override:  'override',
};

export function AuditTrace({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          Deterministic audit trace
        </div>
        <span className="text-xs font-mono text-slate-500">
          {entries.filter((e) => e.outcome === 'fired').length} of {entries.length} rules
        </span>
      </div>
      <ol className="divide-y divide-slate-800">
        {entries.map((entry, i) => (
          <li key={i} className="flex gap-3 px-4 py-3">
            <span className={`w-2 h-2 rounded-full mt-2 flex-shrink-0 ${OUTCOME_DOT[entry.outcome]}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-3 flex-wrap">
                <span className="font-mono text-xs font-semibold text-slate-300">
                  {entry.rule}
                </span>
                <span className="text-xs uppercase tracking-wider text-slate-500">
                  {OUTCOME_LABEL[entry.outcome]}
                </span>
              </div>
              <p className="text-xs text-slate-400 leading-snug mt-1">{entry.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// ActionRail — function-calling buttons. These map 1:1 to the Gemma tool
// schema documented in the project brief. Clicking dispatches the action;
// the parent owns the actual side effect.
// ──────────────────────────────────────────────────────────────────────────
export interface ActionCall {
  fn: 'emit_cap_xml' | 'trigger_siren' | 'send_lora_alert' | 'notify_civil_defense';
  arg: string;          // short ES-language arg label, e.g. "AlertID=42"
  busy?: boolean;
  disabledReason?: string | null;
}

const ACTION_ICON: Record<ActionCall['fn'], typeof FileText> = {
  emit_cap_xml:         FileText,
  trigger_siren:        Siren,
  send_lora_alert:      Radio,
  notify_civil_defense: Megaphone,
};

const ACTION_LABEL: Record<ActionCall['fn'], string> = {
  emit_cap_xml:         'Emit CAP v1.2',
  trigger_siren:        'Trigger siren',
  send_lora_alert:      'Send LoRa alert',
  notify_civil_defense: 'Notify Civil Defense',
};

export function ActionRail({
  actions,
  onInvoke,
}: {
  actions: ActionCall[];
  onInvoke: (fn: ActionCall['fn']) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-1">
        <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
          Operator actions
        </div>
        <span className="text-xs font-mono text-slate-500">function_call</span>
      </div>
      {actions.map((a) => {
        const IconComp = ACTION_ICON[a.fn];
        return (
          <button
            key={a.fn}
            className="cc-action-btn"
            disabled={!!a.busy || !!a.disabledReason}
            onClick={() => onInvoke(a.fn)}
            title={a.disabledReason ?? ''}
          >
            {a.busy
              ? <LoaderCircle className="w-4 h-4 text-amber-300" style={{ animation: 'volunteer-spin 1s linear infinite' }} />
              : <IconComp className="w-4 h-4 text-amber-300" />}
            <span>{ACTION_LABEL[a.fn]}</span>
            <span className="cc-action-arg">{a.arg}</span>
          </button>
        );
      })}
      <style>{`@keyframes volunteer-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// CapStatusCard — CAP v1.2 export status. Compact, monospace, with last
// emit timestamp + receipt ID.
// ──────────────────────────────────────────────────────────────────────────
interface CapStatusCardProps {
  status: 'idle' | 'pending' | 'emitted' | 'error';
  lastEmit?: string | null;     // ISO string
  receiptId?: string | null;
  schemaVersion?: string;
  recipientCount?: number;
  errorMessage?: string | null;
}

export function CapStatusCard({
  status,
  lastEmit,
  receiptId,
  schemaVersion = 'CAP v1.2',
  recipientCount = 0,
  errorMessage,
}: CapStatusCardProps) {
  const statusTone: Record<CapStatusCardProps['status'], { dot: string; label: string; color: string }> = {
    idle:    { dot: 'bg-slate-700', label: 'Not emitted', color: 'text-slate-400' },
    pending: { dot: 'bg-amber-400', label: 'Emitting…',   color: 'text-amber-300' },
    emitted: { dot: 'bg-green-500', label: 'Emitted',     color: 'text-green-300' },
    error:   { dot: 'bg-red-600',   label: 'Failed',      color: 'text-red-600' },
  };
  const tone = statusTone[status];
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          {schemaVersion} · export
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${tone.dot}`} />
          <span className={`text-xs font-semibold uppercase tracking-wider ${tone.color}`}>{tone.label}</span>
        </div>
      </div>
      <div className="flex flex-col gap-1 text-xs">
        <div className="cc-metric">
          <span className="cc-k">last emit</span>
          <span className="cc-v">{lastEmit ?? '—'}</span>
        </div>
        <div className="cc-metric">
          <span className="cc-k">receipt</span>
          <span className="cc-v">{receiptId ?? '—'}</span>
        </div>
        <div className="cc-metric">
          <span className="cc-k">recipients</span>
          <span className="cc-v">{recipientCount}</span>
        </div>
      </div>
      {status === 'error' && errorMessage && (
        <div className="mt-3 text-xs text-red-600 font-mono leading-snug">{errorMessage}</div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// OfflineSyncCard — queue depth, last sync, connectivity state.
// ──────────────────────────────────────────────────────────────────────────
interface OfflineSyncCardProps {
  isOnline: boolean;
  queueCount: number;
  lastSync?: string | null;
}

export function OfflineSyncCard({ isOnline, queueCount, lastSync }: OfflineSyncCardProps) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          Offline queue · last sync
        </div>
        <div className="flex items-center gap-2">
          {isOnline ? (
            <><Cloud className="w-3 h-3 text-green-400" /> <span className="text-xs font-semibold text-green-300 uppercase tracking-wider">Online</span></>
          ) : (
            <><WifiOff className="w-3 h-3 text-red-600" /> <span className="text-xs font-semibold text-red-600 uppercase tracking-wider">Offline</span></>
          )}
        </div>
      </div>
      <div className="flex items-baseline gap-3">
        <div className="text-4xl font-bold tabular-nums text-white">{queueCount}</div>
        <div className="text-xs text-slate-400 uppercase tracking-wider">reports in queue</div>
      </div>
      <div className="mt-3 text-xs cc-metric">
        <span className="cc-k">last_sync</span>
        <span className="cc-v">{lastSync ?? '—'}</span>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// IncidentTimeline — horizontal lifecycle. Compact, fits in 120px tall.
// ──────────────────────────────────────────────────────────────────────────
export interface TimelineEvent {
  at: string;                    // ISO timestamp
  kind: 'detect' | 'volunteer' | 'fuse' | 'cap' | 'siren' | 'notify' | 'sync';
  label: string;                 // ES short label
  detail?: string;               // ES sub-detail
  done: boolean;                 // grayed if not yet happened
}

const KIND_ICON: Record<TimelineEvent['kind'], typeof Eye> = {
  detect:    Eye,
  volunteer: UserCheck,
  fuse:      Activity,
  cap:       FileText,
  siren:     Siren,
  notify:    Bell,
  sync:      Cloud,
};

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

export function IncidentTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          Incident timeline
        </div>
        <span className="text-xs font-mono text-slate-500">
          {events.filter((e) => e.done).length} / {events.length} events
        </span>
      </div>
      <div className="overflow-x-auto">
        <div className="flex items-stretch gap-0 min-w-0" style={{ minWidth: 720 }}>
          {events.map((e, i) => {
            const IconComp = KIND_ICON[e.kind];
            const isLast = i === events.length - 1;
            return (
              <div key={i} className="flex-1 flex items-start gap-0 min-w-0">
                <div className="flex flex-col items-center gap-2 flex-shrink-0" style={{ width: 32 }}>
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center border-2 ${
                      e.done
                        ? 'bg-amber-400 border-amber-300 text-slate-900'
                        : 'bg-slate-800 border-slate-700 text-slate-500'
                    }`}
                  >
                    <IconComp className="w-4 h-4" />
                  </div>
                </div>
                <div className="flex-1 min-w-0 pl-2 pr-3">
                  <div className={`text-xs font-mono ${e.done ? 'text-amber-300' : 'text-slate-500'}`}>
                    {fmtTime(e.at)}
                  </div>
                  <div className={`text-sm font-semibold leading-tight mt-1 ${e.done ? 'text-white' : 'text-slate-500'}`}>
                    {e.label}
                  </div>
                  {e.detail && (
                    <div className="text-xs text-slate-400 leading-snug mt-1">{e.detail}</div>
                  )}
                  {!isLast && (
                    <div className={`h-1 mt-3 ${e.done && events[i + 1]?.done ? 'bg-amber-400' : 'bg-slate-800'}`} />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// NodeProfileCard — header for the Persona A fixed-node screen. Surfaces
// what the operator needs to know about the local runtime BEFORE they look
// at numbers: which hardware, which model, where it runs, when last seen.
// ──────────────────────────────────────────────────────────────────────────
export interface NodeProfileProps {
  siteName: string;
  hardware?: string;            // e.g. "Raspberry Pi 5 · 8 GB"
  model?: string;               // e.g. "gemma4:e2b"
  runtime?: string;              // e.g. "LiteRT-LM" / "Ollama"
  reachable?: boolean;
  lastRunAgoSeconds?: number | null;
}

export function NodeProfileCard({
  siteName,
  hardware = 'Raspberry Pi 5 · 8 GB',
  model = 'gemma4:e2b',
  runtime = 'LiteRT-LM',
  reachable = true,
  lastRunAgoSeconds,
}: NodeProfileProps) {
  return (
    <div className="bg-slate-900 text-slate-300 border border-slate-800 rounded-lg p-5">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="text-xs uppercase tracking-widest text-slate-400 font-bold">
          Local node · profile
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${reachable ? 'bg-green-500' : 'bg-red-600'}`} />
          <span className={`text-xs font-semibold uppercase tracking-wider ${reachable ? 'text-green-300' : 'text-red-600'}`}>
            {reachable ? 'no cloud · available' : 'no cloud · unavailable'}
          </span>
        </div>
      </div>
      <div className="flex items-baseline gap-3 flex-wrap">
        <div className="text-2xl font-bold text-white leading-tight">{siteName}</div>
      </div>
      <div className="grid mt-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Hardware</div>
          <div className="text-sm font-mono text-slate-200 mt-1">{hardware}</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Model</div>
          <div className="text-sm font-mono text-amber-300 mt-1">{model}</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Runtime</div>
          <div className="text-sm font-mono text-slate-200 mt-1">{runtime}</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Last run</div>
          <div className="text-sm font-mono text-slate-200 mt-1">
            {lastRunAgoSeconds == null ? '—' : formatAge(lastRunAgoSeconds)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// NodeMetricsCard — observation + latency metrics. Renders "no medido
// todavía" placeholders for fields the backend hasn't measured yet —
// demo-honest, no fake numbers.
// ──────────────────────────────────────────────────────────────────────────
export interface NodeMetric {
  k: string;            // label (es)
  v: string | null;     // value, or null → "no medido todavía"
  hint?: string;        // optional sub-label / unit context
  tone?: 'fired' | 'idle' | 'unmeasured';
}

export function NodeMetricsCard({ title = 'Node metrics', metrics }: { title?: string; metrics: NodeMetric[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
          {title}
        </div>
        <span className="text-xs font-mono text-slate-500">
          {metrics.filter((m) => m.v !== null).length} / {metrics.length} measured
        </span>
      </div>
      <div className="divide-y divide-slate-800">
        {metrics.map((m, i) => {
          const isMissing = m.v === null;
          const valueColor = isMissing
            ? 'text-slate-500'
            : m.tone === 'fired'
            ? 'text-red-600'
            : 'text-slate-100';
          return (
            <div key={i} className="px-4 py-3 flex items-baseline justify-between gap-3">
              <div className="flex flex-col">
                <span className="text-xs uppercase tracking-wider text-slate-400 font-semibold">{m.k}</span>
                {m.hint && <span className="text-xs text-slate-500 mt-1">{m.hint}</span>}
              </div>
              <span className={`text-sm font-mono font-semibold tabular-nums ${valueColor}`}>
                {isMissing ? 'not yet measured' : m.v}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// HandoffNote — small "feeds into /comando" affordance shown at the
// bottom of SiteDetail so the operator + the camera understand the link
// between the node screen and the fused command center.
// ──────────────────────────────────────────────────────────────────────────
export function HandoffNote({ href = '/' , label = 'Fused result at /command' }: { href?: string; label?: string }) {
  return (
    <a
      href={href}
      className="inline-flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-2 text-sm font-semibold text-orange-700 hover:bg-orange-100 transition-colors"
    >
      <span className="w-2 h-2 rounded-full bg-orange-500" />
      {label}
      <span className="font-mono text-xs opacity-70">→</span>
    </a>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SectionPanel — slate-900 framed panel with title. Used to host the
// sub-blocks (fusion row, audit trace, etc) under a common chrome.
// ──────────────────────────────────────────────────────────────────────────
export function SectionPanel({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-800">
          {title}
        </h2>
        {meta && <div className="text-xs font-mono text-slate-500">{meta}</div>}
      </div>
      {children}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// EmptyCommandCenter — shown when no active alert exists. Quiet, not festive.
// ──────────────────────────────────────────────────────────────────────────
export function EmptyCommandCenter() {
  return (
    <div className="bg-slate-900 text-slate-300 rounded-lg p-10 border border-slate-800 text-center">
      <CheckCircle2 className="w-10 h-10 text-green-400 mx-auto" />
      <div className="text-lg font-semibold mt-3 text-white">No active incident</div>
      <p className="text-sm text-slate-400 mt-2 leading-snug">
        The fusion engine found no corroborated signals warranting an alert.
        Nodes keep sampling; volunteer reports queue if they arrive.
      </p>
      <div className="mt-4 inline-flex items-center gap-2 text-xs text-slate-500 font-mono">
        <CloudRain className="w-3 h-3" /> No CAP emitted in last 24h · stable hydromet
      </div>
    </div>
  );
}
