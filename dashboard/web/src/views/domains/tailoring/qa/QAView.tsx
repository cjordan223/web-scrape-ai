import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';

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
    confidence?: number | null;
    queued_at?: string | null;
    started_at?: string | null;
    completed_at?: string | null;
    top_matches?: string[];
    gaps?: string[];
}

interface QALlmReviewStatus {
    running: boolean;
    batch_id: number;
    started_at?: string | null;
    ended_at?: string | null;
    resolved_model?: string | null;
    active_job?: QALlmReviewItem | null;
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

export default function QAView() {
    const [jobs, setJobs] = useState<QAJob[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [focusedId, setFocusedId] = useState<number | null>(null);
    const [detail, setDetail] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [busy, setBusy] = useState<'approve' | 'reject' | 'llm-review' | null>(null);
    const [scanning, setScanning] = useState(false);
    const [scanResult, setScanResult] = useState<string | null>(null);
    const [reviewStatus, setReviewStatus] = useState<QALlmReviewStatus | null>(null);
    const [reviewError, setReviewError] = useState<string | null>(null);

    const jobsIntervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
    const reviewIntervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
    const reviewSignatureRef = useRef<string>('');

    const fetchJobs = useCallback(async () => {
        try {
            const res = await api.getQAPending(500);
            setJobs(res.items || []);
            setTotal(res.total ?? (res.items || []).length);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchReviewStatus = useCallback(async () => {
        try {
            const res = await api.getQALlmReviewStatus();
            setReviewStatus(res);
            setReviewError(null);
        } catch (err: any) {
            console.error(err);
            setReviewError(err?.response?.data?.error || err?.message || 'Failed to fetch QA review status');
        }
    }, []);

    useEffect(() => {
        fetchJobs();
        fetchReviewStatus();
        jobsIntervalRef.current = setInterval(fetchJobs, 30000);
        reviewIntervalRef.current = setInterval(fetchReviewStatus, 2500);
        return () => {
            clearInterval(jobsIntervalRef.current);
            clearInterval(reviewIntervalRef.current);
        };
    }, [fetchJobs, fetchReviewStatus]);

    useEffect(() => {
        if (!focusedId) {
            setDetail(null);
            return;
        }
        setDetailLoading(true);
        (async () => {
            try {
                const res = await api.getTailoringJobDetail(focusedId);
                setDetail(res);
            } catch {
                setDetail(null);
            } finally {
                setDetailLoading(false);
            }
        })();
    }, [focusedId]);

    useEffect(() => {
        if (!reviewStatus) return;
        const signature = JSON.stringify({
            batchId: reviewStatus.batch_id,
            running: reviewStatus.running,
            queued: reviewStatus.summary.queued,
            reviewing: reviewStatus.summary.reviewing,
            completed: reviewStatus.summary.completed,
            passed: reviewStatus.summary.passed,
            failed: reviewStatus.summary.failed,
            errors: reviewStatus.summary.errors,
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

    const toggleAll = () => {
        if (selected.size === jobs.length) setSelected(new Set());
        else setSelected(new Set(jobs.map((job) => job.id)));
    };

    const removeFromList = (ids: number[]) => {
        setJobs((prev) => prev.filter((job) => !ids.includes(job.id)));
        setTotal((prev) => Math.max(0, prev - ids.length));
        setSelected((prev) => {
            const next = new Set(prev);
            ids.forEach((id) => next.delete(id));
            return next;
        });
        if (focusedId && ids.includes(focusedId)) {
            setFocusedId(null);
            setDetail(null);
        }
    };

    const handleApprove = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('approve');
        try {
            await api.approveQA(ids);
            removeFromList(ids);
        } catch (err) {
            console.error(err);
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
        } catch (err) {
            console.error(err);
        } finally {
            setBusy(null);
        }
    };

    const handleLlmReview = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('llm-review');
        setReviewError(null);
        try {
            const res = await api.llmReviewQA(ids);
            setReviewStatus(res.runner || null);
        } catch (err: any) {
            setReviewError(err?.response?.data?.error || err?.message || 'Failed to queue QA review');
        } finally {
            setBusy(null);
        }
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

    if (loading) {
        return <div className="view-container"><div className="loading"><div className="spinner" /></div></div>;
    }

    return (
        <div style={{ display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>
            <div style={{
                width: '540px',
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                borderRight: '1px solid var(--border)',
                background: 'var(--surface)',
                overflow: 'hidden',
            }}>
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <span style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '.68rem',
                        fontWeight: 600,
                        color: 'var(--text-secondary)',
                        textTransform: 'uppercase',
                        letterSpacing: '.1em',
                    }}>
                        QA Triage ({total} pending)
                    </span>
                </div>

                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={!!busy || selected.size === 0}
                            onClick={() => handleApprove(Array.from(selected))}
                            style={{ flex: 1 }}
                        >
                            {busy === 'approve' ? 'Approving...' : `Approve Selected (${selected.size})`}
                        </button>
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || selected.size === 0}
                            onClick={() => handleReject(Array.from(selected))}
                            style={{ flex: 1, background: 'var(--red, #c44)', color: '#fff', border: 'none' }}
                        >
                            {busy === 'reject' ? 'Rejecting...' : `Reject Selected (${selected.size})`}
                        </button>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || queueTargetIds.length === 0}
                            onClick={() => handleLlmReview(queueTargetIds)}
                            style={{ flex: 1, background: 'var(--surface-2)', border: '1px solid var(--border)' }}
                        >
                            {busy === 'llm-review'
                                ? 'Queueing...'
                                : selected.size > 0
                                    ? `Queue LLM Review (${selected.size})`
                                    : `Queue LLM Review All (${jobs.length})`}
                        </button>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.7rem',
                            color: 'var(--text-secondary)',
                            cursor: 'pointer',
                        }}>
                            <input
                                type="checkbox"
                                checked={selected.size === jobs.length && jobs.length > 0}
                                onChange={toggleAll}
                                style={{ accentColor: 'var(--accent)' }}
                            />
                            Select all
                        </label>
                        {selected.size > 0 && (
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={() => setSelected(new Set())}
                                style={{ fontSize: '.68rem' }}
                            >
                                Clear selection
                            </button>
                        )}
                        <button
                            className="btn btn-ghost btn-sm"
                            disabled={scanning}
                            onClick={async () => {
                                setScanning(true);
                                setScanResult(null);
                                try {
                                    const res = await api.scanMobileJDs();
                                    setScanResult(`${res.processed} scanned`);
                                    if (res.processed > 0) fetchJobs();
                                } catch (err: any) {
                                    setScanResult(`Error: ${err.message}`);
                                } finally {
                                    setScanning(false);
                                }
                            }}
                            style={{ fontSize: '.68rem', marginLeft: 'auto' }}
                        >
                            {scanning ? 'Scanning...' : 'Scan Mobile JDs'}
                        </button>
                    </div>
                    {(scanResult || reviewError) && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {scanResult && (
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                                    {scanResult}
                                </span>
                            )}
                            {reviewError && (
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--red)' }}>
                                    {reviewError}
                                </span>
                            )}
                        </div>
                    )}

                    {trackerVisible && reviewStatus && (
                        <div style={{
                            border: '1px solid var(--border)',
                            background: 'var(--surface-2)',
                            borderRadius: '8px',
                            padding: '10px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '.64rem',
                                    fontWeight: 700,
                                    color: 'var(--text-secondary)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '.08em',
                                }}>
                                    LLM Review Queue
                                </span>
                                <span style={{
                                    marginLeft: 'auto',
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '.64rem',
                                    color: reviewStatus.running ? 'var(--accent)' : 'var(--text-secondary)',
                                }}>
                                    {reviewStatus.running ? 'Running' : 'Idle'}
                                </span>
                            </div>
                            <div style={{
                                height: '8px',
                                borderRadius: '999px',
                                background: 'var(--surface-3)',
                                overflow: 'hidden',
                            }}>
                                <div style={{
                                    width: `${progressPercent}%`,
                                    height: '100%',
                                    background: 'linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 45%, white))',
                                    transition: 'width .2s ease',
                                }} />
                            </div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                    {reviewStatus.summary.completed}/{reviewStatus.summary.total} done
                                </span>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                    {reviewStatus.summary.queued} queued
                                </span>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                    {reviewStatus.summary.reviewing} reviewing
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
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                                    Model: {reviewStatus.resolved_model || 'waiting for model'}
                                </span>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                                    {reviewStatus.active_job
                                        ? `Current: #${reviewStatus.active_job.job_id} ${reviewStatus.active_job.title || ''}`.trim()
                                        : reviewStatus.running
                                            ? 'Current: preparing next job'
                                            : 'Current: queue complete'}
                                </span>
                            </div>
                            <div style={{
                                maxHeight: '220px',
                                overflowY: 'auto',
                                borderTop: '1px solid var(--border)',
                                paddingTop: '8px',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '6px',
                            }}>
                                {reviewStatus.items.map((item) => (
                                    <div key={`${reviewStatus.batch_id}-${item.job_id}`} style={{
                                        padding: '8px',
                                        border: '1px solid var(--border)',
                                        borderRadius: '6px',
                                        background: 'var(--surface)',
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
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
                                                fontSize: '.62rem',
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
                                                lineHeight: 1.45,
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
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {jobs.length === 0 ? (
                        <div style={{
                            padding: '24px 14px',
                            textAlign: 'center',
                            color: 'var(--text-secondary)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.78rem',
                        }}>
                            No pending jobs — new scrape, rescue, and ingest jobs land here before tailoring
                        </div>
                    ) : jobs.map((job) => {
                        const isFocused = focusedId === job.id;
                        const isChecked = selected.has(job.id);
                        return (
                            <div
                                key={job.id}
                                style={{
                                    padding: '9px 14px',
                                    cursor: 'pointer',
                                    borderBottom: '1px solid var(--border)',
                                    borderLeft: isFocused ? '2px solid var(--accent)' : '2px solid transparent',
                                    background: isFocused
                                        ? 'var(--accent-light)'
                                        : isChecked
                                            ? 'rgba(var(--accent-rgb, 100,150,255), 0.06)'
                                            : 'transparent',
                                    transition: 'background .08s',
                                    display: 'flex',
                                    alignItems: 'flex-start',
                                    gap: '8px',
                                }}
                                onMouseEnter={(event) => {
                                    if (!isFocused && !isChecked) event.currentTarget.style.background = 'var(--surface-2)';
                                }}
                                onMouseLeave={(event) => {
                                    if (!isFocused && !isChecked) event.currentTarget.style.background = 'transparent';
                                }}
                            >
                                <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => toggle(job.id)}
                                    onClick={(event) => event.stopPropagation()}
                                    style={{ accentColor: 'var(--accent)', marginTop: '3px', flexShrink: 0 }}
                                />
                                <div style={{ flex: 1, minWidth: 0 }} onClick={() => setFocusedId(job.id)}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)', flexShrink: 0 }}>
                                            #{job.id}
                                        </span>
                                        <span style={{
                                            fontWeight: 600,
                                            fontSize: '.82rem',
                                            flex: 1,
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                        }}>
                                            {job.title || 'Untitled'}
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '2px' }}>
                                        {job.board && (
                                            <span style={{
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.66rem',
                                                color: 'var(--accent)',
                                                background: 'rgba(var(--accent-rgb, 100,150,255), 0.1)',
                                                padding: '1px 6px',
                                                borderRadius: '3px',
                                            }}>
                                                {job.board}
                                            </span>
                                        )}
                                        {job.seniority && (
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                                {job.seniority}
                                            </span>
                                        )}
                                        {job.created_at && (
                                            <span style={{
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.66rem',
                                                color: 'var(--text-secondary)',
                                                marginLeft: 'auto',
                                            }}>
                                                {timeAgo(job.created_at)}
                                            </span>
                                        )}
                                    </div>
                                    {job.snippet && (
                                        <div style={{
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.66rem',
                                            color: 'var(--text-secondary)',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                        }}>
                                            {job.snippet}
                                        </div>
                                    )}
                                    {job.url && (
                                        <div style={{
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.62rem',
                                            color: 'var(--text-secondary)',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                            opacity: 0.6,
                                        }}>
                                            {job.url}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: '20px' }}>
                {!focusedId ? (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        height: '100%',
                        color: 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '.8rem',
                    }}>
                        Select a job to review
                    </div>
                ) : detailLoading ? (
                    <div className="loading"><div className="spinner" /></div>
                ) : !detail ? (
                    <div style={{
                        color: 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '.8rem',
                        textAlign: 'center',
                        padding: '40px',
                    }}>
                        Job not found
                    </div>
                ) : (
                    <div style={{ maxWidth: '800px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0, flex: 1 }}>
                                Job #{detail.id}: {detail.title || 'Untitled'}
                            </h2>
                            <button
                                className="btn btn-primary btn-sm"
                                disabled={!!busy}
                                onClick={() => handleApprove([detail.id])}
                            >
                                {busy === 'approve' ? 'Approving...' : 'Approve'}
                            </button>
                            <button
                                className="btn btn-sm"
                                disabled={!!busy}
                                onClick={() => handleReject([detail.id])}
                                style={{ background: 'var(--red, #c44)', color: '#fff', border: 'none' }}
                            >
                                {busy === 'reject' ? 'Rejecting...' : 'Reject'}
                            </button>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {Object.entries(detail).map(([key, value]) => (
                                <div key={key} style={{ borderBottom: '1px solid var(--border)', paddingBottom: '10px' }}>
                                    <div style={{
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '.7rem',
                                        color: 'var(--text-secondary)',
                                        textTransform: 'uppercase',
                                        letterSpacing: '.08em',
                                        marginBottom: '4px',
                                    }}>
                                        {key}
                                    </div>
                                    {key === 'url' && typeof value === 'string' ? (
                                        <a
                                            href={value}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            style={{ fontFamily: 'var(--font-mono)', fontSize: '.78rem', wordBreak: 'break-all' }}
                                        >
                                            {value}
                                        </a>
                                    ) : (
                                        <pre style={{
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.78rem',
                                            lineHeight: 1.5,
                                            whiteSpace: 'pre-wrap',
                                            wordBreak: 'break-word',
                                            color: 'var(--text)',
                                            margin: 0,
                                            maxHeight: key === 'jd_text' ? '400px' : '200px',
                                            overflow: 'auto',
                                        }}>
                                            {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                                        </pre>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
