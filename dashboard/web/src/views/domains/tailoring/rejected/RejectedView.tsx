import { useEffect, useState } from 'react';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';

interface RejectedJob {
    id: number;
    title?: string;
    url?: string;
    snippet?: string;
    board?: string;
    seniority?: string;
    created_at?: string;
}

export default function RejectedView() {
    const [jobs, setJobs] = useState<RejectedJob[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [focusedId, setFocusedId] = useState<number | null>(null);
    const [detail, setDetail] = useState<any>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [busy, setBusy] = useState(false);

    const load = async () => {
        setLoading(true);
        try {
            const res = await api.getTailoringRejected(500);
            setJobs(res.items || []);
            setTotal(res.total ?? (res.items || []).length);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        const id = setInterval(load, 30000);
        return () => clearInterval(id);
    }, []);

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

    const returnSelectedToQA = async () => {
        if (selected.size === 0) return;
        setBusy(true);
        try {
            const ids = Array.from(selected);
            await api.undoRejectQA(ids);
            removeFromList(ids);
        } catch (err) {
            console.error(err);
        } finally {
            setBusy(false);
        }
    };

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
                        QA Rejected ({total})
                    </span>
                </div>

                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={busy || selected.size === 0}
                            onClick={returnSelectedToQA}
                            style={{ flex: 1 }}
                        >
                            {busy ? 'Returning...' : `Return Selected To QA (${selected.size})`}
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
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)' }}>
                        QA-rejected jobs stay stored in `results`, but they are not queueable until returned to QA.
                    </div>
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {jobs.length === 0 ? (
                        <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.78rem' }}>
                            No QA-rejected jobs are currently stored
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
                                    borderLeft: isFocused ? '2px solid var(--red)' : '2px solid transparent',
                                    background: isFocused ? 'rgba(196, 68, 68, 0.08)' : isChecked ? 'rgba(196, 68, 68, 0.05)' : 'transparent',
                                    transition: 'background .08s',
                                    display: 'flex',
                                    alignItems: 'flex-start',
                                    gap: '8px',
                                }}
                                onMouseEnter={e => { if (!isFocused && !isChecked) e.currentTarget.style.background = 'var(--surface-2)'; }}
                                onMouseLeave={e => { if (!isFocused && !isChecked) e.currentTarget.style.background = 'transparent'; }}
                            >
                                <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => toggle(job.id)}
                                    onClick={e => e.stopPropagation()}
                                    style={{ accentColor: 'var(--red)', marginTop: '3px', flexShrink: 0 }}
                                />
                                <div style={{ flex: 1, minWidth: 0 }} onClick={() => setFocusedId(job.id)}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)', flexShrink: 0 }}>#{job.id}</span>
                                        <span style={{ fontWeight: 600, fontSize: '.82rem', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {job.title || 'Untitled'}
                                        </span>
                                        <span style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            borderRadius: '999px',
                                            border: '1px solid rgba(196, 68, 68, 0.35)',
                                            background: 'rgba(196, 68, 68, 0.10)',
                                            color: 'var(--red)',
                                            padding: '1px 8px',
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.6rem',
                                            fontWeight: 700,
                                            letterSpacing: '.04em',
                                            textTransform: 'uppercase',
                                        }}>
                                            rejected
                                        </span>
                                    </div>
                                    {job.snippet && (
                                        <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                            {job.snippet}
                                        </div>
                                    )}
                                    <div style={{ marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                                        {job.board && <span className={`pill pill-${job.board}`}>{job.board}</span>}
                                        {job.seniority && <span className={`pill pill-${job.seniority}`}>{job.seniority}</span>}
                                        {job.created_at && (
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.64rem', color: 'var(--text-secondary)' }}>
                                                {timeAgo(job.created_at)}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>
                {!focusedId ? (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.85rem' }}>
                        Select a rejected job to inspect it
                    </div>
                ) : detailLoading ? (
                    <div className="loading" style={{ flex: 1 }}><div className="spinner" /></div>
                ) : !detail ? (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.85rem' }}>
                        Unable to load job details
                    </div>
                ) : (
                    <>
                        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: '8px' }}>
                                Rejected Job Detail
                            </div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>{detail.title || 'Untitled'}</div>
                            {detail.url && (
                                <a href={detail.url} target="_blank" rel="noreferrer" style={{ fontSize: '.75rem', color: 'var(--accent)' }}>
                                    {detail.url}
                                </a>
                            )}
                        </div>

                        <div style={{ flex: 1, overflowY: 'auto', padding: '18px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                            <div>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: '6px' }}>
                                    State
                                </div>
                                <div style={{ color: 'var(--red)', fontWeight: 600 }}>QA Rejected</div>
                            </div>
                            {detail.query && (
                                <div>
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: '6px' }}>
                                        Query
                                    </div>
                                    <div>{detail.query}</div>
                                </div>
                            )}
                            {detail.filter_verdicts?.length > 0 && (
                                <div>
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: '6px' }}>
                                        Filter Verdicts
                                    </div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                        {detail.filter_verdicts.map((verdict: string, index: number) => (
                                            <span key={`${verdict}-${index}`} className="pill pill-unknown">{verdict}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {detail.jd_text && (
                                <div>
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: '6px' }}>
                                        Job Description
                                    </div>
                                    <div className="jd-text">{detail.jd_text}</div>
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
