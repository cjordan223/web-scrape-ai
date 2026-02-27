import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';
import VerdictChips from '../../../../components/VerdictChips';
import { PageHeader, PagePrimary, PageSecondary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { EmptyState, LoadingState } from '../../../../components/workflow/States';
import { ActionBar } from '../../../../components/workflow/ActionBar';
import { LogPanel } from '../../../../components/workflow/LogPanel';

export default function TailoringView() {
    const navigate = useNavigate();
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [activeTrace, setActiveTrace] = useState<any>(null);
    // Pipeline trace state
    const [selectedDocTab, setSelectedDocTab] = useState<'analysis' | 'resume' | 'cover'>('analysis');
    const [selectedEvent, setSelectedEvent] = useState<any>(null);
    const [traceTab, setTraceTab] = useState<'system' | 'user' | 'response' | 'meta'>('meta');

    // New state for Manual Tailoring Header
    const [recentJobs, setRecentJobs] = useState<any[]>([]);
    const [runConfig, setRunConfig] = useState({ selected_job_id: 0, skip_analysis: false });
    const [runner, setRunner] = useState<any>({ running: false, log_tail: '' });
    const [runBusy, setRunBusy] = useState(false);
    const [runError, setRunError] = useState('');
    const [runNotice, setRunNotice] = useState('');
    const [selectedJobDetail, setSelectedJobDetail] = useState<any>(null);
    const [selectedJobDetailLoading, setSelectedJobDetailLoading] = useState(false);

    const fetchRuns = useCallback(async () => {
        try {
            const res = await api.getTailoring();
            setData(res);
            if (res.length > 0 && !activeSlug) {
                setActiveSlug(res[0].slug);
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
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
                setRunError(res.error || 'Failed to start run');
                if (res.runner) setRunner(res.runner);
                return;
            }
            if (res.runner) setRunner(res.runner);
            fetchRuns();
        } catch (err) {
            console.error(err);
            setRunError('Failed to start run');
        } finally {
            setRunBusy(false);
        }
    };

    const fetchSelectedJobDetail = async () => {
        if (!runConfig.selected_job_id) {
            setSelectedJobDetail(null);
            return;
        }
        setSelectedJobDetailLoading(true);
        setSelectedJobDetail(null);
        try {
            const res = await api.getJobDetail(runConfig.selected_job_id);
            setSelectedJobDetail(res);
        } catch (err) {
            console.error(err);
        } finally {
            setSelectedJobDetailLoading(false);
        }
    };

    // Auto-fetch job details when dropdown selection changes
    useEffect(() => {
        fetchSelectedJobDetail();
    }, [runConfig.selected_job_id]);

    const copyLogs = async () => {
        if (!runner?.log_tail) return;
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(runner.log_tail);
                setRunNotice('Logs copied');
                return;
            }
            // Fallback for non-secure LAN HTTP contexts.
            const ta = document.createElement('textarea');
            ta.value = runner.log_tail;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            if (ok) setRunNotice('Logs copied');
            else setRunError('Copy failed');
        } catch {
            setRunError('Copy failed');
        }
    };

    const refreshAll = async () => {
        setRunError('');
        setRunNotice('');
        await Promise.all([
            fetchRuns(),
            fetchRunnerStatus(),
            fetchRecentJobs(),
            fetchSelectedJobDetail(),
            activeSlug ? api.getTailoringDetail(activeSlug).then(setActiveTrace).catch(() => {}) : Promise.resolve(),
        ]);
        setRunNotice('Refreshed');
    };

    const jobOptionLabel = (job: any) => {
        const title = (job?.title || '').replace(/\s+/g, ' ').trim();
        return `${job?.id ?? '—'} · ${title || 'Untitled job'} (${timeAgo(job?.created_at)})`;
    };

    useEffect(() => {
        fetchRuns();
        fetchRecentJobs();
        fetchRunnerStatus();

        const i1 = setInterval(fetchRuns, 30000);
        const i2 = setInterval(fetchRunnerStatus, 10000);
        return () => { clearInterval(i1); clearInterval(i2); };
    }, [fetchRuns]);

    useEffect(() => {
        const fetchTrace = async () => {
            if (!activeSlug) return;
            try {
                const res = await api.getTailoringDetail(activeSlug);
                setActiveTrace(res);
            } catch (err) {
                console.error(err);
                setActiveTrace(null);
            }
        };
        fetchTrace();
    }, [activeSlug]);

    const traces = activeTrace?.events || [];

    // Group trace events into pipeline structure
    const groupTraceEvents = (events: any[]) => {
        const analysis: any = { llm: null };
        const resume: Record<number, any> = {};
        const cover: Record<number, any> = {};

        for (const ev of events) {
            const attempt = ev.attempt ?? 1;
            const isLlm = ev.event_type === 'llm_call_success' || ev.event_type === 'llm_call_error';
            const isVal = ev.event_type === 'validation_result';

            if (ev.doc_type === 'analysis') {
                if (isLlm && (!analysis.llm || ev.event_type === 'llm_call_success')) {
                    analysis.llm = ev;
                }
            } else if (ev.doc_type === 'resume') {
                if (!resume[attempt]) resume[attempt] = { strategy: null, draft: null, qa: null, validation: null };
                if (isVal) { resume[attempt].validation = ev; }
                else if (isLlm) {
                    const slot = ev.phase as 'strategy' | 'draft' | 'qa';
                    if (slot && (!resume[attempt][slot] || ev.event_type === 'llm_call_success')) {
                        resume[attempt][slot] = ev;
                    }
                }
            } else if (ev.doc_type === 'cover') {
                if (!cover[attempt]) cover[attempt] = { strategy: null, draft: null, qa: null, validation: null };
                if (isVal) { cover[attempt].validation = ev; }
                else if (isLlm) {
                    const slot = ev.phase as 'strategy' | 'draft' | 'qa';
                    if (slot && (!cover[attempt][slot] || ev.event_type === 'llm_call_success')) {
                        cover[attempt][slot] = ev;
                    }
                }
            }
        }

        return { analysis, resume, cover };
    };

    const grouped = groupTraceEvents(traces);

    const fmtDuration = (ms: number | null | undefined) => {
        if (ms == null) return '';
        return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
    };

    const StageRow = ({ label, ev, isValidation }: { label: string; ev: any; isValidation?: boolean }) => {
        if (!ev) {
            return (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 8px', color: 'var(--text-secondary)', fontSize: '.85rem' }}>
                    <span style={{ minWidth: '80px', color: 'var(--text-secondary)' }}>{label}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>·</span>
                    <span style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>—</span>
                </div>
            );
        }
        const success = isValidation
            ? ev.passed !== false
            : ev.event_type === 'llm_call_success';
        const statusColor = success ? '#22c55e' : '#ef4444';
        const statusIcon = success ? '✓' : '✗';
        const failures = !isValidation ? null : (ev.failures || []);

        return (
            <div
                className={selectedEvent === ev ? 'trace-item active' : 'trace-item'}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 8px', cursor: isValidation ? 'default' : 'pointer', borderRadius: '4px' }}
                onClick={isValidation ? undefined : () => { setSelectedEvent(ev); }}
            >
                <span style={{ minWidth: '80px', fontSize: '.85rem', fontWeight: 500 }}>{label}</span>
                <span style={{ color: statusColor, fontWeight: 700, fontSize: '1rem', lineHeight: 1 }}>{statusIcon}</span>
                {!isValidation && ev.duration_ms != null && (
                    <span style={{ fontSize: '.78rem', color: 'var(--text-secondary)' }}>{fmtDuration(ev.duration_ms)}</span>
                )}
                {failures && failures.length > 0 && (
                    <span style={{ fontSize: '.78rem', color: '#ef4444' }}>{failures.join(', ')}</span>
                )}
                {!isValidation && (
                    <button
                        className="btn btn-ghost btn-sm"
                        style={{ marginLeft: 'auto', fontSize: '.75rem', padding: '2px 8px' }}
                        onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}
                    >
                        view
                    </button>
                )}
            </div>
        );
    };

    const AttemptGroup = ({ attempt, slots, isRetry }: { attempt: number; slots: any; isRetry: boolean }) => (
        <div style={{ border: '1px solid var(--border)', borderRadius: '6px', marginBottom: '10px' }}>
            <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)', fontSize: '.8rem', fontWeight: 600, color: 'var(--text-secondary)', background: 'var(--surface-2)', borderRadius: '6px 6px 0 0' }}>
                Attempt {attempt}{isRetry ? ' (retry)' : ''}
            </div>
            <div style={{ padding: '4px 4px' }}>
                <StageRow label="Strategy" ev={slots.strategy} />
                <StageRow label="Draft" ev={slots.draft} />
                <StageRow label="QA" ev={slots.qa} />
                <StageRow label="Validate" ev={slots.validation} isValidation />
            </div>
        </div>
    );

    const copyTracePane = () => {
        let text = '';
        if (traceTab === 'system') text = selectedEvent?.system_prompt || '';
        else if (traceTab === 'user') text = selectedEvent?.user_prompt || '';
        else if (traceTab === 'response') text = selectedEvent?.raw_response || selectedEvent?.error || '';
        else text = JSON.stringify(selectedEvent || {}, null, 2);
        navigator.clipboard.writeText(text).catch(() => {});
    };

    return (
        <PageView>
            <PageHeader
                title="Tailoring Transparency"
                right={
                    <ActionBar style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                    <select
                        value={runConfig.selected_job_id}
                        onChange={(e) => setRunConfig({ ...runConfig, selected_job_id: Number(e.target.value) })}
                        style={{ minWidth: '460px', maxWidth: '620px', padding: '6px 10px', border: '1px solid var(--border)', borderRadius: '6px' }}
                    >
                        <option value={0}>Select a job to run...</option>
                        {recentJobs.map((j: any) => (
                            <option key={`tj-${j.id}`} value={j.id}>{jobOptionLabel(j)}</option>
                        ))}
                    </select>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '.82rem', color: 'var(--text-secondary)' }}>
                        <input type="checkbox" checked={runConfig.skip_analysis} onChange={(e) => setRunConfig({ ...runConfig, skip_analysis: e.target.checked })} />
                        <span>Skip analysis</span>
                    </label>
                    <button className="btn btn-success btn-sm" disabled={runBusy || runner.running || !runConfig.selected_job_id} onClick={runSelectedJob}>
                        {runBusy ? 'Starting...' : (runner.running ? 'Run in progress' : 'Run Selected Job')}
                    </button>
                    <button className="btn btn-ghost btn-sm" disabled={!runner.log_tail} onClick={copyLogs}>
                        Copy Logs
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={refreshAll}>Refresh</button>
                </ActionBar>
                }
            />
            <PagePrimary>
            <div className="stats-bar" style={{ marginBottom: '10px' }}>
                <span>
                    Runner: <strong style={{ color: 'var(--text)' }}>{runner.running ? 'running' : 'idle'}</strong>
                </span>
                {runner.job && (
                    <span>
                        Job: <strong style={{ color: 'var(--text)' }}>{(runner.job?.id ?? '—')} &middot; {(runner.job?.title ?? '')}</strong>
                    </span>
                )}
                {runner.started_at && (
                    <span>
                        Started: <strong style={{ color: 'var(--text)' }}>{timeAgo(runner.started_at)}</strong>
                    </span>
                )}
                {!runner.running && runner.exit_code != null && (
                    <span>
                        Exit: <strong style={{ color: 'var(--text)' }}>{runner.exit_code}</strong>
                    </span>
                )}
                {runError && (
                    <span style={{ color: '#ef4444' }}>{runError}</span>
                )}
                {!runError && runNotice && (
                    <span style={{ color: 'var(--text-secondary)' }}>{runNotice}</span>
                )}
            </div>

            {runner.log_tail && (
                <LogPanel text={runner.log_tail} style={{ maxHeight: '160px', overflow: 'auto', marginBottom: '10px', background: '#0b1220', color: '#9fb3c8', padding: '10px', borderRadius: '8px', fontSize: '11px', whiteSpace: 'pre-wrap', fontFamily: 'monospace' }} />
            )}

            {(selectedJobDetail !== null || selectedJobDetailLoading) && (
                <WorkflowPanel title="Selected job">
                    {selectedJobDetailLoading ? (
                        <LoadingState style={{ padding: '16px' }} />
                    ) : selectedJobDetail ? (
                        <div className="job-detail">
                            <div style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '10px' }}>{selectedJobDetail.title}</div>
                            <div style={{ marginBottom: '8px' }}><strong>URL:</strong> <a href={selectedJobDetail.url} target="_blank" rel="noreferrer">{selectedJobDetail.url}</a></div>
                            <div style={{ marginBottom: '8px', display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                                {selectedJobDetail.board && <span><strong>Board:</strong> <span className={`pill pill-${selectedJobDetail.board}`}>{selectedJobDetail.board}</span></span>}
                                {selectedJobDetail.seniority && <span><strong>Seniority:</strong> <span className={`pill pill-${selectedJobDetail.seniority}`}>{selectedJobDetail.seniority}</span></span>}
                                {selectedJobDetail.experience_years != null && <span><strong>Experience:</strong> {selectedJobDetail.experience_years} years</span>}
                                {selectedJobDetail.salary_k && <span><strong>Salary:</strong> <span style={{ color: 'var(--green)', fontWeight: 600 }}>${Math.round(selectedJobDetail.salary_k / 1000)}K</span></span>}
                                <span><strong>Run:</strong> <span style={{ color: 'var(--text-secondary)' }}>{selectedJobDetail.run_id}</span></span>
                                <span><strong>Created:</strong> <span style={{ color: 'var(--text-secondary)' }}>{new Date(selectedJobDetail.created_at).toLocaleDateString()}</span></span>
                            </div>
                            {selectedJobDetail.snippet && <div style={{ marginBottom: '8px' }}><strong>Snippet:</strong> <span style={{ color: 'var(--text-secondary)', fontSize: '.9rem' }}>{selectedJobDetail.snippet}</span></div>}
                            {selectedJobDetail.query && <div style={{ marginBottom: '8px' }}><strong>Query:</strong> <span style={{ color: 'var(--text-secondary)' }}>{selectedJobDetail.query}</span></div>}

                            {selectedJobDetail.filter_verdicts && selectedJobDetail.filter_verdicts.length > 0 && (
                                <div className="verdicts">
                                    <div style={{ fontWeight: 600, marginBottom: '8px' }}>Filter Verdicts</div>
                                    <VerdictChips verdicts={selectedJobDetail.filter_verdicts} />
                                </div>
                            )}

                            {selectedJobDetail.jd_text && (
                                <div>
                                    <div style={{ fontWeight: 600, marginTop: '16px', marginBottom: '4px' }}>Job Description</div>
                                    <div className="jd-text">{selectedJobDetail.jd_text}</div>
                                </div>
                            )}
                        </div>
                    ) : null}
                </WorkflowPanel>
            )}

            {/* Tailoring Runs Table */}
            <WorkflowPanel title="Tailoring Runs">
                {loading ? (
                    <LoadingState />
                ) : data.length === 0 ? (
                    <EmptyState icon="📄" text="No tailoring output runs found" />
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>Run</th>
                                <th>Status</th>
                                <th>Attempts</th>
                                <th>Events</th>
                                <th>Updated</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.map((run: any) => (
                                <tr key={run.slug} className="clickable-row" onClick={() => setActiveSlug(run.slug)} style={{ background: activeSlug === run.slug ? 'var(--accent-light)' : undefined }}>
                                    <td>
                                        <div style={{ fontWeight: 600 }}>{(run.meta?.job_id ?? '—') + ' · ' + (run.meta?.title ?? run.slug)}</div>
                                        <div style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>{run.slug}</div>
                                    </td>
                                    <td><span className={`pill ${run.status === 'complete' ? 'pill-success' : (run.status === 'failed' ? 'pill-fail' : (run.status === 'no-trace' ? 'pill-unknown' : 'pill-running'))}`}>{run.status}</span></td>
                                    <td style={{ fontSize: '.82rem' }}>resume {run.attempts?.resume ?? 0} / cover {run.attempts?.cover ?? 0}</td>
                                    <td>{run.event_count ?? 0}</td>
                                    <td>{timeAgo(run.updated_at)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </WorkflowPanel>
            </PagePrimary>

            {/* Run Detail with artifact buttons */}
            {activeTrace && activeSlug ? (
                <PageSecondary>
                <div>
                    <WorkflowPanel
                        title="Run Detail"
                        right={<div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                <button className="btn btn-success btn-sm" onClick={() => navigate('/tailoring/outputs/packages')}>Open Package Review</button>
                                <a className="btn btn-ghost btn-sm" href={`/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/meta.json`} target="_blank" rel="noreferrer">meta.json</a>
                                <a className="btn btn-ghost btn-sm" href={`/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/analysis.json`} target="_blank" rel="noreferrer">analysis.json</a>
                                <a className="btn btn-ghost btn-sm" href={`/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/resume_strategy.json`} target="_blank" rel="noreferrer">resume strategy</a>
                                <a className="btn btn-ghost btn-sm" href={`/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/cover_strategy.json`} target="_blank" rel="noreferrer">cover strategy</a>
                                <a className="btn btn-primary btn-sm" href={`/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/llm_trace.jsonl`} target="_blank" rel="noreferrer">download trace</a>
                            </div>}
                        style={{ marginTop: '16px' }}
                    >
                        <div className="stats-bar">
                            <span><strong>{activeTrace.meta?.job_id ?? '—'}</strong> job id</span>
                            <span><strong>{activeTrace.doc_status?.resume ?? 'pending'}</strong> resume</span>
                            <span><strong>{activeTrace.doc_status?.cover ?? 'pending'}</strong> cover</span>
                            <span><strong>{traces.length}</strong> trace events</span>
                        </div>
                    </WorkflowPanel>

                    {/* Pipeline Inspector */}
                    <div style={{ marginTop: '16px' }}>
                        {/* Analysis row */}
                        <div style={{ border: '1px solid var(--border)', borderRadius: '6px', marginBottom: '12px' }}>
                            <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)', fontSize: '.8rem', fontWeight: 600, color: 'var(--text-secondary)', background: 'var(--surface-2)', borderRadius: '6px 6px 0 0' }}>
                                Analysis
                            </div>
                            <div style={{ padding: '4px 4px' }}>
                                <StageRow label="LLM Call" ev={grouped.analysis.llm} />
                            </div>
                        </div>

                        {/* Doc tabs */}
                        <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
                            {(['resume', 'cover'] as const).map(doc => (
                                <button
                                    key={doc}
                                    className={`btn btn-sm ${selectedDocTab === doc ? 'btn-primary' : 'btn-ghost'}`}
                                    onClick={() => setSelectedDocTab(doc)}
                                >
                                    {doc === 'resume' ? 'Resume' : 'Cover Letter'}
                                </button>
                            ))}
                        </div>

                        {/* Attempt groups for selected doc */}
                        {(() => {
                            const docAttempts = selectedDocTab === 'resume' ? grouped.resume : grouped.cover;
                            const attemptNums = Object.keys(docAttempts).map(Number).sort((a, b) => a - b);
                            if (attemptNums.length === 0) {
                                return <div style={{ color: 'var(--text-secondary)', fontSize: '.85rem', padding: '12px 4px' }}>No {selectedDocTab} trace events found.</div>;
                            }
                            return attemptNums.map((n, i) => (
                                <AttemptGroup key={n} attempt={n} slots={docAttempts[n]} isRetry={i > 0} />
                            ));
                        })()}

                        {/* Detail pane */}
                        <div style={{ marginTop: '8px' }}>
                            <div className="trace-tabs">
                                <button className={`btn ${traceTab === 'system' ? 'btn-primary' : 'btn-ghost'} btn-sm`} onClick={() => setTraceTab('system')}>System Prompt</button>
                                <button className={`btn ${traceTab === 'user' ? 'btn-primary' : 'btn-ghost'} btn-sm`} onClick={() => setTraceTab('user')}>User Prompt</button>
                                <button className={`btn ${traceTab === 'response' ? 'btn-primary' : 'btn-ghost'} btn-sm`} onClick={() => setTraceTab('response')}>Raw Response</button>
                                <button className={`btn ${traceTab === 'meta' ? 'btn-primary' : 'btn-ghost'} btn-sm`} onClick={() => setTraceTab('meta')}>Metadata</button>
                                <button className="btn btn-success btn-sm" onClick={copyTracePane}>Copy</button>
                            </div>
                            <div className="trace-content">
                                {!selectedEvent ? (
                                    <div style={{ padding: '20px', color: 'var(--text-secondary)', textAlign: 'center' }}>Click a stage row to view its trace event.</div>
                                ) : (
                                    <>
                                        {traceTab === 'system' && <pre>{selectedEvent.system_prompt || ''}</pre>}
                                        {traceTab === 'user' && <pre>{selectedEvent.user_prompt || ''}</pre>}
                                        {traceTab === 'response' && <pre>{selectedEvent.raw_response || selectedEvent.error || ''}</pre>}
                                        {traceTab === 'meta' && <pre>{JSON.stringify(selectedEvent, null, 2)}</pre>}
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
                </PageSecondary>
            ) : null}
        </PageView>
    );
}
