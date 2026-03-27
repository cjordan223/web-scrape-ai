import { useState, useEffect, useCallback } from 'react';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';

interface Lead {
    id: number;
    title?: string;
    url?: string;
    board?: string;
    created_at?: string;
    company?: string;
    location?: string;
    snippet?: string;
}

const PANEL_BG = 'rgba(19, 24, 31, 0.97)';

export default function LeadsView() {
    const [leads, setLeads] = useState<Lead[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');

    const fetchLeads = useCallback(async () => {
        try {
            const res = await api.getLeads(2000, {
                search: search || undefined,
            });
            const items = res.items || [];
            setLeads(items);
            setTotal(res.total ?? items.length);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [search]);

    useEffect(() => {
        fetchLeads();
        const interval = setInterval(fetchLeads, 60000);
        return () => clearInterval(interval);
    }, [fetchLeads]);

    if (loading) {
        return <div className="view-container"><div className="loading"><div className="spinner" /></div></div>;
    }

    return (
        <div style={{ height: 'calc(100vh - 56px)', overflow: 'hidden', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                <div style={{
                    padding: '14px 16px',
                    borderBottom: '1px solid rgba(100, 160, 220, 0.16)',
                    background: PANEL_BG,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.94rem',
                            fontWeight: 700,
                            color: '#f4ede8',
                        }}>
                            Leads
                        </span>
                        <span style={{
                            fontFamily: 'var(--font)',
                            fontSize: '.76rem',
                            fontWeight: 500,
                            color: 'rgba(233, 220, 210, 0.78)',
                        }}>
                            HN Hiring finds — browse and ingest when ready. {total} leads.
                        </span>
                    </div>
                </div>

                <div style={{
                    padding: '10px 14px',
                    borderBottom: '1px solid rgba(100, 160, 220, 0.12)',
                    background: 'linear-gradient(180deg, rgba(100, 160, 220, 0.05), rgba(19, 24, 31, 0.98))',
                }}>
                    <input
                        type="text"
                        placeholder="Search by company or title..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        style={{
                            width: '100%',
                            padding: '8px 12px',
                            fontFamily: 'var(--font)',
                            fontSize: '.82rem',
                            background: 'rgba(31, 39, 52, 0.7)',
                            border: '1px solid rgba(100, 160, 220, 0.18)',
                            borderRadius: '8px',
                            color: '#eef3ff',
                            outline: 'none',
                        }}
                    />
                </div>

                <div style={{ flex: 1, overflowY: 'auto', padding: '0' }}>
                    {leads.length === 0 ? (
                        <div style={{
                            padding: '40px 20px',
                            textAlign: 'center',
                            fontFamily: 'var(--font)',
                            fontSize: '.84rem',
                            color: 'rgba(233, 220, 210, 0.5)',
                        }}>
                            No leads found.
                        </div>
                    ) : (
                        leads.map((lead) => (
                            <div
                                key={lead.id}
                                style={{
                                    padding: '12px 16px',
                                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                                    cursor: 'pointer',
                                }}
                                onClick={() => lead.url && window.open(lead.url, '_blank')}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '4px' }}>
                                    <span style={{
                                        fontFamily: 'var(--font)',
                                        fontSize: '.84rem',
                                        fontWeight: 700,
                                        color: '#eef3ff',
                                    }}>
                                        {lead.company || 'Unknown'}
                                    </span>
                                    <span style={{
                                        fontFamily: 'var(--font)',
                                        fontSize: '.7rem',
                                        color: 'rgba(233, 220, 210, 0.45)',
                                    }}>
                                        {lead.created_at ? timeAgo(lead.created_at) : ''}
                                    </span>
                                </div>
                                <div style={{
                                    fontFamily: 'var(--font)',
                                    fontSize: '.8rem',
                                    color: 'rgba(233, 220, 210, 0.7)',
                                    marginBottom: '4px',
                                }}>
                                    {lead.title || 'Untitled'}
                                    {lead.location ? ` · ${lead.location}` : ''}
                                </div>
                                {lead.snippet && (
                                    <div style={{
                                        fontFamily: 'var(--font)',
                                        fontSize: '.74rem',
                                        color: 'rgba(233, 220, 210, 0.4)',
                                        lineHeight: '1.4',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        display: '-webkit-box',
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: 'vertical',
                                    }}>
                                        {lead.snippet}
                                    </div>
                                )}
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}
