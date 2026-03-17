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
    applied?: { id: number; status?: string } | null;
}

interface Briefing {
    job: any;
    analysis: any | null;
    resume_strategy: any | null;
    cover_strategy: any | null;
    run_slug: string | null;
}

interface Props {
    onRunStarted: () => void;
}

export default function JobInventoryTab({ onRunStarted }: Props) {
    const [recentJobs, setRecentJobs] = useState<RecentJob[]>([]);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [focusedJobId, setFocusedJobId] = useState<number>(0);
    const [briefing, setBriefing] = useState<Briefing | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [skipAnalysis, setSkipAnalysis] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);
    const [queueError, setQueueError] = useState('');
    const [resetBusy, setResetBusy] = useState(false);

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
        if (!focusedJobId) { setBriefing(null); return; }
        setDetailLoading(true);
        (async () => {
            try {
                const res = await api.getTailoringJobBriefing(focusedJobId);
                setBriefing(res);
            } catch { setBriefing(null); }
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
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em' }}>
                        Recent Jobs ({recentJobs.length})
                    </span>
                    {recentJobs.length > 0 && (
                        <button
                            className="btn btn-ghost btn-sm"
                            disabled={resetBusy}
                            onClick={async () => {
                                if (!confirm('Reset all approved jobs back to QA triage?')) return;
                                setResetBusy(true);
                                try {
                                    await api.resetApprovedQA();
                                    const res = await api.getTailoringRecentJobs();
                                    setRecentJobs(res.items || []);
                                    setSelectedIds(new Set());
                                    setFocusedJobId(0);
                                } catch { }
                                finally { setResetBusy(false); }
                            }}
                            style={{ fontSize: '.64rem', color: 'var(--text-secondary)' }}
                        >
                            {resetBusy ? 'Resetting...' : 'Reset to QA'}
                        </button>
                    )}
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
                        const applied = j.applied;
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
                                                    display: 'inline-flex', alignItems: 'center', gap: '4px',
                                                    borderRadius: '999px',
                                                    border: '1px solid rgba(224, 160, 48, 0.55)',
                                                    background: 'rgba(224, 160, 48, 0.12)',
                                                    color: 'var(--amber, #e0a030)',
                                                    padding: '1px 8px',
                                                    fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600, letterSpacing: '.02em',
                                                }}
                                            >
                                                Already run ({priorRunCount}) •
                                                <span aria-hidden="true" style={{ width: '6px', height: '6px', borderRadius: '999px', background: runStatus.color, display: 'inline-block', marginLeft: '2px' }} />
                                                <span style={{ color: runStatus.color }}>{runStatus.label}</span>
                                            </span>
                                        </div>
                                    )}
                                    {applied && (
                                        <div style={{ marginBottom: '4px' }}>
                                            <span
                                                style={{
                                                    display: 'inline-flex', alignItems: 'center', gap: '4px',
                                                    borderRadius: '999px',
                                                    border: '1px solid rgba(75, 142, 240, 0.35)',
                                                    background: 'rgba(75, 142, 240, 0.10)',
                                                    color: 'var(--accent)',
                                                    padding: '1px 8px',
                                                    fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600, letterSpacing: '.02em',
                                                }}
                                            >
                                                Applied
                                                {applied.status ? <span style={{ opacity: 0.8 }}>• {applied.status}</span> : null}
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

            {/* Right: job briefing */}
            <div style={{ flex: 1, minWidth: 0, overflow: 'auto', background: 'var(--bg)' }}>
                {!focusedJobId ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem' }}>
                        Select a job to view briefing
                    </div>
                ) : detailLoading ? (
                    <div className="loading"><div className="spinner" /></div>
                ) : !briefing ? (
                    <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.8rem', textAlign: 'center', padding: '40px' }}>
                        Job not found
                    </div>
                ) : (
                    <BriefingPanel briefing={briefing} />
                )}
            </div>
        </div>
    );
}


/* ─── Briefing Panel ─── */

function BriefingPanel({ briefing }: { briefing: Briefing }) {
    const { job, analysis, resume_strategy, cover_strategy, run_slug } = briefing;
    const hasRun = Boolean(analysis || resume_strategy || cover_strategy);

    const company = analysis?.company_name || extractCompany(job.url) || '';
    const role = analysis?.role_title || job.title || 'Untitled';

    return (
        <div style={{ padding: '24px 32px 40px', maxWidth: '920px' }}>
            {/* ── Header ── */}
            <div style={{ marginBottom: '28px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                    <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                        color: 'var(--accent)', background: 'var(--accent-light)',
                        border: '1px solid var(--accent-dim)',
                        borderRadius: '2px', padding: '2px 8px',
                        textTransform: 'uppercase', letterSpacing: '.1em',
                    }}>
                        Job #{job.id}
                    </span>
                    {company && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                            color: 'var(--cyan)', background: 'rgba(42, 184, 204, 0.08)',
                            border: '1px solid rgba(42, 184, 204, 0.25)',
                            borderRadius: '2px', padding: '2px 8px',
                            textTransform: 'uppercase', letterSpacing: '.08em',
                        }}>
                            {company}
                        </span>
                    )}
                    {hasRun && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 600,
                            color: 'var(--green)', background: 'rgba(60, 179, 113, 0.08)',
                            border: '1px solid rgba(60, 179, 113, 0.25)',
                            borderRadius: '2px', padding: '2px 8px',
                            textTransform: 'uppercase', letterSpacing: '.1em',
                        }}>
                            Pipeline data available
                        </span>
                    )}
                </div>
                <h2 style={{ fontSize: '1.2rem', fontWeight: 600, lineHeight: 1.3, marginBottom: '8px', color: 'var(--text)' }}>
                    {role}
                </h2>
                {job.url && (
                    <a href={job.url} target="_blank" rel="noreferrer" style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--accent)',
                        textDecoration: 'none', wordBreak: 'break-all',
                    }}>
                        {job.url}
                    </a>
                )}
            </div>

            {/* ── Requirements Summary ── */}
            {job.snippet && (
                <Section title="Requirements Summary" accent="var(--accent)">
                    <p style={{ fontSize: '.86rem', lineHeight: 1.65, color: 'var(--text)' }}>
                        {job.snippet}
                    </p>
                </Section>
            )}

            {/* ── Company Context (from analysis) ── */}
            {analysis?.company_context && (
                <Section title="Company Context" accent="var(--cyan)">
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 20px' }}>
                        <ContextField label="What They Build" value={analysis.company_context.what_they_build} />
                        <ContextField label="Engineering Challenges" value={analysis.company_context.engineering_challenges} />
                        <ContextField label="Company Type" value={analysis.company_context.company_type} pill />
                        <ContextField label="Cover Letter Hook" value={analysis.company_context.cover_letter_hook} />
                    </div>
                </Section>
            )}

            {/* ── JD Requirements Mapping ── */}
            {analysis?.requirements && analysis.requirements.length > 0 && (
                <Section title="Requirements Mapping" accent="var(--purple)">
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                        {analysis.requirements.map((req: any, i: number) => (
                            <RequirementRow key={i} req={req} />
                        ))}
                    </div>
                </Section>
            )}

            {/* ── Summary Angle + Tone ── */}
            {analysis && (analysis.summary_angle || analysis.tone_notes) && (
                <Section title="Positioning" accent="var(--teal)">
                    {analysis.summary_angle && (
                        <div style={{ marginBottom: '10px' }}>
                            <FieldLabel>Summary Angle</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)', fontStyle: 'italic' }}>
                                {analysis.summary_angle}
                            </p>
                        </div>
                    )}
                    {analysis.tone_notes && (
                        <div>
                            <FieldLabel>Tone Notes</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)' }}>
                                {analysis.tone_notes}
                            </p>
                        </div>
                    )}
                </Section>
            )}

            {/* ── Resume Strategy ── */}
            {resume_strategy && (
                <Section title="Resume Strategy" accent="var(--orange)">
                    {resume_strategy.summary_strategy && (
                        <div style={{ marginBottom: '16px' }}>
                            <FieldLabel>Summary Direction</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)' }}>
                                {resume_strategy.summary_strategy}
                            </p>
                        </div>
                    )}
                    {resume_strategy.skills_tailoring && (
                        <div style={{ marginBottom: '16px' }}>
                            <FieldLabel>Skills Reordering</FieldLabel>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                                {Object.entries(resume_strategy.skills_tailoring).map(([cat, guidance]) => (
                                    <div key={cat} style={{
                                        display: 'flex', gap: '10px', padding: '6px 10px',
                                        background: 'var(--surface)', borderRadius: '3px', border: '1px solid var(--border)',
                                    }}>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600, color: 'var(--orange)', minWidth: '160px', flexShrink: 0 }}>
                                            {cat}
                                        </span>
                                        <span style={{ fontSize: '.78rem', color: 'var(--text)', lineHeight: 1.5 }}>
                                            {String(guidance)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {resume_strategy.experience_rewrites && resume_strategy.experience_rewrites.length > 0 && (
                        <div style={{ marginBottom: '16px' }}>
                            <FieldLabel>Experience Rewrites</FieldLabel>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '8px' }}>
                                {resume_strategy.experience_rewrites.map((entry: any, i: number) => (
                                    <ExperienceRewriteCard key={i} entry={entry} />
                                ))}
                            </div>
                        </div>
                    )}
                    {resume_strategy.risk_controls && resume_strategy.risk_controls.length > 0 && (
                        <div>
                            <FieldLabel>Risk Controls</FieldLabel>
                            <ul style={{ margin: '6px 0 0 16px', fontSize: '.78rem', color: 'var(--text)', lineHeight: 1.7 }}>
                                {resume_strategy.risk_controls.map((r: string, i: number) => (
                                    <li key={i}>{r}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                </Section>
            )}

            {/* ── Cover Strategy ── */}
            {cover_strategy && (
                <Section title="Cover Letter Strategy" accent="var(--green)">
                    {cover_strategy.company_hook && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Company Hook</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)', fontStyle: 'italic' }}>
                                {cover_strategy.company_hook}
                            </p>
                        </div>
                    )}
                    {cover_strategy.structure && cover_strategy.structure.length > 0 && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Paragraph Structure</FieldLabel>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                                {cover_strategy.structure.map((para: any, i: number) => (
                                    <div key={i} style={{
                                        padding: '8px 12px', background: 'var(--surface)', borderRadius: '3px',
                                        border: '1px solid var(--border)', borderLeft: '3px solid var(--green)',
                                    }}>
                                        <div style={{ fontWeight: 600, fontSize: '.8rem', marginBottom: '4px', color: 'var(--text)' }}>
                                            {para.focus || para.theme || `Paragraph ${i + 1}`}
                                        </div>
                                        {para.theme && para.theme !== para.focus && (
                                            <div style={{ fontSize: '.74rem', color: 'var(--text-secondary)', marginBottom: '3px' }}>
                                                Theme: {para.theme}
                                            </div>
                                        )}
                                        {para.experience_sources && (
                                            <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                                                Sources: {Array.isArray(para.experience_sources) ? para.experience_sources.join(', ') : String(para.experience_sources)}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {cover_strategy.closing_angle && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Closing Angle</FieldLabel>
                            <p style={{ fontSize: '.84rem', lineHeight: 1.6, color: 'var(--text)' }}>
                                {cover_strategy.closing_angle}
                            </p>
                        </div>
                    )}
                    {cover_strategy.voice_controls && cover_strategy.voice_controls.length > 0 && (
                        <div style={{ marginBottom: '14px' }}>
                            <FieldLabel>Voice Controls</FieldLabel>
                            <ul style={{ margin: '6px 0 0 16px', fontSize: '.78rem', color: 'var(--text)', lineHeight: 1.7 }}>
                                {cover_strategy.voice_controls.map((v: string, i: number) => (
                                    <li key={i}>{v}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {cover_strategy.vignettes_to_use && cover_strategy.vignettes_to_use.length > 0 && (
                        <div>
                            <FieldLabel>Vignettes</FieldLabel>
                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '6px' }}>
                                {cover_strategy.vignettes_to_use.map((v: string, i: number) => (
                                    <span key={i} style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 500,
                                        padding: '2px 8px', borderRadius: '2px',
                                        background: 'rgba(60, 179, 113, 0.08)', border: '1px solid rgba(60, 179, 113, 0.2)',
                                        color: 'var(--green)',
                                    }}>
                                        {v}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </Section>
            )}

            {/* ── Raw JD Text (collapsible) ── */}
            {job.jd_text && (
                <CollapsibleSection title="Full JD Text" defaultOpen={!hasRun}>
                    <pre style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.74rem', lineHeight: 1.6,
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text)',
                        margin: 0, maxHeight: '500px', overflow: 'auto',
                        padding: '12px', background: 'var(--surface)', borderRadius: '3px',
                        border: '1px solid var(--border)',
                    }}>
                        {job.jd_text}
                    </pre>
                </CollapsibleSection>
            )}

            {/* ── Run metadata ── */}
            {run_slug && (
                <div style={{
                    marginTop: '24px', padding: '8px 12px',
                    background: 'var(--surface)', borderRadius: '3px', border: '1px solid var(--border)',
                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)',
                    display: 'flex', gap: '16px',
                }}>
                    <span>Run: {run_slug}</span>
                    {job.created_at && <span>Created: {new Date(job.created_at).toLocaleDateString()}</span>}
                </div>
            )}
        </div>
    );
}


/* ─── Sub-components ─── */

function Section({ title, accent, children }: { title: string; accent: string; children: React.ReactNode }) {
    return (
        <div style={{ marginBottom: '24px' }}>
            <div style={{
                display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px',
                paddingBottom: '6px', borderBottom: `1px solid var(--border)`,
            }}>
                <div style={{ width: '3px', height: '14px', borderRadius: '1px', background: accent, flexShrink: 0 }} />
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
                    color: accent, textTransform: 'uppercase', letterSpacing: '.08em',
                }}>
                    {title}
                </span>
            </div>
            {children}
        </div>
    );
}

function CollapsibleSection({ title, defaultOpen, children }: { title: string; defaultOpen: boolean; children: React.ReactNode }) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div style={{ marginBottom: '24px' }}>
            <div
                style={{
                    display: 'flex', alignItems: 'center', gap: '8px', marginBottom: open ? '12px' : 0,
                    paddingBottom: '6px', borderBottom: '1px solid var(--border)', cursor: 'pointer',
                }}
                onClick={() => setOpen(!open)}
            >
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', fontWeight: 600,
                    color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
                    transition: 'transform .15s', display: 'inline-block',
                    transform: open ? 'rotate(90deg)' : 'rotate(0)',
                }}>
                    ▸
                </span>
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
                    color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
                }}>
                    {title}
                </span>
            </div>
            {open && children}
        </div>
    );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
    return (
        <div style={{
            fontFamily: 'var(--font-mono)', fontSize: '.64rem', fontWeight: 600,
            color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
            marginBottom: '4px',
        }}>
            {children}
        </div>
    );
}

function ContextField({ label, value, pill }: { label: string; value?: string; pill?: boolean }) {
    if (!value) return null;
    return (
        <div>
            <FieldLabel>{label}</FieldLabel>
            {pill ? (
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.72rem', fontWeight: 600,
                    padding: '2px 10px', borderRadius: '2px',
                    background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                    color: 'var(--cyan)', textTransform: 'lowercase',
                }}>
                    {value}
                </span>
            ) : (
                <p style={{ fontSize: '.82rem', lineHeight: 1.55, color: 'var(--text)', margin: 0 }}>{value}</p>
            )}
        </div>
    );
}

function coerceStringList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map((item) => String(item).trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
        return value
            .split(/,\s*/)
            .map((item) => item.trim())
            .filter(Boolean);
    }
    return [];
}

function RequirementRow({ req }: { req: any }) {
    const priorityColor = req.priority === 'high' ? 'var(--red)' : req.priority === 'medium' ? 'var(--amber)' : 'var(--text-secondary)';
    const matchedSkills = coerceStringList(req.matched_skills);
    return (
        <div style={{
            display: 'grid', gridTemplateColumns: '56px 1fr 1fr', gap: '10px',
            padding: '8px 10px', background: 'var(--surface)', borderRadius: '2px',
            border: '1px solid var(--border)', alignItems: 'start',
        }}>
            <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 700,
                textTransform: 'uppercase', color: priorityColor,
                paddingTop: '2px',
            }}>
                {req.priority || '—'}
            </span>
            <div>
                <div style={{ fontSize: '.8rem', fontWeight: 500, color: 'var(--text)', marginBottom: '3px', lineHeight: 1.4 }}>
                    {req.jd_requirement}
                </div>
                {matchedSkills.length > 0 && (
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
                        {matchedSkills.map((s: string, i: number) => (
                            <span key={i} style={{
                                fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 500,
                                padding: '1px 6px', borderRadius: '2px',
                                background: 'rgba(139, 124, 246, 0.08)', border: '1px solid rgba(139, 124, 246, 0.2)',
                                color: 'var(--purple)',
                            }}>
                                {s}
                            </span>
                        ))}
                    </div>
                )}
            </div>
            <div>
                {req.evidence && (
                    <div style={{
                        fontSize: '.74rem', lineHeight: 1.5, color: 'var(--text-secondary)',
                        fontStyle: 'italic', paddingLeft: '10px',
                        borderLeft: '2px solid var(--border-bright)',
                    }}>
                        {req.evidence}
                    </div>
                )}
            </div>
        </div>
    );
}

function ExperienceRewriteCard({ entry }: { entry: any }) {
    const bulletRewrites = Array.isArray(entry.bullet_rewrites) ? entry.bullet_rewrites :
        typeof entry.bullet_rewrites === 'string' ? (() => { try { return JSON.parse(entry.bullet_rewrites); } catch { return []; } })() : [];
    const preserves = Array.isArray(entry.bullets_to_preserve) ? entry.bullets_to_preserve :
        typeof entry.bullets_to_preserve === 'string' ? (() => { try { return JSON.parse(entry.bullets_to_preserve); } catch { return []; } })() : [];

    return (
        <div style={{
            padding: '10px 14px', background: 'var(--surface)', borderRadius: '3px',
            border: '1px solid var(--border)', borderLeft: '3px solid var(--orange)',
        }}>
            <div style={{ fontWeight: 600, fontSize: '.82rem', marginBottom: '8px', color: 'var(--text)' }}>
                {entry.company || 'Unknown Company'}
            </div>
            {bulletRewrites.length > 0 && (
                <div style={{ marginBottom: '8px' }}>
                    {bulletRewrites.map((rw: any, i: number) => (
                        <div key={i} style={{ marginBottom: '6px', paddingLeft: '10px', borderLeft: '2px solid var(--orange)', fontSize: '.76rem', lineHeight: 1.5 }}>
                            <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.66rem', marginBottom: '2px' }}>
                                {rw.baseline_topic}
                            </div>
                            <div style={{ color: 'var(--text)' }}>
                                {rw.rewrite_angle}
                            </div>
                            {rw.jd_requirement_addressed && (
                                <div style={{ color: 'var(--purple)', fontFamily: 'var(--font-mono)', fontSize: '.64rem', marginTop: '2px' }}>
                                    targets: {rw.jd_requirement_addressed}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
            {preserves.length > 0 && (
                <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                    Preserve: {preserves.join(' · ')}
                </div>
            )}
        </div>
    );
}


/* ─── Utility ─── */

function extractCompany(url?: string): string {
    if (!url) return '';
    try {
        const host = new URL(url).hostname.replace('www.', '').replace('jobs.', '').replace('careers.', '');
        const parts = host.split('.');
        if (parts.length >= 2) return parts[parts.length - 2];
    } catch { }
    return '';
}
