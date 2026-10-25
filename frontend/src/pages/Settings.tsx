import { useEffect, useState } from 'react';
import { API_BASE, useAppStore } from '../store';
import { CheckCircle2, Cpu, ServerCrash, UploadCloud, Waves } from 'lucide-react';

interface RuntimeStatus {
  is_online: boolean;
  llm: {
    enabled: boolean;
    reachable: boolean;
    base_url: string;
    model: string;
    detail: string;
  };
  node?: {
    node_profile: string;
    provider: string;
    backend: string;
    vision_backend: string;
    multimodal_backend: string;
    multimodal_vision_backend: string;
    speculative_decoding: boolean;
    max_output_tokens: number;
    multimodal_max_output_tokens: number;
    engine_ready: boolean;
    engine_detail: string;
    counts_for_p1: boolean;
    model_path: string;
    cache_dir: string;
    data_dir: string;
    multimodal_enabled: boolean;
    multimodal_verifier_enabled: boolean;
    multimodal_base_url: string;
    multimodal_model: string;
    multimodal_min_interval_seconds: number;
    multimodal_score_threshold: number;
    multimodal_confidence_threshold: number;
    multimodal_image_max_side: number;
    multimodal_max_frames: number;
    multimodal_frame_sample_seconds: number;
    multimodal_num_ctx: number;
    multimodal_timeout_seconds: number;
    max_curated_frames: number;
    artifact_retention_days: number;
  };
  hydromet: {
    enabled: boolean;
    reachable: boolean;
    detail: string;
  };
}

export default function Settings() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { syncStatus, fetchSyncStatus, flushQueue, queueCount } = useAppStore();
  const [isFlushing, setIsFlushing] = useState(false);

  useEffect(() => {
    const loadRuntime = async () => {
      try {
        const response = await fetch(`${API_BASE}/settings/runtime`);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        setRuntime(await response.json());
      } catch (loadError) {
        console.error(loadError);
        setError('Could not load runtime status.');
      }
    };

    loadRuntime();
    fetchSyncStatus();
    const interval = setInterval(fetchSyncStatus, 8000);
    return () => clearInterval(interval);
  }, [fetchSyncStatus]);

  const onFlush = async () => {
    setIsFlushing(true);
    try {
      await flushQueue();
      await fetchSyncStatus();
    } finally {
      setIsFlushing(false);
    }
  };

  const nodeReadyLabel = runtime?.node?.provider === 'ollama'
    ? 'Ollama dev runtime ready'
    : 'LiteRT runtime ready';
  const nodeNotReadyLabel = runtime?.node?.provider === 'ollama'
    ? 'Ollama dev runtime not ready'
    : 'LiteRT runtime not ready';

  return (
    <div className="space-y-6 pb-20">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Runtime Status</h2>
        <p className="text-sm text-gray-500 mt-1">
          Fixed JalRekha Node runtime plus live hydromet enrichment.
        </p>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <UploadCloud className="w-5 h-5 text-blue-600" /> Sync status
          </h3>
          <button
            onClick={onFlush}
            disabled={isFlushing || queueCount === 0}
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {isFlushing ? 'Flushing...' : `Flush queue (${queueCount})`}
          </button>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3">
            <div className="text-xs uppercase tracking-wide text-yellow-700 font-semibold">Pending</div>
            <div className="mt-1 text-xl font-bold text-yellow-900">{syncStatus?.pending ?? 0}</div>
          </div>
          <div className="rounded-lg border border-green-200 bg-green-50 p-3">
            <div className="text-xs uppercase tracking-wide text-green-700 font-semibold">Sincronizado</div>
            <div className="mt-1 text-xl font-bold text-green-900">{syncStatus?.synced ?? 0}</div>
          </div>
          <div className="rounded-lg border border-red-200 bg-red-50 p-3">
            <div className="text-xs uppercase tracking-wide text-red-700 font-semibold">Failed</div>
            <div className="mt-1 text-xl font-bold text-red-900">{syncStatus?.failed ?? 0}</div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-600" /> JalRekha Volunteer / dev runtime
          </h3>
          {runtime ? (
            <div className="mt-4 space-y-3 text-sm text-gray-700">
              <div className="flex items-center gap-2">
                {runtime.llm.reachable ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <ServerCrash className="w-4 h-4 text-red-600" />}
                <span>{runtime.llm.reachable ? 'LLM endpoint reachable' : 'LLM endpoint not reachable'}</span>
              </div>
              <div><span className="text-gray-500">Enabled:</span> {runtime.llm.enabled ? 'Yes' : 'No'}</div>
              <div><span className="text-gray-500">Base URL:</span> {runtime.llm.base_url}</div>
              <div><span className="text-gray-500">Model:</span> {runtime.llm.model}</div>
              <div><span className="text-gray-500">Detail:</span> {runtime.llm.detail}</div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-500">Loading runtime status...</p>
          )}
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Waves className="w-5 h-5 text-cyan-600" /> Hydromet provider
          </h3>
          {runtime ? (
            <div className="mt-4 space-y-3 text-sm text-gray-700">
              <div className="flex items-center gap-2">
                {runtime.hydromet.reachable ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <ServerCrash className="w-4 h-4 text-red-600" />}
                <span>{runtime.hydromet.reachable ? 'Provider reachable' : 'Provider not reachable'}</span>
              </div>
              <div><span className="text-gray-500">Enabled:</span> {runtime.hydromet.enabled ? 'Yes' : 'No'}</div>
              <div><span className="text-gray-500">Detail:</span> {runtime.hydromet.detail}</div>
              <div><span className="text-gray-500">Backend connectivity toggle:</span> {runtime.is_online ? 'Online' : 'Offline'}</div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-500">Loading provider status...</p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm space-y-4">
        <h3 className="font-semibold text-gray-900">JalRekha Node setup</h3>
        <p className="text-sm text-gray-600">
          The fixed JalRekha Node now targets an embedded LiteRT-LM runtime with Gemma 4 E2B. The Pi 8 profile is a minimum
          demo with one small frame every few minutes; the Pi 16/prod profile uses more frames and context. `JALREKHA_NODE_PROVIDER=ollama`
          remains a development-only JalRekha Node path plus the standard JalRekha Volunteer/local experimentation path.
        </p>
        {runtime?.node && (
          <div className="grid gap-3 text-sm text-gray-700 sm:grid-cols-2">
            <div><span className="text-gray-500">Node profile:</span> {runtime.node.node_profile}</div>
            <div><span className="text-gray-500">Provider:</span> {runtime.node.provider}</div>
            <div><span className="text-gray-500">Backend:</span> {runtime.node.backend}</div>
            <div><span className="text-gray-500">Vision backend:</span> {runtime.node.vision_backend}</div>
            <div><span className="text-gray-500">Multimodal backend:</span> {runtime.node.multimodal_backend}</div>
            <div><span className="text-gray-500">Multimodal vision backend:</span> {runtime.node.multimodal_vision_backend}</div>
            <div><span className="text-gray-500">Speculative decoding:</span> {runtime.node.speculative_decoding ? 'Enabled' : 'Disabled'}</div>
            <div><span className="text-gray-500">Engine output tokens:</span> {runtime.node.max_output_tokens}</div>
            <div><span className="text-gray-500">Multimodal engine tokens:</span> {runtime.node.multimodal_max_output_tokens}</div>
            <div className="flex items-center gap-2">
              {runtime.node.engine_ready ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <ServerCrash className="w-4 h-4 text-red-600" />}
              <span>{runtime.node.engine_ready ? nodeReadyLabel : nodeNotReadyLabel}</span>
            </div>
            <div><span className="text-gray-500">Counts for P1:</span> {runtime.node.counts_for_p1 ? 'Yes' : 'No'}</div>
            <div className="break-all"><span className="text-gray-500">Model path:</span> {runtime.node.model_path}</div>
            <div className="break-all"><span className="text-gray-500">Cache dir:</span> {runtime.node.cache_dir}</div>
            <div className="break-all"><span className="text-gray-500">Data dir:</span> {runtime.node.data_dir}</div>
            <div><span className="text-gray-500">Gemma multimodal:</span> {runtime.node.multimodal_enabled ? 'Enabled' : 'Disabled'}</div>
            <div className="break-all"><span className="text-gray-500">Dev multimodal URL:</span> {runtime.node.multimodal_base_url}</div>
            <div><span className="text-gray-500">Multimodal model:</span> {runtime.node.multimodal_model}</div>
            <div><span className="text-gray-500">Frames per analysis:</span> {runtime.node.multimodal_max_frames}</div>
            <div><span className="text-gray-500">Frame sample spacing:</span> {runtime.node.multimodal_frame_sample_seconds}s</div>
            <div><span className="text-gray-500">Image max side:</span> {runtime.node.multimodal_image_max_side}px</div>
            <div><span className="text-gray-500">Context:</span> {runtime.node.multimodal_num_ctx} tokens</div>
            <div><span className="text-gray-500">Timeout:</span> {runtime.node.multimodal_timeout_seconds}s</div>
            <div><span className="text-gray-500">Curated frames:</span> {runtime.node.max_curated_frames}</div>
            <div><span className="text-gray-500">Artifact retention:</span> {runtime.node.artifact_retention_days} days</div>
          </div>
        )}
        <pre className="overflow-x-auto rounded-lg bg-gray-950 p-4 text-xs text-gray-100">
{`JALREKHA_NODE_PROFILE=raspberry-pi-8gb-multimodal-demo
JALREKHA_DATA_DIR=/mnt/jalrekha/data
JALREKHA_NODE_PROVIDER=litert
JALREKHA_NODE_MODEL_PATH=backend/data/models/gemma-4-E2B-it.litertlm
JALREKHA_NODE_BACKEND=gpu
JALREKHA_NODE_MULTIMODAL_BACKEND=cpu
JALREKHA_NODE_MULTIMODAL_VISION_BACKEND=cpu
JALREKHA_NODE_CACHE_DIR=backend/data/litert-cache
JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING=true
JALREKHA_NODE_MAX_OUTPUT_TOKENS=1024
JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS=2048
JALREKHA_MULTIMODAL_ENABLED=true
JALREKHA_MULTIMODAL_VERIFIER_ENABLED=false
JALREKHA_MULTIMODAL_MODEL=gemma-4-E2B-it.litertlm
JALREKHA_MULTIMODAL_MAX_FRAMES=1
JALREKHA_MULTIMODAL_FRAME_SAMPLE_SECONDS=300
JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE=512
JALREKHA_MULTIMODAL_NUM_CTX=1024
JALREKHA_MULTIMODAL_TIMEOUT_SECONDS=300
JALREKHA_MAX_CURATED_FRAMES=1
JALREKHA_ARTIFACT_RETENTION_DAYS=3`}
        </pre>
        <p className="text-sm text-gray-600">
          Use `./scripts/run_node_pi8_multimodal_demo.sh` for the Pi 8 demo or `./scripts/run_node_pi16_multimodal_prod.sh`
          for the production profile. If the embedded model is unavailable, JalRekha Node records the prepared frames and returns a
          conservative manual-review fallback instead of silently switching to Ollama.
        </p>
      </section>
    </div>
  );
}
