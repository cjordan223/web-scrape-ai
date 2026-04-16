import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../../../api';
import { fmtDate, toLocalInputValue } from '../../../../utils';
import { DetailContextSection, type ContextTab, timeAgo, safePdfName } from './shared';

type PackageDoc = 'resume' | 'cover';
type DocumentMode = 'preview' | 'latex';

const STATUS_OPTIONS = [
    { value: 'all', label: 'All statuses' },
    { value: 'applied', label: 'Applied' },
    { value: 'follow_up', label: 'Follow Up' },
    { value: 'withdrawn', label: 'Withdrawn' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'offer', label: 'Offer' },
];

function statusTone(status?: string | null) {
    switch (status) {
        case 'offer':
            return { background: 'rgba(60,179,113,.12)', color: 'var(--green)', border: '1px solid rgba(60,179,113,.28)' };
        case 'applied':
            return { background: 'rgba(75,142,240,.12)', color: 'var(--accent)', border: '1px solid rgba(75,142,240,.24)' };
        case 'follow_up':
            return { background: 'rgba(200,144,42,.12)', color: 'var(--amber)', border: '1px solid rgba(200,144,42,.26)' };
        case 'withdrawn':
        case 'rejected':
            return { background: 'rgba(217,79,79,.12)', color: 'var(--red)', border: '1px solid rgba(217,79,79,.24)' };
        default:
            return { background: 'var(--surface-3)', color: 'var(--text-secondary)', border: '1px solid var(--border)' };
    }
}

function metaPill(label: string, value: string, tone?: 'default' | 'warm' | 'cool') {
    const palette = tone === 'warm'
        ? { background: 'rgba(200,144,42,.12)', color: 'var(--amber)', border: '1px solid rgba(200,144,42,.22)' }
        : tone === 'cool'
            ? { background: 'rgba(75,142,240,.12)', color: 'var(--accent)', border: '1px solid rgba(75,142,240,.22)' }
            : { background: 'var(--surface-3)', color: 'var(--text-secondary)', border: '1px solid var(--border)' };
    return (
        <span style={{
            ...palette,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px',
            borderRadius: '999px',
            padding: '3px 9px',
            fontSize: '.69rem',
            fontWeight: 600,
            fontFamily: 'var(--font-sans)',
            lineHeight: 1,
        }}>
            <span style={{ opacity: 0.7 }}>{label}</span>
            <span>{value}</span>
        </span>
    );
}

export default function AppliedView() {
    const [searchParams] = useSearchParams();
    const requestedId = Number(searchParams.get('application_id') || '');

    const [items, setItems] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [expandedId, setExpandedId] = useState<number | null>(Number.isFinite(requestedId) && requestedId > 0 ? requestedId : null);
    const [detail, setDetail] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [contextTab, setContextTab] = useState<ContextTab>('overview');
    const [packageDoc, setPackageDoc] = useState<PackageDoc>('resume');
    const [documentMode, setDocumentMode] = useState<DocumentMode>('preview');
    const [statusFilter, setStatusFilter] = useState('all');
    const [searchInput, setSearchInput] = useState('');
    const [search, setSearch] = useState('');
    const [status, setStatus] = useState('applied');
    const [applicationUrl, setApplicationUrl] = useState('');
    const [appliedAt, setAppliedAt] = useState('');
    const [followUpAt, setFollowUpAt] = useState('');
    const [notes, setNotes] = useState('');
    const [saveBusy, setSaveBusy] = useState(false);
    const [saveMessage, setSaveMessage] = useState('');

    useEffect(() => {
        const next = window.setTimeout(() => setSearch(searchInput.trim()), 180);
        return () => window.clearTimeout(next);
    }, [searchInput]);

    const loadList = useCallback(async () => {
        setLoading(true);
        try {
            const params: Record<string, string> = {};
            if (statusFilter !== 'all') params.status = statusFilter;
            if (search) params.q = search;
            const res = await api.getAppliedList(params);
            const nextItems = res.items || [];
            setItems(nextItems);
            setExpandedId((current) => {
                if (requestedId && nextItems.some((item: any) => item.id === requestedId)) return requestedId;
                if (current && nextItems.some((item: any) => item.id === current)) return current;
                return current && nextItems.length === 0 ? null : current;
            });
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [requestedId, search, statusFilter]);

    const loadDetail = useCallback(async (applicationId: number) => {
        setDetailLoading(true);
        try {
            const res = await api.getAppliedDetail(applicationId);
            setDetail(res);
            setContextTab('overview');
            setStatus(res.summary?.status || 'applied');
            setApplicationUrl(res.summary?.application_url || '');
            setAppliedAt(toLocalInputValue(res.summary?.applied_at));
            setFollowUpAt(toLocalInputValue(res.summary?.follow_up_at));
            setNotes(res.summary?.notes || '');
            setSaveMessage('');
        } finally {
            setDetailLoading(false);
        }
    }, []);

    useEffect(() => {
        loadList();
        const id = window.setInterval(() => {
            if (!document.hidden) loadList();
        }, 15000);
        return () => window.clearInterval(id);
    }, [loadList]);

    useEffect(() => {
        if (!expandedId) {
            setDetail(null);
            return;
        }
        loadDetail(expandedId).catch((err) => {
            console.error(err);
            setDetail(null);
        });
    }, [expandedId, loadDetail]);

    const filteredCountLabel = useMemo(() => {
        if (!search && statusFilter === 'all') return `${items.length} snapshots`;
        const pieces = [`${items.length} matches`];
        if (statusFilter !== 'all') pieces.push(STATUS_OPTIONS.find((option) => option.value === statusFilter)?.label || statusFilter);
        if (search) pieces.push(`"${search}"`);
        return pieces.join(' • ');
    }, [items.length, search, statusFilter]);

    const handleSaveTracking = async () => {
        if (!expandedId) return;
        setSaveBusy(true);
        setSaveMessage('');
        try {
            await api.updateAppliedTracking(expandedId, {
                status,
                application_url: applicationUrl || null,
                applied_at: appliedAt ? new Date(appliedAt).toISOString() : null,
                follow_up_at: followUpAt ? new Date(followUpAt).toISOString() : null,
                notes: notes || null,
            });
            await loadList();
            await loadDetail(expandedId);
            setSaveMessage('Tracking saved');
        } catch (e: any) {
            setSaveMessage(e.response?.data?.error || 'Failed to update tracking');
        } finally {
            setSaveBusy(false);
        }
    };

    if (loading && items.length === 0) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <div className="spinner" />
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>
            <div style={{
                padding: '16px 28px 12px',
                borderBottom: '1px solid var(--border)',
                background: 'linear-gradient(180deg, rgba(75,142,240,.06), rgba(75,142,240,0))',
            }}>
                <div style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '.62rem',
                    letterSpacing: '.12em',
                    textTransform: 'uppercase',
                    color: 'var(--text-secondary)',
                    marginBottom: '10px',
                }}>
                    Applied Ledger
                </div>
                <div style={{ display: 'flex', alignItems: 'end', gap: '16px', flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 360px', minWidth: '260px' }}>
                        <div style={{ fontSize: '1.22rem', fontWeight: 700, color: 'var(--text)', marginBottom: '2px' }}>
                            Applied snapshots
                        </div>
                        <div style={{ fontSize: '.84rem', color: 'var(--text-secondary)' }}>
                            Search fast, scan the timeline, and expand only the application you want to inspect.
                        </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        {metaPill('Count', String(items.length), 'cool')}
                        {search ? metaPill('Search', search) : null}
                        {statusFilter !== 'all' ? metaPill('Status', STATUS_OPTIONS.find((option) => option.value === statusFilter)?.label || statusFilter, 'warm') : null}
                    </div>
                </div>
            </div>

            <div style={{ padding: '14px 28px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1.5fr) 220px 160px 150px auto', gap: '10px', alignItems: 'center' }}>
                    <input
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        placeholder="Search title, company, notes, package..."
                        style={{
                            borderRadius: '10px',
                            border: '1px solid var(--border-bright)',
                            background: 'var(--surface)',
                            color: 'var(--text)',
                            padding: '11px 14px',
                            fontSize: '.9rem',
                            fontFamily: 'var(--font-sans)',
                            boxShadow: 'inset 0 1px 0 rgba(255,255,255,.02)',
                        }}
                    />
                    <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                        style={{
                            borderRadius: '10px',
                            border: '1px solid var(--border-bright)',
                            background: 'var(--surface)',
                            color: 'var(--text)',
                            padding: '11px 12px',
                            fontSize: '.88rem',
                            fontFamily: 'var(--font-sans)',
                        }}
                    >
                        {STATUS_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                    <button
                        className="btn btn-ghost"
                        onClick={() => {
                            setSearchInput('');
                            setSearch('');
                            setStatusFilter('all');
                        }}
                        style={{ height: '42px', fontSize: '.82rem' }}
                    >
                        Clear filters
                    </button>
                    <div style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '.68rem',
                        color: 'var(--text-secondary)',
                        textTransform: 'uppercase',
                        letterSpacing: '.08em',
                    }}>
                        {filteredCountLabel}
                    </div>
                </div>
            </div>

            <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'minmax(320px, 1.5fr) minmax(220px, 1fr) 120px 150px 120px 70px',
                    gap: '16px',
                    padding: '10px 28px',
                    borderBottom: '1px solid var(--border)',
                    background: 'var(--surface-2)',
                    position: 'sticky',
                    top: 0,
                    zIndex: 5,
                    fontFamily: 'var(--font-mono)',
                    fontSize: '.62rem',
                    letterSpacing: '.1em',
                    textTransform: 'uppercase',
                    color: 'var(--text-secondary)',
                }}>
                    <div>Job</div>
                    <div>Company + Snapshot</div>
                    <div>Status</div>
                    <div>Applied</div>
                    <div>Follow Up</div>
                    <div>Open</div>
                </div>

                {items.length === 0 ? (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexDirection: 'column',
                        gap: '10px',
                        padding: '80px 20px',
                        color: 'var(--text-secondary)',
                    }}>
                        <span style={{ fontSize: '1.8rem', opacity: 0.22 }}>&#10003;</span>
                        <span style={{ fontSize: '.92rem', fontFamily: 'var(--font-sans)' }}>No applied snapshots match the current filters.</span>
                    </div>
                ) : (
                    items.map((item) => {
                        const isExpanded = expandedId === item.id;
                        const tone = statusTone(item.status);
                        return (
                            <div key={item.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                <div
                                    onClick={() => setExpandedId((current) => current === item.id ? null : item.id)}
                                    style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'minmax(320px, 1.5fr) minmax(220px, 1fr) 120px 150px 120px 70px',
                                        gap: '16px',
                                        padding: '14px 28px',
                                        cursor: 'pointer',
                                        background: isExpanded ? 'rgba(75,142,240,.06)' : 'transparent',
                                        transition: 'background .12s ease',
                                        alignItems: 'start',
                                    }}
                                >
                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '6px' }}>
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)' }}>#{item.id}</span>
                                            <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text)' }}>
                                                {item.job_title || item.package_slug}
                                            </span>
                                        </div>
                                        <div style={{
                                            fontSize: '.84rem',
                                            lineHeight: 1.55,
                                            color: 'var(--text-secondary)',
                                            display: '-webkit-box',
                                            WebkitLineClamp: 2,
                                            WebkitBoxOrient: 'vertical',
                                            overflow: 'hidden',
                                            marginBottom: '8px',
                                        }}>
                                            {item.notes || item.job_url || 'Saved application snapshot'}
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                                            {item.job_url ? (
                                                <a
                                                    href={item.job_url}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    onClick={(event) => event.stopPropagation()}
                                                    style={{
                                                        fontSize: '.75rem',
                                                        color: 'var(--accent)',
                                                        textDecoration: 'none',
                                                    }}
                                                >
                                                    Source job
                                                </a>
                                            ) : null}
                                            <span style={{ fontSize: '.74rem', color: 'var(--text-secondary)' }}>
                                                Updated {timeAgo(item.updated_at || item.applied_at)}
                                            </span>
                                        </div>
                                    </div>

                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '7px' }}>
                                            {item.company_name ? metaPill('Company', item.company_name, 'cool') : null}
                                            {item.package_slug ? metaPill('Snapshot', item.package_slug) : null}
                                        </div>
                                        <div style={{
                                            fontSize: '.74rem',
                                            color: 'var(--text-secondary)',
                                            lineHeight: 1.5,
                                            wordBreak: 'break-word',
                                        }}>
                                            {item.application_url || item.job_url || '--'}
                                        </div>
                                    </div>

                                    <div>
                                        <span style={{
                                            ...tone,
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            borderRadius: '999px',
                                            padding: '4px 10px',
                                            fontSize: '.72rem',
                                            fontWeight: 700,
                                            fontFamily: 'var(--font-sans)',
                                            textTransform: 'capitalize',
                                        }}>
                                            {String(item.status || 'unknown').replace(/_/g, ' ')}
                                        </span>
                                    </div>

                                    <div>
                                        <div style={{ fontSize: '.82rem', fontWeight: 600, color: 'var(--text)' }}>
                                            {fmtDate(item.applied_at || item.updated_at)}
                                        </div>
                                        <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                                            {timeAgo(item.applied_at || item.updated_at)}
                                        </div>
                                    </div>

                                    <div>
                                        <div style={{ fontSize: '.82rem', fontWeight: 600, color: 'var(--text)' }}>
                                            {item.follow_up_at ? fmtDate(item.follow_up_at) : '--'}
                                        </div>
                                        <div style={{ fontSize: '.72rem', color: item.follow_up_at ? 'var(--amber)' : 'var(--text-secondary)', marginTop: '4px' }}>
                                            {item.follow_up_at ? timeAgo(item.follow_up_at) : 'Not set'}
                                        </div>
                                    </div>

                                    <div style={{
                                        display: 'flex',
                                        justifyContent: 'flex-end',
                                        alignItems: 'center',
                                        height: '100%',
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '.9rem',
                                        color: isExpanded ? 'var(--accent)' : 'var(--text-secondary)',
                                    }}>
                                        {isExpanded ? '▾' : '▸'}
                                    </div>
                                </div>

                                {isExpanded ? (
                                    <div style={{
                                        padding: '0 28px 22px',
                                        background: 'rgba(75,142,240,.04)',
                                        borderTop: '1px solid rgba(75,142,240,.12)',
                                    }}>
                                        {detailLoading || !detail || detail.summary?.id !== item.id ? (
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '32px 0' }}>
                                                <div className="spinner" />
                                            </div>
                                        ) : (
                                            <div style={{
                                                border: '1px solid var(--border)',
                                                borderRadius: '16px',
                                                overflow: 'hidden',
                                                background: 'var(--surface)',
                                                boxShadow: '0 12px 32px rgba(0,0,0,.12)',
                                            }}>
                                                <DetailContextSection
                                                    title={detail.job_context?.title || detail.summary?.job_title || 'Untitled'}
                                                    companyName={detail.summary?.company_name || detail.summary?.meta?.company_name || detail.summary?.meta?.company}
                                                    jobUrl={detail.job_context?.url || detail.summary?.job_url}
                                                    status={detail.summary?.status}
                                                    extraMeta={(
                                                        <>
                                                            <span style={{ opacity: 0.3 }}>&middot;</span>
                                                            <span>saved {timeAgo(detail.summary?.created_at)}</span>
                                                        </>
                                                    )}
                                                    badges={(
                                                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                                                            <div style={{ fontFamily: 'var(--font-sans)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>
                                                                snapshot: {detail.summary?.package_slug}
                                                            </div>
                                                            {detail.summary?.follow_up_at ? metaPill('Follow Up', fmtDate(detail.summary?.follow_up_at), 'warm') : null}
                                                        </div>
                                                    )}
                                                    contextTab={contextTab}
                                                    onContextTabChange={setContextTab}
                                                    analysis={detail.analysis}
                                                    resumeStrategy={detail.resume_strategy}
                                                    coverStrategy={detail.cover_strategy}
                                                    jobContext={detail.job_context}
                                                    emptyNote="No analysis or strategy data were stored in this applied snapshot."
                                                />

                                                <div style={{
                                                    borderTop: '1px solid var(--border)',
                                                    borderBottom: '1px solid var(--border)',
                                                    background: 'var(--surface-2)',
                                                    padding: '18px 20px',
                                                    display: 'grid',
                                                    gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                                                    gap: '12px',
                                                }}>
                                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                        <span style={{ fontSize: '.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Status</span>
                                                        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ borderRadius: '10px', border: '1px solid var(--border-bright)', background: 'var(--surface)', color: 'var(--text)', padding: '11px 12px', fontSize: '.9rem', fontFamily: 'var(--font-sans)' }}>
                                                            {STATUS_OPTIONS.filter((option) => option.value !== 'all').map((option) => (
                                                                <option key={option.value} value={option.value}>{option.label}</option>
                                                            ))}
                                                        </select>
                                                    </label>
                                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                        <span style={{ fontSize: '.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Application URL</span>
                                                        <input value={applicationUrl} onChange={(e) => setApplicationUrl(e.target.value)} style={{ borderRadius: '10px', border: '1px solid var(--border-bright)', background: 'var(--surface)', color: 'var(--text)', padding: '11px 12px', fontSize: '.9rem', fontFamily: 'var(--font-sans)' }} />
                                                    </label>
                                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                        <span style={{ fontSize: '.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Applied At</span>
                                                        <input type="datetime-local" value={appliedAt} onChange={(e) => setAppliedAt(e.target.value)} style={{ borderRadius: '10px', border: '1px solid var(--border-bright)', background: 'var(--surface)', color: 'var(--text)', padding: '11px 12px', fontSize: '.9rem', fontFamily: 'var(--font-sans)' }} />
                                                    </label>
                                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                        <span style={{ fontSize: '.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Follow Up</span>
                                                        <input type="datetime-local" value={followUpAt} onChange={(e) => setFollowUpAt(e.target.value)} style={{ borderRadius: '10px', border: '1px solid var(--border-bright)', background: 'var(--surface)', color: 'var(--text)', padding: '11px 12px', fontSize: '.9rem', fontFamily: 'var(--font-sans)' }} />
                                                    </label>
                                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', gridColumn: '1 / -1' }}>
                                                        <span style={{ fontSize: '.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Notes</span>
                                                        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} style={{ minHeight: '88px', resize: 'vertical', borderRadius: '10px', border: '1px solid var(--border-bright)', background: 'var(--surface)', color: 'var(--text)', padding: '11px 12px', fontSize: '.9rem', fontFamily: 'var(--font-sans)', lineHeight: 1.55 }} />
                                                    </label>
                                                    <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                                                        <button className="btn btn-primary" onClick={handleSaveTracking} disabled={saveBusy}>
                                                            {saveBusy ? 'Saving...' : 'Save Tracking'}
                                                        </button>
                                                        {detail.summary?.application_url ? (
                                                            <a className="btn btn-ghost" href={detail.summary.application_url} target="_blank" rel="noreferrer">
                                                                Open Application
                                                            </a>
                                                        ) : null}
                                                        {saveMessage ? (
                                                            <span style={{ fontSize: '.8rem', color: saveMessage === 'Tracking saved' ? 'var(--green)' : 'var(--red)' }}>
                                                                {saveMessage}
                                                            </span>
                                                        ) : null}
                                                    </div>
                                                </div>

                                                <div style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '8px',
                                                    padding: '10px 20px',
                                                    borderBottom: '1px solid var(--border)',
                                                    background: 'var(--surface)',
                                                    flexShrink: 0,
                                                    flexWrap: 'wrap',
                                                }}>
                                                    <select
                                                        value={packageDoc}
                                                        onChange={(e) => setPackageDoc(e.target.value as PackageDoc)}
                                                        style={{
                                                            padding: '9px 12px',
                                                            borderRadius: '10px',
                                                            fontSize: '.86rem',
                                                            fontFamily: 'var(--font-sans)',
                                                            border: '1px solid var(--border-bright)',
                                                            background: 'var(--surface-2)',
                                                            color: 'var(--text)',
                                                            outline: 'none',
                                                        }}
                                                    >
                                                        <option value="resume">Resume</option>
                                                        <option value="cover">Cover Letter</option>
                                                    </select>
                                                    <button className={`btn ${documentMode === 'preview' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setDocumentMode('preview')}>
                                                        Preview
                                                    </button>
                                                    <button className={`btn ${documentMode === 'latex' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setDocumentMode('latex')}>
                                                        LaTeX
                                                    </button>
                                                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                                        <a
                                                            className="btn btn-ghost"
                                                            href={`/api/applied/${encodeURIComponent(String(item.id))}/artifact/Conner_Jordan_Resume.pdf`}
                                                            download={safePdfName(detail.summary?.company_name, detail.summary?.job_title, detail.summary?.package_slug || 'document', 'resume')}
                                                        >
                                                            Download Resume PDF
                                                        </a>
                                                        <a
                                                            className="btn btn-ghost"
                                                            href={`/api/applied/${encodeURIComponent(String(item.id))}/artifact/Conner_Jordan_Cover_Letter.pdf`}
                                                            download={safePdfName(detail.summary?.company_name, detail.summary?.job_title, detail.summary?.package_slug || 'document', 'cover')}
                                                        >
                                                            Download Cover PDF
                                                        </a>
                                                    </div>
                                                </div>

                                                <div style={{ height: '540px', minHeight: '540px', overflow: 'hidden', background: documentMode === 'preview' ? '#525659' : 'var(--surface-3)' }}>
                                                    {documentMode === 'preview' ? (
                                                        <iframe
                                                            src={`/api/applied/${encodeURIComponent(String(item.id))}/artifact/${packageDoc === 'resume' ? 'Conner_Jordan_Resume.pdf' : 'Conner_Jordan_Cover_Letter.pdf'}#pagemode=none&view=Fit`}
                                                            style={{ width: '100%', height: '100%', border: 'none', background: '#525659' }}
                                                        />
                                                    ) : (
                                                        <textarea
                                                            readOnly
                                                            value={packageDoc === 'resume' ? detail.latex?.resume || '' : detail.latex?.cover || ''}
                                                            style={{
                                                                width: '100%',
                                                                height: '100%',
                                                                border: 'none',
                                                                outline: 'none',
                                                                resize: 'none',
                                                                padding: '18px',
                                                                fontFamily: 'var(--font-mono)',
                                                                fontSize: '.78rem',
                                                                lineHeight: 1.6,
                                                                background: 'var(--surface-3)',
                                                                color: 'var(--text)',
                                                            }}
                                                        />
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ) : null}
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}
