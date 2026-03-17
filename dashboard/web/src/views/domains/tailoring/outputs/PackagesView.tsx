import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import { FileDiff, Pencil, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react';
import PackageChatPanel from './PackageChatTab';
import { DetailContextSection, type ContextTab, timeAgo } from './shared';

type MainTab = 'diff' | 'editor';

function toLocalInputValue(isoDate?: string | null) {
    const date = isoDate ? new Date(isoDate) : new Date();
    const offsetMs = date.getTimezoneOffset() * 60_000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
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
    const [chatOpen, setChatOpen] = useState(false);
    const [applyFilter, setApplyFilter] = useState<'all' | 'unapplied' | 'applied'>('all');
    const [applyFormOpen, setApplyFormOpen] = useState(false);
    const [applyUrl, setApplyUrl] = useState('');
    const [applyAt, setApplyAt] = useState(toLocalInputValue());
    const [applyFollowUpAt, setApplyFollowUpAt] = useState('');
    const [applyNotes, setApplyNotes] = useState('');
    const [applyBusy, setApplyBusy] = useState(false);
    const [applyError, setApplyError] = useState('');
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);


    const fetchPackages = useCallback(async () => {
        try {
            const res = await api.getPackages();
            setData(res);
            if (res.length > 0) {
                setActiveSlug((current) => current || res[0].slug);
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadDetail = useCallback(async (slug: string) => {
        const res = await api.getPackageDetail(slug);
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
        setApplyFormOpen(false);
        setApplyError('');
        setApplyUrl(res.summary?.applied?.application_url || res.job_context?.url || res.summary?.meta?.url || '');
        setApplyAt(toLocalInputValue(res.summary?.applied?.applied_at || new Date().toISOString()));
        setApplyFollowUpAt(res.summary?.applied?.follow_up_at ? toLocalInputValue(res.summary.applied.follow_up_at) : '');
        setApplyNotes(res.summary?.applied?.notes || '');
        return res;
    }, []);

    useEffect(() => {
        fetchPackages();
    }, [fetchPackages]);

    useEffect(() => {
        const fetchDetail = async () => {
            if (!activeSlug) {
                setPkgDetail(null);
                return;
            }
            try {
                await loadDetail(activeSlug);
            } catch (err) {
                console.error(err);
                setPkgDetail(null);
            }
        };
        fetchDetail();
    }, [activeSlug, loadDetail]);

    const persistLatex = async (slug: string, doc: 'resume' | 'cover', content: string) => {
        await api.savePackageLatex(slug, doc, content);
        setDiffBuster(prev => ({ ...prev, [doc]: Date.now() }));
    };

    const handleLatexChange = (val: string) => {
        if (packageDoc === 'resume') setResumeTex(val);
        else setCoverTex(val);

        setSaveStatus('saving...');
        if (saveTimer.current) clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(async () => {
            try {
                await persistLatex(activeSlug!, packageDoc, val);
                setSaveStatus('saved');
            } catch {
                setSaveStatus('save failed');
            }
        }, 900);
    };

    const handleCompile = async () => {
        if (!activeSlug) return;
        const currentTex = packageDoc === 'resume' ? resumeTex : coverTex;
        setCompileError('');
        setSaveStatus('saving...');
        if (saveTimer.current) {
            clearTimeout(saveTimer.current);
            saveTimer.current = null;
        }
        try {
            await persistLatex(activeSlug, packageDoc, currentTex);
            setSaveStatus('compiling...');
            const result = await api.compilePackageDoc(activeSlug, packageDoc);
            if (!result?.ok) {
                setCompileError(result?.error || 'compile failed');
                setSaveStatus('compile failed');
                return;
            }
            setSaveStatus('compiled');
            setPreviewBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
            setDiffBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
        } catch (e: any) {
            const errorMessage = e.response?.data?.error || (e.message === 'Network Error' ? 'save failed' : 'compile failed');
            setCompileError(errorMessage);
            setSaveStatus(errorMessage === 'save failed' ? 'save failed' : 'compile failed');
        }
    };

    const handleMarkApplied = async () => {
        if (!activeSlug) return;
        setApplyBusy(true);
        setApplyError('');
        try {
            const payload = {
                application_url: applyUrl || null,
                applied_at: applyAt ? new Date(applyAt).toISOString() : null,
                follow_up_at: applyFollowUpAt ? new Date(applyFollowUpAt).toISOString() : null,
                notes: applyNotes || null,
            };
            await api.applyPackage(activeSlug, payload);
            await fetchPackages();
            await loadDetail(activeSlug);
        } catch (e: any) {
            setApplyError(e.response?.data?.error || 'Failed to save applied snapshot');
        } finally {
            setApplyBusy(false);
        }
    };

    const filteredData = data.filter((item) => {
        if (applyFilter === 'applied') return Boolean(item.applied);
        if (applyFilter === 'unapplied') return !item.applied;
        return true;
    });

    useEffect(() => {
        if (!filteredData.some((item) => item.slug === activeSlug)) {
            setActiveSlug(filteredData[0]?.slug || null);
        }
    }, [filteredData, activeSlug]);

    const activePkg = filteredData.find(p => p.slug === activeSlug) || data.find(p => p.slug === activeSlug);
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
    const strategy = pkgDetail?.resume_strategy;
    const coverStrategy = pkgDetail?.cover_strategy;
    const analysis = pkgDetail?.analysis;
    const appliedSummary = pkgDetail?.summary?.applied;

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
                    <div style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em',
                        marginBottom: '8px',
                    }}>
                        Packages ({filteredData.length})
                    </div>
                    <div style={{ display: 'flex', gap: '6px' }}>
                        {([
                            ['all', 'All'],
                            ['unapplied', 'Unapplied'],
                            ['applied', 'Applied'],
                        ] as const).map(([value, label]) => (
                            <button
                                key={value}
                                className={`btn btn-sm ${applyFilter === value ? 'btn-primary' : 'btn-ghost'}`}
                                style={{ fontSize: '.66rem', flex: 1 }}
                                onClick={() => setApplyFilter(value)}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {filteredData.map((item) => {
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
                                    {item.meta?.job_title || item.meta?.title || item.slug}
                                </div>
                                <div style={{
                                    display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px',
                                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)',
                                }}>
                                    <span>{item.meta?.company_name || item.meta?.company || '--'}</span>
                                    <span style={{ opacity: 0.4 }}>&middot;</span>
                                    <span>{timeAgo(item.updated_at)}</span>
                                </div>
                                <div style={{ display: 'flex', gap: '4px', marginTop: '5px', flexWrap: 'wrap' }}>
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
                                    {item.applied && (
                                        <span style={{
                                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 600,
                                            padding: '1px 5px', borderRadius: '2px',
                                            background: 'rgba(75,142,240,.12)', color: 'var(--accent)',
                                        }}>
                                            APPLIED
                                        </span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* ══════════ MAIN CONTENT ══════════ */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

                {filteredData.length === 0 ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, fontFamily: 'var(--font-mono)', fontSize: '.82rem', color: 'var(--text-secondary)' }}>
                        No packages match the current filter.
                    </div>
                ) : !pkgDetail ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
                        <div className="spinner" />
                    </div>
                ) : (
                    <>
                        <DetailContextSection
                            title={pkgDetail.job_context?.title || 'Untitled'}
                            companyName={pkgDetail.summary?.meta?.company_name || pkgDetail.summary?.meta?.company}
                            jobUrl={pkgDetail.job_context?.url}
                            status={pkgDetail.summary?.status}
                            badges={(
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                    {appliedSummary && (
                                        <a
                                            className="btn btn-ghost btn-sm"
                                            href={`/tailoring/outputs/applied?application_id=${encodeURIComponent(String(appliedSummary.id))}`}
                                            style={{ fontSize: '.68rem' }}
                                        >
                                            View Applied
                                        </a>
                                    )}
                                    {!appliedSummary && (
                                        <button
                                            className="btn btn-primary btn-sm"
                                            style={{ fontSize: '.68rem' }}
                                            onClick={() => setApplyFormOpen((open) => !open)}
                                        >
                                            Mark Applied
                                        </button>
                                    )}
                                </div>
                            )}
                            contextTab={contextTab}
                            onContextTabChange={setContextTab}
                            analysis={analysis}
                            resumeStrategy={strategy}
                            coverStrategy={coverStrategy}
                            jobContext={pkgDetail.job_context}
                            emptyNote="No analysis or strategy data available for this package."
                        />

                        {applyFormOpen && !appliedSummary && (
                            <div style={{
                                borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                                padding: '12px 20px', display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '12px',
                            }}>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Application URL</span>
                                    <input
                                        value={applyUrl}
                                        onChange={(e) => setApplyUrl(e.target.value)}
                                        style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}
                                    />
                                </label>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Applied At</span>
                                    <input
                                        type="datetime-local"
                                        value={applyAt}
                                        onChange={(e) => setApplyAt(e.target.value)}
                                        style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}
                                    />
                                </label>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Follow Up</span>
                                    <input
                                        type="datetime-local"
                                        value={applyFollowUpAt}
                                        onChange={(e) => setApplyFollowUpAt(e.target.value)}
                                        style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}
                                    />
                                </label>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', gridColumn: '1 / -1' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Notes</span>
                                    <textarea
                                        value={applyNotes}
                                        onChange={(e) => setApplyNotes(e.target.value)}
                                        style={{
                                            minHeight: '74px', resize: 'vertical', borderRadius: '6px', border: '1px solid var(--border)',
                                            background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px',
                                        }}
                                    />
                                </label>
                                <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <button className="btn btn-primary btn-sm" onClick={handleMarkApplied} disabled={applyBusy}>
                                        {applyBusy ? 'Saving Snapshot...' : 'Save Applied Snapshot'}
                                    </button>
                                    <button className="btn btn-ghost btn-sm" onClick={() => setApplyFormOpen(false)} disabled={applyBusy}>
                                        Cancel
                                    </button>
                                    {applyError && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--red)' }}>{applyError}</span>}
                                </div>
                            </div>
                        )}

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

                        {/* ── Main content area + chat panel ── */}
                        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

                            {/* Document view */}
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

                            {/* ── Chat bottom panel ── */}
                            {activeSlug && (
                                <div style={{
                                    flexShrink: 0, borderTop: '1px solid var(--border)',
                                    display: 'flex', flexDirection: 'column',
                                    height: chatOpen ? '340px' : '32px',
                                    transition: 'height .15s ease',
                                    overflow: 'hidden',
                                }}>
                                    {/* Toggle bar */}
                                    <button
                                        onClick={() => setChatOpen(prev => !prev)}
                                        style={{
                                            display: 'flex', alignItems: 'center', gap: '6px',
                                            padding: '6px 14px', background: 'var(--surface-2)',
                                            border: 'none', borderBottom: chatOpen ? '1px solid var(--border)' : 'none',
                                            cursor: 'pointer', flexShrink: 0,
                                            fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 600,
                                            color: 'var(--text-secondary)', textTransform: 'uppercase',
                                            letterSpacing: '.08em', width: '100%', textAlign: 'left',
                                        }}
                                    >
                                        <MessageSquare size={12} />
                                        Chat Workspace
                                        <span style={{ fontSize: '.6rem', fontWeight: 400, opacity: 0.6 }}>
                                            ({packageDoc})
                                        </span>
                                        <span style={{ fontSize: '.58rem', fontWeight: 400, opacity: 0.55 }}>
                                            q&a + edits
                                        </span>
                                        <span style={{ marginLeft: 'auto' }}>
                                            {chatOpen ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
                                        </span>
                                    </button>

                                    {/* Chat content */}
                                    {chatOpen && (
                                        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                                            <PackageChatPanel
                                                slug={activeSlug}
                                                docFocus={packageDoc}
                                                onDocUpdated={async () => {
                                                    try {
                                                        await loadDetail(activeSlug!);
                                                    } catch {}
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
