import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../../api';
import { fmtDate } from '../../../utils';

type RunRow = {
  run_id: string;
  started_at: string;
  net_new: number | null;
  gate_mode: string | null;
  rotation_group: number | null;
};

type SourceRow = {
  source: string;
  tier: string;
  raw_hits: number;
  dedup_drops: number;
  filter_drops: number;
  llm_rejects: number;
  stored_pending: number;
  stored_lead: number;
  runs: number;
};

type DayRow = { day: string; net_new: number | null };

type TierStats = { per_run: RunRow[]; by_source: SourceRow[]; daily_net_new: DayRow[] };

type SystemStatus = {
  profile: { target_net_new_per_run?: number; rotation_groups?: number };
  scheduler: { cadence_hours: number | null };
  last_run: RunRow | null;
};

export default function ScraperMetricsView() {
  const [stats, setStats] = useState<TierStats | null>(null);
  const [sys, setSys] = useState<SystemStatus | null>(null);
  const [since, setSince] = useState<'7d' | '14d' | '30d'>('7d');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [a, b] = await Promise.all([api.getTierStatsRollup(since), api.getSystemStatus()]);
      setStats(a);
      setSys(b);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [since]);

  useEffect(() => { refresh(); }, [refresh]);

  const target = sys?.profile.target_net_new_per_run ?? 13;
  const rotationGroups = sys?.profile.rotation_groups ?? 4;
  const cadenceHours = sys?.scheduler.cadence_hours ?? 6;
  const runsPerDay = Math.max(1, Math.round(24 / cadenceHours));
  const dailyTarget = target * runsPerDay;

  const kpis = useMemo(() => computeKpis(stats, target), [stats, target]);

  if (loading && !stats) return <Frame>Loading…</Frame>;
  if (error) return <Frame>Failed to load: {error}</Frame>;
  if (!stats) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, padding: 24 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div>
          <h1 style={{ fontSize: 28, margin: 0, fontWeight: 600 }}>Scraper Metrics</h1>
          <p style={{ color: 'var(--text-muted)', margin: '4px 0 0', fontSize: 13 }}>
            Tier-aware scheduler output. Target: <strong>{target}</strong> net-new / run,{' '}
            <strong>{dailyTarget}</strong> / day at {runsPerDay} runs/day.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Window</label>
          <select
            value={since}
            onChange={(e) => setSince(e.target.value as '7d' | '14d' | '30d')}
            style={{
              padding: '6px 10px',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'var(--text-primary)',
              borderRadius: 6,
              fontSize: 13,
            }}
          >
            <option value="7d">7 days</option>
            <option value="14d">14 days</option>
            <option value="30d">30 days</option>
          </select>
          <button onClick={refresh} style={btn}>Refresh</button>
        </div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
        <KpiTile
          label="Last run"
          value={kpis.lastNetNew != null ? String(kpis.lastNetNew) : '—'}
          unit={kpis.lastNetNew != null ? `/ ${target} target` : ''}
          tone={kpis.lastNetNew == null ? 'muted' : kpis.lastNetNew >= target ? 'good' : kpis.lastNetNew >= target * 0.7 ? 'warn' : 'bad'}
        />
        <KpiTile
          label={`Total net-new (${since})`}
          value={kpis.totalNetNew != null ? String(kpis.totalNetNew) : '—'}
          unit={kpis.totalNetNew != null ? `vs ${kpis.windowTarget} target` : ''}
          tone={kpis.totalNetNew == null ? 'muted' : kpis.totalNetNew >= kpis.windowTarget ? 'good' : 'warn'}
        />
        <KpiTile
          label="Gate overflow rate"
          value={kpis.gateTotal === 0 ? '—' : `${Math.round((kpis.overflow / kpis.gateTotal) * 100)}%`}
          unit={kpis.gateTotal === 0 ? '' : `${kpis.overflow}/${kpis.gateTotal} runs`}
          tone={kpis.gateTotal === 0 ? 'muted' : kpis.overflow === 0 ? 'good' : kpis.overflow / kpis.gateTotal > 0.33 ? 'bad' : 'warn'}
        />
        <KpiTile
          label="Rotation coverage"
          value={kpis.rotationSeen.size > 0 ? `${kpis.rotationSeen.size} / ${rotationGroups}` : '—'}
          unit="groups seen"
          tone={kpis.rotationSeen.size === rotationGroups ? 'good' : 'muted'}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 16 }}>
        <section style={card}>
          <SectionHeader
            title={`Daily net-new (${since})`}
            subtitle={`Dashed line = daily target (${dailyTarget}). Bars below mean the pipeline is starving.`}
          />
          <DailyChart data={stats.daily_net_new} target={dailyTarget} />
        </section>

        <section style={card}>
          <SectionHeader
            title="Per-run net-new (last 20)"
            subtitle="Green = gate ran normally. Amber = overflow (gate skipped some items). Grey = historical run before freshness merge."
          />
          <RunStrip rows={stats.per_run.slice(0, 20)} target={target} />
        </section>
      </div>

      <section style={card}>
        <SectionHeader
          title={`Source health (${since})`}
          subtitle="For each source: raw hits that came in, and the fate of those hits across dedup, filter, LLM gate, and storage."
        />
        <SourceTable rows={stats.by_source} />
      </section>
    </div>
  );
}

function computeKpis(stats: TierStats | null, target: number) {
  const lastNetNew = stats?.per_run[0]?.net_new ?? null;
  const dayCount = stats?.daily_net_new.length ?? 0;
  const totalNetNew = stats?.daily_net_new.reduce((acc, d) => acc + (d.net_new ?? 0), 0) ?? null;
  const runsInWindow = stats?.per_run.length ?? 0;
  const windowTarget = runsInWindow * target;
  const rotationSeen = new Set<number>();
  let overflow = 0;
  let gateTotal = 0;
  stats?.per_run.forEach((r) => {
    if (r.rotation_group != null) rotationSeen.add(r.rotation_group);
    if (r.gate_mode != null) {
      gateTotal += 1;
      if (r.gate_mode === 'overflow') overflow += 1;
    }
  });
  return { lastNetNew, totalNetNew, rotationSeen, overflow, gateTotal, windowTarget, dayCount };
}

function DailyChart({ data, target }: { data: DayRow[]; target: number }) {
  if (data.length === 0) return <Empty>No runs in this window.</Empty>;
  const values = data.map((d) => d.net_new ?? 0);
  const max = Math.max(target * 1.2, ...values, 1);
  const width = 100 / data.length;
  return (
    <div style={{ position: 'relative', height: 180 }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
        <line
          x1="0"
          x2="100"
          y1={100 - (target / max) * 100}
          y2={100 - (target / max) * 100}
          stroke="rgba(250, 204, 21, 0.6)"
          strokeWidth="0.4"
          strokeDasharray="1 1"
          vectorEffect="non-scaling-stroke"
        />
        {data.map((d, i) => {
          const v = d.net_new ?? 0;
          const h = (v / max) * 100;
          const x = i * width + width * 0.15;
          const barW = width * 0.7;
          const color = v >= target ? 'rgba(34,197,94,0.8)' : v >= target * 0.5 ? 'rgba(245,158,11,0.8)' : 'rgba(239,68,68,0.7)';
          return (
            <g key={d.day}>
              <rect x={x} y={100 - h} width={barW} height={h} fill={color} rx="0.5" />
            </g>
          );
        })}
      </svg>
      <div style={{ display: 'flex', marginTop: 4 }}>
        {data.map((d) => (
          <div key={d.day} style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{d.net_new ?? 0}</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{d.day.slice(5)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RunStrip({ rows, target }: { rows: RunRow[]; target: number }) {
  if (rows.length === 0) return <Empty>No runs yet.</Empty>;
  const reversed = [...rows].reverse();
  const values = reversed.map((r) => r.net_new ?? 0);
  const max = Math.max(target * 1.2, ...values, 1);
  return (
    <div style={{ height: 180, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', flex: 1, gap: 3 }}>
        {reversed.map((r) => {
          const v = r.net_new;
          const h = v == null ? 20 : (v / max) * 100;
          const color = v == null
            ? 'rgba(255,255,255,0.08)'
            : r.gate_mode === 'overflow'
            ? 'rgba(245,158,11,0.8)'
            : r.gate_mode === 'normal'
            ? 'rgba(34,197,94,0.75)'
            : 'rgba(147, 197, 253, 0.6)';
          const title = `${fmtDate(r.started_at)} · net-new=${v ?? 'n/a'} · gate=${r.gate_mode ?? 'n/a'} · group=${r.rotation_group ?? 'n/a'}`;
          return (
            <div
              key={r.run_id}
              title={title}
              style={{
                flex: 1,
                height: `${h}%`,
                background: color,
                borderRadius: 2,
                minHeight: v == null ? 2 : 4,
              }}
            />
          );
        })}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6, display: 'flex', justifyContent: 'space-between' }}>
        <span>older</span>
        <span>newer →</span>
      </div>
    </div>
  );
}

function SourceTable({ rows }: { rows: SourceRow[] }) {
  if (rows.length === 0) {
    return <Empty>No per-tier stats yet. Stats populate after the first scheduler-driven run.</Empty>;
  }
  const tierOrder: Record<string, number> = { workhorse: 0, discovery: 1, lead: 2 };
  const sorted = [...rows].sort((a, b) => {
    const t = (tierOrder[a.tier] ?? 99) - (tierOrder[b.tier] ?? 99);
    return t !== 0 ? t : b.raw_hits - a.raw_hits;
  });
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: 'left', color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          <th style={th}>Source</th>
          <th style={th}>Tier</th>
          <th style={{ ...th, textAlign: 'right' }}>Raw</th>
          <th style={{ ...th, textAlign: 'right' }}>Dedup</th>
          <th style={{ ...th, textAlign: 'right' }}>Filter</th>
          <th style={{ ...th, textAlign: 'right' }}>LLM</th>
          <th style={{ ...th, textAlign: 'right' }}>Stored</th>
          <th style={{ ...th, minWidth: 160 }}>Funnel</th>
          <th style={{ ...th, textAlign: 'right' }}>Runs</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => {
          const stored = r.stored_pending + r.stored_lead;
          return (
            <tr key={`${r.source}-${r.tier}`} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ ...td, fontFamily: 'var(--font-mono)' }}>{r.source}</td>
              <td style={{ ...td }}>
                <TierBadge tier={r.tier} />
              </td>
              <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{r.raw_hits}</td>
              <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{r.dedup_drops}</td>
              <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{r.filter_drops}</td>
              <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{r.llm_rejects}</td>
              <td style={{ ...td, textAlign: 'right', color: 'rgb(134, 239, 172)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{stored}</td>
              <td style={{ ...td }}>
                <FunnelBar raw={r.raw_hits} stored={stored} dedup={r.dedup_drops} filter={r.filter_drops} llm={r.llm_rejects} />
              </td>
              <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{r.runs}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function FunnelBar({ raw, stored, dedup, filter, llm }: { raw: number; stored: number; dedup: number; filter: number; llm: number }) {
  const total = Math.max(raw, stored + dedup + filter + llm, 1);
  const seg = (v: number, c: string) => ({ flex: v / total, background: c });
  return (
    <div style={{ display: 'flex', height: 10, borderRadius: 3, overflow: 'hidden', background: 'rgba(255,255,255,0.04)' }}>
      <div style={{ ...seg(stored, 'rgba(34,197,94,0.8)') }} />
      <div style={{ ...seg(dedup, 'rgba(148,163,184,0.5)') }} />
      <div style={{ ...seg(filter, 'rgba(239,68,68,0.6)') }} />
      <div style={{ ...seg(llm, 'rgba(168,85,247,0.6)') }} />
    </div>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const colors: Record<string, string> = {
    workhorse: 'rgba(34,197,94,0.2)',
    discovery: 'rgba(168,85,247,0.2)',
    lead: 'rgba(59,130,246,0.2)',
  };
  return (
    <span
      style={{
        fontSize: 11,
        padding: '2px 8px',
        borderRadius: 4,
        background: colors[tier] ?? 'rgba(255,255,255,0.05)',
        fontFamily: 'var(--font-mono)',
      }}
    >
      {tier}
    </span>
  );
}

function KpiTile({ label, value, unit, tone }: { label: string; value: string; unit?: string; tone: 'good' | 'warn' | 'bad' | 'muted' }) {
  const accent: Record<string, string> = {
    good: 'rgb(134, 239, 172)',
    warn: 'rgb(252, 211, 77)',
    bad: 'rgb(252, 165, 165)',
    muted: 'var(--text-muted)',
  };
  return (
    <div style={{ ...card, padding: 16 }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ marginTop: 6, display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <div style={{ fontSize: 28, fontWeight: 600, color: accent[tone], fontVariantNumeric: 'tabular-nums' }}>{value}</div>
        {unit && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{unit}</div>}
      </div>
    </div>
  );
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <h2 style={{ fontSize: 15, margin: 0, fontWeight: 600 }}>{title}</h2>
      {subtitle && <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>{subtitle}</p>}
    </div>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return <div style={{ ...card, margin: 24, color: 'var(--text-muted)' }}>{children}</div>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: '16px 0' }}>{children}</div>;
}

const card: React.CSSProperties = {
  background: 'rgba(255, 255, 255, 0.03)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
  borderRadius: 16,
  padding: 20,
};

const th: React.CSSProperties = {
  padding: '8px 10px',
  fontWeight: 500,
};

const td: React.CSSProperties = {
  padding: '10px',
};

const btn: React.CSSProperties = {
  padding: '6px 14px',
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontSize: 13,
  cursor: 'pointer',
};
