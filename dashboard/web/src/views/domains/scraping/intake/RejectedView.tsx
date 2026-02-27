import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../../../api';
import { Search } from 'lucide-react';
import { fmtDate } from '../../../../utils';
import VerdictChips from '../../../../components/VerdictChips';
import { PageHeader, PagePrimary, PageSecondary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { EmptyState, LoadingState } from '../../../../components/workflow/States';
import { ActionBar } from '../../../../components/workflow/ActionBar';
import { FilterToolbar } from '../../../../components/workflow/FilterToolbar';

export default function RejectedView() {
    const [searchParams] = useSearchParams();
    const [rejected, setRejected] = useState<any>({ items: [], total: 0, pages: 0 });
    const [stats, setStats] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [runIds, setRunIds] = useState<string[]>([]);

    // Filters
    const [stageStr, setStageStr] = useState('');
    const [runId, setRunId] = useState(searchParams.get('run_id') || '');
    const [search, setSearch] = useState('');

    // Pagination
    const [page, setPage] = useState(1);
    const [perPage, setPerPage] = useState(50);

    // Expand
    const [expandedId, setExpandedId] = useState<number | null>(null);
    const [expandedDetail, setExpandedDetail] = useState<any>(null);

    // Approving
    const [approvingIds, setApprovingIds] = useState<Record<number, boolean>>({});

    const fetchRejected = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getRejected({
                page,
                per_page: perPage,
                stage: stageStr,
                run_id: runId,
                search
            });
            setRejected(data);
            const statsRes = await api.getRejectedStats();
            setStats(statsRes);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [page, perPage, stageStr, runId, search]);

    useEffect(() => {
        fetchRejected();
    }, [fetchRejected]);

    useEffect(() => {
        api.getRunIds().then(setRunIds).catch(() => {});
    }, []);

    const toggleJob = async (id: number) => {
        if (expandedId === id) {
            setExpandedId(null);
            setExpandedDetail(null);
            return;
        }
        setExpandedId(id);
        setExpandedDetail(null);
        try {
            const data = await api.getJobDetail(id);
            setExpandedDetail(data);
        } catch (err) {
            console.error(err);
        }
    };

    const approveRejected = async (e: React.MouseEvent, job: any) => {
        e.stopPropagation();
        setApprovingIds(prev => ({ ...prev, [job.id]: true }));
        try {
            await api.approveRejected(job.id);
            // Remove from list
            setRejected((prev: any) => ({
                ...prev,
                items: prev.items.filter((j: any) => j.id !== job.id),
                total: prev.total - 1
            }));
        } catch (err) {
            console.error('Failed to approve', err);
        } finally {
            setApprovingIds(prev => ({ ...prev, [job.id]: false }));
        }
    };

    return (
        <PageView>
            <PageHeader
                title="Rejected Jobs"
                right={<div style={{ fontSize: '.85rem', color: 'var(--text-secondary)' }}>{stats?.total?.toLocaleString() ?? 0} total rejections</div>}
            />
            <PagePrimary>
            {stats && (
                <WorkflowPanel
                    title="Rejection Breakdown by Stage"
                    right={<div style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>Click to filter</div>}
                    style={{ marginBottom: '24px' }}
                >
                    <div style={{ padding: '14px 20px', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                        <span
                            className={`pill ${stageStr === '' ? 'pill-running' : 'pill-unknown'}`}
                            style={{ cursor: 'pointer', fontSize: '.82rem', padding: '4px 12px' }}
                            onClick={() => { setStageStr(''); setPage(1); }}
                        >
                            All ({stats.total || 0})
                        </span>
                        {Object.entries(stats.by_stage || {}).map(([stage, cnt]: any) => (
                            <span
                                key={stage}
                                className={`pill ${stageStr === stage ? 'pill-running' : `pill-stage-${stage}`}`}
                                style={{ cursor: 'pointer', fontSize: '.82rem', padding: '4px 12px' }}
                                onClick={() => { setStageStr(stage); setPage(1); }}
                            >
                                {stage} ({cnt})
                            </span>
                        ))}
                    </div>
                </WorkflowPanel>
            )}
            </PagePrimary>
            <PageSecondary>
            <WorkflowPanel>
                <FilterToolbar>
                    <select value={stageStr} onChange={(e) => { setStageStr(e.target.value); setPage(1); }}>
                        <option value="">All Stages</option>
                        {Object.keys(stats?.by_stage || {}).map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <select value={runId} onChange={(e) => { setRunId(e.target.value); setPage(1); }}>
                        <option value="">All Runs</option>
                        {runIds.map(r => <option key={r} value={r}>{r.slice(0, 12)}...</option>)}
                    </select>
                    <input type="text" placeholder="Search titles..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} style={{ minWidth: '180px' }} />
                    <button className="btn btn-ghost btn-sm" onClick={() => { setSearch(''); setStageStr(''); setRunId(''); setPage(1); }}>Clear</button>
                </FilterToolbar>

                {loading && <LoadingState />}

                {!loading && rejected.items?.length === 0 && (
                    <EmptyState icon="✔" text="No rejections match your filters" />
                )}

                {!loading && rejected.items?.length > 0 && (
                    <table>
                        <thead>
                            <tr>
                                <th>Title</th>
                                <th>Board</th>
                                <th>Rejected At</th>
                                <th>Reason</th>
                                <th>Date</th>
                                <th style={{ width: '160px' }}>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rejected.items.map((job: any) => (
                                <tr key={job.id} className={expandedId === job.id ? 'expanded' : ''}>
                                    <td>
                                        <div onClick={() => toggleJob(job.id)} style={{ cursor: 'pointer' }}>
                                            <div style={{ fontWeight: 600, maxWidth: '380px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {job.title}
                                            </div>
                                            <div style={{ fontSize: '.8rem', color: 'var(--text-secondary)', maxWidth: '380px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {job.snippet}
                                            </div>
                                        </div>
                                        {expandedId === job.id && (
                                            <div className="job-detail" onClick={(e) => e.stopPropagation()}>
                                                <div style={{ marginBottom: '8px' }}><strong>URL:</strong> <a href={job.url} target="_blank" rel="noreferrer">{job.url}</a></div>
                                                <div style={{ marginBottom: '8px' }}><strong>Run:</strong> <span style={{ color: 'var(--text-secondary)' }}>{job.run_id}</span></div>
                                                {expandedDetail ? (
                                                    <div className="verdicts" style={{ marginTop: '8px' }}>
                                                        <div style={{ fontWeight: 600, marginBottom: '8px' }}>Filter Verdicts</div>
                                                        <VerdictChips verdicts={expandedDetail.filter_verdicts || []} />
                                                    </div>
                                                ) : (
                                                    <LoadingState style={{ padding: '12px' }} />
                                                )}
                                            </div>
                                        )}
                                    </td>
                                    <td><span className={`pill pill-${job.board}`}>{job.board}</span></td>
                                    <td><span className={`pill pill-stage-${job.rejection_stage}`}>{job.rejection_stage}</span></td>
                                    <td style={{ fontSize: '.82rem', color: 'var(--text-secondary)', maxWidth: '280px', wordBreak: 'break-word' }}>
                                        {job.rejection_reason}
                                    </td>
                                    <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(job.created_at)}</td>
                                    <td>
                                        <ActionBar style={{ alignItems: 'center', gap: '8px', justifyContent: 'flex-end' }}>
                                            <button
                                                className="btn btn-success btn-sm"
                                                disabled={!!approvingIds[job.id]}
                                                onClick={(e) => approveRejected(e, job)}
                                            >
                                                {approvingIds[job.id] ? 'Approving...' : 'Approve'}
                                            </button>
                                            <a href={job.url} target="_blank" rel="noreferrer" className="ext-link" title="Open URL">
                                                <Search size={16} />
                                            </a>
                                        </ActionBar>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}

                {rejected.pages > 1 && (
                    <div className="pagination">
                        <div className="pagination-info">Page {page} of {rejected.pages} ({rejected.total} total)</div>
                        <div className="pagination-controls">
                            <select value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }} style={{ padding: '4px 8px', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '.85rem' }}>
                                <option value="50">50</option>
                                <option value="100">100</option>
                                <option value="200">200</option>
                            </select>
                            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
                            <span className="page-num">{page} / {rejected.pages}</span>
                            <button disabled={page >= rejected.pages} onClick={() => setPage(p => p + 1)}>Next</button>
                        </div>
                    </div>
                )}
            </WorkflowPanel>
            </PageSecondary>
        </PageView>
    );
}
