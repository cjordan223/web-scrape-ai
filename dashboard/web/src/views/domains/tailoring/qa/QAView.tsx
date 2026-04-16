import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import { fmtDate, timeAgo, sourceMeta, normalizeSource, compactHost, type SourceFilter } from '../../../../utils';
import { CollapsibleSection } from '../../../../components/CollapsibleSection';

interface QAJob {
    id: number;
    title?: string;
    url?: string;
    snippet?: string;
    board?: string;
    seniority?: string;
    created_at?: string;
    company?: string;
    source?: string;
    location?: string;
    salary_k?: number | null;
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

const QUEUE_BATCH_PRESETS = [10, 25, 50, 100];
const QA_ACCENT = '#d97830';
const QA_ACCENT_SOFT = 'rgba(217, 120, 48, 0.14)';
const QA_PANEL = 'linear-gradient(180deg, rgba(217, 120, 48, 0.10), rgba(196, 79, 79, 0.04))';

const toolbarFieldStyle: React.CSSProperties = {
    minWidth: 0,
    padding: '10px 12px',
    borderRadius: '10px',
    border: '1px solid rgba(217, 120, 48, 0.22)',
    background: 'rgba(15, 19, 26, 0.96)',
    color: '#edf2ff',
    fontSize: '.84rem',
    fontFamily: 'var(--font)',
    fontWeight: 500,
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)',
};

function FieldLabel({ children }: { children: React.ReactNode }) {
    return (
        <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '.64rem',
            fontWeight: 600,
            color: 'var(--text-secondary)',
            textTransform: 'uppercase',
            letterSpacing: '.08em',
            marginBottom: '4px',
        }}>
            {children}
        </div>
    );
}

function DetailMeta({ label, value }: { label: string; value?: React.ReactNode }) {
    if (value === undefined || value === null || value === '') return null;
    return (
        <div style={{
            padding: '8px 10px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
        }}>
            <FieldLabel>{label}</FieldLabel>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.74rem', color: 'var(--text)', lineHeight: 1.45 }}>
                {value}
            </div>
        </div>
    );
}

function QADetailPanel({
    detail,
    busy,
    onApprove,
    onReject,
    onPermanentlyReject,
}: {
    detail: any;
    busy: 'approve' | 'reject' | 'llm-review' | null;
    onApprove: (id: number) => void;
    onReject: (id: number) => void;
    onPermanentlyReject: (id: number) => void;
}) {
    const source = sourceMeta(normalizeSource(detail.source));
    const logistics = [detail.location, detail.seniority, detail.salary_k ? `$${Math.round(Number(detail.salary_k) / 1000)}K` : ''].filter(Boolean);

    return (
        <div style={{ padding: '18px 22px 26px' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', justifyContent: 'space-between', marginBottom: '18px', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: '280px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
                        <span style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.62rem',
                            fontWeight: 600,
                            color: 'var(--accent)',
                            background: 'var(--accent-light)',
                            border: '1px solid var(--accent-dim)',
                            borderRadius: '4px',
                            padding: '2px 8px',
                            textTransform: 'uppercase',
                            letterSpacing: '.08em',
                        }}>
                            Job #{detail.id}
                        </span>
                        {detail.company ? (
                            <span style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                borderRadius: '999px',
                                border: '1px solid rgba(42, 184, 204, 0.25)',
                                background: 'rgba(42, 184, 204, 0.08)',
                                color: 'var(--cyan, #2ab8cc)',
                                padding: '1px 8px',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '.62rem',
                                fontWeight: 600,
                            }}>
                                {detail.company}
                            </span>
                        ) : null}
                        {detail.board ? <span className={`pill pill-${detail.board}`} style={{ fontSize: '.67rem' }}>{detail.board}</span> : null}
                        <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            borderRadius: '999px',
                            border: `1px solid ${source.border}`,
                            background: source.background,
                            color: source.color,
                            padding: '1px 8px',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.62rem',
                            fontWeight: 600,
                        }}>
                            {source.label}
                        </span>
                        {logistics.map((item) => (
                            <span key={item} style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                borderRadius: '999px',
                                border: '1px solid var(--border)',
                                background: 'var(--surface-2)',
                                color: 'var(--text-secondary)',
                                padding: '1px 8px',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '.62rem',
                                fontWeight: 600,
                            }}>
                                {item}
                            </span>
                        ))}
                    </div>
                    <h3 style={{ fontSize: '1.05rem', fontWeight: 600, lineHeight: 1.35, color: 'var(--text)', margin: 0 }}>
                        {detail.title || 'Untitled'}
                    </h3>
                    {detail.url ? (
                        <a
                            href={detail.url}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                                display: 'inline-block',
                                marginTop: '8px',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '.72rem',
                                color: 'var(--accent)',
                                textDecoration: 'none',
                                wordBreak: 'break-all',
                            }}
                        >
                            {detail.url}
                        </a>
                    ) : null}
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                        className="btn btn-primary btn-sm"
                        disabled={!!busy}
                        onClick={() => onApprove(detail.id)}
                    >
                        {busy === 'approve' ? 'Approving...' : 'Approve'}
                    </button>
                    <button
                        className="btn btn-sm"
                        disabled={!!busy}
                        onClick={() => onReject(detail.id)}
                        style={{ background: 'var(--red, #c44)', color: '#fff', border: 'none' }}
                    >
                        {busy === 'reject' ? 'Rejecting...' : 'Reject'}
                    </button>
                    <button
                        className="btn btn-sm"
                        disabled={!!busy}
                        onClick={() => onPermanentlyReject(detail.id)}
                        style={{ background: 'rgba(140, 20, 20, 0.85)', color: '#fff', border: '1px solid rgba(200, 40, 40, 0.4)' }}
                    >
                        Dead
                    </button>
                </div>
            </div>

            {detail.snippet ? (
                <div style={{ marginBottom: '20px' }}>
                    <FieldLabel>Requirements Summary</FieldLabel>
                    <div style={{
                        fontSize: '.84rem',
                        lineHeight: 1.6,
                        color: 'var(--text)',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: '6px',
                        padding: '12px 14px',
                    }}>
                        {detail.snippet}
                    </div>
                </div>
            ) : null}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px', marginBottom: '20px' }}>
                <DetailMeta label="Created" value={detail.created_at ? fmtDate(detail.created_at) : undefined} />
                <DetailMeta label="Query" value={detail.query} />
                <DetailMeta label="Run ID" value={detail.run_id} />
                <DetailMeta label="Decision" value={detail.decision} />
            </div>

            {detail.jd_text ? (
                <CollapsibleSection title="Full JD Text" defaultOpen>
                    <pre style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '.74rem',
                        lineHeight: 1.6,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        color: 'var(--text)',
                        margin: 0,
                        maxHeight: '420px',
                        overflow: 'auto',
                        padding: '12px',
                        background: 'var(--surface)',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                    }}>
                        {detail.jd_text}
                    </pre>
                </CollapsibleSection>
            ) : null}
        </div>
    );
}

export default function QAView() {
    const [jobs, setJobs] = useState<QAJob[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [queueBatchSize, setQueueBatchSize] = useState('25');
    const [focusedId, setFocusedId] = useState<number | null>(null);
    const [detail, setDetail] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [busy, setBusy] = useState<'approve' | 'reject' | 'llm-review' | null>(null);
    const [scanning, setScanning] = useState(false);
    const [scanResult, setScanResult] = useState<string | null>(null);
    const [reviewStatus, setReviewStatus] = useState<QALlmReviewStatus | null>(null);
    const [reviewError, setReviewError] = useState<string | null>(null);
    const [scrapeEnabled, setScrapeEnabled] = useState<boolean | null>(null);
    const [scrapeToggling, setScrapeToggling] = useState(false);
    const [boardFilter, setBoardFilter] = useState('');
    const [sourceFilter, setSourceFilter] = useState<'' | SourceFilter>('');
    const [searchFilter, setSearchFilter] = useState('');

    const jobsIntervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
    const reviewIntervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
    const reviewSignatureRef = useRef<string>('');

    const fetchJobs = useCallback(async () => {
        try {
            const res = await api.getQAPending(2000, {
                board: boardFilter || undefined,
                source: sourceFilter || undefined,
                search: searchFilter || undefined,
            });
            const items = res.items || [];
            setJobs(items);
            setTotal(res.total ?? items.length);
            setSelected((prev) => new Set(Array.from(prev).filter((id) => items.some((item: QAJob) => item.id === id))));
            setFocusedId((prev) => (prev && items.some((item: QAJob) => item.id === prev) ? prev : null));
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [boardFilter, searchFilter, sourceFilter]);

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

    const fetchScrapeEnabled = useCallback(async () => {
        try {
            const res = await api.getRunsControls();
            setScrapeEnabled(res.scrape_enabled ?? null);
        } catch {
            // ignore
        }
    }, []);

    const toggleScrape = async () => {
        if (scrapeEnabled === null) return;
        setScrapeToggling(true);
        try {
            await api.setScrapeEnabled(!scrapeEnabled);
            setScrapeEnabled(!scrapeEnabled);
        } catch (err) {
            console.error(err);
        } finally {
            setScrapeToggling(false);
        }
    };

    useEffect(() => {
        fetchJobs();
        fetchReviewStatus();
        fetchScrapeEnabled();
        jobsIntervalRef.current = setInterval(fetchJobs, 30000);
        reviewIntervalRef.current = setInterval(fetchReviewStatus, 2500);
        return () => {
            clearInterval(jobsIntervalRef.current);
            clearInterval(reviewIntervalRef.current);
        };
    }, [fetchJobs, fetchReviewStatus, fetchScrapeEnabled]);

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

    const toggleFocused = (id: number) => {
        setFocusedId((prev) => prev === id ? null : id);
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

    const handlePermanentlyReject = async (ids: number[]) => {
        if (!ids.length) return;
        setBusy('reject');
        try {
            await api.permanentlyRejectQA(ids);
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
    const parsedQueueBatchSize = Number.parseInt(queueBatchSize, 10);
    const queueFirstCount = Number.isFinite(parsedQueueBatchSize) ? Math.max(0, parsedQueueBatchSize) : 0;
    const queueFirstIds = jobs.slice(0, queueFirstCount).map((job) => job.id);
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

    const boardOptions = Array.from(new Set(jobs.map((job) => (job.board || '').trim()).filter(Boolean)));
    if (boardFilter && !boardOptions.includes(boardFilter)) boardOptions.push(boardFilter);
    boardOptions.sort((a, b) => a.localeCompare(b));

    const sourceOptions: SourceFilter[] = Array.from(new Set(jobs.map((job) => normalizeSource(job.source))));
    if (sourceFilter && !sourceOptions.includes(sourceFilter)) sourceOptions.push(sourceFilter);
    sourceOptions.sort((a, b) => a.localeCompare(b));

    if (loading) {
        return <div className="view-container"><div className="loading"><div className="spinner" /></div></div>;
    }

    return (
        <div style={{ height: 'calc(100vh - 56px)', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                <div style={{
                    padding: '14px 16px',
                    borderBottom: '1px solid rgba(217, 120, 48, 0.16)',
                    background: QA_PANEL,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    boxShadow: 'inset 0 -1px 0 rgba(255,255,255,0.02)',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.94rem',
                            fontWeight: 700,
                            color: '#f4ede8',
                            letterSpacing: '.01em',
                        }}>
                            QA Triage
                        </span>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.76rem',
                            fontWeight: 500,
                            color: 'rgba(233, 220, 210, 0.78)',
                        }}>
                            Review incoming jobs before they move forward. {total} pending.
                        </span>
                    </div>
                    {scrapeEnabled !== null && (
                        <button
                            className="btn btn-sm"
                            disabled={scrapeToggling}
                            onClick={toggleScrape}
                            style={{
                                fontSize: '.74rem',
                                fontFamily: 'var(--font)',
                                fontWeight: 700,
                                padding: '6px 12px',
                                background: scrapeEnabled ? 'var(--red, #c44)' : 'var(--green, #2a2)',
                                color: '#fff',
                                border: 'none',
                                borderRadius: '8px',
                            }}
                        >
                            {scrapeToggling ? '...' : scrapeEnabled ? 'Stop Pipeline' : 'Start Pipeline'}
                        </button>
                    )}
                </div>

                <div style={{
                    padding: '14px 14px 12px',
                    borderBottom: '1px solid rgba(217, 120, 48, 0.12)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                    background: 'linear-gradient(180deg, rgba(217, 120, 48, 0.05), rgba(19, 24, 31, 0.98))',
                }}>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={!!busy || selected.size === 0}
                            onClick={() => handleApprove(Array.from(selected))}
                            style={{ flex: 1, fontFamily: 'var(--font)', fontWeight: 700, minHeight: '38px' }}
                        >
                            {busy === 'approve' ? 'Approving...' : `Approve Selected (${selected.size})`}
                        </button>
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || selected.size === 0}
                            onClick={() => handleReject(Array.from(selected))}
                            style={{ flex: 1, background: 'var(--red, #c44)', color: '#fff', border: 'none', fontFamily: 'var(--font)', fontWeight: 700, minHeight: '38px' }}
                        >
                            {busy === 'reject' ? 'Rejecting...' : `Reject Selected (${selected.size})`}
                        </button>
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || selected.size === 0}
                            onClick={() => handlePermanentlyReject(Array.from(selected))}
                            style={{ background: 'rgba(140, 20, 20, 0.85)', color: '#fff', border: '1px solid rgba(200, 40, 40, 0.4)', fontFamily: 'var(--font)', fontWeight: 700, minHeight: '38px' }}
                        >
                            {busy === 'reject' ? 'Rejecting...' : `Dead (${selected.size})`}
                        </button>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || queueTargetIds.length === 0}
                            onClick={() => handleLlmReview(queueTargetIds)}
                            style={{ flex: 1, background: 'rgba(31, 39, 52, 0.92)', border: '1px solid rgba(217, 120, 48, 0.18)', fontFamily: 'var(--font)', fontWeight: 600, minHeight: '38px', color: '#eef3ff' }}
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
                            fontFamily: 'var(--font)',
                            fontSize: '.74rem',
                            fontWeight: 700,
                            color: 'rgba(236, 228, 220, 0.82)',
                            textTransform: 'uppercase',
                            letterSpacing: '.06em',
                            whiteSpace: 'nowrap',
                        }}>
                            First
                        </label>
                        <input
                            type="number"
                            min={1}
                            step={1}
                            inputMode="numeric"
                            value={queueBatchSize}
                            onChange={(e) => setQueueBatchSize(e.target.value)}
                            style={{ ...toolbarFieldStyle, width: '92px', minWidth: '92px' }}
                        />
                        <button
                            className="btn btn-sm"
                            disabled={!!busy || queueFirstIds.length === 0}
                            onClick={() => handleLlmReview(queueFirstIds)}
                            style={{
                                flex: 1,
                                background: 'rgba(31, 39, 52, 0.92)',
                                border: '1px solid rgba(217, 120, 48, 0.18)',
                                fontFamily: 'var(--font)',
                                fontWeight: 600,
                                minHeight: '38px',
                                color: '#eef3ff',
                            }}
                        >
                            {busy === 'llm-review'
                                ? 'Queueing...'
                                : `Queue First ${queueFirstIds.length}${queueFirstCount > jobs.length ? ` of ${jobs.length}` : ''}`}
                        </button>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.7rem',
                            fontWeight: 700,
                            color: 'rgba(236, 228, 220, 0.76)',
                            textTransform: 'uppercase',
                            letterSpacing: '.06em',
                        }}>
                            Quick queue
                        </span>
                        {QUEUE_BATCH_PRESETS.map((size) => {
                            const active = queueBatchSize === String(size);
                            const available = Math.min(size, jobs.length);
                            return (
                                <button
                                    key={size}
                                    className="btn btn-ghost btn-sm"
                                    disabled={jobs.length === 0}
                                    onClick={() => setQueueBatchSize(String(size))}
                                    style={{
                                        fontSize: '.7rem',
                                        padding: '5px 9px',
                                        fontFamily: 'var(--font)',
                                        fontWeight: active ? 700 : 600,
                                        border: `1px solid ${active ? QA_ACCENT : 'rgba(217, 120, 48, 0.14)'}`,
                                        background: active ? QA_ACCENT_SOFT : 'rgba(19, 24, 31, 0.85)',
                                        color: active ? '#f5e7dc' : 'rgba(228, 220, 213, 0.72)',
                                    }}
                                >
                                    {available === size ? size : `${size} (${available})`}
                                </button>
                            );
                        })}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, .85fr) minmax(0, .9fr) auto', gap: '10px', alignItems: 'center' }}>
                        <input
                            type="text"
                            value={searchFilter}
                            onChange={(e) => setSearchFilter(e.target.value)}
                            placeholder="Search title, company, URL..."
                            style={toolbarFieldStyle}
                        />
                        <select value={boardFilter} onChange={(e) => setBoardFilter(e.target.value)} style={toolbarFieldStyle}>
                            <option value="">All Boards</option>
                            {boardOptions.map((board) => <option key={board} value={board}>{board}</option>)}
                        </select>
                        <select value={sourceFilter} onChange={(e) => setSourceFilter((e.target.value || '') as '' | SourceFilter)} style={toolbarFieldStyle}>
                            <option value="">All Sources</option>
                            {sourceOptions.map((source) => <option key={source} value={source}>{sourceMeta(source).label}</option>)}
                        </select>
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => {
                                setSearchFilter('');
                                setBoardFilter('');
                                setSourceFilter('');
                            }}
                            disabled={!searchFilter && !boardFilter && !sourceFilter}
                            style={{ fontSize: '.72rem', whiteSpace: 'nowrap', fontFamily: 'var(--font)', fontWeight: 600 }}
                        >
                            Clear filters
                        </button>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            fontFamily: 'var(--font)',
                            fontSize: '.78rem',
                            fontWeight: 600,
                            color: '#e6ecf5',
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
                                style={{ fontSize: '.72rem', fontFamily: 'var(--font)', fontWeight: 600 }}
                            >
                                Clear selection
                            </button>
                        )}
                        {(searchFilter || boardFilter || sourceFilter) && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                <span>{total} matching jobs</span>
                                {boardFilter ? <span>board: {boardFilter}</span> : null}
                                {sourceFilter ? <span>source: {sourceMeta(sourceFilter).label}</span> : null}
                                {searchFilter ? <span>search: "{searchFilter}"</span> : null}
                            </div>
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
                            style={{ fontSize: '.72rem', marginLeft: 'auto', fontFamily: 'var(--font)', fontWeight: 600 }}
                        >
                            {scanning ? 'Scanning...' : 'Scan Mobile JDs'}
                        </button>
                    </div>
                    {(scanResult || reviewError) && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {scanResult ? (
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                                    {scanResult}
                                </span>
                            ) : null}
                            {reviewError ? (
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--red)' }}>
                                    {reviewError}
                                </span>
                            ) : null}
                        </div>
                    )}

                    {trackerVisible && reviewStatus && (
                        <div style={{
                            border: '1px solid rgba(217, 120, 48, 0.14)',
                            background: 'linear-gradient(180deg, rgba(28, 35, 46, 0.96), rgba(20, 24, 32, 0.96))',
                            borderRadius: '12px',
                            padding: '12px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                            boxShadow: '0 10px 24px rgba(0,0,0,0.18)',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{
                                    fontFamily: 'var(--font)',
                                    fontSize: '.72rem',
                                    fontWeight: 700,
                                    color: '#f0e6de',
                                    textTransform: 'uppercase',
                                    letterSpacing: '.08em',
                                }}>
                                    LLM Review Queue
                                </span>
                                <span style={{
                                    marginLeft: 'auto',
                                    fontFamily: 'var(--font)',
                                    fontSize: '.72rem',
                                    fontWeight: 700,
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
                                    background: 'linear-gradient(90deg, #d97830, #e6b36d)',
                                    transition: 'width .2s ease',
                                }} />
                            </div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.74rem', fontWeight: 600, color: '#d6dce5' }}>
                                    {reviewStatus.summary.completed}/{reviewStatus.summary.total} done
                                </span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.74rem', fontWeight: 600, color: '#d6dce5' }}>
                                    {reviewStatus.summary.queued} queued
                                </span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.74rem', fontWeight: 600, color: '#d6dce5' }}>
                                    {reviewStatus.summary.reviewing} reviewing
                                </span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.74rem', fontWeight: 700, color: 'var(--green)' }}>
                                    {reviewStatus.summary.passed} approved
                                </span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.74rem', fontWeight: 700, color: 'var(--red)' }}>
                                    {reviewStatus.summary.failed} rejected
                                </span>
                                {reviewStatus.summary.errors > 0 ? (
                                    <span style={{ fontFamily: 'var(--font)', fontSize: '.74rem', fontWeight: 700, color: 'var(--red)' }}>
                                        {reviewStatus.summary.errors} errors
                                    </span>
                                ) : null}
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.72rem', color: '#d1d8e2' }}>
                                    Model: {reviewStatus.resolved_model || 'waiting for model'}
                                </span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.72rem', color: '#d1d8e2' }}>
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
                                        {item.reason && item.status !== 'queued' && item.status !== 'reviewing' ? (
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
                                        ) : null}
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
                    ) : (
                        <div>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: '44px minmax(320px, 2.1fr) minmax(220px, 1.15fr) minmax(150px, .9fr) minmax(120px, .7fr) 78px',
                                gap: '12px',
                                alignItems: 'center',
                                padding: '10px 14px',
                                borderBottom: '1px solid rgba(217, 120, 48, 0.14)',
                                background: 'linear-gradient(180deg, rgba(217, 120, 48, 0.08), rgba(28, 35, 46, 0.94))',
                                position: 'sticky',
                                top: 0,
                                zIndex: 1,
                            }}>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.68rem', fontWeight: 700, color: 'rgba(238,228,220,0.76)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Pick</span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.68rem', fontWeight: 700, color: 'rgba(238,228,220,0.76)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Job</span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.68rem', fontWeight: 700, color: 'rgba(238,228,220,0.76)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Company + Source</span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.68rem', fontWeight: 700, color: 'rgba(238,228,220,0.76)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Context</span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.68rem', fontWeight: 700, color: 'rgba(238,228,220,0.76)', textTransform: 'uppercase', letterSpacing: '.08em' }}>JD Link</span>
                                <span style={{ fontFamily: 'var(--font)', fontSize: '.68rem', fontWeight: 700, color: 'rgba(238,228,220,0.76)', textTransform: 'uppercase', letterSpacing: '.08em', textAlign: 'right' }}>Open</span>
                            </div>

                            {jobs.map((job) => {
                                const isFocused = focusedId === job.id;
                                const isChecked = selected.has(job.id);
                                const source = sourceMeta(normalizeSource(job.source));
                                const company = job.company?.trim() || '';
                                const host = compactHost(job.url);
                                const logistics = [job.location, job.seniority, job.salary_k ? `$${Math.round(Number(job.salary_k) / 1000)}K` : ''].filter(Boolean);

                                return (
                                    <div key={job.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                        <div
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: '44px minmax(320px, 2.1fr) minmax(220px, 1.15fr) minmax(150px, .9fr) minmax(120px, .7fr) 78px',
                                                gap: '12px',
                                                alignItems: 'start',
                                                padding: '12px 14px',
                                                cursor: 'pointer',
                                                borderLeft: isFocused ? '2px solid var(--accent)' : '2px solid transparent',
                                                background: isFocused ? 'var(--accent-light)' : isChecked ? 'rgba(var(--accent-rgb, 100,150,255), 0.06)' : 'transparent',
                                                transition: 'background .08s',
                                            }}
                                            onClick={() => toggleFocused(job.id)}
                                            onMouseEnter={(event) => {
                                                if (!isFocused && !isChecked) event.currentTarget.style.background = 'var(--surface-2)';
                                            }}
                                            onMouseLeave={(event) => {
                                                if (!isFocused && !isChecked) event.currentTarget.style.background = 'transparent';
                                            }}
                                        >
                                            <div style={{ display: 'flex', justifyContent: 'center', paddingTop: '2px' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={isChecked}
                                                    onChange={() => toggle(job.id)}
                                                    onClick={(event) => event.stopPropagation()}
                                                    style={{ accentColor: 'var(--accent)' }}
                                                />
                                            </div>

                                            <div style={{ minWidth: 0 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)', flexShrink: 0 }}>
                                                        #{job.id}
                                                    </span>
                                                    <span style={{ fontFamily: 'var(--font)', fontWeight: 700, fontSize: '.94rem', lineHeight: 1.35, color: '#edf1f7' }}>
                                                        {job.title || 'Untitled'}
                                                    </span>
                                                </div>
                                                {job.snippet ? (
                                                    <div style={{
                                                        fontFamily: 'var(--font)',
                                                        fontSize: '.8rem',
                                                        color: '#b9c5d5',
                                                        lineHeight: 1.55,
                                                        display: '-webkit-box',
                                                        WebkitLineClamp: 2,
                                                        WebkitBoxOrient: 'vertical',
                                                        overflow: 'hidden',
                                                        marginBottom: '6px',
                                                    }}>
                                                        {job.snippet}
                                                    </div>
                                                ) : null}
                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                                    {host ? <span>{host}</span> : null}
                                                    {job.created_at ? <span title={fmtDate(job.created_at)}>{timeAgo(job.created_at)}</span> : null}
                                                </div>
                                            </div>

                                            <div style={{ minWidth: 0 }}>
                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
                                                    {company ? (
                                                        <span style={{
                                                            display: 'inline-flex',
                                                            alignItems: 'center',
                                                            borderRadius: '999px',
                                                            border: '1px solid rgba(42, 184, 204, 0.25)',
                                                            background: 'rgba(42, 184, 204, 0.08)',
                                                            color: 'var(--cyan, #2ab8cc)',
                                                            padding: '1px 8px',
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '.62rem',
                                                            fontWeight: 600,
                                                        }}>
                                                            {company}
                                                        </span>
                                                    ) : null}
                                                    {job.board ? <span className={`pill pill-${job.board}`} style={{ fontSize: '.67rem' }}>{job.board}</span> : null}
                                                    <span style={{
                                                        display: 'inline-flex',
                                                        alignItems: 'center',
                                                        borderRadius: '999px',
                                                        border: `1px solid ${source.border}`,
                                                        background: source.background,
                                                        color: source.color,
                                                        padding: '1px 8px',
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '.62rem',
                                                        fontWeight: 600,
                                                    }}>
                                                        {source.label}
                                                    </span>
                                                </div>
                                                <div style={{ fontFamily: 'var(--font)', fontSize: '.76rem', color: '#a9b6c8', lineHeight: 1.45 }}>
                                                    {job.url || 'No source URL'}
                                                </div>
                                            </div>

                                            <div style={{ minWidth: 0, display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                                {logistics.length > 0 ? logistics.map((item) => (
                                                    <span key={item} style={{
                                                        display: 'inline-flex',
                                                        alignItems: 'center',
                                                        borderRadius: '999px',
                                                        border: '1px solid var(--border)',
                                                        background: 'var(--surface-2)',
                                                        color: 'var(--text-secondary)',
                                                        padding: '1px 8px',
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '.62rem',
                                                        fontWeight: 600,
                                                    }}>
                                                        {item}
                                                    </span>
                                                )) : (
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>No extra metadata</span>
                                                )}
                                            </div>

                                            <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                {job.url ? (
                                                    <a
                                                        href={job.url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        onClick={(event) => event.stopPropagation()}
                                                        style={{
                                                            display: 'inline-flex',
                                                            alignItems: 'center',
                                                            justifyContent: 'center',
                                                            width: 'fit-content',
                                                            borderRadius: '999px',
                                                            border: '1px solid rgba(217, 120, 48, 0.35)',
                                                            background: 'rgba(217, 120, 48, 0.12)',
                                                            color: '#f3c7a4',
                                                            padding: '5px 11px',
                                                            fontFamily: 'var(--font)',
                                                            fontSize: '.68rem',
                                                            fontWeight: 700,
                                                            letterSpacing: '.03em',
                                                            textDecoration: 'none',
                                                            textTransform: 'uppercase',
                                                        }}
                                                    >
                                                        Open JD
                                                    </a>
                                                ) : (
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>No link</span>
                                                )}
                                            </div>

                                            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'flex-start', paddingTop: '2px' }}>
                                                <span style={{
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '.86rem',
                                                    color: isFocused ? 'var(--accent)' : 'var(--text-secondary)',
                                                    transform: isFocused ? 'rotate(180deg)' : 'rotate(0deg)',
                                                    transition: 'transform .15s ease',
                                                }}>
                                                    ▾
                                                </span>
                                            </div>
                                        </div>

                                        {isFocused ? (
                                            <div style={{ background: 'rgba(75, 142, 240, 0.05)', borderTop: '1px solid var(--border)' }}>
                                                {detailLoading ? (
                                                    <div className="loading" style={{ minHeight: '220px' }}><div className="spinner" /></div>
                                                ) : !detail ? (
                                                    <div style={{
                                                        color: 'var(--text-secondary)',
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '.8rem',
                                                        textAlign: 'center',
                                                        padding: '32px',
                                                    }}>
                                                        Job not found
                                                    </div>
                                                ) : (
                                                    <QADetailPanel
                                                        detail={detail}
                                                        busy={busy}
                                                        onApprove={(id) => handleApprove([id])}
                                                        onReject={(id) => handleReject([id])}
                                                        onPermanentlyReject={(id) => handlePermanentlyReject([id])}
                                                    />
                                                )}
                                            </div>
                                        ) : null}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
