import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import JobInventoryTab from './JobInventoryTab';
import PipelineTab from './PipelineTab';
import RunHistoryTab from './RunHistoryTab';
import IngestTab from './IngestTab';

type Tab = 'jobs' | 'pipeline' | 'history' | 'ingest';

export default function TailoringView() {
    const [activeTab, setActiveTab] = useState<Tab>('jobs');

    // --- Shared state ---
    const [runs, setRuns] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [runner, setRunner] = useState<any>({ running: false, log_tail: '' });
    const [llmStatus, setLlmStatus] = useState<any>(null);
    const [models, setModels] = useState<{ id: string; state: string }[]>([]);
    const [modelPanelOpen, setModelPanelOpen] = useState(false);
    const [modelsLoading, setModelsLoading] = useState(false);
    const [modelBusy, setModelBusy] = useState<string | null>(null);
    const [modelError, setModelError] = useState('');
    const [stopBusy, setStopBusy] = useState(false);

    const prevRunningRef = useRef<boolean>(false);

    // --- Data fetching ---

    const fetchRuns = useCallback(async () => {
        try {
            const res = await api.getTailoring();
            setRuns(res);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    }, []);

    const fetchRunnerStatus = async () => {
        try {
            const res = await api.getTailoringRunnerStatus();
            setRunner(res);
        } catch (err) { console.error(err); }
    };

    const fetchLlmStatus = async () => {
        try {
            const res = await api.getLlmStatus();
            setLlmStatus(res);
        } catch { /* ignore */ }
    };

    const openModelPanel = async () => {
        setModelPanelOpen(true);
        setModelError('');
        setModelsLoading(true);
        try {
            const res = await api.getLlmModels();
            setModels(res.models || []);
        } catch (e: any) {
            setModelError(e?.response?.data?.error || 'Failed to fetch models');
            setModels([]);
        } finally {
            setModelsLoading(false);
        }
    };

    const handleLoadModel = async (id: string) => {
        setModelBusy(id);
        setModelError('');
        try {
            const res = await api.loadLlmModel(id);
            if (!res.ok) { setModelError(res.error || 'Load failed'); return; }
            const updated = await api.getLlmModels();
            setModels(updated.models || []);
            await fetchLlmStatus();
            setModelPanelOpen(false);
        } catch (e: any) {
            setModelError(e?.response?.data?.error || 'Load failed');
        } finally {
            setModelBusy(null);
        }
    };

    const handleUnloadModel = async (id: string) => {
        setModelBusy(id);
        setModelError('');
        try {
            const res = await api.unloadLlmModel(id);
            if (!res.ok) { setModelError(res.error || 'Unload failed'); return; }
            const updated = await api.getLlmModels();
            setModels(updated.models || []);
            await fetchLlmStatus();
        } catch (e: any) {
            setModelError(e?.response?.data?.error || 'Unload failed');
        } finally {
            setModelBusy(null);
        }
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

    // Fast-poll while runner active; auto-switch to pipeline tab
    useEffect(() => {
        if (!runner.running) {
            if (prevRunningRef.current) fetchRuns();
            prevRunningRef.current = false;
            return;
        }
        if (!prevRunningRef.current) setActiveTab('pipeline');
        prevRunningRef.current = true;
        const f1 = setInterval(fetchRunnerStatus, 2000);
        const f2 = setInterval(fetchRuns, 5000);
        return () => { clearInterval(f1); clearInterval(f2); };
    }, [runner.running]);

    const onRunStarted = () => {
        fetchRunnerStatus();
        fetchRuns();
        setActiveTab('pipeline');
    };

    // --- Render ---

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 56px)', overflow: 'hidden' }}>

            {/* ══════════ CONTROL STRIP ══════════ */}
            <div style={{
                display: 'flex', alignItems: 'center', gap: '12px', padding: '8px 16px',
                borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', flexShrink: 0,
                flexWrap: 'wrap',
            }}>
                {/* Runner status */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className={`status-dot ${runner.running ? 'active' : 'idle'}`} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.75rem', fontWeight: 500 }}>
                        {runner.running ? 'RUNNING' : 'IDLE'}
                    </span>
                    {runner.running && runner.job && (
                        <span style={{ fontSize: '.72rem', color: 'var(--text-secondary)' }}>
                            Job {runner.job.id}
                        </span>
                    )}
                    {runner.queue?.length > 0 && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.68rem',
                            background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                            borderRadius: '2px', padding: '1px 6px', color: 'var(--amber, #e0a030)',
                        }}>
                            {runner.queue.length} queued
                        </span>
                    )}
                </div>

                <div style={{ width: '1px', height: '20px', background: 'var(--border-bright)' }} />

                <button
                    className="btn btn-danger btn-sm"
                    onClick={handleStopTailoringRuns}
                    disabled={stopBusy || (!runner.running && (!runner.queue || runner.queue.length === 0))}
                    title="Gracefully stop active tailoring run and clear queued jobs"
                >
                    {stopBusy ? 'Stopping...' : 'Stop Tailoring Runs'}
                </button>

                {/* LLM Model */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em' }}>LLM</span>
                    {llmStatus?.models?.[0] && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.68rem',
                            background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                            borderRadius: '2px', padding: '1px 6px', color: 'var(--green)',
                            maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }} title={llmStatus.models[0]}>
                            {llmStatus.models[0].split('/').pop()}
                        </span>
                    )}
                    <button
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: '.68rem' }}
                        onClick={() => modelPanelOpen ? setModelPanelOpen(false) : openModelPanel()}
                    >
                        {modelPanelOpen ? 'Close' : 'Switch'}
                    </button>
                </div>

                {/* Tab bar — pushed right */}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: '2px' }}>
                    {([
                        { key: 'jobs' as Tab, label: 'Jobs' },
                        { key: 'pipeline' as Tab, label: 'Pipeline' },
                        { key: 'history' as Tab, label: 'History' },
                        { key: 'ingest' as Tab, label: 'Ingest' },
                    ]).map(t => (
                        <button
                            key={t.key}
                            className={`btn btn-sm ${activeTab === t.key ? 'btn-primary' : 'btn-ghost'}`}
                            onClick={() => setActiveTab(t.key)}
                            style={{ fontSize: '.78rem' }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Model switcher dropdown */}
            {modelPanelOpen && (
                <div style={{
                    padding: '8px 16px', borderBottom: '1px solid var(--border)', background: 'var(--surface)',
                    display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center', flexShrink: 0,
                }}>
                    {modelError && (
                        <div style={{ fontSize: '.7rem', color: 'var(--red)', fontFamily: 'var(--font-mono)', width: '100%' }}>{modelError}</div>
                    )}
                    {modelsLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>
                            <div className="spinner" style={{ width: '12px', height: '12px' }} /> Loading...
                        </div>
                    ) : models.length === 0 ? (
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>No models found</div>
                    ) : models.map(m => {
                        const isLoaded = m.state === 'loaded';
                        const isBusy = modelBusy === m.id;
                        return (
                            <div key={m.id} style={{
                                display: 'flex', alignItems: 'center', gap: '6px',
                                padding: '4px 8px', borderRadius: '2px',
                                background: isLoaded ? 'rgba(var(--green-rgb, 80,200,120), 0.08)' : 'var(--surface-3)',
                                border: `1px solid ${isLoaded ? 'var(--green)' : 'var(--border)'}`,
                            }}>
                                <span style={{
                                    width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0,
                                    background: isLoaded ? 'var(--green)' : 'var(--text-secondary)',
                                }} />
                                <span style={{
                                    fontFamily: 'var(--font-mono)', fontSize: '.68rem',
                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                    maxWidth: '200px',
                                }} title={m.id}>{m.id.split('/').pop()}</span>
                                {isBusy ? (
                                    <div className="spinner" style={{ width: '12px', height: '12px', flexShrink: 0 }} />
                                ) : isLoaded ? (
                                    <button className="btn btn-ghost btn-sm" style={{ fontSize: '.65rem', flexShrink: 0 }}
                                        onClick={() => handleUnloadModel(m.id)} disabled={modelBusy !== null}>Unload</button>
                                ) : (
                                    <button className="btn btn-primary btn-sm" style={{ fontSize: '.65rem', flexShrink: 0 }}
                                        onClick={() => handleLoadModel(m.id)} disabled={modelBusy !== null}>Load</button>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {/* ══════════ TAB CONTENT ══════════ */}
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                {activeTab === 'jobs' && (
                    <JobInventoryTab onRunStarted={onRunStarted} />
                )}
                {activeTab === 'pipeline' && (
                    <PipelineTab runner={runner} runs={runs} />
                )}
                {activeTab === 'history' && (
                    <RunHistoryTab runs={runs} loading={loading} />
                )}
                {activeTab === 'ingest' && (
                    <IngestTab onRunStarted={onRunStarted} />
                )}
            </div>
        </div>
    );
}
