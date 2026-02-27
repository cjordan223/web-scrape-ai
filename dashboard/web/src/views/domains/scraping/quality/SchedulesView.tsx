import { useEffect, useState, useCallback } from 'react';
import { api } from '../../../../api';
import { fmtBytes } from '../../../../utils';
import { PageHeader, PagePrimary, PageSecondary, PageView } from '../../../../components/workflow/PageLayout';
import { EmptyState, LoadingState } from '../../../../components/workflow/States';

export default function SchedulesView() {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [expandedId, setExpandedId] = useState<string | null>(null);
    const [logData, setLogData] = useState<Record<string, any>>({});
    const [logLines, setLogLines] = useState(100);

    const fetchSchedules = useCallback(async () => {
        try {
            const res = await api.getSchedules();
            setData(res);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchSchedules();
    }, [fetchSchedules]);

    const toggleSched = (id: string) => {
        if (expandedId === id) setExpandedId(null);
        else setExpandedId(id);
    };

    const fetchLog = async (label: string) => {
        try {
            const res = await api.getScheduleLog(label, logLines);
            setLogData(prev => ({ ...prev, [label]: res }));
        } catch (err) {
            console.error(err);
        }
    };

    const loadedCount = data.filter(j => j.loaded).length;
    const notLoadedCount = data.filter(j => !j.loaded).length;
    const runningCount = data.filter(j => j.running).length;
    const exitErrorCount = data.filter(j => j.loaded && j.last_exit !== 0 && j.last_exit !== null).length;

    return (
        <PageView>
            <PageHeader title="Scheduled Jobs" right={<button className="btn btn-ghost btn-sm" onClick={fetchSchedules}>Refresh</button>} />
            <PagePrimary>
            {/* Summary metric cards */}
            <div className="cards" style={{ marginBottom: '24px' }}>
                <div className="card">
                    <div className="card-icon green">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    </div>
                    <div className="card-label">Loaded</div>
                    <div className="card-value">{loadedCount}</div>
                </div>
                <div className="card">
                    <div className="card-icon red">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                    </div>
                    <div className="card-label">Not Loaded</div>
                    <div className="card-value">{notLoadedCount}</div>
                </div>
                <div className="card">
                    <div className="card-icon blue">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                    </div>
                    <div className="card-label">Running Now</div>
                    <div className="card-value">{runningCount}</div>
                </div>
                <div className="card">
                    <div className="card-icon amber">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    </div>
                    <div className="card-label">Last Exit != 0</div>
                    <div className="card-value">{exitErrorCount}</div>
                </div>
            </div>
            </PagePrimary>

            <PageSecondary>
            {loading ? (
                <LoadingState />
            ) : data.length === 0 ? (
                <EmptyState icon="⏱" text="No launchd agents found" />
            ) : (
                <div style={{ maxWidth: '900px' }}>
                    {data.map((sched: any) => (
                        <div key={sched.label} className={`sched-card ${sched.running ? 'running-now' : (sched.loaded ? 'loaded' : 'not-loaded')}`}>
                            <div className="sched-header" onClick={() => toggleSched(sched.label)}>
                                <div>
                                    <div className="sched-label">{sched.label}</div>
                                    <div style={{ fontSize: '.8rem', color: 'var(--text-secondary)', marginTop: '2px' }}>{sched.schedule || 'No schedule'}</div>
                                </div>
                                <div className="sched-meta">
                                    <span className={`pill ${sched.running ? 'pill-running' : (sched.loaded ? 'pill-success' : 'pill-fail')}`}>
                                        {sched.running ? 'Running' : (sched.loaded ? 'Loaded' : 'Not Loaded')}
                                    </span>
                                    {sched.last_exit !== null && sched.last_exit !== undefined && (
                                        <span className={`pill ${sched.last_exit === 0 ? 'pill-success' : 'pill-fail'}`}>
                                            Exit: {sched.last_exit}
                                        </span>
                                    )}
                                    <span style={{ fontSize: '.8rem' }}>{expandedId === sched.label ? '▼' : '▶'}</span>
                                </div>
                            </div>

                            {expandedId === sched.label && (
                                <div className="sched-detail">
                                    <div className="sched-field">
                                        <div className="sched-field-label">Command</div>
                                        <div className="sched-field-value">{sched.command}</div>
                                    </div>
                                    <div className="sched-field">
                                        <div className="sched-field-label">Working Dir</div>
                                        <div className="sched-field-value">{sched.working_dir || '—'}</div>
                                    </div>
                                    <div className="sched-field">
                                        <div className="sched-field-label">Schedule</div>
                                        <div className="sched-field-value">{(sched.schedule || 'None') + (sched.interval_seconds ? ` (${sched.interval_seconds}s)` : '')}</div>
                                    </div>
                                    <div className="sched-field">
                                        <div className="sched-field-label">Run at Load</div>
                                        <div className="sched-field-value">{sched.run_at_load ? 'Yes' : 'No'}</div>
                                    </div>
                                    <div className="sched-field">
                                        <div className="sched-field-label">PID</div>
                                        <div className="sched-field-value">{sched.pid ?? '—'}</div>
                                    </div>
                                    <div className="sched-field">
                                        <div className="sched-field-label">Last Exit</div>
                                        <div className="sched-field-value">
                                            <span style={sched.last_exit !== 0 && sched.last_exit !== null ? { color: 'var(--red)', fontWeight: 600 } : {}}>
                                                {sched.last_exit ?? '—'}
                                            </span>
                                        </div>
                                    </div>
                                    <div className="sched-field">
                                        <div className="sched-field-label">Log File</div>
                                        <div className="sched-field-value">{sched.log_path || 'None'}</div>
                                    </div>
                                    {sched.log_size > 0 && (
                                        <div className="sched-field">
                                            <div className="sched-field-label">Log Size</div>
                                            <div className="sched-field-value">{fmtBytes(sched.log_size)}</div>
                                        </div>
                                    )}
                                    <div className="sched-field">
                                        <div className="sched-field-label">Plist Path</div>
                                        <div className="sched-field-value">{sched.plist_path}</div>
                                    </div>

                                    {/* Interactive log viewer */}
                                    {sched.log_path && (
                                        <div>
                                            <div className="log-controls">
                                                <button className="btn btn-sm btn-primary" onClick={() => fetchLog(sched.label)}>
                                                    {logData[sched.label] ? 'Refresh Log' : 'View Log'}
                                                </button>
                                                <select
                                                    value={logLines}
                                                    onChange={(e) => {
                                                        const val = Number(e.target.value);
                                                        setLogLines(val);
                                                        if (logData[sched.label]) {
                                                            api.getScheduleLog(sched.label, val).then(res => {
                                                                setLogData(prev => ({ ...prev, [sched.label]: res }));
                                                            }).catch(() => {});
                                                        }
                                                    }}
                                                    style={{ padding: '4px 8px', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '.8rem' }}
                                                >
                                                    <option value="50">50 lines</option>
                                                    <option value="100">100 lines</option>
                                                    <option value="300">300 lines</option>
                                                    <option value="500">500 lines</option>
                                                </select>
                                                {logData[sched.label] && (
                                                    <span style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>
                                                        Showing last {logData[sched.label].lines.length} of {logData[sched.label].total_lines} lines
                                                    </span>
                                                )}
                                            </div>
                                            {logData[sched.label] && (
                                                <div className="log-viewer">
                                                    {logData[sched.label].lines.map((line: string, i: number) => (
                                                        <div key={i} className="log-line">{line}</div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
            </PageSecondary>
        </PageView>
    );
}
