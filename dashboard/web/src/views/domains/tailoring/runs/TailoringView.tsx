import { useEffect, useState, useCallback, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../../../../api';
import JobInventoryTab from './JobInventoryTab';
import PipelineTab from './PipelineTab';
import RunHistoryTab from './RunHistoryTab';
type Tab = 'jobs' | 'pipeline' | 'history';
const TAILORING_RUNS_TAB_KEY = 'tailoring.runs.activeTab';

function getInitialTab(pathname?: string): Tab {
    if (pathname === '/pipeline/ready') return 'jobs';
    if (typeof window === 'undefined') return 'history';
    const saved = window.localStorage.getItem(TAILORING_RUNS_TAB_KEY);
    if (saved === 'jobs' || saved === 'pipeline' || saved === 'history') {
        return saved;
    }
    return 'history';
}

const tabs: { key: Tab; label: string }[] = [
    { key: 'jobs', label: 'Ready' },
    { key: 'pipeline', label: 'Pipeline' },
    { key: 'history', label: 'History' },
];

export default function TailoringView() {
    const location = useLocation();
    const [activeTab, setActiveTab] = useState<Tab>(() => getInitialTab(location.pathname));

    // --- Shared state ---
    const [runs, setRuns] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [runner, setRunner] = useState<any>({ running: false, log_tail: '' });
    const [llmStatus, setLlmStatus] = useState<any>(null);
    const [stopBusy, setStopBusy] = useState(false);

    const prevRunningRef = useRef<boolean>(false);
    const runsRequestInFlightRef = useRef(false);
    const runnerRequestInFlightRef = useRef(false);
    const llmStatusRequestInFlightRef = useRef(false);

    // --- Data fetching ---

    const fetchRuns = useCallback(async () => {
        if (runsRequestInFlightRef.current) return;
        runsRequestInFlightRef.current = true;
        try {
            const res = await api.getTailoring();
            setRuns(res);
        } catch (err) { console.error(err); }
        finally {
            runsRequestInFlightRef.current = false;
            setLoading(false);
        }
    }, []);

    const fetchRunnerStatus = async () => {
        if (runnerRequestInFlightRef.current) return;
        runnerRequestInFlightRef.current = true;
        try {
            const res = await api.getTailoringRunnerStatus();
            setRunner(res);
        } catch (err) { console.error(err); }
        finally { runnerRequestInFlightRef.current = false; }
    };

    const fetchLlmStatus = async () => {
        if (llmStatusRequestInFlightRef.current) return;
        llmStatusRequestInFlightRef.current = true;
        try {
            const res = await api.getLlmStatus();
            setLlmStatus(res);
        } catch { /* ignore */ }
        finally { llmStatusRequestInFlightRef.current = false; }
    };

    const handleStopTailoringRuns = async () => {
        if (!runner.running && (!runner.queue || runner.queue.length === 0)) return;
        const confirmed = window.confirm('Stop the active tailoring run and clear queued tailoring jobs?');
        if (!confirmed) return;
        setStopBusy(true);
        try {
            await api.stopTailoringRunner({ clear_queue: true, wait_seconds: 5 });
            await fetchRunnerStatus();
            await fetchRuns();
        } catch (e: any) {
            alert(e?.response?.data?.error || 'Failed to stop tailoring runs');
        } finally {
            setStopBusy(false);
        }
    };

    // --- Effects ---

    useEffect(() => {
        fetchRuns();
        fetchRunnerStatus();
        fetchLlmStatus();
        const i1 = setInterval(fetchRuns, 30000);
        const i2 = setInterval(fetchRunnerStatus, 10000);
        return () => { clearInterval(i1); clearInterval(i2); };
    }, [fetchRuns]);

    useEffect(() => {
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(TAILORING_RUNS_TAB_KEY, activeTab);
        }
    }, [activeTab]);

    useEffect(() => {
        if (location.pathname === '/pipeline/ready') {
            setActiveTab('jobs');
        }
    }, [location.pathname]);

    // Fast-poll while runner active; auto-switch to pipeline tab
    useEffect(() => {
        if (!runner.running) {
            if (prevRunningRef.current) fetchRuns();
            prevRunningRef.current = false;
            return;
        }
        if (!prevRunningRef.current && location.pathname !== '/pipeline/ready') setActiveTab('pipeline');
        prevRunningRef.current = true;
        const f1 = setInterval(fetchRunnerStatus, 2000);
        const f2 = setInterval(fetchRuns, 5000);
        return () => { clearInterval(f1); clearInterval(f2); };
    }, [runner.running, location.pathname]);

    const onRunStarted = () => {
        fetchRunnerStatus();
        fetchRuns();
        setActiveTab('pipeline');
    };

    const modelName = (llmStatus?.selected_model || llmStatus?.models?.[0] || '').split('/').pop();
    const queueLen = runner.queue?.length || 0;
    const canStop = runner.running || queueLen > 0;

    // --- Render ---

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>

            {/* ══════════ TOOLBAR ══════════ */}
            <div className="tv-toolbar">
                {/* Tabs */}
                <div className="tv-tabs">
                    {tabs.map(t => (
                        <button
                            key={t.key}
                            className={`tv-tab${activeTab === t.key ? ' active' : ''}`}
                            onClick={() => setActiveTab(t.key)}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {/* Status cluster — right side */}
                <div className="tv-status">
                    <span className={`status-dot ${runner.running ? 'active' : 'idle'}`} />
                    <span className="tv-status-label">
                        {runner.running ? 'RUNNING' : 'IDLE'}
                    </span>
                    {runner.running && runner.job && (
                        <span className="tv-status-dim">#{runner.job.id}</span>
                    )}
                    {queueLen > 0 && (
                        <span className="tv-badge tv-badge--amber">{queueLen}q</span>
                    )}

                    {modelName && (
                        <>
                            <span className="tv-sep" />
                            <span className="tv-badge tv-badge--green" title={llmStatus?.selected_model || llmStatus?.models?.[0]}>
                                {modelName}
                            </span>
                            <a href="/ops/llm" className="tv-link">Configure</a>
                        </>
                    )}

                    <span className="tv-sep" />
                    <button
                        className="btn btn-danger btn-sm"
                        onClick={handleStopTailoringRuns}
                        disabled={stopBusy || !canStop}
                        title="Stop active run and clear queue"
                        style={{ fontSize: '.68rem', padding: '2px 8px' }}
                    >
                        {stopBusy ? 'Stopping...' : 'Stop'}
                    </button>
                </div>
            </div>

            {/* ══════════ TAB CONTENT ══════════ */}
            <div style={{
                flex: 1,
                minHeight: 0,
                overflow: 'hidden',
                background: 'var(--surface)',
            }}>
                {activeTab === 'jobs' && (
                    <JobInventoryTab onRunStarted={onRunStarted} />
                )}
                {activeTab === 'pipeline' && (
                    <PipelineTab runner={runner} runs={runs} />
                )}
                {activeTab === 'history' && (
                    <RunHistoryTab runs={runs} loading={loading} onRunStarted={onRunStarted} />
                )}
            </div>
        </div>
    );
}
