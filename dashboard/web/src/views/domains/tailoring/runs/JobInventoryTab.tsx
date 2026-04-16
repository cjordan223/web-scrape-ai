import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../../../../api';
import { fmtDate, timeAgo, sourceMeta, normalizeSource, compactHost, type SourceFilter } from '../../../../utils';
import { CollapsibleSection } from '../../../../components/CollapsibleSection';

interface ReadyJob {
    id: number;
    title?: string;
    company?: string;
    board?: string;
    source?: string;
    seniority?: string;
    location?: string;
    salary_k?: number | null;
    snippet?: string;
    created_at?: string;
    url?: string;
    tailoring_run_count?: number;
    has_tailoring_runs?: boolean;
    tailoring_latest_status?: 'complete' | 'partial' | 'failed' | 'no-trace' | string;
    applied?: { id: number; status?: string } | null;
    queue_item?: { id: number; status?: 'queued' | 'running' | string } | null;
    ready_bucket?: 'backlog' | 'next' | 'later' | string;
    ready_bucket_updated_at?: string | null;
}

interface Briefing {
    job: any;
    analysis: any | null;
    resume_strategy: any | null;
    cover_strategy: any | null;
    run_slug: string | null;
}

interface Props {
    onRunStarted: () => void;
}

type ReadySortKey = 'job' | 'company' | 'context' | 'date_added' | 'history';
type ReadyBucket = 'backlog' | 'next' | 'later';

const READY_BUCKETS: ReadyBucket[] = ['backlog', 'next', 'later'];
const READY_QUEUE_PRESETS = [10, 20, 50, 100];

function compareText(a?: string | null, b?: string | null) {
    return (a || '').localeCompare(b || '', undefined, { sensitivity: 'base' });
}

function normalizeReadyBucket(bucket?: string): ReadyBucket {
    if (bucket === 'next' || bucket === 'later') return bucket;
    return 'backlog';
}

function readyBucketMeta(bucket: ReadyBucket) {
    if (bucket === 'next') return { label: 'Queue Next', color: 'var(--green)', background: 'rgba(60, 179, 113, 0.10)', border: 'rgba(60, 179, 113, 0.32)' };
    if (bucket === 'later') return { label: 'Later', color: 'var(--amber, #e0a030)', background: 'rgba(224, 160, 48, 0.10)', border: 'rgba(224, 160, 48, 0.32)' };
    return { label: 'Backlog', color: 'var(--text-secondary)', background: 'var(--surface-2)', border: 'var(--border)' };
}

function apiErrorMessage(err: unknown, fallback: string) {
    const responseMessage = (err as any)?.response?.data?.error;
    const message = typeof responseMessage === 'string' && responseMessage.trim()
        ? responseMessage
        : (err as Error | undefined)?.message;
    return message && message.trim() ? message : fallback;
}

export default function JobInventoryTab({ onRunStarted }: Props) {
    const [readyJobs, setReadyJobs] = useState<ReadyJob[]>([]);
    const [readyTotal, setReadyTotal] = useState(0);
    const [bucketCounts, setBucketCounts] = useState<Record<ReadyBucket, number>>({ backlog: 0, next: 0, later: 0 });
    // boardOptions derived via useMemo to avoid extra render pass
    const [boardFilter, setBoardFilter] = useState<string[]>([]);
    const [sourceFilter, setSourceFilter] = useState<'' | SourceFilter>('');
    const [seniorityFilter, setSeniorityFilter] = useState('');
    const [locationFilter, setLocationFilter] = useState('');
    const [bucketFilter, setBucketFilter] = useState<'all' | ReadyBucket>('all');
    const [searchFilter, setSearchFilter] = useState('');
    const [untailoredOnly, setUntailoredOnly] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [focusedJobId, setFocusedJobId] = useState<number>(0);
    const [briefing, setBriefing] = useState<Briefing | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [skipAnalysis, setSkipAnalysis] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);
    const [queueError, setQueueError] = useState('');
    const [resetBusy, setResetBusy] = useState(false);
    const [sortKey, setSortKey] = useState<ReadySortKey>('date_added');
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
    const [queueBatchSize, setQueueBatchSize] = useState('20');

    const loadReadyJobs = useCallback(async () => {
        try {
            const res = await api.getTailoringReady(2000, {
                board: boardFilter.length ? boardFilter.join(',') : undefined,
                source: sourceFilter || undefined,
                seniority: seniorityFilter || undefined,
                location: locationFilter || undefined,
                search: searchFilter || undefined,
                bucket: bucketFilter,
            });
            const items = res.items || [];
            setReadyJobs(items);
            setReadyTotal(res.total || 0);
            setBucketCounts({
                backlog: Number(res.bucket_counts?.backlog || 0),
                next: Number(res.bucket_counts?.next || 0),
                later: Number(res.bucket_counts?.later || 0),
            });
            setSelectedIds(prev => new Set(Array.from(prev).filter(id => items.some((item: ReadyJob) => item.id === id))));
            setFocusedJobId(prev => (prev && items.some((item: ReadyJob) => item.id === prev) ? prev : 0));
        } catch (err) { console.error(err); }
    }, [boardFilter, bucketFilter, locationFilter, searchFilter, seniorityFilter, sourceFilter]);

    const boardOptions = useMemo(() => {
        const nextOptions: string[] = Array.from(new Set<string>(
            readyJobs.map((job: ReadyJob) => (job.board || '').trim()).filter(Boolean)
        ));
        boardFilter.forEach((board) => {
            if (board && !nextOptions.includes(board)) nextOptions.push(board);
        });
        nextOptions.sort((a, b) => a.localeCompare(b));
        return nextOptions;
    }, [readyJobs, boardFilter]);

    useEffect(() => {
        loadReadyJobs();
        const id = setInterval(loadReadyJobs, 15000);
        return () => clearInterval(id);
    }, [loadReadyJobs]);

    useEffect(() => {
        if (!focusedJobId) { setBriefing(null); return; }
        setDetailLoading(true);
        (async () => {
            try {
                const res = await api.getTailoringJobBriefing(focusedJobId);
                setBriefing(res);
            } catch { setBriefing(null); }
            finally { setDetailLoading(false); }
        })();
    }, [focusedJobId]);

    const toggleSelection = (id: number) => {
        const job = readyJobs.find((item) => item.id === id);
        if (job?.queue_item?.status === 'queued' || job?.queue_item?.status === 'running') {
            return;
        }
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const queueJobIds = async (jobIds: number[]) => {
        if (jobIds.length === 0) return;
        setQueueBusy(true);
        setQueueError('');
        try {
            const jobs = jobIds.map(job_id => ({ job_id, skip_analysis: skipAnalysis }));
            const res = await api.queueTailoring(jobs);
            if (!res.ok) { setQueueError(res.error || 'Failed to queue'); return; }
            if ((res.duplicates || []).length > 0 && (res.items || []).length === 0) {
                setQueueError(`${res.duplicates.length} job(s) were already queued or running`);
            }
            await loadReadyJobs();
            setSelectedIds(new Set());
            onRunStarted();
        } catch { setQueueError('Failed to queue jobs'); }
        finally { setQueueBusy(false); }
    };

    const queueSelected = async () => {
        await queueJobIds(Array.from(selectedIds));
    };

    const updateSelectedBucket = async (bucket: ReadyBucket) => {
        if (selectedIds.size === 0) return;
        setQueueBusy(true);
        setQueueError('');
        try {
            await api.setTailoringReadyBucket(Array.from(selectedIds), bucket);
            await loadReadyJobs();
            setSelectedIds(new Set());
        } catch {
            setQueueError(`Failed to move jobs to ${readyBucketMeta(bucket).label}`);
        } finally {
            setQueueBusy(false);
        }
    };

    const queueBucket = async (bucket: 'next' | 'later') => {
        setQueueBusy(true);
        setQueueError('');
        try {
            const res = await api.queueTailoringBucket(bucket, { skip_analysis: skipAnalysis, limit: 2000 });
            if (!res.ok) {
                setQueueError(res.error || 'Failed to queue saved jobs');
                return;
            }
            if (!res.queued) {
                setQueueError(`No ${readyBucketMeta(bucket).label.toLowerCase()} jobs were available to queue`);
            }
            await loadReadyJobs();
            setSelectedIds(new Set());
            onRunStarted();
        } catch {
            setQueueError('Failed to queue saved jobs');
        } finally {
            setQueueBusy(false);
        }
    };

    const toggleFocusedJob = (id: number) => {
        setFocusedJobId(prev => prev === id ? 0 : id);
    };

    const sourceOptions: SourceFilter[] = Array.from(new Set(readyJobs.map(job => normalizeSource(job.source))));
    if (sourceFilter && !sourceOptions.includes(sourceFilter)) sourceOptions.push(sourceFilter);
    sourceOptions.sort((a, b) => a.localeCompare(b));

    const seniorityOptions = Array.from(new Set(readyJobs.map(job => (job.seniority || '').trim()).filter(Boolean)));
    if (seniorityFilter && !seniorityOptions.includes(seniorityFilter)) seniorityOptions.push(seniorityFilter);
    seniorityOptions.sort((a, b) => a.localeCompare(b));

    const toggleBoardFilter = (board: string) => {
        setBoardFilter((prev) => (
            prev.includes(board) ? prev.filter((item) => item !== board) : [...prev, board]
        ));
    };

    const parsedQueueBatchSize = Number.parseInt(queueBatchSize, 10);

    const toggleSort = (key: ReadySortKey) => {
        if (sortKey === key) {
            setSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
            return;
        }
        setSortKey(key);
        setSortDir(key === 'date_added' ? 'desc' : 'asc');
    };

    const untailoredCount = readyJobs.reduce(
        (acc, job) => acc + (Number(job.tailoring_run_count || 0) === 0 ? 1 : 0),
        0,
    );
    const visibleReadyJobs = untailoredOnly
        ? readyJobs.filter((job) => Number(job.tailoring_run_count || 0) === 0)
        : readyJobs;

    const sortedReadyJobs = [...visibleReadyJobs].sort((a, b) => {
        let result = 0;
        if (sortKey === 'job') {
            result = compareText(a.title, b.title) || (Number(a.id) - Number(b.id));
        } else if (sortKey === 'company') {
            result = compareText(a.company || extractCompany(a.url), b.company || extractCompany(b.url))
                || compareText(a.board, b.board)
                || compareText(normalizeSource(a.source), normalizeSource(b.source));
        } else if (sortKey === 'context') {
            const aContext = [a.location, a.seniority, a.salary_k ? String(a.salary_k) : ''].filter(Boolean).join(' ');
            const bContext = [b.location, b.seniority, b.salary_k ? String(b.salary_k) : ''].filter(Boolean).join(' ');
            result = compareText(aContext, bContext);
        } else if (sortKey === 'date_added') {
            result = new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
        } else if (sortKey === 'history') {
            const aApplied = a.applied ? 1 : 0;
            const bApplied = b.applied ? 1 : 0;
            const aRuns = Number(a.tailoring_run_count || 0);
            const bRuns = Number(b.tailoring_run_count || 0);
            result = (aApplied - bApplied) || (aRuns - bRuns);
        }
        return sortDir === 'asc' ? result : -result;
    });
    const selectableSortedReadyJobs = sortedReadyJobs.filter((job) => job.queue_item?.status !== 'queued' && job.queue_item?.status !== 'running');
    const queueFirstCount = Number.isFinite(parsedQueueBatchSize) ? Math.max(0, parsedQueueBatchSize) : 0;
    const queueFirstIds = selectableSortedReadyJobs.slice(0, queueFirstCount).map((job) => job.id);

    const SortHeader = ({ label, sort }: { label: string; sort: ReadySortKey }) => {
        const active = sortKey === sort;
        return (
            <button
                type="button"
                onClick={() => toggleSort(sort)}
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    border: 'none',
                    background: 'transparent',
                    padding: 0,
                    cursor: 'pointer',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '.64rem',
                    color: active ? 'var(--text)' : 'var(--text-secondary)',
                    textTransform: 'uppercase',
                    letterSpacing: '.08em',
                    fontWeight: active ? 700 : 500,
                }}
            >
                <span>{label}</span>
                <span style={{ opacity: active ? 1 : 0.45 }}>
                    {active ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                </span>
            </button>
        );
    };

    return (
        <div style={{ height: '100%', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em' }}>
                        Ready Backlog ({readyTotal})
                    </span>
                    {readyJobs.length > 0 && (
                        <button
                            className="btn btn-ghost btn-sm"
                            disabled={resetBusy}
                            onClick={async () => {
                                if (!confirm('Reset all approved jobs back to QA triage?')) return;
                                setResetBusy(true);
                                try {
                                    await api.resetApprovedQA();
                                    await loadReadyJobs();
                                    setSelectedIds(new Set());
                                    setFocusedJobId(0);
                                } catch { }
                                finally { setResetBusy(false); }
                            }}
                            style={{ fontSize: '.64rem', color: 'var(--text-secondary)' }}
                        >
                            {resetBusy ? 'Resetting...' : 'Reset to QA'}
                        </button>
                    )}
                </div>

                {/* Queue controls */}
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <button
                            className={`btn btn-sm${bucketFilter === 'all' ? ' btn-primary' : ' btn-ghost'}`}
                            onClick={() => setBucketFilter('all')}
                            style={{ fontSize: '.68rem' }}
                        >
                            All ({bucketCounts.backlog + bucketCounts.next + bucketCounts.later})
                        </button>
                        {READY_BUCKETS.map((bucket) => {
                            const meta = readyBucketMeta(bucket);
                            const active = bucketFilter === bucket;
                            return (
                                <button
                                    key={bucket}
                                    className={`btn btn-sm${active ? ' btn-primary' : ' btn-ghost'}`}
                                    onClick={() => setBucketFilter(bucket)}
                                    style={{
                                        fontSize: '.68rem',
                                        color: active ? undefined : meta.color,
                                        borderColor: active ? undefined : meta.border,
                                        background: active ? undefined : meta.background,
                                    }}
                                >
                                    {meta.label} ({bucketCounts[bucket] || 0})
                                </button>
                            );
                        })}
                        <div style={{ width: '1px', height: '18px', background: 'var(--border-bright)' }} />
                        <button
                            className={`btn btn-sm${untailoredOnly ? ' btn-primary' : ' btn-ghost'}`}
                            onClick={() => setUntailoredOnly(prev => !prev)}
                            style={{ fontSize: '.68rem' }}
                        >
                            Untailored ({untailoredCount})
                        </button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, .9fr) minmax(0, .9fr) minmax(0, 1fr) auto', gap: '8px', alignItems: 'center' }}>
                        <input
                            type="text"
                            value={searchFilter}
                            onChange={e => setSearchFilter(e.target.value)}
                            placeholder="Search title, company, URL..."
                            style={{
                                minWidth: 0,
                                padding: '8px 10px',
                                borderRadius: '8px',
                                border: '1px solid var(--border)',
                                background: 'var(--bg)',
                                color: 'var(--text)',
                                fontSize: '.78rem',
                            }}
                        />
                        <select value={sourceFilter} onChange={e => setSourceFilter((e.target.value || '') as '' | SourceFilter)} style={{ minWidth: 0 }}>
                            <option value="">All Sources</option>
                            {sourceOptions.map(source => <option key={source} value={source}>{sourceMeta(source).label}</option>)}
                        </select>
                        <select value={seniorityFilter} onChange={e => setSeniorityFilter(e.target.value)} style={{ minWidth: 0 }}>
                            <option value="">All Seniority</option>
                            {seniorityOptions.map(seniority => <option key={seniority} value={seniority}>{seniority}</option>)}
                        </select>
                        <input
                            type="text"
                            value={locationFilter}
                            onChange={e => setLocationFilter(e.target.value)}
                            placeholder="Location contains..."
                            style={{
                                minWidth: 0,
                                padding: '8px 10px',
                                borderRadius: '8px',
                                border: '1px solid var(--border)',
                                background: 'var(--bg)',
                                color: 'var(--text)',
                                fontSize: '.78rem',
                            }}
                        />
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => {
                                setSearchFilter('');
                                setBoardFilter([]);
                                setSourceFilter('');
                                setSeniorityFilter('');
                                setLocationFilter('');
                                setBucketFilter('all');
                                setUntailoredOnly(false);
                            }}
                            disabled={!searchFilter && boardFilter.length === 0 && !sourceFilter && !seniorityFilter && !locationFilter && bucketFilter === 'all' && !untailoredOnly}
                            style={{ fontSize: '.68rem', whiteSpace: 'nowrap' }}
                        >
                            Clear filters
                        </button>
                    </div>
                    {boardOptions.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>
                                Boards
                            </span>
                            {boardOptions.map((board) => {
                                const active = boardFilter.includes(board);
                                return (
                                    <label
                                        key={board}
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '6px',
                                            padding: '4px 8px',
                                            borderRadius: '999px',
                                            border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                                            background: active ? 'var(--accent-light)' : 'var(--surface-2)',
                                            color: active ? 'var(--accent)' : 'var(--text-secondary)',
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.64rem',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={active}
                                            onChange={() => toggleBoardFilter(board)}
                                            style={{ accentColor: 'var(--accent)' }}
                                        />
                                        <span>{board}</span>
                                    </label>
                                );
                            })}
                        </div>
                    )}
                    {(searchFilter || boardFilter.length > 0 || sourceFilter || seniorityFilter || locationFilter || bucketFilter !== 'all' || untailoredOnly) && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                            <span>{untailoredOnly ? `${visibleReadyJobs.length} untailored` : `${readyTotal} matching`} jobs</span>
                            {boardFilter.length > 0 ? <span>boards: {boardFilter.join(', ')}</span> : null}
                            {sourceFilter ? <span>source: {sourceMeta(sourceFilter).label}</span> : null}
                            {seniorityFilter ? <span>seniority: {seniorityFilter}</span> : null}
                            {locationFilter ? <span>location: "{locationFilter}"</span> : null}
                            {bucketFilter !== 'all' ? <span>review bucket: {readyBucketMeta(bucketFilter).label}</span> : null}
                            {searchFilter ? <span>search: "{searchFilter}"</span> : null}
                            {untailoredOnly ? <span>untailored only</span> : null}
                        </div>
                    )}
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={queueBusy || selectedIds.size === 0}
                            onClick={queueSelected}
                            style={{ flex: 1 }}
                        >
                            {queueBusy ? 'Queuing...' : `Queue Selected (${selectedIds.size})`}
                        </button>
                        <button
                            className="btn btn-ghost btn-sm"
                            disabled={queueBusy || bucketCounts.next === 0}
                            onClick={() => queueBucket('next')}
                            style={{ fontSize: '.68rem', whiteSpace: 'nowrap', color: readyBucketMeta('next').color }}
                        >
                            Queue Next ({bucketCounts.next})
                        </button>
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => {
                                const selectableIds = selectableSortedReadyJobs.map((job) => job.id);
                                if (selectedIds.size === selectableIds.length) setSelectedIds(new Set());
                                else setSelectedIds(new Set(selectableIds));
                            }}
                            disabled={readyJobs.length === 0}
                            style={{ fontSize: '.68rem', whiteSpace: 'nowrap' }}
                        >
                            {selectedIds.size > 0 && selectedIds.size === selectableSortedReadyJobs.length ? 'Deselect All' : 'Select Visible'}
                        </button>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                            <input type="checkbox" checked={skipAnalysis}
                                onChange={e => setSkipAnalysis(e.target.checked)}
                                style={{ accentColor: 'var(--accent)' }} />
                            Skip analysis
                        </label>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', whiteSpace: 'nowrap' }}>
                            Queue top
                        </span>
                        <div style={{ display: 'inline-flex', alignItems: 'center', border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--surface-2)' }}>
                            {READY_QUEUE_PRESETS.map((size, idx) => {
                                const active = queueBatchSize === String(size);
                                const available = Math.min(size, selectableSortedReadyJobs.length);
                                return (
                                    <button
                                        key={size}
                                        type="button"
                                        disabled={selectableSortedReadyJobs.length === 0}
                                        onClick={() => setQueueBatchSize(String(size))}
                                        style={{
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.7rem',
                                            fontWeight: active ? 700 : 500,
                                            padding: '6px 12px',
                                            background: active ? 'var(--accent-light)' : 'transparent',
                                            color: active ? 'var(--accent)' : 'var(--text-secondary)',
                                            border: 'none',
                                            borderLeft: idx === 0 ? 'none' : '1px solid var(--border)',
                                            cursor: selectableSortedReadyJobs.length === 0 ? 'not-allowed' : 'pointer',
                                            whiteSpace: 'nowrap',
                                        }}
                                        title={available !== size ? `Only ${available} available` : undefined}
                                    >
                                        {size}
                                    </button>
                                );
                            })}
                            <div style={{ width: '1px', alignSelf: 'stretch', background: 'var(--border)' }} />
                            <input
                                type="number"
                                min={1}
                                step={1}
                                inputMode="numeric"
                                value={queueBatchSize}
                                onChange={(e) => setQueueBatchSize(e.target.value)}
                                aria-label="Custom top-N value"
                                style={{
                                    width: '56px',
                                    padding: '6px 8px',
                                    border: 'none',
                                    background: 'transparent',
                                    color: 'var(--text)',
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '.7rem',
                                    textAlign: 'center',
                                }}
                            />
                        </div>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={queueBusy || queueFirstIds.length === 0}
                            onClick={() => queueJobIds(queueFirstIds)}
                            style={{ fontSize: '.68rem', whiteSpace: 'nowrap' }}
                            title={queueFirstCount > selectableSortedReadyJobs.length ? `Only ${selectableSortedReadyJobs.length} available` : undefined}
                        >
                            {queueBusy ? 'Queuing…' : `Queue ${queueFirstIds.length}`}
                        </button>
                        <button
                            className="btn btn-ghost btn-sm"
                            disabled={queueBusy || queueFirstIds.length === 0}
                            onClick={() => setSelectedIds(new Set(queueFirstIds))}
                            style={{ fontSize: '.68rem', whiteSpace: 'nowrap' }}
                        >
                            Select {queueFirstIds.length}
                        </button>
                    </div>
                    {selectedIds.size > 0 && (
                        <div style={{
                            display: 'flex',
                            gap: '6px',
                            alignItems: 'center',
                            flexWrap: 'wrap',
                            padding: '8px 10px',
                            borderRadius: '8px',
                            background: 'rgba(75, 142, 240, 0.06)',
                            border: '1px solid rgba(75, 142, 240, 0.22)',
                        }}>
                            <span style={{
                                fontFamily: 'var(--font-mono)', fontSize: '.64rem', fontWeight: 700,
                                color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '.08em',
                                padding: '2px 8px', borderRadius: '999px',
                                background: 'rgba(75, 142, 240, 0.14)',
                                marginRight: '2px',
                            }}>
                                {selectedIds.size} selected
                            </span>
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={() => setSelectedIds(new Set())}
                                style={{ fontSize: '.68rem' }}
                                title="Clear selection"
                            >
                                Clear
                            </button>
                            <div style={{ width: '1px', alignSelf: 'stretch', background: 'var(--border)', margin: '0 4px' }} />
                            <button
                                className="btn btn-ghost btn-sm"
                                disabled={queueBusy}
                                onClick={() => updateSelectedBucket('next')}
                                style={{ fontSize: '.68rem', color: readyBucketMeta('next').color }}
                            >
                                → Queue Next
                            </button>
                            <button
                                className="btn btn-ghost btn-sm"
                                disabled={queueBusy}
                                onClick={() => updateSelectedBucket('later')}
                                style={{ fontSize: '.68rem', color: readyBucketMeta('later').color }}
                            >
                                → Later
                            </button>
                            <button
                                className="btn btn-ghost btn-sm"
                                disabled={queueBusy}
                                onClick={() => updateSelectedBucket('backlog')}
                                style={{ fontSize: '.68rem' }}
                            >
                                → Backlog
                            </button>
                            <div style={{ width: '1px', alignSelf: 'stretch', background: 'var(--border)', margin: '0 4px' }} />
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={async () => {
                                    if (!confirm(`Return ${selectedIds.size} job(s) to QA? Output files are preserved.`)) return;
                                    setQueueError('');
                                    try {
                                        await api.rollbackToQA(Array.from(selectedIds));
                                        await loadReadyJobs();
                                        setSelectedIds(new Set());
                                        setFocusedJobId(0);
                                    } catch (err) {
                                        setQueueError(apiErrorMessage(err, 'Failed to return jobs to QA'));
                                    }
                                }}
                                style={{ fontSize: '.68rem', color: 'var(--amber, #d1a23b)' }}
                                title="Return to QA triage (output files preserved)"
                            >
                                Back to QA
                            </button>
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={async () => {
                                    if (!confirm(`Reject ${selectedIds.size} job(s)? They will be permanently removed from the ready backlog.`)) return;
                                    setQueueError('');
                                    try {
                                        await api.rejectQA(Array.from(selectedIds));
                                        await loadReadyJobs();
                                        setSelectedIds(new Set());
                                        setFocusedJobId(0);
                                    } catch (err) {
                                        setQueueError(apiErrorMessage(err, 'Failed to reject jobs'));
                                    }
                                }}
                                style={{ fontSize: '.68rem', color: 'var(--red)' }}
                                title="Reject from the ready backlog"
                            >
                                Reject
                            </button>
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={async () => {
                                    if (!confirm(`Permanently reject ${selectedIds.size} job(s)? These URLs will never re-enter the pipeline.`)) return;
                                    setQueueError('');
                                    try {
                                        await api.permanentlyRejectQA(Array.from(selectedIds));
                                        await loadReadyJobs();
                                        setSelectedIds(new Set());
                                        setFocusedJobId(0);
                                    } catch (err) {
                                        setQueueError(apiErrorMessage(err, 'Failed to permanently reject jobs'));
                                    }
                                }}
                                style={{ fontSize: '.68rem', color: 'rgba(200, 40, 40, 0.9)' }}
                                title="Permanently reject (URL never re-enters pipeline)"
                            >
                                Dead
                            </button>
                        </div>
                    )}
                    {queueError && <div style={{ fontSize: '.72rem', color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>{queueError}</div>}
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {readyJobs.length === 0 ? (
                        <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.78rem' }}>
                            No QA-approved jobs are ready for tailoring
                        </div>
                    ) : (
                        <div>
                            <div
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: '44px minmax(300px, 2fr) minmax(210px, 1.1fr) minmax(180px, 1fr) 110px 42px',
                                    gap: '12px',
                                    alignItems: 'center',
                                    padding: '10px 14px',
                                    borderBottom: '1px solid var(--border)',
                                    background: 'var(--surface-2)',
                                    position: 'sticky',
                                    top: 0,
                                    zIndex: 1,
                                }}
                            >
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Pick</span>
                                <SortHeader label="Job" sort="job" />
                                <SortHeader label="Company + Source" sort="company" />
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <SortHeader label="Meta" sort="context" />
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.56rem', color: 'var(--text-secondary)', opacity: 0.6 }}>·</span>
                                    <SortHeader label="Runs" sort="history" />
                                </div>
                                <SortHeader label="Added" sort="date_added" />
                                <span />
                            </div>
                            {sortedReadyJobs.map((j) => {
                        const isFocused = focusedJobId === j.id;
                        const isChecked = selectedIds.has(j.id);
                        const queueState = j.queue_item?.status;
                        const isUnavailable = queueState === 'queued' || queueState === 'running';
                        const priorRunCount = Number(j.tailoring_run_count || 0);
                        const hasPriorRun = Boolean(j.has_tailoring_runs || priorRunCount > 0);
                        const applied = j.applied;
                        const source = sourceMeta(normalizeSource(j.source));
                        const reviewBucket = normalizeReadyBucket(j.ready_bucket);
                        const reviewMeta = readyBucketMeta(reviewBucket);
                        const company = j.company?.trim() || extractCompany(j.url) || '';
                        const host = compactHost(j.url);
                        const logistics = [j.location, j.seniority, j.salary_k ? `$${Math.round(j.salary_k / 1000)}K` : ''].filter(Boolean);
                        return (
                            <div key={j.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                <div
                                    style={{
                                        display: 'grid',
                                        gridTemplateColumns: '44px minmax(300px, 2fr) minmax(210px, 1.1fr) minmax(180px, 1fr) 110px 42px',
                                        gap: '12px',
                                        alignItems: 'start',
                                        padding: '12px 14px',
                                        cursor: 'pointer',
                                        borderLeft: isFocused ? '2px solid var(--accent)' : '2px solid transparent',
                                        background: isFocused ? 'var(--accent-light)' : isChecked ? 'rgba(var(--accent-rgb, 100,150,255), 0.06)' : 'transparent',
                                        transition: 'background .08s',
                                    }}
                                    onClick={() => toggleFocusedJob(j.id)}
                                    onMouseEnter={e => { if (!isFocused && !isChecked) e.currentTarget.style.background = 'var(--surface-2)'; }}
                                    onMouseLeave={e => { if (!isFocused && !isChecked) e.currentTarget.style.background = 'transparent'; }}
                                >
                                    {/* ── Col 1: Pick ── */}
                                    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: '4px' }}>
                                        <input
                                            type="checkbox"
                                            checked={isChecked}
                                            disabled={isUnavailable}
                                            onChange={() => toggleSelection(j.id)}
                                            onClick={e => e.stopPropagation()}
                                            style={{ accentColor: 'var(--accent)' }}
                                        />
                                    </div>

                                    {/* ── Col 2: Job ── */}
                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', flexShrink: 0 }}>#{j.id}</span>
                                            <span style={{ fontWeight: 600, fontSize: '.88rem', lineHeight: 1.35, color: 'var(--text)' }}>
                                                {j.title || 'Untitled'}
                                            </span>
                                            <span style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                borderRadius: '999px',
                                                border: `1px solid ${reviewMeta.border}`,
                                                background: reviewMeta.background,
                                                color: reviewMeta.color,
                                                padding: '1px 8px',
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.6rem',
                                                fontWeight: 700,
                                                letterSpacing: '.03em',
                                                flexShrink: 0,
                                            }}>
                                                {reviewMeta.label}
                                            </span>
                                        </div>
                                        {j.snippet && (
                                            <div
                                                style={{
                                                    fontSize: '.76rem',
                                                    color: 'var(--text-secondary)',
                                                    lineHeight: 1.5,
                                                    display: '-webkit-box',
                                                    WebkitLineClamp: 2,
                                                    WebkitBoxOrient: 'vertical',
                                                    overflow: 'hidden',
                                                    marginBottom: '6px',
                                                }}
                                            >
                                                {j.snippet}
                                            </div>
                                        )}
                                        {host && (
                                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                                                {host}
                                            </div>
                                        )}
                                    </div>

                                    {/* ── Col 3: Company + Source ── */}
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
                                            {j.board ? <span className={`pill pill-${j.board}`} style={{ fontSize: '.66rem' }}>{j.board}</span> : null}
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
                                            {queueState ? (
                                                <span style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    borderRadius: '999px',
                                                    border: `1px solid ${queueState === 'running' ? 'rgba(75, 142, 240, 0.35)' : 'rgba(60, 179, 113, 0.32)'}`,
                                                    background: queueState === 'running' ? 'rgba(75, 142, 240, 0.10)' : 'rgba(60, 179, 113, 0.10)',
                                                    color: queueState === 'running' ? 'var(--accent)' : 'var(--green)',
                                                    padding: '1px 8px',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '.62rem',
                                                    fontWeight: 700,
                                                }}>
                                                    {queueState}
                                                </span>
                                            ) : null}
                                        </div>
                                        <div
                                            style={{
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.66rem',
                                                color: 'var(--text-secondary)',
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap',
                                            }}
                                            title={j.url || undefined}
                                        >
                                            {j.url || 'No source URL'}
                                        </div>
                                    </div>

                                    {/* ── Col 4: Meta (context + history merged) ── */}
                                    <div style={{ minWidth: 0, display: 'flex', flexWrap: 'wrap', gap: '6px', alignContent: 'flex-start' }}>
                                        {logistics.map(item => (
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
                                        {hasPriorRun && (
                                            <span style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                borderRadius: '999px',
                                                border: '1px solid rgba(224, 160, 48, 0.45)',
                                                background: 'rgba(224, 160, 48, 0.10)',
                                                color: 'var(--amber, #e0a030)',
                                                padding: '1px 8px',
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.62rem',
                                                fontWeight: 700,
                                            }}>
                                                {priorRunCount} pkg
                                            </span>
                                        )}
                                        {applied && (
                                            <span style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                borderRadius: '999px',
                                                border: '1px solid rgba(75, 142, 240, 0.35)',
                                                background: 'rgba(75, 142, 240, 0.10)',
                                                color: 'var(--accent)',
                                                padding: '1px 8px',
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '.62rem',
                                                fontWeight: 700,
                                            }}>
                                                Applied
                                            </span>
                                        )}
                                        {logistics.length === 0 && !hasPriorRun && !applied && (
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)', opacity: 0.7 }}>
                                                —
                                            </span>
                                        )}
                                    </div>

                                    {/* ── Col 5: Added ── */}
                                    <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text)', fontWeight: 600 }}>
                                            {j.created_at ? timeAgo(j.created_at) : '—'}
                                        </span>
                                        {j.created_at && (
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', color: 'var(--text-secondary)' }}>
                                                {fmtDate(j.created_at)}
                                            </span>
                                        )}
                                    </div>

                                    {/* ── Col 6: Actions ── */}
                                    <div style={{
                                        display: 'flex', flexDirection: 'column',
                                        alignItems: 'center', gap: '6px',
                                        paddingTop: '2px',
                                    }}>
                                        {j.url && (
                                            <a
                                                href={j.url}
                                                target="_blank"
                                                rel="noreferrer"
                                                onClick={e => e.stopPropagation()}
                                                title="Open job description in new tab"
                                                style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    width: '26px',
                                                    height: '26px',
                                                    borderRadius: '6px',
                                                    border: '1px solid rgba(75, 142, 240, 0.35)',
                                                    background: 'rgba(75, 142, 240, 0.10)',
                                                    color: 'var(--accent)',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '.72rem',
                                                    fontWeight: 700,
                                                    textDecoration: 'none',
                                                    lineHeight: 1,
                                                }}
                                                aria-label="Open JD in new tab"
                                            >
                                                ↗
                                            </a>
                                        )}
                                        <span style={{
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.82rem',
                                            color: isFocused ? 'var(--accent)' : 'var(--text-secondary)',
                                            transform: isFocused ? 'rotate(180deg)' : 'rotate(0deg)',
                                            transition: 'transform .15s ease',
                                            lineHeight: 1,
                                        }}>
                                            ▾
                                        </span>
                                    </div>
                                </div>

                                {isFocused && (
                                    <div style={{ background: 'rgba(75, 142, 240, 0.05)', borderTop: '1px solid var(--border)' }}>
                                        {detailLoading ? (
                                            <div className="loading" style={{ minHeight: '220px' }}><div className="spinner" /></div>
                                        ) : !briefing ? (
                                            <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem', textAlign: 'center', padding: '32px' }}>
                                                Job not found
                                            </div>
                                        ) : (
                                            <BriefingPanel briefing={briefing} compact />
                                        )}
                                    </div>
                                )}
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


/* ─── Briefing Panel ─── */

function BriefingPanel({ briefing, compact = false }: { briefing: Briefing; compact?: boolean }) {
    const { job, analysis, resume_strategy, cover_strategy, run_slug } = briefing;
    const hasRun = Boolean(analysis || resume_strategy || cover_strategy);

    const company = analysis?.company_name || extractCompany(job.url) || '';
    const role = analysis?.role_title || job.title || 'Untitled';

    return (
        <div style={{ padding: compact ? '18px 22px 26px' : '24px 32px 40px', maxWidth: compact ? 'none' : '920px' }}>
            {/* ── Header ── */}
            <div style={{ marginBottom: '28px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                    <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                        color: 'var(--accent)', background: 'var(--accent-light)',
                        border: '1px solid var(--accent-dim)',
                        borderRadius: '2px', padding: '2px 8px',
                        textTransform: 'uppercase', letterSpacing: '.1em',
                    }}>
                        Job #{job.id}
                    </span>
                    {company && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                            color: 'var(--cyan)', background: 'rgba(42, 184, 204, 0.08)',
                            border: '1px solid rgba(42, 184, 204, 0.25)',
                            borderRadius: '2px', padding: '2px 8px',
                            textTransform: 'uppercase', letterSpacing: '.08em',
                        }}>
                            {company}
                        </span>
                    )}
                    {hasRun && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 600,
                            color: 'var(--green)', background: 'rgba(60, 179, 113, 0.08)',
                            border: '1px solid rgba(60, 179, 113, 0.25)',
                            borderRadius: '2px', padding: '2px 8px',
                            textTransform: 'uppercase', letterSpacing: '.1em',
                        }}>
                            Pipeline data available
                        </span>
                    )}
                </div>
                <h2 style={{ fontSize: '1.2rem', fontWeight: 600, lineHeight: 1.3, marginBottom: '8px', color: 'var(--text)' }}>
                    {role}
                </h2>
                {job.url && (
                    <a href={job.url} target="_blank" rel="noreferrer" style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--accent)',
                        textDecoration: 'none', wordBreak: 'break-all',
                    }}>
                        {job.url}
                    </a>
                )}
            </div>

            {/* ── Requirements Summary ── */}
            {job.snippet && (
                <Section title="Requirements Summary" accent="var(--accent)">
                    <p style={{ fontSize: '.86rem', lineHeight: 1.65, color: 'var(--text)' }}>
                        {job.snippet}
                    </p>
                </Section>
            )}

            {/* ── Company Context (from analysis) ── */}
            {analysis?.company_context && (
                <Section title="Company Context" accent="var(--cyan)">
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 20px' }}>
                        <ContextField label="What They Build" value={analysis.company_context.what_they_build} />
                        <ContextField label="Engineering Challenges" value={analysis.company_context.engineering_challenges} />
                        <ContextField label="Company Type" value={analysis.company_context.company_type} pill />
                        <ContextField label="Cover Letter Hook" value={analysis.company_context.cover_letter_hook} />
                    </div>
                </Section>
            )}

            {/* ── JD Requirements Mapping ── */}
            {analysis?.requirements && analysis.requirements.length > 0 && (
                <Section title="Requirements Mapping" accent="var(--purple)">
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                        {analysis.requirements.map((req: any, i: number) => (
                            <RequirementRow key={i} req={req} />
                        ))}
                    </div>
                </Section>
            )}

            {/* ── Summary Angle + Tone ── */}
            {analysis && (analysis.summary_angle || analysis.tone_notes) && (
                <Section title="Positioning" accent="var(--teal)">
                    {analysis.summary_angle && (
                        <div style={{ marginBottom: '10px' }}>
                            <FieldLabel>Summary Angle</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)', fontStyle: 'italic' }}>
                                {analysis.summary_angle}
                            </p>
                        </div>
                    )}
                    {analysis.tone_notes && (
                        <div>
                            <FieldLabel>Tone Notes</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)' }}>
                                {analysis.tone_notes}
                            </p>
                        </div>
                    )}
                </Section>
            )}

            {/* ── Resume Strategy ── */}
            {resume_strategy && (
                <Section title="Resume Strategy" accent="var(--orange)">
                    {resume_strategy.summary_strategy && (
                        <div style={{ marginBottom: '16px' }}>
                            <FieldLabel>Summary Direction</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)' }}>
                                {resume_strategy.summary_strategy}
                            </p>
                        </div>
                    )}
                    {resume_strategy.skills_tailoring && (
                        <div style={{ marginBottom: '16px' }}>
                            <FieldLabel>Skills Reordering</FieldLabel>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                                {Object.entries(resume_strategy.skills_tailoring).map(([cat, guidance]) => (
                                    <div key={cat} style={{
                                        display: 'flex', gap: '10px', padding: '6px 10px',
                                        background: 'var(--surface)', borderRadius: '3px', border: '1px solid var(--border)',
                                    }}>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600, color: 'var(--orange)', minWidth: '160px', flexShrink: 0 }}>
                                            {cat}
                                        </span>
                                        <span style={{ fontSize: '.78rem', color: 'var(--text)', lineHeight: 1.5 }}>
                                            {String(guidance)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {resume_strategy.experience_rewrites && resume_strategy.experience_rewrites.length > 0 && (
                        <div style={{ marginBottom: '16px' }}>
                            <FieldLabel>Experience Rewrites</FieldLabel>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '8px' }}>
                                {resume_strategy.experience_rewrites.map((entry: any, i: number) => (
                                    <ExperienceRewriteCard key={i} entry={entry} />
                                ))}
                            </div>
                        </div>
                    )}
                    {resume_strategy.risk_controls && resume_strategy.risk_controls.length > 0 && (
                        <div>
                            <FieldLabel>Risk Controls</FieldLabel>
                            <ul style={{ margin: '6px 0 0 16px', fontSize: '.78rem', color: 'var(--text)', lineHeight: 1.7 }}>
                                {resume_strategy.risk_controls.map((r: string, i: number) => (
                                    <li key={i}>{r}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                </Section>
            )}

            {/* ── Cover Strategy ── */}
            {cover_strategy && (
                <Section title="Cover Letter Strategy" accent="var(--green)">
                    {cover_strategy.company_hook && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Company Hook</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)', fontStyle: 'italic' }}>
                                {cover_strategy.company_hook}
                            </p>
                        </div>
                    )}
                    {cover_strategy.structure && cover_strategy.structure.length > 0 && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Paragraph Structure</FieldLabel>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                                {cover_strategy.structure.map((para: any, i: number) => (
                                    <div key={i} style={{
                                        padding: '8px 12px', background: 'var(--surface)', borderRadius: '3px',
                                        border: '1px solid var(--border)', borderLeft: '3px solid var(--green)',
                                    }}>
                                        <div style={{ fontWeight: 600, fontSize: '.8rem', marginBottom: '4px', color: 'var(--text)' }}>
                                            {para.focus || para.theme || `Paragraph ${i + 1}`}
                                        </div>
                                        {para.theme && para.theme !== para.focus && (
                                            <div style={{ fontSize: '.74rem', color: 'var(--text-secondary)', marginBottom: '3px' }}>
                                                Theme: {para.theme}
                                            </div>
                                        )}
                                        {para.experience_sources && (
                                            <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                                                Sources: {Array.isArray(para.experience_sources) ? para.experience_sources.join(', ') : String(para.experience_sources)}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {cover_strategy.closing_angle && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Closing Angle</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)' }}>
                                {cover_strategy.closing_angle}
                            </p>
                        </div>
                    )}
                    {cover_strategy.voice_controls && cover_strategy.voice_controls.length > 0 && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Voice Controls</FieldLabel>
                            <ul style={{ margin: '6px 0 0 16px', fontSize: '.78rem', color: 'var(--text)', lineHeight: 1.7 }}>
                                {cover_strategy.voice_controls.map((v: string, i: number) => (
                                    <li key={i}>{v}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {cover_strategy.vignettes_to_use && cover_strategy.vignettes_to_use.length > 0 && (
                        <div>
                            <FieldLabel>Vignettes</FieldLabel>
                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '6px' }}>
                                {cover_strategy.vignettes_to_use.map((v: string, i: number) => (
                                    <span key={i} style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 500,
                                        padding: '2px 8px', borderRadius: '2px',
                                        background: 'rgba(60, 179, 113, 0.08)', border: '1px solid rgba(60, 179, 113, 0.2)',
                                        color: 'var(--green)',
                                    }}>
                                        {v}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </Section>
            )}

            {/* ── Raw JD Text (collapsible) ── */}
            {job.jd_text && (
                <CollapsibleSection title="Full JD Text" defaultOpen={!hasRun}>
                    <pre style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.74rem', lineHeight: 1.6,
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text)',
                        margin: 0, maxHeight: '500px', overflow: 'auto',
                        padding: '12px', background: 'var(--surface)', borderRadius: '3px',
                        border: '1px solid var(--border)',
                    }}>
                        {job.jd_text}
                    </pre>
                </CollapsibleSection>
            )}

            {/* ── Run metadata ── */}
            {run_slug && (
                <div style={{
                    marginTop: '24px', padding: '8px 12px',
                    background: 'var(--surface)', borderRadius: '3px', border: '1px solid var(--border)',
                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)',
                    display: 'flex', gap: '16px',
                }}>
                    <span>Run: {run_slug}</span>
                    {job.created_at && <span>Created: {new Date(job.created_at).toLocaleDateString()}</span>}
                </div>
            )}
        </div>
    );
}


/* ─── Sub-components ─── */

function Section({ title, accent, children }: { title: string; accent: string; children: React.ReactNode }) {
    return (
        <div style={{ marginBottom: '24px' }}>
            <div style={{
                display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px',
                paddingBottom: '6px', borderBottom: `1px solid var(--border)`,
            }}>
                <div style={{ width: '3px', height: '14px', borderRadius: '1px', background: accent, flexShrink: 0 }} />
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
                    color: accent, textTransform: 'uppercase', letterSpacing: '.08em',
                }}>
                    {title}
                </span>
            </div>
            {children}
        </div>
    );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
    return (
        <div style={{
            fontFamily: 'var(--font-mono)', fontSize: '.64rem', fontWeight: 600,
            color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
            marginBottom: '4px',
        }}>
            {children}
        </div>
    );
}

function ContextField({ label, value, pill }: { label: string; value?: string; pill?: boolean }) {
    if (!value) return null;
    return (
        <div>
            <FieldLabel>{label}</FieldLabel>
            {pill ? (
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.72rem', fontWeight: 600,
                    padding: '2px 10px', borderRadius: '2px',
                    background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                    color: 'var(--cyan)', textTransform: 'lowercase',
                }}>
                    {value}
                </span>
            ) : (
                <p style={{ fontSize: '.82rem', lineHeight: 1.55, color: 'var(--text)', margin: 0 }}>{value}</p>
            )}
        </div>
    );
}

function coerceStringList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map((item) => String(item).trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
        return value
            .split(/,\s*/)
            .map((item) => item.trim())
            .filter(Boolean);
    }
    return [];
}

function RequirementRow({ req }: { req: any }) {
    const priorityColor = req.priority === 'high' ? 'var(--red)' : req.priority === 'medium' ? 'var(--amber)' : 'var(--text-secondary)';
    const matchedSkills = coerceStringList(req.matched_skills);
    return (
        <div style={{
            display: 'grid', gridTemplateColumns: '56px 1fr 1fr', gap: '10px',
            padding: '8px 10px', background: 'var(--surface)', borderRadius: '2px',
            border: '1px solid var(--border)', alignItems: 'start',
        }}>
            <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 700,
                textTransform: 'uppercase', color: priorityColor,
                paddingTop: '2px',
            }}>
                {req.priority || '—'}
            </span>
            <div>
                <div style={{ fontSize: '.8rem', fontWeight: 500, color: 'var(--text)', marginBottom: '3px', lineHeight: 1.4 }}>
                    {req.jd_requirement}
                </div>
                {matchedSkills.length > 0 && (
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
                        {matchedSkills.map((s: string, i: number) => (
                            <span key={i} style={{
                                fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 500,
                                padding: '1px 6px', borderRadius: '2px',
                                background: 'rgba(139, 124, 246, 0.08)', border: '1px solid rgba(139, 124, 246, 0.2)',
                                color: 'var(--purple)',
                            }}>
                                {s}
                            </span>
                        ))}
                    </div>
                )}
            </div>
            <div>
                {req.evidence && (
                    <div style={{
                        fontSize: '.74rem', lineHeight: 1.5, color: 'var(--text-secondary)',
                        fontStyle: 'italic', paddingLeft: '10px',
                        borderLeft: '2px solid var(--border-bright)',
                    }}>
                        {req.evidence}
                    </div>
                )}
            </div>
        </div>
    );
}

function ExperienceRewriteCard({ entry }: { entry: any }) {
    const bulletRewrites = Array.isArray(entry.bullet_rewrites) ? entry.bullet_rewrites :
        typeof entry.bullet_rewrites === 'string' ? (() => { try { return JSON.parse(entry.bullet_rewrites); } catch { return []; } })() : [];
    const preserves = Array.isArray(entry.bullets_to_preserve) ? entry.bullets_to_preserve :
        typeof entry.bullets_to_preserve === 'string' ? (() => { try { return JSON.parse(entry.bullets_to_preserve); } catch { return []; } })() : [];

    return (
        <div style={{
            padding: '10px 14px', background: 'var(--surface)', borderRadius: '3px',
            border: '1px solid var(--border)', borderLeft: '3px solid var(--orange)',
        }}>
            <div style={{ fontWeight: 600, fontSize: '.82rem', marginBottom: '8px', color: 'var(--text)' }}>
                {entry.company || 'Unknown Company'}
            </div>
            {bulletRewrites.length > 0 && (
                <div style={{ marginBottom: '8px' }}>
                    {bulletRewrites.map((rw: any, i: number) => (
                        <div key={i} style={{ marginBottom: '6px', paddingLeft: '10px', borderLeft: '2px solid var(--orange)', fontSize: '.76rem', lineHeight: 1.5 }}>
                            <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.66rem', marginBottom: '2px' }}>
                                {rw.baseline_topic}
                            </div>
                            <div style={{ color: 'var(--text)' }}>
                                {rw.rewrite_angle}
                            </div>
                            {rw.jd_requirement_addressed && (
                                <div style={{ color: 'var(--purple)', fontFamily: 'var(--font-mono)', fontSize: '.64rem', marginTop: '2px' }}>
                                    targets: {rw.jd_requirement_addressed}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
            {preserves.length > 0 && (
                <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                    Preserve: {preserves.join(' · ')}
                </div>
            )}
        </div>
    );
}


/* ─── Utility ─── */

function extractCompany(url?: string): string {
    if (!url) return '';
    try {
        const host = new URL(url).hostname.replace('www.', '').replace('jobs.', '').replace('careers.', '');
        const parts = host.split('.');
        if (parts.length >= 2) return parts[parts.length - 2];
    } catch { }
    return '';
}
