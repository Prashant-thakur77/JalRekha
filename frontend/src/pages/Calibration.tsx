import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { API_BASE } from '../store';
import { LoaderCircle, Save, Undo2 } from 'lucide-react';

type Mode = 'roi' | 'critical' | 'reference' | 'done';

function toAssetUrl(assetPath?: string | null) {
  if (!assetPath) return null;
  if (assetPath.startsWith('http://') || assetPath.startsWith('https://')) return assetPath;
  return `${API_BASE.replace(/\/api\/?$/, '')}${assetPath}`;
}

export default function Calibration() {
  const { id } = useParams();
  const navigate = useNavigate();
  const imgRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [sampleFrameUrl, setSampleFrameUrl] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState({ w: 640, h: 480 });
  const [mode, setMode] = useState<Mode>('roi');
  const [roi, setRoi] = useState<number[][]>([]);
  const [criticalLine, setCriticalLine] = useState<number[][]>([]);
  const [referenceLine, setReferenceLine] = useState<number[][]>([]);
  const [notes, setNotes] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const [siteRes, calRes] = await Promise.all([
          fetch(`${API_BASE}/sites/${id}`),
          fetch(`${API_BASE}/sites/${id}/calibration`),
        ]);
        if (siteRes.ok) {
          const s = await siteRes.json();
          setSampleFrameUrl(toAssetUrl(s?.sample_frame_url));
        }
        if (calRes.ok) {
          const c = await calRes.json();
          const tryParse = (raw: string | null) => {
            if (!raw) return [];
            try { return JSON.parse(raw) as number[][]; } catch { return []; }
          };
          setRoi(tryParse(c?.roi_polygon));
          setCriticalLine(tryParse(c?.critical_line));
          setReferenceLine(tryParse(c?.reference_line));
          setNotes(c?.notes ?? '');
          if (tryParse(c?.roi_polygon).length > 0) setMode('done');
        }
      } catch (e) {
        console.error(e);
      }
    })();
  }, [id]);

  const draw = () => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !img.complete) return;
    canvas.width = img.clientWidth;
    canvas.height = img.clientHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const sx = canvas.width / naturalSize.w;
    const sy = canvas.height / naturalSize.h;
    if (roi.length > 0) {
      ctx.beginPath();
      roi.forEach(([x, y], i) => {
        const px = x * sx, py = y * sy;
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      if (mode !== 'roi' || roi.length >= 4) ctx.closePath();
      ctx.fillStyle = 'rgba(59,130,246,0.2)';
      ctx.fill();
      ctx.strokeStyle = '#1d4ed8';
      ctx.lineWidth = 2;
      ctx.stroke();
      roi.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x * sx, y * sy, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#1d4ed8';
        ctx.fill();
      });
    }
    const drawLine = (line: number[][], color: string) => {
      if (line.length < 2) {
        line.forEach(([x, y]) => {
          const ctx2 = canvas.getContext('2d')!;
          ctx2.beginPath();
          ctx2.arc(x * sx, y * sy, 4, 0, Math.PI * 2);
          ctx2.fillStyle = color;
          ctx2.fill();
        });
        return;
      }
      ctx.beginPath();
      ctx.moveTo(line[0][0] * sx, line[0][1] * sy);
      ctx.lineTo(line[1][0] * sx, line[1][1] * sy);
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.stroke();
    };
    drawLine(criticalLine, '#dc2626');
    drawLine(referenceLine, '#f59e0b');
  };

  useEffect(() => {
    draw();
  });

  const onImgLoad = () => {
    const img = imgRef.current;
    if (!img) return;
    setNaturalSize({ w: img.naturalWidth || 640, h: img.naturalHeight || 480 });
    draw();
  };

  const onCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const sx = naturalSize.w / canvas.width;
    const sy = naturalSize.h / canvas.height;
    const point: number[] = [Math.round(cx * sx), Math.round(cy * sy)];
    if (mode === 'roi') {
      setRoi([...roi, point]);
    } else if (mode === 'critical' && criticalLine.length < 2) {
      setCriticalLine([...criticalLine, point]);
    } else if (mode === 'reference' && referenceLine.length < 2) {
      setReferenceLine([...referenceLine, point]);
    }
  };

  const reset = () => {
    setRoi([]);
    setCriticalLine([]);
    setReferenceLine([]);
    setMode('roi');
  };

  const next = () => {
    if (mode === 'roi' && roi.length >= 4) setMode('critical');
    else if (mode === 'critical' && criticalLine.length === 2) setMode('reference');
    else if (mode === 'reference' && referenceLine.length === 2) setMode('done');
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!id) return;
    if (roi.length < 4) { setError('Draw an ROI polygon with at least 4 points.'); return; }
    if (criticalLine.length !== 2) { setError('Mark 2 points for the critical line.'); return; }
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      const payload = {
        roi_polygon: roi,
        critical_line: criticalLine,
        reference_line: referenceLine.length === 2 ? referenceLine : [],
        notes,
      };
      const r = await fetch(`${API_BASE}/sites/${id}/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(await r.text());
      setMessage('Calibration saved.');
      setTimeout(() => navigate(`/sites/${id}`), 700);
    } catch (e) {
      console.error(e);
      setError('Could not save calibration.');
    } finally {
      setIsSaving(false);
    }
  };

  const instruction = () => {
    if (mode === 'roi') return `Click to add ROI polygon points (${roi.length} placed, minimum 4).`;
    if (mode === 'critical') return `Click 2 points for the critical line (${criticalLine.length}/2).`;
    if (mode === 'reference') return `Click 2 points for the reference line (${referenceLine.length}/2) — optional.`;
    return 'Calibration ready. Save to apply.';
  };

  return (
    <div className="space-y-6 pb-20">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Site calibration</h2>
        <p className="text-sm text-gray-500 mt-1">
          Click on the reference frame to draw the ROI and lines. Data is saved to the same endpoint as the numeric version.
        </p>
      </div>

      {sampleFrameUrl ? (
        <section className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="relative">
            <img
              ref={imgRef}
              src={sampleFrameUrl}
              alt="Reference frame"
              onLoad={onImgLoad}
              className="w-full object-cover select-none"
              draggable={false}
            />
            <canvas
              ref={canvasRef}
              onClick={onCanvasClick}
              className="absolute inset-0 w-full h-full cursor-crosshair"
            />
          </div>
          <div className="px-5 py-3 border-t border-gray-200 text-sm text-gray-700 flex items-center justify-between flex-wrap gap-3">
            <span>{instruction()}</span>
            <div className="flex gap-2">
              <button type="button" onClick={reset} className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm hover:border-gray-400">
                <Undo2 className="w-4 h-4" /> Reset
              </button>
              <button type="button" onClick={next} disabled={mode === 'done'} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                {mode === 'roi' ? 'Next: critical line' : mode === 'critical' ? 'Next: reference' : mode === 'reference' ? 'Done' : 'Done'}
              </button>
            </div>
          </div>
        </section>
      ) : (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
          No reference frame loaded for this site. Upload one from the seed or run <code>scripts/fetch_demo_assets.py</code>.
        </div>
      )}

      <form onSubmit={save} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm space-y-4">
        <label className="block text-sm font-medium text-gray-700">
          Notes
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1 min-h-[80px] w-full rounded-lg border border-gray-300 px-3 py-2"
            placeholder="Notes on the camera, conditions, or reference marks."
          />
        </label>
        <div className="text-xs text-gray-500">
          ROI: {roi.length} points · Critical: {criticalLine.length}/2 · Reference: {referenceLine.length}/2
        </div>
        {message && <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">{message}</div>}
        {error && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</div>}
        <button
          type="submit"
          disabled={isSaving}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {isSaving ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {isSaving ? 'Saving...' : 'Save calibration'}
        </button>
      </form>
    </div>
  );
}
