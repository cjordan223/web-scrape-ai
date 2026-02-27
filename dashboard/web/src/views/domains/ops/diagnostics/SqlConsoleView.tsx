import { useState, useRef, useEffect } from 'react';
import { api } from '../../../../api';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { EmptyState } from '../../../../components/workflow/States';
import { ActionBar } from '../../../../components/workflow/ActionBar';

export default function SqlConsoleView() {
    const [query, setQuery] = useState('');
    const [result, setResult] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [history, setHistory] = useState<string[]>([]);
    const [adminStatus, setAdminStatus] = useState<any>(null);
    const [adminLoading, setAdminLoading] = useState(true);
    const [adminError, setAdminError] = useState('');
    const [adminBusy, setAdminBusy] = useState(false);
    const [adminNotice, setAdminNotice] = useState('');
    const [adminAction, setAdminAction] = useState('truncate_all');
    const [confirmText, setConfirmText] = useState('');
    const [selectedTables, setSelectedTables] = useState<Record<string, boolean>>({});

    const editorRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        const saved = localStorage.getItem('sql_history');
        if (saved) {
            try { setHistory(JSON.parse(saved)); } catch (e) { }
        }
    }, []);

    const loadAdminStatus = async () => {
        setAdminLoading(true);
        setAdminError('');
        try {
            const data = await api.dbAdminStatus();
            setAdminStatus(data);
            const next: Record<string, boolean> = {};
            (data.tables || []).forEach((t: any) => { next[t.name] = false; });
            setSelectedTables(next);
        } catch (err: any) {
            setAdminError(err.response?.data?.error || err.message || 'Failed to load DB admin status');
        } finally {
            setAdminLoading(false);
        }
    };

    useEffect(() => {
        loadAdminStatus();
    }, []);

    const saveHistory = (q: string) => {
        const newHist = [q, ...history.filter(h => h !== q)].slice(0, 10);
        setHistory(newHist);
        localStorage.setItem('sql_history', JSON.stringify(newHist));
    };

    const runQuery = async (q: string = query) => {
        if (!q.trim()) return;
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const res = await api.dbQuery(q);
            if (res.error) {
                setError(res.error);
            } else {
                setResult(res);
                saveHistory(q);
            }
        } catch (err: any) {
            setError(err.response?.data?.error || err.message || 'Network error');
        } finally {
            setLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            runQuery();
        }
    };

    const presets = [
        { label: "Count everything", query: "SELECT count(*) FROM results;" },
        { label: "Grouping by board", query: "SELECT board, count(*) as count FROM results GROUP BY board ORDER BY count DESC;" },
        { label: "Recent jobs with salary", query: "SELECT id, title, salary_k, url FROM results WHERE salary_k IS NOT NULL ORDER BY created_at DESC LIMIT 20;" },
        { label: "Common rejection reasons", query: "SELECT rejection_reason, count(*) as c FROM seen_urls WHERE rejection_reason IS NOT NULL GROUP BY rejection_reason ORDER BY c DESC LIMIT 10;" },
        { label: "Errors grouping", query: "SELECT status, error_count, errors FROM runs WHERE error_count > 0 ORDER BY started_at DESC LIMIT 10;" },
        { label: "Recent runs", query: "SELECT * FROM runs ORDER BY started_at DESC LIMIT 20;" },
        { label: "Top domains", query: "SELECT substr(url, instr(url, '://') + 3, instr(substr(url, instr(url, '://') + 3), '/') - 1) as domain, count(*) as count FROM results GROUP BY domain ORDER BY count DESC LIMIT 20;" }
    ];

    const runAdminAction = async () => {
        setAdminNotice('');
        setAdminError('');
        setAdminBusy(true);
        try {
            const tables = Object.entries(selectedTables)
                .filter(([, checked]) => checked)
                .map(([name]) => name);
            const res = await api.dbAdminAction(adminAction, tables, confirmText);
            if (res.error) {
                setAdminError(res.error);
            } else {
                const affected = (res.affected_tables || []).length;
                setAdminNotice(`Completed ${res.action}. Affected tables: ${affected}`);
                setConfirmText('');
                await loadAdminStatus();
            }
        } catch (err: any) {
            setAdminError(err.response?.data?.error || err.message || 'Failed to execute admin action');
        } finally {
            setAdminBusy(false);
        }
    };

    return (
        <PageView>
            <PageHeader title="SQL Console" subtitle="READ-ONLY · SELECT only · LIMIT 1000" />
            <PagePrimary>
            <div className="preset-queries">
                {presets.map(p => (
                    <div key={p.label} className="preset-btn" onClick={() => { setQuery(p.query); runQuery(p.query); }}>
                        {p.label}
                    </div>
                ))}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px', gap: '20px' }}>
                <div>
                    <textarea
                        ref={editorRef}
                        className="sql-editor"
                        placeholder="Type your SELECT query here... (Cmd+Enter to run)"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        onKeyDown={handleKeyDown}
                    ></textarea>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px', marginBottom: '24px' }}>
                        <div className="query-meta">Read-only connection &middot; Limits automatically applied to large sets</div>
                        <button className="btn btn-primary" disabled={loading} onClick={() => runQuery()}>
                            {loading ? 'Running...' : 'Run Query ⌘↵'}
                        </button>
                    </div>

                    {error && (
                        <WorkflowPanel style={{ background: '#fef2f2', borderColor: '#fecaca' }}>
                            <div style={{ padding: '16px', color: '#991b1b', fontFamily: 'monospace', fontSize: '.9rem' }}>
                                {error}
                            </div>
                        </WorkflowPanel>
                    )}

                    {result && !error && (
                        <WorkflowPanel
                            title={<span style={{ fontWeight: 600, fontSize: '.9rem' }}>Results</span>}
                            right={<div style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>{result.row_count} rows &middot; {result.elapsed_ms.toFixed(1)}ms</div>}
                            headerStyle={{ padding: '12px 20px' }}
                        >
                            <div style={{ overflowX: 'auto', maxHeight: '500px' }}>
                                {result.rows.length === 0 ? (
                                    <EmptyState text="Query returned 0 rows." style={{ padding: '24px' }} />
                                ) : (
                                    <table style={{ margin: 0, minWidth: '100%' }}>
                                        <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                                            <tr>
                                                {result.columns.map((col: string, i: number) => (
                                                    <th key={i}>{col}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {result.rows.map((row: any, i: number) => (
                                                <tr key={i}>
                                                    {result.columns.map((col: string, j: number) => (
                                                        <td key={j} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxWidth: '300px' }}>
                                                            {row[col] === null ? <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>NULL</span> : String(row[col])}
                                                        </td>
                                                    ))}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}
                            </div>
                        </WorkflowPanel>
                    )}
                </div>

                <div>
                    <WorkflowPanel title={<span style={{ fontWeight: 600, fontSize: '.85rem' }}>Query History</span>} headerStyle={{ padding: '12px' }}>
                        <div>
                            {history.length === 0 ? (
                                <div style={{ padding: '16px', fontSize: '.8rem', color: 'var(--text-secondary)' }}>No history</div>
                            ) : (
                                history.map((h, i) => (
                                    <div key={i} className="query-history-item" onClick={() => { setQuery(h); runQuery(h); }}>
                                        {h.slice(0, 60)}{h.length > 60 ? '...' : ''}
                                    </div>
                                ))
                            )}
                        </div>
                    </WorkflowPanel>

                    <WorkflowPanel title={<span style={{ fontWeight: 600, fontSize: '.85rem' }}>DB Admin</span>} headerStyle={{ padding: '12px' }} style={{ marginTop: '12px' }}>
                        {adminLoading ? (
                            <div style={{ padding: '12px', fontSize: '.82rem', color: 'var(--text-secondary)' }}>Loading admin status...</div>
                        ) : (
                            <div style={{ padding: '12px' }}>
                                {!adminStatus?.enabled && (
                                    <div style={{ fontSize: '.8rem', color: '#b45309', marginBottom: '10px' }}>
                                        Disabled: set <code>DASHBOARD_ENABLE_DB_ADMIN=1</code> on backend to enable.
                                    </div>
                                )}
                                <div style={{ fontSize: '.8rem', marginBottom: '8px' }}>Action</div>
                                <select value={adminAction} onChange={(e) => setAdminAction(e.target.value)} style={{ width: '100%', marginBottom: '10px' }}>
                                    <option value="truncate_all">Delete all rows (all tables)</option>
                                    <option value="truncate_tables">Delete rows (selected tables)</option>
                                    <option value="drop_tables">Drop selected tables</option>
                                </select>

                                {adminAction !== 'truncate_all' && (
                                    <div style={{ marginBottom: '10px', maxHeight: '140px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                                        {(adminStatus?.tables || []).map((t: any) => (
                                            <label key={t.name} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '.8rem' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={!!selectedTables[t.name]}
                                                    onChange={(e) => setSelectedTables(prev => ({ ...prev, [t.name]: e.target.checked }))}
                                                />
                                                <span>{t.name} ({t.row_count})</span>
                                            </label>
                                        ))}
                                    </div>
                                )}

                                <div style={{ fontSize: '.78rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                                    Type <strong>{adminStatus?.confirm_phrase || 'DROP ALL DATA'}</strong> to confirm
                                </div>
                                <input
                                    type="text"
                                    value={confirmText}
                                    onChange={(e) => setConfirmText(e.target.value)}
                                    placeholder={adminStatus?.confirm_phrase || 'DROP ALL DATA'}
                                    style={{ width: '100%', marginBottom: '10px' }}
                                />

                                <ActionBar style={{ justifyContent: 'space-between' }}>
                                    <button className="btn btn-ghost btn-sm" onClick={loadAdminStatus}>Refresh</button>
                                    <button className="btn btn-primary btn-sm" disabled={!adminStatus?.enabled || adminBusy} onClick={runAdminAction}>
                                        {adminBusy ? 'Running...' : 'Execute Admin Action'}
                                    </button>
                                </ActionBar>

                                {adminError && <div style={{ marginTop: '8px', color: '#dc2626', fontSize: '.8rem' }}>{adminError}</div>}
                                {!adminError && adminNotice && <div style={{ marginTop: '8px', color: '#065f46', fontSize: '.8rem' }}>{adminNotice}</div>}
                            </div>
                        )}
                    </WorkflowPanel>
                </div>
            </div>
            </PagePrimary>
        </PageView>
    );
}
