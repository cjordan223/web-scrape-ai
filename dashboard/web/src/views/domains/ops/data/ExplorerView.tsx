import { useEffect, useState, useCallback } from 'react';
import { api } from '../../../../api';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { EmptyState, LoadingState } from '../../../../components/workflow/States';

export default function ExplorerView() {
    const [tables, setTables] = useState<any[]>([]);
    const [activeTable, setActiveTable] = useState<string>('');

    const [data, setData] = useState<any>({ columns: [], items: [], total: 0, page: 1, pages: 1 });
    const [loading, setLoading] = useState(false);

    // Filters state per column
    const [colFilters, setColFilters] = useState<Record<string, string>>({});

    // Sorting state
    const [sortBy, setSortBy] = useState<string>('');
    const [sortDir, setSortDir] = useState<string>('desc');

    // Pagination
    const [perPage, setPerPage] = useState(50);
    const [page, setPage] = useState(1);

    // Modal
    const [modalRow, setModalRow] = useState<any>(null);

    const fetchTables = useCallback(async () => {
        try {
            const res = await api.dbTables();
            setTables(res);
            if (res.length > 0) setActiveTable(res[0].name);
        } catch (err) {
            console.error(err);
        }
    }, []);

    useEffect(() => {
        fetchTables();
    }, [fetchTables]);

    const fetchData = useCallback(async () => {
        if (!activeTable) return;
        setLoading(true);
        try {
            const res = await api.dbTableData(activeTable, {
                page,
                per_page: perPage,
                sort_by: sortBy,
                sort_dir: sortDir,
                ...colFilters
            });
            setData(res);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, [activeTable, page, perPage, sortBy, sortDir, colFilters]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    const handleTableChange = (t: string) => {
        setActiveTable(t);
        setColFilters({});
        setSortBy('');
        setSortDir('desc');
        setPage(1);
    };

    const handleFilterChange = (col: string, val: string) => {
        setColFilters(prev => ({ ...prev, [col]: val }));
        setPage(1);
    };

    const clearFilters = () => {
        setColFilters({});
        setPage(1);
    };

    const toggleSort = (col: string) => {
        if (sortBy === col) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(col);
            setSortDir('desc');
        }
        setPage(1);
    };

    return (
        <PageView>
            <PageHeader title="Database Explorer" />
            <PagePrimary>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                {tables.map(t => (
                    <button
                        key={t.name}
                        className={`btn ${activeTable === t.name ? 'btn-primary' : 'btn-ghost'} btn-sm`}
                        onClick={() => handleTableChange(t.name)}
                    >
                        {t.name} ({(t.row_count || 0).toLocaleString()})
                    </button>
                ))}
            </div>

            <WorkflowPanel
                title={activeTable}
                right={
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <div style={{ fontSize: '.85rem', color: 'var(--text-secondary)' }}>
                            Showing {data.items.length} of {data.total?.toLocaleString() ?? 0}
                        </div>
                        <button className="btn btn-ghost btn-sm" onClick={clearFilters}>Clear Filters</button>
                    </div>
                }
            >

                <div style={{ overflowX: 'auto' }}>
                    <table style={{ minWidth: '1000px' }}>
                        <thead>
                            <tr>
                                <th style={{ width: '40px' }}></th>
                                {data.columns.map((col: string) => (
                                    <th key={col}>
                                        <div onClick={() => toggleSort(col)} style={{ cursor: 'pointer', marginBottom: '6px' }}>
                                            {col} <span className="sort-arrow">{sortBy === col ? (sortDir === 'asc' ? '▲' : '▼') : '▼'}</span>
                                        </div>
                                        <input
                                            type="text"
                                            className="col-filter"
                                            placeholder="Filter..."
                                            value={colFilters[col] || ''}
                                            onChange={(e) => handleFilterChange(col, e.target.value)}
                                        />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {loading ? (
                                <tr>
                                    <td colSpan={data.columns.length + 1}>
                                        <LoadingState />
                                    </td>
                                </tr>
                            ) : data.items.length === 0 ? (
                                <tr>
                                    <td colSpan={data.columns.length + 1}>
                                        <EmptyState text="No rows match." style={{ padding: '24px' }} />
                                    </td>
                                </tr>
                            ) : (
                                data.items.map((row: any, i: number) => (
                                    <tr key={i}>
                                        <td>
                                            <div className="cell-expand" onClick={() => setModalRow(row)}>⛶</div>
                                        </td>
                                        {data.columns.map((col: string) => {
                                            let val = row[col];
                                            let isJson = false;
                                            let displayVal = val === null ? 'NULL' : String(val);
                                            if (typeof val === 'string' && (val.startsWith('{') || val.startsWith('['))) {
                                                isJson = true;
                                            }
                                            return (
                                                <td key={col}>
                                                    <div className={isJson ? 'json-cell' : 'cell-truncate'} title={displayVal}>
                                                        {displayVal}
                                                    </div>
                                                </td>
                                            );
                                        })}
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>

                {data.pages > 0 && (
                    <div className="pagination">
                        <div className="pagination-info">Page {page} of {data.pages}</div>
                        <div className="pagination-controls">
                            <select value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }} style={{ padding: '4px 8px', border: '1px solid var(--border)', borderRadius: '6px' }}>
                                <option value="50">50</option>
                                <option value="100">100</option>
                                <option value="200">200</option>
                            </select>
                            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
                            <span className="page-num">{page} / {data.pages}</span>
                            <button disabled={page >= data.pages} onClick={() => setPage(p => p + 1)}>Next</button>
                        </div>
                    </div>
                )}
            </WorkflowPanel>
            </PagePrimary>

            {/* Row Modal */}
            {modalRow && (
                <div className="modal-overlay" onClick={() => setModalRow(null)}>
                    <div className="modal" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <div style={{ fontWeight: 600 }}>Row Details</div>
                            <button className="btn btn-ghost btn-sm" onClick={() => setModalRow(null)}>Close</button>
                        </div>
                        <div className="modal-body">
                            {data.columns.map((col: string) => {
                                let val = modalRow[col];
                                let displayVal = val === null ? 'NULL' : String(val);
                                if (typeof val === 'string' && (val.startsWith('{') || val.startsWith('['))) {
                                    try {
                                        displayVal = JSON.stringify(JSON.parse(val), null, 2);
                                    } catch (e) { }
                                }
                                return (
                                    <div key={col} className="modal-field">
                                        <div className="modal-field-label">{col}</div>
                                        <div className="modal-field-value">{displayVal}</div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>
            )}
        </PageView>
    );
}
