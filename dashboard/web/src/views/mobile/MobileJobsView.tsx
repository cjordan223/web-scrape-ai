import { useEffect, useCallback, useState } from 'react';
import { api } from '../../api';

interface Job {
    id: number;
    title: string;
    url: string;
    runCount: number;
    latestStatus: string;
    applied?: { id: number; status?: string } | null;
    queueItem?: { id: number; status?: 'queued' | 'running' | string } | null;
}

export default function MobileJobsView() {
    const [jobs, setJobs] = useState<Job[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [skipAnalysis, setSkipAnalysis] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);
    const [queueMsg, setQueueMsg] = useState('');
    const [runnerStatus, setRunnerStatus] = useState<any>(null);

    const load = useCallback(() => {
        setLoading(true);
        api.getTailoringReady(500).then(res => {
            setTotal(res.total || 0);
            setJobs((res.items || []).map((j: any) => ({
                id: j.id, title: j.title || 'Untitled', url: j.url || '',
                runCount: j.tailoring_run_count || 0,
                latestStatus: j.tailoring_latest_status || '',
                applied: j.applied || null,
                queueItem: j.queue_item || null,
            })));
        }).catch(() => {}).finally(() => setLoading(false));
        api.getTailoringRunnerStatus().then(setRunnerStatus).catch(() => {});
    }, []);

    useEffect(() => {
        load();
        const id = setInterval(load, 15000);
        return () => clearInterval(id);
    }, [load]);

    const toggle = (id: number) => {
        const job = jobs.find((item) => item.id === id);
        if (job?.queueItem?.status === 'queued' || job?.queueItem?.status === 'running') {
            return;
        }
        setSelected(prev => {
            const n = new Set(prev);
            n.has(id) ? n.delete(id) : n.add(id);
            return n;
        });
    };

    const queueSelected = async () => {
        if (selected.size === 0) return;
        setQueueBusy(true); setQueueMsg('');
        try {
            const payload = Array.from(selected).map(job_id => ({ job_id, skip_analysis: skipAnalysis }));
            const res = await api.queueTailoring(payload);
            if (!res.ok) { setQueueMsg(res.error || 'Failed'); return; }
            setQueueMsg(`Queued ${selected.size} job(s)`);
            setSelected(new Set());
            load();
            setTimeout(() => setQueueMsg(''), 3000);
        } catch (e: any) {
            setQueueMsg(e?.response?.data?.error || 'Queue failed');
        } finally { setQueueBusy(false); }
    };

    const statusDot = (s: string) => {
        const c = s === 'complete' ? 'var(--green)' : s === 'failed' ? 'var(--red)' : s === 'partial' ? 'var(--amber)' : 'var(--text-secondary)';
        return <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, display: 'inline-block', marginRight: 4 }} />;
    };

    const hdr: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
    };
    const row: React.CSSProperties = {
        padding: '10px 0', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'flex-start', gap: '10px',
    };
    const btn: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.8rem', fontWeight: 600,
        padding: '12px', borderRadius: '4px', border: 'none', cursor: 'pointer',
        width: '100%', minHeight: '44px', background: 'var(--accent)', color: '#fff',
    };

    return (
        <div style={{ padding: '12px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={hdr}>Ready ({total})</span>
                <button onClick={load} style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.68rem', background: 'transparent',
                    border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 10px',
                    color: 'var(--text-secondary)', cursor: 'pointer', minHeight: '32px',
                }}>Refresh</button>
            </div>

            {/* Runner banner */}
            {runnerStatus?.running && (
                <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--amber)',
                    padding: '8px 10px', background: 'rgba(200,144,42,.08)', borderRadius: '4px',
                    marginBottom: '10px', border: '1px solid rgba(200,144,42,.2)',
                }}>Running job #{runnerStatus.job?.id || runnerStatus.active_item?.job_id}
                    {runnerStatus.queue?.length > 0 && ` · ${runnerStatus.queue.length} queued`}
                </div>
            )}

            {/* Queue action bar */}
            {selected.size > 0 && (
                <div style={{
                    position: 'sticky', top: 0, zIndex: 10, padding: '10px 0', marginBottom: '4px',
                    background: 'var(--bg)', display: 'flex', flexDirection: 'column', gap: '8px',
                }}>
                    <button style={{ ...btn, opacity: queueBusy ? 0.5 : 1 }}
                        onClick={queueSelected} disabled={queueBusy}>
                        {queueBusy ? 'Queuing...' : `Queue Selected (${selected.size})`}
                    </button>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                            <input type="checkbox" checked={skipAnalysis} onChange={e => setSkipAnalysis(e.target.checked)}
                                style={{ accentColor: 'var(--accent)', width: 18, height: 18 }} />
                            Skip analysis
                        </label>
                        <button onClick={() => setSelected(new Set())} style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.68rem', background: 'transparent',
                            border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '4px',
                        }}>Clear</button>
                    </div>
                </div>
            )}

            {queueMsg && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--green)', marginBottom: '8px' }}>{queueMsg}</div>
            )}

            {loading && <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--text-secondary)', padding: '20px 0', textAlign: 'center' }}>Loading...</div>}

            {!loading && jobs.length === 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.78rem', color: 'var(--text-secondary)', padding: '40px 0', textAlign: 'center' }}>
                    No QA-approved jobs are ready for tailoring
                </div>
            )}

            {jobs.map(j => {
                const checked = selected.has(j.id);
                const queueState = j.queueItem?.status;
                const isUnavailable = queueState === 'queued' || queueState === 'running';
                return (
                    <div key={j.id} style={{
                        ...row,
                        background: checked ? 'rgba(75,142,240,.06)' : 'transparent',
                    }} onClick={() => toggle(j.id)}>
                        <input type="checkbox" checked={checked} disabled={isUnavailable} readOnly
                            style={{ accentColor: 'var(--accent)', width: 20, height: 20, marginTop: 2, flexShrink: 0 }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)' }}>#{j.id}</span>
                                <span style={{ fontSize: '.82rem', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {j.title}
                                </span>
                                {queueState && (
                                    <span style={{
                                        marginLeft: 'auto',
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '.58rem',
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '.04em',
                                        color: queueState === 'running' ? 'var(--accent)' : 'var(--amber, #e0a030)',
                                    }}>
                                        {queueState}
                                    </span>
                                )}
                            </div>
                            {j.runCount > 0 && (
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', color: 'var(--text-secondary)', marginTop: '3px', display: 'flex', alignItems: 'center' }}>
                                    {statusDot(j.latestStatus)}
                                    {j.runCount} run{j.runCount !== 1 ? 's' : ''} · {j.latestStatus || 'unknown'}
                                </div>
                            )}
                            {j.applied && (
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', color: 'var(--accent)', marginTop: '3px' }}>
                                    Applied{j.applied.status ? ` · ${j.applied.status}` : ''}
                                </div>
                            )}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
