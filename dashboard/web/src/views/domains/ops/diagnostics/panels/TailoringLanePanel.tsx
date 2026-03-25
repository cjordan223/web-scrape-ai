import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../../../../api';
import { timeAgo, fmtDuration } from '../../../../../utils';

type SubTab = 'ready' | 'packages' | 'applied' | 'traces';

const STATUS_COLORS: Record<string, string> = {
  applied: 'var(--accent)',
  follow_up: 'var(--amber, #d1a23b)',
  withdrawn: 'var(--text-secondary)',
  rejected: 'var(--red)',
  offer: 'var(--green)',
  interviewing: 'var(--cyan, #2ab8cc)',
};

const STAGE_COLORS: Record<string, string> = {
  analysis: '#7c8cf8',
  resume_strategy: '#4ade80',
  resume_draft: '#4ade80',
  resume_qa: '#4ade80',
  cover_strategy: '#f59e0b',
  cover_draft: '#f59e0b',
  cover_qa: '#f59e0b',
};

export default function TailoringLanePanel() {
  const [tab, setTab] = useState<SubTab>('ready');
  return (
    <div className="ps-lane-panel">
      <div className="ps-lane-tabs">
        <button className={`ps-lane-tab${tab === 'ready' ? ' active' : ''}`} onClick={() => setTab('ready')}>Ready</button>
        <button className={`ps-lane-tab${tab === 'packages' ? ' active' : ''}`} onClick={() => setTab('packages')}>Packages</button>
        <button className={`ps-lane-tab${tab === 'applied' ? ' active' : ''}`} onClick={() => setTab('applied')}>Applied</button>
        <button className={`ps-lane-tab${tab === 'traces' ? ' active' : ''}`} onClick={() => setTab('traces')}>Traces</button>
      </div>
      {tab === 'ready' ? <ReadyTab /> : tab === 'packages' ? <PackagesTab /> : tab === 'applied' ? <AppliedTab /> : <TracesTab />}
    </div>
  );
}

function ReadyTab() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const fetch = useCallback(async () => {
    try {
      const res = await api.getTailoringReady(500);
      setJobs(res.items || []);
      setTotal(res.total ?? (res.items || []).length);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch();
    pollRef.current = setInterval(fetch, 15000);
    return () => clearInterval(pollRef.current);
  }, [fetch]);

  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const toggleAll = () => {
    if (selected.size === jobs.length) setSelected(new Set());
    else setSelected(new Set(jobs.map((j) => j.id)));
  };

  const handleQueue = async () => {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy('queue');
    try {
      await api.queueTailoring(ids.map((id) => ({ job_id: id })));
      setJobs((prev) => prev.filter((j) => !ids.includes(j.id)));
      setTotal((prev) => Math.max(0, prev - ids.length));
      setSelected(new Set());
    } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  const handleQueueAll = async () => {
    if (!jobs.length) return;
    setBusy('all');
    try {
      await api.queueTailoring(jobs.map((j) => ({ job_id: j.id })));
      setJobs([]);
      setTotal(0);
      setSelected(new Set());
    } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  return (
    <div className="ps-lane-content">
      <div className="ps-lane-filters" style={{ justifyContent: 'space-between' }}>
        <span className="ps-lane-count" style={{ margin: 0 }}>{total} ready to tailor</span>
        {jobs.length > 0 && (
          <button className="ps-lane-btn-sm" onClick={handleQueueAll} disabled={!!busy}>
            {busy === 'all' ? '...' : 'Queue All'}
          </button>
        )}
      </div>

      {loading ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : jobs.length === 0 ? (
        <div className="ps-lane-empty">No jobs ready for tailoring</div>
      ) : (
        <>
          <div className="ps-lane-list">
            <div className="ps-lane-row ps-lane-row-header" onClick={toggleAll}>
              <input type="checkbox" checked={selected.size === jobs.length && jobs.length > 0} readOnly />
              <span>Select all</span>
            </div>
            {jobs.map((job: any) => (
              <div
                key={job.id}
                className={`ps-lane-row ps-lane-row-selectable${selected.has(job.id) ? ' selected' : ''}`}
                onClick={() => toggle(job.id)}
              >
                <input type="checkbox" checked={selected.has(job.id)} readOnly />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="ps-lane-row-title">{job.title || 'Untitled'}</div>
                  <div className="ps-lane-row-meta">
                    {job.board && <span className="ps-lane-badge">{job.board}</span>}
                    <span className="ps-lane-date">{timeAgo(job.created_at)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {selected.size > 0 && (
            <div className="ps-lane-action-bar">
              <span className="ps-lane-action-count">{selected.size} selected</span>
              <button className="ps-lane-btn ps-lane-btn-green" onClick={handleQueue} disabled={!!busy}>
                {busy === 'queue' ? '...' : 'Queue Selected'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PackagesTab() {
  const [packages, setPackages] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'unapplied' | 'applied'>('all');

  const fetch = useCallback(async () => {
    try { setPackages(await api.getPackages()); }
    catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch();
    const id = setInterval(fetch, 15000);
    return () => clearInterval(id);
  }, [fetch]);

  const filtered = packages.filter((pkg) => {
    if (filter === 'applied') return pkg.applied;
    if (filter === 'unapplied') return !pkg.applied;
    return true;
  });

  return (
    <div className="ps-lane-content">
      <div className="ps-lane-chips">
        {(['all', 'unapplied', 'applied'] as const).map((f) => (
          <button key={f} className={`ps-lane-chip${filter === f ? ' active' : ''}`} onClick={() => setFilter(f)}>
            {f === 'all' ? `All (${packages.length})` : f === 'unapplied' ? `Unapplied (${packages.filter((p) => !p.applied).length})` : `Applied (${packages.filter((p) => p.applied).length})`}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : filtered.length === 0 ? (
        <div className="ps-lane-empty">No packages</div>
      ) : (
        <div className="ps-lane-list">
          {filtered.map((pkg: any) => (
            <a key={pkg.slug} className="ps-lane-row" href={`/pipeline/packages`} target="_blank" rel="noopener noreferrer">
              <div className="ps-lane-row-title">{pkg.job_title || pkg.slug}</div>
              <div className="ps-lane-row-meta">
                <span className="ps-lane-badge" style={{
                  color: pkg.applied ? 'var(--green)' : 'var(--amber, #d1a23b)',
                  background: pkg.applied ? 'rgba(60,179,113,0.1)' : 'rgba(224,160,48,0.12)',
                }}>{pkg.applied ? 'Applied' : 'Ready'}</span>
                <span className="ps-lane-date">{timeAgo(pkg.created_at)}</span>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function AppliedTab() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const res = await api.getAppliedList();
      setItems(res.items || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch();
    const id = setInterval(fetch, 15000);
    return () => clearInterval(id);
  }, [fetch]);

  return (
    <div className="ps-lane-content">
      {loading ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : items.length === 0 ? (
        <div className="ps-lane-empty">No applications yet</div>
      ) : (
        <div className="ps-lane-list">
          {items.map((app: any) => {
            const status = app.status || 'applied';
            return (
              <div key={app.id} className="ps-lane-row">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="ps-lane-row-title">{app.job_title || app.slug || 'Untitled'}</div>
                  <div className="ps-lane-row-meta">
                    <span className="ps-lane-badge" style={{ color: STATUS_COLORS[status] || 'var(--text-secondary)' }}>{status}</span>
                    {app.company && <span className="ps-lane-badge">{app.company}</span>}
                    <span className="ps-lane-date">{timeAgo(app.applied_at)}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TracesTab() {
  const [archives, setArchives] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [trace, setTrace] = useState<any>(null);
  const [traceLoading, setTraceLoading] = useState(false);

  const fetch = useCallback(async () => {
    try { setArchives(await api.getPipelinePackages()); }
    catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const loadTrace = async (archiveId: number, slug: string) => {
    if (expandedId === archiveId) { setExpandedId(null); setTrace(null); return; }
    setExpandedId(archiveId);
    setTraceLoading(true);
    try { setTrace(await api.getPipelineTrace(archiveId, slug)); }
    catch (e) { console.error(e); setTrace(null); }
    finally { setTraceLoading(false); }
  };

  const calls = trace?.events?.filter((e: any) => e.event === 'llm_call_success') || [];

  return (
    <div className="ps-lane-content">
      {loading ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : archives.length === 0 ? (
        <div className="ps-lane-empty">No tailoring runs</div>
      ) : (
        <div className="ps-lane-list">
          {archives.map((arch: any) => (
            <div key={arch.id}>
              <div
                className={`ps-lane-row ps-lane-row-selectable${expandedId === arch.id ? ' selected' : ''}`}
                onClick={() => loadTrace(arch.id, arch.slug)}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="ps-lane-row-title">{arch.job_title || arch.slug}</div>
                  <div className="ps-lane-row-meta">
                    <span className="ps-lane-date">{timeAgo(arch.created_at)}</span>
                  </div>
                </div>
              </div>
              {expandedId === arch.id && (
                <div className="ps-lane-trace-detail">
                  {traceLoading ? (
                    <div className="ps-lane-empty">Loading trace...</div>
                  ) : calls.length === 0 ? (
                    <div className="ps-lane-empty">No LLM calls recorded</div>
                  ) : (
                    calls.map((call: any, i: number) => {
                      const stage = call.stage || call.data?.stage || 'unknown';
                      return (
                        <div key={i} className="ps-lane-trace-call">
                          <span className="ps-lane-badge" style={{ color: STAGE_COLORS[stage] || 'var(--text-secondary)' }}>{stage}</span>
                          {call.data?.model && <span className="ps-lane-badge">{call.data.model}</span>}
                          {call.data?.duration_ms != null && (
                            <span className="ps-lane-date">{fmtDuration(call.data.duration_ms / 1000)}</span>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
