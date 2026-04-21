import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../api';

interface QAJob {
    id: number;
    title?: string;
    url?: string;
    snippet?: string;
    board?: string;
    seniority?: string;
    created_at?: string;
}

interface QALlmReviewItem {
    job_id: number;
    title?: string;
    status: 'queued' | 'reviewing' | 'pass' | 'fail' | 'skipped' | 'error';
    reason?: string;
}

interface QALlmReviewStatus {
    running: boolean;
    resolved_model?: string | null;
    items: QALlmReviewItem[];
    summary: {
        total: number;
        queued: number;
        reviewing: number;
        completed: number;
        passed: number;
        failed: number;
        skipped: number;
        errors: number;
    };
    active_job?: QALlmReviewItem | null;
}

const STATUS_LABELS: Record<QALlmReviewItem['status'], string> = {
    queued: 'Queued',
    reviewing: 'Reviewing',
    pass: 'Approved',
    fail: 'Rejected',
    skipped: 'Skipped',
    error: 'Error',
};

const STATUS_COLORS: Record<QALlmReviewItem['status'], string> = {
    queued: 'var(--text-secondary)',
    reviewing: 'var(--accent)',
    pass: 'var(--green)',
    fail: 'var(--red)',
    skipped: 'var(--amber, #d1a23b)',
    error: 'var(--red)',
};

export default function MobileQAView() {
    const [jobs, setJobs] = useState<QAJob[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [expanded, setExpanded] = useState<number | null>(null);
    const [detail, setDetail] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [busy, setBusy] = useState<string | null>(null);
    const [scanning, setScanning] = useState(false);
    const [scanMsg, setScanMsg] = useState('');
    const [reviewStatus, setReviewStatus] = useState<QALlmReviewStatus | null>(null);
    const [reviewError, setReviewError] = useState('');
    const [undoToast, setUndoToast] = useState<{ ids: number[]; action: 'approve' | 'reject'; timer: ReturnType<typeof setTimeout> } | null>(null);
    const reviewSignatureRef = useRef('');
    const jobsRequestInFlightRef = useRef(false);
    const reviewRequestInFlightRef = useRef(false);

    const fetchJobs = useCallback(async () => {
        if (jobsRequestInFlightRef.current) return;
        jobsRequestInFlightRef.current = true;
        try {
            const res = await api.getQAPending(500);
            setJobs(res.items || []);
            setTotal(res.total ?? (res.items || []).length);
        } catch {
            // ignore
        } finally {
            jobsRequestInFlightRef.current = false;
            setLoading(false);
        }
    }, []);

    const fetchReviewStatus = useCallback(async () => {
        if (reviewRequestInFlightRef.current) return;
        reviewRequestInFlightRef.current = true;
        try {
            const res = await api.getQALlmReviewStatus();
            setReviewStatus(res);
            setReviewError('');
        } catch (err: any) {
            setReviewError(err?.response?.data?.error || err?.message || 'Failed to fetch QA review status');
        } finally {
            reviewRequestInFlightRef.current = false;
        }
    }, []);

    useEffect(() => {
        fetchJobs();
        fetchReviewStatus();
        const jobsTimer = setInterval(fetchJobs, 30000);
        const reviewTimer = setInterval(fetchReviewStatus, 2500);
        return () => {
            clearInterval(jobsTimer);
            clearInterval(reviewTimer);
        };
    }, [fetchJobs, fetchReviewStatus]);

    useEffect(() => {
        if (!expanded) {
            setDetail(null);
            return;
        }
        setDetailLoading(true);
        api.getTailoringJobDetail(expanded)
            .then(setDetail)
            .catch(() => setDetail(null))
            .finally(() => setDetailLoading(false));
    }, [expanded]);

    useEffect(() => {
        if (!reviewStatus) return;
        const signature = JSON.stringify({
            running: reviewStatus.running,
            queued: reviewStatus.summary.queued,
            reviewing: reviewStatus.summary.reviewing,
            completed: reviewStatus.summary.completed,
            passed: reviewStatus.summary.passed,
            failed: reviewStatus.summary.failed,
            errors: reviewStatus.summary.errors,
            activeJob: reviewStatus.active_job?.job_id ?? null,
        });
        if (signature === reviewSignatureRef.current) return;
        reviewSignatureRef.current = signature;
        fetchJobs();
    }, [fetchJobs, reviewStatus]);

    const toggle = (id: number) => {
        setSelected((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };

    const removeFromList = (ids: number[]) => {
        setJobs((prev) => prev.filter((job) => !ids.includes(job.id)));
        setTotal((prev) => Math.max(0, prev - ids.length));
        setSelected((prev) => {
            const next = new Set(prev);
            ids.forEach((id) => next.delete(id));
            return next;
        });
        if (expanded && ids.includes(expanded)) {
            setExpanded(null);
            setDetail(null);
        }
    };

    const showUndoToast = (ids: number[], action: 'approve' | 'reject') => {
        if (undoToast) clearTimeout(undoToast.timer);
        const timer = setTimeout(() => setUndoToast(null), 6000);
        setUndoToast({ ids, action, timer });
    };

    const handleUndo = async () => {
        if (!undoToast) return;
        clearTimeout(undoToast.timer);
        const { ids, action } = undoToast;
        setUndoToast(null);
        try {
            if (action === 'approve') await api.undoApproveQA(ids);
            else await api.undoRejectQA(ids);
            fetchJobs();
        } catch { /* ignore */ }
    };

    const handleApprove = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('approve');
        try {
            await api.approveQA(ids);
            removeFromList(ids);
            showUndoToast(ids, 'approve');
        } catch {
            // ignore
        } finally {
            setBusy(null);
        }
    };

    const handleReject = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('reject');
        try {
            await api.rejectQA(ids);
            removeFromList(ids);
            showUndoToast(ids, 'reject');
        } catch {
            // ignore
        } finally {
            setBusy(null);
        }
    };

    const handleLlmReview = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('llm-review');
        setReviewError('');
        try {
            const res = await api.llmReviewQA(ids);
            setReviewStatus(res.runner || null);
        } catch (err: any) {
            setReviewError(err?.response?.data?.error || err?.message || 'Failed to queue QA review');
        } finally {
            setBusy(null);
        }
    };

    const handleScan = async () => {
        setScanning(true);
        setScanMsg('');
        try {
            const res = await api.scanMobileJDs();
            setScanMsg(`${res.processed} scanned`);
            if (res.processed > 0) fetchJobs();
        } catch (err: any) {
            setScanMsg(`Error: ${err.message}`);
        } finally {
            setScanning(false);
        }
    };

    const timeAgo = (iso?: string) => {
        if (!iso) return '';
        const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
        return `${Math.round(seconds / 86400)}d ago`;
    };

    const hdr: React.CSSProperties = {
        fontFamily: 'var(--font-mono)',
        fontSize: '.7rem',
        fontWeight: 600,
        color: 'var(--text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '.08em',
    };
    const btn: React.CSSProperties = {
        fontFamily: 'var(--font-mono)',
        fontSize: '.8rem',
        fontWeight: 600,
        padding: '12px',
        borderRadius: '4px',
        border: 'none',
        cursor: 'pointer',
        width: '100%',
        minHeight: '44px',
    };
    const primaryBtn: React.CSSProperties = { ...btn, background: 'var(--accent)', color: '#fff' };
    const dangerBtn: React.CSSProperties = { ...btn, background: 'var(--red, #c44)', color: '#fff' };
    const ghostBtn: React.CSSProperties = {
        fontFamily: 'var(--font-mono)',
        fontSize: '.68rem',
        background: 'transparent',
        border: '1px solid var(--border)',
        borderRadius: '4px',
        padding: '4px 10px',
        color: 'var(--text-secondary)',
        cursor: 'pointer',
        minHeight: '32px',
    };

    const queueTargetIds = selected.size > 0 ? Array.from(selected) : jobs.map((job) => job.id);
    const trackerVisible = Boolean(
        reviewStatus
        && (
            reviewStatus.running
            || reviewStatus.summary.queued > 0
            || reviewStatus.summary.reviewing > 0
        ),
    );
    const progressPercent = reviewStatus?.summary.total
        ? Math.round((reviewStatus.summary.completed / reviewStatus.summary.total) * 100)
        : 0;

    return (
        <div style={{ padding: '12px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={hdr}>QA Triage ({total})</span>
                <div style={{ display: 'flex', gap: '6px' }}>
                    <button onClick={() => {
                        if (selected.size === jobs.length) setSelected(new Set());
                        else setSelected(new Set(jobs.map(j => j.id)));
                    }} disabled={jobs.length === 0} style={ghostBtn}>
                        {selected.size === jobs.length && jobs.length > 0 ? 'Deselect' : 'Select All'}
                    </button>
                    <button onClick={() => handleLlmReview(jobs.map((job) => job.id))} disabled={!!busy || jobs.length === 0} style={ghostBtn}>
                        {busy === 'llm-review' && selected.size === 0 ? 'Queueing...' : 'Queue All'}
                    </button>
                    <button onClick={handleScan} disabled={scanning} style={ghostBtn}>
                        {scanning ? 'Scanning...' : 'Scan'}
                    </button>
                    <button onClick={fetchJobs} style={ghostBtn}>Refresh</button>
                </div>
            </div>

            {(scanMsg || reviewError) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
                    {scanMsg && (
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                            {scanMsg}
                        </div>
                    )}
                    {reviewError && (
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--red)' }}>
                            {reviewError}
                        </div>
                    )}
                </div>
            )}

            {trackerVisible && reviewStatus && (
                <div style={{
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    background: 'var(--surface)',
                    padding: '10px',
                    marginBottom: '10px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={hdr}>LLM Review Queue</span>
                        <span style={{
                            marginLeft: 'auto',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.64rem',
                            color: reviewStatus.running ? 'var(--accent)' : 'var(--text-secondary)',
                        }}>
                            {reviewStatus.running ? 'Running' : 'Idle'}
                        </span>
                    </div>
                    <div style={{ height: '8px', background: 'var(--surface-3)', borderRadius: '999px', overflow: 'hidden' }}>
                        <div style={{
                            width: `${progressPercent}%`,
                            height: '100%',
                            background: 'linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 45%, white))',
                        }} />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                            {reviewStatus.summary.completed}/{reviewStatus.summary.total} done
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--green)' }}>
                            {reviewStatus.summary.passed} approved
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--red)' }}>
                            {reviewStatus.summary.failed} rejected
                        </span>
                        {reviewStatus.summary.errors > 0 && (
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--red)' }}>
                                {reviewStatus.summary.errors} errors
                            </span>
                        )}
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                        Model: {reviewStatus.resolved_model || 'waiting for model'}
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                        {reviewStatus.active_job
                            ? `Current: #${reviewStatus.active_job.job_id} ${reviewStatus.active_job.title || ''}`.trim()
                            : reviewStatus.running
                                ? 'Current: preparing next job'
                                : 'Current: queue complete'}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '180px', overflowY: 'auto' }}>
                        {reviewStatus.items.map((item) => (
                            <div key={`${item.job_id}-${item.status}`} style={{
                                border: '1px solid var(--border)',
                                borderRadius: '6px',
                                padding: '8px',
                                background: 'var(--bg)',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.65rem', color: 'var(--text-secondary)' }}>
                                        #{item.job_id}
                                    </span>
                                    <span style={{
                                        flex: 1,
                                        minWidth: 0,
                                        fontSize: '.76rem',
                                        fontWeight: 600,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                    }}>
                                        {item.title || 'Untitled'}
                                    </span>
                                    <span style={{
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '.6rem',
                                        color: STATUS_COLORS[item.status],
                                        border: `1px solid ${STATUS_COLORS[item.status]}`,
                                        borderRadius: '999px',
                                        padding: '1px 6px',
                                    }}>
                                        {STATUS_LABELS[item.status]}
                                    </span>
                                </div>
                                {item.reason && item.status !== 'queued' && item.status !== 'reviewing' && (
                                    <div style={{
                                        marginTop: '6px',
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '.62rem',
                                        color: item.status === 'error' ? 'var(--red)' : 'var(--text-secondary)',
                                        whiteSpace: 'pre-wrap',
                                        wordBreak: 'break-word',
                                    }}>
                                        {item.reason}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {selected.size > 0 && (
                <div style={{
                    position: 'sticky',
                    top: 0,
                    zIndex: 10,
                    padding: '10px 0',
                    marginBottom: '4px',
                    background: 'var(--bg)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                }}>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <button style={{ ...primaryBtn, opacity: busy ? 0.5 : 1 }}
                            onClick={() => handleApprove(Array.from(selected))} disabled={!!busy}>
                            {busy === 'approve' ? 'Approving...' : `Approve (${selected.size})`}
                        </button>
                        <button style={{ ...dangerBtn, opacity: busy ? 0.5 : 1 }}
                            onClick={() => handleReject(Array.from(selected))} disabled={!!busy}>
                            {busy === 'reject' ? 'Rejecting...' : `Reject (${selected.size})`}
                        </button>
                    </div>
                    <button
                        style={{
                            ...primaryBtn,
                            fontSize: '.72rem',
                            background: 'var(--surface-2)',
                            color: 'var(--text)',
                            border: '1px solid var(--border)',
                            opacity: busy ? 0.5 : 1,
                        }}
                        onClick={() => handleLlmReview(queueTargetIds)}
                        disabled={!!busy}
                    >
                        {busy === 'llm-review' ? 'Queueing...' : `Queue LLM Review (${selected.size})`}
                    </button>
                    <button onClick={() => setSelected(new Set())} style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '.68rem',
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text-secondary)',
                        cursor: 'pointer',
                        padding: '4px',
                    }}>
                        Clear selection
                    </button>
                </div>
            )}

            {loading && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--text-secondary)', padding: '20px 0', textAlign: 'center' }}>
                    Loading...
                </div>
            )}

            {!loading && jobs.length === 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.78rem', color: 'var(--text-secondary)', padding: '40px 0', textAlign: 'center' }}>
                    No pending jobs. New scrape and ingest jobs land here before they become ready.
                </div>
            )}

            {jobs.map((job) => {
                const checked = selected.has(job.id);
                const isExpanded = expanded === job.id;
                return (
                    <div key={job.id} style={{
                        padding: '10px 0',
                        borderBottom: '1px solid var(--border)',
                        background: checked ? 'rgba(75,142,240,.06)' : 'transparent',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }} onClick={() => toggle(job.id)}>
                            <input
                                type="checkbox"
                                checked={checked}
                                readOnly
                                style={{ accentColor: 'var(--accent)', width: 20, height: 20, marginTop: 2, flexShrink: 0 }}
                            />
                            <div style={{ flex: 1, minWidth: 0 }} onClick={(event) => { event.stopPropagation(); setExpanded(isExpanded ? null : job.id); }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)' }}>#{job.id}</span>
                                    <span style={{ fontSize: '.82rem', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                                        {job.title || 'Untitled'}
                                    </span>
                                </div>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', color: 'var(--text-secondary)', marginTop: '3px', display: 'flex', gap: '8px' }}>
                                    {job.board && <span style={{ color: 'var(--accent)' }}>{job.board}</span>}
                                    {job.seniority && <span>{job.seniority}</span>}
                                    {job.created_at && <span style={{ marginLeft: 'auto' }}>{timeAgo(job.created_at)}</span>}
                                </div>
                            </div>
                        </div>

                        {isExpanded && (
                            <div style={{ marginTop: '10px', marginLeft: '30px', padding: '10px', background: 'var(--surface)', borderRadius: '4px', border: '1px solid var(--border)' }}>
                                {detailLoading ? (
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>Loading...</div>
                                ) : !detail ? (
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>Not found</div>
                                ) : (
                                    <>
                                        {detail.jd_text && (
                                            <div style={{
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.7rem',
                                                lineHeight: 1.5,
                                                whiteSpace: 'pre-wrap',
                                                wordBreak: 'break-word',
                                                maxHeight: '300px',
                                                overflow: 'auto',
                                                marginBottom: '10px',
                                            }}>
                                                {detail.jd_text}
                                            </div>
                                        )}
                                        {detail.url && (
                                            <a
                                                href={detail.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                style={{ fontFamily: 'var(--font-mono)', fontSize: '.65rem', wordBreak: 'break-all', color: 'var(--accent)' }}
                                            >
                                                {detail.url}
                                            </a>
                                        )}
                                        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                                            <button
                                                style={{ ...primaryBtn, fontSize: '.72rem', padding: '8px' }}
                                                onClick={() => handleApprove([job.id])}
                                                disabled={!!busy}
                                            >
                                                Approve
                                            </button>
                                            <button
                                                style={{ ...dangerBtn, fontSize: '.72rem', padding: '8px' }}
                                                onClick={() => handleReject([job.id])}
                                                disabled={!!busy}
                                            >
                                                Reject
                                            </button>
                                        </div>
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}

            {undoToast && (
                <div style={{
                    position: 'fixed',
                    bottom: '72px',
                    left: '16px',
                    right: '16px',
                    background: 'var(--surface-2, #333)',
                    color: 'var(--text)',
                    borderRadius: '8px',
                    padding: '12px 16px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '.75rem',
                    zIndex: 100,
                    boxShadow: '0 4px 12px rgba(0,0,0,.3)',
                }}>
                    <span>
                        {undoToast.ids.length} job{undoToast.ids.length > 1 ? 's' : ''}{' '}
                        {undoToast.action === 'approve' ? 'approved' : 'rejected'}
                    </span>
                    <button
                        onClick={handleUndo}
                        style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--accent)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.75rem',
                            fontWeight: 700,
                            cursor: 'pointer',
                            padding: '4px 8px',
                        }}
                    >
                        Undo
                    </button>
                </div>
            )}
        </div>
    );
}
