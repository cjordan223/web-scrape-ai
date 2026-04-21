import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../../../../api';
import { timeAgo } from '../../../../../utils';

type SubTab = 'pending' | 'rejected';

interface QAJob {
  id: number;
  title?: string;
  board?: string;
  seniority?: string;
  created_at?: string;
}

export default function IngestionLanePanel() {
  const [tab, setTab] = useState<SubTab>('pending');
  return (
    <div className="ps-lane-panel">
      <div className="ps-lane-tabs">
        <button className={`ps-lane-tab${tab === 'pending' ? ' active' : ''}`} onClick={() => setTab('pending')}>QA Pending</button>
        <button className={`ps-lane-tab${tab === 'rejected' ? ' active' : ''}`} onClick={() => setTab('rejected')}>Rejected</button>
      </div>
      {tab === 'pending' ? <PendingTab /> : <QARejectedTab />}
    </div>
  );
}

function PendingTab() {
  const [jobs, setJobs] = useState<QAJob[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<string | null>(null);
  const [reviewStatus, setReviewStatus] = useState<any>(null);

  const jobsInterval = useRef<ReturnType<typeof setInterval>>(undefined);
  const reviewInterval = useRef<ReturnType<typeof setInterval>>(undefined);
  const jobsRequestInFlightRef = useRef(false);
  const reviewRequestInFlightRef = useRef(false);

  const fetchJobs = useCallback(async () => {
    if (jobsRequestInFlightRef.current) return;
    jobsRequestInFlightRef.current = true;
    try {
      const res = await api.getQAPending(500);
      setJobs(res.items || []);
      setTotal(res.total ?? (res.items || []).length);
    } catch (e) { console.error(e); }
    finally {
      jobsRequestInFlightRef.current = false;
      setLoading(false);
    }
  }, []);

  const fetchReview = useCallback(async () => {
    if (reviewRequestInFlightRef.current) return;
    reviewRequestInFlightRef.current = true;
    try { setReviewStatus(await api.getQALlmReviewStatus()); }
    catch (e) { console.error(e); }
    finally { reviewRequestInFlightRef.current = false; }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetchReview();
    jobsInterval.current = setInterval(fetchJobs, 30000);
    reviewInterval.current = setInterval(fetchReview, 2500);
    return () => { clearInterval(jobsInterval.current); clearInterval(reviewInterval.current); };
  }, [fetchJobs, fetchReview]);

  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const toggleAll = () => {
    if (selected.size === jobs.length) setSelected(new Set());
    else setSelected(new Set(jobs.map((j) => j.id)));
  };

  const removeFromList = (ids: number[]) => {
    setJobs((prev) => prev.filter((j) => !ids.includes(j.id)));
    setTotal((prev) => Math.max(0, prev - ids.length));
    setSelected((prev) => { const next = new Set(prev); ids.forEach((id) => next.delete(id)); return next; });
  };

  const handleApprove = async () => {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy('approve');
    try { await api.approveQA(ids); removeFromList(ids); } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  const handleReject = async () => {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy('reject');
    try { await api.rejectQA(ids); removeFromList(ids); } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  const handleLlmReview = async () => {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy('llm');
    try { await api.llmReviewQA(ids); setSelected(new Set()); } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  const handleScan = async () => {
    setScanning(true);
    setScanResult(null);
    try {
      const res = await api.scanMobileJDs();
      setScanResult(`Imported ${res.imported ?? 0} job(s)`);
      fetchJobs();
    } catch (e: any) { setScanResult(e?.message || 'Scan failed'); }
    finally { setScanning(false); }
  };

  const reviewRunning = reviewStatus?.running;
  const summary = reviewStatus?.summary;

  return (
    <div className="ps-lane-content">
      <div className="ps-lane-filters" style={{ justifyContent: 'space-between' }}>
        <span className="ps-lane-count" style={{ margin: 0 }}>{total} pending</span>
        <button className="ps-lane-btn-sm" onClick={handleScan} disabled={scanning}>
          {scanning ? 'Scanning...' : 'Scan Mobile'}
        </button>
      </div>
      {scanResult && <div className="ps-lane-notice">{scanResult}</div>}

      {reviewRunning && summary && (
        <div className="ps-lane-review-bar">
          <div className="ps-lane-review-progress">
            <div className="ps-lane-review-fill" style={{ width: `${summary.total ? (summary.completed / summary.total) * 100 : 0}%` }} />
          </div>
          <div className="ps-lane-review-meta">
            LLM Review: {summary.completed}/{summary.total}
            {reviewStatus.resolved_model && <span> · {reviewStatus.resolved_model}</span>}
          </div>
        </div>
      )}

      {loading ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : jobs.length === 0 ? (
        <div className="ps-lane-empty">No pending jobs</div>
      ) : (
        <>
          <div className="ps-lane-list">
            <div className="ps-lane-row ps-lane-row-header" onClick={toggleAll}>
              <input type="checkbox" checked={selected.size === jobs.length && jobs.length > 0} readOnly />
              <span>Select all</span>
            </div>
            {jobs.map((job) => (
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
              <button className="ps-lane-btn ps-lane-btn-green" onClick={handleApprove} disabled={!!busy}>
                {busy === 'approve' ? '...' : 'Approve'}
              </button>
              <button className="ps-lane-btn ps-lane-btn-red" onClick={handleReject} disabled={!!busy}>
                {busy === 'reject' ? '...' : 'Reject'}
              </button>
              <button className="ps-lane-btn" onClick={handleLlmReview} disabled={!!busy}>
                {busy === 'llm' ? '...' : 'LLM Review'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function QARejectedTab() {
  const [jobs, setJobs] = useState<QAJob[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.getTailoringRejected(500);
      setJobs(res.items || []);
      setTotal(res.total ?? (res.items || []).length);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const handleReturn = async () => {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy(true);
    try {
      await api.undoRejectQA(ids);
      setJobs((prev) => prev.filter((j) => !ids.includes(j.id)));
      setTotal((prev) => Math.max(0, prev - ids.length));
      setSelected(new Set());
    } catch (e) { console.error(e); }
    finally { setBusy(false); }
  };

  return (
    <div className="ps-lane-content">
      <div className="ps-lane-count">{total} rejected</div>

      {loading ? (
        <div className="ps-lane-empty">Loading...</div>
      ) : jobs.length === 0 ? (
        <div className="ps-lane-empty">No rejected jobs</div>
      ) : (
        <>
          <div className="ps-lane-list">
            {jobs.map((job) => (
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
              <button className="ps-lane-btn" onClick={handleReturn} disabled={busy}>
                {busy ? '...' : 'Return to QA'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
