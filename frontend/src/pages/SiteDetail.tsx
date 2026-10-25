import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { API_BASE, useAppStore, type Site } from '../store';
import {
  CheckCircle2,
  CloudRain,
  FileText,
  Gauge,
  LoaderCircle,
  PlayCircle,
  Save,
  Send,
  Siren,
  TriangleAlert,
  Upload,
  Video,
  Waves,
} from 'lucide-react';

type SeverityLevel = 'minor' | 'moderate' | 'severe';

function alertLevelToSeverity(level: string): SeverityLevel {
  const l = level.toLowerCase();
  if (l === 'red') return 'severe';
  if (l === 'orange') return 'moderate';
  if (l === 'yellow') return 'minor';
  return 'minor';
}

interface Calibration {
  roi_polygon?: number[][] | null;
  critical_line?: number[][] | null;
  reference_line?: number[][] | null;
  notes?: string | null;
}

interface SiteDetailPayload extends Site {
  sample_video_source_url?: string | null;
  sample_video_url?: string | null;
  sample_frame_url?: string | null;
}

function parsePoints(raw?: string | null): number[][] | null {
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as number[][];
  } catch {
    return null;
  }
}

interface HydrometSnapshot {
  site_id: string;
  signal_score: number;
  summary: string;
  precipitation_mm: number;
  precipitation_probability: number;
  river_discharge?: number | null;
  river_discharge_max?: number | null;
  river_discharge_trend?: number | null;
}

interface NodeAnalysisResponse {
  observation: {
    frames_analyzed: number;
    waterline_ratio: number;
    rise_velocity: number;
    confidence: number;
    crossed_critical_line: boolean;
    evidence_frame_url?: string | null;
    image_description?: string | null;
    image_assessment_model?: string | null;
    image_assessment_confidence?: number | null;
    image_water_visible?: boolean | null;
    image_infrastructure_at_risk?: boolean | null;
  };
  alert: {
    id?: number;
    level: string;
    score: number;
    summary: string;
    reasoning_summary?: string | null;
    reasoning_chain?: string | null;
    reasoning_model?: string | null;
  };
  sample_video_source_url?: string | null;
}

function parseChain(raw?: string | null): string[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.map((x) => String(x)) : [];
  } catch {
    return [];
  }
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}

function toAssetUrl(assetPath?: string | null) {
  if (!assetPath) {
    return null;
  }
  if (assetPath.startsWith('http://') || assetPath.startsWith('https://')) {
    return assetPath;
  }
  const apiOrigin = API_BASE.replace(/\/api\/?$/, '');
  return `${apiOrigin}${assetPath}`;
}

export default function SiteDetail() {
  const { id } = useParams();
  const [site, setSite] = useState<SiteDetailPayload | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [snapshot, setSnapshot] = useState<HydrometSnapshot | null>(null);
  const [nodeVideo, setNodeVideo] = useState<File | null>(null);
  const [analysisResult, setAnalysisResult] = useState<NodeAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isAnalyzingSample, setIsAnalyzingSample] = useState(false);
  const [isEmittingCap, setIsEmittingCap] = useState(false);
  const [capXml, setCapXml] = useState<string | null>(null);
  const [isExportingSinagir, setIsExportingSinagir] = useState(false);
  const [sinagirJson, setSinagirJson] = useState<string | null>(null);
  const [actionLog, setActionLog] = useState<string[]>([]);
  const emitCap = useAppStore((s) => s.emitCap);

  const pushAction = (msg: string) => {
    const t = new Date().toLocaleTimeString();
    setActionLog((prev) => [`${t}  ${msg}`, ...prev].slice(0, 6));
  };

  const hasSite = Boolean(id);

  const criticalLineText = useMemo(() => {
    if (!calibration?.critical_line || calibration.critical_line.length < 2) {
      return 'Default line from backend';
    }
    return calibration.critical_line.map((point) => `(${point[0]}, ${point[1]})`).join(' -> ');
  }, [calibration]);

  const sampleFrameUrl = toAssetUrl(site?.sample_frame_url);
  const evidenceFrameUrl = toAssetUrl(analysisResult?.observation.evidence_frame_url);

  useEffect(() => {
    if (!id) {
      return;
    }

    const load = async () => {
      setError(null);
      try {
        const [siteRes, calibrationRes, snapshotRes] = await Promise.all([
          fetch(`${API_BASE}/sites/${id}`),
          fetch(`${API_BASE}/sites/${id}/calibration`),
          fetch(`${API_BASE}/sites/${id}/external-snapshot`),
        ]);

        if (!siteRes.ok) {
          throw new Error('Could not load site');
        }
        setSite(await siteRes.json());

        if (calibrationRes.ok) {
          const calibrationPayload = await calibrationRes.json();
          setCalibration({
            roi_polygon: parsePoints(calibrationPayload.roi_polygon),
            critical_line: parsePoints(calibrationPayload.critical_line),
            reference_line: parsePoints(calibrationPayload.reference_line),
            notes: calibrationPayload.notes,
          });
        } else {
          setCalibration(null);
        }

        if (snapshotRes.ok) {
          setSnapshot(await snapshotRes.json());
        } else {
          setSnapshot(null);
        }
      } catch (loadError) {
        console.error(loadError);
        setError('Failed to load site detail.');
      }
    };

    load();
  }, [id]);

  const refreshHydromet = async () => {
    if (!id) {
      return;
    }

    setIsRefreshing(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/sites/${id}/external-snapshot/refresh`, {
        method: 'POST',
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || 'Hydromet refresh failed');
      }
      setSnapshot(await response.json());
    } catch (refreshError) {
      console.error(refreshError);
      setError(refreshError instanceof Error ? refreshError.message : 'Hydromet refresh failed.');
    } finally {
      setIsRefreshing(false);
    }
  };

  const runNodeAnalysis = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!id || !nodeVideo) {
      return;
    }

    setIsAnalyzing(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('site_id', id);
      formData.append('video', nodeVideo);

      const response = await fetch(`${API_BASE}/node/analyze`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setAnalysisResult(await response.json());
    } catch (analysisError) {
      console.error(analysisError);
      setError('Node analysis failed. Upload a short fixed-camera clip and try again.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleEmitCap = async () => {
    if (!site || !analysisResult) return;
    setIsEmittingCap(true);
    setError(null);
    try {
      const severity = alertLevelToSeverity(analysisResult.alert.level);
      const xml = await emitCap({
        site_id: site.id,
        lat: site.lat,
        lon: site.lng,
        severity,
        headline: `${severity} alert at ${site.name}`,
        instruction: 'Coordinate with Civil Defense before public dissemination.',
        summary: analysisResult.alert.summary,
        areaDesc: site.region,
      });
      setCapXml(xml);
      pushAction(`CAP XML emitted (${severity}) for ${site.name}`);
    } catch (capError) {
      console.error(capError);
      setError('Could not emit CAP. Check backend.');
    } finally {
      setIsEmittingCap(false);
    }
  };

  const handleExportSinagir = async () => {
    if (!analysisResult?.alert?.id) return;
    setIsExportingSinagir(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/alerts/${analysisResult.alert.id}/export-sinagir`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error(await res.text());
      const json = await res.text();
      setSinagirJson(json);
      pushAction(`SINAGIR JSON exported for alert #${analysisResult.alert.id}`);
    } catch (e) {
      console.error(e);
      setError('Could not export SINAGIR.');
    } finally {
      setIsExportingSinagir(false);
    }
  };

  const simulateSiren = () => pushAction('Siren: SIMULATED trigger (demo, no real actuator)');
  const simulateLora = () => pushAction('LoRa: SIMULATED payload emitted (demo, no real radio)');
  const simulateNotify = () => pushAction('Notification: SIMULATED push to operator (demo)');

  const runBundledSample = async () => {
    if (!id) {
      return;
    }

    setIsAnalyzingSample(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/sites/${id}/sample-node-analysis`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setAnalysisResult(await response.json());
    } catch (analysisError) {
      console.error(analysisError);
      setError('Bundled sample analysis failed. Confirm the demo clip exists on disk.');
    } finally {
      setIsAnalyzingSample(false);
    }
  };

  if (!hasSite) {
    return <div className="p-6 text-gray-600">Missing site identifier.</div>;
  }

  return (
    <div className="space-y-6 pb-20">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{site?.name ?? id}</h2>
          <p className="text-gray-500 mt-1">{site?.region ?? 'Loading region...'}</p>
          {site?.description && <p className="text-sm text-gray-600 mt-2 max-w-2xl">{site.description}</p>}
        </div>
        <Link
          to={`/sites/${id}/calibrate`}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 hover:border-blue-300 hover:text-blue-700"
        >
          <Save className="w-4 h-4" /> Adjust calibration
        </Link>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <TriangleAlert className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4 mb-4">
            <div>
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <CloudRain className="w-5 h-5 text-blue-600" /> Live hydromet context
              </h3>
              <p className="text-sm text-gray-500 mt-1">Open-Meteo weather + flood snapshot for this site.</p>
            </div>
            <button
              onClick={refreshHydromet}
              disabled={isRefreshing}
              className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isRefreshing ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>

          {snapshot ? (
            <div className="space-y-3 text-sm text-gray-700">
              <div className="rounded-lg bg-blue-50 p-3 border border-blue-100">
                <div className="text-xs uppercase tracking-wide text-blue-700 font-semibold">Signal score</div>
                <div className="mt-1 text-2xl font-bold text-blue-900">{formatPercent(snapshot.signal_score)}</div>
              </div>
              <div>{snapshot.summary}</div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-gray-50 p-3 border border-gray-100">
                  <div className="text-xs text-gray-500">Rain now</div>
                  <div className="font-semibold">{snapshot.precipitation_mm.toFixed(1)} mm</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3 border border-gray-100">
                  <div className="text-xs text-gray-500">12h rain probability</div>
                  <div className="font-semibold">{snapshot.precipitation_probability.toFixed(0)}%</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3 border border-gray-100 col-span-2">
                  <div className="text-xs text-gray-500">River discharge</div>
                  <div className="font-semibold">
                    {snapshot.river_discharge != null ? `${snapshot.river_discharge.toFixed(1)} m3/s` : 'Unavailable'}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No stored snapshot yet. Refresh to fetch live hydromet data.</p>
          )}
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
            <Gauge className="w-5 h-5 text-amber-600" /> Calibration summary
          </h3>
          <p className="text-sm text-gray-500 mb-4">The node analysis uses the latest stored ROI and threshold lines.</p>
          <div className="space-y-3 text-sm text-gray-700">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Critical line</div>
              <div className="font-mono text-xs mt-1">{criticalLineText}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Notes</div>
              <div className="mt-1">{calibration?.notes ?? 'No notes stored. Backend will fall back to defaults.'}</div>
            </div>
          </div>
          {sampleFrameUrl && (
            <div className="mt-4 rounded-xl border border-gray-200 overflow-hidden bg-gray-50">
              <img src={sampleFrameUrl} alt="Sample frame used for site calibration" className="w-full object-cover" />
              <div className="px-4 py-3 text-xs text-gray-600 flex items-center justify-between gap-3 flex-wrap">
                <span>Reference frame stored for this site calibration.</span>
                {site?.sample_video_source_url && (
                  <a
                    href={site.sample_video_source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-blue-700 hover:text-blue-800"
                  >
                    Source
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
          <div>
            <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <Upload className="w-5 h-5 text-orange-600" /> Fixed-node video analysis
            </h3>
            <p className="text-sm text-gray-500">
              Upload a short clip from a fixed camera or run the bundled site clip. The backend samples roughly 1 FPS, searches within the calibrated band and recomputes the fused site alert.
            </p>
          </div>
          {site?.sample_video_url && (
            <button
              onClick={runBundledSample}
              disabled={isAnalyzingSample}
              className="inline-flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-2.5 text-sm font-semibold text-orange-700 hover:bg-orange-100 disabled:opacity-50"
            >
              {isAnalyzingSample ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
              {isAnalyzingSample ? 'Running sample...' : 'Analyze bundled sample'}
            </button>
          )}
        </div>

        <form onSubmit={runNodeAnalysis} className="space-y-4">
          <input
            type="file"
            accept="video/*"
            onChange={(event) => setNodeVideo(event.target.files?.[0] ?? null)}
            className="w-full text-sm text-gray-500 file:mr-4 file:rounded-full file:border-0 file:bg-orange-50 file:px-4 file:py-2 file:font-semibold file:text-orange-700 hover:file:bg-orange-100"
          />
          <button
            type="submit"
            disabled={!nodeVideo || isAnalyzing}
            className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {isAnalyzing ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {isAnalyzing ? 'Analyzing...' : 'Analyze uploaded clip'}
          </button>
        </form>

        {analysisResult && (
          <div className="mt-5 grid gap-4 lg:grid-cols-[0.9fr,1.1fr]">
            <div className="space-y-4">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                <div className="font-semibold text-gray-900 mb-2">Node metrics</div>
                <div>Frames analyzed: {analysisResult.observation.frames_analyzed}</div>
                <div>Waterline ratio: {analysisResult.observation.waterline_ratio.toFixed(2)}</div>
                <div>Rise velocity: {analysisResult.observation.rise_velocity.toFixed(4)}</div>
                <div>Confidence: {formatPercent(analysisResult.observation.confidence)}</div>
                <div>Critical crossed: {analysisResult.observation.crossed_critical_line ? 'Yes' : 'No'}</div>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                <div className="font-semibold text-gray-900 mb-2">Resulting alert</div>
                <div className="capitalize">Level: {analysisResult.alert.level}</div>
                <div>Score: {formatPercent(analysisResult.alert.score)}</div>
                <div className="mt-2">{analysisResult.alert.summary}</div>
                {analysisResult.alert.reasoning_summary && (
                  <details className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
                    <summary className="cursor-pointer font-semibold text-blue-800">
                      Gemma reasoning ({analysisResult.alert.reasoning_model ?? 'local'})
                    </summary>
                    <p className="mt-2 whitespace-pre-wrap">{analysisResult.alert.reasoning_summary}</p>
                    {parseChain(analysisResult.alert.reasoning_chain).length > 0 && (
                      <ol className="mt-2 list-decimal pl-5 text-xs text-blue-900/80">
                        {parseChain(analysisResult.alert.reasoning_chain).map((step, i) => (
                          <li key={i}>{step}</li>
                        ))}
                      </ol>
                    )}
                  </details>
                )}
                {analysisResult.sample_video_source_url && (
                  <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
                    <Video className="w-4 h-4" /> Sample source connected from the official provider page.
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 overflow-hidden bg-gray-50">
              {evidenceFrameUrl ? (
                <div className="relative">
                  <img src={evidenceFrameUrl} alt="Evidence frame with calibration overlays" className="w-full object-cover" />
                  {analysisResult.observation.image_description && (
                    <div className="absolute inset-x-0 bottom-0 bg-black/70 text-white text-xs px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold">
                          Gemma ({analysisResult.observation.image_assessment_model ?? 'local'})
                        </span>
                        {typeof analysisResult.observation.image_assessment_confidence === 'number' && (
                          <span>conf {formatPercent(analysisResult.observation.image_assessment_confidence)}</span>
                        )}
                      </div>
                      <p className="mt-1 opacity-95">{analysisResult.observation.image_description}</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full min-h-[240px] flex items-center justify-center text-sm text-gray-500 px-6 text-center">
                  The backend stored an analysis result, but no evidence frame URL was returned.
                </div>
              )}
            </div>
          </div>
        )}

        {analysisResult && (
          <div className="mt-6 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
              <h4 className="font-semibold text-gray-900 flex items-center gap-2">
                <Siren className="w-5 h-5 text-orange-500" /> Command center
              </h4>
              <span className="text-xs text-gray-500">
                Siren / LoRa / Notify are demo-simulated. CAP + SINAGIR hit the real backend.
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleEmitCap}
                disabled={isEmittingCap || !site}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {isEmittingCap ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                Emit CAP
              </button>
              <button
                onClick={handleExportSinagir}
                disabled={isExportingSinagir || !analysisResult.alert.id}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-800 hover:border-blue-300 hover:text-blue-700 disabled:opacity-50"
                title={analysisResult.alert.id ? '' : 'Backend did not return an alert id'}
              >
                <FileText className="w-4 h-4" /> Export SINAGIR
              </button>
              <button
                onClick={simulateSiren}
                className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-3 py-2 text-sm font-semibold text-white hover:bg-orange-700"
              >
                <Siren className="w-4 h-4" /> Trigger siren (sim)
              </button>
              <button
                onClick={simulateLora}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-800 hover:border-blue-300 hover:text-blue-700"
              >
                <Waves className="w-4 h-4" /> Send LoRa (sim)
              </button>
              <button
                onClick={simulateNotify}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-800 hover:border-blue-300 hover:text-blue-700"
              >
                <CheckCircle2 className="w-4 h-4" /> Notify operator (sim)
              </button>
            </div>

            {actionLog.length > 0 && (
              <ol className="mt-4 space-y-1 text-xs text-gray-600 font-mono">
                {actionLog.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ol>
            )}

            {capXml && (
              <details className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-gray-800">CAP XML payload</summary>
                <pre className="mt-2 overflow-x-auto text-xs text-gray-700 whitespace-pre-wrap">{capXml}</pre>
              </details>
            )}
            {sinagirJson && (
              <details className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-gray-800">SINAGIR JSON</summary>
                <pre className="mt-2 overflow-x-auto text-xs text-gray-700 whitespace-pre-wrap">{sinagirJson}</pre>
              </details>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
