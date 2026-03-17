import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, apiClient } from '../../../../api';
import { copyText } from '../../../../utils';
import { groupTraceEvents, StageRow, SectionLabel, ArtifactViewer, TraceInspector } from './shared';

interface Props {
    runner: any;
    runs: any[];
}

export default function PipelineTab({ runner, runs }: Props) {
    const navigate = useNavigate();

    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [activeTrace, setActiveTrace] = useState<any>(null);
    const [selectedEvent, setSelectedEvent] = useState<any>(null);
    const [traceTab, setTraceTab] = useState<'overview' | 'system' | 'user' | 'response' | 'raw'>('overview');
    const [artifactView, setArtifactView] = useState<{ name: string; content: string; isPdf: boolean } | null>(null);
    const [artifactLoading, setArtifactLoading] = useState(false);

    const logRef = useRef<HTMLPreElement>(null);

    // Auto-select run matching currently running job, or most recent
    useEffect(() => {
        const jobId = runner?.job?.id;
        if (jobId && runs.length) {
            const match = runs.find((r: any) => r?.meta?.job_id === jobId);
            if (match?.slug && match.slug !== activeSlug) setActiveSlug(match.slug);
        } else if (!activeSlug && runs.length) {
            setActiveSlug(runs[0].slug);
        }
    }, [runner, runs]);

    // Fetch trace when slug changes
    useEffect(() => {
        if (!activeSlug) return;
        (async () => {
            try {
                const res = await api.getTailoringDetail(activeSlug);
                setActiveTrace(res);
            } catch { setActiveTrace(null); }
        })();
    }, [activeSlug]);

    // Live trace polling while runner active
    useEffect(() => {
        if (!runner.running || !activeSlug) return;
        const iv = setInterval(async () => {
            try {
                const res = await api.getTailoringDetail(activeSlug);
                setActiveTrace(res);
            } catch { /* ignore */ }
        }, 3000);
        return () => clearInterval(iv);
    }, [runner.running, activeSlug]);

    // Auto-scroll log
    useEffect(() => {
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, [runner.log_tail]);

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

    const traces = activeTrace?.events || [];
    const grouped = groupTraceEvents(traces);
    const activeRun = runs.find((r: any) => r.slug === activeSlug);
    const artifacts = activeRun?.artifacts || {};
    const availableArtifacts = Object.entries(artifacts).filter(([, exists]) => exists).map(([name]) => name);

    const docIcon = (status: string | undefined) => {
        if (!status || status === 'pending') return <span style={{ color: 'var(--text-secondary)' }}>--</span>;
        if (status === 'complete' || status === 'passed') return <span style={{ color: 'var(--green)', fontWeight: 700 }}>OK</span>;
        return <span style={{ color: 'var(--red)', fontWeight: 700 }}>FAIL</span>;
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            {/* Live log when runner has output */}
            {runner.log_tail && (
                <div style={{ borderBottom: '1px solid var(--border)', maxHeight: '180px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 14px', background: 'var(--surface-2)' }}>
                        <SectionLabel>Live Log</SectionLabel>
                        <button className="btn btn-ghost btn-sm" style={{ fontSize: '.68rem' }}
                            onClick={() => { void copyText(runner.log_tail); }}>
                            Copy
                        </button>
                    </div>
                    <pre ref={logRef} style={{
                        flex: 1, overflow: 'auto', padding: '8px 14px', margin: 0,
                        fontFamily: 'var(--font-mono)', fontSize: '.68rem', lineHeight: 1.5,
                        background: '#080c11', color: '#6a8da8', whiteSpace: 'pre-wrap',
                    }}>
                        {runner.log_tail}
                    </pre>
                </div>
            )}

            {!activeSlug || !activeTrace ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.85rem' }}>
                    {runner.running ? 'Pipeline starting...' : 'No active run — start one from the Jobs tab'}
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
                        <button className="btn btn-success btn-sm" onClick={() => navigate('/tailoring/outputs/packages')}>
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

                    {/* Pipeline tree + detail inspector */}
                    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
                        {/* Pipeline tree */}
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
                                    {runner.running ? 'Pipeline starting...' : 'No trace events'}
                                </div>
                            )}
                        </div>

                        {/* Detail inspector */}
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
    );
}
