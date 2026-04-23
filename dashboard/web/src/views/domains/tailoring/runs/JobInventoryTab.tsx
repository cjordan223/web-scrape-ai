import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
    DollarSign, MapPin, Briefcase, ExternalLink, ChevronRight, ChevronDown,
    CheckCircle2, Clock, Package, X, SlidersHorizontal, Layers, Search,
} from 'lucide-react';
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
type PackageFilter = 'all' | 'created' | 'not_created';

const READY_BUCKETS: ReadyBucket[] = ['backlog', 'next', 'later'];
const READY_QUEUE_PRESETS = [10, 20, 50, 100];
const READY_GROUP_STORAGE_KEY = 'tailoring.ready.groupByCompany';

function companyKey(job: ReadyJob): string {
    const raw = (job.company || extractCompany(job.url) || '').trim().toLowerCase();
    return raw || '__unknown__';
}

function companyDisplay(job: ReadyJob): string {
    const raw = (job.company || extractCompany(job.url) || '').trim();
    return raw || 'Unknown company';
}

function getInitialGroupByCompany(): boolean {
    if (typeof window === 'undefined') return true;
    const v = window.localStorage.getItem(READY_GROUP_STORAGE_KEY);
    return v === null ? true : v === '1';
}

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
    const [packageFilter, setPackageFilter] = useState<PackageFilter>('all');
    const [searchFilter, setSearchFilter] = useState('');
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [focusedJobId, setFocusedJobId] = useState<number>(0);
    const [briefing, setBriefing] = useState<Briefing | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [skipAnalysis, setSkipAnalysis] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);
    const [queueError, setQueueError] = useState('');
    const [resetBusy, setResetBusy] = useState(false);
    const [sortKey, setSortKey] = useState<ReadySortKey>('company');
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
    const [queueBatchSize, setQueueBatchSize] = useState('20');
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [groupByCompany, setGroupByCompany] = useState<boolean>(getInitialGroupByCompany);
    const [collapsedCompanies, setCollapsedCompanies] = useState<Set<string>>(new Set());
    const didInitCollapseRef = useRef(false);
    const listRef = useRef<HTMLDivElement | null>(null);
    const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());

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
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(READY_GROUP_STORAGE_KEY, groupByCompany ? '1' : '0');
        }
    }, [groupByCompany]);

    useEffect(() => {
        if (didInitCollapseRef.current) return;
        if (!groupByCompany) return;
        if (readyJobs.length === 0) return;
        const keys = new Set<string>();
        for (const job of readyJobs) keys.add(companyKey(job));
        setCollapsedCompanies(keys);
        didInitCollapseRef.current = true;
    }, [groupByCompany, readyJobs]);

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

    const packageCreatedCount = readyJobs.reduce(
        (acc, job) => acc + (Number(job.tailoring_run_count || 0) > 0 ? 1 : 0),
        0,
    );
    const packageNotCreatedCount = Math.max(0, readyJobs.length - packageCreatedCount);
    const visibleReadyJobs = readyJobs.filter((job) => {
        const hasPackage = Number(job.tailoring_run_count || 0) > 0;
        if (packageFilter === 'created') return hasPackage;
        if (packageFilter === 'not_created') return !hasPackage;
        return true;
    });

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

    const companyGroups = useMemo(() => {
        const groups = new Map<string, { key: string; display: string; jobs: ReadyJob[] }>();
        for (const job of sortedReadyJobs) {
            const key = companyKey(job);
            let bucket = groups.get(key);
            if (!bucket) {
                bucket = { key, display: companyDisplay(job), jobs: [] };
                groups.set(key, bucket);
            }
            bucket.jobs.push(job);
        }
        return Array.from(groups.values());
    }, [sortedReadyJobs]);

    const displayedReadyJobs = useMemo(() => {
        if (!groupByCompany) return sortedReadyJobs;
        const out: ReadyJob[] = [];
        for (const group of companyGroups) {
            if (collapsedCompanies.has(group.key)) continue;
            out.push(...group.jobs);
        }
        return out;
    }, [groupByCompany, sortedReadyJobs, companyGroups, collapsedCompanies]);

    type ListEntry =
        | { kind: 'header'; group: { key: string; display: string; jobs: ReadyJob[] } }
        | { kind: 'job'; job: ReadyJob };

    const listEntries: ListEntry[] = useMemo(() => {
        if (!groupByCompany) {
            return sortedReadyJobs.map((job) => ({ kind: 'job' as const, job }));
        }
        const out: ListEntry[] = [];
        for (const group of companyGroups) {
            out.push({ kind: 'header', group });
            if (!collapsedCompanies.has(group.key)) {
                for (const job of group.jobs) out.push({ kind: 'job', job });
            }
        }
        return out;
    }, [groupByCompany, sortedReadyJobs, companyGroups, collapsedCompanies]);

    const toggleCompanyCollapsed = useCallback((key: string) => {
        setCollapsedCompanies((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    }, []);

    const focusedJob = sortedReadyJobs.find((j) => j.id === focusedJobId) || null;

    const moveFocus = useCallback((direction: 1 | -1) => {
        if (displayedReadyJobs.length === 0) return;
        const currentIdx = displayedReadyJobs.findIndex((j) => j.id === focusedJobId);
        let nextIdx: number;
        if (currentIdx < 0) {
            nextIdx = direction === 1 ? 0 : displayedReadyJobs.length - 1;
        } else {
            nextIdx = Math.max(0, Math.min(displayedReadyJobs.length - 1, currentIdx + direction));
        }
        const nextJob = displayedReadyJobs[nextIdx];
        if (!nextJob) return;
        setFocusedJobId(nextJob.id);
        const node = cardRefs.current.get(nextJob.id);
        if (node) node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }, [displayedReadyJobs, focusedJobId]);

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            const tgt = e.target as HTMLElement | null;
            const tag = tgt?.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tgt?.isContentEditable) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); moveFocus(1); return; }
            if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); moveFocus(-1); return; }
            if (e.key === ' ' && focusedJobId) { e.preventDefault(); toggleSelection(focusedJobId); return; }
            if (e.key === 'Escape') { setFocusedJobId(0); return; }
            if ((e.key === 'o' || e.key === 'O') && focusedJob?.url) {
                e.preventDefault();
                window.open(focusedJob.url, '_blank', 'noopener,noreferrer');
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [moveFocus, focusedJobId, focusedJob]);

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

                {/* Quick search — always visible */}
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <Search
                            size={14}
                            style={{
                                position: 'absolute',
                                left: 10,
                                color: 'var(--text-secondary)',
                                pointerEvents: 'none',
                            }}
                        />
                        <input
                            type="search"
                            value={searchFilter}
                            onChange={(e) => setSearchFilter(e.target.value)}
                            placeholder="Search company, title, URL..."
                            aria-label="Search ready jobs"
                            style={{
                                width: '100%',
                                padding: '8px 34px 8px 32px',
                                borderRadius: '8px',
                                border: `1px solid ${searchFilter ? 'var(--accent)' : 'var(--border)'}`,
                                background: 'var(--bg)',
                                color: 'var(--text)',
                                fontSize: '.78rem',
                                outline: 'none',
                            }}
                        />
                        {searchFilter && (
                            <button
                                type="button"
                                onClick={() => setSearchFilter('')}
                                aria-label="Clear search"
                                title="Clear search"
                                style={{
                                    position: 'absolute',
                                    right: 6,
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                    padding: 4,
                                    display: 'inline-flex',
                                }}
                            >
                                <X size={13} />
                            </button>
                        )}
                    </div>
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
                        {([
                            ['all', `Packages: All (${readyJobs.length})`],
                            ['created', `Package created (${packageCreatedCount})`],
                            ['not_created', `Package not created (${packageNotCreatedCount})`],
                        ] as const).map(([value, label]) => (
                            <button
                                key={value}
                                className={`btn btn-sm${packageFilter === value ? ' btn-primary' : ' btn-ghost'}`}
                                onClick={() => setPackageFilter(value)}
                                style={{ fontSize: '.68rem' }}
                            >
                                {label}
                            </button>
                        ))}
                        <span style={{ flex: 1 }} />
                        {(() => {
                            const activeFilterCount =
                                (searchFilter ? 1 : 0)
                                + (boardFilter.length > 0 ? 1 : 0)
                                + (sourceFilter ? 1 : 0)
                                + (seniorityFilter ? 1 : 0)
                                + (locationFilter ? 1 : 0)
                                + (packageFilter !== 'all' ? 1 : 0);
                            return (
                                <button
                                    className={`btn btn-sm${filtersOpen || activeFilterCount > 0 ? ' btn-primary' : ' btn-ghost'}`}
                                    onClick={() => setFiltersOpen(prev => !prev)}
                                    style={{ fontSize: '.68rem', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                                    title={filtersOpen ? 'Hide filters' : 'Show filters'}
                                >
                                    <SlidersHorizontal size={12} />
                                    Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
                                </button>
                            );
                        })()}
                        {(searchFilter || boardFilter.length > 0 || sourceFilter || seniorityFilter || locationFilter || packageFilter !== 'all') && (
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={() => {
                                    setSearchFilter('');
                                    setBoardFilter([]);
                                    setSourceFilter('');
                                    setSeniorityFilter('');
                                    setLocationFilter('');
                                    setPackageFilter('all');
                                }}
                                style={{ fontSize: '.68rem', display: 'inline-flex', alignItems: 'center', gap: '4px', color: 'var(--text-secondary)' }}
                                title="Clear all filter values"
                            >
                                <X size={11} /> Clear
                            </button>
                        )}
                    </div>
                    {filtersOpen && (<>
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, .9fr) minmax(0, .9fr) minmax(0, 1fr) auto', gap: '8px', alignItems: 'center' }}>
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
                                setPackageFilter('all');
                            }}
                            disabled={!searchFilter && boardFilter.length === 0 && !sourceFilter && !seniorityFilter && !locationFilter && bucketFilter === 'all' && packageFilter === 'all'}
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
                    {(searchFilter || boardFilter.length > 0 || sourceFilter || seniorityFilter || locationFilter || bucketFilter !== 'all' || packageFilter !== 'all') && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)' }}>
                            <span>{visibleReadyJobs.length} shown · {readyTotal} matching server filters</span>
                            {boardFilter.length > 0 ? <span>boards: {boardFilter.join(', ')}</span> : null}
                            {sourceFilter ? <span>source: {sourceMeta(sourceFilter).label}</span> : null}
                            {seniorityFilter ? <span>seniority: {seniorityFilter}</span> : null}
                            {locationFilter ? <span>location: "{locationFilter}"</span> : null}
                            {bucketFilter !== 'all' ? <span>review bucket: {readyBucketMeta(bucketFilter).label}</span> : null}
                            {searchFilter ? <span>search: "{searchFilter}"</span> : null}
                            {packageFilter !== 'all' ? <span>{packageFilter === 'created' ? 'package created' : 'package not created'}</span> : null}
                        </div>
                    )}
                    </>)}
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
                                const pool = groupByCompany ? displayedReadyJobs : sortedReadyJobs;
                                const selectableIds = pool
                                    .filter((job) => job.queue_item?.status !== 'queued' && job.queue_item?.status !== 'running')
                                    .map((job) => job.id);
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

                <div style={{ flex: 1, minHeight: 0, display: 'flex', overflow: 'hidden' }}>
                    {readyJobs.length === 0 ? (
                        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.82rem' }}>
                            No QA-approved jobs are ready for tailoring
                        </div>
                    ) : (
                        <>
                            {/* ═════ LEFT: Candidate cards ═════ */}
                            <div
                                ref={listRef}
                                style={{
                                    width: 'clamp(380px, 40%, 520px)',
                                    flexShrink: 0,
                                    borderRight: '1px solid var(--border)',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    minHeight: 0,
                                }}
                            >
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        gap: '8px',
                                        padding: '8px 12px',
                                        borderBottom: '1px solid var(--border)',
                                        background: 'var(--surface-2)',
                                        position: 'sticky',
                                        top: 0,
                                        zIndex: 2,
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--font-mono)', fontSize: '.62rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>
                                        <span>Sort</span>
                                        <select
                                            value={sortKey}
                                            onChange={(e) => setSortKey(e.target.value as ReadySortKey)}
                                            style={{ padding: '3px 6px', fontSize: '.7rem', background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '6px' }}
                                        >
                                            <option value="date_added">Date added</option>
                                            <option value="job">Title</option>
                                            <option value="company">Company</option>
                                            <option value="context">Location / Pay</option>
                                            <option value="history">Prior runs</option>
                                        </select>
                                        <button
                                            type="button"
                                            onClick={() => setSortDir(prev => prev === 'asc' ? 'desc' : 'asc')}
                                            title={sortDir === 'asc' ? 'Ascending' : 'Descending'}
                                            style={{ padding: '2px 8px', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '.72rem', fontFamily: 'var(--font-mono)' }}
                                        >
                                            {sortDir === 'asc' ? '▲' : '▼'}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setGroupByCompany(prev => !prev)}
                                            title={groupByCompany ? 'Ungroup company clusters' : 'Group jobs by company'}
                                            style={{
                                                display: 'inline-flex', alignItems: 'center', gap: '4px',
                                                padding: '2px 8px',
                                                border: `1px solid ${groupByCompany ? 'var(--accent)' : 'var(--border)'}`,
                                                borderRadius: '6px',
                                                background: groupByCompany ? 'var(--accent-light)' : 'var(--bg)',
                                                color: groupByCompany ? 'var(--accent)' : 'var(--text-secondary)',
                                                cursor: 'pointer', fontSize: '.7rem', fontFamily: 'var(--font-mono)',
                                                fontWeight: groupByCompany ? 700 : 500, letterSpacing: '.04em',
                                            }}
                                        >
                                            <Layers size={11} />
                                            Group
                                        </button>
                                        {groupByCompany && companyGroups.length > 0 && (
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    const allCollapsed = collapsedCompanies.size >= companyGroups.length;
                                                    if (allCollapsed) setCollapsedCompanies(new Set());
                                                    else setCollapsedCompanies(new Set(companyGroups.map((g) => g.key)));
                                                }}
                                                title={collapsedCompanies.size >= companyGroups.length ? 'Expand all companies' : 'Collapse all companies'}
                                                style={{
                                                    padding: '2px 6px', border: '1px solid var(--border)', borderRadius: '6px',
                                                    background: 'var(--bg)', color: 'var(--text-secondary)', cursor: 'pointer',
                                                    fontSize: '.68rem', fontFamily: 'var(--font-mono)',
                                                }}
                                            >
                                                {collapsedCompanies.size >= companyGroups.length ? 'Expand' : 'Collapse'} all
                                            </button>
                                        )}
                                    </div>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', color: 'var(--text-secondary)', opacity: 0.8, whiteSpace: 'nowrap' }}>
                                        {groupByCompany
                                            ? `${companyGroups.length} cos · ${sortedReadyJobs.length} jobs · ↑↓ j/k · space pick`
                                            : `${sortedReadyJobs.length} shown · ↑↓ j/k navigate · space pick · enter open`}
                                    </span>
                                </div>

                                <div style={{ flex: 1, overflowY: 'auto', padding: '10px', background: 'var(--bg)' }}>
                                    {listEntries.map((entry) => {
                                        if (entry.kind === 'header') {
                                            const group = entry.group;
                                            const isCollapsed = collapsedCompanies.has(group.key);
                                            const selectableIds = group.jobs
                                                .filter((jj) => jj.queue_item?.status !== 'queued' && jj.queue_item?.status !== 'running')
                                                .map((jj) => jj.id);
                                            const appliedCount = group.jobs.filter((jj) => !!jj.applied).length;
                                            const priorCount = group.jobs.filter((jj) => Number(jj.tailoring_run_count || 0) > 0).length;
                                            return (
                                                <div
                                                    key={`__group_${group.key}`}
                                                    onClick={() => toggleCompanyCollapsed(group.key)}
                                                    style={{
                                                        position: 'sticky',
                                                        top: 0,
                                                        zIndex: 1,
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '8px',
                                                        padding: '8px 10px',
                                                        marginBottom: '6px',
                                                        borderRadius: '8px',
                                                        border: '1px solid rgba(139, 124, 246, 0.32)',
                                                        background: 'linear-gradient(90deg, rgba(139, 124, 246, 0.16), rgba(139, 124, 246, 0.04))',
                                                        backdropFilter: 'blur(6px)',
                                                        WebkitBackdropFilter: 'blur(6px)',
                                                        cursor: 'pointer',
                                                        userSelect: 'none',
                                                    }}
                                                    title={isCollapsed ? 'Expand company group' : 'Collapse company group'}
                                                >
                                                    <ChevronDown
                                                        size={13}
                                                        style={{
                                                            color: 'var(--purple, #8b7cf6)',
                                                            transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                                                            transition: 'transform .12s ease',
                                                            flexShrink: 0,
                                                        }}
                                                    />
                                                    <Layers size={12} style={{ color: 'var(--purple, #8b7cf6)', opacity: 0.85, flexShrink: 0 }} />
                                                    <span
                                                        style={{
                                                            fontWeight: 700,
                                                            fontSize: '.8rem',
                                                            color: 'var(--text)',
                                                            letterSpacing: '.02em',
                                                            overflow: 'hidden',
                                                            textOverflow: 'ellipsis',
                                                            whiteSpace: 'nowrap',
                                                            minWidth: 0,
                                                        }}
                                                    >
                                                        {group.display}
                                                    </span>
                                                    <span
                                                        style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '.6rem',
                                                            fontWeight: 700,
                                                            color: 'var(--purple, #8b7cf6)',
                                                            background: 'rgba(139, 124, 246, 0.14)',
                                                            border: '1px solid rgba(139, 124, 246, 0.28)',
                                                            padding: '1px 7px',
                                                            borderRadius: '999px',
                                                            letterSpacing: '.04em',
                                                            flexShrink: 0,
                                                        }}
                                                    >
                                                        {group.jobs.length} {group.jobs.length === 1 ? 'job' : 'jobs'}
                                                    </span>
                                                    {appliedCount > 0 && (
                                                        <span
                                                            title={`${appliedCount} already applied`}
                                                            style={{
                                                                display: 'inline-flex', alignItems: 'center', gap: '3px',
                                                                fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 700,
                                                                color: 'var(--accent)',
                                                            }}
                                                        >
                                                            <CheckCircle2 size={10} />
                                                            {appliedCount}
                                                        </span>
                                                    )}
                                                    {priorCount > 0 && (
                                                        <span
                                                            title={`${priorCount} with prior tailoring runs`}
                                                            style={{
                                                                display: 'inline-flex', alignItems: 'center', gap: '3px',
                                                                fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 700,
                                                                color: 'var(--amber, #e0a030)',
                                                            }}
                                                        >
                                                            <Package size={10} />
                                                            {priorCount}
                                                        </span>
                                                    )}
                                                    <span style={{ flex: 1 }} />
                                                    {selectableIds.length > 0 && (
                                                        <button
                                                            type="button"
                                                            onClick={(e) => { e.stopPropagation(); queueJobIds(selectableIds); }}
                                                            disabled={queueBusy}
                                                            className="btn btn-ghost btn-sm"
                                                            title={`Queue every selectable job at ${group.display}`}
                                                            style={{ fontSize: '.64rem', padding: '2px 8px', color: 'var(--accent)', whiteSpace: 'nowrap' }}
                                                        >
                                                            Queue {selectableIds.length}
                                                        </button>
                                                    )}
                                                    <button
                                                        type="button"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            const ids = group.jobs
                                                                .filter((jj) => jj.queue_item?.status !== 'queued' && jj.queue_item?.status !== 'running')
                                                                .map((jj) => jj.id);
                                                            setSelectedIds((prev) => {
                                                                const next = new Set(prev);
                                                                const allPicked = ids.every((id) => next.has(id));
                                                                if (allPicked) ids.forEach((id) => next.delete(id));
                                                                else ids.forEach((id) => next.add(id));
                                                                return next;
                                                            });
                                                        }}
                                                        className="btn btn-ghost btn-sm"
                                                        title="Pick / unpick every job in this company"
                                                        style={{ fontSize: '.64rem', padding: '2px 8px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}
                                                    >
                                                        Pick
                                                    </button>
                                                </div>
                                            );
                                        }
                                        const j = entry.job;
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
                                        const salaryLabel = j.salary_k ? `$${Math.round(j.salary_k / 1000)}K` : null;
                                        const locationLabel = (j.location || '').trim() || null;
                                        const seniorityLabel = (j.seniority || '').trim() || null;
                                        return (
                                            <div
                                                key={j.id}
                                                ref={(el) => {
                                                    if (el) cardRefs.current.set(j.id, el);
                                                    else cardRefs.current.delete(j.id);
                                                }}
                                                onClick={() => setFocusedJobId(j.id)}
                                                style={{
                                                    marginBottom: '8px',
                                                    marginLeft: groupByCompany ? '14px' : 0,
                                                    padding: '12px 14px',
                                                    borderRadius: '10px',
                                                    border: `1px solid ${isFocused ? 'var(--accent)' : isChecked ? 'rgba(75, 142, 240, 0.35)' : 'var(--border)'}`,
                                                    borderLeft: groupByCompany
                                                        ? (isFocused
                                                            ? '3px solid var(--accent)'
                                                            : '3px solid rgba(139, 124, 246, 0.28)')
                                                        : `1px solid ${isFocused ? 'var(--accent)' : isChecked ? 'rgba(75, 142, 240, 0.35)' : 'var(--border)'}`,
                                                    background: isFocused ? 'var(--accent-light)' : isChecked ? 'rgba(75, 142, 240, 0.05)' : 'var(--surface)',
                                                    cursor: 'pointer',
                                                    transition: 'all .12s ease',
                                                    boxShadow: isFocused ? '0 0 0 1px var(--accent), 0 2px 8px rgba(75, 142, 240, 0.15)' : 'none',
                                                    opacity: isUnavailable ? 0.78 : 1,
                                                }}
                                            >
                                                {/* Top row: id · bucket · applied/queue · checkbox · open */}
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                                    <input
                                                        type="checkbox"
                                                        checked={isChecked}
                                                        disabled={isUnavailable}
                                                        onChange={() => toggleSelection(j.id)}
                                                        onClick={e => e.stopPropagation()}
                                                        style={{ accentColor: 'var(--accent)', margin: 0, cursor: isUnavailable ? 'not-allowed' : 'pointer' }}
                                                        aria-label={`Select job ${j.id}`}
                                                    />
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
                                                        #{j.id}
                                                    </span>
                                                    <span style={{
                                                        display: 'inline-flex', alignItems: 'center',
                                                        borderRadius: '999px',
                                                        border: `1px solid ${reviewMeta.border}`,
                                                        background: reviewMeta.background,
                                                        color: reviewMeta.color,
                                                        padding: '1px 8px',
                                                        fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 700,
                                                        letterSpacing: '.04em', textTransform: 'uppercase',
                                                    }}>
                                                        {reviewMeta.label}
                                                    </span>
                                                    {queueState && (
                                                        <span style={{
                                                            display: 'inline-flex', alignItems: 'center',
                                                            borderRadius: '999px',
                                                            border: `1px solid ${queueState === 'running' ? 'rgba(75, 142, 240, 0.35)' : 'rgba(60, 179, 113, 0.32)'}`,
                                                            background: queueState === 'running' ? 'rgba(75, 142, 240, 0.10)' : 'rgba(60, 179, 113, 0.10)',
                                                            color: queueState === 'running' ? 'var(--accent)' : 'var(--green)',
                                                            padding: '1px 8px',
                                                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 700,
                                                        }}>
                                                            {queueState}
                                                        </span>
                                                    )}
                                                    <span style={{ flex: 1 }} />
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }} title={j.created_at ? fmtDate(j.created_at) : ''}>
                                                        <Clock size={10} style={{ verticalAlign: '-1px', marginRight: '3px', opacity: 0.7 }} />
                                                        {j.created_at ? timeAgo(j.created_at) : '—'}
                                                    </span>
                                                    {j.url && (
                                                        <a
                                                            href={j.url}
                                                            target="_blank"
                                                            rel="noreferrer"
                                                            onClick={e => e.stopPropagation()}
                                                            title="Open JD in new tab (o)"
                                                            style={{
                                                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                                                width: '22px', height: '22px', borderRadius: '5px',
                                                                border: '1px solid rgba(75, 142, 240, 0.28)',
                                                                background: 'rgba(75, 142, 240, 0.08)',
                                                                color: 'var(--accent)',
                                                            }}
                                                            aria-label="Open JD in new tab"
                                                        >
                                                            <ExternalLink size={11} />
                                                        </a>
                                                    )}
                                                </div>

                                                {/* Title */}
                                                <div style={{
                                                    fontWeight: 600, fontSize: '.92rem', lineHeight: 1.35, color: 'var(--text)',
                                                    marginBottom: '8px',
                                                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                                                    overflow: 'hidden',
                                                }}>
                                                    {j.title || 'Untitled'}
                                                </div>

                                                {/* Headline facts: PAY · LOCATION · SENIORITY */}
                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                                                    <FactChip
                                                        icon={<DollarSign size={12} />}
                                                        label={salaryLabel || 'Salary N/A'}
                                                        color={salaryLabel ? 'var(--green)' : 'var(--text-secondary)'}
                                                        background={salaryLabel ? 'rgba(60, 179, 113, 0.12)' : 'var(--surface-2)'}
                                                        border={salaryLabel ? 'rgba(60, 179, 113, 0.35)' : 'var(--border)'}
                                                        dim={!salaryLabel}
                                                    />
                                                    <FactChip
                                                        icon={<MapPin size={12} />}
                                                        label={locationLabel || 'Location N/A'}
                                                        color={locationLabel ? 'var(--cyan, #2ab8cc)' : 'var(--text-secondary)'}
                                                        background={locationLabel ? 'rgba(42, 184, 204, 0.10)' : 'var(--surface-2)'}
                                                        border={locationLabel ? 'rgba(42, 184, 204, 0.32)' : 'var(--border)'}
                                                        dim={!locationLabel}
                                                    />
                                                    {seniorityLabel && (
                                                        <FactChip
                                                            icon={<Briefcase size={12} />}
                                                            label={seniorityLabel}
                                                            color="var(--amber, #e0a030)"
                                                            background="rgba(224, 160, 48, 0.10)"
                                                            border="rgba(224, 160, 48, 0.32)"
                                                        />
                                                    )}
                                                </div>

                                                {/* Company / source row */}
                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: j.snippet ? '8px' : '6px' }}>
                                                    {company && (
                                                        <span style={{
                                                            display: 'inline-flex', alignItems: 'center',
                                                            borderRadius: '999px',
                                                            border: '1px solid rgba(139, 124, 246, 0.32)',
                                                            background: 'rgba(139, 124, 246, 0.08)',
                                                            color: 'var(--purple, #8b7cf6)',
                                                            padding: '1px 8px',
                                                            fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                                                        }}>
                                                            {company}
                                                        </span>
                                                    )}
                                                    {j.board && (
                                                        <span className={`pill pill-${j.board}`} style={{ fontSize: '.62rem' }}>
                                                            {j.board}
                                                        </span>
                                                    )}
                                                    <span style={{
                                                        display: 'inline-flex', alignItems: 'center',
                                                        borderRadius: '999px',
                                                        border: `1px solid ${source.border}`,
                                                        background: source.background,
                                                        color: source.color,
                                                        padding: '1px 8px',
                                                        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                                                    }}>
                                                        {source.label}
                                                    </span>
                                                </div>

                                                {j.snippet && (
                                                    <div style={{
                                                        fontSize: '.74rem', color: 'var(--text-secondary)', lineHeight: 1.5,
                                                        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                                                        overflow: 'hidden', marginBottom: '6px',
                                                    }}>
                                                        {j.snippet}
                                                    </div>
                                                )}

                                                {/* Footer: host + history badges */}
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    {host && (
                                                        <span style={{
                                                            fontFamily: 'var(--font-mono)', fontSize: '.62rem',
                                                            color: 'var(--text-secondary)', opacity: 0.7,
                                                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                            flex: 1, minWidth: 0,
                                                        }}>
                                                            {host}
                                                        </span>
                                                    )}
                                                    {hasPriorRun && (
                                                        <span title={`${priorRunCount} prior tailoring run(s)`} style={{
                                                            display: 'inline-flex', alignItems: 'center', gap: '3px',
                                                            fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 700,
                                                            color: 'var(--amber, #e0a030)',
                                                        }}>
                                                            <Package size={10} />
                                                            {priorRunCount}
                                                        </span>
                                                    )}
                                                    {applied && (
                                                        <span title="Applied" style={{
                                                            display: 'inline-flex', alignItems: 'center', gap: '3px',
                                                            fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 700,
                                                            color: 'var(--accent)',
                                                        }}>
                                                            <CheckCircle2 size={10} />
                                                            Applied
                                                        </span>
                                                    )}
                                                    {isFocused && (
                                                        <ChevronRight size={14} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* ═════ RIGHT: Briefing detail ═════ */}
                            <div style={{ flex: 1, minWidth: 0, overflow: 'auto', background: 'var(--surface)' }}>
                                {!focusedJobId ? (
                                    <div style={{
                                        height: '100%', display: 'flex', flexDirection: 'column',
                                        alignItems: 'center', justifyContent: 'center', gap: '10px',
                                        color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.82rem',
                                        padding: '40px',
                                    }}>
                                        <ChevronRight size={28} style={{ opacity: 0.35, transform: 'rotate(180deg)' }} />
                                        <div style={{ textAlign: 'center', maxWidth: '320px', lineHeight: 1.5 }}>
                                            Select a candidate on the left to see the tailoring briefing, requirements mapping, and strategy.
                                        </div>
                                        <div style={{ fontSize: '.66rem', opacity: 0.7, marginTop: '8px' }}>
                                            ↑↓ / j k navigate · space pick · enter expand · o open JD
                                        </div>
                                    </div>
                                ) : detailLoading ? (
                                    <div className="loading" style={{ minHeight: '320px' }}><div className="spinner" /></div>
                                ) : !briefing ? (
                                    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem' }}>
                                        Job not found
                                    </div>
                                ) : (
                                    <BriefingPanel briefing={briefing} />
                                )}
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}

/* ─── Fact chip for headline facts (pay/location/seniority) ─── */
function FactChip({
    icon, label, color, background, border, dim,
}: { icon: React.ReactNode; label: string; color: string; background: string; border: string; dim?: boolean }) {
    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            padding: '3px 9px',
            borderRadius: '999px',
            border: `1px solid ${border}`,
            background,
            color,
            fontFamily: 'var(--font-mono)',
            fontSize: '.7rem',
            fontWeight: 600,
            fontStyle: dim ? 'italic' : 'normal',
            opacity: dim ? 0.75 : 1,
        }}>
            {icon}
            {label}
        </span>
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
