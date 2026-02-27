import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../../../api';
import { Search } from 'lucide-react';
import { fmtDate } from '../../../../utils';
import VerdictChips from '../../../../components/VerdictChips';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { EmptyState, LoadingState } from '../../../../components/workflow/States';
import { FilterToolbar } from '../../../../components/workflow/FilterToolbar';

export default function JobsView() {
    const [searchParams] = useSearchParams();
    const [jobs, setJobs] = useState<any>({ items: [], total: 0, pages: 0, page: 1, latest_run_id: null });
    const [loading, setLoading] = useState(true);
    const [runIds, setRunIds] = useState<string[]>([]);

    // Filters
    const [board, setBoard] = useState('');
    const [seniority, setSeniority] = useState('');
    const [search, setSearch] = useState('');
    const [urlSearch, setUrlSearch] = useState('');
    const [runId, setRunId] = useState(searchParams.get('run_id') || '');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');

    // Pagination & Sorting
    const [page, setPage] = useState(1);
    const [perPage, setPerPage] = useState(25);
    const [sortBy, setSortBy] = useState('created_at');
    const [sortDir, setSortDir] = useState('desc');

    // Expanded row
    const [expandedId, setExpandedId] = useState<number | null>(null);
    const [expandedDetail, setExpandedDetail] = useState<any>(null);

    // Form dropdown data
    const boards = ["greenhouse", "lever", "ashby", "workday", "bamboohr", "icims", "smartrecruiters", "unknown"];
    const seniorities = ["junior", "mid", "senior"];

    const fetchJobs = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getJobs({
                page,
                per_page: perPage,
                board,
                seniority,
                search,
                url_search: urlSearch,
                run_id: runId,
                sort_by: sortBy,
                sort_dir: sortDir,
                date_from: dateFrom,
                date_to: dateTo
            });
            setJobs(data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [page, perPage, board, seniority, search, urlSearch, runId, sortBy, sortDir, dateFrom, dateTo]);

    useEffect(() => {
        fetchJobs();
    }, [fetchJobs]);

    useEffect(() => {
        api.getRunIds().then(setRunIds).catch(() => {});
    }, []);

    const toggleSort = (col: string) => {
        if (sortBy === col) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(col);
            setSortDir('desc');
        }
        setPage(1);
    };

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

    const clearFilters = () => {
        setBoard('');
        setSeniority('');
        setSearch('');
        setUrlSearch('');
        setRunId('');
        setDateFrom('');
        setDateTo('');
        setPage(1);
    };

    return (
        <PageView>
            <PageHeader title="Jobs" right={<div className="pagination-info">{jobs.total} total results</div>} />
            <PagePrimary>
            <WorkflowPanel>
                <FilterToolbar>
                    <select value={board} onChange={(e) => { setBoard(e.target.value); setPage(1); }}>
                        <option value="">All Boards</option>
                        {boards.map(b => <option key={b} value={b}>{b}</option>)}
                    </select>
                    <select value={seniority} onChange={(e) => { setSeniority(e.target.value); setPage(1); }}>
                        <option value="">All Seniority</option>
                        {seniorities.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <input type="text" placeholder="Search titles..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} style={{ minWidth: '160px' }} />
                    <input type="text" placeholder="Search URLs..." value={urlSearch} onChange={(e) => { setUrlSearch(e.target.value); setPage(1); }} style={{ minWidth: '160px' }} />
                    <select value={runId} onChange={(e) => { setRunId(e.target.value); setPage(1); }}>
                        <option value="">All Runs</option>
                        {runIds.map(r => <option key={r} value={r}>{r.slice(0, 12)}...</option>)}
                    </select>
                    <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
                    <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} />
                    <button className="btn btn-ghost btn-sm" onClick={clearFilters}>Clear</button>
                </FilterToolbar>

                {jobs.items.length > 0 && (
                    <div className="stats-bar">
                        <span>Showing <strong>{jobs.items.length}</strong> of <strong>{jobs.total}</strong></span>
                        {(() => {
                            const boardCounts: Record<string, number> = {};
                            const seniorityCounts: Record<string, number> = {};
                            jobs.items.forEach((j: any) => {
                                if (j.board) boardCounts[j.board] = (boardCounts[j.board] || 0) + 1;
                                if (j.seniority) seniorityCounts[j.seniority] = (seniorityCounts[j.seniority] || 0) + 1;
                            });
                            return (
                                <>
                                    {Object.entries(boardCounts).map(([b, cnt]) => (
                                        <span key={b} className={`pill pill-${b}`} style={{ fontSize: '.75rem' }}>{b} {cnt}</span>
                                    ))}
                                    {Object.entries(seniorityCounts).map(([s, cnt]) => (
                                        <span key={s} className={`pill pill-${s}`} style={{ fontSize: '.75rem' }}>{s} {cnt}</span>
                                    ))}
                                </>
                            );
                        })()}
                    </div>
                )}

                {loading && <LoadingState />}

                {!loading && jobs.items.length === 0 && (
                    <EmptyState icon="🔎" text="No jobs match your filters" />
                )}

                {!loading && jobs.items.length > 0 && (
                    <table>
                        <thead>
                            <tr>
                                <th onClick={() => toggleSort('title')} className={sortBy === 'title' ? 'sorted' : ''}>
                                    Title <span className="sort-arrow">{sortBy === 'title' ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                </th>
                                <th onClick={() => toggleSort('board')} className={sortBy === 'board' ? 'sorted' : ''}>
                                    Board <span className="sort-arrow">{sortBy === 'board' ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                </th>
                                <th onClick={() => toggleSort('seniority')} className={sortBy === 'seniority' ? 'sorted' : ''}>
                                    Seniority <span className="sort-arrow">{sortBy === 'seniority' ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                </th>
                                <th onClick={() => toggleSort('experience_years')} className={sortBy === 'experience_years' ? 'sorted' : ''}>
                                    Exp <span className="sort-arrow">{sortBy === 'experience_years' ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                </th>
                                <th onClick={() => toggleSort('salary_k')} className={sortBy === 'salary_k' ? 'sorted' : ''}>
                                    Salary <span className="sort-arrow">{sortBy === 'salary_k' ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                </th>
                                <th onClick={() => toggleSort('created_at')} className={sortBy === 'created_at' ? 'sorted' : ''}>
                                    Date <span className="sort-arrow">{sortBy === 'created_at' ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                </th>
                                <th style={{ width: '40px' }}></th>
                            </tr>
                        </thead>
                        <tbody>
                            {jobs.items.map((job: any) => (
                                <tr key={job.id} className={expandedId === job.id ? 'expanded' : ''}>
                                    <td>
                                        <div onClick={() => toggleJob(job.id)} style={{ cursor: 'pointer' }}>
                                            <div style={{ fontWeight: 600, maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {job.title}
                                                {job.run_id === jobs.latest_run_id && <span className="pill pill-new">NEW</span>}
                                            </div>
                                            <div style={{ fontSize: '.8rem', color: 'var(--text-secondary)', maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {job.snippet}
                                            </div>
                                        </div>

                                        {expandedId === job.id && (
                                            <div className="job-detail" onClick={(e) => e.stopPropagation()}>
                                                <div style={{ marginBottom: '8px' }}><strong>URL:</strong> <a href={job.url} target="_blank" rel="noreferrer">{job.url}</a></div>
                                                <div style={{ marginBottom: '8px' }}><strong>Query:</strong> <span style={{ color: 'var(--text-secondary)' }}>{job.query}</span></div>
                                                <div style={{ marginBottom: '8px' }}><strong>Run:</strong> <span style={{ color: 'var(--text-secondary)' }}>{job.run_id}</span></div>

                                                {expandedDetail ? (
                                                    <div>
                                                        {expandedDetail.salary_k && (
                                                            <div style={{ marginBottom: '8px' }}>
                                                                <strong>Salary:</strong> <span style={{ color: 'var(--green)', fontWeight: 600 }}>${Math.round(expandedDetail.salary_k / 1000)}K</span>
                                                            </div>
                                                        )}
                                                        <div className="verdicts">
                                                            <div style={{ fontWeight: 600, marginBottom: '8px' }}>Filter Verdicts</div>
                                                            <VerdictChips verdicts={expandedDetail.filter_verdicts || []} />
                                                        </div>
                                                        {expandedDetail.jd_text && (
                                                            <div>
                                                                <div style={{ fontWeight: 600, marginTop: '16px', marginBottom: '4px' }}>Job Description</div>
                                                                <div className="jd-text">{expandedDetail.jd_text}</div>
                                                            </div>
                                                        )}
                                                    </div>
                                                ) : (
                                                    <LoadingState style={{ padding: '16px' }} />
                                                )}
                                            </div>
                                        )}
                                    </td>
                                    <td><span className={`pill pill-${job.board}`}>{job.board}</span></td>
                                    <td><span className={`pill pill-${job.seniority}`}>{job.seniority}</span></td>
                                    <td>{job.experience_years ?? '—'}</td>
                                    <td style={job.salary_k ? { fontWeight: 600 } : {}}>
                                        {job.salary_k ? `$${Math.round(job.salary_k / 1000)}K` : '—'}
                                    </td>
                                    <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(job.created_at)}</td>
                                    <td>
                                        <a href={job.url} target="_blank" rel="noreferrer" className="ext-link" title="Open job posting">
                                            <Search size={16} />
                                        </a>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}

                {jobs.pages > 0 && (
                    <div className="pagination">
                        <div className="pagination-info">Page {page} of {jobs.pages}</div>
                        <div className="pagination-controls">
                            <select value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }} style={{ padding: '4px 8px', border: '1px solid var(--border)', borderRadius: '6px' }}>
                                <option value="25">25</option>
                                <option value="50">50</option>
                                <option value="100">100</option>
                            </select>
                            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
                            <span className="page-num">{page} / {jobs.pages}</span>
                            <button disabled={page >= jobs.pages} onClick={() => setPage(p => p + 1)}>Next</button>
                        </div>
                    </div>
                )}
            </WorkflowPanel>
            </PagePrimary>
        </PageView>
    );
}
