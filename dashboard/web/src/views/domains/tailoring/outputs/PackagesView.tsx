import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import { ExternalLink, FileDiff, Pencil } from 'lucide-react';

function timeAgo(isoDate: string | undefined | null) {
    if (!isoDate) return 'Never';
    const d = new Date(isoDate);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

type MainTab = 'diff' | 'editor';
type ContextTab = 'overview' | 'strategy' | 'jd';

// ── Shared inline styles ──

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
    chip: {
        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 500,
        padding: '2px 7px', borderRadius: '2px',
        background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
        color: 'var(--text)',
    },
    riskChip: {
        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 500,
        padding: '2px 7px', borderRadius: '2px',
        background: 'rgba(217,79,79,.06)', border: '1px solid rgba(217,79,79,.12)',
        color: 'var(--red)',
    },
} as const;

// ── Strategy Card ──

function StrategyCard({ label, data }: { label: string; data: any }) {
    if (!data) {
        return (
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={S.sectionLabel}>{label}</div>
                <div style={{ ...S.fieldValue, color: 'var(--text-secondary)' }}>No strategy data</div>
            </div>
        );
    }

    // Resume strategy fields
    const summaryStrategy = data.summary_strategy;
    const skillsStrategy = data.skills_strategy;
    const experienceFocus = data.experience_focus;
    const riskControls = data.risk_controls;

    // Cover strategy fields
    const openingAngle = data.opening_angle;
    const paragraphFocus = data.paragraph_focus;
    const voiceControls = data.voice_controls;
    const claimsToAvoid = data.claims_to_avoid;

    return (
        <div style={{ flex: 1, minWidth: 0 }}>
            <div style={S.sectionLabel}>{label}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>

                {/* Summary / Opening */}
                {(summaryStrategy || openingAngle) && (
                    <div>
                        <div style={S.fieldLabel}>{summaryStrategy ? 'Summary Angle' : 'Opening Angle'}</div>
                        <div style={S.fieldValue}>{summaryStrategy || openingAngle}</div>
                    </div>
                )}

                {/* Skills strategy (resume only) */}
                {skillsStrategy && (
                    <div>
                        <div style={S.fieldLabel}>Skills Strategy</div>
                        <div style={S.fieldValue}>{skillsStrategy}</div>
                    </div>
                )}

                {/* Experience focus (resume) */}
                {experienceFocus && Array.isArray(experienceFocus) && experienceFocus.length > 0 && (
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

                {/* Paragraph focus (cover) */}
                {paragraphFocus && Array.isArray(paragraphFocus) && (
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

                {/* Voice controls (cover) */}
                {voiceControls && Array.isArray(voiceControls) && (
                    <div>
                        <div style={S.fieldLabel}>Voice Controls</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                            {voiceControls.map((v: string, i: number) => (
                                <div key={i} style={{ fontSize: '.7rem', lineHeight: 1.4, color: 'var(--text)' }}>{v}</div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Risk controls / Claims to avoid */}
                {(riskControls || claimsToAvoid) && (
                    <div>
                        <div style={S.fieldLabel}>{riskControls ? 'Risk Controls' : 'Claims to Avoid'}</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                            {(riskControls || claimsToAvoid || []).map((r: string, i: number) => (
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

// ── JD Display ──

function JdDisplay({ text }: { text: string }) {
    if (!text) {
        return <div style={{ ...S.fieldValue, color: 'var(--text-secondary)' }}>No JD available</div>;
    }

    // Split into paragraphs and render with visual structure
    const paragraphs = text.split(/\n{2,}/).filter(Boolean);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {paragraphs.map((para, i) => {
                const lines = para.split('\n');
                // Detect if this paragraph is a header-like line (short, no period, often all-caps or title case)
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

                // Check if it's a bullet list
                const isBulletList = lines.every(l => /^\s*[-•*]\s/.test(l) || l.trim() === '');
                if (isBulletList) {
                    return (
                        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            {lines.filter(l => l.trim()).map((line, j) => (
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

export default function PackagesView() {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [pkgDetail, setPkgDetail] = useState<any>(null);

    // Tabs
    const [mainTab, setMainTab] = useState<MainTab>('diff');
    const [contextTab, setContextTab] = useState<ContextTab>('overview');

    // Live Editor State
    const [packageDoc, setPackageDoc] = useState<'resume' | 'cover'>('resume');
    const [resumeTex, setResumeTex] = useState('');
    const [coverTex, setCoverTex] = useState('');
    const [saveStatus, setSaveStatus] = useState('');
    const [compileError, setCompileError] = useState('');
    const [previewBuster, setPreviewBuster] = useState({ resume: Date.now(), cover: Date.now() });
    const [diffBuster, setDiffBuster] = useState({ resume: Date.now(), cover: Date.now() });
    const [diffError, setDiffError] = useState('');
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);


    const fetchPackages = useCallback(async () => {
        try {
            const res = await api.getPackages();
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

    useEffect(() => {
        fetchPackages();
    }, [fetchPackages]);

    useEffect(() => {
        const fetchDetail = async () => {
            if (!activeSlug) return;
            try {
                const res = await api.getPackageDetail(activeSlug);
                setPkgDetail(res);
                setResumeTex(res.latex?.resume || '');
                setCoverTex(res.latex?.cover || '');
                setPreviewBuster({ resume: Date.now(), cover: Date.now() });
                setDiffBuster({ resume: Date.now(), cover: Date.now() });
                setSaveStatus('');
                setCompileError('');
                setDiffError('');
                setMainTab('diff');
                setContextTab('overview');
            } catch (err) {
                console.error(err);
                setPkgDetail(null);
            }
        };
        fetchDetail();
    }, [activeSlug]);

    const handleLatexChange = (val: string) => {
        if (packageDoc === 'resume') setResumeTex(val);
        else setCoverTex(val);

        setSaveStatus('saving...');
        if (saveTimer.current) clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(async () => {
            try {
                await api.savePackageLatex(activeSlug!, packageDoc, val);
                setSaveStatus('saved');
                setDiffBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
            } catch {
                setSaveStatus('save failed');
            }
        }, 900);
    };

    const handleCompile = async () => {
        if (!activeSlug) return;
        setCompileError('');
        setSaveStatus('compiling...');
        try {
            await api.compilePackageDoc(activeSlug, packageDoc);
            setSaveStatus('compiled');
            setPreviewBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
            setDiffBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
        } catch (e: any) {
            setCompileError(e.response?.data?.error || 'compile failed');
            setSaveStatus('compile failed');
        }
    };

    const activePkg = data.find(p => p.slug === activeSlug);
    const resumePdfKey = Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Resume.pdf'));
    const coverPdfKey = Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Cover_Letter.pdf'));
    const pdfKey = packageDoc === 'resume'
        ? Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Resume.pdf'))
        : Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Cover_Letter.pdf'));
    const currentPdfUrl = activeSlug && pdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(pdfKey)}?v=${previewBuster[packageDoc]}`
        : '';
    const resumePdfUrl = activeSlug && resumePdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(resumePdfKey)}`
        : '';
    const coverPdfUrl = activeSlug && coverPdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(coverPdfKey)}`
        : '';

    // Strategy summary extraction
    const strategy = pkgDetail?.resume_strategy;
    const coverStrategy = pkgDetail?.cover_strategy;
    const analysis = pkgDetail?.analysis;

    if (loading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <div className="spinner" />
            </div>
        );
    }

    if (data.length === 0) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 'calc(100vh - 56px)', flexDirection: 'column', gap: '12px' }}>
                <span style={{ fontSize: '1.6rem', opacity: 0.2 }}>&#9998;</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.82rem', color: 'var(--text-secondary)' }}>No document packages generated yet.</span>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>

            {/* ══════════ LEFT SIDEBAR — Package List ══════════ */}
            <div style={{
                width: '280px', flexShrink: 0, display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border)', background: 'var(--surface)', overflow: 'hidden',
            }}>
                <div style={{
                    padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                }}>
                    <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em',
                    }}>
                        Packages ({data.length})
                    </span>
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {data.map((item) => {
                        const isActive = activeSlug === item.slug;
                        const hasResume = item.artifacts['Conner_Jordan_Resume.pdf'];
                        const hasCover = item.artifacts['Conner_Jordan_Cover_Letter.pdf'];
                        return (
                            <div
                                key={item.slug}
                                onClick={() => setActiveSlug(item.slug)}
                                style={{
                                    padding: '10px 14px', cursor: 'pointer',
                                    borderBottom: '1px solid var(--border)',
                                    borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                                    background: isActive ? 'var(--accent-light)' : 'transparent',
                                    transition: 'background .08s',
                                }}
                                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--surface-2)'; }}
                                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = isActive ? 'var(--accent-light)' : 'transparent'; }}
                            >
                                <div style={{
                                    fontWeight: 600, fontSize: '.8rem', lineHeight: 1.3,
                                    overflow: 'hidden', textOverflow: 'ellipsis',
                                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                                }}>
                                    {item.meta?.job_title || item.slug}
                                </div>
                                <div style={{
                                    display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px',
                                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)',
                                }}>
                                    <span>{item.meta?.company_name || '--'}</span>
                                    <span style={{ opacity: 0.4 }}>&middot;</span>
                                    <span>{timeAgo(item.updated_at)}</span>
                                </div>
                                <div style={{ display: 'flex', gap: '4px', marginTop: '5px' }}>
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 500,
                                        padding: '1px 5px', borderRadius: '2px',
                                        background: hasResume ? 'rgba(60,179,113,.10)' : 'rgba(217,79,79,.08)',
                                        color: hasResume ? 'var(--green)' : 'var(--red)',
                                    }}>RES</span>
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 500,
                                        padding: '1px 5px', borderRadius: '2px',
                                        background: hasCover ? 'rgba(60,179,113,.10)' : 'rgba(217,79,79,.08)',
                                        color: hasCover ? 'var(--green)' : 'var(--red)',
                                    }}>CVR</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* ══════════ MAIN CONTENT ══════════ */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

                {!pkgDetail ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
                        <div className="spinner" />
                    </div>
                ) : (
                    <>
                        {/* ── Context Header ── */}
                        <div style={{
                            flexShrink: 0, borderBottom: '1px solid var(--border)', background: 'var(--surface)',
                        }}>
                            {/* Title bar */}
                            <div style={{
                                display: 'flex', alignItems: 'center', gap: '12px',
                                padding: '12px 20px 0',
                            }}>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <h2 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, lineHeight: 1.3 }}>
                                        {pkgDetail.job_context?.title || 'Untitled'}
                                    </h2>
                                    <div style={{
                                        display: 'flex', alignItems: 'center', gap: '8px', marginTop: '3px',
                                        fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)',
                                    }}>
                                        <span>{pkgDetail.summary?.meta?.company_name}</span>
                                        {pkgDetail.job_context?.url && (
                                            <>
                                                <span style={{ opacity: 0.3 }}>&middot;</span>
                                                <a href={pkgDetail.job_context.url} target="_blank" rel="noreferrer"
                                                    style={{ color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                                                    JD <ExternalLink size={10} />
                                                </a>
                                            </>
                                        )}
                                        {pkgDetail.summary?.status && (
                                            <>
                                                <span style={{ opacity: 0.3 }}>&middot;</span>
                                                <span style={{
                                                    padding: '0 5px', borderRadius: '2px', fontSize: '.62rem', fontWeight: 600,
                                                    textTransform: 'uppercase',
                                                    background: pkgDetail.summary.status === 'complete' ? 'rgba(60,179,113,.10)' : 'rgba(200,144,42,.10)',
                                                    color: pkgDetail.summary.status === 'complete' ? 'var(--green)' : 'var(--amber)',
                                                }}>{pkgDetail.summary.status}</span>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </div>

                            {/* Context tabs */}
                            <div style={{
                                display: 'flex', gap: '0', padding: '0 20px', marginTop: '10px',
                            }}>
                                {([
                                    { key: 'overview' as ContextTab, label: 'Overview' },
                                    { key: 'strategy' as ContextTab, label: 'Strategy' },
                                    { key: 'jd' as ContextTab, label: 'Full JD' },
                                ]).map(t => (
                                    <button
                                        key={t.key}
                                        onClick={() => setContextTab(t.key)}
                                        style={{
                                            padding: '6px 14px', fontSize: '.72rem', fontFamily: 'var(--font-mono)',
                                            fontWeight: contextTab === t.key ? 600 : 400,
                                            color: contextTab === t.key ? 'var(--accent)' : 'var(--text-secondary)',
                                            background: 'transparent', border: 'none', cursor: 'pointer',
                                            borderBottom: contextTab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
                                            transition: 'color .1s',
                                        }}
                                    >
                                        {t.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Context panel content */}
                        <div style={{
                            flexShrink: 0, overflow: 'auto',
                            maxHeight: contextTab === 'overview' ? '180px' : '300px',
                            borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                            padding: '12px 20px',
                        }}>
                            {contextTab === 'overview' && (
                                <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                                    {/* Analysis highlights */}
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
                                            {analysis.key_requirements && Array.isArray(analysis.key_requirements) && (
                                                <div style={{ marginTop: '4px' }}>
                                                    <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.68rem' }}>Key reqs:</span>
                                                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '3px' }}>
                                                        {analysis.key_requirements.slice(0, 8).map((r: string, i: number) => (
                                                            <span key={i} style={{
                                                                fontFamily: 'var(--font-mono)', fontSize: '.62rem',
                                                                padding: '1px 6px', borderRadius: '2px',
                                                                background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                                                                color: 'var(--text)',
                                                            }}>{typeof r === 'string' ? r : (r as any)?.skill || JSON.stringify(r)}</span>
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

                                    {/* Strategy highlights */}
                                    {strategy && (
                                        <div style={{ flex: '1 1 280px', minWidth: 0 }}>
                                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: '6px' }}>
                                                Resume Strategy
                                            </div>
                                            {strategy.positioning && (
                                                <div style={{ fontSize: '.74rem', lineHeight: 1.4, color: 'var(--text)', marginBottom: '6px' }}>
                                                    {typeof strategy.positioning === 'string'
                                                        ? strategy.positioning.slice(0, 250)
                                                        : JSON.stringify(strategy.positioning).slice(0, 250)}
                                                </div>
                                            )}
                                            {strategy.emphasis_areas && Array.isArray(strategy.emphasis_areas) && (
                                                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                                                    {strategy.emphasis_areas.slice(0, 6).map((a: string, i: number) => (
                                                        <span key={i} style={{
                                                            fontFamily: 'var(--font-mono)', fontSize: '.62rem',
                                                            padding: '1px 6px', borderRadius: '2px',
                                                            background: 'rgba(75, 142, 240, 0.08)', border: '1px solid rgba(75, 142, 240, 0.15)',
                                                            color: 'var(--accent)',
                                                        }}>{a}</span>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {/* If no analysis or strategy, show a note */}
                                    {!analysis && !strategy && (
                                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.76rem', color: 'var(--text-secondary)' }}>
                                            No analysis or strategy data available for this package.
                                        </div>
                                    )}
                                </div>
                            )}

                            {contextTab === 'strategy' && (
                                <div style={{ display: 'flex', gap: '20px' }}>
                                    <StrategyCard label="Resume Strategy" data={strategy} />
                                    <StrategyCard label="Cover Strategy" data={coverStrategy} />
                                </div>
                            )}

                            {contextTab === 'jd' && (
                                <JdDisplay text={pkgDetail.job_context?.jd_text || pkgDetail.job_context?.snippet || ''} />
                            )}
                        </div>

                        {/* ── Main tab bar ── */}
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 20px',
                            borderBottom: '1px solid var(--border)', background: 'var(--surface)', flexShrink: 0,
                        }}>
                            <button
                                className={`btn btn-sm ${mainTab === 'diff' ? 'btn-primary' : 'btn-ghost'}`}
                                onClick={() => setMainTab('diff')}
                                style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '.74rem' }}
                            >
                                <FileDiff size={13} /> Diff Review
                            </button>
                            <button
                                className={`btn btn-sm ${mainTab === 'editor' ? 'btn-primary' : 'btn-ghost'}`}
                                onClick={() => setMainTab('editor')}
                                style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '.74rem' }}
                            >
                                <Pencil size={13} /> Edit &amp; Preview
                            </button>

                            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <select
                                    value={packageDoc}
                                    onChange={(e) => setPackageDoc(e.target.value as 'resume' | 'cover')}
                                    style={{
                                        padding: '3px 8px', borderRadius: '2px', fontSize: '.72rem',
                                        fontFamily: 'var(--font-mono)',
                                        border: '1px solid var(--border-bright)', background: 'var(--surface-3)',
                                        color: 'var(--text)', outline: 'none',
                                    }}
                                >
                                    <option value="resume">Resume</option>
                                    <option value="cover">Cover Letter</option>
                                </select>

                                {mainTab === 'diff' && (
                                    <button className="btn btn-ghost btn-sm" style={{ fontSize: '.68rem' }}
                                        onClick={() => {
                                            setDiffError('');
                                            setDiffBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
                                        }}>
                                        Refresh
                                    </button>
                                )}
                                {mainTab === 'editor' && (
                                    <>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)' }}>{saveStatus}</span>
                                        <button className="btn btn-primary btn-sm" style={{ fontSize: '.68rem' }} onClick={handleCompile}>Compile</button>
                                    </>
                                )}
                                <a
                                    className="btn btn-ghost btn-sm"
                                    style={{ fontSize: '.68rem', pointerEvents: resumePdfUrl ? 'auto' : 'none', opacity: resumePdfUrl ? 1 : 0.45 }}
                                    href={resumePdfUrl || undefined}
                                    download={`Conner_Jordan_Resume_${activeSlug || 'package'}.pdf`}
                                    title={resumePdfUrl ? 'Download finished resume PDF' : 'Resume PDF not available yet'}
                                >
                                    Download Resume PDF
                                </a>
                                <a
                                    className="btn btn-ghost btn-sm"
                                    style={{ fontSize: '.68rem', pointerEvents: coverPdfUrl ? 'auto' : 'none', opacity: coverPdfUrl ? 1 : 0.45 }}
                                    href={coverPdfUrl || undefined}
                                    download={`Conner_Jordan_Cover_Letter_${activeSlug || 'package'}.pdf`}
                                    title={coverPdfUrl ? 'Download finished cover letter PDF' : 'Cover letter PDF not available yet'}
                                >
                                    Download Cover PDF
                                </a>
                            </div>
                        </div>

                        {/* ── Main content area ── */}
                        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>

                            {mainTab === 'diff' && (
                                <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                                    {diffError && (
                                        <div style={{ padding: '8px 20px', fontSize: '.74rem', color: 'var(--red)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                                            {diffError}
                                        </div>
                                    )}
                                    <iframe
                                        src={activeSlug ? `/api/packages/${encodeURIComponent(activeSlug)}/diff-preview/${packageDoc}?v=${diffBuster[packageDoc]}#pagemode=none&view=Fit` : ''}
                                        style={{ flex: 1, border: 'none', width: '100%', background: '#525659' }}
                                        onError={() => setDiffError('Failed to load diff preview.')}
                                    />
                                </div>
                            )}

                            {mainTab === 'editor' && (
                                <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', overflow: 'hidden' }}>
                                    {/* LaTeX Editor */}
                                    <div style={{ display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)', overflow: 'hidden' }}>
                                        <textarea
                                            value={packageDoc === 'resume' ? resumeTex : coverTex}
                                            onChange={e => handleLatexChange(e.target.value)}
                                            style={{
                                                flex: 1, width: '100%', padding: '12px 14px',
                                                fontFamily: 'var(--font-mono)', fontSize: '.76rem', lineHeight: 1.6,
                                                resize: 'none', border: 'none', outline: 'none',
                                                background: 'var(--surface-3)', color: 'var(--text)',
                                            }}
                                        />
                                        {compileError && (
                                            <div style={{
                                                padding: '6px 14px', fontSize: '.72rem', color: 'var(--red)',
                                                fontFamily: 'var(--font-mono)', background: 'rgba(217,79,79,.06)',
                                                borderTop: '1px solid var(--border)', flexShrink: 0,
                                            }}>{compileError}</div>
                                        )}
                                    </div>

                                    {/* PDF Preview */}
                                    <iframe
                                        src={currentPdfUrl ? `${currentPdfUrl}#pagemode=none&view=Fit` : ''}
                                        style={{ width: '100%', height: '100%', border: 'none', background: '#525659' }}
                                    />
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
