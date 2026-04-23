import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../../api';
import { fmtDate } from '../../../utils';

type RunRow = {
  run_id: string;
  started_at: string;
  net_new: number | null;
  net_new_qa_pending: number;
  net_new_lead: number;
  gate_mode: string | null;
  rotation_group: number | null;
};

type ReviewHealth = 'green' | 'yellow' | 'red' | 'unknown';

type RunReview = {
  health?: ReviewHealth;
  summary?: string;
  flags?: string[];
  recommendations?: string[];
  _raw?: string;
};

type ReviewedRun = {
  run_id: string;
  started_at: string;
  completed_at: string | null;
  elapsed: number | null;
  net_new: number | null;
  gate_mode: string | null;
  rotation_group: number | null;
  rotation_members: string[] | null;
  raw_count: number | null;
  dedup_count: number | null;
  filtered_count: number | null;
  llm_review_at: string | null;
  review: RunReview | null;
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

type DayRow = {
  day: string;
  net_new: number | null;
  net_new_qa_pending: number;
  net_new_lead: number;
};

type TierStats = { per_run: RunRow[]; by_source: SourceRow[]; daily_net_new: DayRow[] };

type SystemStatus = {
  profile: { target_net_new_per_run?: number; rotation_groups?: number };
  scheduler: { cadence_hours: number | null };
  last_run: RunRow | null;
};

type ScraperReportSummary = {
  raw?: number;
  dedup?: number;
  filtered?: number;
  net_new?: number;
  errors?: number;
  accepted?: number;
  rejected?: number;
  jobs?: number;
};

type ScraperReportItem = {
  run_id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  elapsed: number | null;
  raw_count: number | null;
  dedup_count: number | null;
  filtered_count: number | null;
  error_count: number | null;
  trigger_source: string | null;
  net_new: number | null;
  gate_mode: string | null;
  rotation_group: number | null;
  rotation_members?: string[] | null;
  llm_review_at: string | null;
  review: RunReview | null;
  review_health?: ReviewHealth | null;
  source_count: number;
  job_status_counts: Record<string, number>;
  summary: ScraperReportSummary;
};

type ScraperReportJob = {
  id: number;
  title: string;
  company: string;
  url: string;
  board: string;
  source: string;
  status: string;
  rejection_stage: string | null;
  rejection_reason: string | null;
  seniority: string | null;
  experience_years: number | null;
  salary_k: number | null;
  score: number | null;
  created_at: string | null;
};

type ScraperTierStat = {
  tier: string;
  source: string;
  raw_hits: number;
  dedup_drops: number;
  filter_drops: number;
  llm_rejects: number;
  llm_uncertain_low: number;
  llm_overflow: number;
  stored_pending: number;
  stored_lead: number;
  duration_ms: number | null;
};

type ScraperReportDetail = ScraperReportItem & {
  errors: string[];
  tier_stats: ScraperTierStat[];
  jobs: ScraperReportJob[];
};

export default function ScraperMetricsView() {
  const [stats, setStats] = useState<TierStats | null>(null);
  const [sys, setSys] = useState<SystemStatus | null>(null);
  const [reviews, setReviews] = useState<ReviewedRun[]>([]);
  const [reports, setReports] = useState<ScraperReportItem[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [reportDetail, setReportDetail] = useState<ScraperReportDetail | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [jobStatusFilter, setJobStatusFilter] = useState('all');
  const [regenerating, setRegenerating] = useState<string | null>(null);
  const [since, setSince] = useState<'7d' | '14d' | '30d'>('7d');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [a, b, c, d] = await Promise.all([
        api.getTierStatsRollup(since),
        api.getSystemStatus(),
        api.getScraperReviews(10),
        api.getScraperReports(100),
      ]);
      setStats(a);
      setSys(b);
      setReviews(c.runs ?? []);
      const reportItems = d.items ?? [];
      setReports(reportItems);
      setSelectedReportId((prev) => prev ?? reportItems[0]?.run_id ?? null);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [since]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!selectedReportId) {
      setReportDetail(null);
      return;
    }
    let cancelled = false;
    setReportLoading(true);
    api.getScraperReport(selectedReportId)
      .then((res) => {
        if (!cancelled) setReportDetail(res.report ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setReportLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedReportId]);

  const handleRegenerate = useCallback(async (runId: string) => {
    setRegenerating(runId);
    try {
      await api.regenerateScraperReview(runId);
      const [c, d] = await Promise.all([
        api.getScraperReviews(10),
        api.getScraperReports(100),
      ]);
      setReviews(c.runs ?? []);
      setReports(d.items ?? []);
      if (selectedReportId === runId) {
        const detail = await api.getScraperReport(runId);
        setReportDetail(detail.report ?? null);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRegenerating(null);
    }
  }, [selectedReportId]);

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
          <p style={{ color: 'var(--text-muted)', margin: '4px 0 0', fontSize: 13, maxWidth: 780, lineHeight: 1.55 }}>
            Tier-aware scheduler fires every <strong>{cadenceHours}h</strong> ({runsPerDay} runs/day) and rotates spiders across{' '}
            <strong>{rotationGroups}</strong> discovery groups. Target: <strong>{target}</strong> net-new jobs per run (
            <strong>{dailyTarget}</strong>/day). Each completed run is auto-reviewed by the LLM oversight loop below; the KPI
            tiles, per-run strip, and source funnel below are the inputs the reviewer sees.
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

      <LatestReviewPanel
        reviews={reviews}
        onRegenerate={handleRegenerate}
        regenerating={regenerating}
      />

      <ScraperReportsPanel
        reports={reports}
        selectedId={selectedReportId}
        detail={reportDetail}
        loading={reportLoading}
        statusFilter={jobStatusFilter}
        onStatusFilter={setJobStatusFilter}
        onSelect={setSelectedReportId}
        onRegenerate={handleRegenerate}
        regenerating={regenerating}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
        <KpiTile
          label="Last run"
          value={kpis.lastNetNew != null ? String(kpis.lastNetNew) : '—'}
          unit={kpis.lastNetNew != null ? `/ ${target} target` : ''}
          tone={kpis.lastNetNew == null ? 'muted' : kpis.lastNetNew >= target ? 'good' : kpis.lastNetNew >= target * 0.7 ? 'warn' : 'bad'}
          footer={kpis.lastNetNew != null ? <StatusSplit qa={kpis.lastQaPending} lead={kpis.lastLead} /> : undefined}
        />
        <KpiTile
          label={`Total net-new (${since})`}
          value={kpis.totalNetNew != null ? String(kpis.totalNetNew) : '—'}
          unit={kpis.totalNetNew != null ? `vs ${kpis.windowTarget} target` : ''}
          tone={kpis.totalNetNew == null ? 'muted' : kpis.totalNetNew >= kpis.windowTarget ? 'good' : 'warn'}
          footer={kpis.totalNetNew != null ? <StatusSplit qa={kpis.totalQaPending} lead={kpis.totalLead} /> : undefined}
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
            subtitle={`Bars are stacked by scrape-time status: amber = qa_pending (still owes QA approval before tailoring), blue = lead (hn_hiring/remoteok — lowest confidence). Dashed line = daily target (${dailyTarget}). Target is set at total-net-new today — "ready for tailoring" is a subset earned after QA.`}
          />
          <DailyChart data={stats.daily_net_new} target={dailyTarget} />
        </section>

        <section style={card}>
          <SectionHeader
            title="Per-run net-new (last 20)"
            subtitle="Bar height = net-new stored. Fill is stacked by status (amber = qa_pending, blue = lead). Outline reflects the gate: green = normal, amber = overflow (budget hit, some items unscored), no outline = skipped_by_cadence. Hover a bar for exact breakdown."
          />
          <RunStrip rows={stats.per_run.slice(0, 20)} target={target} />
        </section>
      </div>

      <section style={card}>
        <SectionHeader
          title={`Source health (${since})`}
          subtitle="Per-spider funnel aggregated over the window. Tiers: workhorse (always runs, known-good sources) · discovery (rotates, LLM-gated for noise) · lead (HN hiring / curated). Columns: Raw = items fetched; Dedup/Filter/LLM = drops at each stage; Stored = kept as pending or lead; Runs = how many scheduler ticks this spider appeared in."
        />
        <SourceTable rows={stats.by_source} />
      </section>
    </div>
  );
}

function runDuration(start?: string | null, end?: string | null, elapsed?: number | null) {
  if (elapsed != null && Number.isFinite(elapsed)) {
    const seconds = Math.round(elapsed);
    return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
  }
  if (!start || !end) return '--';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '--';
  const seconds = Math.round(ms / 1000);
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
}

function ScraperReportsPanel({
  reports,
  selectedId,
  detail,
  loading,
  statusFilter,
  onStatusFilter,
  onSelect,
  onRegenerate,
  regenerating,
}: {
  reports: ScraperReportItem[];
  selectedId: string | null;
  detail: ScraperReportDetail | null;
  loading: boolean;
  statusFilter: string;
  onStatusFilter: (status: string) => void;
  onSelect: (runId: string) => void;
  onRegenerate: (runId: string) => void;
  regenerating: string | null;
}) {
  const filteredJobs = (detail?.jobs ?? []).filter((job) => statusFilter === 'all' || job.status === statusFilter);
  const statusOptions = Array.from(new Set((detail?.jobs ?? []).map((job) => job.status).filter(Boolean))).sort();
  const selectedSummary = detail?.summary ?? reports.find((report) => report.run_id === selectedId)?.summary ?? {};
  const review = detail?.review;
  const health = (detail?.review_health || review?.health || 'unknown') as ReviewHealth;
  const healthStyle = HEALTH_STYLE[health] ?? HEALTH_STYLE.unknown;
  const isRegenerating = selectedId ? regenerating === selectedId : false;

  return (
    <section style={{ ...card, padding: 0, overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <SectionHeader
          title="Scrape Reports"
          subtitle="One report per completed scrape, with reviewer findings, tier-source stats, and the jobs produced by that run."
        />
        <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '.72rem', whiteSpace: 'nowrap' }}>{reports.length} reports</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '340px minmax(0, 1fr)', minHeight: 520 }}>
        <aside style={{ borderRight: '1px solid rgba(255,255,255,0.08)', overflow: 'hidden' }}>
          <div style={{ maxHeight: 520, overflow: 'auto' }}>
            {reports.length === 0 ? <div style={{ padding: 16, color: 'var(--text-muted)' }}>No scraper reports yet.</div> : null}
            {reports.map((report) => {
              const active = report.run_id === selectedId;
              const healthKey = (report.review_health || report.review?.health || 'unknown') as ReviewHealth;
              const style = HEALTH_STYLE[healthKey] ?? HEALTH_STYLE.unknown;
              return (
                <button
                  key={report.run_id}
                  type="button"
                  onClick={() => onSelect(report.run_id)}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    border: 0,
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                    background: active ? 'rgba(96,165,250,0.14)' : 'transparent',
                    color: 'var(--text-primary)',
                    padding: '13px 14px',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                    <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{report.run_id.slice(0, 12)}</strong>
                    <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{runDuration(report.started_at, report.completed_at, report.elapsed)}</span>
                  </div>
                  <div style={{ marginTop: 5, color: 'var(--text-secondary)', fontSize: 12 }}>
                    {report.completed_at ? fmtDate(report.completed_at) : fmtDate(report.started_at)}
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 9, flexWrap: 'wrap', fontFamily: 'var(--font-mono)', fontSize: '.7rem' }}>
                    <span style={{ color: style.text }}>{style.label}</span>
                    <span style={{ color: 'rgb(134, 239, 172)' }}>{report.summary?.net_new ?? 0} net</span>
                    <span style={{ color: 'var(--text-muted)' }}>{report.summary?.jobs ?? 0} jobs</span>
                    <span style={{ color: 'var(--text-muted)' }}>{report.source_count} sources</span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        <main style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: 16, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 18 }}>{detail ? `Run ${detail.run_id}` : 'Select a Report'}</h2>
                <div style={{ color: 'var(--text-muted)', marginTop: 5, fontSize: 12 }}>
                  {loading ? 'Loading report...' : detail ? `${detail.trigger_source || 'scheduled'} · ${detail.gate_mode || 'no gate'} · ${runDuration(detail.started_at, detail.completed_at, detail.elapsed)}` : '--'}
                </div>
              </div>
              {detail ? (
                <button
                  style={{ ...btn, minWidth: 110 }}
                  onClick={() => onRegenerate(detail.run_id)}
                  disabled={isRegenerating}
                >
                  {isRegenerating ? 'Regenerating...' : 'Regenerate'}
                </button>
              ) : null}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 10, marginTop: 16 }}>
              <MiniMetric label="Raw" value={selectedSummary.raw ?? 0} />
              <MiniMetric label="Dedup" value={selectedSummary.dedup ?? 0} />
              <MiniMetric label="Filtered" value={selectedSummary.filtered ?? 0} />
              <MiniMetric label="Net New" value={selectedSummary.net_new ?? 0} tone="rgb(134, 239, 172)" />
              <MiniMetric label="Accepted" value={selectedSummary.accepted ?? 0} />
              <MiniMetric label="Rejected" value={selectedSummary.rejected ?? 0} tone="rgb(252, 165, 165)" />
            </div>
          </div>

          <div style={{ padding: 16, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: healthStyle.dot }} />
              <strong style={{ color: healthStyle.text }}>{healthStyle.label}</strong>
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                Reviewed {detail?.llm_review_at ? fmtDate(detail.llm_review_at) : '--'}
              </span>
            </div>
            <p style={{ margin: '8px 0 0', color: review?.summary ? 'var(--text-primary)' : 'var(--text-muted)', lineHeight: 1.5, fontSize: 13 }}>
              {review?.summary || 'No reviewer summary has been generated for this scrape yet.'}
            </p>
            {review?.flags?.length ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                {review.flags.map((flag) => (
                  <span key={flag} style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4, background: 'rgba(239,68,68,0.12)', color: 'rgb(252,165,165)', fontFamily: 'var(--font-mono)' }}>{flag}</span>
                ))}
              </div>
            ) : null}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, .55fr) minmax(0, 1fr)', minHeight: 260 }}>
            <section style={{ padding: 16, borderRight: '1px solid rgba(255,255,255,0.08)', overflow: 'auto' }}>
              <SectionHeader title="Source Stats" />
              {!detail?.tier_stats?.length ? <Empty>No tier-source stats captured.</Empty> : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
                      <th style={th}>Source</th>
                      <th style={{ ...th, textAlign: 'right' }}>Raw</th>
                      <th style={{ ...th, textAlign: 'right' }}>Stored</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.tier_stats.map((row) => (
                      <tr key={`${row.tier}-${row.source}`} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={td}>
                          <div style={{ fontFamily: 'var(--font-mono)' }}>{row.source}</div>
                          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>{row.tier}</div>
                        </td>
                        <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{row.raw_hits}</td>
                        <td style={{ ...td, textAlign: 'right', color: 'rgb(134,239,172)', fontVariantNumeric: 'tabular-nums' }}>{row.stored_pending + row.stored_lead}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section style={{ minWidth: 0, overflow: 'hidden' }}>
              <div style={{ padding: 16, borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <SectionHeader title="Jobs From This Scrape" />
                <select
                  value={statusFilter}
                  onChange={(e) => onStatusFilter(e.target.value)}
                  style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', fontSize: 12 }}
                >
                  <option value="all">All statuses</option>
                  {statusOptions.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </div>
              <div style={{ overflow: 'auto', maxHeight: 360 }}>
                {!detail ? <Empty>Select a report to see its jobs.</Empty> : null}
                {detail && filteredJobs.length === 0 ? <div style={{ padding: 16, color: 'var(--text-muted)' }}>No jobs match this status.</div> : null}
                {filteredJobs.map((job) => (
                  <div key={job.id} style={{ padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 650, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.title || `Job #${job.id}`}</div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 3 }}>{job.company || 'Unknown'} · {job.board || job.source || '--'}</div>
                      </div>
                      <span style={{ color: job.status === 'rejected' ? 'rgb(252,165,165)' : 'rgb(134,239,172)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{job.status}</span>
                    </div>
                    {job.rejection_reason ? <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 6 }}>{job.rejection_stage}: {job.rejection_reason}</div> : null}
                    {job.url ? <a href={job.url} target="_blank" rel="noreferrer" style={{ color: 'rgb(147,197,253)', fontSize: 12, marginTop: 6, display: 'inline-block' }}>Open JD</a> : null}
                  </div>
                ))}
              </div>
            </section>
          </div>
        </main>
      </div>
    </section>
  );
}

function MiniMetric({ label, value, tone = 'var(--text-primary)' }: { label: string; value: number | string; tone?: string }) {
  return (
    <div style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '10px 12px', background: 'rgba(255,255,255,0.025)' }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0, fontFamily: 'var(--font-mono)' }}>{label}</div>
      <div style={{ color: tone, fontSize: 20, fontWeight: 650, marginTop: 4 }}>{value}</div>
    </div>
  );
}

const REVIEWER_EXPLAINER =
  'When a scheduled run completes, a background loop (60s poll, max 5 reviews/tick) sends the run\u2019s raw/dedup/filter/net-new counts, per-spider tier stats, and the last 7 runs as baseline to the MLX gate model (Meta-Llama-3.1-8B-Instruct-4bit, qwen2.5:7b fallback). The model returns health, summary, flags, and recommendations as JSON. If the LLM is unreachable the review stays empty and is retried on the next tick \u2014 no fake summaries. Regenerate forces a fresh call for a specific run.';

const HEALTH_STYLE: Record<ReviewHealth, { dot: string; label: string; text: string }> = {
  green: { dot: 'rgb(34, 197, 94)', label: 'Healthy', text: 'rgb(134, 239, 172)' },
  yellow: { dot: 'rgb(234, 179, 8)', label: 'Watch', text: 'rgb(252, 211, 77)' },
  red: { dot: 'rgb(239, 68, 68)', label: 'Degraded', text: 'rgb(252, 165, 165)' },
  unknown: { dot: 'rgba(148, 163, 184, 0.8)', label: 'Unknown', text: 'var(--text-muted)' },
};

function LatestReviewPanel({
  reviews,
  onRegenerate,
  regenerating,
}: {
  reviews: ReviewedRun[];
  onRegenerate: (runId: string) => void;
  regenerating: string | null;
}) {
  const latest = reviews[0];
  if (!latest) {
    return (
      <section style={card}>
        <SectionHeader
          title="Run oversight"
          subtitle={REVIEWER_EXPLAINER}
        />
        <Empty>No completed runs reviewed yet.</Empty>
      </section>
    );
  }
  const review = latest.review;
  const health: ReviewHealth = (review?.health as ReviewHealth) ?? 'unknown';
  const style = HEALTH_STYLE[health] ?? HEALTH_STYLE.unknown;
  const pending = !review;
  const isRegenerating = regenerating === latest.run_id;
  return (
    <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 10px',
                borderRadius: 999,
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.08)',
                fontSize: 12,
                color: style.text,
                fontWeight: 600,
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: style.dot }} />
              {style.label}
            </span>
            <h2 style={{ fontSize: 15, margin: 0, fontWeight: 600 }}>Run oversight</h2>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {fmtDate(latest.started_at)} · net-new {latest.net_new ?? '—'} · gate {latest.gate_mode ?? '—'}
            </span>
          </div>
          <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.55 }}>
            {REVIEWER_EXPLAINER}
          </p>
          <p style={{ margin: '10px 0 0', fontSize: 13, lineHeight: 1.55, color: pending ? 'var(--text-muted)' : 'var(--text-primary)' }}>
            {pending
              ? 'Awaiting review. Background reviewer will retry on its next 60s tick. If MLX is down or the primary model is unavailable, the reviewer falls back to qwen2.5:7b via Ollama.'
              : review?.summary || '(No summary provided.)'}
          </p>
        </div>
        <button
          style={{ ...btn, minWidth: 110 }}
          onClick={() => onRegenerate(latest.run_id)}
          disabled={isRegenerating}
          title="Clear this run's review and force the background reviewer to re-generate it on the next poll tick."
        >
          {isRegenerating ? 'Regenerating…' : 'Regenerate'}
        </button>
      </div>

      {review?.flags && review.flags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
          {review.flags.map((f, i) => (
            <span
              key={i}
              style={{
                fontSize: 11,
                padding: '3px 9px',
                borderRadius: 4,
                background: 'rgba(239, 68, 68, 0.12)',
                color: 'rgb(252, 165, 165)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {f}
            </span>
          ))}
        </div>
      )}

      {review?.recommendations && review.recommendations.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0, color: 'var(--text-muted)', marginBottom: 6 }}>
            Recommendations
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.55 }}>
            {review.recommendations.map((r, i) => (
              <li key={i} style={{ marginBottom: 3 }}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {latest.llm_review_at && (
        <div style={{ marginTop: 14, fontSize: 11, color: 'var(--text-muted)' }}>
          Reviewed {fmtDate(latest.llm_review_at)} · run {latest.run_id.slice(0, 12)}
        </div>
      )}
    </section>
  );
}

function computeKpis(stats: TierStats | null, target: number) {
  const last = stats?.per_run[0];
  const lastNetNew = last?.net_new ?? null;
  const lastQaPending = last?.net_new_qa_pending ?? 0;
  const lastLead = last?.net_new_lead ?? 0;
  const dayCount = stats?.daily_net_new.length ?? 0;
  const totalNetNew = stats?.daily_net_new.reduce((acc, d) => acc + (d.net_new ?? 0), 0) ?? null;
  const totalQaPending = stats?.daily_net_new.reduce((acc, d) => acc + d.net_new_qa_pending, 0) ?? 0;
  const totalLead = stats?.daily_net_new.reduce((acc, d) => acc + d.net_new_lead, 0) ?? 0;
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
  return {
    lastNetNew, lastQaPending, lastLead,
    totalNetNew, totalQaPending, totalLead,
    rotationSeen, overflow, gateTotal, windowTarget, dayCount,
  };
}

function DailyChart({ data, target }: { data: DayRow[]; target: number }) {
  if (data.length === 0) return <Empty>No runs in this window.</Empty>;
  const totals = data.map((d) => d.net_new ?? 0);
  const max = Math.max(target * 1.2, ...totals, 1);
  const width = 100 / data.length;
  const QA_COLOR = 'rgba(245,158,11,0.85)';
  const LEAD_COLOR = 'rgba(96,165,250,0.7)';
  const OTHER_COLOR = 'rgba(148,163,184,0.45)';
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
          const total = d.net_new ?? 0;
          const qa = d.net_new_qa_pending;
          const lead = d.net_new_lead;
          const other = Math.max(0, total - qa - lead);
          const x = i * width + width * 0.15;
          const barW = width * 0.7;
          const qaH = (qa / max) * 100;
          const leadH = (lead / max) * 100;
          const otherH = (other / max) * 100;
          let y = 100 - qaH;
          const segs: React.ReactNode[] = [];
          if (qa > 0) {
            segs.push(<rect key="qa" x={x} y={y} width={barW} height={qaH} fill={QA_COLOR} rx="0.5" />);
          }
          if (lead > 0) {
            const ly = y - leadH;
            segs.push(<rect key="lead" x={x} y={ly} width={barW} height={leadH} fill={LEAD_COLOR} rx="0.5" />);
            y = ly;
          }
          if (other > 0) {
            const oy = y - otherH;
            segs.push(<rect key="other" x={x} y={oy} width={barW} height={otherH} fill={OTHER_COLOR} rx="0.5" />);
          }
          return (
            <g key={d.day}>
              <title>{`${d.day} · ${total} total · ${qa} qa_pending · ${lead} lead${other ? ` · ${other} other` : ''}`}</title>
              {segs}
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
      <ChartLegend qaColor={QA_COLOR} leadColor={LEAD_COLOR} />
    </div>
  );
}

function ChartLegend({ qaColor, leadColor }: { qaColor: string; leadColor: string }) {
  const swatch = (c: string): React.CSSProperties => ({
    display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: c, marginRight: 6,
  });
  return (
    <div style={{ display: 'flex', gap: 14, marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
      <span><span style={swatch(qaColor)} />qa_pending — needs QA approval</span>
      <span><span style={swatch(leadColor)} />lead — hn_hiring / remoteok</span>
      <span style={{ marginLeft: 'auto' }}>Dashed line = total target</span>
    </div>
  );
}

function RunStrip({ rows, target }: { rows: RunRow[]; target: number }) {
  if (rows.length === 0) return <Empty>No runs yet.</Empty>;
  const reversed = [...rows].reverse();
  const values = reversed.map((r) => r.net_new ?? 0);
  const max = Math.max(target * 1.2, ...values, 1);
  const QA_COLOR = 'rgba(245,158,11,0.85)';
  const LEAD_COLOR = 'rgba(96,165,250,0.7)';
  const OTHER_COLOR = 'rgba(148,163,184,0.45)';
  return (
    <div style={{ height: 180, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', flex: 1, gap: 3 }}>
        {reversed.map((r) => {
          if (r.net_new == null) {
            return (
              <div
                key={r.run_id}
                title={`${fmtDate(r.started_at)} · net-new=n/a · gate=${r.gate_mode ?? 'n/a'} · group=${r.rotation_group ?? 'n/a'}`}
                style={{ flex: 1, height: '20%', background: 'rgba(255,255,255,0.08)', borderRadius: 2, minHeight: 2 }}
              />
            );
          }
          const total = r.net_new;
          const qa = r.net_new_qa_pending;
          const lead = r.net_new_lead;
          const other = Math.max(0, total - qa - lead);
          const h = (total / max) * 100;
          const title = `${fmtDate(r.started_at)} · net-new=${total} (qa=${qa}, lead=${lead}${other ? `, other=${other}` : ''}) · gate=${r.gate_mode ?? 'n/a'} · group=${r.rotation_group ?? 'n/a'}`;
          const outline =
            r.gate_mode === 'overflow'
              ? '1px solid rgba(245,158,11,0.9)'
              : r.gate_mode === 'normal'
              ? '1px solid rgba(34,197,94,0.7)'
              : 'none';
          return (
            <div
              key={r.run_id}
              title={title}
              style={{
                flex: 1,
                height: `${h}%`,
                minHeight: 4,
                display: 'flex',
                flexDirection: 'column-reverse',
                borderRadius: 2,
                overflow: 'hidden',
                outline,
                outlineOffset: -1,
              }}
            >
              {qa > 0 && <div style={{ flex: qa, background: QA_COLOR }} />}
              {lead > 0 && <div style={{ flex: lead, background: LEAD_COLOR }} />}
              {other > 0 && <div style={{ flex: other, background: OTHER_COLOR }} />}
            </div>
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
        <tr style={{ textAlign: 'left', color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0 }}>
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

function KpiTile({ label, value, unit, tone, footer }: { label: string; value: string; unit?: string; tone: 'good' | 'warn' | 'bad' | 'muted'; footer?: React.ReactNode }) {
  const accent: Record<string, string> = {
    good: 'rgb(134, 239, 172)',
    warn: 'rgb(252, 211, 77)',
    bad: 'rgb(252, 165, 165)',
    muted: 'var(--text-muted)',
  };
  return (
    <div style={{ ...card, padding: 16 }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ marginTop: 6, display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <div style={{ fontSize: 28, fontWeight: 600, color: accent[tone], fontVariantNumeric: 'tabular-nums' }}>{value}</div>
        {unit && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{unit}</div>}
      </div>
      {footer && <div style={{ marginTop: 6 }}>{footer}</div>}
    </div>
  );
}

function StatusSplit({ qa, lead }: { qa: number; lead: number }) {
  if (qa === 0 && lead === 0) {
    return <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>no items stored</span>;
  }
  return (
    <div style={{ display: 'flex', gap: 10, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
      {qa > 0 && (
        <span title="Items that reached storage as qa_pending — they still need QA approval (manual or LLM-review) before they can be tailored.">
          <span style={{ color: 'rgb(252, 211, 77)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{qa}</span>{' '}
          <span>need QA</span>
        </span>
      )}
      {lead > 0 && (
        <span title="Lead-tier items from hn_hiring / remoteok — lowest confidence, separate manual flow.">
          <span style={{ color: 'rgb(147, 197, 253)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{lead}</span>{' '}
          <span>lead</span>
        </span>
      )}
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
