import React from 'react';

// ─── Trace grouping ───

export function groupTraceEvents(events: any[]) {
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
}

// ─── Helpers ───

const fmtDuration = (ms: number | null | undefined) => ms == null ? '' : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;

// ─── Sub-components ───

export function SectionLabel({ children }: { children: React.ReactNode }) {
    return (
        <div style={{
            fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
            color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em',
            padding: '8px 10px 4px',
        }}>{children}</div>
    );
}

interface StageRowProps {
    label: string;
    ev: any;
    isValidation?: boolean;
    indent?: boolean;
    selectedEvent: any;
    artifactView: any;
    onSelect: (ev: any) => void;
}

export function StageRow({ label, ev, isValidation, indent, selectedEvent, artifactView, onSelect }: StageRowProps) {
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
            onClick={isValidation ? undefined : () => onSelect(ev)}
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
}

// ─── Artifact Viewer ───

interface ArtifactViewerProps {
    artifact: { name: string; content: string; isPdf: boolean };
    onClose: () => void;
}

export function ArtifactViewer({ artifact, onClose }: ArtifactViewerProps) {
    if (artifact.isPdf) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 600 }}>{artifact.name}</span>
                    <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={onClose}>Close</button>
                </div>
                <iframe src={artifact.content} style={{ flex: 1, border: 'none', minHeight: '600px', background: '#fff' }} />
            </div>
        );
    }
    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 600 }}>{artifact.name}</span>
                <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}
                    onClick={() => { navigator.clipboard.writeText(artifact.content).catch(() => { }); }}>
                    Copy
                </button>
                <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '12px' }}>
                <pre style={{ fontFamily: 'var(--font-mono)', fontSize: '.76rem', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text)' }}>
                    {artifact.content}
                </pre>
            </div>
        </div>
    );
}

// ─── Trace Inspector ───

interface TraceInspectorProps {
    event: any;
    traceTab: 'overview' | 'system' | 'user' | 'response' | 'raw';
    setTraceTab: (tab: 'overview' | 'system' | 'user' | 'response' | 'raw') => void;
}

export function TraceInspector({ event, traceTab, setTraceTab }: TraceInspectorProps) {
    const isSuccess = event.event_type === 'llm_call_success' || event.passed === true || event.status === 'passed';
    const isError = event.event_type === 'llm_call_error' || event.passed === false || event.status === 'failed' || event.status === 'error';

    const diagnostics: string[] = [];
    if (event.event_type === 'llm_call_error') diagnostics.push('Request failed before a usable response was produced.');
    if (event.event_type === 'llm_call_success' && !event.raw_response) diagnostics.push('Call succeeded but response body is empty.');
    if (event.response_parse_status === 'failed') diagnostics.push('Response parse failed. The model returned text that did not match expected format.');
    if (event.passed === false) diagnostics.push('Validation failed. See failure list for violated gates.');
    if (event.attempt && Number(event.attempt) > 1) diagnostics.push(`Retry attempt #${event.attempt}. Earlier attempt(s) failed.`);
    if (diagnostics.length === 0 && isSuccess) diagnostics.push('Event looks healthy.');

    const requestSummary = [
        `event=${event.event_type || '--'}`,
        `doc=${event.doc_type || '--'}`,
        `phase=${event.phase || '--'}`,
        `attempt=${event.attempt ?? '--'}`,
        `model=${event.model || '--'}`,
        `duration_ms=${event.duration_ms ?? '--'}`,
        `parse=${event.response_parse_kind || '--'}/${event.response_parse_status || '--'}`,
    ].join('\n');

    const healthChecks = [
        { label: 'Prompt', ok: Boolean(event.system_prompt || event.user_prompt), desc: 'System/user prompt captured for this event.' },
        { label: 'Response', ok: event.event_type === 'llm_call_success' ? Boolean(event.raw_response) : event.event_type !== 'llm_call_error', desc: 'Response text captured from model call.' },
        { label: 'Parse', ok: (event.response_parse_status || 'skipped') !== 'failed', desc: 'Response parser accepted expected format.' },
        { label: 'Validation', ok: event.passed !== false, desc: 'Final hard-gate validation passed for this attempt.' },
    ];

    const tabContent = () => {
        if (traceTab === 'overview') return '';
        if (traceTab === 'system') return event.system_prompt || '(empty)';
        if (traceTab === 'user') return event.user_prompt || '(empty)';
        if (traceTab === 'response') return event.raw_response || event.error || '(empty)';
        return JSON.stringify(event, null, 2);
    };

    const truncate = (s: string | undefined | null, max: number) => {
        if (!s) return null;
        return s.length > max ? s.slice(0, max) + '\n... (' + (s.length - max) + ' chars truncated)' : s;
    };

    const startRaw = event.started_at || event.timestamp;
    const endRaw = event.ended_at;
    const startDate = startRaw ? new Date(startRaw) : null;
    const endDate = endRaw ? new Date(endRaw) : null;
    const fmtTime = (d: Date | null) => d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--';
    const parseOk = (event.response_parse_status || 'skipped') !== 'failed';
    const valOk = event.passed !== false;

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
                            onClick={() => navigator.clipboard.writeText(event.error || 'No error for this event').catch(() => { })}>
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
                        <div className="trace-timeline">
                            {/* Step 1: Call Initiated */}
                            <div className="trace-tl-step">
                                <div className="trace-tl-rail">
                                    <div className="trace-tl-dot trace-tl-dot--neutral" />
                                    <div className="trace-tl-line" />
                                </div>
                                <div className="trace-tl-body">
                                    <div className="trace-tl-head">
                                        <span className="trace-tl-time">{fmtTime(startDate)}</span>
                                        <span className="trace-tl-label">Call initiated</span>
                                        <span className="trace-tl-tag">{(event.doc_type || '--').toUpperCase()} / {(event.phase || '--').toUpperCase()} / ATT {event.attempt ?? 1}</span>
                                    </div>
                                    <div className="trace-tl-meta">
                                        <span>{event.model || '--'}</span>
                                        <span>temp={event.temperature ?? '--'}</span>
                                        <span>max_tok={event.max_tokens ?? '--'}</span>
                                        {event.endpoint && <span className="trace-tl-endpoint">{event.endpoint}</span>}
                                    </div>
                                    {event.system_prompt && (
                                        <div className="trace-tl-block">
                                            <div className="trace-tl-block-label">System prompt</div>
                                            <pre className="trace-tl-pre">{truncate(event.system_prompt, 3000)}</pre>
                                        </div>
                                    )}
                                    {event.user_prompt && (
                                        <div className="trace-tl-block">
                                            <div className="trace-tl-block-label">User prompt</div>
                                            <pre className="trace-tl-pre">{truncate(event.user_prompt, 3000)}</pre>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Step 2: Response / Error */}
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
                                        {!isError && event.duration_ms != null && (
                                            <span className="trace-tl-tag">{fmtDuration(event.duration_ms)} &middot; {event.response_chars ?? '--'} chars</span>
                                        )}
                                    </div>
                                    {isError && event.error ? (
                                        <div className="trace-tl-block trace-tl-block--err">
                                            <div className="trace-tl-block-label">Error</div>
                                            <pre className="trace-tl-pre">{event.error}</pre>
                                        </div>
                                    ) : event.raw_response ? (
                                        <div className="trace-tl-block">
                                            <div className="trace-tl-block-label">Raw response</div>
                                            <pre className="trace-tl-pre">{truncate(event.raw_response, 4000)}</pre>
                                        </div>
                                    ) : (
                                        <div className="trace-tl-detail">No response body captured.</div>
                                    )}
                                </div>
                            </div>

                            {/* Step 3: Parse */}
                            {!isError && (
                                <div className="trace-tl-step">
                                    <div className="trace-tl-rail">
                                        <div className={`trace-tl-dot trace-tl-dot--${parseOk ? 'ok' : 'err'}`} />
                                        {event.passed != null && <div className="trace-tl-line" />}
                                    </div>
                                    <div className="trace-tl-body">
                                        <div className="trace-tl-head">
                                            <span className="trace-tl-time" />
                                            <span className={`trace-tl-label trace-tl-label--${parseOk ? 'ok' : 'err'}`}>
                                                Parse &amp; extract
                                            </span>
                                            <span className="trace-tl-tag">{event.response_parse_kind || '--'} parser &rarr; {event.response_parse_status || '--'}</span>
                                        </div>
                                        {!parseOk && (
                                            <div className="trace-tl-sub trace-tl-sub--err">
                                                Model output did not match expected JSON/LaTeX shape for this step.
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Step 4: Validation */}
                            {event.passed != null && (
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
                                        {!valOk && Array.isArray(event.failures) && event.failures.length > 0 && (
                                            <div className="trace-tl-block trace-tl-block--err">
                                                <div className="trace-tl-block-label">Failures</div>
                                                {event.failures.map((f: string, i: number) => (
                                                    <div key={i} className="trace-tl-sub trace-tl-sub--err">{f}</div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Context footer */}
                        <div className="trace-tl-footer">
                            <span>Call ID: {event.call_id || '--'}</span>
                            <span>Run: {event.run_slug || '--'}</span>
                            <span>Job {event.job_id ?? '--'}: {event.job_title || '--'}</span>
                        </div>
                    </div>
                ) : (
                    <pre>{tabContent()}</pre>
                )}
            </div>
        </div>
    );
}
