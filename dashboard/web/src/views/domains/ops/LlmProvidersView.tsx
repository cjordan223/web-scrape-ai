import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api';
import { CollapsibleSection } from '../../../components/CollapsibleSection';
import { fmtBytes, fmtDate } from '../../../utils';

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
type ActivityEvent = { id: number; level: 'info' | 'success' | 'error'; message: string; ts: string };
type StepState = 'pending' | 'active' | 'done' | 'error';
type StepItem = { key: string; label: string; state: StepState };
type SwitchState = { title: string; detail: string; provider?: string; model?: string; tone?: 'info' | 'success' | 'error'; steps?: StepItem[] } | null;

type MachineProfile = { chip: string | null; cpu_cores: number | null; gpu_cores: number | null; memory_gb: number | null; os_version: string | null };
type ModelFit = { rating: 'excellent' | 'good' | 'caution' | 'heavy' | 'unknown'; detail: string };
type CatalogModel = {
  id: string; provider: string; family: string; parameter_size: string; parameter_count_b: number | null;
  quantization: string; context_length: number | null; size_bytes: number;
  capabilities: string[]; use_case: string; fit: ModelFit; modified_at: string | null;
};
type BenchmarkResult = {
  ok: boolean; model: string; wall_time_s?: number; time_to_first_token_ms?: number;
  generation_tokens_per_sec?: number; prompt_eval_tokens_per_sec?: number;
  eval_tokens?: number; prompt_tokens?: number; response_preview?: string;
  cached?: boolean; error?: string;
};

const LOCAL_IDS = new Set(['ollama', 'mlx']);

const dot = (color: string, glow = false) => ({
  width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 as const,
  boxShadow: glow ? `0 0 10px ${color}` : undefined,
});
const badge = (bg: string, fg: string) => ({
  fontSize: '0.7rem', padding: '2px 8px', borderRadius: 10, background: bg, color: fg, fontWeight: 500 as const,
});
const btn = (bg: string, fg: string, disabled?: boolean, isGhost = false) => ({
  background: isGhost ? 'transparent' : bg, color: fg, 
  border: isGhost ? `1px solid ${bg}` : '1px solid transparent', 
  borderRadius: 'var(--radius)',
  padding: '0.45rem 0.9rem', fontSize: '0.8rem', cursor: disabled ? 'not-allowed' as const : 'pointer' as const,
  opacity: disabled ? 0.5 : 1,
  transition: 'all 0.2s ease',
});
const card = (highlight: boolean) => ({
  background: 'var(--surface)', 
  border: `1px solid ${highlight ? 'var(--accent)' : 'var(--surface-2)'}`,
  boxShadow: highlight ? '0 4px 14px rgba(75, 142, 240, 0.1)' : '0 2px 8px rgba(0,0,0,0.15)',
  borderRadius: '10px', padding: '1.25rem',
  transition: 'all 0.2s ease',
});
const selectStyle = {
  background: 'var(--surface-3)', color: 'var(--text)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '0.5rem 0.75rem', fontSize: '0.85rem', width: '100%', maxWidth: 400,
  transition: 'border-color 0.2s ease, background 0.2s ease', outline: 'none',
};
const consoleShell = {
  background: '#0b1118',
  border: '1px solid rgba(75,142,240,0.18)',
  borderRadius: 'var(--radius)',
  padding: '0.85rem 1rem',
  fontFamily: 'var(--font-mono)',
  fontSize: '0.76rem',
  lineHeight: 1.55,
  color: '#c7d2e0',
  maxHeight: 260,
  overflowY: 'auto' as const,
};
const stepperRow = {
  display: 'flex',
  alignItems: 'center',
  gap: '0.55rem',
  flexWrap: 'wrap' as const,
  marginTop: '0.7rem',
};

function buildSteps(activeKey: string, labels: Array<[string, string]>, tone: 'info' | 'success' | 'error' = 'info'): StepItem[] {
  const activeIndex = Math.max(0, labels.findIndex(([key]) => key === activeKey));
  return labels.map(([key, label], index) => {
    let state: StepState = 'pending';
    if (tone === 'success') state = 'done';
    else if (tone === 'error' && index === activeIndex) state = 'error';
    else if (index < activeIndex) state = 'done';
    else if (index === activeIndex) state = 'active';
    return { key, label, state };
  });
}

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
  const [switchState, setSwitchState] = useState<SwitchState>(null);
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);

  // Pull state
  const [pullInput, setPullInput] = useState('');
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState<PullStatus | null>(null);

  // Infrastructure state
  const [infra, setInfra] = useState<{ services: any[] } | null>(null);

  // Catalog state
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([]);
  const [machineProfile, setMachineProfile] = useState<MachineProfile | null>(null);
  const [catalogSelected, setCatalogSelected] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const [benchmarks, setBenchmarks] = useState<Record<string, BenchmarkResult>>({});
  const [benchmarking, setBenchmarking] = useState<Record<string, boolean>>({});
  const [expandedModel, setExpandedModel] = useState<string | null>(null);

  // Chat state
  type ChatMsg = { role: string; content: string };
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'local' | 'cloud' | 'catalog'>('local');
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const switchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pullCompleteRef = useRef<string | null>(null);

  const pushEvent = useCallback((level: ActivityEvent['level'], message: string) => {
    setActivityEvents(prev => [
      { id: Date.now() + Math.floor(Math.random() * 1000), level, message, ts: new Date().toISOString() },
      ...prev,
    ].slice(0, 40));
  }, []);

  const describeProvider = useCallback((providerId: string) => {
    return providers.find(p => p.id === providerId)?.label || providerId;
  }, [providers]);

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
      const data = await api.getLlmModels('ollama');
      const models = data.models || [];
      setOllamaModels(models);
      const selected = data.selected_model || 'default';
      const hasSelected = selected === 'default' || models.some((m: { id: string }) => m.id === selected);
      setOllamaSelectedModel(hasSelected ? selected : 'default');
    } catch { setOllamaModels([]); }
  }, []);

  const refreshInfra = useCallback(async () => {
    try { setInfra(await api.getLlmInfrastructure()); } catch { /* ignore */ }
  }, []);

  const refreshCatalog = useCallback(async () => {
    setCatalogLoading(true);
    setCatalogError('');
    try {
      const data = await api.getLlmCatalog();
      setCatalogModels(data.models || []);
      setMachineProfile(data.machine || null);
      setCatalogSelected(data.selected_model || '');
      if (data.error) setCatalogError(data.error);
    } catch (e: any) {
      setCatalogError(e?.message || 'Failed to load catalog');
    } finally { setCatalogLoading(false); }
  }, []);

  const handleBenchmark = useCallback(async (modelId: string, provider = 'ollama') => {
    setBenchmarking(prev => ({ ...prev, [modelId]: true }));
    try {
      const result = await api.runLlmBenchmark(modelId, provider);
      setBenchmarks(prev => ({ ...prev, [modelId]: result }));
    } catch (e: any) {
      setBenchmarks(prev => ({ ...prev, [modelId]: { ok: false, model: modelId, error: e?.message || 'Benchmark failed' } }));
    } finally {
      setBenchmarking(prev => ({ ...prev, [modelId]: false }));
    }
  }, []);

  // Initial load
  useEffect(() => {
    refreshProviders();
    refreshLocalStatus();
    refreshMlxModels();
    refreshOllamaModels();
    refreshInfra();
    refreshCatalog();
  }, [refreshProviders, refreshLocalStatus, refreshMlxModels, refreshOllamaModels, refreshInfra, refreshCatalog]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!text || chatLoading) return;
    const userMsg: ChatMsg = { role: 'user', content: text };
    const msgs = [...chatMessages, userMsg];
    setChatMessages(msgs);
    setChatInput('');
    setChatLoading(true);
    try {
      const res = await api.llmChat(msgs);
      if (res.ok) {
        setChatMessages(prev => [...prev, { role: 'assistant', content: res.reply }]);
      } else {
        setChatMessages(prev => [...prev, { role: 'assistant', content: `Error: ${res.error}` }]);
      }
    } catch (e: any) {
      setChatMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e?.message || 'Request failed'}` }]);
    } finally { setChatLoading(false); }
  };

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
          const token = `${st.model_id || 'unknown'}:${st.exit_code}`;
          if (pullCompleteRef.current !== token) {
            pullCompleteRef.current = token;
            pushEvent(st.exit_code === 0 ? 'success' : 'error', st.exit_code === 0
              ? `Finished pulling MLX model ${st.model_id || ''}`.trim()
              : `MLX model pull failed for ${st.model_id || 'unknown'} (exit ${st.exit_code ?? 'unknown'})`);
          }
        }
      } catch {
        pushEvent('error', 'Unable to refresh MLX pull status');
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [pulling, pushEvent, refreshMlxModels]);

  // --- Handlers ---

  const handleActivate = async (providerId: string) => {
    setActivating(a => ({ ...a, [providerId]: true }));
    setSwitchState({
      title: `Switching to ${describeProvider(providerId)}`,
      detail: 'Updating runtime controls and refreshing provider state.',
      provider: providerId,
      tone: 'info',
      steps: buildSteps('save', [
        ['save', 'Save Provider'],
        ['verify', 'Refresh State'],
        ['ready', 'Ready'],
      ]),
    });
    pushEvent('info', `Switch requested: ${describeProvider(activeProvider || 'current')} -> ${describeProvider(providerId)}`);
    try {
      const model = providerId === 'mlx' ? (mlxStatus.model || undefined)
        : providerId === 'ollama' ? (ollamaSelectedModel || undefined)
        : undefined;
      await api.activateLlmProvider(providerId, undefined, model);
      await refreshProviders();
      await refreshLocalStatus();
      if (providerId === 'ollama') await refreshOllamaModels();
      if (providerId === 'mlx') await refreshMlxModels();
      setSwitchState({
        title: `${describeProvider(providerId)} is active`,
        detail: providerId === 'mlx'
          ? 'New requests will use the running MLX server and selected model.'
          : providerId === 'ollama'
            ? 'New requests will use Ollama and the selected on-demand model.'
            : 'New requests will use this provider.',
        provider: providerId,
        model: model,
        tone: 'success',
        steps: buildSteps('ready', [
          ['save', 'Save Provider'],
          ['verify', 'Refresh State'],
          ['ready', 'Ready'],
        ], 'success'),
      });
      pushEvent('success', `Activated ${describeProvider(providerId)}${model ? ` with ${model}` : ''}`);
    } catch (e: any) {
      const msg = e?.response?.data?.error || e?.message || 'Provider activation failed';
      setSwitchState({
        title: `Switch to ${describeProvider(providerId)} failed`,
        detail: msg,
        provider: providerId,
        tone: 'error',
        steps: buildSteps('verify', [
          ['save', 'Save Provider'],
          ['verify', 'Refresh State'],
          ['ready', 'Ready'],
        ], 'error'),
      });
      pushEvent('error', `Activation failed for ${describeProvider(providerId)}: ${msg}`);
    } finally {
      window.setTimeout(() => setSwitchState(current => current?.tone === 'info' ? null : current), 2500);
      window.setTimeout(() => setSwitchState(null), 6000);
      setActivating(a => ({ ...a, [providerId]: false }));
    }
  };

  const handleMlxModelSelect = async (model: string) => {
    setMlxSwitching(true);
    setSwitchState({
      title: 'Starting MLX model',
      detail: `Launching ${model} and waiting for the local server to respond on port 8080.`,
      provider: 'mlx',
      model,
      tone: 'info',
      steps: buildSteps('start', [
        ['save', 'Save Selection'],
        ['start', 'Start Server'],
        ['verify', 'Verify Health'],
        ['ready', 'Ready'],
      ]),
    });
    pushEvent('info', `Starting MLX model ${model}`);
    try {
      const res = await api.startMlx(model);
      if (res && !res.ok) {
        setTestResults(prev => ({ ...prev, mlx: { ok: false, error: res.error || 'Failed to start MLX', total: 0 } }));
        setSwitchState({
          title: 'MLX model start failed',
          detail: res.error || 'Failed to start MLX',
          provider: 'mlx',
          model,
          tone: 'error',
          steps: buildSteps('start', [
            ['save', 'Save Selection'],
            ['start', 'Start Server'],
            ['verify', 'Verify Health'],
            ['ready', 'Ready'],
          ], 'error'),
        });
        pushEvent('error', `MLX start failed for ${model}: ${res.error || 'unknown error'}`);
        setMlxSwitching(false);
        return;
      }
      // Poll until server is up (max 60s for large models)
      if (switchPollRef.current) clearInterval(switchPollRef.current);
      const pollId = setInterval(async () => {
        try {
          const st = await api.getMlxStatus();
          setMlxStatus(st);
          if (st.running) {
            setMlxSwitching(false);
            clearInterval(pollId);
            // Persist model selection to runtime controls
            if (st.model) await api.selectLlmModel(st.model);
            await refreshProviders();
            await refreshLocalStatus();
            setSwitchState({
              title: 'MLX ready',
              detail: `${st.model || model} is live. New requests will use the MLX server.`,
              provider: 'mlx',
              model: st.model || model,
              tone: 'success',
              steps: buildSteps('ready', [
                ['save', 'Save Selection'],
                ['start', 'Start Server'],
                ['verify', 'Verify Health'],
                ['ready', 'Ready'],
              ], 'success'),
            });
            pushEvent('success', `MLX server is ready with ${st.model || model}`);
          }
        } catch {
          pushEvent('error', 'Unable to poll MLX server status during model switch');
        }
      }, 1500);
      switchPollRef.current = pollId;
      setTimeout(() => {
        clearInterval(pollId);
        setMlxSwitching(false);
        setSwitchState(current => current?.tone === 'info'
          ? {
              title: 'MLX switch timed out',
              detail: `The UI stopped waiting for ${model}. Check the console below for pull or startup errors.`,
              provider: 'mlx',
              model,
              tone: 'error',
              steps: buildSteps('verify', [
                ['save', 'Save Selection'],
                ['start', 'Start Server'],
                ['verify', 'Verify Health'],
                ['ready', 'Ready'],
              ], 'error'),
            }
          : current);
        pushEvent('error', `Timed out waiting for MLX model ${model} to become ready`);
      }, 60000);
    } catch (err: any) {
      const msg = err?.response?.data?.error || err?.message || 'Failed to start MLX';
      setTestResults(prev => ({ ...prev, mlx: { ok: false, error: msg, total: 0 } }));
      setSwitchState({
        title: 'MLX model start failed',
        detail: msg,
        provider: 'mlx',
        model,
        tone: 'error',
        steps: buildSteps('start', [
          ['save', 'Save Selection'],
          ['start', 'Start Server'],
          ['verify', 'Verify Health'],
          ['ready', 'Ready'],
        ], 'error'),
      });
      pushEvent('error', `MLX start failed for ${model}: ${msg}`);
      setMlxSwitching(false);
    }
  };

  const handleMlxStop = async () => {
    pushEvent('info', 'Stop requested for MLX server');
    try {
      await api.stopMlx();
      setMlxStatus({ running: false, pid: null, model: null, port: null });
      setSwitchState({
        title: 'MLX server stopped',
        detail: activeProvider === 'mlx'
          ? 'MLX is still the active provider, so the dashboard may auto-recover it.'
          : 'MLX is offline until started again.',
        provider: 'mlx',
        tone: 'success',
        steps: buildSteps('ready', [
          ['stop', 'Send Stop'],
          ['verify', 'Refresh State'],
          ['ready', 'Stopped'],
        ], 'success'),
      });
      pushEvent('success', activeProvider === 'mlx'
        ? 'Stopped MLX server. Auto-recovery may bring it back because MLX is still active.'
        : 'Stopped MLX server');
    } catch (e: any) {
      const msg = e?.response?.data?.error || e?.message || 'Failed to stop MLX';
      setSwitchState({
        title: 'MLX stop failed',
        detail: msg,
        provider: 'mlx',
        tone: 'error',
        steps: buildSteps('verify', [
          ['stop', 'Send Stop'],
          ['verify', 'Refresh State'],
          ['ready', 'Stopped'],
        ], 'error'),
      });
      pushEvent('error', `MLX stop failed: ${msg}`);
    }
  };

  const handleOllamaModelSelect = async (identifier: string) => {
    try {
      setSwitchState({
        title: 'Updating Ollama model',
        detail: identifier
          ? `Saving ${identifier} as the model to use for future Ollama requests.`
          : 'Clearing explicit Ollama model selection.',
        provider: 'ollama',
        model: identifier || undefined,
        tone: 'info',
        steps: buildSteps('save', [
          ['save', 'Save Selection'],
          ['verify', 'Refresh State'],
          ['ready', 'Ready'],
        ]),
      });
      pushEvent('info', identifier ? `Selecting Ollama model ${identifier}` : 'Clearing Ollama model selection');
      await api.selectLlmModel(identifier);
      await refreshOllamaModels();
      setSwitchState({
        title: 'Ollama model updated',
        detail: identifier
          ? `${identifier} will be used the next time Ollama is active.`
          : 'Ollama will fall back to its default model resolution.',
        provider: 'ollama',
        model: identifier || undefined,
        tone: 'success',
        steps: buildSteps('ready', [
          ['save', 'Save Selection'],
          ['verify', 'Refresh State'],
          ['ready', 'Ready'],
        ], 'success'),
      });
      pushEvent('success', identifier ? `Saved Ollama model ${identifier}` : 'Cleared Ollama model override');
    } catch (e: any) {
      const msg = e?.response?.data?.error || e?.message || 'Failed to save Ollama model';
      setSwitchState({
        title: 'Ollama model update failed',
        detail: msg,
        provider: 'ollama',
        model: identifier || undefined,
        tone: 'error',
        steps: buildSteps('verify', [
          ['save', 'Save Selection'],
          ['verify', 'Refresh State'],
          ['ready', 'Ready'],
        ], 'error'),
      });
      pushEvent('error', `Failed to save Ollama model ${identifier || '(default)'}: ${msg}`);
    }
  };

  const handlePull = async () => {
    const id = pullInput.trim();
    if (!id) return;
    pushEvent('info', `Pulling MLX model ${id}`);
    const result = await api.pullMlxModel(id);
    if (result.ok) {
      setPulling(true);
      setPullInput('');
      pullCompleteRef.current = null;
      setSwitchState({
        title: 'Downloading MLX model',
        detail: `${id} is downloading in the background. You can watch progress in the console below.`,
        provider: 'mlx',
        model: id,
        tone: 'info',
        steps: buildSteps('start', [
          ['queue', 'Queue Download'],
          ['start', 'Transfer Files'],
          ['verify', 'Update Cache'],
          ['ready', 'Ready'],
        ]),
      });
    } else {
      pushEvent('error', `Failed to start MLX pull for ${id}: ${result.error || 'unknown error'}`);
      setSwitchState({
        title: 'MLX download failed to start',
        detail: result.error || 'Unknown error',
        provider: 'mlx',
        model: id,
        tone: 'error',
        steps: buildSteps('queue', [
          ['queue', 'Queue Download'],
          ['start', 'Transfer Files'],
          ['verify', 'Update Cache'],
          ['ready', 'Ready'],
        ], 'error'),
      });
    }
  };

  const handleSaveKey = async (providerId: string) => {
    const key = keyInputs[providerId] ?? '';
    setSaving(s => ({ ...s, [providerId]: true }));
    try {
      await api.setLlmProviderKey(providerId, key);
      setKeyInputs(k => ({ ...k, [providerId]: '' }));
      await refreshProviders();
      pushEvent('success', `Saved API key for ${describeProvider(providerId)}`);
    } finally { setSaving(s => ({ ...s, [providerId]: false })); }
  };

  const handleClearKey = async (providerId: string) => {
    setSaving(s => ({ ...s, [providerId]: true }));
    try {
      await api.setLlmProviderKey(providerId, '');
      await refreshProviders();
      pushEvent('success', `Cleared API key for ${describeProvider(providerId)}`);
    } finally { setSaving(s => ({ ...s, [providerId]: false })); }
  };

  const handleTest = async (providerId: string) => {
    setTesting(t => ({ ...t, [providerId]: true }));
    setTestResults(r => ({ ...r, [providerId]: undefined as any }));

    const maxRetries = LOCAL_IDS.has(providerId) ? 8 : 1;
    const retryDelay = 2000;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        const result = await api.testLlmProvider(providerId);
        if (result.ok) {
          setTestResults(r => ({ ...r, [providerId]: result }));
          pushEvent('success', `${describeProvider(providerId)} connection test succeeded`);
          setTesting(t => ({ ...t, [providerId]: false }));
          return;
        }
        // Non-ok but no exception — show if last attempt
        if (attempt === maxRetries) {
          setTestResults(r => ({ ...r, [providerId]: result }));
          pushEvent('error', `${describeProvider(providerId)} connection test failed: ${result.error || 'unknown error'}`);
        } else {
          setTestResults(r => ({ ...r, [providerId]: { ok: false, error: `Waiting for server to become ready (attempt ${attempt}/${maxRetries})...` } }));
        }
      } catch (e: any) {
        if (attempt === maxRetries) {
          const msg = e?.response?.data?.error || e?.message || 'Connection failed';
          setTestResults(r => ({ ...r, [providerId]: { ok: false, error: msg } }));
          pushEvent('error', `${describeProvider(providerId)} connection test failed: ${msg}`);
        } else {
          setTestResults(r => ({ ...r, [providerId]: { ok: false, error: `Waiting for server to become ready (attempt ${attempt}/${maxRetries})...` } }));
        }
      }
      if (attempt < maxRetries) await new Promise(res => setTimeout(res, retryDelay));
    }
    setTesting(t => ({ ...t, [providerId]: false }));
  };

  // --- Render helpers ---

  if (loading) return <div className="view-container"><div className="loading"><div className="spinner" /></div></div>;

  const active = providers.find(p => p.id === activeProvider);
  const localProviders = providers.filter(p => LOCAL_IDS.has(p.id));
  const cloudProviders = providers.filter(p => !LOCAL_IDS.has(p.id));

  const ollamaOnline = ollamaStatus?.state === 'online';
  const activeModelLabel = activeProvider === 'mlx'
    ? (mlxStatus.model || 'none')
    : ollamaSelectedModel || 'not configured';
  const switchTone = switchState?.tone === 'error'
    ? { bg: 'rgba(217,79,79,0.08)', border: 'var(--red)', dot: 'var(--red)' }
    : switchState?.tone === 'success'
      ? { bg: 'rgba(60,179,113,0.08)', border: 'var(--green)', dot: 'var(--green)' }
      : { bg: 'rgba(75,142,240,0.08)', border: 'var(--accent)', dot: 'var(--accent)' };

  return (
    <div className="view-container" style={{ padding: '1.5rem', maxWidth: 1400, margin: '0 auto' }}>
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

      {switchState && (
        <div style={{
          background: switchTone.bg,
          border: `1px solid ${switchTone.border}`,
          borderRadius: 'var(--radius)',
          padding: '0.85rem 1rem',
          marginBottom: '1rem',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.35rem' }}>
            <span style={dot(switchTone.dot)} />
            <span style={{ fontWeight: 600 }}>{switchState.title}</span>
            {switchState.provider && (
              <span style={{ ...badge('rgba(255,255,255,0.06)', 'var(--text-secondary)') }}>
                {switchState.provider}
              </span>
            )}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.5 }}>
            {switchState.detail}
          </div>
          {switchState.model && (
            <div style={{ marginTop: '0.35rem', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
              Target model: <span style={{ color: 'var(--text)' }}>{switchState.model}</span>
            </div>
          )}
          {switchState.steps && switchState.steps.length > 0 && (
            <div style={stepperRow}>
              {switchState.steps.map((step, index) => {
                const palette = step.state === 'done'
                  ? { bg: 'rgba(60,179,113,0.16)', fg: 'var(--green)', border: 'rgba(60,179,113,0.35)', dot: 'var(--green)' }
                  : step.state === 'active'
                    ? { bg: 'rgba(75,142,240,0.16)', fg: 'var(--accent)', border: 'rgba(75,142,240,0.35)', dot: 'var(--accent)' }
                    : step.state === 'error'
                      ? { bg: 'rgba(217,79,79,0.16)', fg: 'var(--red)', border: 'rgba(217,79,79,0.35)', dot: 'var(--red)' }
                      : { bg: 'rgba(255,255,255,0.04)', fg: 'var(--text-secondary)', border: 'rgba(255,255,255,0.08)', dot: 'rgba(255,255,255,0.18)' };
                return (
                  <div key={step.key} style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: '0.45rem',
                      padding: '0.32rem 0.6rem', borderRadius: 999,
                      background: palette.bg, border: `1px solid ${palette.border}`,
                    }}>
                      <span style={dot(palette.dot)} />
                      <span style={{ fontSize: '0.76rem', color: palette.fg, fontWeight: 500 }}>{step.label}</span>
                    </div>
                    {index < switchState.steps!.length - 1 && (
                      <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>→</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
        <button
          onClick={() => setActiveTab('local')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'local' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'local' ? 'var(--text)' : 'var(--text-secondary)',
            padding: '0.5rem 1rem',
            fontSize: '0.9rem',
            cursor: 'pointer',
            fontWeight: activeTab === 'local' ? 500 : 400,
          }}
        >
          Local Setup
        </button>
        <button
          onClick={() => setActiveTab('cloud')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'cloud' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'cloud' ? 'var(--text)' : 'var(--text-secondary)',
            padding: '0.5rem 1rem',
            fontSize: '0.9rem',
            cursor: 'pointer',
            fontWeight: activeTab === 'cloud' ? 500 : 400,
          }}
        >
          Cloud Setup
        </button>
        <button
          onClick={() => setActiveTab('catalog')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'catalog' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'catalog' ? 'var(--text)' : 'var(--text-secondary)',
            padding: '0.5rem 1rem',
            fontSize: '0.9rem',
            cursor: 'pointer',
            fontWeight: activeTab === 'catalog' ? 500 : 400,
          }}
        >
          Model Catalog
        </button>
      </div>

      {activeTab === 'local' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(480px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                <span style={dot(statusColor, online)} />
                <span style={{ fontWeight: 600, fontSize: '1.05rem', letterSpacing: '-0.01em' }}>{p.label}</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  {online ? 'Online' : 'Offline'}
                </span>
                {isActive && <span style={badge('rgba(60,179,113,0.15)', 'var(--green)')}>ACTIVE</span>}
                {isMlx && mlxSwitching && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--accent)', animation: 'pulse 1.5s infinite' }}>Loading model...</span>
                )}
              </div>

              {/* Inset Configuration Well */}
              <div style={{
                background: 'var(--surface-2)',
                padding: '1.25rem',
                borderRadius: '8px',
                marginBottom: '1.25rem',
                border: '1px solid var(--border)'
              }}>
                {/* Current model */}
                {online && currentModel && (
                  <div style={{ fontSize: '0.85rem', color: 'var(--text)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Model:</span> 
                    <span style={{ padding: '0.2rem 0.5rem', background: 'var(--surface-3)', borderRadius: '4px', border: '1px solid var(--border-bright)' }}>
                      <strong>{currentModel}</strong>
                    </span>
                  </div>
                )}

                {/* Model selector */}
                <div style={(!isMlx || isMlx && !mlxStatus.running && testResults[p.id]?.error?.includes('lifecycle management is disabled')) ? {} : { marginBottom: '1rem' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>
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
                      <option value="">Select a model...</option>
                      {ollamaModels.map(m => (
                        <option key={m.id} value={m.id}>{m.id}</option>
                      ))}
                    </select>
                  )}
                </div>

                {/* MLX management disabled hint */}
                {isMlx && !mlxSwitching && !mlxStatus.running && testResults[p.id]?.error?.includes('lifecycle management is disabled') && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.75rem', fontStyle: 'italic' }}>
                    MLX management disabled. Set JOBFORGE_MANAGE_MLX=1 to enable start/stop/pull.
                  </div>
                )}

                {/* MLX pull model */}
                {isMlx && (
                  <div style={{ marginTop: '0.25rem' }}>
                    <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>
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
                        marginTop: '0.75rem', padding: '0.75rem', background: 'var(--surface-3)',
                        borderRadius: 'var(--radius)', fontSize: '0.75rem', fontFamily: 'monospace',
                        maxHeight: 120, overflowY: 'auto', color: 'var(--text-secondary)', border: '1px solid var(--border)'
                      }}>
                        {pullStatus.progress.map((line, i) => <div key={i}>{line}</div>)}
                        {pullStatus.exit_code !== null && pullStatus.exit_code !== undefined && (
                          <div style={{ color: pullStatus.exit_code === 0 ? 'var(--green)' : 'var(--red)', marginTop: 6 }}>
                            {pullStatus.exit_code === 0 ? 'Download complete' : `Failed (exit code ${pullStatus.exit_code})`}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Action buttons */}
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                {isMlx && mlxStatus.running && (
                  <button onClick={handleMlxStop} style={btn('rgba(217,79,79,0.15)', '#ffb4b4')}>
                    Stop Server
                  </button>
                )}
                <button onClick={() => handleTest(p.id)} disabled={testing[p.id]} style={btn('var(--border-bright)', 'var(--text)', testing[p.id], true)}>
                  {testing[p.id] ? 'Testing...' : 'Test Connection'}
                </button>
                {!isActive && (
                  <button onClick={() => handleActivate(p.id)} disabled={activating[p.id]} style={btn('var(--green)', '#fff', activating[p.id])}>
                    {activating[p.id] ? 'Activating...' : 'Activate'}
                  </button>
                )}
              </div>

              {/* Test result */}
              {testResults[p.id] && (() => {
                const tr = testResults[p.id];
                const isRetrying = testing[p.id] && !tr.ok;
                const toneColor = tr.ok ? 'var(--green)' : isRetrying ? 'var(--accent)' : 'var(--red)';
                const toneBg = tr.ok ? 'rgba(60,179,113,0.08)' : isRetrying ? 'rgba(75,142,240,0.08)' : 'rgba(217,79,79,0.08)';
                return (
                  <div style={{
                    marginTop: '0.5rem', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)', fontSize: '0.8rem',
                    background: toneBg, border: `1px solid ${toneColor}`, color: toneColor,
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                  }}>
                    {isRetrying && <span className="spinner" style={{ width: 14, height: 14, flexShrink: 0 }} />}
                    <span>
                      {tr.ok
                        ? `Connected - ${tr.total} model${tr.total === 1 ? '' : 's'} available`
                        : isRetrying
                          ? tr.error
                          : `Failed: ${tr.error}`}
                    </span>
                  </div>
                );
              })()}
            </div>
          );
        })}
        </div>
      )}

      {activeTab === 'cloud' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(480px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
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
      )}

      {activeTab === 'catalog' && (
        <div style={{ marginBottom: '2rem' }}>
          {/* Machine profile header */}
          {machineProfile && (
            <div style={{
              background: 'var(--surface-2)', border: '1px solid var(--border)',
              borderRadius: '10px', padding: '1rem 1.25rem', marginBottom: '1.25rem',
              display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap',
            }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text)', letterSpacing: '-0.01em' }}>
                This Machine
              </div>
              {machineProfile.chip && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Chip</span>
                  <span style={{ ...badge('rgba(75,142,240,0.12)', 'var(--accent)'), fontSize: '0.73rem' }}>{machineProfile.chip}</span>
                </div>
              )}
              {machineProfile.cpu_cores && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>CPU</span>
                  <span style={{ ...badge('rgba(255,255,255,0.06)', 'var(--text)'), fontSize: '0.73rem' }}>{machineProfile.cpu_cores} cores</span>
                </div>
              )}
              {machineProfile.gpu_cores && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>GPU</span>
                  <span style={{ ...badge('rgba(255,255,255,0.06)', 'var(--text)'), fontSize: '0.73rem' }}>{machineProfile.gpu_cores} cores</span>
                </div>
              )}
              {machineProfile.memory_gb && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>RAM</span>
                  <span style={{ ...badge('rgba(60,179,113,0.15)', 'var(--green)'), fontSize: '0.73rem' }}>{machineProfile.memory_gb} GB unified</span>
                </div>
              )}
              {machineProfile.os_version && (
                <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginLeft: 'auto' }}>{machineProfile.os_version}</span>
              )}
            </div>
          )}

          {catalogLoading && (
            <div className="loading"><div className="spinner" /></div>
          )}
          {catalogError && (
            <div style={{
              padding: '0.75rem 1rem', borderRadius: 'var(--radius)', marginBottom: '1rem',
              background: 'rgba(217,79,79,0.08)', border: '1px solid var(--red)', color: 'var(--red)', fontSize: '0.85rem',
            }}>
              {catalogError}
            </div>
          )}

          {!catalogLoading && catalogModels.length === 0 && !catalogError && (
            <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '2rem', fontSize: '0.9rem' }}>
              No models installed. Pull models via Ollama to see them here.
            </div>
          )}

          {/* Refresh button */}
          {!catalogLoading && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.75rem' }}>
              <button onClick={refreshCatalog} style={btn('var(--surface-2)', 'var(--text)')}>
                Refresh Catalog
              </button>
            </div>
          )}

          {/* Model cards */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {catalogModels.map(m => {
              const isSelected = m.id === catalogSelected;
              const isExpanded = expandedModel === m.id;
              const bench = benchmarks[m.id];
              const isBenching = benchmarking[m.id];
              const fitColor = m.fit.rating === 'excellent' ? 'var(--green)'
                : m.fit.rating === 'good' ? 'var(--accent)'
                : m.fit.rating === 'caution' ? 'var(--yellow)'
                : m.fit.rating === 'heavy' ? 'var(--red)' : 'var(--text-secondary)';
              const fitBg = m.fit.rating === 'excellent' ? 'rgba(60,179,113,0.12)'
                : m.fit.rating === 'good' ? 'rgba(75,142,240,0.12)'
                : m.fit.rating === 'caution' ? 'rgba(255,193,7,0.12)'
                : m.fit.rating === 'heavy' ? 'rgba(217,79,79,0.12)' : 'rgba(255,255,255,0.04)';

              return (
                <div key={m.id} style={{
                  ...card(isSelected),
                  cursor: 'pointer',
                  position: 'relative' as const,
                }} onClick={() => setExpandedModel(isExpanded ? null : m.id)}>
                  {/* Top row: name + badges */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                    <span style={{
                      ...badge(
                        m.provider === 'mlx' ? 'rgba(168,85,247,0.15)' : 'rgba(75,142,240,0.12)',
                        m.provider === 'mlx' ? '#a855f7' : 'var(--accent)',
                      ),
                      fontSize: '0.66rem', textTransform: 'uppercase' as const, letterSpacing: '0.06em',
                    }}>
                      {m.provider || 'ollama'}
                    </span>
                    <span style={{ fontWeight: 600, fontSize: '0.95rem', letterSpacing: '-0.01em' }}>{m.id}</span>
                    {isSelected && <span style={badge('rgba(60,179,113,0.15)', 'var(--green)')}>SELECTED</span>}
                    <span style={{ ...badge(fitBg, fitColor), textTransform: 'uppercase' as const, letterSpacing: '0.04em' }}>
                      {m.fit.rating}
                    </span>
                    <span style={badge('rgba(255,255,255,0.06)', 'var(--text-secondary)')}>{m.use_case}</span>
                    {bench?.ok && (
                      <span style={badge('rgba(75,142,240,0.12)', 'var(--accent)')}>
                        {bench.generation_tokens_per_sec} tok/s
                      </span>
                    )}
                  </div>

                  {/* Meta row */}
                  <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
                    {m.family && <span>Family: <span style={{ color: 'var(--text)' }}>{m.family}</span></span>}
                    {m.parameter_size && <span>Params: <span style={{ color: 'var(--text)' }}>{m.parameter_size}</span></span>}
                    {m.quantization && <span>Quant: <span style={{ color: 'var(--text)' }}>{m.quantization}</span></span>}
                    {m.context_length && <span>Context: <span style={{ color: 'var(--text)' }}>{(m.context_length / 1000).toFixed(0)}k</span></span>}
                    <span>Size: <span style={{ color: 'var(--text)' }}>{fmtBytes(m.size_bytes)}</span></span>
                  </div>

                  {/* Capability badges */}
                  {m.capabilities.length > 0 && (
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', marginBottom: '0.35rem' }}>
                      {m.capabilities.map(cap => (
                        <span key={cap} style={{
                          fontSize: '0.68rem', padding: '1px 7px', borderRadius: 8,
                          background: cap === 'tools' ? 'rgba(75,142,240,0.12)'
                            : cap === 'vision' ? 'rgba(168,85,247,0.12)'
                            : cap === 'thinking' ? 'rgba(255,193,7,0.12)'
                            : 'rgba(255,255,255,0.06)',
                          color: cap === 'tools' ? 'var(--accent)'
                            : cap === 'vision' ? '#a855f7'
                            : cap === 'thinking' ? '#ffc107'
                            : 'var(--text-secondary)',
                          fontWeight: 500,
                        }}>
                          {cap}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Fit detail */}
                  <div style={{ fontSize: '0.76rem', color: fitColor, marginBottom: isExpanded ? '0.75rem' : 0 }}>
                    {m.fit.detail}
                  </div>

                  {/* Expanded: benchmark + details */}
                  {isExpanded && (
                    <div style={{
                      marginTop: '0.5rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border)',
                    }} onClick={e => e.stopPropagation()}>
                      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                        <button
                          onClick={() => handleBenchmark(m.id, m.provider || 'ollama')}
                          disabled={isBenching}
                          style={btn('var(--accent)', '#fff', isBenching)}
                        >
                          {isBenching ? 'Running...' : bench?.ok ? 'Re-run Benchmark' : 'Benchmark on This Machine'}
                        </button>
                        {!isSelected && m.provider !== 'mlx' && (
                          <button
                            onClick={async () => {
                              await api.selectLlmModel(m.id);
                              setCatalogSelected(m.id);
                              refreshOllamaModels();
                            }}
                            style={btn('var(--green)', '#fff')}
                          >
                            Select for Tailoring
                          </button>
                        )}
                        {m.modified_at && (
                          <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginLeft: 'auto' }}>
                            Updated: {fmtDate(m.modified_at)}
                          </span>
                        )}
                      </div>

                      {/* Benchmark results */}
                      {bench && (
                        <div style={{
                          background: bench.ok ? 'rgba(60,179,113,0.06)' : 'rgba(217,79,79,0.06)',
                          border: `1px solid ${bench.ok ? 'rgba(60,179,113,0.2)' : 'rgba(217,79,79,0.2)'}`,
                          borderRadius: 'var(--radius)', padding: '0.85rem 1rem',
                        }}>
                          {bench.ok ? (
                            <>
                              <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem' }}>
                                Benchmark Results
                                {bench.cached && <span style={{ fontWeight: 400, color: 'var(--text-secondary)', marginLeft: '0.5rem' }}>(cached)</span>}
                              </div>
                              <div style={{
                                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                gap: '0.5rem', fontSize: '0.8rem',
                              }}>
                                <div>
                                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', marginBottom: 2 }}>Generation Speed</div>
                                  <div style={{ fontWeight: 600, fontSize: '1.1rem', color: 'var(--green)' }}>
                                    {bench.generation_tokens_per_sec} <span style={{ fontSize: '0.75rem', fontWeight: 400 }}>tok/s</span>
                                  </div>
                                </div>
                                <div>
                                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', marginBottom: 2 }}>Time to First Token</div>
                                  <div style={{ fontWeight: 600, fontSize: '1.1rem', color: 'var(--accent)' }}>
                                    {bench.time_to_first_token_ms! < 1000
                                      ? `${Math.round(bench.time_to_first_token_ms!)} ms`
                                      : `${(bench.time_to_first_token_ms! / 1000).toFixed(1)} s`}
                                  </div>
                                </div>
                                <div>
                                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', marginBottom: 2 }}>Prompt Eval</div>
                                  <div style={{ fontWeight: 600, fontSize: '1.1rem', color: 'var(--text)' }}>
                                    {bench.prompt_eval_tokens_per_sec} <span style={{ fontSize: '0.75rem', fontWeight: 400 }}>tok/s</span>
                                  </div>
                                </div>
                                <div>
                                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', marginBottom: 2 }}>Wall Time</div>
                                  <div style={{ fontWeight: 600, fontSize: '1.1rem', color: 'var(--text)' }}>
                                    {bench.wall_time_s}s
                                  </div>
                                </div>
                              </div>
                              {bench.response_preview && (
                                <div style={{
                                  marginTop: '0.65rem', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)',
                                  background: 'var(--surface)', fontSize: '0.76rem', color: 'var(--text-secondary)',
                                  fontFamily: 'var(--font-mono)', lineHeight: 1.5, maxHeight: 80, overflowY: 'auto' as const,
                                }}>
                                  {bench.response_preview}
                                </div>
                              )}
                            </>
                          ) : (
                            <div style={{ color: 'var(--red)', fontSize: '0.82rem' }}>
                              Benchmark failed: {bench.error}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <CollapsibleSection title="Provider Console" defaultOpen={Boolean(switchState)}>
        <div style={consoleShell}>
          {activityEvents.length === 0 ? (
            <div style={{ color: '#7f92aa' }}>No provider activity yet. Switch, test, stop, or pull a model to see a trace here.</div>
          ) : (
            activityEvents.map(event => {
              const color = event.level === 'error' ? '#ff8e8e' : event.level === 'success' ? '#73d8a6' : '#8fc1ff';
              return (
                <div key={event.id} style={{ display: 'grid', gridTemplateColumns: '72px 70px 1fr', gap: '0.75rem', padding: '0.18rem 0' }}>
                  <span style={{ color: '#6f8298' }}>
                    {new Date(event.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                  <span style={{ color, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{event.level}</span>
                  <span>{event.message}</span>
                </div>
              );
            })
          )}
        </div>
      </CollapsibleSection>



      {/* Infrastructure Status */}
      <h3 style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 0.75rem' }}>
        Infrastructure
      </h3>
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '2rem', flexWrap: 'wrap' }}>
        {(infra?.services || []).map((svc: any) => (
          <div key={svc.name} style={{
            ...card(false), flex: '1 1 250px', minWidth: 220,
            display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.8rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
              <span style={dot(svc.status === 'running' ? 'var(--green)' : 'var(--red)')} />
              <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{svc.name}</span>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginLeft: 'auto' }}>:{svc.port}</span>
            </div>
            <div style={{ color: 'var(--text-secondary)' }}>Managed by: {svc.managed_by}</div>
            {svc.pid && <div style={{ color: 'var(--text-secondary)' }}>PID: {svc.pid}</div>}
            {svc.model && <div style={{ color: 'var(--text-secondary)' }}>Model: <span style={{ color: 'var(--text)' }}>{svc.model}</span></div>}
            {svc.disk_usage != null && <div style={{ color: 'var(--text-secondary)' }}>Disk: {fmtBytes(svc.disk_usage)}</div>}
            {svc.manage_enabled === false && svc.name === 'MLX' && (
              <div style={{ color: 'var(--yellow)', fontSize: '0.75rem', fontStyle: 'italic' }}>Management disabled</div>
            )}
          </div>
        ))}
      </div>

      {/* Chat */}
      <h3 style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 0.75rem' }}>
        Model Chat
      </h3>
      <div style={{
        ...card(false), display: 'flex', flexDirection: 'column', height: 420,
      }}>
        {/* Messages */}
        <div style={{
          flex: 1, overflowY: 'auto', padding: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem',
        }}>
          {chatMessages.length === 0 && (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center', marginTop: '2rem' }}>
              Send a message to test the active model
              {activeModelLabel && activeModelLabel !== 'none' && (
                <div style={{ fontSize: '0.75rem', marginTop: '0.25rem' }}>({activeModelLabel})</div>
              )}
            </div>
          )}
          {chatMessages.map((msg, i) => (
            <div key={i} style={{
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: '80%',
              padding: '0.5rem 0.75rem',
              borderRadius: 'var(--radius)',
              fontSize: '0.85rem',
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              background: msg.role === 'user' ? 'var(--accent)' : 'var(--surface-2)',
              color: msg.role === 'user' ? '#fff' : 'var(--text)',
            }}>
              {msg.content}
            </div>
          ))}
          {chatLoading && (
            <div style={{ alignSelf: 'flex-start', padding: '0.5rem 0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <span className="spinner" style={{ width: 14, height: 14, marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} />
              Thinking...
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Input */}
        <div style={{ display: 'flex', gap: '0.5rem', padding: '0.5rem 0 0', borderTop: '1px solid var(--border)' }}>
          <input
            type="text"
            value={chatInput}
            onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendChat()}
            placeholder="Type a message..."
            disabled={chatLoading}
            style={{
              flex: 1, background: 'var(--surface-2)', color: 'var(--text)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              padding: '0.5rem 0.75rem', fontSize: '0.85rem', outline: 'none',
            }}
          />
          <button
            onClick={sendChat}
            disabled={chatLoading || !chatInput.trim()}
            style={btn('var(--accent)', '#fff', chatLoading || !chatInput.trim())}
          >
            Send
          </button>
          {chatMessages.length > 0 && (
            <button
              onClick={() => setChatMessages([])}
              style={btn('var(--surface-3)', 'var(--text-secondary)')}
            >
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
