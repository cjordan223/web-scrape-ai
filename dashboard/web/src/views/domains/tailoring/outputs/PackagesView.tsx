import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import { ExternalLink } from 'lucide-react';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { EmptyState, LoadingState } from '../../../../components/workflow/States';

function timeAgo(isoDate: string | undefined | null) {
    if (!isoDate) return 'Never';
    const d = new Date(isoDate);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

export default function PackagesView() {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [pkgDetail, setPkgDetail] = useState<any>(null);

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
            } catch (e) {
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

    // Derive PDF filename from the artifacts listed in the package data
    const activePkg = data.find(p => p.slug === activeSlug);
    const pdfKey = packageDoc === 'resume'
        ? Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Resume.pdf'))
        : Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Cover_Letter.pdf'));
    const currentPdfUrl = activeSlug && pdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(pdfKey)}?v=${previewBuster[packageDoc]}`
        : '';

    return (
        <PageView>
            <PageHeader title="Application Packages" />
            <PagePrimary>
            {loading ? (
                <LoadingState />
            ) : data.length === 0 ? (
                <EmptyState icon="🖊" text="No document packages generated yet." />
            ) : (
                <div className="pkg-grid">
                    {/* List of packages */}
                    <div className="pkg-list">
                        {data.map((item) => (
                            <div
                                key={item.slug}
                                className={`pkg-item ${activeSlug === item.slug ? 'active' : ''}`}
                                onClick={() => setActiveSlug(item.slug)}
                            >
                                <div style={{ fontWeight: 600, fontSize: '.85rem' }}>{item.meta?.job_title || item.slug}</div>
                                <div style={{ fontSize: '.75rem', color: 'var(--text-secondary)' }}>
                                    {item.meta?.company_name} &middot; {timeAgo(item.updated_at)}
                                </div>
                                <div style={{ marginTop: '4px', display: 'flex', gap: '4px' }}>
                                    <span className={`pill ${item.artifacts['Conner_Jordan_Resume.pdf'] ? 'pill-success' : 'pill-fail'}`} style={{ fontSize: '0.65rem' }}>Resume</span>
                                    <span className={`pill ${item.artifacts['Conner_Jordan_Cover_Letter.pdf'] ? 'pill-success' : 'pill-fail'}`} style={{ fontSize: '0.65rem' }}>Cover Letter</span>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Package details */}
                    <div className="pkg-main">
                        {!pkgDetail ? (
                            <LoadingState />
                        ) : (
                            <>
                                <div style={{ display: 'flex', gap: '16px', alignItems: 'center', background: '#fff', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                    <div style={{ flex: 1 }}>
                                        <h2 style={{ fontSize: '1.2rem', marginBottom: '4px' }}>{pkgDetail.job_context?.title}</h2>
                                        <div style={{ color: 'var(--text-secondary)' }}>
                                            {pkgDetail.summary?.meta?.company_name} &middot; <a href={pkgDetail.job_context?.url} target="_blank" rel="noreferrer" className="ext-link">Original JD <ExternalLink size={12} display="inline" /></a>
                                        </div>
                                    </div>
                                </div>

                                <div className="editor-grid" style={{ marginTop: '16px' }}>
                                    {/* LaTeX Editor */}
                                    <div className="doc-box">
                                        <div className="doc-box-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                                            <div style={{ whiteSpace: 'nowrap' }}>Live LaTeX Editor</div>
                                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                                                <span style={{ fontSize: '.8rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{saveStatus}</span>
                                                <select
                                                    value={packageDoc}
                                                    onChange={(e) => setPackageDoc(e.target.value as 'resume' | 'cover')}
                                                    style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)' }}
                                                >
                                                    <option value="resume">Resume</option>
                                                    <option value="cover">Cover Letter</option>
                                                </select>
                                                <button className="btn btn-primary btn-sm" onClick={handleCompile}>Compile</button>
                                            </div>
                                        </div>
                                        <div className="doc-box-body" style={{ display: 'flex', flexDirection: 'column' }}>
                                            {packageDoc === 'resume' ? (
                                                <textarea
                                                    className="latex-editor"
                                                    value={resumeTex}
                                                    onChange={e => handleLatexChange(e.target.value)}
                                                    style={{ flex: 1, border: 'none', resize: 'none' }}
                                                />
                                            ) : (
                                                <textarea
                                                    className="latex-editor"
                                                    value={coverTex}
                                                    onChange={e => handleLatexChange(e.target.value)}
                                                    style={{ flex: 1, border: 'none', resize: 'none' }}
                                                />
                                            )}
                                            {compileError && <div style={{ fontSize: '.8rem', color: 'var(--red)', marginTop: '8px' }}>{compileError}</div>}
                                        </div>
                                    </div>

                                    {/* PDF Previewer */}
                                    <div className="doc-box">
                                        <div className="doc-box-header">Live PDF Preview</div>
                                        <div className="doc-box-body" style={{ height: '620px', maxHeight: 'none', padding: 0 }}>
                                            <iframe src={currentPdfUrl} style={{ width: '100%', height: '620px', border: 0 }}></iframe>
                                        </div>
                                    </div>
                                </div>

                                <WorkflowPanel
                                    title="Generated Content Highlight (vs Baseline)"
                                    right={<button className="btn btn-ghost btn-sm" onClick={() => {
                                            setDiffError('');
                                            setDiffBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
                                        }}>Refresh Highlighted PDF</button>}
                                    style={{ marginTop: '16px' }}
                                >
                                    <div className="stats-bar">
                                        <span>This diff preview highlights generated edits versus the baseline template.</span>
                                    </div>
                                    <div className="doc-box-body" style={{ height: '760px', maxHeight: 'none', padding: 0 }}>
                                        <iframe
                                            src={activeSlug ? `/api/packages/${encodeURIComponent(activeSlug)}/diff-preview/${packageDoc}?v=${diffBuster[packageDoc]}` : ''}
                                            style={{ width: '100%', height: '760px', border: 0 }}
                                            onError={() => setDiffError('Failed to load highlighted diff preview.')}
                                        ></iframe>
                                    </div>
                                    {diffError && <div style={{ fontSize: '.8rem', color: 'var(--red)', marginTop: '8px' }}>{diffError}</div>}
                                </WorkflowPanel>

                                <div className="editor-grid" style={{ marginTop: '16px' }}>
                                    <div className="doc-box">
                                        <div className="doc-box-header">Full Job Description</div>
                                        <div className="doc-box-body">
                                            <pre>{pkgDetail.job_context?.jd_text || pkgDetail.job_context?.snippet || 'No JD available'}</pre>
                                        </div>
                                    </div>
                                    <div className="doc-box">
                                        <div className="doc-box-header">Resume Strategy JSON</div>
                                        <div className="doc-box-body">
                                            <pre>{pkgDetail.resume_strategy ? JSON.stringify(pkgDetail.resume_strategy, null, 2) : 'No strategy file'}</pre>
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
            </PagePrimary>
        </PageView>
    );
}
