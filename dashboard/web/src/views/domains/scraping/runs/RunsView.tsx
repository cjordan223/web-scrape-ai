import { Fragment, useEffect, useRef, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../../../api';
import { copyText } from '../../../../utils';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend,
    Filler
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
    Legend,
    Filler
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

const NOISY_LOG_PATTERNS = [
    /urllib3\.connectionpool/,
    /^\[(?:INIT|FETCH|SCRAPE|COMPLETE)\]/,
    /^[┏┗┃┡│└┌├┬┴─]+/,
];

const stripLogPrefix = (line: string) => {
    const marker = line.indexOf(' — ');
    return marker >= 0 ? line.slice(marker + 3).trim() : line.trim();
};

const splitLogLines = (text: string | undefined | null) =>
    String(text || '')
        .split('\n')
        .map((line) => line.trimEnd())
        .filter(Boolean);

const findLastUsefulLine = (lines: string[]) => {
    const useful = [...lines].reverse().find((line) => !NOISY_LOG_PATTERNS.some((pattern) => pattern.test(line)));
    return useful || lines[lines.length - 1] || '';
};

const deriveConsoleSummary = (text: string, runner: any, activeRun: any) => {
    const lines = splitLogLines(text);
    const messages = lines.map(stripLogPrefix);
    const lastUseful = stripLogPrefix(findLastUsefulLine(lines));

    let queries: number | null = null;
    let searchResults: number | null = null;
    let crawlResults: number | null = null;
    let rawResults: number | null = null;
    let uniqueResults: number | null = null;
    let accepted: number | null = null;
    let rejected: number | null = null;
    let quarantined: number | null = null;
    let llmCalls = 0;
    let candidateProgress = '';
    let watcherResults: number | null = null;

    for (const message of messages) {
        let match = message.match(/^Executing (\d+) queries/);
        if (match) queries = Number(match[1]);

        match = message.match(/^Got (\d+) raw results from SearXNG/);
        if (match) searchResults = Number(match[1]);

        match = message.match(/^Got (\d+) results from Crawl4AI/);
        if (match) crawlResults = Number(match[1]);

        match = message.match(/^Got (\d+) results from watchers/);
        if (match) watcherResults = Number(match[1]);

        // Also catch individual watcher lines like "Watcher 'usajobs' (custom) returned N results"
        match = message.match(/^Watcher .+ returned (\d+) results/);
        if (match) watcherResults = (watcherResults || 0) + Number(match[1]);

        match = message.match(/^USAJobs: (\d+) unique results/);
        if (match) watcherResults = Number(match[1]);

        match = message.match(/^Total raw results: (\d+)/);
        if (match) rawResults = Number(match[1]);

        match = message.match(/^(\d+) new \(unseen\) results after dedup/);
        if (match) uniqueResults = Number(match[1]);

        match = message.match(/^Candidate (\d+)\/(\d+):/);
        if (match) candidateProgress = `${match[1]} / ${match[2]}`;

        match = message.match(/^(\d+) jobs passed filters, (\d+) rejected, (\d+) quarantined/);
        if (match) {
            accepted = Number(match[1]);
            rejected = Number(match[2]);
            quarantined = Number(match[3]);
        }

        if (message.startsWith('LLM Review Call')) llmCalls += 1;
    }

    const phaseMatchers = [
        { label: 'Persisting results', pattern: /Persisted \d+\/\d+ results|Promoted \d+ review candidates|jobs passed filters/ },
        { label: 'Running LLM review', pattern: /LLM Review Call|LLM review completed|LLM passed|LLM rejected/ },
        { label: 'Filtering candidates', pattern: /Candidate \d+\/\d+|Filter outcome|Rejecting '|Accepted '|Quarantining '/ },
        { label: 'Deduplicating URLs', pattern: /new \(unseen\) results after dedup|Skipping previously seen URL|Skipping in-run duplicate URL/ },
        { label: 'Running watchers', pattern: /Watcher .+ returned|USAJobs:|Got \d+ results from watchers/ },
        { label: 'Crawling boards', pattern: /Crawling \d+ job board targets|Crawl target \d+\/\d+|Got \d+ results from Crawl4AI/ },
        { label: 'Searching via SearXNG', pattern: /Executing \d+ queries|Query \d+\/\d+|raw results from SearXNG/ },
        { label: 'Initializing scrape', pattern: /Scrape config|LLM review override applied/ },
    ];

    const phase =
        phaseMatchers.find((entry) => messages.some((message) => entry.pattern.test(message)))?.label ||
        (activeRun?.active ? 'Waiting for runtime output' : 'Idle');

    const sourceLabel = activeRun?.active ? (runner?.running ? 'Manual live run' : 'Scheduled live run') : 'Last manual run';
    const statusTone = activeRun?.active ? 'pill-running' : (runner?.exit_code === 0 ? 'pill-success' : (runner?.started_at ? 'pill-fail' : 'pill-unknown'));
    const statusLabel = activeRun?.active
        ? 'Pipeline active'
        : runner?.started_at
            ? (runner.exit_code === 0 ? 'Last run completed' : 'Last run ended with errors')
            : 'No recent manual run';

    return {
        phase,
        sourceLabel,
        statusTone,
        statusLabel,
        lastEvent: lastUseful || 'No runtime feedback yet.',
        candidateProgress: candidateProgress || '—',
        metrics: [
            { label: 'Queries', value: queries != null ? String(queries) : '—' },
            { label: 'Search', value: searchResults != null ? String(searchResults) : '—' },
            { label: 'Crawl', value: crawlResults != null ? String(crawlResults) : '—' },
            { label: 'Watchers', value: watcherResults != null ? String(watcherResults) : '—' },
            { label: 'Raw', value: rawResults != null ? String(rawResults) : '—' },
            { label: 'Unique', value: uniqueResults != null ? String(uniqueResults) : '—' },
            { label: 'Decision', value: accepted != null ? `${accepted}/${rejected ?? 0}/${quarantined ?? 0}` : '—' },
            { label: 'LLM calls', value: llmCalls > 0 ? String(llmCalls) : '—' },
        ],
    };
};

function SourceDiagnosticsPanel() {
    const [diag, setDiag] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [collapsed, setCollapsed] = useState(false);

    useEffect(() => {
        (async () => {
            try {
                setDiag(await api.getSourceDiagnostics());
            } catch (e) {
                console.error('Failed to load source diagnostics', e);
            } finally {
                setLoading(false);
            }
        })();
    }, []);

    if (loading) return <WorkflowPanel><LoadingState /></WorkflowPanel>;
    if (!diag) return null;

    const { by_source, by_board, rejection_by_board, recent_runs, top_rejections } = diag;
    const totalAccepted = by_source.reduce((s: number, r: any) => s + r.accepted, 0);

    return (
        <WorkflowPanel>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: collapsed ? 0 : '16px' }}>
                <div className="runs-control-title" style={{ cursor: 'pointer' }} onClick={() => setCollapsed(c => !c)}>
                    Source Diagnostics {collapsed ? '▶' : '▼'}
                </div>
            </div>

            {!collapsed && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    {/* Source breakdown */}
                    <div>
                        <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '8px' }}>Accepted Jobs by Source</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {by_source.map((s: any) => {
                                const pct = totalAccepted > 0 ? (s.accepted / totalAccepted * 100) : 0;
                                const label = s.source === 'searxng' ? 'SearXNG' : s.source === 'crawl4ai' ? 'Crawl4AI' : s.source.replace('watcher:', '');
                                return (
                                    <div key={s.source} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <div style={{ width: '100px', fontSize: '0.8rem', fontWeight: 500 }}>{label}</div>
                                        <div style={{ flex: 1, height: '14px', background: '#e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                                            <div style={{
                                                height: '100%',
                                                borderRadius: '6px',
                                                width: `${pct}%`,
                                                background: s.source === 'searxng' ? 'var(--purple)' : s.source === 'crawl4ai' ? 'var(--cyan)' : 'var(--amber)',
                                            }} />
                                        </div>
                                        <div style={{ width: '70px', fontSize: '0.8rem', fontWeight: 600, textAlign: 'right' }}>
                                            {s.accepted} <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>({pct.toFixed(0)}%)</span>
                                        </div>
                                        <div style={{ width: '70px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {s.runs} run{s.runs !== 1 ? 's' : ''}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {/* Board breakdown */}
                    <div>
                        <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '8px' }}>Accepted Jobs by Board</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                            {by_board.map((b: any) => (
                                <span key={b.board} className={`pill pill-${b.board}`} style={{ fontSize: '0.8rem' }}>
                                    {b.board}: {b.accepted}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Top rejection stages */}
                    <div>
                        <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '8px' }}>Top Rejection Stages (all time)</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                            {top_rejections.map((r: any) => (
                                <span key={r.stage} className="pill pill-fail" style={{ fontSize: '0.8rem' }}>
                                    {r.stage}: {r.count.toLocaleString()}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Rejection heatmap by board */}
                    {Object.keys(rejection_by_board).length > 0 && (
                        <div>
                            <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '8px' }}>Rejection Stages by Board</div>
                            <div style={{ overflowX: 'auto' }}>
                                <table style={{ fontSize: '0.8rem' }}>
                                    <thead>
                                        <tr>
                                            <th>Board</th>
                                            <th>Top Rejection Stage</th>
                                            <th>Count</th>
                                            <th>Total Rejected</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {Object.entries(rejection_by_board).map(([board, stages]: [string, any]) => {
                                            const sorted = Object.entries(stages).sort((a: any, b: any) => b[1] - a[1]);
                                            const total = sorted.reduce((s: number, [, c]: any) => s + c, 0);
                                            const [topStage, topCount] = sorted[0] || ['—', 0];
                                            return (
                                                <tr key={board}>
                                                    <td><span className={`pill pill-${board}`}>{board}</span></td>
                                                    <td>{topStage}</td>
                                                    <td>{topCount as number}</td>
                                                    <td>{total}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Recent runs source breakdown */}
                    <div>
                        <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '8px' }}>Recent Runs — Source Breakdown</div>
                        <div style={{ overflowX: 'auto' }}>
                            <table style={{ fontSize: '0.8rem' }}>
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>Status</th>
                                        <th>Raw</th>
                                        <th>Stored</th>
                                        <th>Sources</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {recent_runs.map((r: any) => {
                                        const stored = Object.values(r.sources as Record<string, number>).reduce((s: number, c: number) => s + c, 0);
                                        return (
                                            <tr key={r.run_id}>
                                                <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(r.started_at)}</td>
                                                <td><span className={`pill ${r.status === 'complete' ? 'pill-success' : 'pill-fail'}`}>{r.status}</span></td>
                                                <td>{r.raw_count || 0}</td>
                                                <td style={{ fontWeight: 600 }}>{stored}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                                                        {Object.entries(r.sources as Record<string, number>).map(([src, cnt]) => {
                                                            const label = src === 'searxng' ? 'SearXNG' : src === 'crawl4ai' ? 'Crawl4AI' : src.replace('watcher:', '');
                                                            return <span key={src} className="pill pill-unknown" style={{ fontSize: '0.75rem' }}>{label}: {cnt}</span>;
                                                        })}
                                                        {Object.keys(r.sources).length === 0 && <span style={{ color: 'var(--text-secondary)' }}>—</span>}
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}
        </WorkflowPanel>
    );
}

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
    const consoleLogRef = useRef<HTMLPreElement>(null);
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [expandedRunDetail, setExpandedRunDetail] = useState<any>(null);
    const [liveLogs, setLiveLogs] = useState<string[]>([]);
    const [liveLogsError, setLiveLogsError] = useState<string | null>(null);
    const [activeConsoleLines, setActiveConsoleLines] = useState<string[]>([]);
    const [activeConsoleError, setActiveConsoleError] = useState<string | null>(null);
    const [activeConsoleLogPath, setActiveConsoleLogPath] = useState<string | null>(null);

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
                fetchActiveRun();
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

    useEffect(() => {
        let interval: number | undefined;

        if (activeRun?.active && activeRun?.run_id) {
            const fetchConsole = async () => {
                try {
                    const data = await api.getRunLogs(activeRun.run_id!, 400);
                    setActiveConsoleLines(data.lines || []);
                    setActiveConsoleError(null);
                    setActiveConsoleLogPath(data.log_path || null);
                } catch (err: any) {
                    setActiveConsoleError(err.response?.data?.error || 'Failed to fetch live run logs');
                    setActiveConsoleLines([]);
                    setActiveConsoleLogPath(null);
                }
            };

            fetchConsole();
            interval = window.setInterval(fetchConsole, 3000);
        } else {
            setActiveConsoleLines([]);
            setActiveConsoleError(null);
            setActiveConsoleLogPath(null);
        }

        return () => {
            if (interval) window.clearInterval(interval);
        };
    }, [activeRun?.active, activeRun?.run_id]);

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

    const consoleText = useMemo(() => {
        if (activeRun?.active) {
            if (activeConsoleError) return `Error: ${activeConsoleError}`;
            if (activeConsoleLines.length > 0) return activeConsoleLines.join('\n');
            return 'Waiting for live pipeline output...';
        }
        if (runner.log_tail) return runner.log_tail;
        return 'No live scrape output yet. Start a manual pipeline run or wait for the next scheduled scrape.';
    }, [activeConsoleError, activeConsoleLines, activeRun?.active, runner.log_tail]);

    const consoleSummary = useMemo(
        () => deriveConsoleSummary(consoleText, runner, activeRun),
        [consoleText, runner, activeRun]
    );

    useEffect(() => {
        if (consoleLogRef.current) {
            consoleLogRef.current.scrollTop = consoleLogRef.current.scrollHeight;
        }
    }, [consoleText]);

    return (
        <PageView>
            <PageHeader title="Run History & Controls" />
            <PagePrimary>
            <div className="runs-control-panel runs-control-panel--compact">
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
            </div>

            <WorkflowPanel className="scrape-console-panel">
                <div className="scrape-console-shell">
                    <div className="scrape-console-sidebar">
                        <div className="scrape-console-heading">
                            <div>
                                <div className="runs-control-title">Pipeline Console</div>
                                <div className="scrape-console-title-row">
                                    <h3>Manual Run + Live Runtime Feedback</h3>
                                    <div className="runs-pill-row">
                                        <span className={`pill ${consoleSummary.statusTone}`}>{consoleSummary.statusLabel}</span>
                                        <span className="pill pill-unknown">{consoleSummary.sourceLabel}</span>
                                        <span className="pill pill-unknown">{consoleSummary.phase}</span>
                                    </div>
                                </div>
                            </div>
                            <div className="control-action-row">
                                <button className="btn btn-primary" disabled={loadingRunner || runner.running || activeRun?.active} onClick={() => startManualRun(true)}>
                                    {loadingRunner ? 'Starting...' : (runner.running ? 'Manual run in progress' : 'Run Pipeline With LLM')}
                                </button>
                                <button className="btn btn-ghost" disabled={loadingRunner || runner.running || activeRun?.active} onClick={() => startManualRun(false)}>
                                    Run Pipeline Without LLM
                                </button>
                                <button className="btn btn-ghost btn-sm" onClick={fetchRunnerStatus}>Refresh</button>
                                <button className="btn btn-ghost btn-sm" onClick={() => { void copyText(consoleText); }}>
                                    Copy Log
                                </button>
                            </div>
                        </div>

                        <div className="control-note">
                            Manual runs always bypass scheduled controls. Scheduled runs will also stream here while active.
                        </div>

                        <div className="scrape-console-metrics">
                            {consoleSummary.metrics.map((metric) => (
                                <div key={metric.label} className="scrape-console-metric">
                                    <div className="scrape-console-metric-label">{metric.label}</div>
                                    <div className="scrape-console-metric-value">{metric.value}</div>
                                </div>
                            ))}
                        </div>

                        <div className="scrape-console-detail-grid">
                            <div className="scrape-console-detail">
                                <span>Candidate Progress</span>
                                <strong>{consoleSummary.candidateProgress}</strong>
                            </div>
                            <div className="scrape-console-detail">
                                <span>Started</span>
                                <strong>{runner.started_at ? fmtDate(runner.started_at) : '—'}</strong>
                            </div>
                            <div className="scrape-console-detail">
                                <span>LLM Mode</span>
                                <strong>{runner.options?.llm_enabled_override === false ? 'Manual off' : (controls.llm_enabled ? 'Enabled' : 'Scheduled off')}</strong>
                            </div>
                            <div className="scrape-console-detail">
                                <span>Log File</span>
                                <strong title={activeConsoleLogPath || runner.log_path || ''}>{activeConsoleLogPath || runner.log_path || '—'}</strong>
                            </div>
                        </div>

                        <div className="scrape-console-last-event">
                            <div className="runs-control-title">Latest Runtime Event</div>
                            <div>{consoleSummary.lastEvent}</div>
                        </div>
                    </div>

                    <div className="scrape-console-stream">
                        <div className="scrape-console-stream-header">
                            <div>
                                <div className="runs-control-title">Live Pipeline Output</div>
                                <div className="scrape-console-stream-subtitle">
                                    {activeRun?.active ? 'Streaming the active scrape log with live polling.' : 'Showing the most recent manual scrape log.'}
                                </div>
                            </div>
                        </div>
                        <pre ref={consoleLogRef} className="manual-log scrape-console-log">
                            {consoleText}
                        </pre>
                    </div>
                </div>
            </WorkflowPanel>

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

            <SourceDiagnosticsPanel />
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
