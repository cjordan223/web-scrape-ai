import { useEffect, useState } from 'react';
import { api } from '../../api';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8899/api' : '/api';

interface Pkg {
    slug: string;
    title: string;
    company: string;
    updated: string;
    status: string;
    hasResume: boolean;
    hasCover: boolean;
}

function parsePkg(p: any): Pkg {
    return {
        slug: p.slug,
        title: p.meta?.title || '(untitled)',
        company: p.meta?.company || '',
        updated: p.updated_at || '',
        status: p.status || '',
        hasResume: !!p.artifacts?.['Conner_Jordan_Resume.pdf'],
        hasCover: !!p.artifacts?.['Conner_Jordan_Cover_Letter.pdf'],
    };
}

export default function MobileDocsView() {
    const [packages, setPackages] = useState<Pkg[]>([]);
    const [loading, setLoading] = useState(true);
    const [expanded, setExpanded] = useState<string | null>(null);
    const [runnerLabel, setRunnerLabel] = useState('');

    const load = () => {
        setLoading(true);
        api.getPackages().then((items: any[]) => {
            setPackages(items.map(parsePkg));
        }).catch(() => {}).finally(() => setLoading(false));
        api.getTailoringRunnerStatus().then(d => {
            setRunnerLabel(d.running ? `Tailoring job #${d.job_id}...` : '');
        }).catch(() => {});
    };

    useEffect(() => { load(); }, []);

    const timeAgo = (iso: string) => {
        if (!iso) return '';
        const s = (Date.now() - new Date(iso).getTime()) / 1000;
        if (s < 3600) return `${Math.round(s / 60)}m ago`;
        if (s < 86400) return `${Math.round(s / 3600)}h ago`;
        return `${Math.round(s / 86400)}d ago`;
    };

    const artifactUrl = (slug: string, file: string) =>
        `${API_BASE}/tailoring/runs/${encodeURIComponent(slug)}/artifact/${encodeURIComponent(file)}`;

    const statusColor = (s: string) => {
        if (s === 'complete') return 'var(--green)';
        if (s === 'failed') return 'var(--red)';
        if (s === 'partial') return 'var(--amber)';
        return 'var(--text-secondary)';
    };

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
                <span style={hdr}>Packages ({packages.length})</span>
                <button onClick={load} style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.68rem', background: 'transparent',
                    border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 10px',
                    color: 'var(--text-secondary)', cursor: 'pointer', minHeight: '32px',
                }}>Refresh</button>
            </div>

            {runnerLabel && (
                <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--amber)',
                    padding: '8px 10px', background: 'rgba(200,144,42,.08)', borderRadius: '4px',
                    marginBottom: '10px', border: '1px solid rgba(200,144,42,.2)',
                }}>{runnerLabel}</div>
            )}

            {loading && <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--text-secondary)', padding: '20px 0', textAlign: 'center' }}>Loading...</div>}

            {packages.map(p => (
                <div key={p.slug} style={card} onClick={() => setExpanded(expanded === p.slug ? null : p.slug)}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: '.82rem', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {p.title}
                            </div>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                {p.company}{p.company && p.updated ? ' · ' : ''}{timeAgo(p.updated)}
                                {p.status && <span style={{ marginLeft: '6px', color: statusColor(p.status) }}>{p.status}</span>}
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                            <span style={chip(p.hasResume)}>RES</span>
                            <span style={chip(p.hasCover)}>CVR</span>
                        </div>
                    </div>

                    {expanded === p.slug && (
                        <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}
                            onClick={e => e.stopPropagation()}>
                            {p.hasResume ? (
                                <a href={artifactUrl(p.slug, 'Conner_Jordan_Resume.pdf')} target="_blank" rel="noopener" style={openBtn}>
                                    Open Resume PDF
                                </a>
                            ) : (
                                <span style={{ ...openBtn, opacity: 0.4 }}>No Resume PDF</span>
                            )}
                            {p.hasCover ? (
                                <a href={artifactUrl(p.slug, 'Conner_Jordan_Cover_Letter.pdf')} target="_blank" rel="noopener" style={openBtn}>
                                    Open Cover Letter PDF
                                </a>
                            ) : (
                                <span style={{ ...openBtn, opacity: 0.4 }}>No Cover Letter PDF</span>
                            )}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}
