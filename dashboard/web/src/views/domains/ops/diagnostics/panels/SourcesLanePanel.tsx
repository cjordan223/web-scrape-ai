import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../../../api';
import { fmtDate } from '../../../../../utils';

type SubTab = 'jobs' | 'rejected';

const DECISION_COLORS: Record<string, { color: string; bg: string }> = {
  qa_pending: { color: 'var(--amber, #e0a030)', bg: 'rgba(224, 160, 48, 0.12)' },
  qa_approved: { color: 'var(--green)', bg: 'rgba(60, 179, 113, 0.10)' },
  qa_rejected: { color: 'var(--red)', bg: 'rgba(196, 68, 68, 0.10)' },
};

const DECISION_LABELS: Record<string, string> = {
  qa_pending: 'Pending',
  qa_approved: 'Ready',
  qa_rejected: 'Rejected',
};

export default function SourcesLanePanel() {
  const [tab, setTab] = useState<SubTab>('jobs');
  return (
    <div className="ps-lane-panel">
      <div className="ps-lane-tabs">
        <button className={`ps-lane-tab${tab === 'jobs' ? ' active' : ''}`} onClick={() => setTab('jobs')}>Jobs</button>
        <button className={`ps-lane-tab${tab === 'rejected' ? ' active' : ''}`} onClick={() => setTab('rejected')}>Rejected</button>
      </div>
      {tab === 'jobs' ? <JobsTab /> : <RejectedTab />}
    </div>
  );
}

function JobsTab() {
  const [jobs, setJobs] = useState<any>({ items: [], total: 0, pages: 0, page: 1 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [board, setBoard] = useState('');
  const [decision, setDecision] = useState('');
  const [page, setPage] = useState(1);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getJobs({ page, per_page: 20, board, decision, search, sort_by: 'created_at', sort_dir: 'desc' });
      setJobs(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [page, board, decision, search]);

  useEffect(() => { fetch(); }, [fetch]);

  const boards = ['greenhouse', 'lever', 'ashby', 'workday', 'simplyhired', 'usajobs', 'unknown'];

  return (
    <div className="ps-lane-content">
      <div className="ps-lane-filters">
        <input
          className="ps-lane-search"
          type="text"
          placeholder="Search titles..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
        <select className="ps-lane-select" value={board} onChange={(e) => { setBoard(e.target.value); setPage(1); }}>
          <option value="">All boards</option>
          {boards.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <select className="ps-lane-select" value={decision} onChange={(e) => { setDecision(e.target.value); setPage(1); }}>
          <option value="">All decisions</option>
          <option value="qa_pending">QA Pending</option>
          <option value="qa_approved">Ready</option>
          <option value="qa_rejected">Rejected</option>
        </select>
      </div>

      {loading && jobs.items.length === 0 ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : jobs.items.length === 0 ? (
        <div className="ps-lane-empty">No jobs found</div>
      ) : (
        <>
          <div className="ps-lane-count">{jobs.total} results</div>
          <div className="ps-lane-list">
            {jobs.items.map((job: any) => {
              const dm = DECISION_COLORS[job.decision] || { color: 'var(--text-secondary)', bg: 'var(--surface-2)' };
              return (
                <a
                  key={job.id}
                  className="ps-lane-row"
                  href={job.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="ps-lane-row-title">{job.title || 'Untitled'}</div>
                  <div className="ps-lane-row-meta">
                    {job.board && <span className="ps-lane-badge">{job.board}</span>}
                    <span className="ps-lane-badge" style={{ color: dm.color, background: dm.bg }}>
                      {DECISION_LABELS[job.decision] || job.decision}
                    </span>
                    <span className="ps-lane-date">{fmtDate(job.created_at)}</span>
                  </div>
                </a>
              );
            })}
          </div>
          {jobs.pages > 1 && (
            <div className="ps-lane-pagination">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
              <span>{page} / {jobs.pages}</span>
              <button disabled={page >= jobs.pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RejectedTab() {
  const [rejected, setRejected] = useState<any>({ items: [], total: 0, pages: 0 });
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [stage, setStage] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [approvingIds, setApprovingIds] = useState<Record<number, boolean>>({});

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const [data, statsRes] = await Promise.all([
        api.getRejected({ page, per_page: 20, stage, search }),
        api.getRejectedStats(),
      ]);
      setRejected(data);
      setStats(statsRes);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [page, stage, search]);

  useEffect(() => { fetch(); }, [fetch]);

  const handleApprove = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    setApprovingIds((prev) => ({ ...prev, [id]: true }));
    try {
      await api.approveRejected(id);
      setRejected((prev: any) => ({
        ...prev,
        items: prev.items.filter((j: any) => j.id !== id),
        total: Math.max(0, prev.total - 1),
      }));
    } catch (e) { console.error(e); }
    finally { setApprovingIds((prev) => ({ ...prev, [id]: false })); }
  };

  const stagePills = stats?.stages || [];

  return (
    <div className="ps-lane-content">
      {stagePills.length > 0 && (
        <div className="ps-lane-chips">
          <button
            className={`ps-lane-chip${!stage ? ' active' : ''}`}
            onClick={() => { setStage(''); setPage(1); }}
          >All</button>
          {stagePills.map((s: any) => (
            <button
              key={s.stage}
              className={`ps-lane-chip${stage === s.stage ? ' active' : ''}`}
              onClick={() => { setStage(s.stage); setPage(1); }}
            >{s.stage} ({s.count})</button>
          ))}
        </div>
      )}
      <div className="ps-lane-filters">
        <input
          className="ps-lane-search"
          type="text"
          placeholder="Search..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
      </div>

      {loading && rejected.items.length === 0 ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : rejected.items.length === 0 ? (
        <div className="ps-lane-empty">No rejected jobs</div>
      ) : (
        <>
          <div className="ps-lane-count">{rejected.total} rejected</div>
          <div className="ps-lane-list">
            {rejected.items.map((job: any) => (
              <div key={job.id} className="ps-lane-row">
                <div className="ps-lane-row-main">
                  <div className="ps-lane-row-title">{job.title || 'Untitled'}</div>
                  <div className="ps-lane-row-meta">
                    <span className="ps-lane-badge ps-lane-badge-muted">{job.rejection_stage}</span>
                    <span className="ps-lane-date">{fmtDate(job.created_at)}</span>
                  </div>
                </div>
                <button
                  className="ps-lane-btn-sm"
                  disabled={approvingIds[job.id]}
                  onClick={(e) => handleApprove(e, job.id)}
                >
                  {approvingIds[job.id] ? '...' : 'Approve'}
                </button>
              </div>
            ))}
          </div>
          {rejected.pages > 1 && (
            <div className="ps-lane-pagination">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
              <span>{page} / {rejected.pages}</span>
              <button disabled={page >= rejected.pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
