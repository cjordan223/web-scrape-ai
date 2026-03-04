import { useState, useEffect } from 'react';
import { api } from '../../../../api';

interface RecentJob {
    id: number;
    title?: string;
    created_at?: string;
    url?: string;
    tailoring_run_count?: number;
    has_tailoring_runs?: boolean;
    tailoring_latest_status?: 'complete' | 'partial' | 'failed' | 'no-trace' | string;
}

interface Props {
    onRunStarted: () => void;
}

export default function JobInventoryTab({ onRunStarted }: Props) {
    const [recentJobs, setRecentJobs] = useState<RecentJob[]>([]);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [focusedJobId, setFocusedJobId] = useState<number>(0);
    const [jobDetail, setJobDetail] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [skipAnalysis, setSkipAnalysis] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);
    const [queueError, setQueueError] = useState('');

    const statusMeta = (status?: string) => {
        if (status === 'complete') return { label: 'passed', color: 'var(--green)' };
        if (status === 'failed') return { label: 'failed', color: 'var(--red)' };
        if (status === 'partial') return { label: 'partial', color: 'var(--amber, #e0a030)' };
        if (status === 'no-trace') return { label: 'no-trace', color: 'var(--text-secondary)' };
        return { label: 'unknown', color: 'var(--text-secondary)' };
    };

    useEffect(() => {
        (async () => {
            try {
                const res = await api.getTailoringRecentJobs();
                setRecentJobs(res.items || []);
            } catch (err) { console.error(err); }
        })();
    }, []);

    useEffect(() => {
        if (!focusedJobId) { setJobDetail(null); return; }
        setDetailLoading(true);
        (async () => {
            try {
                const res = await api.getTailoringJobDetail(focusedJobId);
                setJobDetail(res);
            } catch { setJobDetail(null); }
            finally { setDetailLoading(false); }
        })();
    }, [focusedJobId]);

    const toggleSelection = (id: number) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const queueSelected = async () => {
        if (selectedIds.size === 0) return;
        setQueueBusy(true);
        setQueueError('');
        try {
            const jobs = Array.from(selectedIds).map(job_id => ({ job_id, skip_analysis: skipAnalysis }));
            const res = await api.queueTailoring(jobs);
            if (!res.ok) { setQueueError(res.error || 'Failed to queue'); return; }
            setSelectedIds(new Set());
            onRunStarted();
        } catch { setQueueError('Failed to queue jobs'); }
        finally { setQueueBusy(false); }
    };

    return (
        <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
            {/* Left: job list */}
            <div style={{
                width: '520px', flexShrink: 0, display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border)', background: 'var(--surface)', overflow: 'hidden',
            }}>
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em' }}>
                        Recent Jobs ({recentJobs.length})
                    </span>
                </div>

                {/* Queue controls */}
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={queueBusy || selectedIds.size === 0}
                            onClick={queueSelected}
                            style={{ flex: 1 }}
                        >
                            {queueBusy ? 'Queuing...' : `Queue Selected (${selectedIds.size})`}
                        </button>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                            <input type="checkbox" checked={skipAnalysis}
                                onChange={e => setSkipAnalysis(e.target.checked)}
                                style={{ accentColor: 'var(--accent)' }} />
                            Skip analysis
                        </label>
                    </div>
                    {selectedIds.size > 0 && (
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => setSelectedIds(new Set())}
                            style={{ fontSize: '.68rem', alignSelf: 'flex-start' }}
                        >
                            Clear selection
                        </button>
                    )}
                    {queueError && <div style={{ fontSize: '.72rem', color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>{queueError}</div>}
                </div>

                {/* Job list */}
                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {recentJobs.length === 0 ? (
                        <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.78rem' }}>
                            No recent jobs
                        </div>
                    ) : recentJobs.map((j) => {
                        const isFocused = focusedJobId === j.id;
                        const isChecked = selectedIds.has(j.id);
                        const priorRunCount = Number(j.tailoring_run_count || 0);
                        const hasPriorRun = Boolean(j.has_tailoring_runs || priorRunCount > 0);
                        const runStatus = statusMeta(j.tailoring_latest_status);
                        return (
                            <div
                                key={j.id}
                                style={{
                                    padding: '9px 14px', cursor: 'pointer',
                                    borderBottom: '1px solid var(--border)',
                                    borderLeft: isFocused ? '2px solid var(--accent)' : '2px solid transparent',
                                    background: isFocused ? 'var(--accent-light)' : isChecked ? 'rgba(var(--accent-rgb, 100,150,255), 0.06)' : 'transparent',
                                    transition: 'background .08s',
                                    display: 'flex', alignItems: 'flex-start', gap: '8px',
                                }}
                                onMouseEnter={e => { if (!isFocused && !isChecked) e.currentTarget.style.background = 'var(--surface-2)'; }}
                                onMouseLeave={e => { if (!isFocused && !isChecked) e.currentTarget.style.background = 'transparent'; }}
                            >
                                <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => toggleSelection(j.id)}
                                    onClick={e => e.stopPropagation()}
                                    style={{ accentColor: 'var(--accent)', marginTop: '3px', flexShrink: 0 }}
                                />
                                <div style={{ flex: 1, minWidth: 0 }} onClick={() => setFocusedJobId(j.id)}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)', flexShrink: 0 }}>#{j.id}</span>
                                        <span style={{ fontWeight: 600, fontSize: '.82rem', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {j.title || 'Untitled'}
                                        </span>
                                    </div>
                                    {hasPriorRun && (
                                        <div style={{ marginBottom: '4px' }}>
                                            <span
                                                title={`Tailoring has already been run ${priorRunCount} time${priorRunCount === 1 ? '' : 's'} for this job. Latest run status: ${runStatus.label}.`}
                                                style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '4px',
                                                    borderRadius: '999px',
                                                    border: '1px solid rgba(224, 160, 48, 0.55)',
                                                    background: 'rgba(224, 160, 48, 0.12)',
                                                    color: 'var(--amber, #e0a030)',
                                                    padding: '1px 8px',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '.62rem',
                                                    fontWeight: 600,
                                                    letterSpacing: '.02em',
                                                }}
                                            >
                                                Already run ({priorRunCount}) •
                                                <span
                                                    aria-hidden="true"
                                                    style={{
                                                        width: '6px',
                                                        height: '6px',
                                                        borderRadius: '999px',
                                                        background: runStatus.color,
                                                        display: 'inline-block',
                                                        marginLeft: '2px',
                                                    }}
                                                />
                                                <span style={{ color: runStatus.color }}>{runStatus.label}</span>
                                            </span>
                                        </div>
                                    )}
                                    {j.url && (
                                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {j.url}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Right: job detail */}
            <div style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: '20px' }}>
                {!focusedJobId ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem' }}>
                        Select a job to view details
                    </div>
                ) : detailLoading ? (
                    <div className="loading"><div className="spinner" /></div>
                ) : !jobDetail ? (
                    <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem', textAlign: 'center', padding: '40px' }}>
                        Job not found
                    </div>
                ) : (
                    <div style={{ maxWidth: '800px' }}>
                        <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '16px' }}>
                            Job #{jobDetail.id}: {jobDetail.title || 'Untitled'}
                        </h2>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {Object.entries(jobDetail).map(([key, value]) => (
                                <div key={key} style={{ borderBottom: '1px solid var(--border)', paddingBottom: '10px' }}>
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: '4px' }}>
                                        {key}
                                    </div>
                                    <pre style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.78rem', lineHeight: 1.5,
                                        whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text)',
                                        margin: 0, maxHeight: key === 'jd_text' ? '400px' : '200px', overflow: 'auto',
                                    }}>
                                        {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                                    </pre>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
