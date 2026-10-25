/**
 * Typed fetch helpers for the agent, region and relief API (docs/API_AGENT.md).
 * Every helper throws ApiError on a non-2xx response and lets network errors
 * propagate, so pages can show a calm error state instead of crashing.
 */
import { API_BASE } from './store';

// ── Shared ────────────────────────────────────────────────────────────────

export interface Band {
  min: number;
  typ: number;
  max: number;
}

export type CountryCode = 'NP' | 'IN' | string;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Origin of the API server (where /uploads/... is served). */
export function serverOrigin(): string {
  try {
    const base = typeof window !== 'undefined' ? window.location.href : 'http://localhost/';
    return new URL(API_BASE, base).origin;
  } catch {
    return '';
  }
}

/** Turn a server-relative path like `/uploads/x.png` into an absolute URL. */
export function mediaUrl(path?: string | null): string | null {
  if (!path) return null;
  if (/^(https?:|data:|blob:)/i.test(path)) return path;
  return `${serverOrigin()}${path.startsWith('/') ? '' : '/'}${path}`;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown; error?: unknown };
    const detail = body?.detail ?? body?.error;
    if (typeof detail === 'string') return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    // not JSON
  }
  return `HTTP ${res.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    throw new ApiError(res.status, await readError(res));
  }
  return (await res.json()) as T;
}

function jsonInit(method: string, body: unknown, headers: Record<string, string> = {}): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  };
}

function qs(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

const enc = encodeURIComponent;

// ── Operator PIN (sessionStorage) ─────────────────────────────────────────

const PIN_KEY = 'nadisaathi.operatorPin';

export function getStoredPin(): string | null {
  try {
    return window.sessionStorage.getItem(PIN_KEY);
  } catch {
    return null;
  }
}

export function setStoredPin(pin: string): void {
  try {
    window.sessionStorage.setItem(PIN_KEY, pin);
  } catch {
    // storage blocked; the PIN is still used for this one call
  }
}

export function clearStoredPin(): void {
  try {
    window.sessionStorage.removeItem(PIN_KEY);
  } catch {
    // ignore
  }
}

function pinHeaders(pin: string): Record<string, string> {
  return { 'X-Operator-Pin': pin };
}

// ── Regions and rivers ────────────────────────────────────────────────────

export interface LanguageProfile {
  code: string;
  name: string;
  native_name: string;
  script?: string;
  tts?: Record<string, unknown>;
  asr?: Record<string, unknown>;
}

export interface RegionSummary {
  id: string;
  name: string;
  country_code: CountryCode;
  languages: LanguageProfile[];
  channels: string[];
  authority_roles: Array<{ id: string; name: string; approves: string[] }>;
  levels: Array<{ id: string; label: Record<string, string>; color: string }>;
  bounds?: { min_lon: number; max_lon: number; min_lat: number; max_lat: number };
}

export interface RegionProfile extends RegionSummary {
  admin_units?: unknown[];
  alert_format?: Record<string, unknown>;
  agencies?: unknown[];
}

export interface RiverSummary {
  id: string;
  name: string;
  countries: CountryCode[];
  nodes: number;
  edges: number;
}

export type RiverNodeKind = 'gauge' | 'camera' | 'barrage' | 'village' | string;

export interface RiverNode {
  id: string;
  name: string;
  country: CountryCode;
  lat?: number;
  lng?: number;
  kind: RiverNodeKind;
  river?: string;
  warning_m?: number | null;
  danger_m?: number | null;
  agency?: string;
  site_id?: string | null;
  region_id?: string;
  admin_unit?: string;
  /** Latest agent reading for this node's site, when the server includes it. */
  live?: { stage_m?: number | null; rate_m_per_h?: number | null; mode?: string; updated_at?: string } | null;
}

export interface RiverEdge {
  from: string;
  to: string;
  distance_km?: number;
  travel_time_h: Band;
  method?: string;
  source?: string;
}

export interface RiverGraph {
  id: string;
  name: string;
  nodes: RiverNode[];
  edges: RiverEdge[];
}

export interface EtaTarget {
  node_id: string;
  name: string;
  country: CountryCode;
  region_id?: string;
  eta_h: Band;
  path: string[];
  crosses_border: boolean;
}

export interface EtaResult {
  basin: string;
  from_node: string;
  computed_at: string;
  downstream: EtaTarget[];
}

export const getRegions = () => request<RegionSummary[]>('/regions');
export const getRegion = (id: string) => request<RegionProfile>(`/regions/${enc(id)}`);
export const getRivers = () => request<RiverSummary[]>('/rivers');
export const getRiver = (basin: string) => request<RiverGraph>(`/rivers/${enc(basin)}`);
export const getEta = (basin: string, fromNode: string, rateMPerH?: number | null) =>
  request<EtaResult>(`/rivers/${enc(basin)}/eta${qs({ from_node: fromNode, rate_m_per_h: rateMPerH ?? undefined })}`);

// ── Agent ─────────────────────────────────────────────────────────────────

export type AgentMode = 'normal' | 'watch' | 'alert' | 'degraded' | string;

export interface AgentState {
  site_id: string;
  mode: AgentMode;
  cadence_s: number;
  last_stage_m?: number | null;
  last_sigma_m?: number | null;
  last_rate_m_per_h?: number | null;
  last_quality?: string | null;
  basin?: string | null;
  node_id?: string | null;
  region_id?: string | null;
  updated_at?: string | null;
}

export interface TraceSummary {
  trace_id: string;
  site_id: string;
  cycle: number;
  started_at: string;
  branches: string[];
  summary: string;
  steps: number;
  scenario_run_id?: string | null;
}

export interface Measurement {
  stage_m?: number | null;
  sigma_m?: number | null;
  rate_m_per_h?: number | null;
  usable?: boolean;
  quality?: { ok: boolean; reasons: string[] };
  estimators?: Record<string, number | null>;
  registration?: string | null;
  overlay_url?: string | null;
  frame_url?: string | null;
  timings_ms?: Record<string, number>;
}

export interface TraceDecision {
  branch?: string | null;
  reason?: string;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}

export interface TraceStep {
  i: number;
  t?: string;
  kind: 'tool' | 'decision' | 'guard' | 'approval' | 'fallback' | string;
  tool?: string | null;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  decision?: TraceDecision | null;
  latency_ms?: number | null;
  cost_usd_est?: number | null;
  model?: string | null;
  guard?: { accepted: boolean; reason?: string } | null;
}

export interface TraceDetail {
  trace_id: string;
  site_id: string;
  cycle: number;
  started_at: string;
  branches: string[];
  measurement?: Measurement | null;
  steps: TraceStep[];
  summary?: string;
  scenario_run_id?: string | null;
}

export const getAgentState = () => request<AgentState[]>('/agent/state');
export const getTraces = (opts: { siteId?: string | null; limit?: number; branch?: string | null } = {}) =>
  request<TraceSummary[]>(`/agent/traces${qs({ site_id: opts.siteId ?? undefined, limit: opts.limit ?? 50, branch: opts.branch ?? undefined })}`);
export const getTrace = (traceId: string) => request<TraceDetail>(`/agent/traces/${enc(traceId)}`);

export function runAgentCycle(siteId: string, frames: File[]): Promise<TraceDetail> {
  const form = new FormData();
  form.append('site_id', siteId);
  for (const frame of frames) form.append('frames', frame);
  return request<TraceDetail>('/agent/cycle', { method: 'POST', body: form });
}

// ── Approvals ─────────────────────────────────────────────────────────────

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface DraftMessage {
  lang: string;
  text: string;
  chars?: number;
  segments?: number;
}

export interface Approval {
  scenario_run_id?: string | null;
  id: number;
  created_at: string;
  status: ApprovalStatus | string;
  action: string;
  site_id?: string | null;
  region_id?: string | null;
  role?: string | null;
  role_label?: string | null;
  title: string;
  rationale?: string | null;
  trace_id?: string | null;
  payload?: {
    messages?: DraftMessage[];
    audio?: Array<{ lang: string; url: string }>;
    cap_xml?: string | null;
    eta?: Band | null;
    recipients?: string | null;
    [key: string]: unknown;
  } | null;
  evidence?: Array<{ label: string; value: string; source?: string | null }>;
  decided_by?: string | null;
  decided_at?: string | null;
  decision_note?: string | null;
  dispatch?: Record<string, string> | null;
}

export interface ApprovalDecision {
  decision: 'approve' | 'reject';
  operator: string;
  note?: string;
  edited_messages?: Array<{ lang: string; text: string }>;
}

export const getApprovals = (status: ApprovalStatus | 'all' = 'pending') =>
  request<Approval[]>(`/approvals${qs({ status })}`);

export const decideApproval = (id: number, body: ApprovalDecision, pin: string) =>
  request<Approval>(`/approvals/${id}/decision`, jsonInit('POST', body, pinHeaders(pin)));

// ── Scenario replays ──────────────────────────────────────────────────────

export interface Scenario {
  id: string;
  title: string;
  description?: string;
  basin?: string;
  label: string;
  /** Number of steps, or a description when the agent's cadence decides. */
  steps?: number | string;
  /** Site the replay drives; used to pick the camera to watch. */
  site_id?: string | null;
  warning_m?: number | null;
  danger_m?: number | null;
  /** True for replays of real camera footage (e.g. USGS HIVIS frames). */
  real?: boolean;
  duration_min?: number;
  /** Disturbances scripted into the replay (rain on the lens, camera knocked...). */
  events?: Array<{ t_from_min: number; t_to_min: number; tag: string }>;
}

export interface ScenarioRun {
  run_id: string;
  scenario_id?: string;
  status: 'running' | 'done' | 'failed' | string;
  step?: number;
  total?: number;
  trace_ids?: string[];
  approval_ids?: number[];
  error?: string | null;
  /** Optional; used when present. */
  site_id?: string | null;
  label?: string;
  sim_minutes?: number;
}

export interface SeriesPoint {
  t: string;
  stage_m: number;
  sigma_m?: number | null;
  usable?: boolean;
  filtered_stage_m?: number | null;
}

export interface SiteLive {
  site: { id: string; name: string; region?: string };
  warning_m?: number | null;
  danger_m?: number | null;
  latest?: {
    at?: string;
    frame_url?: string | null;
    overlay_url?: string | null;
    stage_m?: number | null;
    sigma_m?: number | null;
    rate_m_per_h?: number | null;
    quality_ok?: boolean;
    quality_reasons?: string[];
    usable?: boolean;
  } | null;
  series?: SeriesPoint[];
  agent?: { mode: AgentMode; cadence_s: number } | null;
}

export const getScenarios = () => request<Scenario[]>('/scenarios');
export const runScenario = (id: string, speed = 1.0) =>
  request<ScenarioRun>(`/scenarios/${enc(id)}/run`, jsonInit('POST', { speed }));
export const getScenarioRun = (runId: string) => request<ScenarioRun>(`/scenarios/runs/${enc(runId)}`);
export const getSiteLive = (siteId: string) => request<SiteLive>(`/sites/${enc(siteId)}/live`);

// ── Relief ────────────────────────────────────────────────────────────────

export type ReliefNeed = 'rescue' | 'food' | 'water' | 'medical' | 'shelter' | 'other';
export type Urgency = 'critical' | 'high' | 'medium' | 'low';

export interface ReliefRequestInput {
  text: string;
  lang: 'hi' | 'ne' | 'en' | 'mai' | 'bho';
  lat?: number | null;
  lng?: number | null;
  site_id?: string | null;
  channel: 'app' | 'sms' | 'voice';
  people?: number | null;
  /** Optional hint from the form; the server may parse its own. */
  need?: ReliefNeed | null;
}

export interface ReliefRequest {
  id: number;
  need: ReliefNeed | string;
  people?: number | null;
  urgency: Urgency | string;
  priority: number;
  duplicate_of?: number | null;
  status: string;
  parsed_by?: string;
  text?: string;
  lang?: string;
  lat?: number | null;
  lng?: number | null;
  created_at?: string;
  team?: string | null;
}

export interface PhotoCheckResult {
  approval_id?: number;
  branch?: string;
  water_fraction?: number;
  waterline_y?: number | null;
  submerged_frac?: number | null;
  est_depth_m?: number | null;
  depth_pm_m?: number | null;
  passable: 'no' | 'yes' | 'unknown' | string;
  confidence?: number;
  needs_review?: boolean;
  overlay_url?: string | null;
  faces_blurred?: number;
}

export interface PhotoCheckInput {
  photo: File;
  refTop?: { x: number; y: number } | null;
  refBottom?: { x: number; y: number } | null;
  refHeightM?: number | null;
  routeId?: string | null;
}

export interface RouteStatus {
  id: string;
  name: string;
  status: 'passable' | 'blocked' | 'unknown' | string;
  verified?: boolean;
  updated_at?: string;
  source?: string;
}

export interface Shelter {
  id: string;
  name: string;
  region_id?: string;
  admin_unit?: string;
  lat?: number;
  lng?: number;
  capacity?: number | null;
  occupancy?: number | null;
}

export interface Sitrep {
  region_id: string;
  generated_at: string;
  text: string;
  numbers: Array<{ value: string; label: string; source?: string }>;
  model?: string;
  fallback_used?: boolean;
}

export interface EvidenceItem {
  key: string;
  label: string;
  value: number;
  unit?: string;
  baseline?: { name: string; value: number } | null;
  dataset?: string;
  file?: string;
  note?: string | null;
}

export const createReliefRequest = (body: ReliefRequestInput) =>
  request<ReliefRequest>('/relief/requests', jsonInit('POST', body));
export const getReliefRequests = () => request<ReliefRequest[]>('/relief/requests');
export const decideReliefRequest = (
  id: number,
  body: { decision: 'approve' | 'reject'; operator: string; team?: string },
  pin: string,
) => request<ReliefRequest>(`/relief/requests/${id}/decision`, jsonInit('POST', body, pinHeaders(pin)));

export function photoCheck(input: PhotoCheckInput): Promise<PhotoCheckResult> {
  const form = new FormData();
  form.append('photo', input.photo);
  if (input.refTop && input.refBottom) {
    form.append('ref_top_x', String(Math.round(input.refTop.x)));
    form.append('ref_top_y', String(Math.round(input.refTop.y)));
    form.append('ref_bottom_x', String(Math.round(input.refBottom.x)));
    form.append('ref_bottom_y', String(Math.round(input.refBottom.y)));
    form.append('ref_height_m', String(input.refHeightM ?? 1.0));
  }
  if (input.routeId) form.append('route_id', input.routeId);
  return request<PhotoCheckResult>('/relief/photo-check', { method: 'POST', body: form });
}

export const getRoutes = () => request<RouteStatus[]>('/relief/routes');
export const getShelters = (regionId?: string | null) =>
  request<Shelter[]>(`/relief/shelters${qs({ region_id: regionId ?? undefined })}`);
export const getSitrep = (regionId: string) => request<Sitrep>(`/sitrep/${enc(regionId)}`);
export const getEvidence = () =>
  request<{ generated_from: string[]; items: EvidenceItem[] }>('/evidence');

// ── Small helpers used by several pages ───────────────────────────────────

/** "tr_abc#2" → { traceId: "tr_abc", step: 2 }. Returns null for other sources. */
export function parseTraceSource(source?: string | null): { traceId: string; step: number | null } | null {
  if (!source) return null;
  const match = /^(tr_[^#\s]+)(?:#(\d+))?$/.exec(source.trim());
  if (!match) return null;
  return { traceId: match[1], step: match[2] !== undefined ? Number(match[2]) : null };
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export interface RedTeamResult {
  trace_id: string;
  truth_stage_m: number;
  opencv_stage_m: number | null;
  vlm_parsed: { stage_m?: number | null; ok?: boolean; reason?: string } | null;
  vlm_accepted: boolean;
  guard_reason: string | null;
  siren_fired: boolean;
  branches: string[];
  verdict: string;
}

export const redTeam = (reply: string) => request<RedTeamResult>('/agent/red-team', jsonInit('POST', { reply }));
