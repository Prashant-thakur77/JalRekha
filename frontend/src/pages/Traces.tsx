import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, RefreshCw } from 'lucide-react';
import { errorMessage, getAgentState, getTraces, type AgentState, type TraceSummary } from '../api';
import { useI18n } from '../i18n';
import { fmtDateTime } from '../lib/format';
import { BranchChip, Chip, PageHeader, StateNotice } from '../components/ui';
import RedTeam from '../components/RedTeam';

export default function Traces() {
  const { t } = useI18n();
  const [siteId, setSiteId] = useState('');
  const [branch, setBranch] = useState('');
  const [sites, setSites] = useState<AgentState[]>([]);
  const [traces, setTraces] = useState<TraceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (site: string, br: string) =>
      getTraces({ siteId: site || null, limit: 50, branch: br || null }).then(
        (list) => {
          setTraces(Array.isArray(list) ? list : []);
          setError(null);
        },
        (err: unknown) => setError(errorMessage(err)),
      ),
    [],
  );

  useEffect(() => {
    void load(siteId, branch);
  }, [load, siteId, branch]);

  useEffect(() => {
    getAgentState()
      .then((list) => setSites(Array.isArray(list) ? list : []))
      .catch(() => setSites([]));
  }, []);

  return (
    <div className="ns-page">
      <PageHeader
        title={t('trace.title')}
        subtitle={t('trace.subtitle')}
        actions={
          <button type="button" className="ns-btn ns-btn--secondary" onClick={() => void load(siteId, branch)}>
            <RefreshCw className="w-4 h-4" aria-hidden="true" /> {t('common.refresh')}
          </button>
        }
      />
      <RedTeam />
      <div className="ns-field ns-field--inline">
        <label htmlFor="trace-branch">{t('trace.branchFilter')}</label>
        <select id="trace-branch" className="ns-input" value={branch} onChange={(e) => setBranch(e.target.value)}>
          <option value="">{t('trace.allBranches')}</option>
          {['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9'].map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>
      </div>
      {sites.length > 0 && (
        <div className="ns-field ns-field--inline">
          <label htmlFor="trace-site">{t('common.site')}</label>
          <select id="trace-site" className="ns-input" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">{t('common.allSites')}</option>
            {sites.map((s) => (
              <option key={s.site_id} value={s.site_id}>
                {s.site_id}
              </option>
            ))}
          </select>
        </div>
      )}

      {error && <StateNotice kind="error" message={t('trace.loadError')} detail={error} onRetry={() => void load(siteId, branch)} />}
      {!error && traces === null && <StateNotice kind="loading" message={t('common.loading')} />}
      {!error && traces?.length === 0 && <StateNotice kind="empty" message={t('trace.empty')} />}
      {traces && traces.length > 0 && (
        <ul className="ns-list">
          {traces.map((tr) => (
            <li key={tr.trace_id}>
              <Link to={`/traces/${encodeURIComponent(tr.trace_id)}`} className="ns-list__link">
                <div className="min-w-0 ns-stack-sm">
                  <div className="ns-row ns-wrap ns-hint">
                    <time dateTime={tr.started_at}>{fmtDateTime(tr.started_at)}</time>
                    <span>· {tr.site_id}</span>
                    <span>· {t('trace.cycle', { n: tr.cycle })}</span>
                    <span>· {t('trace.steps', { n: tr.steps })}</span>
                    {tr.scenario_run_id && <Chip tone="replay">{t('trace.replay')}</Chip>}
                  </div>
                  <p className="ns-strong">{tr.summary}</p>
                  {(tr.branches ?? []).length > 0 && (
                    <div className="ns-row ns-wrap">
                      {tr.branches.map((b) => (
                        <BranchChip key={b} branch={b} showName />
                      ))}
                    </div>
                  )}
                </div>
                <ChevronRight className="w-5 h-5 shrink-0" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
