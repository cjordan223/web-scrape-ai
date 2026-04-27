import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Activity, ArrowUpRight, Brain, Briefcase, CheckSquare, ClipboardCheck, ClipboardPaste,
  Cpu, Database, FileCheck, Gauge, GitBranch, Library, Package, Play, RefreshCcw,
  Search, Square, Terminal, XCircle,
} from 'lucide-react';
import { api } from '../../../../api';
import { fmt, timeAgo } from '../../../../utils';
import '../../../../styles/pipeline-editor.css';

// ─── Types ──────────────────────────────────────────────────────────
interface Inventory {
  total: number;
  qa_pending: number;
  qa_approved: number;
  qa_rejected: number;
  rejected: number;
}

interface PipelineStats {
  run_id: string | null;
  started_at: string | null;
  raw_count: number;
  dedup_dropped: number;
  filter_rejected: number;
  stored: number;
  per_source: Record<string, number>;
  per_rejection: Record<string, number>;
  inventory: Inventory;
}

interface QAReviewSummary {
  total: number;
  queued: number;
  reviewing: number;
  completed: number;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
}

interface QAStatus {
  running: boolean;
  resolved_model: string | null;
  summary: QAReviewSummary;
}

interface Live {
  scrapeRunning: boolean;
  scrapeStartedAt: string | null;
  scrapeLogTail: string;
  qaRunning: boolean;
  qaModel: string | null;
  qaProgress: { completed: number; total: number } | null;
  qaPassed: number;
  qaFailed: number;
  tailorRunning: boolean;
  tailorJob: string | null;
  tailorQueue: number;
  tailorLogTail: string;
}

type Tone = 'accent' | 'green' | 'red' | 'amber' | 'cyan' | 'orange' | 'violet' | 'muted';

interface Event {
  id: string;
  label: string;
  detail?: string;
  tone: Tone;
  ts: number;
}

const INITIAL_LIVE: Live = {
  scrapeRunning: false, scrapeStartedAt: null, scrapeLogTail: '',
  qaRunning: false, qaModel: null, qaProgress: null, qaPassed: 0, qaFailed: 0,
  tailorRunning: false, tailorJob: null, tailorQueue: 0, tailorLogTail: '',
};

// ─── Helpers ─────────────────────────────────────────────────────────
function buildLive(scrape: any, qa: any, tailor: any): Live {
  return {
    scrapeRunning: scrape?.running ?? false,
    scrapeStartedAt: scrape?.started_at ?? null,
    scrapeLogTail: scrape?.log_tail ?? '',
    qaRunning: qa?.running ?? false,
    qaModel: qa?.resolved_model ?? null,
    qaProgress: qa?.summary ? { completed: qa.summary.completed, total: qa.summary.total } : null,
    qaPassed: qa?.summary?.passed ?? 0,
    qaFailed: qa?.summary?.failed ?? 0,
    tailorRunning: tailor?.running ?? false,
    tailorJob: tailor?.job?.title ?? tailor?.active_item?.title ?? null,
    tailorQueue: tailor?.queue?.length ?? 0,
    tailorLogTail: tailor?.log_tail ?? '',
  };
}

function diffEvents(prev: { live: Live; stats: PipelineStats | null } | null,
                    next: { live: Live; stats: PipelineStats | null }): Event[] {
  if (!prev) return [];
  const out: Event[] = [];
  const ts = Date.now();
  const push = (label: string, detail: string | undefined, tone: Tone) =>
    out.push({ id: `${label}-${ts}-${out.length}`, label, detail, tone, ts });

  if (prev.live.scrapeRunning !== next.live.scrapeRunning) {
    push(next.live.scrapeRunning ? 'Discover lane started' : 'Discover lane stopped',
      next.live.scrapeRunning ? 'Scraper sweeping sources' : 'Awaiting next sweep',
      next.live.scrapeRunning ? 'accent' : 'muted');
  }
  if (prev.live.qaRunning !== next.live.qaRunning) {
    push(next.live.qaRunning ? 'Review batch started' : 'Review batch stopped',
      next.live.qaRunning ? `Model: ${next.live.qaModel ?? 'unknown'}` : 'Review queue paused',
      next.live.qaRunning ? 'cyan' : 'muted');
  }
  if (prev.live.tailorRunning !== next.live.tailorRunning) {
    push(next.live.tailorRunning ? 'Tailor lane started' : 'Tailor lane stopped',
      next.live.tailorRunning ? (next.live.tailorJob || 'Generating package') : 'Lane idle',
      next.live.tailorRunning ? 'orange' : 'muted');
  }
  if (prev.live.tailorQueue !== next.live.tailorQueue) {
    const delta = next.live.tailorQueue - prev.live.tailorQueue;
    push(`Tailor queue ${delta > 0 ? '+' : ''}${delta}`,
      `${fmt(next.live.tailorQueue)} packages awaiting`, delta > 0 ? 'amber' : 'muted');
  }
  const pi = prev.stats?.inventory, ni = next.stats?.inventory;
  if (pi && ni) {
    if (ni.qa_approved > pi.qa_approved) push(`Approved +${ni.qa_approved - pi.qa_approved}`, `${fmt(ni.qa_approved)} ready to tailor`, 'green');
    if (ni.qa_rejected > pi.qa_rejected) push(`Rejected +${ni.qa_rejected - pi.qa_rejected}`, `${fmt(ni.qa_rejected)} dropped at review`, 'red');
    if (ni.total > pi.total)             push(`Stored +${ni.total - pi.total}`,        `${fmt(ni.total)} jobs in inventory`, 'green');
  }
  return out;
}

function timeSince(ts: number) {
  return timeAgo(new Date(ts).toISOString());
}

// ─── Phase definition ────────────────────────────────────────────────
type PhaseKey = 'discover' | 'inventory' | 'review' | 'tailor' | 'apply';

interface PhaseSpec {
  key: PhaseKey;
  number: string;
  name: string;
  caption: string;
  accent: string;
  laneTo: string;
  laneLabel: string;
}

const PHASES: PhaseSpec[] = [
  { key: 'discover',  number: '01', name: 'Discover',  caption: 'Scrape boards & search engines',  accent: 'var(--accent)', laneTo: '/ops/scraper',      laneLabel: 'Scraper config' },
  { key: 'inventory', number: '02', name: 'Inventory', caption: 'Persist & dedupe to SQLite',       accent: 'var(--violet, var(--purple))', laneTo: '/ops/inventory',  laneLabel: 'Browse inventory' },
  { key: 'review',    number: '03', name: 'Review',    caption: 'Automated fit triage',             accent: 'var(--cyan)',   laneTo: '/ops/qa',          laneLabel: 'Open QA' },
  { key: 'tailor',    number: '04', name: 'Tailor',    caption: 'Generate resume & cover packages', accent: 'var(--orange)', laneTo: '/pipeline/ready',  laneLabel: 'Ready queue' },
  { key: 'apply',     number: '05', name: 'Apply',     caption: 'Track outbound applications',      accent: 'var(--green)',  laneTo: '/pipeline/applied',laneLabel: 'Applied tracker' },
];

// ─── Workflow shortcuts ──────────────────────────────────────────────
interface Shortcut { to: string; label: string; desc: string; icon: any; group: 'pipeline' | 'ops'; }
const SHORTCUTS: Shortcut[] = [
  { to: '/pipeline/ingest',  label: 'Ingest',     desc: 'Manual JD paste / fetch',  icon: ClipboardPaste, group: 'pipeline' },
  { to: '/ops/qa',           label: 'QA',         desc: 'Automated fit review',     icon: CheckSquare,    group: 'ops' },
  { to: '/pipeline/ready',   label: 'Ready',      desc: 'Approved backlog',         icon: Briefcase,      group: 'pipeline' },
  { to: '/pipeline/packages',label: 'Packages',   desc: 'Tailoring outputs',        icon: Package,        group: 'pipeline' },
  { to: '/pipeline/applied', label: 'Applied',    desc: 'Submission tracker',       icon: FileCheck,      group: 'pipeline' },
  { to: '/ops/inventory',    label: 'Inventory',  desc: 'All stored jobs',          icon: Database,       group: 'ops' },
  { to: '/ops/rejected/qa',  label: 'QA Rejects', desc: 'LLM-failed bucket',        icon: XCircle,        group: 'ops' },
  { to: '/ops/traces',       label: 'Traces',     desc: 'Tailoring LLM trace',      icon: GitBranch,      group: 'ops' },
  { to: '/ops/llm',          label: 'LLM',        desc: 'Providers · models · keys',icon: Cpu,            group: 'ops' },
  { to: '/ops/metrics',      label: 'Metrics',    desc: 'Tailoring perf',           icon: Gauge,          group: 'ops' },
  { to: '/ops/scraper',      label: 'Scraper',    desc: 'Tier health · freshness',  icon: Activity,       group: 'ops' },
  { to: '/ops/qa-reports',   label: 'QA Reports', desc: 'Review audit trail',       icon: ClipboardCheck, group: 'ops' },
  { to: '/ops/persona',      label: 'Persona',    desc: 'Voice · vignettes · soul', icon: Library,        group: 'ops' },
  { to: '/ops/system',       label: 'System',     desc: 'Scheduler · runtime',      icon: Gauge,          group: 'ops' },
  { to: '/ops/admin',        label: 'Admin',      desc: 'SQL · bulk ops',           icon: Terminal,       group: 'ops' },
];

// ─── Subcomponents ───────────────────────────────────────────────────
function StatusDot({ on, color }: { on: boolean; color: string }) {
  return <span className={`pc-dot${on ? ' is-live' : ''}`} style={{ ['--dot' as any]: color }} />;
}

function PhaseCard({ phase, live, stats, isLast }: {
  phase: PhaseSpec;
  live: Live;
  stats: PipelineStats | null;
  isLast: boolean;
}) {
  const navigate = useNavigate();
  const inv = stats?.inventory;

  let primary: { value: string; sub: string };
  let running = false;
  let secondary: string;

  switch (phase.key) {
    case 'discover':
      running = live.scrapeRunning;
      primary = { value: fmt(stats?.raw_count ?? 0), sub: 'pulled · last run' };
      secondary = running && live.scrapeStartedAt ? `running · ${timeAgo(live.scrapeStartedAt)}` : 'idle';
      break;
    case 'inventory':
      primary = { value: fmt(inv?.total ?? 0), sub: 'total stored' };
      secondary = `${fmt(inv?.qa_pending ?? 0)} awaiting review`;
      break;
    case 'review':
      running = live.qaRunning;
      primary = { value: fmt(inv?.qa_pending ?? 0), sub: 'pending review' };
      secondary = running && live.qaProgress
        ? `reviewing · ${live.qaProgress.completed}/${live.qaProgress.total}`
        : `${fmt(inv?.qa_approved ?? 0)} approved · ${fmt(inv?.qa_rejected ?? 0)} rejected`;
      break;
    case 'tailor':
      running = live.tailorRunning;
      primary = { value: fmt(live.tailorQueue), sub: 'in tailor queue' };
      secondary = running ? (live.tailorJob || 'generating') : `${fmt(inv?.qa_approved ?? 0)} ready`;
      break;
    case 'apply':
      primary = { value: '—', sub: 'tracked applications' };
      secondary = 'see applied tracker';
      break;
  }

  return (
    <div
      className={`pc-phase${running ? ' is-running' : ''}`}
      style={{ ['--phase' as any]: phase.accent }}
    >
      <div className="pc-phase-rail" />
      <div className="pc-phase-head">
        <span className="pc-phase-number">{phase.number}</span>
        <StatusDot on={running} color={phase.accent} />
      </div>
      <div className="pc-phase-name">{phase.name}</div>
      <div className="pc-phase-caption">{phase.caption}</div>

      <div className="pc-phase-metric">
        <span className="pc-phase-metric-value">{primary.value}</span>
        <span className="pc-phase-metric-sub">{primary.sub}</span>
      </div>

      <div className="pc-phase-state">{secondary}</div>

      <button
        type="button"
        className="pc-phase-lane"
        onClick={() => navigate(phase.laneTo)}
      >
        <span>{phase.laneLabel}</span>
        <ArrowUpRight size={12} />
      </button>

      {!isLast && <div className="pc-phase-connector" aria-hidden />}
    </div>
  );
}

function Funnel({ inv }: { inv: Inventory | undefined }) {
  if (!inv) return <div className="pc-empty">No inventory yet</div>;
  const total = Math.max(inv.total, 1);
  const rows: { label: string; value: number; color: string }[] = [
    { label: 'Total stored',     value: inv.total,        color: 'var(--text)' },
    { label: 'Pending review',   value: inv.qa_pending,   color: 'var(--amber)' },
    { label: 'Approved',         value: inv.qa_approved,  color: 'var(--green)' },
    { label: 'QA rejected',      value: inv.qa_rejected,  color: 'var(--red)' },
    { label: 'Scraper rejected', value: inv.rejected,     color: 'var(--text-secondary)' },
  ];
  return (
    <div className="pc-funnel">
      {rows.map((r) => {
        const pct = (r.value / total) * 100;
        return (
          <div className="pc-funnel-row" key={r.label}>
            <div className="pc-funnel-row-head">
              <span>{r.label}</span>
              <span className="pc-mono">{fmt(r.value)}<span className="pc-funnel-pct">{pct.toFixed(0)}%</span></span>
            </div>
            <div className="pc-funnel-track"><div className="pc-funnel-fill" style={{ width: `${Math.min(pct, 100)}%`, background: r.color }} /></div>
          </div>
        );
      })}
    </div>
  );
}

function Feed({ events }: { events: Event[] }) {
  if (events.length === 0) {
    return (
      <div className="pc-empty">
        <Activity size={14} /> <span>No activity recorded yet</span>
      </div>
    );
  }
  return (
    <div className="pc-feed">
      {events.map((e) => (
        <div key={e.id} className={`pc-feed-row pc-tone-${e.tone}`}>
          <span className="pc-feed-stripe" />
          <div className="pc-feed-body">
            <div className="pc-feed-head">
              <span className="pc-feed-label">{e.label}</span>
              <span className="pc-feed-time pc-mono">{timeSince(e.ts)}</span>
            </div>
            {e.detail && <div className="pc-feed-detail">{e.detail}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

function LogPanel({ title, color, content, meta }: { title: string; color: string; content: string; meta?: string }) {
  return (
    <div className="pc-log-panel">
      <div className="pc-log-head" style={{ ['--phase' as any]: color }}>
        <span className="pc-log-rail" />
        <span className="pc-log-title">{title}</span>
        {meta && <span className="pc-log-meta pc-mono">{meta}</span>}
      </div>
      <pre className="pc-log-body">{content || '— waiting for output —'}</pre>
    </div>
  );
}

function ShortcutCard({ s }: { s: Shortcut }) {
  const Icon = s.icon;
  return (
    <Link to={s.to} className={`pc-short pc-short-${s.group}`}>
      <span className="pc-short-icon"><Icon size={14} /></span>
      <span className="pc-short-text">
        <span className="pc-short-label">{s.label}</span>
        <span className="pc-short-desc">{s.desc}</span>
      </span>
      <ArrowUpRight size={11} className="pc-short-chev" />
    </Link>
  );
}

// ─── Main ────────────────────────────────────────────────────────────
export default function PipelineEditorView() {
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [qaStatus, setQaStatus] = useState<QAStatus | null>(null);
  const [live, setLive] = useState<Live>(INITIAL_LIVE);
  const [events, setEvents] = useState<Event[]>([]);
  const [activeRun, setActiveRun] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const snapshotRef = useRef<{ live: Live; stats: PipelineStats | null } | null>(null);

  const refresh = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const [nextStats, scrape, qa, tailor, run] = await Promise.all([
        api.getScraperPipelineStats().catch(() => null),
        api.getScrapeRunnerStatus().catch(() => null),
        api.getQALlmReviewStatus().catch(() => null),
        api.getTailoringRunnerStatus().catch(() => null),
        api.getActiveRun().catch(() => null),
      ]);
      const nextLive = buildLive(scrape, qa, tailor);
      const fresh = diffEvents(snapshotRef.current, { live: nextLive, stats: nextStats });
      if (fresh.length) setEvents((prev) => [...fresh.reverse(), ...prev].slice(0, 30));
      setStats(nextStats);
      setQaStatus(qa);
      setLive(nextLive);
      setActiveRun(run);
      setLastUpdated(Date.now());
      snapshotRef.current = { live: nextLive, stats: nextStats };
    } catch (e: any) {
      if (manual) setError(e?.message || String(e));
    } finally {
      if (manual) setRefreshing(false);
    }
  }, []);

  useEffect(() => { void refresh(false); }, [refresh]);
  useEffect(() => {
    const id = setInterval(() => { void refresh(false); }, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const handleRunScrape = useCallback(async () => {
    try { await api.runScrapeNow(true); void refresh(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refresh]);

  const handleStopScrape = useCallback(async () => {
    if (!activeRun?.run_id) return;
    try { await api.terminateRun(activeRun.run_id); void refresh(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [activeRun, refresh]);

  const handleRunQA = useCallback(async () => {
    try {
      const pending = await api.getQAPending();
      const ids = (pending.jobs || []).map((j: any) => j.id);
      if (!ids.length) return;
      await api.llmReviewQA(ids);
      void refresh(true);
    } catch (e: any) { setError(e?.message || String(e)); }
  }, [refresh]);

  const handleStopQA = useCallback(async () => {
    try { await api.cancelQAReview(); void refresh(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refresh]);

  const handleRunTailor = useCallback(async () => {
    try { await api.runTailoringLatest(); void refresh(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refresh]);

  const handleStopTailor = useCallback(async () => {
    try { await api.stopTailoringRunner({ clear_queue: true }); void refresh(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refresh]);

  const inv = stats?.inventory;
  const totalRunning = useMemo(() => Number(live.scrapeRunning) + Number(live.qaRunning) + Number(live.tailorRunning),
    [live]);
  const lastUpdatedLabel = lastUpdated ? timeAgo(new Date(lastUpdated).toISOString()) : 'never';

  return (
    <div className="pc-root">
      {/* ── Masthead ─────────────────────────────────────────── */}
      <header className="pc-mast">
        <div className="pc-mast-left">
          <div className="pc-eyebrow">
            <span className="pc-eyebrow-dot" />
            TXT · ORCHESTRATION · CONSOLE
          </div>
          <h1 className="pc-title">Pipeline Console</h1>
          <p className="pc-subtitle">
            Live state of every connected workflow — discover, inventory, review, tailor, apply.
          </p>
        </div>
        <div className="pc-mast-right">
          <div className="pc-mast-stat">
            <span className="pc-mast-stat-num pc-mono">{totalRunning}</span>
            <span className="pc-mast-stat-cap">lanes active</span>
          </div>
          <div className="pc-mast-stat">
            <span className="pc-mast-stat-num pc-mono">{fmt(inv?.total ?? 0)}</span>
            <span className="pc-mast-stat-cap">jobs in inventory</span>
          </div>
          <div className="pc-mast-stat">
            <span className="pc-mast-stat-num pc-mono">{fmt(inv?.qa_pending ?? 0)}</span>
            <span className="pc-mast-stat-cap">awaiting review</span>
          </div>
          <button
            className="pc-mast-refresh"
            onClick={() => { void refresh(true); }}
            disabled={refreshing}
            title={`Last updated ${lastUpdatedLabel}`}
          >
            <RefreshCcw size={13} className={refreshing ? 'is-spinning' : ''} />
            <span>{lastUpdatedLabel}</span>
          </button>
        </div>
      </header>

      {error && <div className="pc-error" onClick={() => setError(null)}>{error}</div>}

      {/* ── Phase strip ─────────────────────────────────────── */}
      <section className="pc-section">
        <div className="pc-section-head">
          <span className="pc-section-marker">I.</span>
          <h2 className="pc-section-title">Pipeline phases</h2>
          <span className="pc-section-rule" />
          <span className="pc-section-meta">{PHASES.length} stages · click to drill in</span>
        </div>
        <div className="pc-phase-strip">
          {PHASES.map((p, i) => (
            <PhaseCard
              key={p.key}
              phase={p}
              live={live}
              stats={stats}
              isLast={i === PHASES.length - 1}
            />
          ))}
        </div>

        {/* ── Lane controls ──── */}
        <div className="pc-controls">
          <LaneControl
            label="Discover"
            color="var(--accent)"
            running={live.scrapeRunning}
            detail={live.scrapeRunning && live.scrapeStartedAt ? `running ${timeAgo(live.scrapeStartedAt)}` : 'sweep all sources'}
            onRun={handleRunScrape}
            onStop={handleStopScrape}
            stopDisabled={!activeRun?.run_id && !live.scrapeRunning}
          />
          <LaneControl
            label="Review"
            color="var(--cyan)"
            running={live.qaRunning}
            detail={live.qaRunning && live.qaProgress
              ? `${live.qaProgress.completed}/${live.qaProgress.total} · ${live.qaModel ?? 'llm'}`
              : `${fmt(inv?.qa_pending ?? 0)} pending · LLM fit review`}
            onRun={handleRunQA}
            onStop={handleStopQA}
          />
          <LaneControl
            label="Tailor"
            color="var(--orange)"
            running={live.tailorRunning}
            detail={live.tailorRunning
              ? (live.tailorJob || `queue · ${fmt(live.tailorQueue)}`)
              : `${fmt(inv?.qa_approved ?? 0)} approved · generate latest`}
            onRun={handleRunTailor}
            onStop={handleStopTailor}
          />
        </div>
      </section>

      {/* ── State + activity ────────────────────────────────── */}
      <section className="pc-section">
        <div className="pc-section-head">
          <span className="pc-section-marker">II.</span>
          <h2 className="pc-section-title">Inventory & telemetry</h2>
          <span className="pc-section-rule" />
        </div>
        <div className="pc-grid-2">
          <div className="pc-card">
            <div className="pc-card-head">
              <span className="pc-card-eyebrow">funnel</span>
              <h3 className="pc-card-title">Inventory composition</h3>
            </div>
            <Funnel inv={inv} />
          </div>
          <div className="pc-card">
            <div className="pc-card-head">
              <span className="pc-card-eyebrow">activity</span>
              <h3 className="pc-card-title">Recent pipeline events</h3>
              <span className="pc-card-meta pc-mono">{events.length}</span>
            </div>
            <Feed events={events.slice(0, 12)} />
          </div>
        </div>
      </section>

      {/* ── Live processes (only when something runs) ───────── */}
      {(live.scrapeRunning || live.tailorRunning || live.qaRunning) && (
        <section className="pc-section">
          <div className="pc-section-head">
            <span className="pc-section-marker">III.</span>
            <h2 className="pc-section-title">Live process feed</h2>
            <span className="pc-section-rule" />
            <span className="pc-section-meta">{totalRunning} running</span>
          </div>
          <div className="pc-grid-3">
            {live.scrapeRunning && (
              <LogPanel
                title="Discover · scrape"
                color="var(--accent)"
                meta={live.scrapeStartedAt ? timeAgo(live.scrapeStartedAt) : 'live'}
                content={live.scrapeLogTail}
              />
            )}
            {live.qaRunning && (
              <div className="pc-log-panel">
                <div className="pc-log-head" style={{ ['--phase' as any]: 'var(--cyan)' }}>
                  <span className="pc-log-rail" />
                  <span className="pc-log-title">Review · LLM fit</span>
                  {live.qaProgress && (
                    <span className="pc-log-meta pc-mono">{live.qaProgress.completed}/{live.qaProgress.total}</span>
                  )}
                </div>
                <div className="pc-qa-pills">
                  {qaStatus?.summary && qaStatus.summary.total > 0 && (
                    <>
                      <span className="pc-pill pc-pill-green">{qaStatus.summary.passed} pass</span>
                      <span className="pc-pill pc-pill-red">{qaStatus.summary.failed} fail</span>
                      {qaStatus.summary.skipped > 0 && <span className="pc-pill">{qaStatus.summary.skipped} skip</span>}
                      {qaStatus.summary.errors > 0 && <span className="pc-pill pc-pill-red">{qaStatus.summary.errors} err</span>}
                    </>
                  )}
                </div>
                {qaStatus?.resolved_model && (
                  <div className="pc-qa-model"><Brain size={11} /><span className="pc-mono">{qaStatus.resolved_model}</span></div>
                )}
                {live.qaProgress && (
                  <div className="pc-qa-bar">
                    <div className="pc-qa-bar-fill" style={{
                      width: `${(live.qaProgress.completed / Math.max(live.qaProgress.total, 1)) * 100}%`
                    }} />
                  </div>
                )}
              </div>
            )}
            {live.tailorRunning && (
              <LogPanel
                title="Tailor · generation"
                color="var(--orange)"
                meta={live.tailorJob ? `queue ${fmt(live.tailorQueue)}` : 'live'}
                content={live.tailorLogTail}
              />
            )}
          </div>
        </section>
      )}

      {/* ── Workflow shortcuts ─────────────────────────────── */}
      <section className="pc-section pc-section-final">
        <div className="pc-section-head">
          <span className="pc-section-marker">{(live.scrapeRunning || live.qaRunning || live.tailorRunning) ? 'IV.' : 'III.'}</span>
          <h2 className="pc-section-title">All workflows</h2>
          <span className="pc-section-rule" />
          <span className="pc-section-meta">{SHORTCUTS.length} routes</span>
        </div>
        <div className="pc-shorts">
          <div className="pc-shorts-group">
            <div className="pc-shorts-label">Pipeline</div>
            <div className="pc-shorts-grid">
              {SHORTCUTS.filter((s) => s.group === 'pipeline').map((s) => <ShortcutCard key={s.to} s={s} />)}
            </div>
          </div>
          <div className="pc-shorts-group">
            <div className="pc-shorts-label">Ops</div>
            <div className="pc-shorts-grid">
              {SHORTCUTS.filter((s) => s.group === 'ops').map((s) => <ShortcutCard key={s.to} s={s} />)}
            </div>
          </div>
        </div>
      </section>

      <footer className="pc-foot">
        <span className="pc-foot-mark"><Search size={11} /></span>
        <span className="pc-foot-text">TexTailor orchestration console · pipeline state polled every 4s</span>
      </footer>
    </div>
  );
}

function LaneControl({ label, color, running, detail, onRun, onStop, stopDisabled }: {
  label: string; color: string; running: boolean; detail: string;
  onRun: () => void; onStop: () => void; stopDisabled?: boolean;
}) {
  return (
    <div className={`pc-lane-ctl${running ? ' is-running' : ''}`} style={{ ['--phase' as any]: color }}>
      <span className="pc-lane-ctl-rail" />
      <div className="pc-lane-ctl-body">
        <div className="pc-lane-ctl-head">
          <StatusDot on={running} color={color} />
          <span className="pc-lane-ctl-label">{label}</span>
        </div>
        <div className="pc-lane-ctl-detail">{detail}</div>
      </div>
      {running ? (
        <button className="pc-btn pc-btn-stop" onClick={onStop} disabled={stopDisabled}>
          <Square size={11} /> Stop
        </button>
      ) : (
        <button className="pc-btn pc-btn-run" onClick={onRun}>
          <Play size={11} /> Run
        </button>
      )}
    </div>
  );
}
