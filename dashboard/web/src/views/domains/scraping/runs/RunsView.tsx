import { Fragment, useEffect, useRef, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../../../api';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend
} from 'chart.js';
import { fmtDate, fmtDuration } from '../../../../utils';
import { PageHeader, PagePrimary, PageSecondary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { LoadingState } from '../../../../components/workflow/States';
import { ActionBar } from '../../../../components/workflow/ActionBar';
import { LogPanel } from '../../../../components/workflow/LogPanel';
import { RunTimelineChart } from '../../../../components/workflow/RunTimelineChart';

ChartJS.register(
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend
);

const SCHEDULE_INTERVAL_OPTIONS = [
    { value: 15, label: 'Every 15 minutes' },
    { value: 30, label: 'Every 30 minutes' },
    { value: 45, label: 'Every 45 minutes' },
    { value: 60, label: 'Every 1 hour' },
    { value: 90, label: 'Every 90 minutes' },
    { value: 120, label: 'Every 2 hours' },
    { value: 180, label: 'Every 3 hours' },
    { value: 360, label: 'Every 6 hours' },
    { value: 720, label: 'Every 12 hours' },
    { value: 1440, label: 'Every 24 hours' },
    { value: 2880, label: 'Every 48 hours (2 days)' },
    { value: 4320, label: 'Every 72 hours (3 days)' },
    { value: 10080, label: 'Every 7 days' },
];

const SCHEDULE_STOP_OPTIONS = [
    { value: '', label: 'No shutoff (run indefinitely)' },
    { value: 6, label: 'Stop after 6 hours' },
    { value: 12, label: 'Stop after 12 hours' },
    { value: 24, label: 'Stop after 1 day' },
    { value: 48, label: 'Stop after 2 days' },
    { value: 72, label: 'Stop after 3 days' },
    { value: 168, label: 'Stop after 7 days' },
    { value: 336, label: 'Stop after 14 days' },
];

const formatCadence = (minutes: number | null | undefined) => {
    if (!minutes || minutes <= 0) return 'Uses launchd trigger cadence';
    if (minutes % 1440 === 0) {
        const days = minutes / 1440;
        return `Every ${days} day${days === 1 ? '' : 's'}`;
    }
    if (minutes % 60 === 0) {
        const hours = minutes / 60;
        return `Every ${hours} hour${hours === 1 ? '' : 's'}`;
    }
    return `Every ${minutes} minutes`;
};

const deriveStopAfterHours = (controls: any): string => {
    const stopRaw = controls?.schedule_stop_at;
    if (!stopRaw) return '';
    const stopAt = new Date(stopRaw);
    if (Number.isNaN(stopAt.getTime())) return '';

    const startedRaw = controls?.schedule_started_at;
    const startedAt = startedRaw ? new Date(startedRaw) : null;
    if (!startedAt || Number.isNaN(startedAt.getTime())) return '';

    const diffMs = stopAt.getTime() - startedAt.getTime();
    if (diffMs <= 0) return '';
    const diffHours = diffMs / (60 * 60 * 1000);
    if (!Number.isInteger(diffHours)) return '';
    return String(diffHours);
};

export default function RunsView() {
    const navigate = useNavigate();
    const [controls, setControls] = useState<any>({
        scrape_enabled: true,
        llm_enabled: true,
        schedule_interval_minutes: null,
        schedule_started_at: null,
        schedule_stop_at: null,
        updated_at: null
    });
    const [runner, setRunner] = useState<any>({ running: false });
    const [loadingControls, setLoadingControls] = useState(false);
    const [savingSchedule, setSavingSchedule] = useState(false);
    const [loadingRunner, setLoadingRunner] = useState(false);
    const [llmStatus, setLlmStatus] = useState<any>(null);
    const [activeRun, setActiveRun] = useState<{ active: boolean; run_id?: string } | null>(null);
    const [scheduleIntervalMinutes, setScheduleIntervalMinutes] = useState<number>(1440);
    const [scheduleStopAfterHours, setScheduleStopAfterHours] = useState<string>('');
    const [customIntervalMinutes, setCustomIntervalMinutes] = useState<string>('');
    const [customStopAfterHours, setCustomStopAfterHours] = useState<string>('');

    // Runs state
    const [runs, setRuns] = useState<any[]>([]);
    const [stats, setStats] = useState<any>(null);
    const [runsLoading, setRunsLoading] = useState(true);
    const [page, setPage] = useState(1);
    const [pages, setPages] = useState(0);

    const prevRunnerRunning = useRef(false);
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [expandedRunDetail, setExpandedRunDetail] = useState<any>(null);
    const [liveLogs, setLiveLogs] = useState<string[]>([]);
    const [liveLogsError, setLiveLogsError] = useState<string | null>(null);

    const fetchControls = async () => {
        try {
            const data = await api.getRunsControls();
            setControls(data);
            setScheduleIntervalMinutes(data?.schedule_interval_minutes || 1440);
            setScheduleStopAfterHours(deriveStopAfterHours(data));
            setCustomIntervalMinutes('');
            setCustomStopAfterHours('');
        } catch (err) {
            console.error(err);
        }
    };

    const fetchRunnerStatus = async () => {
        try {
            const data = await api.getScrapeRunnerStatus();
            setRunner(data);
            // When a manual run completes, refresh the runs table
            if (prevRunnerRunning.current && !data.running) {
                fetchRuns();
            }
            prevRunnerRunning.current = data.running;
        } catch (err) {
            console.error(err);
        }
    };

    const fetchRuns = async () => {
        setRunsLoading(true);
        try {
            const data = await api.getRuns({ page, per_page: 50 });
            setRuns(data.runs || []);
            setPages(data.pages || 0);
            setStats(data.stats || null);
        } catch (err) {
            console.error(err);
        } finally {
            setRunsLoading(false);
        }
    };

    const fetchLlmStatus = async () => {
        try { setLlmStatus(await api.getLlmStatus()); } catch { }
    };

    const fetchActiveRun = async () => {
        try {
            const data = await api.getActiveRun();
            setActiveRun(data || { active: false });
        } catch { }
    };

    useEffect(() => {
        fetchControls();
        fetchRunnerStatus();
        fetchRuns();
        fetchLlmStatus();
        fetchActiveRun();
        const i1 = setInterval(fetchRunnerStatus, 5000);
        const i2 = setInterval(fetchLlmStatus, 60000);
        const i3 = setInterval(fetchActiveRun, 10000);
        return () => { clearInterval(i1); clearInterval(i2); clearInterval(i3); };
    }, []);

    useEffect(() => {
        fetchRuns();
    }, [page]);

    const handleToggleScrape = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const val = e.target.checked;
        setLoadingControls(true);
        setControls((prev: any) => ({ ...prev, scrape_enabled: val })); // Optimistic
        try {
            await api.setScrapeEnabled(val);
            await fetchControls();
        } catch (err) {
            console.error(err);
            setControls((prev: any) => ({ ...prev, scrape_enabled: !val })); // Revert
        } finally {
            setLoadingControls(false);
        }
    };

    const handleToggleLlm = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const val = e.target.checked;
        setLoadingControls(true);
        setControls((prev: any) => ({ ...prev, llm_enabled: val })); // Optimistic
        try {
            await api.setLlmEnabled(val);
            await fetchControls();
        } catch (err) {
            console.error(err);
            setControls((prev: any) => ({ ...prev, llm_enabled: !val })); // Revert
        } finally {
            setLoadingControls(false);
        }
    };

    const startManualRun = async (useLlm: boolean) => {
        setLoadingRunner(true);
        try {
            await api.runScrapeNow(useLlm);
            await fetchRunnerStatus();
        } catch (err) {
            console.error(err);
        } finally {
            setLoadingRunner(false);
        }
    };

    const handleSaveSchedule = async () => {
        const intervalToUse = customIntervalMinutes.trim() !== '' ? Number(customIntervalMinutes) : scheduleIntervalMinutes;
        if (!Number.isInteger(intervalToUse) || intervalToUse < 1) {
            alert('Run cadence must be a whole number of minutes (>= 1).');
            return;
        }

        let stopAfterToUse: number | null = null;
        if (customStopAfterHours.trim() !== '') {
            const parsed = Number(customStopAfterHours);
            if (!Number.isInteger(parsed) || parsed < 1) {
                alert('Shutoff must be a whole number of hours (>= 1).');
                return;
            }
            stopAfterToUse = parsed;
        } else if (scheduleStopAfterHours !== '') {
            stopAfterToUse = Number(scheduleStopAfterHours);
        }

        setSavingSchedule(true);
        try {
            await api.updateRunsControls({
                schedule_interval_minutes: intervalToUse,
                schedule_stop_after_hours: stopAfterToUse,
            });
            await fetchControls();
        } catch (err) {
            console.error(err);
        } finally {
            setSavingSchedule(false);
        }
    };

    const handleDisableScheduledScrape = async () => {
        setLoadingControls(true);
        try {
            await api.setScrapeEnabled(false);
            await fetchControls();
        } catch (err) {
            console.error(err);
        } finally {
            setLoadingControls(false);
        }
    };

    const handleStopScheduledRunsNow = async () => {
        setLoadingControls(true);
        try {
            await api.updateRunsControls({
                scrape_enabled: false,
                schedule_stop_after_hours: null,
            });
            await fetchControls();
            await fetchActiveRun();
        } catch (err) {
            console.error(err);
        } finally {
            setLoadingControls(false);
        }
    };

    const handleTerminateActiveRun = async () => {
        if (!activeRun?.active || !activeRun?.run_id) return;
        if (!window.confirm("Terminate the currently running scrape now?")) return;
        try {
            await api.terminateRun(activeRun.run_id);
            await fetchRuns();
            await fetchRunnerStatus();
            await fetchActiveRun();
        } catch (err) {
            console.error(err);
            alert("Failed to terminate active run.");
        }
    };

    const toggleRunExpand = async (runId: string) => {
        if (expandedRunId === runId) {
            setExpandedRunId(null);
            setExpandedRunDetail(null);
            setLiveLogs([]);
            setLiveLogsError(null);
        } else {
            setExpandedRunId(runId);
            setExpandedRunDetail(null);
            setLiveLogs([]);
            setLiveLogsError(null);
            try {
                const data = await api.getRun(runId);
                setExpandedRunDetail(data);
            } catch (err) {
                console.error(err);
            }
        }
    };

    const handleTerminate = async (runId: string) => {
        if (!window.confirm("Are you sure you want to terminate this run? It will be marked as failed gracefully.")) return;
        try {
            await api.terminateRun(runId);
            await fetchRuns(); // Refresh table status immediately
        } catch (err: any) {
            console.error("Failed to terminate run:", err);
            alert("Failed to terminate run: " + (err.response?.data?.error || err.message));
        }
    };

    // Poll live logs for an expanded running run
    useEffect(() => {
        let interval: any;
        if (expandedRunId) {
            const run = runs.find(r => r.run_id === expandedRunId);
            if (run && run.status === 'running') {
                const fetchLogs = async () => {
                    try {
                        const logData = await api.getRunLogs(expandedRunId, 200);
                        setLiveLogs(logData.lines || []);
                        setLiveLogsError(null);
                    } catch (err: any) {
                        setLiveLogsError(err.response?.data?.error || "Failed to fetch logs");
                    }
                };
                fetchLogs();
                interval = setInterval(fetchLogs, 3000);
            }
        }
        return () => {
            if (interval) clearInterval(interval);
        };
    }, [expandedRunId, runs]);

    // Chart logic
    const chartData = useMemo(() => {
        if (!runs || runs.length === 0) return null;
        const validRuns = runs.filter(r => r.elapsed != null).slice(0, 50).reverse();
        if (validRuns.length === 0) return null;

        const labels = validRuns.map((r: any) => {
            const d = new Date(r.started_at);
            return `${d.toLocaleString('en-US', { month: 'short', day: 'numeric' })}`;
        });
        const times = validRuns.map((r: any) => r.elapsed);
        const colors = validRuns.map((r: any) => r.status === 'complete' ? '#06d6a0' : (r.status === 'failed' ? '#ef476f' : '#cbd5e1'));

        return {
            labels,
            datasets: [{
                label: 'Duration (s)',
                data: times,
                backgroundColor: colors,
                borderWidth: 0,
                borderRadius: 4
            }]
        };
    }, [runs]);

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false }
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: { color: 'rgba(0,0,0,0.05)' }
            },
            x: {
                grid: { display: false }
            }
        }
    };

    const cadenceLabel = useMemo(
        () => formatCadence(controls.schedule_interval_minutes),
        [controls.schedule_interval_minutes]
    );
    const stopLabel = useMemo(() => {
        if (!controls.schedule_stop_at) return 'No auto-shutoff';
        return `Stops at ${fmtDate(controls.schedule_stop_at)}`;
    }, [controls.schedule_stop_at]);

    return (
        <PageView>
            <PageHeader title="Run History & Controls" />
            <PagePrimary>
            <div className="runs-control-panel">
                <div className="runs-control-block">
                    <div className="runs-control-title">Current State</div>
                    <div className="runs-pill-row">
                        <span className={`pill ${controls.scrape_enabled ? 'pill-success' : 'pill-unknown'}`}>
                            {controls.scrape_enabled ? 'Scheduled scrape enabled' : 'Scheduled scrape disabled'}
                        </span>
                        <span className={`pill ${activeRun?.active ? 'pill-running' : 'pill-unknown'}`}>
                            {activeRun?.active ? 'Scrape currently running' : 'No active scrape run'}
                        </span>
                        <span className={`pill ${llmStatus?.enabled === false ? 'pill-unknown' : (llmStatus?.available ? 'pill-success' : 'pill-fail')}`}
                            title={llmStatus?.enabled === false ? 'LLM checks are disabled by runtime controls' : (llmStatus?.available ? (llmStatus.models || []).join(', ') : `LLM server not reachable at ${llmStatus?.url}`)}>
                            {llmStatus?.enabled === false ? 'LLM review disabled' : (llmStatus?.available ? 'LLM online' : 'LLM offline')}
                        </span>
                        <span className="pill pill-unknown" title="Scheduled minimum interval between automatic runs">
                            {cadenceLabel}
                        </span>
                        <span className={`pill ${controls.schedule_stop_at ? 'pill-fail' : 'pill-unknown'}`} title="Auto-shutoff window">
                            {stopLabel}
                        </span>
                    </div>
                    <div className="control-note">
                        {controls.updated_at ? `Last control change: ${fmtDate(controls.updated_at)}` : 'No control changes yet'}
                    </div>
                </div>

                <div className="runs-control-block">
                    <div className="runs-control-title">Runtime Toggles</div>
                    <div className="switch-row">
                        <div className="switch-item">
                            <div className="switch-meta">
                                <strong>Scheduled Scrape</strong>
                                <span>Keep launchd runs active or pause them at runtime.</span>
                            </div>
                            <label className="switch">
                                <input type="checkbox" checked={controls.scrape_enabled} disabled={loadingControls} onChange={handleToggleScrape} />
                                <span className="slider"></span>
                            </label>
                        </div>
                        <div className="switch-item">
                            <div className="switch-meta">
                                <strong>Scheduled LLM Review</strong>
                                <span>Control whether scheduled scrapes run the LLM review stage.</span>
                            </div>
                            <label className="switch">
                                <input type="checkbox" checked={controls.llm_enabled} disabled={loadingControls} onChange={handleToggleLlm} />
                                <span className="slider"></span>
                            </label>
                        </div>
                    </div>
                </div>

                <div className="runs-control-block">
                    <div className="runs-control-title">Schedule Window</div>
                    <div className="schedule-form">
                        <label className="schedule-label">
                            <span>Run cadence</span>
                            <select
                                value={scheduleIntervalMinutes}
                                disabled={savingSchedule || loadingControls}
                                onChange={(e) => setScheduleIntervalMinutes(Number(e.target.value))}
                            >
                                {SCHEDULE_INTERVAL_OPTIONS.map((opt) => (
                                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                                ))}
                            </select>
                        </label>
                        <label className="schedule-label">
                            <span>Custom cadence (minutes)</span>
                            <input
                                type="number"
                                min={1}
                                step={1}
                                value={customIntervalMinutes}
                                disabled={savingSchedule || loadingControls}
                                onChange={(e) => setCustomIntervalMinutes(e.target.value)}
                                placeholder="Optional override, e.g. 240"
                            />
                        </label>
                        <label className="schedule-label">
                            <span>Shutoff</span>
                            <select
                                value={scheduleStopAfterHours}
                                disabled={savingSchedule || loadingControls}
                                onChange={(e) => setScheduleStopAfterHours(e.target.value)}
                            >
                                {SCHEDULE_STOP_OPTIONS.map((opt) => (
                                    <option key={String(opt.value)} value={opt.value}>{opt.label}</option>
                                ))}
                            </select>
                        </label>
                        <label className="schedule-label">
                            <span>Custom shutoff (hours)</span>
                            <input
                                type="number"
                                min={1}
                                step={1}
                                value={customStopAfterHours}
                                disabled={savingSchedule || loadingControls}
                                onChange={(e) => setCustomStopAfterHours(e.target.value)}
                                placeholder="Optional override, e.g. 36"
                            />
                        </label>
                        <div className="control-action-row">
                            <button
                                className="btn btn-primary"
                                disabled={savingSchedule || loadingControls}
                                onClick={handleSaveSchedule}
                            >
                                {savingSchedule ? 'Applying...' : 'Apply Schedule'}
                            </button>
                            <button
                                className="btn btn-ghost"
                                disabled={savingSchedule || loadingControls || !controls.scrape_enabled}
                                onClick={handleDisableScheduledScrape}
                            >
                                Disable Scheduled Scrape
                            </button>
                            <button
                                className="btn btn-danger"
                                disabled={savingSchedule || loadingControls}
                                onClick={handleStopScheduledRunsNow}
                            >
                                Stop Scheduled Runs Now
                            </button>
                            <button
                                className="btn btn-ghost"
                                disabled={savingSchedule || loadingControls || !activeRun?.active || !activeRun?.run_id}
                                onClick={handleTerminateActiveRun}
                            >
                                Terminate Active Run
                            </button>
                        </div>
                        <div className="control-note">
                            If custom values are set, they override the dropdowns. Manual pipeline runs still execute immediately.
                        </div>
                    </div>
                </div>

                <div className="runs-control-block">
                    <div className="runs-control-title">Manual Pipeline Run</div>
                    <div className="control-actions">
                        <div className="control-action-row">
                            <button className="btn btn-primary" disabled={loadingRunner || runner.running || activeRun?.active} onClick={() => startManualRun(true)}>
                                {loadingRunner ? 'Starting...' : (runner.running ? 'Manual run in progress' : 'Run Pipeline With LLM')}
                            </button>
                            <button className="btn btn-ghost" disabled={loadingRunner || runner.running || activeRun?.active} onClick={() => startManualRun(false)}>
                                Run Pipeline Without LLM
                            </button>
                            <button className="btn btn-ghost btn-sm" onClick={fetchRunnerStatus}>Refresh</button>
                        </div>
                        <div className="control-note">Manual runs always bypass scheduled controls.</div>

                        {runner.started_at && (
                            <div className="control-note" style={{ marginTop: '8px' }}>
                                Last manual run: <strong>{runner.running ? 'running' : (runner.exit_code === 0 ? 'completed' : 'failed')}</strong>
                                <div>Started: {fmtDate(runner.started_at)}</div>
                                {runner.options && (
                                    <div>— LLM: <strong>{runner.options.llm_enabled_override === false ? 'off' : 'on'}</strong></div>
                                )}
                            </div>
                        )}

                        {runner.log_tail && (
                            <pre className="manual-log" style={{ marginTop: '12px', fontSize: '0.75rem', padding: '8px', background: '#1e1e2e', color: '#cdd6f4', borderRadius: '6px', maxHeight: '150px', overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                                {runner.log_tail}
                            </pre>
                        )}
                    </div>
                </div>
            </div>

            {stats && (
                <div className="cards" style={{ marginBottom: '24px' }}>
                    <div className="card">
                        <div className="card-label">Avg Duration</div>
                        <div className="card-value" style={{ fontSize: '1.3rem' }}>{fmtDuration(stats.avg_duration)}</div>
                    </div>
                    <div className="card">
                        <div className="card-label">Success Rate</div>
                        <div className="card-value" style={{ fontSize: '1.3rem' }}>{stats.success_rate}%</div>
                    </div>
                    <div className="card">
                        <div className="card-label">Avg Jobs/Run</div>
                        <div className="card-value" style={{ fontSize: '1.3rem' }}>{stats.avg_jobs_per_run}</div>
                    </div>
                    <div className="card">
                        <div className="card-label">Total Runs</div>
                        <div className="card-value" style={{ fontSize: '1.3rem' }}>{stats.total_runs}</div>
                    </div>
                </div>
            )}

            {chartData && <RunTimelineChart data={chartData} options={chartOptions} />}
            </PagePrimary>
            <PageSecondary>
            <WorkflowPanel>
                {runsLoading && <LoadingState />}
                {!runsLoading && (
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Duration</th>
                                <th>Status</th>
                                <th>Pipeline</th>
                                <th>Stored</th>
                                <th>Rejected</th>
                                <th>Run ID</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {runs.map((run: any) => (
                                <Fragment key={run.run_id}>
                                    <tr>
                                        <td>
                                            <div style={{ whiteSpace: 'nowrap', cursor: 'pointer' }} onClick={() => toggleRunExpand(run.run_id)}>
                                                <span>{fmtDate(run.started_at)}</span>
                                                <span style={{ fontSize: '0.8rem', color: 'var(--accent)', marginLeft: '4px' }}>
                                                    {expandedRunId === run.run_id ? '▼' : '▶'}
                                                </span>
                                            </div>
                                        </td>
                                        <td>{run.elapsed != null ? fmtDuration(run.elapsed) : '—'}</td>
                                        <td>
                                            <span className={`pill ${run.status === 'complete' ? 'pill-success' : (run.status === 'running' ? 'pill-running' : 'pill-fail')}`}>
                                                {run.status}
                                            </span>
                                        </td>
                                        <td>
                                            <div className="run-flow">
                                                <span>{run.raw_count ?? '—'}</span>
                                                <span className="arrow">&#8594;</span>
                                                <span>{run.dedup_count ?? '—'}</span>
                                                <span className="arrow">&#8594;</span>
                                                <strong>{run.filtered_count ?? '—'}</strong>
                                            </div>
                                        </td>
                                        <td style={{ fontWeight: 600 }}>{run.job_count ?? '—'}</td>
                                        <td style={{ color: 'var(--red)', fontWeight: 600 }}>{run.filtered_count - (run.job_count || 0)}</td>
                                        <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{run.run_id.slice(0, 12)}...</td>
                                        <td>
                                            <ActionBar style={{ gap: '4px' }}>
                                                <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/scraping/intake/jobs?run_id=${run.run_id}`)}>Jobs</button>
                                                <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/scraping/intake/rejected?run_id=${run.run_id}`)}>Rej</button>
                                                {run.status === 'running' && (
                                                    <button
                                                        className="btn btn-sm"
                                                        style={{ padding: '2px 6px', fontSize: '0.75rem', marginLeft: '6px', background: '#ef476f', color: '#fff' }}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleTerminate(run.run_id);
                                                        }}
                                                        title="Terminate this run"
                                                    >
                                                        Terminate
                                                    </button>
                                                )}
                                            </ActionBar>
                                        </td>
                                    </tr>

                                    {/* Dropdown Details */}
                                    {expandedRunId === run.run_id && (
                                        <tr className="runs-expanded">
                                            <td colSpan={8}>
                                                <div className="run-expanded-inner">
                                                    {run.status === 'running' ? (
                                                        <div className="live-log-container">
                                                            <div style={{ fontWeight: 600, fontSize: '.9rem', marginBottom: '8px', color: '#06d6a0' }}>
                                                                ● Live Run Logs
                                                            </div>
                                                            <LogPanel
                                                                text={liveLogsError ? `Error: ${liveLogsError}` : (liveLogs.length > 0 ? liveLogs.join('\n') : 'Waiting for logs...')}
                                                                style={{ fontSize: '0.75rem', padding: '12px', background: '#1e1e2e', color: liveLogsError ? '#ef476f' : '#cdd6f4', borderRadius: '6px', maxHeight: '400px', overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}
                                                            />
                                                        </div>
                                                    ) : (
                                                        <div style={{ marginTop: '12px' }}>
                                                            {/* Funnel */}
                                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '16px', padding: '12px', background: '#f8fafc', borderRadius: '6px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '4px' }}>Run Attrition Funnel</div>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                                    <div style={{ width: '80px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Raw</div>
                                                                    <div style={{ flex: 1, height: '12px', background: '#e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                                                                        <div style={{ height: '100%', background: 'var(--purple)', width: `${run.raw_count ? 100 : 0}%` }}></div>
                                                                    </div>
                                                                    <div style={{ width: '40px', fontSize: '0.75rem', fontWeight: 600 }}>{run.raw_count || 0}</div>
                                                                </div>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                                    <div style={{ width: '80px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Unique</div>
                                                                    <div style={{ flex: 1, height: '12px', background: '#e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                                                                        <div style={{ height: '100%', background: 'var(--cyan)', width: `${run.raw_count ? (run.dedup_count / run.raw_count * 100) : 0}%` }}></div>
                                                                    </div>
                                                                    <div style={{ width: '40px', fontSize: '0.75rem', fontWeight: 600 }}>{run.dedup_count || 0}</div>
                                                                </div>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                                    <div style={{ width: '80px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Filtered</div>
                                                                    <div style={{ flex: 1, height: '12px', background: '#e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                                                                        <div style={{ height: '100%', background: 'var(--amber)', width: `${run.raw_count ? (run.filtered_count / run.raw_count * 100) : 0}%` }}></div>
                                                                    </div>
                                                                    <div style={{ width: '40px', fontSize: '0.75rem', fontWeight: 600 }}>{run.filtered_count || 0}</div>
                                                                </div>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                                    <div style={{ width: '80px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Stored</div>
                                                                    <div style={{ flex: 1, height: '12px', background: '#e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                                                                        <div style={{ height: '100%', background: 'var(--green)', width: `${run.raw_count ? (run.job_count / run.raw_count * 100) : 0}%` }}></div>
                                                                    </div>
                                                                    <div style={{ width: '40px', fontSize: '0.75rem', fontWeight: 600 }}>{run.job_count || 0}</div>
                                                                </div>
                                                            </div>

                                                            {/* Errors */}
                                                            {run.errors && run.errors.length > 0 && (
                                                                <div className="error-panel">
                                                                    <div className="error-panel-title">Errors ({run.errors.length})</div>
                                                                    {run.errors.map((err: string, i: number) => (
                                                                        <div key={i} className="error-item">{err}</div>
                                                                    ))}
                                                                </div>
                                                            )}

                                                            {/* Jobs */}
                                                            {!expandedRunDetail ? (
                                                                <LoadingState style={{ padding: '12px' }} />
                                                            ) : (
                                                                <div>
                                                                    <div style={{ fontWeight: 600, marginBottom: '8px', fontSize: '0.85rem' }}>{expandedRunDetail.jobs?.length || 0} jobs from this run</div>
                                                                    {(expandedRunDetail.jobs?.length || 0) > 0 && (
                                                                        <table style={{ fontSize: '0.85rem' }}>
                                                                            <thead><tr><th>Title</th><th>Board</th><th>Seniority</th></tr></thead>
                                                                            <tbody>
                                                                                {expandedRunDetail.jobs.slice(0, 20).map((rj: any) => (
                                                                                    <tr key={rj.id}>
                                                                                        <td><a href={rj.url} target="_blank" rel="noreferrer" style={{ fontSize: '0.85rem' }}>{rj.title}</a></td>
                                                                                        <td><span className={`pill pill-${rj.board}`}>{rj.board}</span></td>
                                                                                        <td><span className={`pill pill-${rj.seniority}`}>{rj.seniority}</span></td>
                                                                                    </tr>
                                                                                ))}
                                                                            </tbody>
                                                                        </table>
                                                                    )}
                                                                    {(expandedRunDetail.jobs?.length || 0) > 20 && (
                                                                        <div style={{ padding: '8px 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                                            + {expandedRunDetail.jobs.length - 20} more...
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    )}
                                </Fragment>
                            ))}
                        </tbody>
                    </table>
                )}

                {pages > 1 && (
                    <div className="pagination">
                        <div className="pagination-info">Page {page} of {pages}</div>
                        <div className="pagination-controls">
                            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
                            <span className="page-num">{page} / {pages}</span>
                            <button disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next</button>
                        </div>
                    </div>
                )}
            </WorkflowPanel>
            </PageSecondary>
        </PageView>
    );
}
