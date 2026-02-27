import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, apiClient } from '../../../../api';
import { timeAgo } from '../../../../utils';

export default function TailoringView() {
    const navigate = useNavigate();

    // --- Data state ---
    const [runs, setRuns] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [recentJobs, setRecentJobs] = useState<any[]>([]);
    const [runner, setRunner] = useState<any>({ running: false, log_tail: '' });

    // --- Selection state ---
    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [activeTrace, setActiveTrace] = useState<any>(null);
    const [selectedEvent, setSelectedEvent] = useState<any>(null);
    const [traceTab, setTraceTab] = useState<'overview' | 'system' | 'user' | 'response' | 'raw'>('overview');

    // --- Artifact viewer state ---
    const [artifactView, setArtifactView] = useState<{ name: string; content: string; isPdf: boolean } | null>(null);
    const [artifactLoading, setArtifactLoading] = useState(false);

    // --- Run controls ---
    const [runConfig, setRunConfig] = useState({ selected_job_id: 0, skip_analysis: false });
    const [runBusy, setRunBusy] = useState(false);
    const [runError, setRunError] = useState('');

    // --- Refs ---
    const logRef = useRef<HTMLPreElement>(null);
    const prevRunningRef = useRef<boolean>(false);

    // ───────────────────────────── Data fetching ─────────────────────────────

    const fetchRuns = useCallback(async () => {
        try {
            const res = await api.getTailoring();
            setRuns(res);
            if (res.length > 0 && !activeSlug) setActiveSlug(res[0].slug);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    }, [activeSlug]);

    const fetchRecentJobs = async () => {
        try {
            const res = await api.getTailoringRecentJobs();
            setRecentJobs(res.items || []);
            if (!runConfig.selected_job_id && (res.items || []).length > 0) {
                setRunConfig(prev => ({ ...prev, selected_job_id: res.items[0].id }));
            }
        } catch (err) { console.error(err); }
    };

    const fetchRunnerStatus = async () => {
        try {
            const res = await api.getTailoringRunnerStatus();
            setRunner(res);
        } catch (err) { console.error(err); }
    };

    const runSelectedJob = async () => {
        if (!runConfig.selected_job_id) return;
        setRunBusy(true);
        setRunError('');
        try {
            const res = await api.runTailoring(runConfig.selected_job_id, runConfig.skip_analysis);
            if (!res.ok) {
                setRunError(res.error || 'Failed to start');
                if (res.runner) setRunner(res.runner);
                return;
            }
            if (res.runner) setRunner(res.runner);
            fetchRuns();
        } catch { setRunError('Failed to start run'); }
        finally { setRunBusy(false); }
    };

    const viewArtifact = async (name: string) => {
        if (!activeSlug) return;
        if (name.endsWith('.pdf')) {
            setArtifactView({ name, content: `${apiClient.defaults.baseURL}/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(name)}`, isPdf: true });
            setSelectedEvent(null);
            return;
        }
        setArtifactLoading(true);
        try {
            const res = await apiClient.get(`/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(name)}`, { transformResponse: [(d: string) => d] });
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
        } catch { setRunError('Failed to load artifact'); }
        finally { setArtifactLoading(false); }
    };

    // ───────────────────────────── Effects ───────────────────────────────────

    // Initial load + slow polling
    useEffect(() => {
        fetchRuns();
        fetchRecentJobs();
        fetchRunnerStatus();
        const i1 = setInterval(fetchRuns, 30000);
        const i2 = setInterval(fetchRunnerStatus, 10000);
        return () => { clearInterval(i1); clearInterval(i2); };
    }, [fetchRuns]);

    // Fast-poll while runner is active; flush on completion
    useEffect(() => {
        if (!runner.running) {
            if (prevRunningRef.current) fetchRuns();
            prevRunningRef.current = false;
            return;
        }
        prevRunningRef.current = true;
        const f1 = setInterval(fetchRunnerStatus, 2000);
        const f2 = setInterval(fetchRuns, 5000);
        return () => { clearInterval(f1); clearInterval(f2); };
    }, [runner.running]);

    // Fetch trace when active slug changes
    useEffect(() => {
        if (!activeSlug) return;
        (async () => {
            try {
                const res = await api.getTailoringDetail(activeSlug);
                setActiveTrace(res);
            } catch { setActiveTrace(null); }
        })();
    }, [activeSlug]);

    // Re-fetch trace for active run while runner is going (live pipeline updates)
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

    // Auto-select the run matching the currently running job
    useEffect(() => {
        const jobId = runner?.job?.id;
        if (!jobId || !runs.length) return;
        const match = runs.find((r: any) => r?.meta?.job_id === jobId);
        if (match?.slug && match.slug !== activeSlug) setActiveSlug(match.slug);
    }, [runner, runs, activeSlug]);

    // Auto-scroll log
    useEffect(() => {
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, [runner.log_tail]);

    // ───────────────────────────── Helpers ───────────────────────────────────

    const traces = activeTrace?.events || [];

    const groupTraceEvents = (events: any[]) => {
        const analysis: any = { llm: null };
        const resume: Record<number, any> = {};
        const cover: Record<number, any> = {};
        for (const ev of events) {
            const attempt = ev.attempt ?? 1;
            const isLlm = ev.event_type === 'llm_call_success' || ev.event_type === 'llm_call_error';
            const isVal = ev.event_type === 'validation_result';
            if (ev.doc_type === 'analysis') {
                if (isLlm && (!analysis.llm || ev.event_type === 'llm_call_success')) analysis.llm = ev;
            } else if (ev.doc_type === 'resume') {
                if (!resume[attempt]) resume[attempt] = { strategy: null, draft: null, qa: null, validation: null };
                if (isVal) resume[attempt].validation = ev;
                else if (isLlm) {
                    const slot = ev.phase as 'strategy' | 'draft' | 'qa';
                    if (slot && (!resume[attempt][slot] || ev.event_type === 'llm_call_success')) resume[attempt][slot] = ev;
                }
            } else if (ev.doc_type === 'cover') {
                if (!cover[attempt]) cover[attempt] = { strategy: null, draft: null, qa: null, validation: null };
                if (isVal) cover[attempt].validation = ev;
                else if (isLlm) {
                    const slot = ev.phase as 'strategy' | 'draft' | 'qa';
                    if (slot && (!cover[attempt][slot] || ev.event_type === 'llm_call_success')) cover[attempt][slot] = ev;
                }
            }
        }
        return { analysis, resume, cover };
    };

    const grouped = groupTraceEvents(traces);
    const fmtDuration = (ms: number | null | undefined) => ms == null ? '' : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;

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

    const activeRun = runs.find((r: any) => r.slug === activeSlug);
    const artifacts = activeRun?.artifacts || {};
    const availableArtifacts = Object.entries(artifacts).filter(([, exists]) => exists).map(([name]) => name);

    // ───────────────────────────── Sub-components ────────────────────────────

    const StageRow = ({ label, ev, isValidation, indent }: { label: string; ev: any; isValidation?: boolean; indent?: boolean }) => {
        if (!ev) {
            return (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 10px', paddingLeft: indent ? '28px' : '10px', opacity: 0.4, fontFamily: 'var(--font-mono)', fontSize: '.75rem' }}>
                    <span style={{ width: '72px' }}>{label}</span>
                    <span>--</span>
                </div>
            );
        }
        const success = isValidation ? ev.passed !== false : ev.event_type === 'llm_call_success';
        const isSelected = selectedEvent === ev && !artifactView;
        const failures = isValidation ? (ev.failures || []) : null;

        return (
            <div
                onClick={isValidation ? undefined : () => { setSelectedEvent(ev); setArtifactView(null); }}
                style={{
                    display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px',
                    padding: '5px 10px', paddingLeft: indent ? '28px' : '10px',
                    cursor: isValidation ? 'default' : 'pointer',
                    borderRadius: '2px',
                    background: isSelected ? 'var(--accent-light)' : 'transparent',
                    borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
                    fontFamily: 'var(--font-mono)', fontSize: '.75rem',
                    transition: 'background .08s',
                }}
                onMouseEnter={e => { if (!isSelected && !isValidation) (e.currentTarget.style.background = 'var(--surface-2)'); }}
                onMouseLeave={e => { if (!isSelected) (e.currentTarget.style.background = 'transparent'); }}
            >
                <span style={{ width: '72px', fontWeight: 500 }}>{label}</span>
                <span style={{ color: success ? 'var(--green)' : 'var(--red)', fontWeight: 700, fontSize: '.85rem' }}>
                    {success ? 'OK' : 'ERR'}
                </span>
                {!isValidation && ev.duration_ms != null && (
                    <span style={{ color: 'var(--text-secondary)', fontSize: '.72rem' }}>{fmtDuration(ev.duration_ms)}</span>
                )}
                {failures && failures.length > 0 && (
                    <div style={{ fontSize: '.72rem', color: 'var(--red)', flexBasis: '100%', marginTop: '2px', paddingLeft: '78px' }}>
                        {failures.join(', ')}
                    </div>
                )}
            </div>
        );
    };

    const SectionLabel = ({ children }: { children: React.ReactNode }) => (
        <div style={{
            fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
            color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em',
            padding: '8px 10px 4px',
        }}>{children}</div>
    );

    // ───────────────────────────── Detail pane content ───────────────────────

    const renderDetailContent = () => {
        // Artifact view
        if (artifactView) {
            if (artifactView.isPdf) {
                return (
                    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 600 }}>{artifactView.name}</span>
                            <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setArtifactView(null)}>Close</button>
                        </div>
                        <iframe src={artifactView.content} style={{ flex: 1, border: 'none', minHeight: '600px', background: '#fff' }} />
                    </div>
                );
            }
            return (
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 600 }}>{artifactView.name}</span>
                        <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}
                            onClick={() => { navigator.clipboard.writeText(artifactView.content).catch(() => { }); }}>
                            Copy
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setArtifactView(null)}>Close</button>
                    </div>
                    <div style={{ flex: 1, overflow: 'auto', padding: '12px' }}>
                        <pre style={{ fontFamily: 'var(--font-mono)', fontSize: '.76rem', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text)' }}>
                            {artifactView.content}
                        </pre>
                    </div>
                </div>
            );
        }

        // Trace view
        if (selectedEvent) {
            const isSuccess = selectedEvent.event_type === 'llm_call_success' || selectedEvent.passed === true || selectedEvent.status === 'passed';
            const isError = selectedEvent.event_type === 'llm_call_error' || selectedEvent.passed === false || selectedEvent.status === 'failed' || selectedEvent.status === 'error';

            const diagnostics: string[] = [];
            if (selectedEvent.event_type === 'llm_call_error') diagnostics.push('Request failed before a usable response was produced.');
            if (selectedEvent.event_type === 'llm_call_success' && !selectedEvent.raw_response) diagnostics.push('Call succeeded but response body is empty.');
            if (selectedEvent.response_parse_status === 'failed') diagnostics.push('Response parse failed. The model returned text that did not match expected format.');
            if (selectedEvent.passed === false) diagnostics.push('Validation failed. See failure list for violated gates.');
            if (selectedEvent.attempt && Number(selectedEvent.attempt) > 1) diagnostics.push(`Retry attempt #${selectedEvent.attempt}. Earlier attempt(s) failed.`);
            if (diagnostics.length === 0 && isSuccess) diagnostics.push('Event looks healthy.');

            const requestSummary = [
                `event=${selectedEvent.event_type || '--'}`,
                `doc=${selectedEvent.doc_type || '--'}`,
                `phase=${selectedEvent.phase || '--'}`,
                `attempt=${selectedEvent.attempt ?? '--'}`,
                `model=${selectedEvent.model || '--'}`,
                `duration_ms=${selectedEvent.duration_ms ?? '--'}`,
                `parse=${selectedEvent.response_parse_kind || '--'}/${selectedEvent.response_parse_status || '--'}`,
            ].join('\n');

            const healthChecks = [
                { label: 'Prompt', ok: Boolean(selectedEvent.system_prompt || selectedEvent.user_prompt), desc: 'System/user prompt captured for this event.' },
                { label: 'Response', ok: selectedEvent.event_type === 'llm_call_success' ? Boolean(selectedEvent.raw_response) : selectedEvent.event_type !== 'llm_call_error', desc: 'Response text captured from model call.' },
                { label: 'Parse', ok: (selectedEvent.response_parse_status || 'skipped') !== 'failed', desc: 'Response parser accepted expected format.' },
                { label: 'Validation', ok: selectedEvent.passed !== false, desc: 'Final hard-gate validation passed for this attempt.' },
            ];

            const tabContent = () => {
                if (traceTab === 'overview') return '';
                if (traceTab === 'system') return selectedEvent.system_prompt || '(empty)';
                if (traceTab === 'user') return selectedEvent.user_prompt || '(empty)';
                if (traceTab === 'response') return selectedEvent.raw_response || selectedEvent.error || '(empty)';
                return JSON.stringify(selectedEvent, null, 2);
            };
            return (
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    <div className="trace-health-strip">
                        {healthChecks.map((h) => (
                            <div key={h.label} className={`trace-health-chip ${h.ok ? 'ok' : 'bad'}`} title={h.desc}>
                                <span>{h.label}</span>
                                <strong>{h.ok ? 'OK' : 'ISSUE'}</strong>
                            </div>
                        ))}
                    </div>
                    <div className="trace-tabs">
                        {(['overview', 'system', 'user', 'response', 'raw'] as const).map(t => (
                            <button key={t} className={`btn ${traceTab === t ? 'btn-primary' : 'btn-ghost'} btn-sm`}
                                onClick={() => setTraceTab(t)} style={{ textTransform: 'capitalize' }}>
                                {t}
                            </button>
                        ))}
                        {traceTab === 'overview' && (
                            <>
                                <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}
                                    onClick={() => navigator.clipboard.writeText(selectedEvent.error || 'No error for this event').catch(() => { })}>
                                    Copy error
                                </button>
                                <button className="btn btn-ghost btn-sm"
                                    onClick={() => navigator.clipboard.writeText(requestSummary).catch(() => { })}>
                                    Copy summary
                                </button>
                                <button className="btn btn-ghost btn-sm" onClick={() => setTraceTab('raw')}>
                                    Open raw
                                </button>
                            </>
                        )}
                        {traceTab !== 'overview' && (
                            <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}
                                onClick={() => navigator.clipboard.writeText(tabContent()).catch(() => { })}>
                                Copy
                            </button>
                        )}
                    </div>
                    <div className="trace-content">
                        {traceTab === 'overview' ? (
                            <div className="trace-overview">
                                {(() => {
                                    const startRaw = selectedEvent.started_at || selectedEvent.timestamp;
                                    const endRaw = selectedEvent.ended_at;
                                    const startDate = startRaw ? new Date(startRaw) : null;
                                    const endDate = endRaw ? new Date(endRaw) : null;
                                    const fmtTime = (d: Date | null) => d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--';
                                    const parseOk = (selectedEvent.response_parse_status || 'skipped') !== 'failed';
                                    const valOk = selectedEvent.passed !== false;
                                    const truncate = (s: string | undefined | null, max: number) => {
                                        if (!s) return null;
                                        return s.length > max ? s.slice(0, max) + '\n... (' + (s.length - max) + ' chars truncated)' : s;
                                    };

                                    return (
                                        <div className="trace-timeline">
                                            {/* ── Step 1: Call Initiated ── */}
                                            <div className="trace-tl-step">
                                                <div className="trace-tl-rail">
                                                    <div className="trace-tl-dot trace-tl-dot--neutral" />
                                                    <div className="trace-tl-line" />
                                                </div>
                                                <div className="trace-tl-body">
                                                    <div className="trace-tl-head">
                                                        <span className="trace-tl-time">{fmtTime(startDate)}</span>
                                                        <span className="trace-tl-label">Call initiated</span>
                                                        <span className="trace-tl-tag">{(selectedEvent.doc_type || '--').toUpperCase()} / {(selectedEvent.phase || '--').toUpperCase()} / ATT {selectedEvent.attempt ?? 1}</span>
                                                    </div>
                                                    <div className="trace-tl-meta">
                                                        <span>{selectedEvent.model || '--'}</span>
                                                        <span>temp={selectedEvent.temperature ?? '--'}</span>
                                                        <span>max_tok={selectedEvent.max_tokens ?? '--'}</span>
                                                        {selectedEvent.endpoint && <span className="trace-tl-endpoint">{selectedEvent.endpoint}</span>}
                                                    </div>
                                                    {/* System prompt */}
                                                    {selectedEvent.system_prompt && (
                                                        <div className="trace-tl-block">
                                                            <div className="trace-tl-block-label">System prompt</div>
                                                            <pre className="trace-tl-pre">{truncate(selectedEvent.system_prompt, 3000)}</pre>
                                                        </div>
                                                    )}
                                                    {/* User prompt */}
                                                    {selectedEvent.user_prompt && (
                                                        <div className="trace-tl-block">
                                                            <div className="trace-tl-block-label">User prompt</div>
                                                            <pre className="trace-tl-pre">{truncate(selectedEvent.user_prompt, 3000)}</pre>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>

                                            {/* ── Step 2: Response / Error ── */}
                                            <div className="trace-tl-step">
                                                <div className="trace-tl-rail">
                                                    <div className={`trace-tl-dot trace-tl-dot--${isError ? 'err' : 'ok'}`} />
                                                    <div className="trace-tl-line" />
                                                </div>
                                                <div className="trace-tl-body">
                                                    <div className="trace-tl-head">
                                                        <span className="trace-tl-time">{fmtTime(endDate)}</span>
                                                        <span className={`trace-tl-label trace-tl-label--${isError ? 'err' : 'ok'}`}>
                                                            {isError ? 'Request failed' : 'Response received'}
                                                        </span>
                                                        {!isError && selectedEvent.duration_ms != null && (
                                                            <span className="trace-tl-tag">{fmtDuration(selectedEvent.duration_ms)} &middot; {selectedEvent.response_chars ?? '--'} chars</span>
                                                        )}
                                                    </div>
                                                    {isError && selectedEvent.error ? (
                                                        <div className="trace-tl-block trace-tl-block--err">
                                                            <div className="trace-tl-block-label">Error</div>
                                                            <pre className="trace-tl-pre">{selectedEvent.error}</pre>
                                                        </div>
                                                    ) : selectedEvent.raw_response ? (
                                                        <div className="trace-tl-block">
                                                            <div className="trace-tl-block-label">Raw response</div>
                                                            <pre className="trace-tl-pre">{truncate(selectedEvent.raw_response, 4000)}</pre>
                                                        </div>
                                                    ) : (
                                                        <div className="trace-tl-detail">No response body captured.</div>
                                                    )}
                                                </div>
                                            </div>

                                            {/* ── Step 3: Parse ── */}
                                            {!isError && (
                                                <div className="trace-tl-step">
                                                    <div className="trace-tl-rail">
                                                        <div className={`trace-tl-dot trace-tl-dot--${parseOk ? 'ok' : 'err'}`} />
                                                        {selectedEvent.passed != null && <div className="trace-tl-line" />}
                                                    </div>
                                                    <div className="trace-tl-body">
                                                        <div className="trace-tl-head">
                                                            <span className="trace-tl-time" />
                                                            <span className={`trace-tl-label trace-tl-label--${parseOk ? 'ok' : 'err'}`}>
                                                                Parse &amp; extract
                                                            </span>
                                                            <span className="trace-tl-tag">{selectedEvent.response_parse_kind || '--'} parser &rarr; {selectedEvent.response_parse_status || '--'}</span>
                                                        </div>
                                                        {!parseOk && (
                                                            <div className="trace-tl-sub trace-tl-sub--err">
                                                                Model output did not match expected JSON/LaTeX shape for this step.
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}

                                            {/* ── Step 4: Validation ── */}
                                            {selectedEvent.passed != null && (
                                                <div className="trace-tl-step">
                                                    <div className="trace-tl-rail">
                                                        <div className={`trace-tl-dot trace-tl-dot--${valOk ? 'ok' : 'err'}`} />
                                                    </div>
                                                    <div className="trace-tl-body">
                                                        <div className="trace-tl-head">
                                                            <span className="trace-tl-time" />
                                                            <span className={`trace-tl-label trace-tl-label--${valOk ? 'ok' : 'err'}`}>
                                                                Validation
                                                            </span>
                                                            <span className="trace-tl-tag">{valOk ? 'all gates passed' : 'gate violations'}</span>
                                                        </div>
                                                        {!valOk && Array.isArray(selectedEvent.failures) && selectedEvent.failures.length > 0 && (
                                                            <div className="trace-tl-block trace-tl-block--err">
                                                                <div className="trace-tl-block-label">Failures</div>
                                                                {selectedEvent.failures.map((f: string, i: number) => (
                                                                    <div key={i} className="trace-tl-sub trace-tl-sub--err">{f}</div>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })()}

                                {/* ── Context footer ── */}
                                <div className="trace-tl-footer">
                                    <span>Call ID: {selectedEvent.call_id || '--'}</span>
                                    <span>Run: {selectedEvent.run_slug || '--'}</span>
                                    <span>Job {selectedEvent.job_id ?? '--'}: {selectedEvent.job_title || '--'}</span>
                                </div>
                            </div>
                        ) : (
                            <pre>{tabContent()}</pre>
                        )}
                    </div>
                </div>
            );
        }

        // Empty
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem' }}>
                Select a pipeline stage or artifact to inspect
            </div>
        );
    };

    // ───────────────────────────── Render ────────────────────────────────────

    return (
        <div style={{ display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>

            {/* ══════════ LEFT SIDEBAR ══════════ */}
            <div style={{
                width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border)', background: 'var(--surface)', overflow: 'hidden',
            }}>

                {/* Runner status bar */}
                <div style={{
                    padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                    display: 'flex', alignItems: 'center', gap: '8px',
                }}>
                    <span className={`status-dot ${runner.running ? 'active' : 'idle'}`} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 500 }}>
                        {runner.running ? 'RUNNING' : 'IDLE'}
                    </span>
                    {runner.running && runner.job && (
                        <span style={{ fontSize: '.72rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            Job {runner.job.id}
                        </span>
                    )}
                </div>

                {/* New run controls */}
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <SectionLabel>New Run</SectionLabel>
                    <select
                        value={runConfig.selected_job_id}
                        onChange={e => setRunConfig({ ...runConfig, selected_job_id: Number(e.target.value) })}
                        style={{
                            width: '100%', padding: '6px 8px', border: '1px solid var(--border-bright)',
                            borderRadius: '2px', fontSize: '.78rem', fontFamily: 'var(--font-mono)',
                            background: 'var(--surface-3)', color: 'var(--text)', outline: 'none',
                        }}
                    >
                        <option value={0}>Select job...</option>
                        {recentJobs.map((j: any) => (
                            <option key={j.id} value={j.id}>
                                {j.id} - {(j.title || 'Untitled').substring(0, 40)}
                            </option>
                        ))}
                    </select>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                            className="btn btn-primary btn-sm"
                            disabled={runBusy || runner.running || !runConfig.selected_job_id}
                            onClick={runSelectedJob}
                            style={{ flex: 1 }}
                        >
                            {runBusy ? 'Starting...' : runner.running ? 'In Progress' : 'Run'}
                        </button>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                            <input type="checkbox" checked={runConfig.skip_analysis}
                                onChange={e => setRunConfig({ ...runConfig, skip_analysis: e.target.checked })}
                                style={{ accentColor: 'var(--accent)' }} />
                            Skip analysis
                        </label>
                    </div>
                    {runError && <div style={{ fontSize: '.72rem', color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>{runError}</div>}
                </div>

                {/* Live log (shown when runner has output) */}
                {runner.log_tail && (
                    <div style={{ borderBottom: '1px solid var(--border)', maxHeight: '180px', display: 'flex', flexDirection: 'column' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 14px', background: 'var(--surface-2)' }}>
                            <SectionLabel>Live Log</SectionLabel>
                            <button className="btn btn-ghost btn-sm" style={{ fontSize: '.68rem' }}
                                onClick={() => { navigator.clipboard.writeText(runner.log_tail).catch(() => { }); }}>
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

                {/* Run history */}
                <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                    <div style={{ padding: '10px 14px 6px' }}>
                        <SectionLabel>Run History</SectionLabel>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto' }}>
                        {loading ? (
                            <div className="loading"><div className="spinner" /></div>
                        ) : runs.length === 0 ? (
                            <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.78rem' }}>
                                No runs yet
                            </div>
                        ) : (
                            runs.map((run: any) => {
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
                            })
                        )}
                    </div>
                </div>
            </div>

            {/* ══════════ MAIN CONTENT ══════════ */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

                {!activeSlug || !activeTrace ? (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.85rem' }}>
                        Select a run from the sidebar or start a new one
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
                                        onClick={() => artifactView?.name === name ? setArtifactView(null) : viewArtifact(name)}
                                        style={{ fontSize: '.7rem', fontFamily: 'var(--font-mono)' }}
                                    >
                                        {name}
                                    </button>
                                ))}
                                {artifactLoading && <div className="spinner" style={{ width: '14px', height: '14px' }} />}
                            </div>
                        )}

                        {/* Pipeline + detail inspector */}
                        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

                            {/* Pipeline tree */}
                            <div style={{
                                width: '260px', flexShrink: 0, overflowY: 'auto',
                                borderRight: '1px solid var(--border)', background: 'var(--surface)',
                                padding: '4px 0',
                            }}>
                                {/* Analysis */}
                                <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '6px', marginBottom: '2px' }}>
                                    <SectionLabel>Analysis</SectionLabel>
                                    <StageRow label="LLM" ev={grouped.analysis.llm} />
                                </div>

                                {/* Resume */}
                                {Object.keys(grouped.resume).length > 0 && (
                                    <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '6px', marginBottom: '2px' }}>
                                        {Object.keys(grouped.resume).map(Number).sort((a, b) => a - b).map((n, i, arr) => (
                                            <div key={`r-${n}`}>
                                                <SectionLabel>Resume{arr.length > 1 ? ` #${n}${i > 0 ? ' (retry)' : ''}` : ''}</SectionLabel>
                                                <StageRow label="Strategy" ev={grouped.resume[n].strategy} indent />
                                                <StageRow label="Draft" ev={grouped.resume[n].draft} indent />
                                                <StageRow label="QA" ev={grouped.resume[n].qa} indent />
                                                <StageRow label="Validate" ev={grouped.resume[n].validation} isValidation indent />
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* Cover */}
                                {Object.keys(grouped.cover).length > 0 && (
                                    <div style={{ paddingBottom: '6px' }}>
                                        {Object.keys(grouped.cover).map(Number).sort((a, b) => a - b).map((n, i, arr) => (
                                            <div key={`c-${n}`}>
                                                <SectionLabel>Cover{arr.length > 1 ? ` #${n}${i > 0 ? ' (retry)' : ''}` : ''}</SectionLabel>
                                                <StageRow label="Strategy" ev={grouped.cover[n].strategy} indent />
                                                <StageRow label="Draft" ev={grouped.cover[n].draft} indent />
                                                <StageRow label="QA" ev={grouped.cover[n].qa} indent />
                                                <StageRow label="Validate" ev={grouped.cover[n].validation} isValidation indent />
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

                            {/* Detail / inspector pane */}
                            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                                {renderDetailContent()}
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
