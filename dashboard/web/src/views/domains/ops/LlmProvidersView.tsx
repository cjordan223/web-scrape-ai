import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api';

type Provider = {
  id: string;
  label: string;
  base_url: string;
  auth: string | null;
  notes: string;
  has_key: boolean;
  masked_key: string | null;
  active: boolean;
};

type MlxStatus = { running: boolean; pid: number | null; model: string | null; port: number | null };
type OllamaStatus = { enabled: boolean; available: boolean; models: string[]; provider: string; selected_model: string; state: string };
type CachedModel = { id: string };
type TestResult = { ok: boolean; models?: string[]; total?: number; error?: string };
type PullStatus = { pulling: boolean; model_id: string | null; progress: string[]; exit_code: number | null };

const LOCAL_IDS = new Set(['ollama', 'mlx']);

const dot = (color: string) => ({
  width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 as const,
});
const badge = (bg: string, fg: string) => ({
  fontSize: '0.7rem', padding: '2px 8px', borderRadius: 10, background: bg, color: fg, fontWeight: 500 as const,
});
const btn = (bg: string, fg: string, disabled?: boolean) => ({
  background: bg, color: fg, border: 'none', borderRadius: 'var(--radius)',
  padding: '0.4rem 0.8rem', fontSize: '0.8rem', cursor: disabled ? 'not-allowed' as const : 'pointer' as const,
  opacity: disabled ? 0.5 : 1,
});
const card = (highlight: boolean) => ({
  background: 'var(--surface)', border: `1px solid ${highlight ? 'var(--accent)' : 'var(--border)'}`,
  borderRadius: 'var(--radius)', padding: '1rem',
});
const selectStyle = {
  background: 'var(--surface-2)', color: 'var(--text)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '0.4rem 0.6rem', fontSize: '0.85rem', width: '100%', maxWidth: 400,
};

export default function LlmProvidersView() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeProvider, setActiveProvider] = useState('');
  const [loading, setLoading] = useState(true);

  // Local provider state
  const [mlxStatus, setMlxStatus] = useState<MlxStatus>({ running: false, pid: null, model: null, port: null });
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null);
  const [mlxCachedModels, setMlxCachedModels] = useState<CachedModel[]>([]);
  const [mlxSwitching, setMlxSwitching] = useState(false);
  const [ollamaModels, setOllamaModels] = useState<{ id: string; state: string }[]>([]);
  const [ollamaSelectedModel, setOllamaSelectedModel] = useState('default');

  // Cloud provider state
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [activating, setActivating] = useState<Record<string, boolean>>({});

  // Pull state
  const [pullInput, setPullInput] = useState('');
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState<PullStatus | null>(null);

  const switchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // --- Data fetching ---

  const refreshProviders = useCallback(async () => {
    try {
      const data = await api.getLlmProviders();
      setProviders(data.providers);
      setActiveProvider(data.active_provider);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  const refreshLocalStatus = useCallback(async () => {
    try { setMlxStatus(await api.getMlxStatus()); } catch { /* ignore */ }
    try {
      const st = await api.getLlmStatus();
      setOllamaStatus(st);
    } catch { /* ignore */ }
  }, []);

  const refreshMlxModels = useCallback(async () => {
    try {
      const data = await api.getMlxModels();
      setMlxCachedModels(data.models || []);
    } catch { setMlxCachedModels([]); }
  }, []);

  const refreshOllamaModels = useCallback(async () => {
    try {
      const data = await api.getLlmModels();
      setOllamaModels(data.models || []);
      setOllamaSelectedModel(data.selected_model || 'default');
    } catch { setOllamaModels([]); }
  }, []);

  // Initial load
  useEffect(() => {
    refreshProviders();
    refreshLocalStatus();
    refreshMlxModels();
    refreshOllamaModels();
  }, [refreshProviders, refreshLocalStatus, refreshMlxModels, refreshOllamaModels]);

  // Poll local status every 5s
  useEffect(() => {
    const interval = setInterval(refreshLocalStatus, 5000);
    return () => clearInterval(interval);
  }, [refreshLocalStatus]);

  // Poll pull status when active
  useEffect(() => {
    if (!pulling) return;
    const interval = setInterval(async () => {
      try {
        const st = await api.getMlxPullStatus();
        setPullStatus(st);
        if (!st.pulling) {
          setPulling(false);
          refreshMlxModels();
        }
      } catch { /* ignore */ }
    }, 2000);
    return () => clearInterval(interval);
  }, [pulling, refreshMlxModels]);

  // --- Handlers ---

  const handleActivate = async (providerId: string) => {
    setActivating(a => ({ ...a, [providerId]: true }));
    try {
      await api.activateLlmProvider(providerId);
      await refreshProviders();
      if (providerId === 'ollama') await refreshOllamaModels();
    } finally { setActivating(a => ({ ...a, [providerId]: false })); }
  };

  const handleMlxModelSelect = async (model: string) => {
    setMlxSwitching(true);
    try {
      await api.startMlx(model);
      // Poll until server is up (max 60s for large models)
      if (switchPollRef.current) clearInterval(switchPollRef.current);
      const pollId = setInterval(async () => {
        try {
          const st = await api.getMlxStatus();
          setMlxStatus(st);
          if (st.running) { setMlxSwitching(false); clearInterval(pollId); }
        } catch { /* ignore */ }
      }, 1500);
      switchPollRef.current = pollId;
      setTimeout(() => { clearInterval(pollId); setMlxSwitching(false); }, 60000);
    } catch { setMlxSwitching(false); }
  };

  const handleMlxStop = async () => {
    await api.stopMlx();
    setMlxStatus({ running: false, pid: null, model: null, port: null });
  };

  const handleOllamaModelSelect = async (identifier: string) => {
    try {
      await api.selectLlmModel(identifier);
      await refreshOllamaModels();
    } catch { /* ignore */ }
  };

  const handlePull = async () => {
    const id = pullInput.trim();
    if (!id) return;
    const result = await api.pullMlxModel(id);
    if (result.ok) {
      setPulling(true);
      setPullInput('');
    }
  };

  const handleSaveKey = async (providerId: string) => {
    const key = keyInputs[providerId] ?? '';
    setSaving(s => ({ ...s, [providerId]: true }));
    try {
      await api.setLlmProviderKey(providerId, key);
      setKeyInputs(k => ({ ...k, [providerId]: '' }));
      await refreshProviders();
    } finally { setSaving(s => ({ ...s, [providerId]: false })); }
  };

  const handleClearKey = async (providerId: string) => {
    setSaving(s => ({ ...s, [providerId]: true }));
    try {
      await api.setLlmProviderKey(providerId, '');
      await refreshProviders();
    } finally { setSaving(s => ({ ...s, [providerId]: false })); }
  };

  const handleTest = async (providerId: string) => {
    setTesting(t => ({ ...t, [providerId]: true }));
    setTestResults(r => ({ ...r, [providerId]: undefined as any }));
    try {
      const result = await api.testLlmProvider(providerId);
      setTestResults(r => ({ ...r, [providerId]: result }));
    } catch (e: any) {
      const msg = e?.response?.data?.error || e?.message || 'Connection failed';
      setTestResults(r => ({ ...r, [providerId]: { ok: false, error: msg } }));
    } finally { setTesting(t => ({ ...t, [providerId]: false })); }
  };

  // --- Render helpers ---

  if (loading) return <div className="view-container"><div className="loading"><div className="spinner" /></div></div>;

  const active = providers.find(p => p.id === activeProvider);
  const localProviders = providers.filter(p => LOCAL_IDS.has(p.id));
  const cloudProviders = providers.filter(p => !LOCAL_IDS.has(p.id));

  const ollamaOnline = ollamaStatus?.state === 'online';
  const activeModelLabel = activeProvider === 'mlx'
    ? (mlxStatus.model || 'none')
    : activeProvider === 'ollama'
      ? (ollamaSelectedModel !== 'default' ? ollamaSelectedModel : ollamaModels[0]?.id || 'none')
      : '';

  return (
    <div className="view-container" style={{ padding: '1.5rem', maxWidth: 900 }}>
      {/* Active provider banner */}
      {active && (
        <div style={{
          background: 'var(--surface-2)', border: '1px solid var(--green)',
          borderRadius: 'var(--radius)', padding: '0.75rem 1rem', marginBottom: '1.5rem',
          display: 'flex', alignItems: 'center', gap: '0.75rem',
        }}>
          <span style={dot('var(--green)')} />
          <span style={{ fontWeight: 500 }}>Active: {active.label}</span>
          {activeModelLabel && activeModelLabel !== 'none' && (
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              model: {activeModelLabel}
            </span>
          )}
        </div>
      )}

      {/* Local Providers */}
      <h3 style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 0.75rem' }}>
        Local Providers
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '2rem' }}>
        {localProviders.map(p => {
          const isActive = p.id === activeProvider;
          const isOllama = p.id === 'ollama';
          const isMlx = p.id === 'mlx';
          const online = isOllama ? ollamaOnline : mlxStatus.running;
          const statusColor = online ? 'var(--green)' : 'var(--red)';
          const currentModel = isOllama
            ? (ollamaSelectedModel !== 'default' ? ollamaSelectedModel : ollamaModels[0]?.id)
            : mlxStatus.model;

          return (
            <div key={p.id} style={card(isActive)}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                <span style={dot(statusColor)} />
                <span style={{ fontWeight: 600, fontSize: '1rem' }}>{p.label}</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  {online ? 'Online' : 'Offline'}
                </span>
                {isActive && <span style={badge('rgba(60,179,113,0.15)', 'var(--green)')}>ACTIVE</span>}
                {isMlx && mlxSwitching && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--accent)' }}>Loading model...</span>
                )}
              </div>

              {/* Current model */}
              {online && currentModel && (
                <div style={{ fontSize: '0.85rem', color: 'var(--text)', marginBottom: '0.75rem' }}>
                  Model: <strong>{currentModel}</strong>
                </div>
              )}

              {/* Model selector */}
              <div style={{ marginBottom: '0.75rem' }}>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                  {isMlx ? 'Cached Models' : 'Available Models'}
                </label>
                {isMlx ? (
                  <select
                    value={mlxStatus.model || ''}
                    onChange={e => e.target.value && handleMlxModelSelect(e.target.value)}
                    disabled={mlxSwitching}
                    style={{ ...selectStyle, opacity: mlxSwitching ? 0.5 : 1 }}
                  >
                    <option value="">Select a model...</option>
                    {mlxCachedModels.map(m => (
                      <option key={m.id} value={m.id}>{m.id}</option>
                    ))}
                  </select>
                ) : (
                  <select
                    value={ollamaSelectedModel}
                    onChange={e => handleOllamaModelSelect(e.target.value)}
                    style={selectStyle}
                  >
                    {ollamaModels.length === 0 && <option value="">No models available</option>}
                    {ollamaModels.map(m => (
                      <option key={m.id} value={m.id}>{m.id}</option>
                    ))}
                  </select>
                )}
              </div>

              {/* MLX pull model */}
              {isMlx && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                    Pull New Model
                  </label>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <input
                      type="text"
                      placeholder="mlx-community/model-name"
                      value={pullInput}
                      onChange={e => setPullInput(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handlePull()}
                      disabled={pulling}
                      style={{
                        ...selectStyle, flex: 1, maxWidth: 'none',
                        opacity: pulling ? 0.5 : 1,
                      }}
                    />
                    <button onClick={handlePull} disabled={pulling || !pullInput.trim()} style={btn('var(--accent)', '#fff', pulling || !pullInput.trim())}>
                      {pulling ? 'Pulling...' : 'Pull'}
                    </button>
                  </div>
                  {pullStatus && (pullStatus.pulling || pullStatus.progress.length > 0) && (
                    <div style={{
                      marginTop: '0.5rem', padding: '0.5rem', background: 'var(--surface-2)',
                      borderRadius: 'var(--radius)', fontSize: '0.7rem', fontFamily: 'monospace',
                      maxHeight: 120, overflowY: 'auto', color: 'var(--text-secondary)',
                    }}>
                      {pullStatus.progress.map((line, i) => <div key={i}>{line}</div>)}
                      {pullStatus.exit_code !== null && pullStatus.exit_code !== undefined && (
                        <div style={{ color: pullStatus.exit_code === 0 ? 'var(--green)' : 'var(--red)', marginTop: 4 }}>
                          {pullStatus.exit_code === 0 ? 'Download complete' : `Failed (exit code ${pullStatus.exit_code})`}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {isMlx && mlxStatus.running && (
                  <button onClick={handleMlxStop} style={btn('var(--red)', '#fff')}>
                    Stop Server
                  </button>
                )}
                <button onClick={() => handleTest(p.id)} disabled={testing[p.id]} style={btn('var(--surface-2)', 'var(--text)', testing[p.id])}>
                  {testing[p.id] ? 'Testing...' : 'Test Connection'}
                </button>
                {!isActive && (
                  <button onClick={() => handleActivate(p.id)} disabled={activating[p.id]} style={btn('var(--green)', '#fff', activating[p.id])}>
                    {activating[p.id] ? 'Activating...' : 'Activate'}
                  </button>
                )}
              </div>

              {/* Test result */}
              {testResults[p.id] && (
                <div style={{
                  marginTop: '0.5rem', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)', fontSize: '0.8rem',
                  background: testResults[p.id].ok ? 'rgba(60,179,113,0.08)' : 'rgba(217,79,79,0.08)',
                  border: `1px solid ${testResults[p.id].ok ? 'var(--green)' : 'var(--red)'}`,
                  color: testResults[p.id].ok ? 'var(--green)' : 'var(--red)',
                }}>
                  {testResults[p.id].ok
                    ? `Connected - ${testResults[p.id].total} model${testResults[p.id].total === 1 ? '' : 's'} available`
                    : `Failed: ${testResults[p.id].error}`}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Cloud Providers */}
      <h3 style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 0.75rem' }}>
        Cloud Providers
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {cloudProviders.map(p => {
          const isActive = p.id === activeProvider;
          const needsKey = p.auth === 'bearer';
          const canActivate = !needsKey || p.has_key;
          const result = testResults[p.id];

          return (
            <div key={p.id} style={card(isActive)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                <span style={{ fontWeight: 600, fontSize: '1rem' }}>{p.label}</span>
                {isActive && <span style={badge('rgba(60,179,113,0.15)', 'var(--green)')}>ACTIVE</span>}
                {!isActive && p.has_key && <span style={badge('rgba(75,142,240,0.12)', 'var(--accent)')}>CONFIGURED</span>}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginBottom: '0.75rem' }}>{p.notes}</div>

              {needsKey && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <input
                      type="password"
                      placeholder={p.masked_key || 'Paste API key'}
                      value={keyInputs[p.id] ?? ''}
                      onChange={e => setKeyInputs(k => ({ ...k, [p.id]: e.target.value }))}
                      style={{ ...selectStyle, flex: 1, minWidth: 200, maxWidth: 'none' }}
                    />
                    <button
                      onClick={() => handleSaveKey(p.id)}
                      disabled={saving[p.id] || !(keyInputs[p.id] ?? '').trim()}
                      style={btn('var(--accent)', '#fff', saving[p.id] || !(keyInputs[p.id] ?? '').trim())}
                    >
                      {saving[p.id] ? 'Saving...' : 'Save Key'}
                    </button>
                    {p.has_key && (
                      <button onClick={() => handleClearKey(p.id)} disabled={saving[p.id]}
                        style={{ ...btn('transparent', 'var(--red)', saving[p.id]), border: '1px solid var(--red)' }}>
                        Clear
                      </button>
                    )}
                  </div>
                  {p.masked_key && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: 4 }}>Stored: {p.masked_key}</div>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                <button onClick={() => handleTest(p.id)} disabled={testing[p.id]} style={btn('var(--surface-2)', 'var(--text)', testing[p.id])}>
                  {testing[p.id] ? 'Testing...' : 'Test Connection'}
                </button>
                {!isActive && (
                  <button
                    onClick={() => handleActivate(p.id)}
                    disabled={activating[p.id] || !canActivate}
                    title={!canActivate ? 'Add an API key first' : undefined}
                    style={btn(canActivate ? 'var(--green)' : 'var(--surface-3)', canActivate ? '#fff' : 'var(--text-secondary)', activating[p.id] || !canActivate)}
                  >
                    {activating[p.id] ? 'Activating...' : 'Activate'}
                  </button>
                )}
              </div>

              {result && (
                <div style={{
                  marginTop: '0.5rem', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)', fontSize: '0.8rem',
                  background: result.ok ? 'rgba(60,179,113,0.08)' : 'rgba(217,79,79,0.08)',
                  border: `1px solid ${result.ok ? 'var(--green)' : 'var(--red)'}`,
                  color: result.ok ? 'var(--green)' : 'var(--red)',
                }}>
                  {result.ok
                    ? `Connected - ${result.total} model${result.total === 1 ? '' : 's'} available`
                    : `Failed: ${result.error}`}
                  {result.ok && result.models && result.models.length > 0 && (
                    <div style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: '0.75rem' }}>
                      {result.models.slice(0, 5).join(', ')}
                      {(result.total ?? 0) > 5 && ` +${(result.total ?? 0) - 5} more`}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
