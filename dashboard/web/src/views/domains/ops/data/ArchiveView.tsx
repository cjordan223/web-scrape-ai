import { useEffect, useState, useCallback } from 'react';
import { api } from '../../../../api';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { Archive, ChevronDown, ChevronRight } from 'lucide-react';

function timeAgo(iso: string | undefined | null) {
    if (!iso) return '';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
}

export default function ArchiveView() {
    const [archives, setArchives] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [status, setStatus] = useState('');
    const [expanded, setExpanded] = useState<number | null>(null);
    const [detail, setDetail] = useState<any>(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            setArchives(await api.getArchives());
        } catch { /* ignore */ }
        setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    const handleCreate = async () => {
        const tag = window.prompt('Archive tag (e.g. "v1-baseline"):');
        if (!tag) return;
        setCreating(true);
        setStatus('');
        try {
            const res = await api.createArchive(tag);
            if (res.ok) {
                setStatus(`Archived ${res.package_count} packages as "${res.tag}"`);
                load();
            } else {
                setStatus(`Error: ${res.error}`);
            }
        } catch (e: any) {
            setStatus(`Error: ${e.response?.data?.error || e.message}`);
        }
        setCreating(false);
        setTimeout(() => setStatus(''), 5000);
    };

    const toggleExpand = async (id: number) => {
        if (expanded === id) {
            setExpanded(null);
            setDetail(null);
            return;
        }
        setExpanded(id);
        try {
            setDetail(await api.getArchiveDetail(id));
        } catch {
            setDetail(null);
        }
    };

    return (
        <PageView>
            <PageHeader title="Archives" subtitle="TAILORING SNAPSHOTS" />
            <PagePrimary>

                {/* Create button + status */}
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px',
                }}>
                    <button
                        className="btn btn-sm"
                        disabled={creating}
                        onClick={handleCreate}
                        style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                        <Archive size={14} />
                        {creating ? 'Archiving...' : 'Archive All Packages'}
                    </button>
                    {status && (
                        <span style={{
                            fontSize: '.78rem', fontFamily: 'var(--font-mono)',
                            color: status.startsWith('Error') ? 'var(--red)' : 'var(--green)',
                        }}>
                            {status}
                        </span>
                    )}
                </div>

                {/* Archive list */}
                {loading ? (
                    <div style={{ color: 'var(--text-secondary)', fontSize: '.85rem' }}>Loading...</div>
                ) : archives.length === 0 ? (
                    <div style={{
                        padding: '40px 20px', textAlign: 'center',
                        color: 'var(--text-secondary)', fontSize: '.85rem',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        background: 'var(--surface)',
                    }}>
                        No archives yet. Click "Archive All Packages" to create one.
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {archives.map(a => (
                            <div key={a.id} style={{
                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                background: 'var(--surface)', overflow: 'hidden',
                            }}>
                                <div
                                    onClick={() => toggleExpand(a.id)}
                                    style={{
                                        padding: '12px 16px', cursor: 'pointer',
                                        display: 'flex', alignItems: 'center', gap: '10px',
                                    }}
                                >
                                    {expanded === a.id
                                        ? <ChevronDown size={14} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                                        : <ChevronRight size={14} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                                    }
                                    <span style={{ fontWeight: 600, fontSize: '.88rem' }}>{a.tag}</span>
                                    <span style={{
                                        fontSize: '.75rem', fontFamily: 'var(--font-mono)',
                                        color: 'var(--text-secondary)', marginLeft: 'auto',
                                    }}>
                                        {a.package_count} packages
                                    </span>
                                    <span style={{
                                        fontSize: '.72rem', fontFamily: 'var(--font-mono)',
                                        color: 'var(--text-secondary)',
                                    }}>
                                        {timeAgo(a.created_at)}
                                    </span>
                                </div>

                                {expanded === a.id && detail && (
                                    <div style={{
                                        borderTop: '1px solid var(--border)',
                                        padding: '14px 16px', background: 'var(--surface-2)',
                                    }}>
                                        {/* Config snapshot summary */}
                                        <div style={{
                                            fontSize: '.72rem', fontFamily: 'var(--font-mono)',
                                            color: 'var(--text-secondary)', marginBottom: '12px',
                                        }}>
                                            created {detail.created_at?.slice(0, 19).replace('T', ' ')}
                                            {detail.config_snapshot && (
                                                <span>
                                                    {' · config: '}
                                                    {Object.keys(detail.config_snapshot)
                                                        .filter(k => detail.config_snapshot[k] != null)
                                                        .join(', ')}
                                                </span>
                                            )}
                                        </div>

                                        {/* Package list */}
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                            {detail.packages?.map((p: any) => (
                                                <div key={p.slug} style={{
                                                    padding: '6px 10px', fontSize: '.78rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    background: 'var(--surface)',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: 'var(--radius)',
                                                }}>
                                                    <span style={{ color: 'var(--text)' }}>
                                                        {p.meta?.job_title || p.slug}
                                                    </span>
                                                    {p.meta?.company_name && (
                                                        <span style={{ color: 'var(--text-secondary)' }}>
                                                            {' — '}{p.meta.company_name}
                                                        </span>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}

            </PagePrimary>
        </PageView>
    );
}
