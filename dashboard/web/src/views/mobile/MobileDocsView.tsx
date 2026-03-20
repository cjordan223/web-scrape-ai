import { useEffect, useCallback, useState } from 'react';
import { api } from '../../api';
import { safePdfName } from '../domains/tailoring/outputs/shared';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8899/api' : '/api';

type TabKey = 'packages' | 'applied';

interface PackageItem {
    slug: string;
    title: string;
    company: string;
    updated: string;
    status: string;
    hasResume: boolean;
    hasCover: boolean;
    applied: boolean;
}

interface AppliedItem {
    id: number;
    title: string;
    company: string;
    updated: string;
    status: string;
    followUpAt: string;
    applicationUrl: string;
    hasResume: boolean;
    hasCover: boolean;
}

function parsePackage(item: any): PackageItem {
    return {
        slug: item.slug,
        title: item.meta?.job_title || item.meta?.title || '(untitled)',
        company: item.meta?.company_name || item.meta?.company || '',
        updated: item.updated_at || '',
        status: item.status || '',
        hasResume: !!item.artifacts?.['Conner_Jordan_Resume.pdf'],
        hasCover: !!item.artifacts?.['Conner_Jordan_Cover_Letter.pdf'],
        applied: !!item.applied,
    };
}

function parseApplied(item: any): AppliedItem {
    return {
        id: item.id,
        title: item.job_title || item.package_slug || '(untitled)',
        company: item.company_name || '',
        updated: item.updated_at || item.applied_at || '',
        status: item.status || 'applied',
        followUpAt: item.follow_up_at || '',
        applicationUrl: item.application_url || '',
        hasResume: !!item.artifacts?.['Conner_Jordan_Resume.pdf'],
        hasCover: !!item.artifacts?.['Conner_Jordan_Cover_Letter.pdf'],
    };
}

function timeAgo(iso: string) {
    if (!iso) return '';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
}

function statusColor(status: string) {
    if (status === 'complete' || status === 'applied' || status === 'offer') return 'var(--green)';
    if (status === 'failed' || status === 'withdrawn' || status === 'rejected') return 'var(--red)';
    if (status === 'follow_up' || status === 'partial') return 'var(--amber)';
    return 'var(--text-secondary)';
}

export default function MobileDocsView() {
    const [tab, setTab] = useState<TabKey>('packages');
    const [packages, setPackages] = useState<PackageItem[]>([]);
    const [applied, setApplied] = useState<AppliedItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [expanded, setExpanded] = useState<string | null>(null);
    const [runnerLabel, setRunnerLabel] = useState('');

    const load = useCallback(() => {
        setLoading(true);
        Promise.all([
            api.getPackages().then((items: any[]) => setPackages(items.map(parsePackage))).catch(() => setPackages([])),
            api.getAppliedList().then((res: any) => setApplied((res.items || []).map(parseApplied))).catch(() => setApplied([])),
            api.getTailoringRunnerStatus().then((d) => setRunnerLabel(d.running ? `Tailoring job #${d.job?.id || d.active_item?.job_id}...` : '')).catch(() => setRunnerLabel('')),
        ]).finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        load();
        const id = setInterval(load, 15000);
        return () => clearInterval(id);
    }, [load]);

    const packageArtifactUrl = (slug: string, file: string) =>
        `${API_BASE}/tailoring/runs/${encodeURIComponent(slug)}/artifact/${encodeURIComponent(file)}`;

    const appliedArtifactUrl = (id: number, file: string) =>
        `${API_BASE}/applied/${encodeURIComponent(String(id))}/artifact/${encodeURIComponent(file)}`;

    const card: React.CSSProperties = {
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px',
        padding: '12px 14px', marginBottom: '8px',
    };
    const chip = (ok: boolean): React.CSSProperties => ({
        fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600,
        padding: '2px 6px', borderRadius: '3px', letterSpacing: '.04em',
        background: ok ? 'rgba(60,179,113,.15)' : 'rgba(82,96,112,.15)',
        color: ok ? 'var(--green)' : 'var(--text-secondary)',
    });
    const openBtn: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.78rem', fontWeight: 600,
        padding: '10px', borderRadius: '4px', border: '1px solid var(--border)',
        background: 'var(--surface-2)', color: 'var(--text)', textAlign: 'center',
        textDecoration: 'none', display: 'block', minHeight: '44px',
        lineHeight: '24px',
    };
    const hdr: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
    };

    return (
        <div style={{ padding: '12px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span style={hdr}>{tab === 'packages' ? `Packages (${packages.length})` : `Applied (${applied.length})`}</span>
                <button onClick={load} style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.68rem', background: 'transparent',
                    border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 10px',
                    color: 'var(--text-secondary)', cursor: 'pointer', minHeight: '32px',
                }}>Refresh</button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                <button className={`btn btn-sm ${tab === 'packages' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setTab('packages'); setExpanded(null); }}>
                    Packages
                </button>
                <button className={`btn btn-sm ${tab === 'applied' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setTab('applied'); setExpanded(null); }}>
                    Applied
                </button>
            </div>

            {runnerLabel && (
                <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--amber)',
                    padding: '8px 10px', background: 'rgba(200,144,42,.08)', borderRadius: '4px',
                    marginBottom: '10px', border: '1px solid rgba(200,144,42,.2)',
                }}>{runnerLabel}</div>
            )}

            {loading && <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--text-secondary)', padding: '20px 0', textAlign: 'center' }}>Loading...</div>}

            {!loading && tab === 'packages' && packages.length === 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--text-secondary)', padding: '20px 0', textAlign: 'center' }}>
                    No packages yet.
                </div>
            )}

            {!loading && tab === 'applied' && applied.length === 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--text-secondary)', padding: '20px 0', textAlign: 'center' }}>
                    No applied snapshots saved yet.
                </div>
            )}

            {!loading && tab === 'packages' && packages.map((item) => {
                const key = `package:${item.slug}`;
                return (
                    <div key={item.slug} style={card} onClick={() => setExpanded(expanded === key ? null : key)}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: '.82rem', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {item.title}
                                </div>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                    {item.company}{item.company && item.updated ? ' · ' : ''}{timeAgo(item.updated)}
                                    {item.status && <span style={{ marginLeft: '6px', color: statusColor(item.status) }}>{item.status}</span>}
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                                <span style={chip(item.hasResume)}>RES</span>
                                <span style={chip(item.hasCover)}>CVR</span>
                                {item.applied && <span style={{ ...chip(true), background: 'rgba(75,142,240,.16)', color: 'var(--accent)' }}>AP</span>}
                            </div>
                        </div>

                        {expanded === key && (
                            <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }} onClick={(e) => e.stopPropagation()}>
                                {item.hasResume ? (
                                    <a href={packageArtifactUrl(item.slug, 'Conner_Jordan_Resume.pdf')} download={safePdfName(item.company, item.title, item.slug, 'resume')} target="_blank" rel="noopener" style={openBtn}>
                                        Open Resume PDF
                                    </a>
                                ) : (
                                    <span style={{ ...openBtn, opacity: 0.4 }}>No Resume PDF</span>
                                )}
                                {item.hasCover ? (
                                    <a href={packageArtifactUrl(item.slug, 'Conner_Jordan_Cover_Letter.pdf')} download={safePdfName(item.company, item.title, item.slug, 'cover')} target="_blank" rel="noopener" style={openBtn}>
                                        Open Cover Letter PDF
                                    </a>
                                ) : (
                                    <span style={{ ...openBtn, opacity: 0.4 }}>No Cover Letter PDF</span>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}

            {!loading && tab === 'applied' && applied.map((item) => {
                const key = `applied:${item.id}`;
                return (
                    <div key={item.id} style={card} onClick={() => setExpanded(expanded === key ? null : key)}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: '.82rem', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {item.title}
                                </div>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                    {item.company}{item.company && item.updated ? ' · ' : ''}{timeAgo(item.updated)}
                                    <span style={{ marginLeft: '6px', color: statusColor(item.status) }}>{item.status}</span>
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                                <span style={chip(item.hasResume)}>RES</span>
                                <span style={chip(item.hasCover)}>CVR</span>
                            </div>
                        </div>

                        {expanded === key && (
                            <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }} onClick={(e) => e.stopPropagation()}>
                                {item.hasResume ? (
                                    <a href={appliedArtifactUrl(item.id, 'Conner_Jordan_Resume.pdf')} download={safePdfName(item.company, item.title, String(item.id), 'resume')} target="_blank" rel="noopener" style={openBtn}>
                                        Open Submitted Resume
                                    </a>
                                ) : (
                                    <span style={{ ...openBtn, opacity: 0.4 }}>No Resume PDF</span>
                                )}
                                {item.hasCover ? (
                                    <a href={appliedArtifactUrl(item.id, 'Conner_Jordan_Cover_Letter.pdf')} download={safePdfName(item.company, item.title, String(item.id), 'cover')} target="_blank" rel="noopener" style={openBtn}>
                                        Open Submitted Cover Letter
                                    </a>
                                ) : (
                                    <span style={{ ...openBtn, opacity: 0.4 }}>No Cover Letter PDF</span>
                                )}
                                {item.applicationUrl && (
                                    <a href={item.applicationUrl} target="_blank" rel="noopener" style={openBtn}>
                                        Open Application Link
                                    </a>
                                )}
                                {item.followUpAt && (
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--amber)', paddingTop: '4px' }}>
                                        Follow up: {new Date(item.followUpAt).toLocaleString()}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
