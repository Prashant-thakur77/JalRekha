import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, RefreshCw } from 'lucide-react';
import { errorMessage, getAgentState, getTraces, type AgentState, type TraceSummary } from '../api';
import { useI18n } from '../i18n';
import { fmtDateTime } from '../lib/format';
import { BranchChip, Chip, PageHeader, StateNotice } from '../components/ui';
import RedTeam from '../components/RedTeam';

export default function Traces() {
  const { t, td } = useI18n();
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
      <div className="ns-filters">
        <div className="ns-filter" role="group" aria-labelledby="trace-branch-label">
          <span id="trace-branch-label" className="ns-eyebrow">{t('trace.branchFilter')}</span>
          <div className="ns-pills">
            {['', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9'].map((b) => (
              <button
                key={b || 'all'}
                type="button"
                className="ns-pill"
                aria-pressed={branch === b}
                title={b ? td(`branch.${b}`, b) : undefined}
                onClick={() => setBranch(b)}
              >
                {b || t('trace.allBranches')}
              </button>
            ))}
          </div>
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
      </div>

      {error && <StateNotice kind="error" message={t('trace.loadError')} detail={error} onRetry={() => void load(siteId, branch)} />}
      {!error && traces === null && <StateNotice kind="loading" message={t('common.loading')} />}
      {!error && traces?.length === 0 && <StateNotice kind="empty" message={t('trace.empty')} />}
      {traces && traces.length > 0 && (
        <div className="ns-dtable-card">
          <table className="ns-dtable ns-dtable--rows">
            <caption className="sr-only">{t('trace.title')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('trace.colTime')}</th>
                <th scope="col">{t('trace.colSite')}</th>
                <th scope="col" className="ns-num">{t('trace.colCycle')}</th>
                <th scope="col">{t('trace.colSummary')}</th>
                <th scope="col" className="ns-num">{t('trace.timeline')}</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((tr) => (
                <tr key={tr.trace_id}>
                  <td className="ns-mono">
                    <time dateTime={tr.started_at}>{fmtDateTime(tr.started_at)}</time>
                  </td>
                  <td className="ns-mono">{tr.site_id}</td>
                  <td className="ns-num">{tr.cycle}</td>
                  <td>
                    <Link to={`/traces/${encodeURIComponent(tr.trace_id)}`} className="ns-dtable__link ns-stretch">
                      {tr.summary}
                    </Link>
                    <div className="ns-row ns-wrap ns-gap-sm">
                      {tr.scenario_run_id && <Chip tone="replay">{t('trace.replay')}</Chip>}
                      {(tr.branches ?? []).map((b) => (
                        <BranchChip key={b} branch={b} showName />
                      ))}
                    </div>
                  </td>
                  <td className="ns-num">
                    {tr.steps} <ChevronRight className="w-4 h-4 ns-inline-icon" aria-hidden="true" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
