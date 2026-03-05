import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Clock, Zap } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface PkgItem {
    archive_id: number;
    archive_tag: string;
    archive_created_at: string;
    slug: string;
    meta: any;
}

interface TraceEvent {
    event_type: string;
    call_id?: string;
    doc_type?: string;
    phase?: string;
    attempt?: number;
    started_at?: string;
    ended_at?: string;
    duration_ms?: number;
    model?: string;
    endpoint?: string;
    max_tokens?: number;
    temperature?: number;
    system_prompt?: string;
    user_prompt?: string;
    raw_response?: string;
    response_chars?: number;
    response_parse_kind?: string;
    response_parse_status?: string;
    passed?: boolean;
    errors?: string[];
    status?: string;
}

interface TraceData {
    slug: string;
    meta: any;
    analysis: any;
    resume_strategy: any;
    cover_strategy: any;
    events: TraceEvent[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const STAGE_LABELS: Record<string, string> = {
    analysis: 'Analysis',
    resume_strategy: 'Resume · Strategy',
    resume_draft: 'Resume · Draft',
    resume_qa: 'Resume · QA',
    cover_strategy: 'Cover · Strategy',
    cover_draft: 'Cover · Draft',
    cover_qa: 'Cover · QA',
};

const STAGE_COLORS: Record<string, string> = {
    analysis: '#7c8cf8',
    resume: '#4ade80',
    cover: '#f59e0b',
};

function stageColor(docType: string) {
    return STAGE_COLORS[docType] || '#9ca3af';
}

function fmtMs(ms: number | undefined) {
    if (ms === undefined) return '';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

// Group start+success pairs into logical call records
function buildCallRecords(events: TraceEvent[]): Array<{
    callId: string | undefined;
    start: TraceEvent | null;
    success: TraceEvent | null;
    docType: string;
    stageKey: string;
    attempt: number;
}> {
    const byCallId = new Map<string, { start: TraceEvent | null; success: TraceEvent | null }>();
    const order: string[] = [];

    for (const ev of events) {
        if (ev.event_type === 'llm_call_start' || ev.event_type === 'llm_call_success') {
            const id = ev.call_id || `anon_${Math.random()}`;
            if (!byCallId.has(id)) {
                byCallId.set(id, { start: null, success: null });
                order.push(id);
            }
            const rec = byCallId.get(id)!;
            if (ev.event_type === 'llm_call_start') rec.start = ev;
            else rec.success = ev;
        }
    }

    return order.map(id => {
        const { start, success } = byCallId.get(id)!;
        const ev = success || start!;
        const docType = ev.doc_type || '';

        // Determine stage label by call order within doc_type
        const docCalls = order.filter(oid => {
            const { start: s, success: su } = byCallId.get(oid)!;
            return ((su || s)?.doc_type || '') === docType;
        });
        const posInDoc = docCalls.indexOf(id);
        const phases = ['strategy', 'draft', 'qa'];
        const inferredPhase = ev.phase || phases[posInDoc] || String(posInDoc);

        return {
            callId: ev.call_id,
            start,
            success,
            docType,
            stageKey: docType === 'analysis' ? 'analysis' : `${docType}_${inferredPhase}`,
            attempt: ev.attempt || 1,
        };
    });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function ExpandableText({ label, text, mono = true }: { label: string; text: string; mono?: boolean }) {
    const [open, setOpen] = useState(false);
    return (
        <div style={{ marginTop: '8px' }}>
            <button
                onClick={() => setOpen(o => !o)}
                style={{
                    background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                    display: 'flex', alignItems: 'center', gap: '4px',
                    color: 'var(--text-secondary)', fontSize: '.68rem', fontFamily: 'var(--font-mono)',
                }}
            >
                {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                {label} ({text.length.toLocaleString()} chars)
            </button>
            {open && (
                <pre style={{
                    marginTop: '6px', padding: '10px 12px',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: '4px', fontSize: '.67rem',
                    fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    maxHeight: '400px', overflowY: 'auto',
                    color: 'var(--text)',
                }}>
                    {text}
                </pre>
            )}
        </div>
    );
}

function ParsedJsonBlock({ label, text }: { label: string; text: string }) {
    const [open, setOpen] = useState(false);
    let pretty = text;
    try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { /* use raw */ }
    return (
        <div style={{ marginTop: '8px' }}>
            <button
                onClick={() => setOpen(o => !o)}
                style={{
                    background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                    display: 'flex', alignItems: 'center', gap: '4px',
                    color: 'var(--accent)', fontSize: '.68rem', fontFamily: 'var(--font-mono)',
                }}
            >
                {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                {label}
            </button>
            {open && (
                <pre style={{
                    marginTop: '6px', padding: '10px 12px',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: '4px', fontSize: '.67rem', fontFamily: 'var(--font-mono)',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    maxHeight: '500px', overflowY: 'auto', color: 'var(--text)',
                }}>
                    {pretty}
                </pre>
            )}
        </div>
    );
}

function CallCard({ rec, index }: { rec: ReturnType<typeof buildCallRecords>[0]; index: number }) {
    const [open, setOpen] = useState(false);
    const ev = rec.success || rec.start!;
    const label = STAGE_LABELS[rec.stageKey] || rec.stageKey;
    const color = stageColor(rec.docType);
    const ok = !!rec.success;
    const dur = rec.success?.duration_ms;
    const parseOk = rec.success?.response_parse_status === 'ok';
    const parseKind = rec.success?.response_parse_kind;

    return (
        <div style={{
            border: '1px solid var(--border)',
            borderLeft: `3px solid ${color}`,
            borderRadius: '4px',
            background: 'var(--surface)',
            overflow: 'hidden',
        }}>
            {/* Header row */}
            <div
                onClick={() => setOpen(o => !o)}
                style={{
                    padding: '10px 14px', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '10px',
                }}
            >
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.6rem', color: 'var(--text-secondary)',
                    minWidth: '18px', textAlign: 'right',
                }}>
                    {index + 1}
                </span>
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 600,
                    color, minWidth: '160px',
                }}>
                    {label}
                </span>
                {ev.attempt && ev.attempt > 1 && (
                    <span style={{
                        fontSize: '.6rem', fontFamily: 'var(--font-mono)',
                        background: 'var(--orange, #f59e0b)', color: '#000',
                        padding: '1px 5px', borderRadius: '3px',
                    }}>
                        retry #{ev.attempt}
                    </span>
                )}
                <span style={{ flex: 1 }} />
                {/* Parse status */}
                {parseKind && (
                    <span style={{
                        fontSize: '.62rem', fontFamily: 'var(--font-mono)',
                        color: parseOk ? 'var(--green)' : 'var(--red)',
                        display: 'flex', alignItems: 'center', gap: '3px',
                    }}>
                        {parseOk ? <CheckCircle size={10} /> : <XCircle size={10} />}
                        {parseKind}
                    </span>
                )}
                {/* Duration */}
                {dur !== undefined && (
                    <span style={{
                        fontSize: '.65rem', fontFamily: 'var(--font-mono)',
                        color: 'var(--text-secondary)',
                        display: 'flex', alignItems: 'center', gap: '3px', minWidth: '48px',
                    }}>
                        <Clock size={10} />
                        {fmtMs(dur)}
                    </span>
                )}
                {/* Tokens */}
                {ev.max_tokens && (
                    <span style={{
                        fontSize: '.62rem', fontFamily: 'var(--font-mono)',
                        color: 'var(--text-secondary)',
                    }}>
                        max {ev.max_tokens.toLocaleString()} tok
                    </span>
                )}
                {/* Model */}
                {ev.model && (
                    <span style={{
                        fontSize: '.62rem', fontFamily: 'var(--font-mono)',
                        color: 'var(--text-secondary)', maxWidth: '140px',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                        {ev.model.split('/').pop()}
                    </span>
                )}
                {ok
                    ? <CheckCircle size={13} style={{ color: 'var(--green)', flexShrink: 0 }} />
                    : <XCircle size={13} style={{ color: 'var(--red)', flexShrink: 0 }} />
                }
                {open ? <ChevronDown size={13} style={{ flexShrink: 0 }} /> : <ChevronRight size={13} style={{ flexShrink: 0 }} />}
            </div>

            {/* Expanded body */}
            {open && (
                <div style={{
                    borderTop: '1px solid var(--border)',
                    padding: '14px 16px', background: 'var(--surface-2)',
                }}>
                    {/* Meta row */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
                        gap: '8px', marginBottom: '12px',
                    }}>
                        {[
                            ['Model', ev.model],
                            ['Endpoint', ev.endpoint],
                            ['Temperature', ev.temperature],
                            ['Max tokens', ev.max_tokens],
                            ['Duration', fmtMs(dur)],
                            ['Response chars', rec.success?.response_chars?.toLocaleString()],
                            ['Parse kind', parseKind],
                            ['Parse status', rec.success?.response_parse_status],
                        ].filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => (
                            <div key={String(k)} style={{ fontSize: '.67rem', fontFamily: 'var(--font-mono)' }}>
                                <span style={{ color: 'var(--text-secondary)' }}>{k}: </span>
                                <span style={{ color: 'var(--text)' }}>{String(v)}</span>
                            </div>
                        ))}
                    </div>

                    {/* System prompt */}
                    {(ev.system_prompt) && (
                        <ExpandableText label="system_prompt" text={ev.system_prompt} />
                    )}

                    {/* User prompt */}
                    {(ev.user_prompt) && (
                        <ExpandableText label="user_prompt" text={ev.user_prompt} />
                    )}

                    {/* Response */}
                    {rec.success?.raw_response && (() => {
                        const resp = rec.success.raw_response;
                        // Try to detect if it's JSON or LaTeX
                        const isJson = parseKind === 'json' || resp.trim().startsWith('{') || resp.trim().startsWith('[');
                        return isJson
                            ? <ParsedJsonBlock label="response (JSON)" text={resp} />
                            : <ExpandableText label="response (LaTeX)" text={resp} />;
                    })()}
                </div>
            )}
        </div>
    );
}

function ValidationCard({ ev }: { ev: TraceEvent }) {
    const label = ev.doc_type === 'resume' ? 'Resume · Validation' : 'Cover · Validation';
    const color = stageColor(ev.doc_type || '');
    return (
        <div style={{
            border: `1px solid ${ev.passed ? 'var(--green)' : 'var(--red)'}`,
            borderLeft: `3px solid ${color}`,
            borderRadius: '4px',
            padding: '8px 14px',
            background: 'var(--surface)',
            display: 'flex', alignItems: 'flex-start', gap: '10px',
        }}>
            {ev.passed
                ? <CheckCircle size={14} style={{ color: 'var(--green)', flexShrink: 0, marginTop: '1px' }} />
                : <XCircle size={14} style={{ color: 'var(--red)', flexShrink: 0, marginTop: '1px' }} />
            }
            <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', fontWeight: 600, color }}>
                    {label}
                    <span style={{
                        marginLeft: '8px', fontWeight: 400,
                        color: ev.passed ? 'var(--green)' : 'var(--red)',
                    }}>
                        {ev.passed ? 'PASSED' : 'FAILED'}
                    </span>
                </div>
                {ev.errors && ev.errors.length > 0 && (
                    <ul style={{
                        margin: '6px 0 0', padding: '0 0 0 16px',
                        fontSize: '.68rem', fontFamily: 'var(--font-mono)', color: 'var(--red)',
                    }}>
                        {ev.errors.map((e, i) => <li key={i}>{e}</li>)}
                    </ul>
                )}
            </div>
        </div>
    );
}

function DocAttemptCard({ ev }: { ev: TraceEvent }) {
    const label = ev.doc_type === 'resume' ? 'Resume · Final' : 'Cover · Final';
    const color = stageColor(ev.doc_type || '');
    const ok = ev.status === 'passed';
    return (
        <div style={{
            border: `1px solid ${ok ? 'var(--green)' : 'var(--red)'}`,
            borderLeft: `3px solid ${color}`,
            borderRadius: '4px',
            padding: '8px 14px',
            background: ok ? 'rgba(74,222,128,.06)' : 'rgba(248,113,113,.06)',
            display: 'flex', alignItems: 'center', gap: '10px',
        }}>
            {ok
                ? <Zap size={14} style={{ color: 'var(--green)', flexShrink: 0 }} />
                : <XCircle size={14} style={{ color: 'var(--red)', flexShrink: 0 }} />
            }
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', fontWeight: 600, color }}>
                {label}
            </span>
            <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '.7rem',
                color: ok ? 'var(--green)' : 'var(--red)',
            }}>
                {(ev.status || '').toUpperCase()}
            </span>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Summary stats bar
// ---------------------------------------------------------------------------
function PipelineSummary({ trace }: { trace: TraceData }) {
    const calls = trace.events.filter(e => e.event_type === 'llm_call_success');
    const totalMs = calls.reduce((s, e) => s + (e.duration_ms || 0), 0);
    const totalChars = calls.reduce((s, e) => s + (e.response_chars || 0), 0);
    const validations = trace.events.filter(e => e.event_type === 'validation_result');
    const allPassed = validations.every(v => v.passed);
    const model = calls[0]?.model || '';

    return (
        <div style={{
            display: 'flex', gap: '0', marginBottom: '20px',
            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            overflow: 'hidden', background: 'var(--surface)',
        }}>
            {[
                ['LLM calls', calls.length],
                ['Total time', fmtMs(totalMs)],
                ['Response chars', totalChars.toLocaleString()],
                ['Validation', allPassed ? 'PASS' : 'FAIL'],
                ['Model', model.split('/').slice(-1)[0] || '—'],
            ].map(([label, value], i) => (
                <div key={i} style={{
                    flex: 1, padding: '10px 14px',
                    borderRight: i < 4 ? '1px solid var(--border)' : 'none',
                }}>
                    <div style={{
                        fontSize: '.6rem', fontFamily: 'var(--font-mono)',
                        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
                        marginBottom: '4px',
                    }}>
                        {label}
                    </div>
                    <div style={{
                        fontSize: '.88rem', fontWeight: 600, fontFamily: 'var(--font-mono)',
                        color: label === 'Validation'
                            ? (allPassed ? 'var(--green)' : 'var(--red)')
                            : 'var(--text)',
                    }}>
                        {String(value)}
                    </div>
                </div>
            ))}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Structured output cards
// ---------------------------------------------------------------------------
function StructuredOutputs({ trace }: { trace: TraceData }) {
    const [open, setOpen] = useState<Record<string, boolean>>({});
    const sections = [
        { key: 'analysis', label: 'Analysis Output', data: trace.analysis },
        { key: 'resume_strategy', label: 'Resume Strategy', data: trace.resume_strategy },
        { key: 'cover_strategy', label: 'Cover Strategy', data: trace.cover_strategy },
    ].filter(s => s.data);

    if (!sections.length) return null;

    return (
        <div style={{ marginBottom: '24px' }}>
            <div style={{
                fontSize: '.62rem', fontFamily: 'var(--font-mono)', fontWeight: 600,
                color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em',
                marginBottom: '8px',
            }}>
                Structured Outputs
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {sections.map(({ key, label, data }) => (
                    <div key={key} style={{
                        border: '1px solid var(--border)', borderRadius: '4px',
                        background: 'var(--surface)', overflow: 'hidden',
                    }}>
                        <div
                            onClick={() => setOpen(p => ({ ...p, [key]: !p[key] }))}
                            style={{
                                padding: '8px 12px', cursor: 'pointer',
                                display: 'flex', alignItems: 'center', gap: '8px',
                            }}
                        >
                            {open[key] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', fontWeight: 600 }}>
                                {label}
                            </span>
                        </div>
                        {open[key] && (
                            <pre style={{
                                borderTop: '1px solid var(--border)',
                                margin: 0, padding: '12px 14px',
                                fontSize: '.67rem', fontFamily: 'var(--font-mono)',
                                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                maxHeight: '500px', overflowY: 'auto',
                                background: 'var(--surface-2)', color: 'var(--text)',
                            }}>
                                {JSON.stringify(data, null, 2)}
                            </pre>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------
export default function PipelineView() {
    const [packages, setPackages] = useState<PkgItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('');
    const [selected, setSelected] = useState<PkgItem | null>(null);
    const [trace, setTrace] = useState<TraceData | null>(null);
    const [traceLoading, setTraceLoading] = useState(false);
    const filterRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        api.getPipelinePackages()
            .then(setPackages)
            .catch(() => {})
            .finally(() => setLoading(false));
    }, []);

    const selectPackage = useCallback(async (pkg: PkgItem) => {
        setSelected(pkg);
        setTrace(null);
        setTraceLoading(true);
        try {
            setTrace(await api.getPipelineTrace(pkg.archive_id, pkg.slug));
        } catch { /* ignore */ }
        setTraceLoading(false);
    }, []);

    const filtered = packages.filter(p => {
        if (!filter) return true;
        const q = filter.toLowerCase();
        return (
            p.slug.toLowerCase().includes(q) ||
            (p.meta?.job_title || '').toLowerCase().includes(q) ||
            (p.meta?.company || p.meta?.company_name || '').toLowerCase().includes(q) ||
            p.archive_tag.toLowerCase().includes(q)
        );
    });

    // Build pipeline timeline from trace events
    const callRecords = trace ? buildCallRecords(trace.events) : [];
    const validationEvents = trace ? trace.events.filter(e => e.event_type === 'validation_result') : [];
    const docAttemptEvents = trace ? trace.events.filter(e => e.event_type === 'doc_attempt_result') : [];

    // Interleave call records with their validation/attempt results by doc_type
    // Group into: analysis, resume pipeline, cover pipeline
    const analysisCalls = callRecords.filter(r => r.docType === 'analysis');
    const resumeCalls = callRecords.filter(r => r.docType === 'resume');
    const coverCalls = callRecords.filter(r => r.docType === 'cover');
    const resumeValidation = validationEvents.filter(e => e.doc_type === 'resume');
    const coverValidation = validationEvents.filter(e => e.doc_type === 'cover');
    const resumeAttempt = docAttemptEvents.filter(e => e.doc_type === 'resume');
    const coverAttempt = docAttemptEvents.filter(e => e.doc_type === 'cover');

    return (
        <PageView>
            <PageHeader title="Pipeline Inspector" subtitle="TAILORING LLM CALL TRACE" />
            <PagePrimary>
                <div style={{ display: 'flex', gap: '0', height: 'calc(100vh - 120px)', overflow: 'hidden' }}>

                    {/* ---- Left: package list ---- */}
                    <div style={{
                        width: '280px', flexShrink: 0,
                        borderRight: '1px solid var(--border)',
                        display: 'flex', flexDirection: 'column', overflow: 'hidden',
                    }}>
                        <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
                            <input
                                ref={filterRef}
                                value={filter}
                                onChange={e => setFilter(e.target.value)}
                                placeholder="filter packages..."
                                style={{
                                    width: '100%', boxSizing: 'border-box',
                                    background: 'var(--surface)', border: '1px solid var(--border)',
                                    borderRadius: '4px', padding: '5px 8px',
                                    fontSize: '.72rem', fontFamily: 'var(--font-mono)',
                                    color: 'var(--text)', outline: 'none',
                                }}
                            />
                        </div>
                        <div style={{ overflowY: 'auto', flex: 1 }}>
                            {loading ? (
                                <div style={{ padding: '16px 12px', fontSize: '.75rem', color: 'var(--text-secondary)' }}>
                                    Loading...
                                </div>
                            ) : filtered.length === 0 ? (
                                <div style={{ padding: '16px 12px', fontSize: '.75rem', color: 'var(--text-secondary)' }}>
                                    No packages
                                </div>
                            ) : filtered.map((p) => {
                                const isSel = selected?.slug === p.slug && selected?.archive_id === p.archive_id;
                                const title = p.meta?.job_title || p.meta?.title || p.slug;
                                const company = p.meta?.company || p.meta?.company_name || '';
                                return (
                                    <div
                                        key={`${p.archive_id}_${p.slug}`}
                                        onClick={() => selectPackage(p)}
                                        style={{
                                            padding: '9px 12px',
                                            borderBottom: '1px solid var(--border)',
                                            cursor: 'pointer',
                                            background: isSel ? 'var(--accent-light, rgba(99,102,241,.12))' : 'transparent',
                                            borderLeft: isSel ? '2px solid var(--accent)' : '2px solid transparent',
                                        }}
                                    >
                                        <div style={{
                                            fontSize: '.72rem', fontWeight: 600,
                                            color: isSel ? 'var(--text)' : 'var(--text)',
                                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                        }}>
                                            {title}
                                        </div>
                                        {company && (
                                            <div style={{
                                                fontSize: '.63rem', color: 'var(--text-secondary)',
                                                fontFamily: 'var(--font-mono)', marginTop: '2px',
                                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                            }}>
                                                {company}
                                            </div>
                                        )}
                                        <div style={{
                                            fontSize: '.6rem', color: 'var(--text-secondary)',
                                            fontFamily: 'var(--font-mono)', marginTop: '3px',
                                        }}>
                                            {p.archive_tag}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {/* ---- Right: trace detail ---- */}
                    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
                        {!selected && (
                            <div style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                height: '200px', color: 'var(--text-secondary)', fontSize: '.85rem',
                                fontFamily: 'var(--font-mono)',
                            }}>
                                Select a package to inspect its pipeline
                            </div>
                        )}

                        {selected && traceLoading && (
                            <div style={{ color: 'var(--text-secondary)', fontSize: '.85rem', fontFamily: 'var(--font-mono)' }}>
                                Loading trace...
                            </div>
                        )}

                        {selected && trace && !traceLoading && (
                            <>
                                {/* Header */}
                                <div style={{ marginBottom: '16px' }}>
                                    <div style={{ fontWeight: 700, fontSize: '1rem', marginBottom: '4px' }}>
                                        {trace.meta?.job_title || trace.meta?.title || trace.slug}
                                    </div>
                                    <div style={{
                                        fontSize: '.72rem', fontFamily: 'var(--font-mono)',
                                        color: 'var(--text-secondary)',
                                    }}>
                                        {trace.meta?.company || trace.meta?.company_name || ''}
                                        {trace.meta?.url && (
                                            <a
                                                href={trace.meta.url}
                                                target="_blank"
                                                rel="noreferrer"
                                                style={{ marginLeft: '10px', color: 'var(--accent)' }}
                                            >
                                                {trace.meta.url}
                                            </a>
                                        )}
                                    </div>
                                    <div style={{
                                        fontSize: '.63rem', fontFamily: 'var(--font-mono)',
                                        color: 'var(--text-secondary)', marginTop: '4px',
                                    }}>
                                        archive: {selected.archive_tag} · slug: {trace.slug}
                                    </div>
                                </div>

                                {/* Summary bar */}
                                <PipelineSummary trace={trace} />

                                {/* Structured outputs */}
                                <StructuredOutputs trace={trace} />

                                {/* ---- Pipeline stages ---- */}

                                {/* Phase header helper */}
                                {(['ANALYSIS', 'RESUME PIPELINE', 'COVER PIPELINE'] as const).map((phase, pi) => {
                                    const calls = [analysisCalls, resumeCalls, coverCalls][pi];
                                    const validations = [[], resumeValidation, coverValidation][pi];
                                    const attempts = [[], resumeAttempt, coverAttempt][pi];
                                    if (!calls.length && !validations.length) return null;
                                    const phaseColor = [STAGE_COLORS.analysis, STAGE_COLORS.resume, STAGE_COLORS.cover][pi];

                                    return (
                                        <div key={phase} style={{ marginBottom: '24px' }}>
                                            <div style={{
                                                fontSize: '.6rem', fontFamily: 'var(--font-mono)', fontWeight: 700,
                                                color: phaseColor, textTransform: 'uppercase', letterSpacing: '.12em',
                                                marginBottom: '8px',
                                                paddingBottom: '4px', borderBottom: `1px solid ${phaseColor}33`,
                                            }}>
                                                {phase}
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                {calls.map((rec, i) => (
                                                    <CallCard key={rec.callId || i} rec={rec} index={i} />
                                                ))}
                                                {validations.map((ev, i) => (
                                                    <ValidationCard key={`v_${i}`} ev={ev} />
                                                ))}
                                                {attempts.map((ev, i) => (
                                                    <DocAttemptCard key={`a_${i}`} ev={ev} />
                                                ))}
                                            </div>
                                        </div>
                                    );
                                })}
                            </>
                        )}
                    </div>
                </div>
            </PagePrimary>
        </PageView>
    );
}
