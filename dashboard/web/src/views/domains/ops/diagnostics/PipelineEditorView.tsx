import { useEffect, useState, useCallback, useMemo, memo, useRef } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  BackgroundVariant,
  useReactFlow,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import '../../../../styles/pipeline-editor.css';
import { api } from '../../../../api';
import { fmt, timeAgo } from '../../../../utils';
import {
  Search, Globe, Database, Filter, Fingerprint, FileText,
  HardDrive, X, Briefcase, Shield, Activity, Plus, Brain,
  Microscope, Target, PenTool, Mail, ShieldCheck, Printer,
  Play, Square, RefreshCcw, Save, RotateCcw, ArrowRight,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────
interface BoardItem {
  url: string;
  board_type: string;
  company: string;
  enabled: boolean;
}

interface ScraperConfig {
  boards: BoardItem[];
  queries: { title_phrase: string; board_site: string; board: string; suffix: string }[];
  searxng: { enabled: boolean; url: string; timeout: number; engines: string; time_range: string; request_delay: number };
  usajobs: { enabled: boolean; keywords: string[]; series: string[]; agencies: string[]; days: number; remote: boolean };
  hard_filters: { domain_blocklist: string[]; title_blocklist: string[]; content_blocklist: string[]; min_salary_k: number; target_salary_k: number };
  filter: { title_keywords: string[]; title_role_words: string[]; require_remote: boolean; require_us_location: boolean; min_jd_chars: number; max_experience_years: number; score_accept_threshold: number; score_reject_threshold: number };
  seen_ttl_days: number;
  target_max_results: number;
  pipeline_order: string[];
  crawl: { enabled: boolean; request_delay: number; max_results_per_target: number };
}

interface QAReviewItem {
  job_id: number;
  title?: string;
  url?: string;
  status: string;
  reason?: string;
  confidence?: number;
  top_matches?: string[];
  gaps?: string[];
}

interface QALlmReviewStatus {
  running: boolean;
  started_at: string | null;
  resolved_model: string | null;
  items?: QAReviewItem[];
  summary: { total: number; queued: number; reviewing: number; completed: number; passed: number; failed: number; skipped: number; errors: number };
}

interface LiveStatus {
  scrapeRunning: boolean;
  scrapeStartedAt: string | null;
  scrapeLogTail: string;
  qaReviewRunning: boolean;
  qaReviewModel: string | null;
  qaReviewProgress: { completed: number; total: number } | null;
  qaReviewItems: QAReviewItem[];
  tailoringRunning: boolean;
  tailoringJob: string | null;
  tailoringQueue: number;
  tailoringLogTail: string;
}

interface PipelineStats {
  run_id: string | null;
  started_at: string | null;
  raw_count: number;
  dedup_dropped: number;
  filter_rejected: number;
  stored: number;
  error_count: number;
  per_source: Record<string, number>;
  per_rejection: Record<string, number>;
  inventory: { total: number; qa_pending: number; qa_approved: number; qa_rejected: number; rejected: number };
}

type EventTone = 'accent' | 'green' | 'red' | 'amber' | 'muted';
type EventScope = 'scrape' | 'inventory' | 'qa' | 'tailor';

interface PipelineEvent {
  id: string;
  label: string;
  detail?: string;
  tone: EventTone;
  scope: EventScope;
  createdAt: number;
}

interface SourceRollupStats {
  searxng: number;
  ashby: number;
  greenhouse: number;
  lever: number;
  usajobs: number;
}

// ─── Static definitions ──────────────────────────────────────────────
const SOURCE_DEFS = [
  { id: 'searxng',    label: 'SearXNG',    icon: Search,    countLabel: 'queries' },
  { id: 'ashby',      label: 'Ashby',      icon: Briefcase, countLabel: 'boards' },
  { id: 'greenhouse', label: 'Greenhouse', icon: Globe,     countLabel: 'boards' },
  { id: 'lever',      label: 'Lever',      icon: Activity,  countLabel: 'boards' },
  { id: 'usajobs',    label: 'USAJobs',    icon: Shield,    countLabel: 'keywords' },
];

const STAGE_DEFS = [
  { id: 'text_extraction', label: 'Text Extract', desc: 'Parse JD from HTML',       icon: FileText },
  { id: 'dedup',           label: 'Dedup',        desc: 'URL dedup (TTL window)',    icon: Fingerprint },
  { id: 'hard_filter',     label: 'Hard Filter',  desc: 'Salary · seniority · domain', icon: Filter },
  { id: 'storage',         label: 'Storage',      desc: 'Persist to SQLite',          icon: HardDrive },
];

const TAILOR_STAGE_DEFS = [
  { id: 'tailor_analysis', label: 'Analysis', desc: 'Extract JD requirements',    icon: Microscope, llm: true },
  { id: 'tailor_strategy', label: 'Strategy', desc: 'Plan resume targeting',      icon: Target,     llm: true },
  { id: 'tailor_resume',   label: 'Resume',   desc: 'LaTeX resume draft',         icon: PenTool,    llm: true },
  { id: 'tailor_cover',    label: 'Cover',    desc: 'LaTeX cover letter',         icon: Mail,       llm: true },
  { id: 'tailor_validate', label: 'Validate', desc: 'Hard gate checks',           icon: ShieldCheck, llm: false },
  { id: 'tailor_compile',  label: 'Compile',  desc: 'pdflatex → PDF',             icon: Printer,    llm: false },
];

const SEARCH_PROVIDER_KEYS = new Set(['google','startpage','duckduckgo','brave','bing','searxng','qwant','yahoo']);

const EMPTY_SOURCE_STATS: SourceRollupStats = { searxng: 0, ashby: 0, greenhouse: 0, lever: 0, usajobs: 0 };

const INITIAL_LIVE_STATUS: LiveStatus = {
  scrapeRunning: false, scrapeStartedAt: null, scrapeLogTail: '',
  qaReviewRunning: false, qaReviewModel: null, qaReviewProgress: null, qaReviewItems: [],
  tailoringRunning: false, tailoringJob: null, tailoringQueue: 0, tailoringLogTail: '',
};

// ─── Helpers ─────────────────────────────────────────────────────────
function timeSince(ts: number | null) {
  if (!ts) return 'waiting';
  return timeAgo(new Date(ts).toISOString());
}

function aggregateSourceStats(perSource: Record<string, number> | undefined): SourceRollupStats {
  const next = { ...EMPTY_SOURCE_STATS };
  for (const [rawKey, value] of Object.entries(perSource || {})) {
    const key = rawKey.toLowerCase();
    if (key.startsWith('ashby')) next.ashby += value;
    else if (key.startsWith('greenhouse')) next.greenhouse += value;
    else if (key.startsWith('lever')) next.lever += value;
    else if (key.startsWith('usajobs')) next.usajobs += value;
    else if (key === 'searxng' || SEARCH_PROVIDER_KEYS.has(key)) next.searxng += value;
    else if (key.includes('search') || key.includes('google') || key.includes('startpage')) next.searxng += value;
  }
  return next;
}

function toneForDelta(delta: number): EventTone {
  if (delta > 0) return 'green';
  if (delta < 0) return 'amber';
  return 'muted';
}

function buildPipelineEvents(
  prev: { live: LiveStatus; stats: PipelineStats | null } | null,
  next: { live: LiveStatus; stats: PipelineStats | null },
): PipelineEvent[] {
  if (!prev) return [];
  const events: PipelineEvent[] = [];
  const now = Date.now();
  const push = (label: string, detail: string | undefined, tone: EventTone, scope: EventScope) =>
    events.push({ id: `${scope}-${label}-${now}-${events.length}`, label, detail, tone, scope, createdAt: now });

  if (prev.live.scrapeRunning !== next.live.scrapeRunning) {
    push(next.live.scrapeRunning ? 'Scrape started' : 'Scrape stopped',
      next.live.scrapeRunning ? 'Discovery lane active.' : 'Awaiting next run.',
      next.live.scrapeRunning ? 'accent' : 'muted', 'scrape');
  }

  if (prev.live.qaReviewRunning !== next.live.qaReviewRunning) {
    push(next.live.qaReviewRunning ? 'QA review started' : 'QA review stopped',
      next.live.qaReviewRunning ? 'Review queue processing.' : 'Review lane idle.',
      next.live.qaReviewRunning ? 'accent' : 'muted', 'qa');
  }

  if (prev.live.tailoringRunning !== next.live.tailoringRunning) {
    push(next.live.tailoringRunning ? 'Tailoring started' : 'Tailoring stopped',
      next.live.tailoringRunning ? (next.live.tailoringJob || 'Package in progress.') : 'No active package.',
      next.live.tailoringRunning ? 'accent' : 'muted', 'tailor');
  }

  if (prev.live.tailoringQueue !== next.live.tailoringQueue) {
    push(`Tailor queue ${prev.live.tailoringQueue} → ${next.live.tailoringQueue}`,
      next.live.tailoringQueue > prev.live.tailoringQueue ? 'More approved jobs queued.' : 'Queue draining.',
      toneForDelta(prev.live.tailoringQueue - next.live.tailoringQueue), 'tailor');
  }

  const prevDone = prev.live.qaReviewProgress?.completed ?? 0;
  const nextDone = next.live.qaReviewProgress?.completed ?? 0;
  if (nextDone > prevDone) {
    push(`QA reviewed +${nextDone - prevDone}`,
      `${nextDone}/${next.live.qaReviewProgress?.total ?? nextDone} in current batch.`, 'green', 'qa');
  }

  const pi = prev.stats?.inventory;
  const ni = next.stats?.inventory;
  if (pi && ni) {
    if (ni.qa_approved > pi.qa_approved) push(`QA approved +${ni.qa_approved - pi.qa_approved}`, `${fmt(ni.qa_approved)} ready to tailor.`, 'green', 'qa');
    if (ni.qa_rejected > pi.qa_rejected) push(`QA rejected +${ni.qa_rejected - pi.qa_rejected}`, `${fmt(ni.qa_rejected)} now in reject bucket.`, 'red', 'qa');
    if (ni.qa_pending !== pi.qa_pending)  push(`Review backlog ${pi.qa_pending} → ${ni.qa_pending}`,
      ni.qa_pending > pi.qa_pending ? 'Backlog grew.' : 'Backlog shrank.',
      toneForDelta(pi.qa_pending - ni.qa_pending), 'inventory');
    if (ni.total > pi.total) push(`Stored +${ni.total - pi.total}`, `${fmt(ni.total)} rows in inventory.`, 'green', 'inventory');
  }

  return events;
}

function buildLiveStatus(scrape: any, qa: any, tailor: any): LiveStatus {
  return {
    scrapeRunning: scrape?.running ?? false,
    scrapeStartedAt: scrape?.started_at ?? null,
    scrapeLogTail: scrape?.log_tail ?? '',
    qaReviewRunning: qa?.running ?? false,
    qaReviewModel: qa?.resolved_model ?? null,
    qaReviewProgress: qa?.summary ? { completed: qa.summary.completed, total: qa.summary.total } : null,
    qaReviewItems: qa?.items ?? [],
    tailoringRunning: tailor?.running ?? false,
    tailoringJob: tailor?.job?.title ?? tailor?.active_item?.title ?? null,
    tailoringQueue: tailor?.queue?.length ?? 0,
    tailoringLogTail: tailor?.log_tail ?? '',
  };
}

function nodeTitle(n: { id: string; type: string } | null): string {
  if (!n) return 'System overview';
  if (n.type === 'source') return SOURCE_DEFS.find(s => s.id === n.id)?.label || n.id;
  if (n.type === 'stage')  return STAGE_DEFS.find(s => s.id === n.id)?.label || n.id;
  if (n.type === 'dbOutput') return 'Results DB';
  if (n.type === 'qaReview') return 'QA LLM Review';
  return TAILOR_STAGE_DEFS.find(s => s.id === n.id)?.label || n.id;
}

function nodeSubtitle(n: { id: string; type: string } | null): string {
  if (!n) return 'Live orchestration across all phases';
  if (n.type === 'source')   return 'Source provider · configuration & throughput';
  if (n.type === 'stage')    return 'Ingest stage · pass / drop counts';
  if (n.type === 'dbOutput') return 'Persistent inventory · downstream handoff';
  if (n.type === 'qaReview') return 'LLM-assisted fit review';
  if (n.type === 'tailorStage') return 'Tailoring stage · LLM generation';
  return '';
}

// ─── Custom nodes ────────────────────────────────────────────────────
function PhaseLabelNode({ data }: NodeProps) {
  const d = data as { label: string; count: string; accent: string; active: boolean };
  return (
    <div className={`pe-phase-label${d.active ? ' pe-phase-active' : ''}`} style={{ ['--phase' as any]: d.accent }}>
      <div className="pe-phase-label-stripe" />
      <div className="pe-phase-label-title">{d.label}</div>
      <div className="pe-phase-label-count">{d.count}</div>
    </div>
  );
}

function SourceNode({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div
      className={`pe-node pe-node-source${selected ? ' is-selected' : ''}${!d.enabled ? ' is-disabled' : ''}${d.active ? ' is-active' : ''}`}
      onClick={d.onSelect}
    >
      <div className="pe-node-icon">{d.iconEl}</div>
      <div className="pe-node-body">
        <div className="pe-node-label">{d.label}</div>
        <div className="pe-node-sub">{d.count} {d.countLabel}</div>
      </div>
      <div className="pe-node-badge">
        {!d.enabled ? 'off' : d.active ? <span className="pe-dot pe-dot-live" /> : d.stat > 0 ? fmt(d.stat) : '—'}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function StageNode({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div
      className={`pe-node pe-node-stage${selected ? ' is-selected' : ''}${d.active ? ' is-active' : ''}`}
      onClick={d.onSelect}
    >
      <div className="pe-node-icon">{d.iconEl}</div>
      <div className="pe-node-body">
        <div className="pe-node-label">{d.label}</div>
        <div className="pe-node-sub">{d.desc}</div>
      </div>
      <div className="pe-node-badge">
        {d.dropCount != null && d.dropCount > 0
          ? <span className="pe-badge-drop">−{fmt(d.dropCount)}</span>
          : d.passCount != null
            ? fmt(d.passCount)
            : <span className="pe-node-order">{d.order}</span>}
      </div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function OutputNode({ data, selected }: NodeProps) {
  const d = data as any;
  const inv = d.inventory;
  return (
    <div
      className={`pe-node pe-node-output${selected ? ' is-selected' : ''}${d.active ? ' is-active' : ''}`}
      onClick={d.onSelect}
    >
      <div className="pe-node-icon"><Database size={16} /></div>
      <div className="pe-node-body">
        <div className="pe-node-label">Results DB</div>
        <div className="pe-node-sub">{inv ? `${fmt(inv.total)} total · ${fmt(inv.qa_pending)} pending` : 'SQLite inventory'}</div>
      </div>
      <div className="pe-node-badge">{inv ? fmt(inv.total) : '—'}</div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function QAReviewNode({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div
      className={`pe-node pe-node-qa${selected ? ' is-selected' : ''}${d.running ? ' is-active' : ''}`}
      onClick={d.onSelect}
    >
      <div className="pe-node-icon"><Brain size={16} /></div>
      <div className="pe-node-body">
        <div className="pe-node-label">QA LLM Review</div>
        <div className="pe-node-sub">
          {d.running ? `${d.progress?.completed ?? 0}/${d.progress?.total ?? 0} reviewing…` : `${fmt(d.pending)} pending · ${fmt(d.approved)} approved`}
        </div>
      </div>
      <div className="pe-node-badge">
        {d.running ? <span className="pe-dot pe-dot-live" style={{ background: 'var(--cyan)' }} /> : fmt(d.pending)}
      </div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function TailorStageNode({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div
      className={`pe-node pe-node-tailor${selected ? ' is-selected' : ''}${d.active ? ' is-active' : ''}`}
      onClick={d.onSelect}
    >
      <div className="pe-node-icon">{d.iconEl}</div>
      <div className="pe-node-body">
        <div className="pe-node-label">
          {d.label}
          {d.llm ? <span className="pe-llm-pip" title="LLM-backed" /> : null}
        </div>
        <div className="pe-node-sub">{d.desc}</div>
      </div>
      <div className="pe-node-badge">
        {d.active && d.isFirst ? <span className="pe-dot pe-dot-live" style={{ background: 'var(--orange)' }} />
          : d.isFirst ? (d.queue > 0 ? fmt(d.queue) : 'idle')
            : <span className="pe-node-order">{d.order}</span>}
      </div>
      <Handle type="target" position={d.handleIn ?? Position.Left} id="target" />
      {!d.isLast && <Handle type="source" position={d.handleOut ?? Position.Right} id="source" />}
    </div>
  );
}

const nodeTypes = {
  phaseLabel: memo(PhaseLabelNode),
  source: memo(SourceNode),
  stage: memo(StageNode),
  dbOutput: memo(OutputNode),
  qaReview: memo(QAReviewNode),
  tailorStage: memo(TailorStageNode),
};

// ─── Layout ──────────────────────────────────────────────────────────
const COL_SOURCES = 40;
const COL_INGEST  = 330;
const COL_REVIEW  = 660;
const COL_TAILOR_START = 980;
const ROW_Y0 = 120;
const ROW_GAP = 84;
const TAILOR_GAP = 210;

function buildNodes(
  config: ScraperConfig,
  stats: PipelineStats | null,
  live: LiveStatus,
  sourceStats: SourceRollupStats,
  onSelect: (id: string, type: string) => void,
): Node[] {
  const nodes: Node[] = [];
  const inv = stats?.inventory;

  const renderedStages = config.pipeline_order.filter((id) => STAGE_DEFS.some((s) => s.id === id));

  // Phase headers
  const headerY = 40;
  nodes.push(
    { id: 'phase-discover', type: 'phaseLabel', position: { x: COL_SOURCES, y: headerY },
      data: { label: 'Discover', count: `${SOURCE_DEFS.length} sources`, accent: 'var(--accent)', active: live.scrapeRunning },
      draggable: false, selectable: false, focusable: false },
    { id: 'phase-ingest', type: 'phaseLabel', position: { x: COL_INGEST, y: headerY },
      data: { label: 'Ingest', count: `${renderedStages.length} stages`, accent: 'var(--purple)', active: live.scrapeRunning },
      draggable: false, selectable: false, focusable: false },
    { id: 'phase-review', type: 'phaseLabel', position: { x: COL_REVIEW, y: headerY },
      data: { label: 'Review', count: inv ? `${fmt(inv.qa_pending)} pending` : 'QA + LLM', accent: 'var(--cyan)', active: live.qaReviewRunning },
      draggable: false, selectable: false, focusable: false },
    { id: 'phase-tailor', type: 'phaseLabel', position: { x: COL_TAILOR_START, y: headerY },
      data: { label: 'Tailor', count: `${TAILOR_STAGE_DEFS.length} steps`, accent: 'var(--orange)', active: live.tailoringRunning },
      draggable: false, selectable: false, focusable: false },
  );

  // Sources column
  SOURCE_DEFS.forEach((src, i) => {
    let count = 0;
    let enabled = true;
    if (src.id === 'searxng') { count = config.queries.length; enabled = config.searxng.enabled; }
    else if (src.id === 'usajobs') { count = config.usajobs.keywords.length; enabled = config.usajobs.enabled; }
    else {
      const boards = config.boards.filter((b) => b.board_type === src.id);
      count = boards.length;
      enabled = boards.some((b) => b.enabled);
    }
    const Icon = src.icon;
    nodes.push({
      id: src.id,
      type: 'source',
      position: { x: COL_SOURCES, y: ROW_Y0 + i * ROW_GAP },
      data: {
        label: src.label, iconEl: <Icon size={15} />, count, countLabel: src.countLabel,
        enabled, active: live.scrapeRunning && enabled,
        stat: sourceStats[src.id as keyof SourceRollupStats] ?? 0,
        onSelect: () => onSelect(src.id, 'source'),
      },
    });
  });

  // Ingest column (only stages with defs — skip unknown like llm_relevance)
  renderedStages.forEach((stageId, i) => {
    const def = STAGE_DEFS.find((s) => s.id === stageId);
    if (!def) return;
    const Icon = def.icon;
    let passCount: number | null = null;
    let dropCount: number | null = null;
    if (stats) {
      if (stageId === 'dedup') { dropCount = stats.dedup_dropped; passCount = stats.raw_count - stats.dedup_dropped; }
      else if (stageId === 'hard_filter') { dropCount = stats.filter_rejected; }
      else if (stageId === 'storage') { passCount = stats.stored; }
    }
    nodes.push({
      id: stageId,
      type: 'stage',
      position: { x: COL_INGEST, y: ROW_Y0 + i * ROW_GAP },
      data: {
        label: def.label, desc: def.desc, iconEl: <Icon size={15} />,
        order: i + 1, passCount, dropCount, active: live.scrapeRunning,
        onSelect: () => onSelect(stageId, 'stage'),
      },
    });
  });

  // Review column — DB + QA
  nodes.push({
    id: 'output',
    type: 'dbOutput',
    position: { x: COL_REVIEW, y: ROW_Y0 + ROW_GAP * 0.5 },
    data: { inventory: inv ?? null, active: live.scrapeRunning, onSelect: () => onSelect('output', 'dbOutput') },
  });
  nodes.push({
    id: 'qaReview',
    type: 'qaReview',
    position: { x: COL_REVIEW, y: ROW_Y0 + ROW_GAP * 2 },
    data: {
      running: live.qaReviewRunning, model: live.qaReviewModel,
      pending: inv?.qa_pending ?? 0, approved: inv?.qa_approved ?? 0, rejected: inv?.qa_rejected ?? 0,
      progress: live.qaReviewProgress,
      onSelect: () => onSelect('qaReview', 'qaReview'),
    },
  });

  // Tailor — serpentine S-curve:
  //   row 0: analysis(col0) → strategy(col1) → resume(col2)  (flows right)
  //   row 1: compile(col0) ← validate(col1) ← cover(col2)    (flows left)
  //   wrap:  resume → cover (top-right to bottom-right)
  const tailorRowY = [ROW_Y0 + ROW_GAP * 0.5, ROW_Y0 + ROW_GAP * 2];
  TAILOR_STAGE_DEFS.forEach((def, i) => {
    const Icon = def.icon;
    const row = i < 3 ? 0 : 1;
    const col = row === 0 ? i : (5 - i);
    const x = COL_TAILOR_START + col * TAILOR_GAP;
    const y = tailorRowY[row];
    const isLast = i === TAILOR_STAGE_DEFS.length - 1;
    const isFirst = i === 0;
    const isWrapSource = i === 2;   // resume: flows down to cover
    const isWrapTarget = i === 3;   // cover: receives from above
    const handleIn = isWrapTarget ? Position.Top : (row === 0 ? Position.Left : Position.Right);
    const handleOut = isWrapSource ? Position.Bottom : (row === 0 ? Position.Right : Position.Left);
    nodes.push({
      id: def.id,
      type: 'tailorStage',
      position: { x, y },
      data: {
        label: def.label, desc: def.desc, iconEl: <Icon size={14} />, llm: def.llm,
        order: i + 1, isFirst, isLast,
        handleIn, handleOut,
        active: live.tailoringRunning,
        queue: live.tailoringQueue,
        job: live.tailoringJob,
        onSelect: () => onSelect(def.id, 'tailorStage'),
      },
    });
  });

  return nodes;
}

function buildEdges(config: ScraperConfig, live: LiveStatus): Edge[] {
  const edges: Edge[] = [];
  const firstStage = config.pipeline_order[0];
  const lastStage  = config.pipeline_order[config.pipeline_order.length - 1];

  const labelStyle = { fill: 'var(--text-secondary)', fontSize: 10, fontFamily: 'var(--font-mono)', letterSpacing: 0 };
  const labelBgStyle = { fill: 'var(--bg)', stroke: 'var(--border)', strokeWidth: 1 };

  const add = (o: {
    id: string; source: string; target: string;
    sourceHandle?: string; targetHandle?: string;
    label?: string; active: boolean; tone: string;
  }) => {
    edges.push({
      id: o.id, source: o.source, target: o.target,
      sourceHandle: o.sourceHandle, targetHandle: o.targetHandle,
      type: 'smoothstep',
      animated: o.active,
      className: `pe-edge pe-edge-${o.tone}${o.active ? ' is-active' : ' is-idle'}`,
      style: { strokeWidth: o.active ? 2.2 : 1.5 },
      ...(o.label ? { label: o.label, labelStyle, labelBgStyle, labelBgPadding: [6, 3] as [number, number], labelBgBorderRadius: 4 } : {}),
    });
  };

  SOURCE_DEFS.forEach((src) => add({ id: `${src.id}->${firstStage}`, source: src.id, target: firstStage, active: live.scrapeRunning, tone: 'source' }));

  for (let i = 0; i < config.pipeline_order.length - 1; i++) {
    add({ id: `${config.pipeline_order[i]}->${config.pipeline_order[i + 1]}`,
      source: config.pipeline_order[i], target: config.pipeline_order[i + 1],
      active: live.scrapeRunning, tone: 'stage' });
  }

  add({ id: `${lastStage}->output`, source: lastStage, target: 'output', active: live.scrapeRunning, tone: 'output', label: 'stored' });
  add({ id: 'output->qaReview', source: 'output', target: 'qaReview', active: live.qaReviewRunning, tone: 'qa', label: 'qa_pending' });
  add({ id: 'qaReview->tailor_analysis', source: 'qaReview', target: 'tailor_analysis', active: live.tailoringRunning, tone: 'tailor', label: 'qa_approved' });

  const tailorIds = TAILOR_STAGE_DEFS.map((t) => t.id);
  for (let i = 0; i < tailorIds.length - 1; i++) {
    add({
      id: `${tailorIds[i]}->${tailorIds[i + 1]}`,
      source: tailorIds[i], target: tailorIds[i + 1],
      active: live.tailoringRunning, tone: 'tailor',
    });
  }

  return edges;
}

// ─── Inspector ───────────────────────────────────────────────────────
function Inspector({
  selectedNode, onClear, config, stats, qaStatus, live, events, sourceStats, onConfigChange,
}: {
  selectedNode: { id: string; type: string } | null;
  onClear: () => void;
  config: ScraperConfig;
  stats: PipelineStats | null;
  qaStatus: QALlmReviewStatus | null;
  live: LiveStatus;
  events: PipelineEvent[];
  sourceStats: SourceRollupStats;
  onConfigChange: (patch: Partial<ScraperConfig>) => void;
}) {
  const title = nodeTitle(selectedNode);
  const subtitle = nodeSubtitle(selectedNode);

  return (
    <aside className="pe-inspector">
      <div className="pe-inspector-head">
        <div>
          <div className="pe-inspector-eyebrow">{selectedNode ? selectedNode.type.replace('dbOutput', 'output').replace('qaReview', 'review').replace('tailorStage', 'tailor stage') : 'overview'}</div>
          <div className="pe-inspector-title">{title}</div>
          <div className="pe-inspector-sub">{subtitle}</div>
        </div>
        {selectedNode && (
          <button className="pe-inspector-close" onClick={onClear} aria-label="Clear selection"><X size={14} /></button>
        )}
      </div>

      <div className="pe-inspector-body">
        {!selectedNode && <OverviewSection stats={stats} live={live} events={events} qaStatus={qaStatus} />}
        {selectedNode?.type === 'source' && (
          <SourceInspector sourceId={selectedNode.id} config={config} sourceStats={sourceStats} events={events} onConfigChange={onConfigChange} />
        )}
        {selectedNode?.type === 'stage' && (
          <StageInspector stageId={selectedNode.id} config={config} stats={stats} events={events} onConfigChange={onConfigChange} />
        )}
        {selectedNode?.type === 'dbOutput' && <DbOutputInspector stats={stats} events={events} />}
        {selectedNode?.type === 'qaReview' && <QAInspector qaStatus={qaStatus} live={live} events={events} />}
        {selectedNode?.type === 'tailorStage' && <TailorStageInspector stageId={selectedNode.id} live={live} events={events} />}
      </div>
    </aside>
  );
}

// ─── Overview (no selection) ─────────────────────────────────────────
function OverviewSection({ stats, live, events, qaStatus }: {
  stats: PipelineStats | null;
  live: LiveStatus;
  events: PipelineEvent[];
  qaStatus: QALlmReviewStatus | null;
}) {
  const inv = stats?.inventory;
  const total = inv?.total ?? 0;
  const pending = inv?.qa_pending ?? 0;
  const approved = inv?.qa_approved ?? 0;
  const rejected = inv?.qa_rejected ?? 0;
  const scrapeRejected = inv?.rejected ?? 0;

  const pct = (v: number) => total > 0 ? (v / total) * 100 : 0;

  return (
    <>
      <SectionHead>Phase state</SectionHead>
      <div className="pe-phase-rows">
        <PhaseRow label="Discover" state={live.scrapeRunning ? 'running' : 'idle'}
          detail={live.scrapeRunning && live.scrapeStartedAt ? `started ${timeAgo(live.scrapeStartedAt)}` : 'idle'}
          color="var(--accent)" />
        <PhaseRow label="Review" state={live.qaReviewRunning ? 'running' : 'idle'}
          detail={live.qaReviewRunning && live.qaReviewProgress
            ? `${live.qaReviewProgress.completed}/${live.qaReviewProgress.total}`
            : qaStatus?.resolved_model || 'idle'}
          color="var(--cyan)" />
        <PhaseRow label="Tailor" state={live.tailoringRunning ? 'running' : 'idle'}
          detail={live.tailoringRunning ? (live.tailoringJob || 'generating') : `queue: ${fmt(live.tailoringQueue)}`}
          color="var(--orange)" />
      </div>

      <SectionHead>Inventory funnel</SectionHead>
      <div className="pe-funnel">
        <FunnelBar label="Total stored" value={total} color="var(--text)" pct={100} total={total} />
        <FunnelBar label="Pending review" value={pending} color="var(--amber)" pct={pct(pending)} total={total} />
        <FunnelBar label="QA approved" value={approved} color="var(--green)" pct={pct(approved)} total={total} />
        <FunnelBar label="QA rejected" value={rejected} color="var(--red)" pct={pct(rejected)} total={total} />
        {scrapeRejected > 0 && <FunnelBar label="Scraper rejected" value={scrapeRejected} color="var(--text-secondary)" pct={0} total={total} />}
      </div>

      <SectionHead>Recent activity</SectionHead>
      <EventList events={events.slice(0, 10)} emptyLabel="No pipeline activity yet" />

      {(live.scrapeRunning && live.scrapeLogTail) && (
        <>
          <SectionHead>Scrape log</SectionHead>
          <LogTail content={live.scrapeLogTail} />
        </>
      )}
      {(live.tailoringRunning && live.tailoringLogTail) && (
        <>
          <SectionHead>Tailoring log</SectionHead>
          <LogTail content={live.tailoringLogTail} />
        </>
      )}
    </>
  );
}

function PhaseRow({ label, state, detail, color }: { label: string; state: 'running' | 'idle'; detail: string; color: string }) {
  return (
    <div className={`pe-phase-row pe-phase-row-${state}`}>
      <span className="pe-phase-row-stripe" style={{ background: color }} />
      <span className="pe-phase-row-label">{label}</span>
      <span className="pe-phase-row-state">
        {state === 'running' ? <span className="pe-dot pe-dot-live" style={{ background: color }} /> : <span className="pe-dot pe-dot-idle" />}
        {state}
      </span>
      <span className="pe-phase-row-detail">{detail}</span>
    </div>
  );
}

function FunnelBar({ label, value, color, pct, total }: { label: string; value: number; color: string; pct: number; total: number }) {
  return (
    <div className="pe-funnel-bar">
      <div className="pe-funnel-bar-head">
        <span>{label}</span>
        <span className="pe-funnel-bar-val">{fmt(value)} <span className="pe-funnel-bar-pct">{total > 0 ? `${pct.toFixed(0)}%` : ''}</span></span>
      </div>
      <div className="pe-funnel-bar-track"><div className="pe-funnel-bar-fill" style={{ width: `${pct}%`, background: color }} /></div>
    </div>
  );
}

// ─── Selection inspectors ────────────────────────────────────────────
function SourceInspector({ sourceId, config, sourceStats, events, onConfigChange }: {
  sourceId: string;
  config: ScraperConfig;
  sourceStats: SourceRollupStats;
  events: PipelineEvent[];
  onConfigChange: (p: Partial<ScraperConfig>) => void;
}) {
  const seen = sourceStats[sourceId as keyof SourceRollupStats] ?? 0;

  if (sourceId === 'searxng') {
    const s = config.searxng;
    const update = (k: string, v: any) => onConfigChange({ searxng: { ...s, [k]: v } });
    return (
      <>
        <MetricRow items={[
          { label: 'Queries', value: fmt(config.queries.length) },
          { label: 'Enabled', value: s.enabled ? 'on' : 'off', tone: s.enabled ? 'green' : 'muted' },
          { label: 'Last run', value: fmt(seen) },
        ]} />
        <SectionHead>SearXNG settings</SectionHead>
        <LabelInput label="Engines" value={s.engines} onChange={(v) => update('engines', v)} />
        <LabelInput label="Time range" value={s.time_range} onChange={(v) => update('time_range', v)} />
        <LabelInput label="Request delay (s)" value={s.request_delay} type="number" step={0.5} onChange={(v) => update('request_delay', Number(v))} />
        <LabelInput label="Timeout (s)" value={s.timeout} type="number" onChange={(v) => update('timeout', Number(v))} />

        <SectionHead>Queries ({config.queries.length})</SectionHead>
        <div className="pe-list">
          {config.queries.map((q, i) => (
            <div className="pe-list-row" key={i}>
              <Search size={11} style={{ opacity: .45 }} />
              <span className="pe-list-row-title">{q.title_phrase}</span>
              {q.board_site && <span className="pe-list-row-meta">{q.board_site.split('.')[0]}</span>}
            </div>
          ))}
        </div>
        <ScopedEvents events={events} scopes={['scrape', 'inventory']} />
      </>
    );
  }

  if (sourceId === 'usajobs') {
    const u = config.usajobs;
    const update = (k: string, v: any) => onConfigChange({ usajobs: { ...u, [k]: v } });
    return (
      <>
        <MetricRow items={[
          { label: 'Keywords', value: fmt(u.keywords.length) },
          { label: 'Enabled', value: u.enabled ? 'on' : 'off', tone: u.enabled ? 'green' : 'muted' },
          { label: 'Last run', value: fmt(seen) },
        ]} />
        <SectionHead>Settings</SectionHead>
        <LabelInput label="Days lookback" value={u.days} type="number" onChange={(v) => update('days', Number(v))} />
        <ToggleRow label="Remote only" on={u.remote} onToggle={() => update('remote', !u.remote)} />
        <SectionHead>Keywords</SectionHead>
        <TagList items={u.keywords} onUpdate={(v) => update('keywords', v)} />
        <SectionHead>Series codes</SectionHead>
        <TagList items={u.series} onUpdate={(v) => update('series', v)} />
        <ScopedEvents events={events} scopes={['scrape']} />
      </>
    );
  }

  // Board sources (ashby / greenhouse / lever)
  const boards = config.boards.filter((b) => b.board_type === sourceId);
  const enabledCount = boards.filter((b) => b.enabled).length;
  const toggle = (idx: number) => {
    const next = [...config.boards];
    const globalIdx = config.boards.findIndex((b) => b.board_type === sourceId && b.company === boards[idx].company);
    if (globalIdx < 0) return;
    next[globalIdx] = { ...next[globalIdx], enabled: !next[globalIdx].enabled };
    onConfigChange({ boards: next });
  };

  return (
    <>
      <MetricRow items={[
        { label: 'Boards', value: fmt(boards.length) },
        { label: 'Enabled', value: fmt(enabledCount), tone: enabledCount > 0 ? 'green' : 'muted' },
        { label: 'Last run', value: fmt(seen) },
      ]} />
      <SectionHead>Boards ({boards.length})</SectionHead>
      <div className="pe-list">
        {boards.map((b, i) => (
          <div className={`pe-list-row${!b.enabled ? ' is-off' : ''}`} key={`${b.board_type}-${b.company}-${i}`}>
            <Toggle on={b.enabled} onToggle={() => toggle(i)} />
            <span className="pe-list-row-title">{b.company}</span>
          </div>
        ))}
      </div>
      {sourceId !== 'lever' && (
        <>
          <SectionHead>Crawl limits</SectionHead>
          <LabelInput label="Max per board" value={config.crawl.max_results_per_target} type="number"
            onChange={(v) => onConfigChange({ crawl: { ...config.crawl, max_results_per_target: Number(v) } })} />
          <LabelInput label="Request delay (s)" value={config.crawl.request_delay} type="number" step={0.5}
            onChange={(v) => onConfigChange({ crawl: { ...config.crawl, request_delay: Number(v) } })} />
        </>
      )}
      <ScopedEvents events={events} scopes={['scrape']} />
    </>
  );
}

function StageInspector({ stageId, config, stats, events, onConfigChange }: {
  stageId: string;
  config: ScraperConfig;
  stats: PipelineStats | null;
  events: PipelineEvent[];
  onConfigChange: (p: Partial<ScraperConfig>) => void;
}) {
  const passCount = stageId === 'dedup' ? Math.max((stats?.raw_count ?? 0) - (stats?.dedup_dropped ?? 0), 0)
    : stageId === 'storage' ? (stats?.stored ?? 0) : null;
  const dropCount = stageId === 'dedup' ? (stats?.dedup_dropped ?? 0)
    : stageId === 'hard_filter' ? (stats?.filter_rejected ?? 0) : null;
  const order = config.pipeline_order.indexOf(stageId) + 1;

  return (
    <>
      <MetricRow items={[
        { label: 'Order', value: String(order) },
        { label: 'Pass', value: fmt(passCount), tone: 'green' },
        { label: 'Drop', value: fmt(dropCount), tone: dropCount ? 'red' : 'muted' },
      ]} />

      {stageId === 'dedup' && (
        <>
          <SectionHead>Deduplication window</SectionHead>
          <LabelInput label="TTL (days)" value={config.seen_ttl_days} type="number"
            onChange={(v) => onConfigChange({ seen_ttl_days: Number(v) })} />
          <div className="pe-hint">URLs older than this re-enter the pipeline.</div>
        </>
      )}

      {stageId === 'hard_filter' && (
        <>
          <SectionHead>Thresholds</SectionHead>
          <LabelInput label="Min salary ($k)" value={config.hard_filters.min_salary_k} type="number"
            onChange={(v) => onConfigChange({ hard_filters: { ...config.hard_filters, min_salary_k: Number(v) } })} />
          <LabelInput label="Target salary ($k)" value={config.hard_filters.target_salary_k} type="number"
            onChange={(v) => onConfigChange({ hard_filters: { ...config.hard_filters, target_salary_k: Number(v) } })} />
          <LabelInput label="Max experience (years)" value={config.filter.max_experience_years} type="number"
            onChange={(v) => onConfigChange({ filter: { ...config.filter, max_experience_years: Number(v) } })} />
          <SectionHead>Seniority blocklist</SectionHead>
          <TagList items={config.hard_filters.title_blocklist}
            onUpdate={(v) => onConfigChange({ hard_filters: { ...config.hard_filters, title_blocklist: v } })} />
          <SectionHead>Content blocklist</SectionHead>
          <TagList items={config.hard_filters.content_blocklist}
            onUpdate={(v) => onConfigChange({ hard_filters: { ...config.hard_filters, content_blocklist: v } })} />
          <SectionHead>Domain blocklist</SectionHead>
          <TagList items={config.hard_filters.domain_blocklist}
            onUpdate={(v) => onConfigChange({ hard_filters: { ...config.hard_filters, domain_blocklist: v } })} />
        </>
      )}

      {(stageId === 'text_extraction' || stageId === 'storage') && (
        <div className="pe-hint">No configurable parameters for this stage.</div>
      )}

      <ScopedEvents events={events} scopes={['scrape', 'inventory']} />
    </>
  );
}

function DbOutputInspector({ stats, events }: { stats: PipelineStats | null; events: PipelineEvent[] }) {
  const inv = stats?.inventory;
  return (
    <>
      <MetricRow items={[
        { label: 'Total', value: fmt(inv?.total) },
        { label: 'Pending', value: fmt(inv?.qa_pending), tone: (inv?.qa_pending ?? 0) > 0 ? 'amber' : 'muted' },
        { label: 'Approved', value: fmt(inv?.qa_approved), tone: 'green' },
      ]} />
      <MetricRow items={[
        { label: 'QA reject', value: fmt(inv?.qa_rejected), tone: (inv?.qa_rejected ?? 0) > 0 ? 'red' : 'muted' },
        { label: 'Scraper reject', value: fmt(inv?.rejected), tone: 'muted' },
      ]} />
      {stats?.per_source && Object.keys(stats.per_source).length > 0 && (
        <>
          <SectionHead>Last run · per source</SectionHead>
          <div className="pe-list">
            {Object.entries(stats.per_source).map(([src, cnt]) => (
              <div className="pe-list-row" key={src}>
                <span className="pe-dot pe-dot-idle" style={{ background: 'var(--accent)' }} />
                <span className="pe-list-row-title">{src}</span>
                <span className="pe-list-row-meta">{fmt(cnt)}</span>
              </div>
            ))}
          </div>
        </>
      )}
      {stats?.per_rejection && Object.keys(stats.per_rejection).length > 0 && (
        <>
          <SectionHead>Last run · rejections</SectionHead>
          <div className="pe-list">
            {Object.entries(stats.per_rejection).map(([stage, cnt]) => (
              <div className="pe-list-row" key={stage}>
                <span className="pe-dot pe-dot-idle" style={{ background: 'var(--red)' }} />
                <span className="pe-list-row-title">{stage}</span>
                <span className="pe-list-row-meta">{fmt(cnt)}</span>
              </div>
            ))}
          </div>
        </>
      )}
      <ScopedEvents events={events} scopes={['inventory', 'scrape']} />
    </>
  );
}

function QAInspector({ qaStatus, live, events }: {
  qaStatus: QALlmReviewStatus | null;
  live: LiveStatus;
  events: PipelineEvent[];
}) {
  const s = qaStatus?.summary;
  const items = (qaStatus?.items || []).filter((i) => i.status !== 'queued').slice(0, 8);
  return (
    <>
      <MetricRow items={[
        { label: 'State', value: qaStatus?.running ? 'Running' : 'Idle', tone: qaStatus?.running ? 'accent' : 'muted' },
        { label: 'Progress', value: live.qaReviewProgress ? `${live.qaReviewProgress.completed}/${live.qaReviewProgress.total}` : '—' },
      ]} />
      {qaStatus?.resolved_model && (
        <div className="pe-tag-line">
          <Brain size={11} style={{ opacity: .5 }} />
          <span className="pe-tag-line-mono">{qaStatus.resolved_model}</span>
        </div>
      )}
      {s && s.total > 0 && (
        <div className="pe-mini-pills">
          <span className="pe-mini-pill pe-mini-pill-green">{s.passed} pass</span>
          <span className="pe-mini-pill pe-mini-pill-red">{s.failed} fail</span>
          {s.skipped > 0 && <span className="pe-mini-pill">{s.skipped} skip</span>}
          {s.errors > 0 && <span className="pe-mini-pill pe-mini-pill-red">{s.errors} err</span>}
          {s.queued > 0 && <span className="pe-mini-pill">{s.queued} queued</span>}
        </div>
      )}
      {items.length > 0 && (
        <>
          <SectionHead>Live results</SectionHead>
          <div className="pe-list">
            {items.map((item) => (
              <div key={item.job_id} className={`pe-qa-result pe-qa-${item.status}`}>
                <div className="pe-qa-result-title">{item.title || `Job #${item.job_id}`}</div>
                {item.reason && <div className="pe-qa-result-reason">{item.reason}</div>}
                {(item.confidence != null) && (
                  <div className="pe-qa-result-conf">confidence {(item.confidence * 100).toFixed(0)}%</div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
      <SectionHead>How it works</SectionHead>
      <div className="pe-hint pe-hint-block">
        Fit review: structured JSON (pass · reason · confidence · matches · gaps) from the active LLM against the candidate profile.
        On pass, a second polish call restructures the JD into a tailored brief.
      </div>
      <ScopedEvents events={events} scopes={['qa', 'inventory']} />
    </>
  );
}

function TailorStageInspector({ stageId, live, events }: {
  stageId: string;
  live: LiveStatus;
  events: PipelineEvent[];
}) {
  const def = TAILOR_STAGE_DEFS.find((s) => s.id === stageId);
  return (
    <>
      <MetricRow items={[
        { label: 'State', value: live.tailoringRunning ? 'Running' : 'Idle', tone: live.tailoringRunning ? 'accent' : 'muted' },
        { label: 'Queue', value: fmt(live.tailoringQueue) },
        { label: 'Kind', value: def?.llm ? 'LLM' : 'mechanical', tone: def?.llm ? 'accent' : 'muted' },
      ]} />
      {live.tailoringJob && (
        <div className="pe-tag-line"><Target size={11} style={{ opacity: .5 }} /><span className="pe-tag-line-mono">{live.tailoringJob}</span></div>
      )}
      <SectionHead>Role</SectionHead>
      <div className="pe-hint pe-hint-block">{def?.desc}</div>
      {live.tailoringRunning && live.tailoringLogTail && (
        <>
          <SectionHead>Live output</SectionHead>
          <LogTail content={live.tailoringLogTail} />
        </>
      )}
      <ScopedEvents events={events} scopes={['tailor', 'qa']} />
    </>
  );
}

// ─── Presentational helpers ──────────────────────────────────────────
function SectionHead({ children }: { children: React.ReactNode }) {
  return <div className="pe-section-head">{children}</div>;
}

function MetricRow({ items }: { items: { label: string; value: string; tone?: 'green' | 'red' | 'amber' | 'accent' | 'muted' }[] }) {
  return (
    <div className="pe-metric-row">
      {items.map((it, i) => (
        <div key={i} className={`pe-metric pe-metric-${it.tone ?? 'muted'}`}>
          <div className="pe-metric-label">{it.label}</div>
          <div className="pe-metric-value">{it.value}</div>
        </div>
      ))}
    </div>
  );
}

function LabelInput({ label, value, onChange, type = 'text', step }: {
  label: string; value: string | number; onChange: (v: string) => void; type?: 'text' | 'number'; step?: number;
}) {
  return (
    <label className="pe-input">
      <span>{label}</span>
      <input type={type} step={step} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return <button className={`pe-toggle${on ? ' is-on' : ''}`} onClick={onToggle} aria-pressed={on} type="button"><span /></button>;
}

function ToggleRow({ label, on, onToggle }: { label: string; on: boolean; onToggle: () => void }) {
  return (
    <div className="pe-toggle-row">
      <span>{label}</span>
      <Toggle on={on} onToggle={onToggle} />
    </div>
  );
}

function TagList({ items, onUpdate }: { items: string[]; onUpdate: (v: string[]) => void }) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const v = draft.trim();
    if (!v || items.includes(v)) return;
    onUpdate([...items, v]);
    setDraft('');
  };
  return (
    <div className="pe-tags">
      <div className="pe-tags-row">
        {items.map((item, i) => (
          <span key={`${item}-${i}`} className="pe-tag">
            {item}
            <button type="button" onClick={() => onUpdate(items.filter((_, j) => j !== i))} aria-label={`remove ${item}`}><X size={10} /></button>
          </span>
        ))}
      </div>
      <div className="pe-tags-add">
        <input value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
          placeholder="add tag…" />
        <button type="button" onClick={add}><Plus size={12} /></button>
      </div>
    </div>
  );
}

function EventList({ events, emptyLabel }: { events: PipelineEvent[]; emptyLabel: string }) {
  if (events.length === 0) {
    return <div className="pe-empty"><Activity size={16} /> <span>{emptyLabel}</span></div>;
  }
  return (
    <div className="pe-events">
      {events.map((ev) => (
        <div key={ev.id} className={`pe-event pe-event-${ev.tone}`}>
          <div className="pe-event-head">
            <span className="pe-event-label">{ev.label}</span>
            <span className="pe-event-time">{timeSince(ev.createdAt)}</span>
          </div>
          {ev.detail && <div className="pe-event-detail">{ev.detail}</div>}
        </div>
      ))}
    </div>
  );
}

function ScopedEvents({ events, scopes }: { events: PipelineEvent[]; scopes: EventScope[] }) {
  const filtered = events.filter((e) => scopes.includes(e.scope)).slice(0, 6);
  return (
    <>
      <SectionHead>Recent activity</SectionHead>
      <EventList events={filtered} emptyLabel="No recent activity here" />
    </>
  );
}

function LogTail({ content }: { content: string }) {
  if (!content) return null;
  return <pre className="pe-log">{content}</pre>;
}

// ─── Toolbar ─────────────────────────────────────────────────────────
function Toolbar({
  live, dirty, saving, refreshing, readyCount, activeRunId,
  onRefresh, onReset, onSave, onRunScrape, onTerminate, onRunQA, onCancelQA, onRunTailor, onStopTailor,
  onFit,
}: {
  live: LiveStatus; dirty: boolean; saving: boolean; refreshing: boolean; readyCount: number; activeRunId: string | null;
  onRefresh: () => void; onReset: () => void; onSave: () => void;
  onRunScrape: () => void; onTerminate: () => void;
  onRunQA: () => void; onCancelQA: () => void;
  onRunTailor: () => void; onStopTailor: () => void;
  onFit: () => void;
}) {
  return (
    <header className="pe-toolbar">
      <div className="pe-toolbar-brand">
        <div className="pe-toolbar-eyebrow">TexTailor · orchestration</div>
        <h1 className="pe-toolbar-title">Pipeline console</h1>
      </div>

      <div className="pe-toolbar-phases">
        <PhaseAction
          label="Discover"
          color="var(--accent)"
          running={live.scrapeRunning}
          detail={live.scrapeRunning && live.scrapeStartedAt ? `running ${timeAgo(live.scrapeStartedAt)}` : 'scrape sources'}
          onRun={onRunScrape}
          onStop={onTerminate}
          stopDisabled={!activeRunId && !live.scrapeRunning}
          runDisabled={dirty}
          runTooltip={dirty ? 'Save config first' : undefined}
        />
        <PhaseAction
          label="Review"
          color="var(--cyan)"
          running={live.qaReviewRunning}
          detail={live.qaReviewRunning && live.qaReviewProgress
            ? `${live.qaReviewProgress.completed}/${live.qaReviewProgress.total}`
            : 'LLM fit review'}
          onRun={onRunQA}
          onStop={onCancelQA}
        />
        <PhaseAction
          label="Tailor"
          color="var(--orange)"
          running={live.tailoringRunning}
          detail={live.tailoringRunning
            ? (live.tailoringJob || `queue: ${fmt(live.tailoringQueue)}`)
            : readyCount > 0 ? `${fmt(readyCount)} ready` : 'generate packages'}
          onRun={onRunTailor}
          onStop={onStopTailor}
        />
      </div>

      <div className="pe-toolbar-utilities">
        {dirty && (
          <>
            <button className="pe-btn" onClick={onReset} disabled={saving}><RotateCcw size={12} /> Reset</button>
            <button className="pe-btn pe-btn-primary" onClick={onSave} disabled={saving}>
              <Save size={12} /> {saving ? 'Saving…' : 'Save config'}
            </button>
          </>
        )}
        <button className="pe-btn" onClick={onFit} title="Fit view">Fit</button>
        <button className="pe-btn" onClick={onRefresh} disabled={refreshing} title="Refresh">
          <RefreshCcw size={12} className={refreshing ? 'is-spinning' : ''} />
        </button>
      </div>
    </header>
  );
}

function PhaseAction({
  label, color, running, detail, onRun, onStop, stopDisabled, runDisabled, runTooltip,
}: {
  label: string; color: string; running: boolean; detail: string;
  onRun: () => void; onStop: () => void;
  stopDisabled?: boolean; runDisabled?: boolean; runTooltip?: string;
}) {
  return (
    <div className={`pe-phase-action${running ? ' is-running' : ''}`} style={{ ['--phase' as any]: color }}>
      <span className="pe-phase-action-stripe" />
      <div className="pe-phase-action-copy">
        <div className="pe-phase-action-label">
          {running ? <span className="pe-dot pe-dot-live" style={{ background: color }} /> : <span className="pe-dot pe-dot-idle" />}
          {label}
        </div>
        <div className="pe-phase-action-detail">{detail}</div>
      </div>
      {running ? (
        <button className="pe-btn pe-btn-danger" onClick={onStop} disabled={stopDisabled}>
          <Square size={12} /> Stop
        </button>
      ) : (
        <button className="pe-btn pe-btn-run" onClick={onRun} disabled={runDisabled} title={runTooltip}>
          <Play size={12} /> Run
        </button>
      )}
    </div>
  );
}

// ─── Canvas ──────────────────────────────────────────────────────────
function Canvas({ nodes, edges, onPaneClick, onNodeDragStop, onFitReady }: {
  nodes: Node[];
  edges: Edge[];
  onPaneClick: () => void;
  onNodeDragStop: (_: any, node: Node) => void;
  onFitReady: (fn: () => void) => void;
}) {
  const { fitView } = useReactFlow();
  const fitRef = useRef(fitView);
  fitRef.current = fitView;
  useEffect(() => {
    onFitReady(() => fitRef.current({ padding: 0.12, maxZoom: 0.95 }));
  }, [onFitReady]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onPaneClick={onPaneClick}
      onNodeDragStop={onNodeDragStop}
      fitView
      fitViewOptions={{ padding: 0.12, maxZoom: 0.95 }}
      proOptions={{ hideAttribution: true }}
      minZoom={0.35}
      maxZoom={1.3}
      defaultEdgeOptions={{ animated: false }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border-bright)" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

// ─── Top-level flow indicator (between columns) ─────────────────────
function FlowLegend() {
  return (
    <div className="pe-flow-legend">
      <span>Discover</span><ArrowRight size={12} />
      <span>Ingest</span><ArrowRight size={12} />
      <span>Review</span><ArrowRight size={12} />
      <span>Tailor</span>
    </div>
  );
}

// ─── Main view ──────────────────────────────────────────────────────
export default function PipelineEditorView() {
  const [config, setConfig] = useState<ScraperConfig | null>(null);
  const [origConfig, setOrigConfig] = useState<ScraperConfig | null>(null);
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [qaStatus, setQaStatus] = useState<QALlmReviewStatus | null>(null);
  const [live, setLive] = useState<LiveStatus>(INITIAL_LIVE_STATUS);
  const [selectedNode, setSelectedNode] = useState<{ id: string; type: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<any>(null);
  const snapshotRef = useRef<{ live: LiveStatus; stats: PipelineStats | null } | null>(null);
  const fitViewRef = useRef<() => void>(() => {});

  const refreshLive = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const [nextStats, scrape, qa, tailor, run] = await Promise.all([
        api.getScraperPipelineStats().catch(() => null),
        api.getScrapeRunnerStatus().catch(() => null),
        api.getQALlmReviewStatus().catch(() => null),
        api.getTailoringRunnerStatus().catch(() => null),
        api.getActiveRun().catch(() => null),
      ]);
      const nextLive = buildLiveStatus(scrape, qa, tailor);
      setStats(nextStats);
      setQaStatus(qa);
      setLive(nextLive);
      setActiveRun(run);
      const freshEvents = buildPipelineEvents(snapshotRef.current, { live: nextLive, stats: nextStats });
      if (freshEvents.length > 0) setEvents((prev) => [...freshEvents.reverse(), ...prev].slice(0, 24));
      snapshotRef.current = { live: nextLive, stats: nextStats };
    } catch { /* silent */ }
    finally { if (manual) setRefreshing(false); }
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([
      api.getScraperConfig(),
      api.getScraperPipelineStats().catch(() => null),
      api.getScrapeRunnerStatus().catch(() => null),
      api.getQALlmReviewStatus().catch(() => null),
      api.getTailoringRunnerStatus().catch(() => null),
      api.getActiveRun().catch(() => null),
    ]).then(([cfg, st, scrape, qa, tailor, run]) => {
      if (!alive) return;
      const nextLive = buildLiveStatus(scrape, qa, tailor);
      setConfig(cfg);
      setOrigConfig(JSON.parse(JSON.stringify(cfg)));
      setStats(st);
      setQaStatus(qa);
      setLive(nextLive);
      setActiveRun(run);
      snapshotRef.current = { live: nextLive, stats: st };
    }).catch((e) => setError(e?.message || String(e)));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const id = setInterval(() => { void refreshLive(false); }, 4000);
    return () => clearInterval(id);
  }, [refreshLive]);

  const dirty = useMemo(() => {
    if (!config || !origConfig) return false;
    return JSON.stringify(config) !== JSON.stringify(origConfig);
  }, [config, origConfig]);

  const sourceStats = useMemo(() => aggregateSourceStats(stats?.per_source), [stats]);

  const handleSelect = useCallback((id: string, type: string) => {
    setSelectedNode((prev) => (prev?.id === id ? null : { id, type }));
  }, []);

  const handleConfigChange = useCallback((patch: Partial<ScraperConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const handleSave = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    try {
      const result = await api.saveScraperConfig(config);
      if (result.ok) {
        setOrigConfig(JSON.parse(JSON.stringify(result.config)));
        setConfig(result.config);
      }
    } catch (e: any) { setError(e?.message || String(e)); }
    setSaving(false);
  }, [config]);

  const handleReset = useCallback(() => {
    if (origConfig) setConfig(JSON.parse(JSON.stringify(origConfig)));
  }, [origConfig]);

  const handleRunScrape = useCallback(async () => {
    try { await api.runScrapeNow(true); void refreshLive(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refreshLive]);

  const handleTerminate = useCallback(async () => {
    if (!activeRun?.run_id) return;
    try { await api.terminateRun(activeRun.run_id); void refreshLive(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [activeRun, refreshLive]);

  const handleRunQA = useCallback(async () => {
    try {
      const pending = await api.getQAPending();
      const ids = (pending.jobs || []).map((j: any) => j.id);
      if (ids.length === 0) return;
      await api.llmReviewQA(ids);
      void refreshLive(true);
    } catch (e: any) { setError(e?.message || String(e)); }
  }, [refreshLive]);

  const handleCancelQA = useCallback(async () => {
    try { await api.cancelQAReview(); void refreshLive(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refreshLive]);

  const handleRunTailor = useCallback(async () => {
    try { await api.runTailoringLatest(); void refreshLive(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refreshLive]);

  const handleStopTailor = useCallback(async () => {
    try { await api.stopTailoringRunner({ clear_queue: true }); void refreshLive(true); }
    catch (e: any) { setError(e?.message || String(e)); }
  }, [refreshLive]);

  const nodes = useMemo(() => {
    if (!config) return [];
    return buildNodes(config, stats, live, sourceStats, handleSelect);
  }, [config, stats, live, sourceStats, handleSelect]);

  const edges = useMemo(() => {
    if (!config) return [];
    return buildEdges(config, live);
  }, [config, live]);

  const handleNodeDragStop = useCallback((_: any, node: Node) => {
    if (!config) return;
    const stageIdx = config.pipeline_order.indexOf(node.id);
    if (stageIdx < 0) return;
    const positions = config.pipeline_order.map((id) => ({
      id,
      y: id === node.id ? (node.position?.y ?? 0) : ROW_Y0 + config.pipeline_order.indexOf(id) * ROW_GAP,
    }));
    positions.sort((a, b) => a.y - b.y);
    const newOrder = positions.map((p) => p.id);
    if (JSON.stringify(newOrder) !== JSON.stringify(config.pipeline_order)) {
      setConfig((prev) => (prev ? { ...prev, pipeline_order: newOrder } : prev));
    }
  }, [config]);

  if (error) {
    return (
      <div className="view-container"><div className="pe-error">Error: {error}</div></div>
    );
  }

  if (!config) {
    return (
      <div className="view-container"><div className="loading"><div className="spinner" /></div></div>
    );
  }

  return (
    <div className="pe-root">
      <ReactFlowProvider>
        <Toolbar
          live={live}
          dirty={dirty}
          saving={saving}
          refreshing={refreshing}
          readyCount={stats?.inventory?.qa_approved ?? 0}
          activeRunId={activeRun?.run_id ?? null}
          onRefresh={() => { void refreshLive(true); }}
          onReset={handleReset}
          onSave={() => { void handleSave(); }}
          onRunScrape={() => { void handleRunScrape(); }}
          onTerminate={() => { void handleTerminate(); }}
          onRunQA={() => { void handleRunQA(); }}
          onCancelQA={() => { void handleCancelQA(); }}
          onRunTailor={() => { void handleRunTailor(); }}
          onStopTailor={() => { void handleStopTailor(); }}
          onFit={() => fitViewRef.current()}
        />
        <div className="pe-workspace">
          <div className="pe-canvas-wrap">
            <FlowLegend />
            <Canvas
              nodes={nodes}
              edges={edges}
              onPaneClick={() => setSelectedNode(null)}
              onNodeDragStop={handleNodeDragStop}
              onFitReady={(fn) => { fitViewRef.current = fn; }}
            />
          </div>
          <Inspector
            selectedNode={selectedNode}
            onClear={() => setSelectedNode(null)}
            config={config}
            stats={stats}
            qaStatus={qaStatus}
            live={live}
            events={events}
            sourceStats={sourceStats}
            onConfigChange={handleConfigChange}
          />
        </div>
      </ReactFlowProvider>
    </div>
  );
}
