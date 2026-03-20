import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../../api';
import JobInventoryTab from './JobInventoryTab';
import PipelineTab from './PipelineTab';
import RunHistoryTab from './RunHistoryTab';
type Tab = 'jobs' | 'pipeline' | 'history';
const TAILORING_RUNS_TAB_KEY = 'tailoring.runs.activeTab';

function getInitialTab(): Tab {
    if (typeof window === 'undefined') return 'history';
    const saved = window.localStorage.getItem(TAILORING_RUNS_TAB_KEY);
    if (saved === 'jobs' || saved === 'pipeline' || saved === 'history') {
        return saved;
    }
    return 'history';
}

export default function TailoringView() {
    const [activeTab, setActiveTab] = useState<Tab>(getInitialTab);

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
    const [llmProvider, setLlmProvider] = useState('lmstudio');
    const [llmBaseUrl, setLlmBaseUrl] = useState('http://localhost:1234');
    const [configBusy, setConfigBusy] = useState(false);

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
            setLlmProvider(res?.provider || 'openai');
            setLlmBaseUrl(res?.url || 'http://localhost:1234');
        } catch { /* ignore */ }
    };

    const openModelPanel = async () => {
        setModelPanelOpen(true);
        setModelError('');
        setModelsLoading(true);
        try {
            const status = await api.getLlmStatus();
            setLlmStatus(status);
            setLlmProvider(status?.provider || 'openai');
            setLlmBaseUrl(status?.url || 'http://localhost:1234');
            const res = await api.getLlmModels();
            setModels(res.models || []);
        } catch (e: any) {
            setModelError(e?.response?.data?.error || 'Failed to fetch models');
            setModels([]);
        } finally {
            setModelsLoading(false);
        }
    };

    const handleSaveConnection = async () => {
        setConfigBusy(true);
        setModelError('');
        setModelsLoading(true);
        try {
            await api.updateRunsControls({
                llm_provider: llmProvider,
                llm_base_url: llmBaseUrl,
            });
            await fetchLlmStatus();
            const updated = await api.getLlmModels();
            setModels(updated.models || []);
        } catch (e: any) {
            setModelError(e?.response?.data?.error || 'Failed to save LLM connection');
            setModels([]);
        } finally {
            setConfigBusy(false);
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

    useEffect(() => {
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(TAILORING_RUNS_TAB_KEY, activeTab);
        }
    }, [activeTab]);

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

            {/* ══════════ TAB BAR ══════════ */}
            <div style={{
                display: 'flex', alignItems: 'stretch', borderBottom: '2px solid var(--border)',
                background: 'var(--surface)', flexShrink: 0,
            }}>
                {([
                    { key: 'jobs' as Tab, label: 'Ready', desc: 'QA-approved backlog' },
                    { key: 'pipeline' as Tab, label: 'Pipeline', desc: 'Live run' },
                    { key: 'history' as Tab, label: 'History', desc: 'Past runs' },
                ]).map(t => {
                    const isActive = activeTab === t.key;
                    return (
                        <button
                            key={t.key}
                            onClick={() => setActiveTab(t.key)}
                            style={{
                                flex: 1, padding: '12px 16px', border: 'none', cursor: 'pointer',
                                background: isActive ? 'var(--surface-2)' : 'transparent',
                                borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                                marginBottom: '-2px',
                                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                transition: 'background .1s, border-color .1s',
                            }}
                            onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--surface-2)'; }}
                            onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                        >
                            <span style={{
                                fontFamily: 'var(--font-mono)', fontSize: '.88rem', fontWeight: isActive ? 700 : 500,
                                color: isActive ? 'var(--text)' : 'var(--text-secondary)',
                                letterSpacing: '.02em',
                            }}>{t.label}</span>
                            <span style={{
                                fontSize: '.62rem', color: 'var(--text-secondary)', opacity: isActive ? .9 : .6,
                            }}>{t.desc}</span>
                        </button>
                    );
                })}
            </div>

            {/* ══════════ STATUS BAR ══════════ */}
            <div style={{
                display: 'flex', alignItems: 'center', gap: '12px', padding: '6px 16px',
                borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', flexShrink: 0,
                flexWrap: 'wrap',
            }}>
                {/* Runner status */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className={`status-dot ${runner.running ? 'active' : 'idle'}`} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', fontWeight: 500 }}>
                        {runner.running ? 'RUNNING' : 'IDLE'}
                    </span>
                    {runner.running && runner.job && (
                        <span style={{ fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                            Job {runner.job.id}
                        </span>
                    )}
                    {runner.queue?.length > 0 && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.66rem',
                            background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                            borderRadius: '2px', padding: '1px 6px', color: 'var(--amber, #e0a030)',
                        }}>
                            {runner.queue.length} queued
                        </span>
                    )}
                </div>

                <div style={{ width: '1px', height: '16px', background: 'var(--border-bright)' }} />

                <button
                    className="btn btn-danger btn-sm"
                    onClick={handleStopTailoringRuns}
                    disabled={stopBusy || (!runner.running && (!runner.queue || runner.queue.length === 0))}
                    title="Gracefully stop active tailoring run and clear queued jobs"
                    style={{ fontSize: '.7rem' }}
                >
                    {stopBusy ? 'Stopping...' : 'Stop'}
                </button>

                <div style={{ width: '1px', height: '16px', background: 'var(--border-bright)' }} />

                {/* LLM Model */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.1em' }}>LLM</span>
                    {(llmStatus?.selected_model || llmStatus?.models?.[0]) && (
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.66rem',
                            background: 'var(--surface-3)', border: '1px solid var(--border-bright)',
                            borderRadius: '2px', padding: '1px 6px', color: 'var(--green)',
                            maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }} title={llmStatus?.selected_model || llmStatus?.models?.[0]}>
                            {(llmStatus?.selected_model || llmStatus?.models?.[0]).split('/').pop()}
                        </span>
                    )}
                    <button
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: '.66rem' }}
                        onClick={() => modelPanelOpen ? setModelPanelOpen(false) : openModelPanel()}
                    >
                        {modelPanelOpen ? 'Close' : 'Switch'}
                    </button>
                </div>
            </div>

            {/* Model switcher dropdown */}
            {modelPanelOpen && (
                <div style={{
                    padding: '8px 16px', borderBottom: '1px solid var(--border)', background: 'var(--surface)',
                    display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', flexShrink: 0,
                }}>
                    {modelError && (
                        <div style={{ fontSize: '.7rem', color: 'var(--red)', fontFamily: 'var(--font-mono)', width: '100%' }}>{modelError}</div>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', flexWrap: 'wrap' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '.72rem' }}>
                            <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>Provider</span>
                            <select
                                value={llmProvider}
                                onChange={(e) => setLlmProvider(e.target.value)}
                                disabled={configBusy}
                                style={{
                                    background: 'var(--surface-3)',
                                    color: 'var(--text)',
                                    border: '1px solid var(--border)',
                                    borderRadius: '2px',
                                    padding: '4px 6px',
                                }}
                            >
                                <option value="lmstudio">LM Studio</option>
                                <option value="openai">OpenAI-compatible</option>
                            </select>
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: '320px', flex: '1 1 320px' }}>
                            <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '.72rem' }}>Base URL</span>
                            <input
                                type="text"
                                value={llmBaseUrl}
                                onChange={(e) => setLlmBaseUrl(e.target.value)}
                                disabled={configBusy}
                                placeholder="http://localhost:1234"
                                style={{
                                    width: '100%',
                                    background: 'var(--surface-3)',
                                    color: 'var(--text)',
                                    border: '1px solid var(--border)',
                                    borderRadius: '2px',
                                    padding: '4px 8px',
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '.72rem',
                                }}
                            />
                        </label>
                        <button className="btn btn-sm btn-primary" onClick={handleSaveConnection} disabled={configBusy || modelsLoading}>
                            {configBusy ? 'Applying...' : 'Apply'}
                        </button>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)' }}>
                            {llmStatus?.capabilities?.manage_models ? 'provider-managed loading enabled' : 'model selection only'}
                        </span>
                    </div>
                    {modelsLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>
                            <div className="spinner" style={{ width: '12px', height: '12px' }} /> Loading...
                        </div>
                    ) : models.length === 0 ? (
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>No models found</div>
                    ) : models.map(m => {
                        const isLoaded = m.state === 'loaded';
                        const isBusy = modelBusy === m.id;
                        const canManageModels = Boolean(llmStatus?.capabilities?.manage_models);
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
                                    canManageModels ? (
                                        <button className="btn btn-ghost btn-sm" style={{ fontSize: '.65rem', flexShrink: 0 }}
                                            onClick={() => handleUnloadModel(m.id)} disabled={modelBusy !== null}>Unload</button>
                                    ) : (
                                        <button className="btn btn-ghost btn-sm" style={{ fontSize: '.65rem', flexShrink: 0 }}
                                            onClick={() => handleUnloadModel(m.id)} disabled={modelBusy !== null}>Clear</button>
                                    )
                                ) : (
                                    <button className="btn btn-primary btn-sm" style={{ fontSize: '.65rem', flexShrink: 0 }}
                                        onClick={() => handleLoadModel(m.id)} disabled={modelBusy !== null}>{canManageModels ? 'Load' : 'Select'}</button>
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
            </div>
        </div>
    );
}
