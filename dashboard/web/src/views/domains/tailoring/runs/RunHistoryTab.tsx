import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, apiClient } from '../../../../api';
import { timeAgo } from '../../../../utils';
import { groupTraceEvents, StageRow, SectionLabel, ArtifactViewer, TraceInspector } from './shared';

interface Props {
    runs: any[];
    loading: boolean;
}

export default function RunHistoryTab({ runs, loading }: Props) {
    const navigate = useNavigate();

    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [activeTrace, setActiveTrace] = useState<any>(null);
    const [selectedEvent, setSelectedEvent] = useState<any>(null);
    const [traceTab, setTraceTab] = useState<'overview' | 'system' | 'user' | 'response' | 'raw'>('overview');
    const [artifactView, setArtifactView] = useState<{ name: string; content: string; isPdf: boolean } | null>(null);
    const [artifactLoading, setArtifactLoading] = useState(false);

    useEffect(() => {
        if (!activeSlug) return;
        (async () => {
            try {
                const res = await api.getTailoringDetail(activeSlug);
                setActiveTrace(res);
            } catch { setActiveTrace(null); }
        })();
    }, [activeSlug]);

    const viewArtifact = async (slug: string, name: string) => {
        if (name.endsWith('.pdf')) {
            setArtifactView({ name, content: `${apiClient.defaults.baseURL}/tailoring/runs/${encodeURIComponent(slug)}/artifact/${encodeURIComponent(name)}`, isPdf: true });
            setSelectedEvent(null);
            return;
        }
        setArtifactLoading(true);
        try {
            const res = await apiClient.get(`/tailoring/runs/${encodeURIComponent(slug)}/artifact/${encodeURIComponent(name)}`, { transformResponse: [(d: string) => d] });
            let content = res.data;
            try {
                if (name.endsWith('.jsonl')) {
                    content = res.data.trim().split('\n').map((l: string) => {
                        try { return JSON.stringify(JSON.parse(l), null, 2); } catch { return l; }
                    }).join('\n\n');
                } else if (name.endsWith('.json')) {
                    content = JSON.stringify(JSON.parse(res.data), null, 2);
                }
            } catch { /* keep raw */ }
            setArtifactView({ name, content, isPdf: false });
            setSelectedEvent(null);
        } catch { /* ignore */ }
        finally { setArtifactLoading(false); }
    };

    const statusPill = (status: string) => {
        if (status === 'complete') return 'pill pill-success';
        if (status === 'failed') return 'pill pill-fail';
        if (status === 'no-trace') return 'pill pill-unknown';
        return 'pill pill-running';
    };

    const docIcon = (status: string | undefined) => {
        if (!status || status === 'pending') return <span style={{ color: 'var(--text-secondary)' }}>--</span>;
        if (status === 'complete' || status === 'passed') return <span style={{ color: 'var(--green)', fontWeight: 700 }}>OK</span>;
        return <span style={{ color: 'var(--red)', fontWeight: 700 }}>FAIL</span>;
    };

    const traces = activeTrace?.events || [];
    const grouped = groupTraceEvents(traces);
    const activeRun = runs.find((r: any) => r.slug === activeSlug);
    const artifacts = activeRun?.artifacts || {};
    const availableArtifacts = Object.entries(artifacts).filter(([, exists]) => exists).map(([name]) => name);

    return (
        <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
            {/* Left: run list */}
            <div style={{
                width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border)', background: 'var(--surface)', overflow: 'hidden',
            }}>
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em' }}>
                        All Runs ({runs.length})
                    </span>
                </div>
                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {loading ? (
                        <div className="loading"><div className="spinner" /></div>
                    ) : runs.length === 0 ? (
                        <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.78rem' }}>
                            No runs yet
                        </div>
                    ) : runs.map((run: any) => {
                        const isActive = activeSlug === run.slug;
                        return (
                            <div
                                key={run.slug}
                                onClick={() => { setActiveSlug(run.slug); setSelectedEvent(null); setArtifactView(null); }}
                                style={{
                                    padding: '9px 14px', cursor: 'pointer',
                                    borderBottom: '1px solid var(--border)',
                                    borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                                    background: isActive ? 'var(--accent-light)' : 'transparent',
                                    transition: 'background .08s',
                                }}
                                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--surface-2)'; }}
                                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                                    <span style={{ fontWeight: 600, fontSize: '.82rem', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {run.meta?.title || run.slug}
                                    </span>
                                    <span className={statusPill(run.status)} style={{ flexShrink: 0 }}>{run.status}</span>
                                </div>
                                <div style={{ display: 'flex', gap: '10px', fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)', alignItems: 'center' }}>
                                    <span>#{run.meta?.job_id ?? '--'}</span>
                                    <span>R:{docIcon(run.doc_status?.resume)}</span>
                                    <span>C:{docIcon(run.doc_status?.cover)}</span>
                                    <span style={{ marginLeft: 'auto' }}>{timeAgo(run.updated_at)}</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Right: pipeline inspector for selected historical run */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {!activeSlug || !activeTrace ? (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.85rem' }}>
                        Select a run to inspect
                    </div>
                ) : (
                    <>
                        {/* Run header */}
                        <div style={{
                            padding: '12px 20px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                            display: 'flex', alignItems: 'center', gap: '14px', flexShrink: 0,
                        }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontWeight: 600, fontSize: '.95rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    Job {activeTrace.meta?.job_id ?? '--'} &middot; {activeTrace.meta?.title ?? activeSlug}
                                </div>
                                <div style={{ display: 'flex', gap: '12px', fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', marginTop: '3px', alignItems: 'center' }}>
                                    <span>Resume {docIcon(activeTrace.doc_status?.resume)}</span>
                                    <span>Cover {docIcon(activeTrace.doc_status?.cover)}</span>
                                    <span>{traces.length} events</span>
                                </div>
                            </div>
                            <button className="btn btn-success btn-sm" onClick={() => navigate('/pipeline/packages')}>
                                Package Review
                            </button>
                        </div>

                        {/* Artifacts bar */}
                        {availableArtifacts.length > 0 && (
                            <div style={{
                                padding: '6px 20px', borderBottom: '1px solid var(--border)',
                                display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center', flexShrink: 0,
                                background: 'var(--surface)',
                            }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em', marginRight: '6px' }}>
                                    Artifacts
                                </span>
                                {availableArtifacts.map(name => (
                                    <button
                                        key={name}
                                        className={`btn btn-sm ${artifactView?.name === name ? 'btn-primary' : 'btn-ghost'}`}
                                        onClick={() => artifactView?.name === name ? setArtifactView(null) : viewArtifact(activeSlug, name)}
                                        style={{ fontSize: '.7rem', fontFamily: 'var(--font-mono)' }}
                                    >
                                        {name}
                                    </button>
                                ))}
                                {artifactLoading && <div className="spinner" style={{ width: '14px', height: '14px' }} />}
                            </div>
                        )}

                        {/* Pipeline tree + detail */}
                        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
                            <div style={{
                                width: '260px', flexShrink: 0, overflowY: 'auto',
                                borderRight: '1px solid var(--border)', background: 'var(--surface)',
                                padding: '4px 0',
                            }}>
                                <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '6px', marginBottom: '2px' }}>
                                    <SectionLabel>Analysis</SectionLabel>
                                    <StageRow label="LLM" ev={grouped.analysis.llm} selectedEvent={selectedEvent} artifactView={artifactView}
                                        onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                </div>

                                {Object.keys(grouped.resume).length > 0 && (
                                    <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '6px', marginBottom: '2px' }}>
                                        {Object.keys(grouped.resume).map(Number).sort((a, b) => a - b).map((n, i, arr) => (
                                            <div key={`r-${n}`}>
                                                <SectionLabel>Resume{arr.length > 1 ? ` #${n}${i > 0 ? ' (retry)' : ''}` : ''}</SectionLabel>
                                                <StageRow label="Strategy" ev={grouped.resume[n].strategy} indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                                <StageRow label="Draft" ev={grouped.resume[n].draft} indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                                <StageRow label="QA" ev={grouped.resume[n].qa} indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                                <StageRow label="Validate" ev={grouped.resume[n].validation} isValidation indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {Object.keys(grouped.cover).length > 0 && (
                                    <div style={{ paddingBottom: '6px' }}>
                                        {Object.keys(grouped.cover).map(Number).sort((a, b) => a - b).map((n, i, arr) => (
                                            <div key={`c-${n}`}>
                                                <SectionLabel>Cover{arr.length > 1 ? ` #${n}${i > 0 ? ' (retry)' : ''}` : ''}</SectionLabel>
                                                <StageRow label="Strategy" ev={grouped.cover[n].strategy} indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                                <StageRow label="Draft" ev={grouped.cover[n].draft} indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                                <StageRow label="QA" ev={grouped.cover[n].qa} indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                                <StageRow label="Validate" ev={grouped.cover[n].validation} isValidation indent selectedEvent={selectedEvent} artifactView={artifactView} onSelect={ev => { setSelectedEvent(ev); setArtifactView(null); }} />
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {Object.keys(grouped.resume).length === 0 && Object.keys(grouped.cover).length === 0 && !grouped.analysis.llm && (
                                    <div style={{ padding: '20px 10px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.75rem' }}>
                                        No trace events
                                    </div>
                                )}
                            </div>

                            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                                {artifactView ? (
                                    <ArtifactViewer artifact={artifactView} onClose={() => setArtifactView(null)} />
                                ) : selectedEvent ? (
                                    <TraceInspector event={selectedEvent} traceTab={traceTab} setTraceTab={setTraceTab} />
                                ) : (
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem' }}>
                                        Select a pipeline stage or artifact to inspect
                                    </div>
                                )}
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
