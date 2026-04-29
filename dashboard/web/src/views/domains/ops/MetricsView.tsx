import { useCallback, useEffect, useState } from 'react';
import { api } from '../../../api';
import { fmtDuration, fmtDate } from '../../../utils';

type MetricsRow = {
  id: number;
  run_slug: string;
  job_id: number;
  job_title?: string;
  job_company?: string;
  model: string | null;
  timestamp: string;
  total_wall_time_s: number | null;
  queue_wait_s: number | null;
  analysis_time_s: number | null;
  analysis_llm_time_s: number | null;
  analysis_llm_calls: number | null;
  resume_time_s: number | null;
  resume_llm_time_s: number | null;
  resume_llm_calls: number | null;
  resume_attempts: number | null;
  cover_time_s: number | null;
  cover_llm_time_s: number | null;
  cover_llm_calls: number | null;
  cover_attempts: number | null;
  compile_resume_s: number | null;
  compile_cover_s: number | null;
  total_llm_calls: number | null;
  total_llm_time_s: number | null;
};

type Baselines = Record<string, number>;

type QueueStats = Record<string, number>;
type ModelStats = Record<string, number>;

type SortKey = keyof MetricsRow;
type SortDir = 'asc' | 'desc';

function dur(v: number | null | undefined): string {
  return v != null ? fmtDuration(v) : '—';
}

function num(v: number | null | undefined): string {
  return v != null ? String(v) : '—';
}

export default function MetricsView() {
  const [metrics, setMetrics] = useState<MetricsRow[]>([]);
  const [baselines, setBaselines] = useState<Baselines>({});
  const [queueStats, setQueueStats] = useState<QueueStats>({});
  const [modelStats, setModelStats] = useState<ModelStats>({});
  
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('timestamp');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const refresh = useCallback(async () => {
    try {
      const data = await api.getTailoringMetrics();
      setMetrics(data.metrics || []);
      setBaselines(data.baselines || {});
      setQueueStats(data.queue_stats || {});
      setModelStats(data.model_stats || {});
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const sorted = [...metrics].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const sortIcon = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '400px', color: 'var(--text-muted)' }}>
        <div className="spinner" style={{ width: 32, height: 32, opacity: 0.5 }}></div>
      </div>
    );
  }

  // --- Calculations ---
  
  // Averages
  const totalWall = baselines.total_wall_time_s || 0;
  
  // Time breakdown (proportional)
  const waitTime = baselines.queue_wait_s || 0;
  const analysisTime = baselines.analysis_time_s || 0;
  const resumeTime = baselines.resume_time_s || 0;
  const coverTime = baselines.cover_time_s || 0;
  // Compile time is remainder of totalWall vs (wait+analysis+resume+cover), sometimes it overlaps or is separate.
  const knownProcessingTime = analysisTime + resumeTime + coverTime;
  const unknownProcessingTime = Math.max(0, totalWall - waitTime - knownProcessingTime);
  const totalLatency = totalWall; // Let's visualize just the wall time chunk
  
  const pct = (val: number) => (totalLatency > 0 ? (val / totalLatency) * 100 : 0) + '%';
  
  // Time Saved
  const runsCount = baselines.run_count || 0;
  const manualTimeH = 1; // Assuming 1 hr manual per job
  const aiTimeH = totalWall / 3600;
  const hoursSaved = runsCount * Math.max(0, manualTimeH - aiTimeH);

  // Success / Failure
  // Queue stats usually keys: 'queued', 'running', 'succeeded', 'failed', 'cancelled'
  const succeeded = queueStats['succeeded'] || 0;
  const failed = queueStats['failed'] || 0;
  const cancelled = queueStats['cancelled'] || 0;
  const queued = queueStats['queued'] || 0;
  const running = queueStats['running'] || 0;
  const totalFinished = succeeded + failed + cancelled; // excluding running/queued
  
  const successRate = totalFinished > 0 ? (succeeded / totalFinished) * 100 : 0;
  const failRate = totalFinished > 0 ? (failed / totalFinished) * 100 : 0;
  const cancelRate = totalFinished > 0 ? (cancelled / totalFinished) * 100 : 0;

  // Render Models
  const topModels = Object.entries(modelStats).sort((a,b) => b[1] - a[1]);

  return (
    <div style={{ padding: '24px 32px 64px', maxWidth: 1400, margin: '0 auto', animation: 'fadeIn 0.6s ease-out' }}>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 32 }}>
        <div>
          <h1 style={{ fontSize: 32, fontWeight: 700, margin: '0 0 8px', letterSpacing: '-0.02em' }}>Pipeline Metrics</h1>
          <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: 15 }}>Averaged intel across {runsCount} tailored application runs.</p>
        </div>
      </div>

      {/* TIER 1: HIGH LEVEL STATS (BENTO BOX GRID) */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', 
        gap: 24, 
        marginBottom: 32 
      }}>
        
        {/* Success Rate */}
        <div style={glassCardStyle}>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16 }}>Execution Reliability</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <span style={{ fontSize: 42, fontWeight: 700, lineHeight: 1 }}>{successRate.toFixed(1)}%</span>
            <span style={{ color: '#10b981', fontSize: 14, fontWeight: 500 }}>Success Rate</span>
          </div>
          
          <div style={{ marginTop: 24, display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', background: 'rgba(255,255,255,0.05)' }}>
            <div style={{ width: `${successRate}%`, background: '#10b981' }} title="Succeeded" />
            <div style={{ width: `${failRate}%`, background: '#ef4444' }} title="Failed" />
            <div style={{ width: `${cancelRate}%`, background: '#f59e0b' }} title="Cancelled" />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
            <span style={{ color: '#10b981' }}>{succeeded} Succeeded</span>
            <span style={{ color: '#ef4444' }}>{failed} Failed</span>
            <span style={{ color: '#f59e0b' }}>{cancelled} Cncld</span>
          </div>
        </div>

        {/* Time Saved */}
        <div style={{ ...glassCardStyle, background: 'linear-gradient(135deg, rgba(99,102,241,0.1), rgba(168,85,247,0.1))', borderColor: 'rgba(99,102,241,0.2)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16 }}>Est. Time Saved</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <span style={{ fontSize: 42, fontWeight: 700, lineHeight: 1, color: '#a855f7' }}>{hoursSaved.toFixed(0)}</span>
            <span style={{ color: '#c084fc', fontSize: 14, fontWeight: 500 }}>Hours</span>
          </div>
          <p style={{ marginTop: 24, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5, margin: '24px 0 0 0' }}>
            Compared to approx 1 hour manual tailoring per job. AI averages <strong>{dur(totalWall)}</strong> per successful package.
          </p>
        </div>

        {/* Throughput */}
        <div style={glassCardStyle}>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16 }}>Queue Activity</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
            <div style={{ flex: 1, padding: '16px', background: 'rgba(0,0,0,0.2)', borderRadius: 12, textAlign: 'center' }}>
               <div style={{ fontSize: 24, fontWeight: 600 }}>{queued}</div>
               <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Queued</div>
            </div>
            <div style={{ flex: 1, padding: '16px', background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.2)', borderRadius: 12, textAlign: 'center' }}>
               <div style={{ fontSize: 24, fontWeight: 600, color: '#60a5fa' }}>{running}</div>
               <div style={{ fontSize: 12, color: '#93c5fd', marginTop: 4 }}>Running</div>
            </div>
          </div>
          <div style={{ marginTop: 16, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>
            Average hold time: <strong>{dur(baselines.queue_wait_s)}</strong>
          </div>
        </div>
      </div>

      {/* TIER 2: DEEP DIVE (LATENCY & MODELS) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)', gap: 24, marginBottom: 32 }}>
        
        {/* Latency Breakdown */}
        <div style={glassCardStyle}>
           <h3 style={{ fontSize: 18, margin: '0 0 24px', fontWeight: 600 }}>Pipeline Latency Breakdown</h3>
           
           <div style={{ display: 'flex', width: '100%', height: 28, borderRadius: 8, overflow: 'hidden', boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.2)' }}>
              <div style={{ width: pct(waitTime), background: '#4b5563', transition: 'width 1s ease' }} title={`Queue: ${dur(waitTime)}`} />
              <div style={{ width: pct(analysisTime), background: '#3b82f6', transition: 'width 1s ease' }} title={`Analysis: ${dur(analysisTime)}`} />
              <div style={{ width: pct(resumeTime), background: '#8b5cf6', transition: 'width 1s ease' }} title={`Resume: ${dur(resumeTime)}`} />
              <div style={{ width: pct(coverTime), background: '#ec4899', transition: 'width 1s ease' }} title={`Cover: ${dur(coverTime)}`} />
              <div style={{ width: pct(unknownProcessingTime), background: '#10b981', transition: 'width 1s ease' }} title={`Compiler/Misc: ${dur(unknownProcessingTime)}`} />
           </div>

           <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px 24px', marginTop: 24 }}>
             <LegendItem color="#4b5563" label="Queue Wait" value={dur(waitTime)} />
             <LegendItem color="#3b82f6" label="Analysis (JD & Bio)" value={dur(analysisTime)} />
             <LegendItem color="#8b5cf6" label="Resume Gen" value={dur(resumeTime)} />
             <LegendItem color="#ec4899" label="Cover Letter" value={dur(coverTime)} />
             <LegendItem color="#10b981" label="Pandoc / Misc" value={dur(unknownProcessingTime)} />
           </div>

           <div style={{ marginTop: 32, paddingTop: 24, borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: 32 }}>
             <div>
               <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Avg LLM Gen Time</div>
               <div style={{ fontSize: 24, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{dur(baselines.total_llm_time_s)}</div>
             </div>
             <div>
               <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Avg LLM Inferences</div>
               <div style={{ fontSize: 24, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{baselines.total_llm_calls}</div>
             </div>
             <div>
               <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Resume / Cover Retries</div>
               <div style={{ fontSize: 24, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{baselines.resume_attempts} / {baselines.cover_attempts}</div>
             </div>
           </div>
        </div>

        {/* Model Distribution */}
        <div style={glassCardStyle}>
           <h3 style={{ fontSize: 18, margin: '0 0 24px', fontWeight: 600 }}>Model Utilization</h3>
           {topModels.length === 0 ? (
             <div style={{ color: 'var(--text-muted)' }}>No model data available.</div>
           ) : (
             <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
               {topModels.map(([modelName, count], i) => (
                 <div key={modelName} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ width: 8, height: 8, borderRadius: 4, background: i === 0 ? '#3b82f6' : 'var(--text-muted)' }} />
                      <span style={{ fontSize: 14, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                        {modelName.length > 25 ? modelName.substring(0,25) + '...' : modelName}
                      </span>
                    </div>
                    <span style={{ fontSize: 14, fontWeight: 600 }}>{count}</span>
                 </div>
               ))}
             </div>
           )}
        </div>
      </div>

      <TierStatsPanel />

      {/* TIER 3: RAW DATA */}
      <h3 style={{ fontSize: 18, margin: '0 0 16px', fontWeight: 600 }}>Recent Trace Logs</h3>
      {metrics.length === 0 ? (
        <div style={{ ...glassCardStyle, textAlign: 'center', color: 'var(--text-muted)' }}>
          No metrics yet. Run a tailoring job to start collecting data.
        </div>
      ) : (
        <div style={{ ...glassCardStyle, padding: 0, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', whiteSpace: 'nowrap', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'rgba(0,0,0,0.2)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <Th onClick={() => toggleSort('timestamp')}>Date{sortIcon('timestamp')}</Th>
                  <Th onClick={() => toggleSort('job_title')}>Job{sortIcon('job_title')}</Th>
                  <Th onClick={() => toggleSort('model')}>Model{sortIcon('model')}</Th>
                  <Th onClick={() => toggleSort('total_wall_time_s')}>Wall Time{sortIcon('total_wall_time_s')}</Th>
                  <Th onClick={() => toggleSort('queue_wait_s')}>Queue{sortIcon('queue_wait_s')}</Th>
                  <Th onClick={() => toggleSort('analysis_time_s')}>Analysis{sortIcon('analysis_time_s')}</Th>
                  <Th onClick={() => toggleSort('resume_time_s')}>Resume{sortIcon('resume_time_s')}</Th>
                  <Th onClick={() => toggleSort('cover_time_s')}>Cover{sortIcon('cover_time_s')}</Th>
                  <Th onClick={() => toggleSort('total_llm_time_s')}>LLM Time{sortIcon('total_llm_time_s')}</Th>
                  <Th onClick={() => toggleSort('total_llm_calls')}>Calls{sortIcon('total_llm_calls')}</Th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(row => (
                  <tr key={row.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', transition: 'background 0.2s', ...tableRowStyle }}>
                    <td style={tdStyle}>{fmtDate(row.timestamp)}</td>
                    <td style={{ ...tdStyle, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      <span title={`${row.job_company || ''} — ${row.job_title || row.run_slug}`}>
                        {row.job_company ? <span style={{color: 'var(--text-secondary)'}}>{row.job_company} — </span> : ''}
                        {row.job_title || row.run_slug}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
                      {(row.model || '—').split('/').pop()}
                    </td>
                    <td style={tdStyle}>{dur(row.total_wall_time_s)}</td>
                    <td style={tdStyle}>{dur(row.queue_wait_s)}</td>
                    <td style={tdStyle}>{dur(row.analysis_time_s)}</td>
                    <td style={tdStyle}>
                      {dur(row.resume_time_s)}
                      {row.resume_attempts && row.resume_attempts > 1 && (
                        <span style={{ color: '#f59e0b', fontSize: 11, marginLeft: 4 }}>({row.resume_attempts}x)</span>
                      )}
                    </td>
                    <td style={tdStyle}>
                      {dur(row.cover_time_s)}
                      {row.cover_attempts && row.cover_attempts > 1 && (
                        <span style={{ color: '#f59e0b', fontSize: 11, marginLeft: 4 }}>({row.cover_attempts}x)</span>
                      )}
                    </td>
                    <td style={tdStyle}>{dur(row.total_llm_time_s)}</td>
                    <td style={tdStyle}>{num(row.total_llm_calls)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Global CSS for Animations */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        tbody tr:hover {
          background: rgba(255,255,255,0.04) !important;
        }
      `}</style>
    </div>
  );
}

// --- Internal Components & Styles ---

const glassCardStyle: React.CSSProperties = {
  background: 'rgba(255, 255, 255, 0.03)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
  borderRadius: 16,
  padding: 24,
};

const tdStyle: React.CSSProperties = {
  padding: '12px 16px',
};

const tableRowStyle: React.CSSProperties = {
  cursor: 'default',
};

function LegendItem({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
       <div style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
       <div style={{ fontSize: 13 }}>
          <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
          <span style={{ marginLeft: 6, fontWeight: 500, fontFamily: 'var(--font-mono)' }}>{value}</span>
       </div>
    </div>
  );
}

type TierRunRow = { run_id: string; started_at: string; net_new: number | null; gate_mode: string | null; rotation_group: number | null };
type TierSourceRow = {
  source: string;
  tier: string;
  raw_hits: number;
  dedup_drops: number;
  duplicate_url?: number;
  duplicate_ats_id?: number;
  duplicate_fingerprint?: number;
  duplicate_similar?: number;
  duplicate_content?: number;
  filter_drops: number;
  llm_rejects: number;
  stored_pending: number;
  stored_lead: number;
  runs: number;
};
type TierDayRow = { day: string; net_new: number };
type TierStatsPayload = { per_run: TierRunRow[]; by_source: TierSourceRow[]; daily_net_new: TierDayRow[] };

function TierStatsPanel() {
  const [data, setData] = useState<TierStatsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getTierStatsRollup('7d').then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div style={{ ...glassCardStyle, marginBottom: 32, color: 'var(--text-muted)' }}>
        Scraper tier stats unavailable: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div style={{ ...glassCardStyle, marginBottom: 32, color: 'var(--text-muted)' }}>Loading scraper tier stats…</div>
    );
  }

  const lastThree = (data.per_run || []).slice(0, 3);
  const overflowWarn = lastThree.length === 3 && lastThree.every((r) => r.gate_mode === 'overflow');

  return (
    <section style={{ ...glassCardStyle, marginBottom: 32 }}>
      <h3 style={{ fontSize: 18, margin: '0 0 16px', fontWeight: 600 }}>Scraper tier stats (7d)</h3>

      {overflowWarn && (
        <div style={{ background: 'rgba(240, 160, 48, 0.12)', border: '1px solid rgba(240, 160, 48, 0.4)', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
          Gate overflow on last 3 runs — SearXNG volume or LLM endpoint may need attention.
        </div>
      )}

      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>Daily net-new (50/day target)</div>
        {data.daily_net_new.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No runs recorded in the last 7 days.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
            {data.daily_net_new.map((d) => {
              const below = (d.net_new ?? 0) < 35;
              return (
                <li key={d.day} style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{d.day}</div>
                  <div style={{ fontSize: 20, fontWeight: 600, color: below ? '#ef4444' : 'var(--text-primary)' }}>
                    {d.net_new}
                    {below && <span style={{ fontSize: 11, marginLeft: 6, color: '#f87171' }}>&lt;70%</span>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>Source health</div>
        {data.by_source.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No tier stats recorded yet.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'rgba(0,0,0,0.2)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <th style={{ padding: '10px 12px', textAlign: 'left', color: 'var(--text-secondary)', fontWeight: 600 }}>Tier</th>
                  <th style={{ padding: '10px 12px', textAlign: 'left', color: 'var(--text-secondary)', fontWeight: 600 }}>Source</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Raw</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Dedup-drop</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Dup detail</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Filter-drop</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>LLM-reject</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Pending</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Lead</th>
                  <th style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)', fontWeight: 600 }}>Runs</th>
                </tr>
              </thead>
              <tbody>
                {data.by_source.map((r) => (
                  <tr key={`${r.tier}-${r.source}`} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                    <td style={{ padding: '8px 12px' }}>{r.tier}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{r.source}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.raw_hits}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.dedup_drops}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                      {(r.duplicate_url ?? 0) + (r.duplicate_ats_id ?? 0) + (r.duplicate_fingerprint ?? 0) + (r.duplicate_similar ?? 0) + (r.duplicate_content ?? 0)}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.filter_drops}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.llm_rejects}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.stored_pending}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.stored_lead}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.runs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function Th({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <th
      onClick={onClick}
      style={{ 
        padding: '12px 16px', 
        cursor: 'pointer', 
        userSelect: 'none', 
        fontWeight: 600, 
        color: 'var(--text-secondary)',
        transition: 'color 0.2s'
      }}
    >
      {children}
    </th>
  );
}
