import { useCallback, useEffect, useState } from 'react';
import { api } from '../../../api';
import { fmtDate } from '../../../utils';

type SchedulerBlock = {
  enabled: boolean;
  cadence: string | null;
  cadence_hours: number | null;
  next_run_at: string | null;
  running: boolean;
};

type ProfileBlock = {
  rotation_groups?: number;
  rotation_cycle_hours?: number;
  seen_ttl_days?: number;
  discovery_every_nth_run?: number;
  target_net_new_per_run?: number;
  error?: string;
};

type LLMGateBlock = {
  enabled?: boolean;
  endpoint?: string;
  model?: string;
  fallback_endpoint?: string;
  fallback_model?: string;
  accept_threshold?: number;
  max_calls_per_run?: number;
  timeout_seconds?: number;
  fail_open?: boolean;
};

type TierRow = { tier: string; spiders: string[] };

type LastRun = {
  run_id: string;
  started_at: string | null;
  completed_at: string | null;
  status: string | null;
  net_new: number | null;
  gate_mode: string | null;
  rotation_group: number | null;
};

type SystemStatus = {
  scheduler: SchedulerBlock;
  profile: ProfileBlock;
  llm_gate: LLMGateBlock;
  tiers: TierRow[];
  feature_flags: Record<string, string>;
  last_run: LastRun | null;
};

const TIER_META: Record<string, { label: string; desc: string; accent: string }> = {
  workhorse: {
    label: 'Workhorse',
    desc: 'Direct ATS — high signal, known-good boards',
    accent: 'rgba(34, 197, 94, 0.35)',
  },
  discovery: {
    label: 'Discovery',
    desc: 'Breadth via SearXNG — gated by LLM relevance',
    accent: 'rgba(168, 85, 247, 0.35)',
  },
  lead: {
    label: 'Lead',
    desc: 'Thin JDs for manual triage',
    accent: 'rgba(59, 130, 246, 0.35)',
  },
};

export default function SystemStatusView() {
  const [data, setData] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getSystemStatus();
      setData(resp);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading && !data) return <div style={{ ...card, color: 'var(--text-muted)' }}>Loading system status…</div>;
  if (error) return <div style={{ ...card, color: 'var(--text-muted)' }}>Failed to load: {error}</div>;
  if (!data) return null;

  const { scheduler, profile, llm_gate, tiers, feature_flags, last_run } = data;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div>
          <h1 style={{ fontSize: 28, margin: 0, fontWeight: 600 }}>System Status</h1>
          <p style={{ color: 'var(--text-muted)', margin: '4px 0 0 0', fontSize: 13 }}>
            Scheduler, scrape profile, and feature-flag snapshot.
          </p>
        </div>
        <button
          onClick={refresh}
          style={{
            padding: '6px 14px',
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 8,
            color: 'var(--text-primary)',
            fontSize: 13,
            cursor: 'pointer',
          }}
        >
          Refresh
        </button>
      </header>

      <section style={card}>
        <SectionHeader title="Scheduler" />
        <div style={grid2}>
          <StatusPill
            label="Enabled"
            value={scheduler.enabled ? 'on' : 'off'}
            tone={scheduler.enabled ? 'good' : 'warn'}
            hint={scheduler.enabled ? 'TEXTAILOR_SCRAPE_SCHEDULER=1' : 'Set env var to enable'}
          />
          <StatusPill
            label="Currently running"
            value={scheduler.running ? 'scrape in progress' : 'idle'}
            tone={scheduler.running ? 'info' : 'muted'}
          />
          <KV label="Cadence (cron)" value={scheduler.cadence ?? '—'} mono />
          <KV
            label="Every"
            value={scheduler.cadence_hours != null ? `${scheduler.cadence_hours} hours` : '—'}
          />
          <KV label="Next tick" value={scheduler.next_run_at ? fmtDate(scheduler.next_run_at) : '—'} mono />
        </div>
      </section>

      <section style={card}>
        <SectionHeader title="Scrape Profile" />
        {profile.error ? (
          <div style={{ color: 'rgb(239, 68, 68)' }}>Failed to load profile: {profile.error}</div>
        ) : (
          <div style={grid3}>
            <KV label="Rotation groups" value={String(profile.rotation_groups)} />
            <KV label="Full cycle" value={`${profile.rotation_cycle_hours} hrs`} />
            <KV label="Dedup TTL" value={`${profile.seen_ttl_days} days`} />
            <KV label="Discovery every Nth" value={String(profile.discovery_every_nth_run)} />
            <KV label="Target net-new / run" value={String(profile.target_net_new_per_run)} />
          </div>
        )}
      </section>

      <section style={card}>
        <SectionHeader title="LLM Relevance Gate (discovery tier)" />
        {Object.keys(llm_gate).length === 0 ? (
          <div style={{ color: 'var(--text-muted)' }}>Not configured</div>
        ) : (
          <div style={grid2}>
            <StatusPill
              label="Enabled"
              value={llm_gate.enabled ? 'on' : 'off'}
              tone={llm_gate.enabled ? 'good' : 'muted'}
            />
            <KV label="Model (primary)" value={llm_gate.model ?? '—'} mono />
            <KV label="Endpoint" value={llm_gate.endpoint ?? '—'} mono />
            <KV label="Model (fallback)" value={llm_gate.fallback_model ?? '—'} mono />
            <KV label="Fallback endpoint" value={llm_gate.fallback_endpoint ?? '—'} mono />
            <KV label="Accept threshold" value={`≥ ${llm_gate.accept_threshold} / 10`} />
            <KV label="Max calls / run" value={String(llm_gate.max_calls_per_run)} />
            <KV label="Timeout" value={`${llm_gate.timeout_seconds}s`} />
            <KV label="Fail open" value={llm_gate.fail_open ? 'yes' : 'no'} />
          </div>
        )}
      </section>

      <section style={card}>
        <SectionHeader title="Tier Roster" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
          {tiers.map((t) => {
            const meta = TIER_META[t.tier] || { label: t.tier, desc: '', accent: 'rgba(255,255,255,0.2)' };
            return (
              <div
                key={t.tier}
                style={{
                  padding: 16,
                  borderRadius: 12,
                  background: 'rgba(255,255,255,0.02)',
                  border: `1px solid ${meta.accent}`,
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{meta.label}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>{meta.desc}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {t.spiders.map((s) => (
                    <span
                      key={s}
                      style={{
                        fontSize: 11,
                        fontFamily: 'var(--font-mono)',
                        padding: '3px 8px',
                        borderRadius: 6,
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.08)',
                      }}
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section style={card}>
        <SectionHeader title="Feature Flags" />
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <tbody>
            {Object.entries(feature_flags).map(([k, v]) => (
              <tr key={k} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '8px 0', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{k}</td>
                <td style={{ padding: '8px 0', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: v === '1' ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.04)',
                      color: v === '1' ? 'rgb(134, 239, 172)' : 'var(--text-muted)',
                    }}
                  >
                    {v || '(unset)'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section style={card}>
        <SectionHeader title="Last Run" />
        {!last_run ? (
          <div style={{ color: 'var(--text-muted)' }}>No runs yet.</div>
        ) : (
          <div style={grid3}>
            <KV label="Run ID" value={last_run.run_id} mono />
            <KV label="Started" value={last_run.started_at ? fmtDate(last_run.started_at) : '—'} />
            <KV label="Completed" value={last_run.completed_at ? fmtDate(last_run.completed_at) : '—'} />
            <KV label="Status" value={last_run.status ?? '—'} />
            <KV label="Net-new" value={last_run.net_new != null ? String(last_run.net_new) : '—'} />
            <KV label="Gate mode" value={last_run.gate_mode ?? '—'} />
            <KV label="Rotation group" value={last_run.rotation_group != null ? String(last_run.rotation_group) : '—'} />
          </div>
        )}
      </section>
    </div>
  );
}

const card: React.CSSProperties = {
  background: 'rgba(255, 255, 255, 0.03)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
  borderRadius: 16,
  padding: 24,
};

const grid2: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
  gap: 16,
};

const grid3: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
  gap: 16,
};

function SectionHeader({ title }: { title: string }) {
  return <h2 style={{ fontSize: 16, margin: '0 0 16px 0', fontWeight: 600 }}>{title}</h2>;
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-muted)', marginBottom: 4 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 14,
          fontFamily: mono ? 'var(--font-mono)' : undefined,
          wordBreak: 'break-all',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function StatusPill({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone: 'good' | 'warn' | 'info' | 'muted';
  hint?: string;
}) {
  const toneStyle: Record<string, { bg: string; fg: string }> = {
    good: { bg: 'rgba(34,197,94,0.15)', fg: 'rgb(134, 239, 172)' },
    warn: { bg: 'rgba(245,158,11,0.15)', fg: 'rgb(252, 211, 77)' },
    info: { bg: 'rgba(59,130,246,0.15)', fg: 'rgb(147, 197, 253)' },
    muted: { bg: 'rgba(255,255,255,0.04)', fg: 'var(--text-muted)' },
  };
  const { bg, fg } = toneStyle[tone];
  return (
    <div>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-muted)', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ padding: '3px 10px', borderRadius: 6, background: bg, color: fg, fontSize: 13, fontWeight: 500 }}>
          {value}
        </span>
        {hint && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{hint}</span>}
      </div>
    </div>
  );
}
