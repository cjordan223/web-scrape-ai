import type { ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';

export type ContextTab = 'overview' | 'strategy' | 'jd';

/** Build a safe PDF filename from company + title for download (plain, no auto-generated look). */
export function safePdfName(company: string | undefined | null, title: string | undefined | null, fallback: string, kind: 'resume' | 'cover'): string {
    const sanit = (s: string) =>
        s.replace(/[^a-zA-Z0-9\s-]/g, '').replace(/\s+/g, '_').replace(/-+/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '').trim().slice(0, 40) || '';
    const c = sanit(String(company || '').trim());
    const t = sanit(String(title || '').trim());
    const suffix = c && t ? `${c}_${t}` : (c || t || fallback);
    const base = kind === 'resume' ? 'Conner_Jordan_Resume' : 'Conner_Jordan_Cover_Letter';
    return `${base}_${suffix}.pdf`;
}

export function timeAgo(isoDate: string | undefined | null) {
    if (!isoDate) return 'Never';
    const d = new Date(isoDate);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function parseMaybeJson(value: unknown): unknown {
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (!trimmed) return '';
    if (!trimmed.startsWith('[') && !trimmed.startsWith('{')) return value;
    try {
        return JSON.parse(trimmed);
    } catch {
        return value;
    }
}

function coerceStringList(value: unknown): string[] {
    const parsed = parseMaybeJson(value);
    if (Array.isArray(parsed)) {
        return parsed
            .map((item) => {
                if (typeof item === 'string') return item.trim();
                if (item && typeof item === 'object') {
                    const record = item as Record<string, unknown>;
                    return String(record.skill || record.jd_requirement || record.requirement || record.name || '').trim();
                }
                return String(item ?? '').trim();
            })
            .filter(Boolean);
    }
    if (typeof parsed === 'string') {
        const trimmed = parsed.trim();
        if (!trimmed) return [];
        if (trimmed.includes('\n')) {
            return trimmed.split(/\n+/).map((item) => item.replace(/^\s*[-•*]\s*/, '').trim()).filter(Boolean);
        }
        if (trimmed.includes(',')) {
            return trimmed.split(/,\s*/).map((item) => item.trim()).filter(Boolean);
        }
        return [trimmed];
    }
    return [];
}

function coerceObjectList(value: unknown): any[] {
    const parsed = parseMaybeJson(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && typeof item === 'object');
}

const S = {
    sectionLabel: {
        fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 600,
        color: 'var(--text-secondary)', textTransform: 'uppercase' as const, letterSpacing: '.1em',
        marginBottom: '8px',
    },
    fieldLabel: {
        fontFamily: 'var(--font-mono)', fontSize: '.64rem', fontWeight: 500,
        color: 'var(--text-secondary)', textTransform: 'uppercase' as const, letterSpacing: '.06em',
        marginBottom: '4px',
    },
    fieldValue: {
        fontSize: '.74rem', lineHeight: 1.45, color: 'var(--text)',
    },
} as const;

function statusColors(status?: string) {
    if (status === 'complete' || status === 'applied' || status === 'offer') {
        return {
            background: 'rgba(60,179,113,.10)',
            color: 'var(--green)',
        };
    }
    if (status === 'follow_up') {
        return {
            background: 'rgba(75, 142, 240, 0.10)',
            color: 'var(--accent)',
        };
    }
    return {
        background: 'rgba(200,144,42,.10)',
        color: status === 'withdrawn' || status === 'rejected' ? 'var(--red)' : 'var(--amber)',
    };
}

export function StrategyCard({ label, data }: { label: string; data: any }) {
    if (!data) {
        return (
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={S.sectionLabel}>{label}</div>
                <div style={{ ...S.fieldValue, color: 'var(--text-secondary)' }}>No strategy data</div>
            </div>
        );
    }

    const summaryStrategy = data.summary_strategy;
    const skillsStrategy = data.skills_strategy;
    const experienceFocus = coerceObjectList(data.experience_focus);
    const riskControls = coerceStringList(data.risk_controls);
    const openingAngle = data.opening_angle;
    const paragraphFocus = coerceStringList(data.paragraph_focus);
    const voiceControls = coerceStringList(data.voice_controls);
    const claimsToAvoid = coerceStringList(data.claims_to_avoid);
    const riskLikeItems = riskControls.length > 0 ? riskControls : claimsToAvoid;

    return (
        <div style={{ flex: 1, minWidth: 0 }}>
            <div style={S.sectionLabel}>{label}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {(summaryStrategy || openingAngle) && (
                    <div>
                        <div style={S.fieldLabel}>{summaryStrategy ? 'Summary Angle' : 'Opening Angle'}</div>
                        <div style={S.fieldValue}>{summaryStrategy || openingAngle}</div>
                    </div>
                )}

                {skillsStrategy && (
                    <div>
                        <div style={S.fieldLabel}>Skills Strategy</div>
                        <div style={S.fieldValue}>{skillsStrategy}</div>
                    </div>
                )}

                {experienceFocus.length > 0 && (
                    <div>
                        <div style={S.fieldLabel}>Experience Focus</div>
                        {experienceFocus.map((ef: any, i: number) => (
                            <div key={i} style={{
                                padding: '6px 8px', borderRadius: '3px', marginTop: i > 0 ? '6px' : 0,
                                background: 'var(--surface-3)', border: '1px solid var(--border)',
                            }}>
                                <div style={{ fontSize: '.72rem', fontWeight: 600, marginBottom: '4px', color: 'var(--text)' }}>
                                    {ef.company}
                                </div>
                                {ef.must_highlight && (
                                    <div style={{ fontSize: '.7rem', color: 'var(--text)', marginBottom: '3px' }}>
                                        <span style={{ color: 'var(--green)', fontFamily: 'var(--font-mono)', fontSize: '.6rem', marginRight: '4px' }}>HIGHLIGHT</span>
                                        {ef.must_highlight}
                                    </div>
                                )}
                                {ef.safe_metrics_to_keep && (
                                    <div style={{ fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                                        <span style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)', fontSize: '.6rem', marginRight: '4px' }}>METRICS</span>
                                        {ef.safe_metrics_to_keep}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {paragraphFocus.length > 0 && (
                    <div>
                        <div style={S.fieldLabel}>Paragraph Focus</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                            {paragraphFocus.map((p: string, i: number) => (
                                <div key={i} style={{
                                    display: 'flex', gap: '6px', alignItems: 'flex-start',
                                    fontSize: '.72rem', lineHeight: 1.4, color: 'var(--text)',
                                }}>
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600,
                                        color: 'var(--text-secondary)', flexShrink: 0, marginTop: '1px',
                                    }}>{i + 1}</span>
                                    {p}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {voiceControls.length > 0 && (
                    <div>
                        <div style={S.fieldLabel}>Voice Controls</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                            {voiceControls.map((v: string, i: number) => (
                                <div key={i} style={{ fontSize: '.7rem', lineHeight: 1.4, color: 'var(--text)' }}>{v}</div>
                            ))}
                        </div>
                    </div>
                )}

                {riskLikeItems.length > 0 && (
                    <div>
                        <div style={S.fieldLabel}>{riskControls.length > 0 ? 'Risk Controls' : 'Claims to Avoid'}</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                            {riskLikeItems.map((r: string, i: number) => (
                                <div key={i} style={{
                                    ...S.fieldValue, fontSize: '.7rem',
                                    padding: '3px 7px', borderRadius: '2px',
                                    background: 'rgba(217,79,79,.04)', borderLeft: '2px solid rgba(217,79,79,.25)',
                                    color: 'var(--text)',
                                }}>{r}</div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

export function JdDisplay({ text }: { text: string }) {
    if (!text) {
        return <div style={{ ...S.fieldValue, color: 'var(--text-secondary)' }}>No JD available</div>;
    }

    const paragraphs = text.split(/\n{2,}/).filter(Boolean);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {paragraphs.map((para, i) => {
                const lines = para.split('\n');
                const isHeader = lines.length === 1 && lines[0].length < 80 && !lines[0].endsWith('.');

                if (isHeader) {
                    return (
                        <div key={i} style={{
                            fontWeight: 600, fontSize: '.8rem', color: 'var(--text)',
                            paddingTop: i > 0 ? '4px' : 0,
                            borderTop: i > 0 ? '1px solid var(--border)' : 'none',
                        }}>
                            {lines[0]}
                        </div>
                    );
                }

                const isBulletList = lines.every((l) => /^\s*[-•*]\s/.test(l) || l.trim() === '');
                if (isBulletList) {
                    return (
                        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            {lines.filter((l) => l.trim()).map((line, j) => (
                                <div key={j} style={{
                                    fontSize: '.74rem', lineHeight: 1.45, color: 'var(--text)',
                                    paddingLeft: '12px',
                                    borderLeft: '2px solid var(--border-bright)',
                                }}>
                                    {line.replace(/^\s*[-•*]\s*/, '')}
                                </div>
                            ))}
                        </div>
                    );
                }

                return (
                    <div key={i} style={{
                        fontSize: '.74rem', lineHeight: 1.5, color: 'var(--text)',
                        whiteSpace: 'pre-wrap',
                    }}>
                        {para}
                    </div>
                );
            })}
        </div>
    );
}

type DetailContextSectionProps = {
    title: string;
    companyName?: string;
    jobUrl?: string;
    status?: string;
    statusLabel?: string;
    extraMeta?: ReactNode;
    badges?: ReactNode;
    contextTab: ContextTab;
    onContextTabChange: (tab: ContextTab) => void;
    analysis: any;
    resumeStrategy: any;
    coverStrategy: any;
    jobContext: any;
    emptyNote?: string;
    showTabsAndBody?: boolean;
};

export function DetailContextSection({
    title,
    companyName,
    jobUrl,
    status,
    statusLabel,
    extraMeta,
    badges,
    contextTab,
    onContextTabChange,
    analysis,
    resumeStrategy,
    coverStrategy,
    jobContext,
    emptyNote,
    showTabsAndBody = true,
}: DetailContextSectionProps) {
    const overviewKeyRequirements = coerceStringList(analysis?.key_requirements);
    const overviewEmphasisAreas = coerceStringList(resumeStrategy?.emphasis_areas);
    const statusStyle = statusColors(status);

    return (
        <>
            <div style={{
                flexShrink: 0, borderBottom: '1px solid var(--border)', background: 'var(--surface)',
            }}>
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '12px',
                    padding: '12px 20px 0',
                }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <h2 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, lineHeight: 1.3 }}>
                            {title || 'Untitled'}
                        </h2>
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '8px', marginTop: '3px',
                            fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)',
                            flexWrap: 'wrap',
                        }}>
                            {companyName && <span>{companyName}</span>}
                            {jobUrl && (
                                <a
                                    href={jobUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                        padding: '3px 8px',
                                        borderRadius: 999,
                                        border: '1px solid var(--border-bright)',
                                        background: 'var(--surface-2)',
                                        fontSize: '.7rem',
                                        fontFamily: 'var(--font-mono)',
                                        textTransform: 'uppercase',
                                        letterSpacing: '.08em',
                                        color: 'var(--accent)',
                                        textDecoration: 'none',
                                    }}
                                >
                                    JD Link
                                    <ExternalLink size={10} />
                                </a>
                            )}
                            {status && (
                                <>
                                    <span style={{ opacity: 0.3 }}>&middot;</span>
                                    <span style={{
                                        padding: '0 5px', borderRadius: '2px', fontSize: '.62rem', fontWeight: 600,
                                        textTransform: 'uppercase',
                                        background: statusStyle.background,
                                        color: statusStyle.color,
                                    }}>{statusLabel || status}</span>
                                </>
                            )}
                            {extraMeta}
                        </div>
                    </div>
                    {badges}
                </div>

                {showTabsAndBody && (
                    <div style={{
                        display: 'flex', gap: '0', padding: '0 20px', marginTop: '10px',
                    }}>
                        {([
                            { key: 'overview' as ContextTab, label: 'Overview' },
                            { key: 'strategy' as ContextTab, label: 'Strategy' },
                            { key: 'jd' as ContextTab, label: 'Full JD' },
                        ]).map((tab) => (
                            <button
                                key={tab.key}
                                onClick={() => onContextTabChange(tab.key)}
                                style={{
                                    padding: '6px 14px', fontSize: '.72rem', fontFamily: 'var(--font-mono)',
                                    fontWeight: contextTab === tab.key ? 600 : 400,
                                    color: contextTab === tab.key ? 'var(--accent)' : 'var(--text-secondary)',
                                    background: 'transparent', border: 'none', cursor: 'pointer',
                                    borderBottom: contextTab === tab.key ? '2px solid var(--accent)' : '2px solid transparent',
                                    transition: 'color .1s',
                                }}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            {showTabsAndBody && (
                <div style={{
                    flexShrink: 0, overflow: 'auto',
                    maxHeight: contextTab === 'overview' ? '180px' : '300px',
                    borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                    padding: '12px 20px',
                }}>
                {contextTab === 'overview' && (
                    <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                        {analysis && (
                            <div style={{ flex: '1 1 280px', minWidth: 0 }}>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: '6px' }}>
                                    Analysis
                                </div>
                                {analysis.role_title && (
                                    <div style={{ fontSize: '.78rem', marginBottom: '4px' }}>
                                        <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.68rem' }}>Role:</span>{' '}
                                        {analysis.role_title}
                                    </div>
                                )}
                                {overviewKeyRequirements.length > 0 && (
                                    <div style={{ marginTop: '4px' }}>
                                        <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.68rem' }}>Key reqs:</span>
                                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '3px' }}>
                                            {overviewKeyRequirements.slice(0, 8).map((requirement: string, i: number) => (
                                                <span key={i} style={{
                                                    fontFamily: 'var(--font-mono)', fontSize: '.62rem',
                                                    padding: '1px 6px', borderRadius: '2px',
                                                    background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                                                    color: 'var(--text)',
                                                }}>{requirement}</span>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {analysis.company_context && (
                                    <div style={{ fontSize: '.74rem', color: 'var(--text-secondary)', marginTop: '6px', lineHeight: 1.4 }}>
                                        {typeof analysis.company_context === 'string'
                                            ? analysis.company_context.slice(0, 200)
                                            : JSON.stringify(analysis.company_context).slice(0, 200)}
                                    </div>
                                )}
                            </div>
                        )}

                        {resumeStrategy && (
                            <div style={{ flex: '1 1 280px', minWidth: 0 }}>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: '6px' }}>
                                    Resume Strategy
                                </div>
                                {resumeStrategy.positioning && (
                                    <div style={{ fontSize: '.74rem', lineHeight: 1.4, color: 'var(--text)', marginBottom: '6px' }}>
                                        {typeof resumeStrategy.positioning === 'string'
                                            ? resumeStrategy.positioning.slice(0, 250)
                                            : JSON.stringify(resumeStrategy.positioning).slice(0, 250)}
                                    </div>
                                )}
                                {overviewEmphasisAreas.length > 0 && (
                                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                                        {overviewEmphasisAreas.slice(0, 6).map((area: string, i: number) => (
                                            <span key={i} style={{
                                                fontFamily: 'var(--font-mono)', fontSize: '.62rem',
                                                padding: '1px 6px', borderRadius: '2px',
                                                background: 'rgba(75, 142, 240, 0.08)', border: '1px solid rgba(75, 142, 240, 0.15)',
                                                color: 'var(--accent)',
                                            }}>{area}</span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {!analysis && !resumeStrategy && (
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.76rem', color: 'var(--text-secondary)' }}>
                                {emptyNote || 'No analysis or strategy data available.'}
                            </div>
                        )}
                    </div>
                )}

                {contextTab === 'strategy' && (
                    <div style={{ display: 'flex', gap: '20px' }}>
                        <StrategyCard label="Resume Strategy" data={resumeStrategy} />
                        <StrategyCard label="Cover Strategy" data={coverStrategy} />
                    </div>
                )}

                    {contextTab === 'jd' && (
                        <JdDisplay text={jobContext?.jd_text || jobContext?.snippet || ''} />
                    )}
                </div>
            )}
        </>
    );
}

// ═════════ Helpers for richer briefing/strategy views ═════════

type CompanyContext = {
    what_they_build?: string;
    engineering_challenges?: string;
    company_type?: string;
    cover_letter_hook?: string;
};

type Requirement = {
    jd_requirement?: string;
    matched_category?: string;
    matched_skills?: string | string[];
    evidence?: string;
    priority?: string;
};

export function CompanyContextCard({ context }: { context?: CompanyContext | string }) {
    if (!context) return null;

    if (typeof context === 'string') {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={S.sectionLabel}>Company Context</div>
                <div style={S.fieldValue}>{context}</div>
            </div>
        );
    }

    const { what_they_build, engineering_challenges, company_type, cover_letter_hook } = context;
    const hasAny = what_they_build || engineering_challenges || company_type || cover_letter_hook;
    if (!hasAny) return null;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={S.sectionLabel}>Company Context</div>
            {what_they_build && (
                <div>
                    <div style={S.fieldLabel}>What they build</div>
                    <div style={S.fieldValue}>{what_they_build}</div>
                </div>
            )}
            {engineering_challenges && (
                <div>
                    <div style={S.fieldLabel}>Engineering challenges</div>
                    <div style={S.fieldValue}>{engineering_challenges}</div>
                </div>
            )}
            {(company_type || cover_letter_hook) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {company_type && (
                        <div style={{ ...S.fieldValue, fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '.08em', fontSize: '.6rem' }}>
                                Company type:
                            </span>{' '}
                            {company_type}
                        </div>
                    )}
                    {cover_letter_hook && (
                        <div>
                            <div style={S.fieldLabel}>Cover letter hook</div>
                            <div style={S.fieldValue}>{cover_letter_hook}</div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export function RequirementsTable({ requirements }: { requirements?: unknown }) {
    const rows = coerceObjectList(requirements).map((r) => r as Requirement);
    if (!rows.length) return null;

    const priorityColor = (p?: string) => {
        const v = (p || '').toLowerCase();
        if (v === 'high') return { background: 'rgba(217,79,79,.12)', color: 'var(--red)' };
        if (v === 'medium') return { background: 'rgba(200,144,42,.12)', color: 'var(--amber)' };
        if (v === 'low') return { background: 'rgba(75,142,240,.12)', color: 'var(--accent)' };
        return { background: 'rgba(255,255,255,.04)', color: 'var(--text-secondary)' };
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={S.sectionLabel}>Requirements Match</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.65rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                Matched JD requirements ({rows.length})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {rows.map((req, idx) => {
                    const skills = coerceStringList(req.matched_skills);
                    const prio = (req.priority || '').toLowerCase();
                    return (
                        <div
                            key={idx}
                            style={{
                                borderRadius: 3,
                                border: '1px solid var(--border)',
                                background: 'var(--surface-3)',
                                padding: '8px 9px',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '4px',
                            }}
                        >
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                                <div style={{ fontSize: '.75rem', fontWeight: 500, color: 'var(--text)' }}>
                                    {req.jd_requirement || 'Unlabeled requirement'}
                                </div>
                                {req.priority && (
                                    <span
                                        style={{
                                            ...priorityColor(req.priority),
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '.6rem',
                                            textTransform: 'uppercase',
                                            letterSpacing: '.08em',
                                            padding: '1px 6px',
                                            borderRadius: 2,
                                            flexShrink: 0,
                                            whiteSpace: 'nowrap',
                                        }}
                                    >
                                        {prio || req.priority}
                                    </span>
                                )}
                            </div>
                            {(req.matched_category || skills.length > 0) && (
                                <div style={{ fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                                    {req.matched_category && (
                                        <>
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.08em' }}>
                                                Category:
                                            </span>{' '}
                                            {req.matched_category}
                                        </>
                                    )}
                                    {skills.length > 0 && (
                                        <div style={{ marginTop: '2px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                            {skills.map((s, i) => (
                                                <span
                                                    key={i}
                                                    style={{
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '.6rem',
                                                        padding: '1px 5px',
                                                        borderRadius: 2,
                                                        background: 'rgba(75,142,240,.08)',
                                                        border: '1px solid rgba(75,142,240,.25)',
                                                        color: 'var(--accent)',
                                                    }}
                                                >
                                                    {s}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                            {req.evidence && (
                                <div
                                    style={{
                                        fontSize: '.7rem',
                                        lineHeight: 1.45,
                                        color: 'var(--text)',
                                        marginTop: '2px',
                                        borderLeft: '2px solid var(--border-bright)',
                                        paddingLeft: '8px',
                                    }}
                                >
                                    {req.evidence}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export function BriefingPanel({
    analysis,
}: {
    analysis: any;
}) {
    if (!analysis) {
        return (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.76rem', color: 'var(--text-secondary)' }}>
                No analysis data available for this package.
            </div>
        );
    }

    const requirements = analysis.requirements;
    const toneNotes = analysis.tone_notes;
    const summaryAngle = analysis.summary_angle;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <CompanyContextCard context={analysis.company_context} />

            <RequirementsTable requirements={requirements} />

            {(summaryAngle || toneNotes) && (
                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.3fr) minmax(0, 1fr)', gap: '14px' }}>
                    {summaryAngle && (
                        <div>
                            <div style={S.sectionLabel}>Positioning Summary</div>
                            <div style={S.fieldValue}>{summaryAngle}</div>
                        </div>
                    )}
                    {toneNotes && (
                        <div>
                            <div style={S.sectionLabel}>Tone Notes</div>
                            <div style={{ ...S.fieldValue, fontSize: '.72rem', color: 'var(--text-secondary)' }}>{toneNotes}</div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export function DocumentsSideBySide({
    resumePdfUrl,
    coverPdfUrl,
    resumeDownloadName,
    coverDownloadName,
}: {
    resumePdfUrl: string;
    coverPdfUrl: string;
    resumeDownloadName?: string;
    coverDownloadName?: string;
}) {
    return (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', height: '100%' }}>
            <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', flexShrink: 0 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-secondary)' }}>
                        Resume
                    </span>
                    <a
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: '.68rem', pointerEvents: resumePdfUrl ? 'auto' : 'none', opacity: resumePdfUrl ? 1 : 0.45 }}
                        href={resumePdfUrl || undefined}
                        download={resumeDownloadName ?? 'Conner_Jordan_Resume.pdf'}
                    >
                        Download PDF
                    </a>
                </div>
                <iframe
                    src={resumePdfUrl ? `${resumePdfUrl}#pagemode=none&view=Fit` : ''}
                    style={{ width: '100%', border: 'none', flex: 1, background: '#525659' }}
                />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', flexShrink: 0 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-secondary)' }}>
                        Cover Letter
                    </span>
                    <a
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: '.68rem', pointerEvents: coverPdfUrl ? 'auto' : 'none', opacity: coverPdfUrl ? 1 : 0.45 }}
                        href={coverPdfUrl || undefined}
                        download={coverDownloadName ?? 'Conner_Jordan_Cover_Letter.pdf'}
                    >
                        Download PDF
                    </a>
                </div>
                <iframe
                    src={coverPdfUrl ? `${coverPdfUrl}#pagemode=none&view=Fit` : ''}
                    style={{ width: '100%', border: 'none', flex: 1, background: '#525659' }}
                />
            </div>
        </div>
    );
}
