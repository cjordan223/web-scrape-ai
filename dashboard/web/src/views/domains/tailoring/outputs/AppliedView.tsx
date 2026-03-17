import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../../../api';
import { DetailContextSection, type ContextTab, timeAgo } from './shared';

type PackageDoc = 'resume' | 'cover';
type DocumentMode = 'preview' | 'latex';

const STATUS_OPTIONS = [
    { value: 'applied', label: 'Applied' },
    { value: 'follow_up', label: 'Follow Up' },
    { value: 'withdrawn', label: 'Withdrawn' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'offer', label: 'Offer' },
];

function toLocalInputValue(isoDate?: string | null) {
    if (!isoDate) return '';
    const date = new Date(isoDate);
    const offsetMs = date.getTimezoneOffset() * 60_000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export default function AppliedView() {
    const [searchParams] = useSearchParams();
    const requestedId = Number(searchParams.get('application_id') || '');

    const [items, setItems] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [activeId, setActiveId] = useState<number | null>(Number.isFinite(requestedId) && requestedId > 0 ? requestedId : null);
    const [detail, setDetail] = useState<any>(null);
    const [contextTab, setContextTab] = useState<ContextTab>('overview');
    const [packageDoc, setPackageDoc] = useState<PackageDoc>('resume');
    const [documentMode, setDocumentMode] = useState<DocumentMode>('preview');
    const [status, setStatus] = useState('applied');
    const [applicationUrl, setApplicationUrl] = useState('');
    const [appliedAt, setAppliedAt] = useState('');
    const [followUpAt, setFollowUpAt] = useState('');
    const [notes, setNotes] = useState('');
    const [saveBusy, setSaveBusy] = useState(false);
    const [saveMessage, setSaveMessage] = useState('');

    const loadList = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.getAppliedList();
            const nextItems = res.items || [];
            setItems(nextItems);
            if (nextItems.length > 0) {
                setActiveId((current) => {
                    if (requestedId && nextItems.some((item: any) => item.id === requestedId)) {
                        return requestedId;
                    }
                    if (current && nextItems.some((item: any) => item.id === current)) {
                        return current;
                    }
                    return nextItems[0].id;
                });
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [requestedId]);

    const loadDetail = useCallback(async (applicationId: number) => {
        const res = await api.getAppliedDetail(applicationId);
        setDetail(res);
        setContextTab('overview');
        setStatus(res.summary?.status || 'applied');
        setApplicationUrl(res.summary?.application_url || '');
        setAppliedAt(toLocalInputValue(res.summary?.applied_at));
        setFollowUpAt(toLocalInputValue(res.summary?.follow_up_at));
        setNotes(res.summary?.notes || '');
        setSaveMessage('');
    }, []);

    useEffect(() => {
        loadList();
    }, [loadList]);

    useEffect(() => {
        if (!activeId) return;
        loadDetail(activeId).catch((err) => {
            console.error(err);
            setDetail(null);
        });
    }, [activeId, loadDetail]);

    const currentItem = items.find((item) => item.id === activeId);
    const artifactBase = activeId ? `/api/applied/${encodeURIComponent(String(activeId))}/artifact` : '';
    const resumePdfUrl = activeId ? `${artifactBase}/Conner_Jordan_Resume.pdf` : '';
    const coverPdfUrl = activeId ? `${artifactBase}/Conner_Jordan_Cover_Letter.pdf` : '';
    const currentPdfUrl = packageDoc === 'resume' ? resumePdfUrl : coverPdfUrl;

    const handleSaveTracking = async () => {
        if (!activeId) return;
        setSaveBusy(true);
        setSaveMessage('');
        try {
            await api.updateAppliedTracking(activeId, {
                status,
                application_url: applicationUrl || null,
                applied_at: appliedAt ? new Date(appliedAt).toISOString() : null,
                follow_up_at: followUpAt ? new Date(followUpAt).toISOString() : null,
                notes: notes || null,
            });
            await loadList();
            await loadDetail(activeId);
            setSaveMessage('Tracking saved');
        } catch (e: any) {
            setSaveMessage(e.response?.data?.error || 'Failed to update tracking');
        } finally {
            setSaveBusy(false);
        }
    };

    if (loading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <div className="spinner" />
            </div>
        );
    }

    if (items.length === 0) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 'calc(100vh - 56px)', flexDirection: 'column', gap: '12px' }}>
                <span style={{ fontSize: '1.6rem', opacity: 0.2 }}>&#10003;</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.82rem', color: 'var(--text-secondary)' }}>No applied job snapshots saved yet.</span>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>
            <div style={{
                width: '300px', flexShrink: 0, display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border)', background: 'var(--surface)', overflow: 'hidden',
            }}>
                <div style={{
                    padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                    fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600,
                    color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em',
                }}>
                    Applied ({items.length})
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {items.map((item) => {
                        const isActive = activeId === item.id;
                        return (
                            <div
                                key={item.id}
                                onClick={() => setActiveId(item.id)}
                                style={{
                                    padding: '10px 14px', cursor: 'pointer',
                                    borderBottom: '1px solid var(--border)',
                                    borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                                    background: isActive ? 'var(--accent-light)' : 'transparent',
                                    transition: 'background .08s',
                                }}
                                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--surface-2)'; }}
                                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = isActive ? 'var(--accent-light)' : 'transparent'; }}
                            >
                                <div style={{
                                    fontWeight: 600, fontSize: '.8rem', lineHeight: 1.3,
                                    overflow: 'hidden', textOverflow: 'ellipsis',
                                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                                }}>
                                    {item.job_title || item.package_slug}
                                </div>
                                <div style={{
                                    display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px',
                                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', flexWrap: 'wrap',
                                }}>
                                    <span>{item.company_name || '--'}</span>
                                    <span style={{ opacity: 0.4 }}>&middot;</span>
                                    <span>{timeAgo(item.updated_at || item.applied_at)}</span>
                                </div>
                                <div style={{ display: 'flex', gap: '4px', marginTop: '6px', flexWrap: 'wrap' }}>
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 600,
                                        padding: '1px 5px', borderRadius: '2px',
                                        background: 'rgba(75,142,240,.12)', color: 'var(--accent)',
                                    }}>
                                        {item.status}
                                    </span>
                                    {item.follow_up_at && (
                                        <span style={{
                                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', fontWeight: 500,
                                            padding: '1px 5px', borderRadius: '2px',
                                            background: 'rgba(200,144,42,.12)', color: 'var(--amber)',
                                        }}>
                                            follow-up
                                        </span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {!detail ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
                        <div className="spinner" />
                    </div>
                ) : (
                    <>
                        <DetailContextSection
                            title={detail.job_context?.title || detail.summary?.job_title || 'Untitled'}
                            companyName={detail.summary?.company_name || detail.summary?.meta?.company_name || detail.summary?.meta?.company}
                            jobUrl={detail.job_context?.url || detail.summary?.job_url}
                            status={detail.summary?.status}
                            extraMeta={(
                                <>
                                    <span style={{ opacity: 0.3 }}>&middot;</span>
                                    <span>saved {timeAgo(detail.summary?.created_at)}</span>
                                </>
                            )}
                            badges={(
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)' }}>
                                    snapshot: {detail.summary?.package_slug}
                                </div>
                            )}
                            contextTab={contextTab}
                            onContextTabChange={setContextTab}
                            analysis={detail.analysis}
                            resumeStrategy={detail.resume_strategy}
                            coverStrategy={detail.cover_strategy}
                            jobContext={detail.job_context}
                            emptyNote="No analysis or strategy data were stored in this applied snapshot."
                        />

                        <div style={{
                            borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                            padding: '12px 20px', display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '12px',
                        }}>
                            <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Status</span>
                                <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}>
                                    {STATUS_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </label>
                            <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Application URL</span>
                                <input value={applicationUrl} onChange={(e) => setApplicationUrl(e.target.value)} style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }} />
                            </label>
                            <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Applied At</span>
                                <input type="datetime-local" value={appliedAt} onChange={(e) => setAppliedAt(e.target.value)} style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }} />
                            </label>
                            <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Follow Up</span>
                                <input type="datetime-local" value={followUpAt} onChange={(e) => setFollowUpAt(e.target.value)} style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }} />
                            </label>
                            <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', gridColumn: '1 / -1' }}>
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Notes</span>
                                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} style={{ minHeight: '74px', resize: 'vertical', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }} />
                            </label>
                            <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '10px' }}>
                                <button className="btn btn-primary btn-sm" onClick={handleSaveTracking} disabled={saveBusy}>
                                    {saveBusy ? 'Saving...' : 'Save Tracking'}
                                </button>
                                {currentItem?.applicationUrl && (
                                    <a className="btn btn-ghost btn-sm" href={currentItem.applicationUrl} target="_blank" rel="noreferrer">
                                        Open Application
                                    </a>
                                )}
                                {saveMessage && (
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.72rem',
                                        color: saveMessage === 'Tracking saved' ? 'var(--green)' : 'var(--red)',
                                    }}>
                                        {saveMessage}
                                    </span>
                                )}
                            </div>
                        </div>

                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 20px',
                            borderBottom: '1px solid var(--border)', background: 'var(--surface)', flexShrink: 0,
                        }}>
                            <select
                                value={packageDoc}
                                onChange={(e) => setPackageDoc(e.target.value as PackageDoc)}
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
                            <button className={`btn btn-sm ${documentMode === 'preview' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setDocumentMode('preview')} style={{ fontSize: '.68rem' }}>
                                Preview
                            </button>
                            <button className={`btn btn-sm ${documentMode === 'latex' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setDocumentMode('latex')} style={{ fontSize: '.68rem' }}>
                                LaTeX
                            </button>
                            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <a
                                    className="btn btn-ghost btn-sm"
                                    style={{ fontSize: '.68rem', pointerEvents: resumePdfUrl ? 'auto' : 'none', opacity: resumePdfUrl ? 1 : 0.45 }}
                                    href={resumePdfUrl || undefined}
                                    download={`Conner_Jordan_Resume_${detail.summary?.package_slug || 'applied'}.pdf`}
                                >
                                    Download Resume PDF
                                </a>
                                <a
                                    className="btn btn-ghost btn-sm"
                                    style={{ fontSize: '.68rem', pointerEvents: coverPdfUrl ? 'auto' : 'none', opacity: coverPdfUrl ? 1 : 0.45 }}
                                    href={coverPdfUrl || undefined}
                                    download={`Conner_Jordan_Cover_Letter_${detail.summary?.package_slug || 'applied'}.pdf`}
                                >
                                    Download Cover PDF
                                </a>
                            </div>
                        </div>

                        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', background: documentMode === 'preview' ? '#525659' : 'var(--surface-3)' }}>
                            {documentMode === 'preview' ? (
                                <iframe
                                    src={currentPdfUrl ? `${currentPdfUrl}#pagemode=none&view=Fit` : ''}
                                    style={{ width: '100%', height: '100%', border: 'none', background: '#525659' }}
                                />
                            ) : (
                                <textarea
                                    readOnly
                                    value={packageDoc === 'resume' ? detail.latex?.resume || '' : detail.latex?.cover || ''}
                                    style={{
                                        width: '100%', height: '100%', border: 'none', outline: 'none', resize: 'none',
                                        padding: '16px', fontFamily: 'var(--font-mono)', fontSize: '.76rem', lineHeight: 1.6,
                                        background: 'var(--surface-3)', color: 'var(--text)',
                                    }}
                                />
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
