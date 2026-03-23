import { useEffect, useState, useCallback, useMemo, memo, useRef } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
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
  HardDrive, Settings, X, GripVertical,
  Briefcase, Shield, Activity, Plus, Brain, Sparkles, CheckCircle, XCircle,
  Microscope, Target, PenTool, Mail, ShieldCheck, Printer,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
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
  hard_filters: { domain_blocklist: string[]; title_blocklist: string[]; content_blocklist: string[]; min_salary_k: number };
  filter: { title_keywords: string[]; title_role_words: string[]; require_remote: boolean; require_us_location: boolean; min_jd_chars: number; max_experience_years: number; score_accept_threshold: number; score_reject_threshold: number };
  seen_ttl_days: number;
  target_max_results: number;
  pipeline_order: string[];
  llm_review: Record<string, any>;
  crawl: { enabled: boolean; request_delay: number; max_results_per_target: number };
}

interface QALlmReviewStatus {
  running: boolean;
  batch_id: number;
  started_at: string | null;
  ended_at: string | null;
  resolved_model: string | null;
  active_job: { job_id: number; title?: string; status: string } | null;
  items?: QAReviewItem[];
  summary: { total: number; queued: number; reviewing: number; completed: number; passed: number; failed: number; skipped: number; errors: number };
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

type InspectorTab = 'overview' | 'configure' | 'activity';
type PipelineEventTone = 'accent' | 'green' | 'red' | 'amber' | 'muted';
type PipelineEventScope = 'scrape' | 'inventory' | 'qa' | 'tailor';

interface PipelineEvent {
  id: string;
  label: string;
  detail?: string;
  tone: PipelineEventTone;
  scope: PipelineEventScope;
  createdAt: number;
}

interface SourceRollupStats {
  searxng: number;
  ashby: number;
  greenhouse: number;
  lever: number;
  usajobs: number;
}

interface PipelineSnapshot {
  live: LiveStatus;
  stats: PipelineStats | null;
}

// ---------------------------------------------------------------------------
// Source definitions
// ---------------------------------------------------------------------------
const SOURCE_DEFS = [
  { id: 'searxng', label: 'SearXNG', icon: Search, countKey: 'queries' as const },
  { id: 'ashby', label: 'Ashby', icon: Briefcase, countKey: 'boards' as const },
  { id: 'greenhouse', label: 'Greenhouse', icon: Globe, countKey: 'boards' as const },
  { id: 'lever', label: 'Lever', icon: Activity, countKey: 'boards' as const },
  { id: 'usajobs', label: 'USAJobs', icon: Shield, countKey: 'usajobs' as const },
];

const STAGE_DEFS = [
  { id: 'text_extraction', label: 'Text Extraction', desc: 'Extract JD text from HTML', icon: FileText },
  { id: 'dedup', label: 'Deduplication', desc: 'URL dedup with TTL window', icon: Fingerprint },
  { id: 'hard_filter', label: 'Hard Filters', desc: 'Domain, seniority, salary', icon: Filter },
  { id: 'storage', label: 'Storage', desc: 'Persist to SQLite', icon: HardDrive },
];

const TAILOR_STAGE_DEFS = [
  { id: 'tailor_analysis', label: 'Analysis', desc: 'Extract JD requirements', icon: Microscope },
  { id: 'tailor_strategy', label: 'Strategy', desc: 'Plan resume targeting', icon: Target },
  { id: 'tailor_resume', label: 'Resume Draft', desc: 'LaTeX generation', icon: PenTool },
  { id: 'tailor_cover', label: 'Cover Letter', desc: 'LaTeX generation', icon: Mail },
  { id: 'tailor_validate', label: 'Validation', desc: 'Hard gates check', icon: ShieldCheck },
  { id: 'tailor_compile', label: 'Compile', desc: 'pdflatex → PDF', icon: Printer },
];

const SEARCH_PROVIDER_KEYS = new Set([
  'google',
  'startpage',
  'duckduckgo',
  'brave',
  'bing',
  'searxng',
  'qwant',
  'yahoo',
]);

const EMPTY_SOURCE_STATS: SourceRollupStats = {
  searxng: 0,
  ashby: 0,
  greenhouse: 0,
  lever: 0,
  usajobs: 0,
};

const INITIAL_LIVE_STATUS: LiveStatus = {
  scrapeRunning: false,
  scrapeStartedAt: null,
  scrapeLogTail: '',
  qaReviewRunning: false,
  qaReviewModel: null,
  qaReviewProgress: null,
  qaReviewItems: [],
  tailoringRunning: false,
  tailoringJob: null,
  tailoringQueue: 0,
  tailoringLogTail: '',
};

function toneForDelta(delta: number): PipelineEventTone {
  if (delta > 0) return 'green';
  if (delta < 0) return 'amber';
  return 'muted';
}

function pluralize(value: number, label: string) {
  return `${fmt(value)} ${label}${value === 1 ? '' : 's'}`;
}

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

function pushEvent(
  bucket: PipelineEvent[],
  {
    label,
    detail,
    tone,
    scope,
    now,
  }: {
    label: string;
    detail?: string;
    tone: PipelineEventTone;
    scope: PipelineEventScope;
    now: number;
  },
) {
  bucket.push({
    id: `${scope}-${label}-${now}-${bucket.length}`,
    label,
    detail,
    tone,
    scope,
    createdAt: now,
  });
}

function buildPipelineEvents(prev: PipelineSnapshot | null, next: PipelineSnapshot): PipelineEvent[] {
  if (!prev) return [];
  const events: PipelineEvent[] = [];
  const now = Date.now();

  if (prev.live.scrapeRunning !== next.live.scrapeRunning) {
    pushEvent(events, {
      label: next.live.scrapeRunning ? 'Scrape started' : 'Scrape stopped',
      detail: next.live.scrapeRunning ? 'Source-to-storage lane is active.' : 'Waiting for the next run.',
      tone: next.live.scrapeRunning ? 'accent' : 'muted',
      scope: 'scrape',
      now,
    });
  }

  if (prev.live.qaReviewRunning !== next.live.qaReviewRunning) {
    pushEvent(events, {
      label: next.live.qaReviewRunning ? 'QA review started' : 'QA review stopped',
      detail: next.live.qaReviewRunning ? 'Review queue is being processed.' : 'LLM review lane is idle.',
      tone: next.live.qaReviewRunning ? 'accent' : 'muted',
      scope: 'qa',
      now,
    });
  }

  if (prev.live.tailoringRunning !== next.live.tailoringRunning) {
    pushEvent(events, {
      label: next.live.tailoringRunning ? 'Tailoring started' : 'Tailoring stopped',
      detail: next.live.tailoringRunning ? (next.live.tailoringJob || 'Package generation is active.') : 'No package is currently rendering.',
      tone: next.live.tailoringRunning ? 'accent' : 'muted',
      scope: 'tailor',
      now,
    });
  }

  if (prev.live.tailoringQueue !== next.live.tailoringQueue) {
    pushEvent(events, {
      label: `Tailoring queue ${prev.live.tailoringQueue} -> ${next.live.tailoringQueue}`,
      detail: next.live.tailoringQueue > prev.live.tailoringQueue ? 'More approved jobs were queued.' : 'Queue is draining.',
      tone: toneForDelta(prev.live.tailoringQueue - next.live.tailoringQueue),
      scope: 'tailor',
      now,
    });
  }

  const prevCompleted = prev.live.qaReviewProgress?.completed ?? 0;
  const nextCompleted = next.live.qaReviewProgress?.completed ?? 0;
  if (nextCompleted > prevCompleted) {
    pushEvent(events, {
      label: `QA reviewed +${nextCompleted - prevCompleted}`,
      detail: `${nextCompleted}/${next.live.qaReviewProgress?.total ?? nextCompleted} completed in the current batch.`,
      tone: 'green',
      scope: 'qa',
      now,
    });
  }

  const prevInv = prev.stats?.inventory;
  const nextInv = next.stats?.inventory;
  if (prevInv && nextInv) {
    if (nextInv.qa_approved > prevInv.qa_approved) {
      pushEvent(events, {
        label: `QA approved +${nextInv.qa_approved - prevInv.qa_approved}`,
        detail: `${fmt(nextInv.qa_approved)} jobs are ready for tailoring.`,
        tone: 'green',
        scope: 'qa',
        now,
      });
    }
    if (nextInv.qa_rejected > prevInv.qa_rejected) {
      pushEvent(events, {
        label: `QA rejected +${nextInv.qa_rejected - prevInv.qa_rejected}`,
        detail: `${fmt(nextInv.qa_rejected)} jobs are now in the rejected bucket.`,
        tone: 'red',
        scope: 'qa',
        now,
      });
    }
    if (nextInv.qa_pending !== prevInv.qa_pending) {
      pushEvent(events, {
        label: `Awaiting QA ${prevInv.qa_pending} -> ${nextInv.qa_pending}`,
        detail: nextInv.qa_pending > prevInv.qa_pending ? 'The review backlog grew.' : 'The review backlog shrank.',
        tone: toneForDelta(prevInv.qa_pending - nextInv.qa_pending),
        scope: 'inventory',
        now,
      });
    }
    if (nextInv.total > prevInv.total) {
      pushEvent(events, {
        label: `Stored jobs +${nextInv.total - prevInv.total}`,
        detail: `${fmt(nextInv.total)} total rows are now in the results DB.`,
        tone: 'green',
        scope: 'inventory',
        now,
      });
    }
  }

  return events;
}

function eventMatchesSelection(event: PipelineEvent, selectedNode: { id: string; type: string } | null) {
  if (!selectedNode) return true;
  if (selectedNode.type === 'source' || selectedNode.type === 'stage' || selectedNode.type === 'dbOutput') {
    return event.scope === 'scrape' || event.scope === 'inventory';
  }
  if (selectedNode.type === 'qaReview') {
    return event.scope === 'qa' || event.scope === 'inventory';
  }
  return event.scope === 'tailor' || event.scope === 'qa';
}

function getNodeDisplayName(node: { id: string; type: string } | null) {
  if (!node) return 'Pipeline Overview';
  if (node.type === 'source') return SOURCE_DEFS.find((item) => item.id === node.id)?.label || node.id;
  if (node.type === 'stage') return STAGE_DEFS.find((item) => item.id === node.id)?.label || node.id;
  if (node.type === 'dbOutput') return 'Results DB';
  if (node.type === 'qaReview') return 'QA LLM Review';
  return TAILOR_STAGE_DEFS.find((item) => item.id === node.id)?.label || node.id;
}

// ---------------------------------------------------------------------------
// Custom Nodes
// ---------------------------------------------------------------------------
function SwimlaneNodeComponent({ data }: NodeProps) {
  const d = data as any;
  return (
    <div className={`pn-lane pn-lane-${d.tone}${d.active ? ' pn-lane-active' : ''}`}>
      <div className="pn-lane-label">{d.label}</div>
      <div className="pn-lane-subtitle">{d.subtitle}</div>
      {d.active ? (
        <div className="pn-lane-pill">
          <span className="pn-live-dot" /> active
        </div>
      ) : null}
    </div>
  );
}

function SourceNodeComponent({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div className={`pn-card pn-card-source${selected ? ' pn-selected' : ''}${d.enabled === false ? ' pn-disabled' : ''}`}
         onClick={d.onSelect}>
      <div className="pn-header">
        <div className="pn-icon pn-icon-source">
          {d.iconEl}
        </div>
        <div className="pn-title-block">
          <div className="pn-title">{d.label}</div>
          <div className="pn-subtitle">{d.count} {d.countLabel}</div>
        </div>
        <div className={`pn-badge pn-badge-status pn-badge-${d.enabled ? (d.active ? 'accent' : 'muted') : 'muted'}`}>
          {d.enabled ? (d.active ? 'active' : 'ready') : 'off'}
        </div>
        <div className="pn-toggle" onClick={(e) => { e.stopPropagation(); d.onToggle?.(); }}>
          <div className={`pn-switch${d.enabled !== false ? ' pn-switch-on' : ''}`} />
        </div>
      </div>
      <div className="pn-body pn-body-stack pn-body-emphasis">
        <div className="pn-kpi">
          <div className="pn-kpi-value">{fmt(d.stat)}</div>
          <div className="pn-kpi-label">items last run</div>
        </div>
        <div className="pn-stat">
          <div className="pn-stat-dot" style={{ background: d.enabled ? 'var(--green)' : 'var(--text-secondary)' }} />
          <span className="pn-stat-value">{d.enabled ? 'enabled' : 'disabled'}</span>
          <span>{d.count} {d.countLabel}</span>
        </div>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function StageNodeComponent({ data, selected }: NodeProps) {
  const d = data as any;
  const primaryValue = d.passCount != null ? fmt(d.passCount) : d.dropCount != null ? fmt(d.dropCount) : String(d.order);
  const primaryLabel = d.passCount != null ? 'pass' : d.dropCount != null ? 'drop' : 'order';
  return (
    <div className={`pn-card pn-card-stage${selected ? ' pn-selected' : ''}${d.active ? ' pn-card-active' : ''}`} onClick={d.onSelect}>
      <div className="pn-header">
        <div className="pn-drag-hint">
          <GripVertical size={12} />
        </div>
        <div className="pn-icon pn-icon-stage">
          {d.iconEl}
        </div>
        <div className="pn-title-block">
          <div className="pn-title">{d.label}</div>
          <div className="pn-subtitle">{d.desc}</div>
        </div>
        <div className="pn-badge">#{d.order}</div>
      </div>
      <div className="pn-body pn-body-emphasis">
        <div className="pn-kpi">
          <div className="pn-kpi-value">{primaryValue}</div>
          <div className="pn-kpi-label">{primaryLabel}</div>
        </div>
        {(d.passCount != null || d.dropCount != null) && (
          <div className="pn-stat-row">
          {d.passCount != null && (
            <div className="pn-stat">
              <div className="pn-stat-dot" style={{ background: 'var(--green)' }} />
              <span className="pn-stat-value">{d.passCount}</span> pass
            </div>
          )}
          {d.dropCount != null && (
            <div className="pn-stat">
              <div className="pn-stat-dot" style={{ background: 'var(--red)' }} />
              <span className="pn-stat-value">{d.dropCount}</span> drop
            </div>
          )}
          </div>
        )}
      </div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function OutputNodeComponent({ data, selected }: NodeProps) {
  const d = data as any;
  const inv = d.inventory;
  return (
    <div className={`pn-card pn-card-output${selected ? ' pn-selected' : ''}${d.active ? ' pn-card-active' : ''}`} onClick={d.onSelect}>
      <div className="pn-header">
        <div className="pn-icon pn-icon-output">
          <Database size={14} />
        </div>
        <div className="pn-title-block">
          <div className="pn-title">Results DB</div>
          <div className="pn-subtitle">{fmt(inv?.total)} stored jobs</div>
        </div>
      </div>
      {inv && (
        <div className="pn-body pn-body-emphasis">
          <div className="pn-kpi">
            <div className="pn-kpi-value">{fmt(inv.qa_pending)}</div>
            <div className="pn-kpi-label">awaiting QA</div>
          </div>
          <div className="pn-stat">
            <div className="pn-stat-dot" style={{ background: 'var(--green)' }} />
            <span className="pn-stat-value">{inv.qa_approved}</span>
            <span>ready</span>
          </div>
          <div className="pn-stat">
            <div className="pn-stat-dot" style={{ background: 'var(--text-secondary)' }} />
            <span className="pn-stat-value">{inv.rejected}</span>
            <span>scraper-rejected</span>
          </div>
        </div>
      )}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} id="right" />
      <Handle type="source" position={Position.Bottom} id="bottom" />
    </div>
  );
}

function QAReviewNodeComponent({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div className={`pn-card pn-card-qa${selected ? ' pn-selected' : ''}${d.running ? ' pn-card-active' : ''}`} onClick={d.onSelect}>
      <div className="pn-header">
        <div className="pn-icon" style={{ background: 'rgba(139, 124, 246, .12)', color: 'var(--purple)' }}>
          <Brain size={16} />
        </div>
        <div className="pn-title-block">
          <div className="pn-title">QA LLM Review</div>
          <div className="pn-subtitle">Candidate-job fit eval</div>
        </div>
        {d.running && (
          <div className="pn-badge pn-live-badge">
            <span className="pn-live-dot" /> live
          </div>
        )}
      </div>
      <div className="pn-body pn-body-emphasis">
        <div className="pn-kpi">
          <div className="pn-kpi-value">{fmt(d.pending)}</div>
          <div className="pn-kpi-label">pending</div>
        </div>
        {d.running && d.model && (
          <div className="pn-stat">
            <Brain size={10} style={{ opacity: .4 }} />
            <span className="pn-stat-value" style={{ fontSize: '.65rem' }}>{d.model.split('/').pop()}</span>
          </div>
        )}
        {d.running && d.progress && (
          <div className="pn-stat">
            <span style={{ opacity: .5 }}>progress</span>
            <span className="pn-stat-value">{d.progress.completed}/{d.progress.total}</span>
          </div>
        )}
        {d.passed != null && (
          <div className="pn-stat">
            <div className="pn-stat-dot" style={{ background: 'var(--green)' }} />
            <span className="pn-stat-value">{d.passed}</span>
            <span>approved</span>
          </div>
        )}
        {d.failed != null && (
          <div className="pn-stat">
            <div className="pn-stat-dot" style={{ background: 'var(--red)' }} />
            <span className="pn-stat-value">{d.failed}</span>
            <span>rejected</span>
          </div>
        )}
      </div>
      <Handle type="target" position={Position.Top} id="top" />
      <Handle type="source" position={Position.Bottom} id="bottom" />
    </div>
  );
}

function TailorStageNodeComponent({ data, selected }: NodeProps) {
  const d = data as any;
  return (
    <div className={`pn-card pn-card-tailor${selected ? ' pn-selected' : ''}${d.entryActive ? ' pn-card-tailor-entry-active' : ''}${d.active ? ' pn-card-active' : ''}`} onClick={d.onSelect}>
      <div className="pn-header">
        <div className="pn-icon" style={{ background: 'rgba(139, 124, 246, .12)', color: 'var(--purple)' }}>
          {d.iconEl}
        </div>
        <div className="pn-title-block">
          <div className="pn-title">{d.label}</div>
          <div className="pn-subtitle">{d.desc}</div>
        </div>
        {d.entryActive ? (
          <div className="pn-badge pn-live-badge">
            <span className="pn-live-dot" /> entry
          </div>
        ) : (
          <div className="pn-badge">#{d.order}</div>
        )}
      </div>
      <div className="pn-body pn-body-emphasis">
        {d.isFirst ? (
          <>
            <div className="pn-kpi">
              <div className="pn-kpi-value">{fmt(d.queue)}</div>
              <div className="pn-kpi-label">queued</div>
            </div>
            {d.running && d.job && (
              <div className="pn-stat">
                <Sparkles size={10} style={{ opacity: .4 }} />
                <span className="pn-stat-value" style={{ fontSize: '.65rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.job}</span>
              </div>
            )}
            {d.approved != null && (
              <div className="pn-stat">
                <div className="pn-stat-dot" style={{ background: 'var(--green)' }} />
                <span className="pn-stat-value">{d.approved}</span> ready
              </div>
            )}
          </>
        ) : (
          <div className="pn-kpi pn-kpi-compact">
            <div className="pn-kpi-label">step</div>
            <div className="pn-kpi-value">{d.order}</div>
          </div>
        )}
      </div>
      <Handle type="target" position={d.handleIn ?? Position.Left} id="target" />
      {!d.isLast && <Handle type="source" position={d.handleOut ?? Position.Right} id="source" />}
    </div>
  );
}

const nodeTypes = {
  swimlane: memo(SwimlaneNodeComponent),
  source: memo(SourceNodeComponent),
  stage: memo(StageNodeComponent),
  dbOutput: memo(OutputNodeComponent),
  qaReview: memo(QAReviewNodeComponent),
  tailorStage: memo(TailorStageNodeComponent),
};

// ---------------------------------------------------------------------------
// Config Sidebar Panel
// ---------------------------------------------------------------------------
function ConfigPanel({ nodeId, nodeType, config, stats, qaStatus, live, onChange, onClose }: {
  nodeId: string;
  nodeType: string;
  config: ScraperConfig;
  stats: PipelineStats | null;
  qaStatus: QALlmReviewStatus | null;
  live: LiveStatus;
  onChange: (patch: Partial<ScraperConfig>) => void;
  onClose: () => void;
}) {
  if (nodeType === 'source') return <SourcePanel sourceId={nodeId} config={config} onChange={onChange} onClose={onClose} />;
  if (nodeType === 'stage') return <StagePanel stageId={nodeId} config={config} onChange={onChange} onClose={onClose} />;
  if (nodeType === 'dbOutput') return <OutputPanel stats={stats} onClose={onClose} />;
  if (nodeType === 'qaReview') return <QAReviewPanel qaStatus={qaStatus} liveItems={live.qaReviewItems} onClose={onClose} />;
  if (nodeType === 'tailorStage') return <TailorStagePanel stageId={nodeId} live={live} onClose={onClose} />;
  return null;
}

function SourcePanel({ sourceId, config, onChange, onClose }: {
  sourceId: string; config: ScraperConfig; onChange: (p: Partial<ScraperConfig>) => void; onClose: () => void;
}) {
  if (sourceId === 'searxng') {
    const s = config.searxng;
    const update = (k: string, v: any) => onChange({ searxng: { ...s, [k]: v } });
    return (
      <div className="pipeline-sidebar">
        <SidebarHeader title="SearXNG" onClose={onClose} />
        <div className="ps-body">
          <div className="ps-section">
            <div className="ps-section-title">Settings</div>
            <Field label="Engines" value={s.engines} onChange={v => update('engines', v)} />
            <Field label="Time Range" value={s.time_range} onChange={v => update('time_range', v)} />
            <NumberField label="Request Delay (s)" value={s.request_delay} step={0.5} onChange={v => update('request_delay', v)} />
            <NumberField label="Timeout (s)" value={s.timeout} onChange={v => update('timeout', v)} />
          </div>
          <div className="ps-section">
            <div className="ps-section-title">Queries ({config.queries.length})</div>
            <div className="ps-board-list">
              {config.queries.map((q, i) => (
                <div key={i} className="ps-board-item">
                  <Search size={12} style={{ opacity: .4, flexShrink: 0 }} />
                  <div className="ps-board-name">{q.title_phrase}</div>
                  {q.board_site && <div className="ps-board-url">{q.board_site.split('.')[0]}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (sourceId === 'usajobs') {
    const u = config.usajobs;
    const update = (k: string, v: any) => onChange({ usajobs: { ...u, [k]: v } });
    return (
      <div className="pipeline-sidebar">
        <SidebarHeader title="USAJobs" onClose={onClose} />
        <div className="ps-body">
          <div className="ps-section">
            <div className="ps-section-title">Settings</div>
            <NumberField label="Days lookback" value={u.days} onChange={v => update('days', v)} />
            <div className="ps-field">
              <div className="ps-field-label">Remote only</div>
              <div className={`pn-switch${u.remote ? ' pn-switch-on' : ''}`}
                   onClick={() => update('remote', !u.remote)} style={{ cursor: 'pointer' }} />
            </div>
          </div>
          <div className="ps-section">
            <div className="ps-section-title">Keywords</div>
            <TagList items={u.keywords} onUpdate={v => update('keywords', v)} />
          </div>
          <div className="ps-section">
            <div className="ps-section-title">Series Codes</div>
            <TagList items={u.series} onUpdate={v => update('series', v)} />
          </div>
        </div>
      </div>
    );
  }

  // Board sources (ashby, greenhouse, lever)
  const boards = config.boards.filter(b => b.board_type === sourceId);
  const toggleBoard = (idx: number) => {
    const allBoards = [...config.boards];
    const globalIdx = allBoards.findIndex(b => b.board_type === sourceId && b.company === boards[idx].company);
    if (globalIdx >= 0) {
      allBoards[globalIdx] = { ...allBoards[globalIdx], enabled: !allBoards[globalIdx].enabled };
      onChange({ boards: allBoards });
    }
  };

  return (
    <div className="pipeline-sidebar">
      <SidebarHeader title={sourceId.charAt(0).toUpperCase() + sourceId.slice(1)} onClose={onClose} />
      <div className="ps-body">
        <div className="ps-section">
          <div className="ps-section-title">Boards ({boards.length})</div>
          <div className="ps-board-list">
            {boards.map((b, i) => (
              <div key={i} className={`ps-board-item${!b.enabled ? ' ps-board-disabled' : ''}`}>
                <div className={`pn-switch${b.enabled ? ' pn-switch-on' : ''}`}
                     onClick={() => toggleBoard(i)} style={{ cursor: 'pointer', transform: 'scale(.85)' }} />
                <div className="ps-board-name">{b.company}</div>
              </div>
            ))}
          </div>
        </div>
        {sourceId !== 'lever' && (
          <div className="ps-section">
            <div className="ps-section-title">Crawl Settings</div>
            <NumberField label="Max per board" value={config.crawl.max_results_per_target}
              onChange={v => onChange({ crawl: { ...config.crawl, max_results_per_target: v } })} />
            <NumberField label="Request delay (s)" value={config.crawl.request_delay} step={0.5}
              onChange={v => onChange({ crawl: { ...config.crawl, request_delay: v } })} />
          </div>
        )}
      </div>
    </div>
  );
}

function StagePanel({ stageId, config, onChange, onClose }: {
  stageId: string; config: ScraperConfig; onChange: (p: Partial<ScraperConfig>) => void; onClose: () => void;
}) {
  const stageDef = STAGE_DEFS.find(s => s.id === stageId);

  if (stageId === 'dedup') {
    return (
      <div className="pipeline-sidebar">
        <SidebarHeader title="Deduplication" onClose={onClose} />
        <div className="ps-body">
          <div className="ps-section">
            <div className="ps-section-title">Settings</div>
            <NumberField label="TTL (days)" value={config.seen_ttl_days}
              onChange={v => onChange({ seen_ttl_days: v })} />
            <div className="ps-field">
              <div className="ps-field-label" style={{ fontSize: '.68rem', color: 'var(--text-secondary)', marginTop: 4 }}>
                URLs older than this re-enter the pipeline
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (stageId === 'hard_filter') {
    const hf = config.hard_filters;
    return (
      <div className="pipeline-sidebar">
        <SidebarHeader title="Hard Filters" onClose={onClose} />
        <div className="ps-body">
          <div className="ps-section">
            <div className="ps-section-title">Thresholds</div>
            <NumberField label="Min salary ($k)" value={hf.min_salary_k}
              onChange={v => onChange({ hard_filters: { ...hf, min_salary_k: v } })} />
            <NumberField label="Max experience (years)" value={config.filter.max_experience_years}
              onChange={v => onChange({ filter: { ...config.filter, max_experience_years: v } })} />
          </div>
          <div className="ps-section">
            <div className="ps-section-title">Seniority Blocklist</div>
            <TagList items={hf.title_blocklist}
              onUpdate={v => onChange({ hard_filters: { ...hf, title_blocklist: v } })} />
          </div>
          <div className="ps-section">
            <div className="ps-section-title">Content Blocklist</div>
            <TagList items={hf.content_blocklist}
              onUpdate={v => onChange({ hard_filters: { ...hf, content_blocklist: v } })} />
          </div>
          <div className="ps-section">
            <div className="ps-section-title">Domain Blocklist</div>
            <TagList items={hf.domain_blocklist}
              onUpdate={v => onChange({ hard_filters: { ...hf, domain_blocklist: v } })} />
          </div>
        </div>
      </div>
    );
  }

  // text_extraction / storage — no params
  return (
    <div className="pipeline-sidebar">
      <SidebarHeader title={stageDef?.label || stageId} onClose={onClose} />
      <div className="ps-body">
        <div className="ps-empty">
          <Settings size={40} />
          <p>No configurable parameters</p>
          <div className="ps-empty-hint">{stageDef?.desc}</div>
        </div>
      </div>
    </div>
  );
}

function OutputPanel({ stats, onClose }: { stats: PipelineStats | null; onClose: () => void }) {
  return (
    <div className="pipeline-sidebar">
      <SidebarHeader title="Output" onClose={onClose} />
      <div className="ps-body">
        {stats?.run_id ? (
          <div className="ps-section">
            <div className="ps-section-title">Last Run</div>
            <div style={{ fontSize: '.75rem', color: 'var(--text-secondary)', marginBottom: 12, fontFamily: 'var(--font-mono)' }}>
              {stats.run_id}
            </div>
            <div className="ps-section-title">Per Source</div>
            <div className="ps-board-list">
              {Object.entries(stats.per_source).map(([src, cnt]) => (
                <div key={src} className="ps-board-item">
                  <div className="pn-stat-dot" style={{ background: 'var(--accent)' }} />
                  <div className="ps-board-name">{src}</div>
                  <div className="ps-board-url">{cnt}</div>
                </div>
              ))}
            </div>
            {Object.keys(stats.per_rejection).length > 0 && (
              <>
                <div className="ps-section-title" style={{ marginTop: 16 }}>Rejections</div>
                <div className="ps-board-list">
                  {Object.entries(stats.per_rejection).map(([stage, cnt]) => (
                    <div key={stage} className="ps-board-item">
                      <div className="pn-stat-dot" style={{ background: 'var(--red)' }} />
                      <div className="ps-board-name">{stage}</div>
                      <div className="ps-board-url">{cnt}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="ps-empty">
            <Database size={40} />
            <p>No completed runs yet</p>
          </div>
        )}
      </div>
    </div>
  );
}

function QAReviewPanel({ qaStatus, liveItems, onClose }: { qaStatus: QALlmReviewStatus | null; liveItems: QAReviewItem[]; onClose: () => void }) {
  const systemPrompt = `You are a job-candidate fit reviewer. Given the candidate's profile and a job description, evaluate whether this is a strong enough match to warrant tailoring application materials.

Evaluation criteria:
- Requirement coverage: do candidate skills map to core JD requirements?
- Experience relevance: does baseline evidence support the role?
- Seniority alignment: mid-to-senior IC roles are ideal (not staff/principal/management)
- Domain fit: security/cloud/devops/platform engineering — not pure frontend, data science, etc.
- Red flags: onsite-only disguised as remote, clearance required, etc.`;

  const responseFormat = `{ "pass": true/false, "reason": "1-2 sentences", "confidence": 0.0-1.0, "top_matches": ["skill1"], "gaps": ["gap1"] }`;

  const polishPrompt = `On pass → second LLM call cleans scraped JD text into structured brief:
ROLE SUMMARY, CORE RESPONSIBILITIES, REQUIRED QUALIFICATIONS, PREFERRED QUALIFICATIONS, LOGISTICS

Returns: { "requirements_summary": "...", "approved_jd_text": "...", "removed_noise": [...] }`;

  const s = qaStatus?.summary;
  return (
    <div className="pipeline-sidebar">
      <SidebarHeader title="QA LLM Review" onClose={onClose} />
      <div className="ps-body">
        {/* Live status */}
        <div className="ps-section">
          <div className="ps-section-title">Status</div>
          <div className="ps-board-list">
            <div className="ps-board-item">
              <div className="pn-stat-dot" style={{ background: qaStatus?.running ? 'var(--green)' : 'var(--text-secondary)' }} />
              <div className="ps-board-name">{qaStatus?.running ? 'Running' : 'Idle'}</div>
            </div>
            {qaStatus?.resolved_model && (
              <div className="ps-board-item">
                <Brain size={12} style={{ opacity: .4, flexShrink: 0 }} />
                <div className="ps-board-name" style={{ fontSize: '.7rem', fontFamily: 'var(--font-mono)' }}>{qaStatus.resolved_model}</div>
              </div>
            )}
          </div>
          {s && s.total > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
              <div className="pn-badge" style={{ background: 'rgba(60, 179, 113, .12)', color: 'var(--green)' }}>
                <CheckCircle size={10} /> {s.passed} pass
              </div>
              <div className="pn-badge" style={{ background: 'rgba(240, 80, 80, .12)', color: 'var(--red)' }}>
                <XCircle size={10} /> {s.failed} fail
              </div>
              {s.skipped > 0 && <div className="pn-badge">{s.skipped} skip</div>}
              {s.errors > 0 && <div className="pn-badge" style={{ color: 'var(--red)' }}>{s.errors} err</div>}
              {s.queued > 0 && <div className="pn-badge">{s.queued} queued</div>}
            </div>
          )}
        </div>

        {/* Architecture */}
        <div className="ps-section">
          <div className="ps-section-title">Architecture</div>
          <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            <div style={{ marginBottom: 8 }}>
              <strong style={{ color: 'var(--text)' }}>Endpoint:</strong>{' '}
              <code style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem' }}>localhost:1234/v1/chat/completions</code>
            </div>
            <div style={{ marginBottom: 8 }}>
              <strong style={{ color: 'var(--text)' }}>Temperature:</strong> 0.2 (review) / 0.1 (polish)
            </div>
            <div style={{ marginBottom: 8 }}>
              <strong style={{ color: 'var(--text)' }}>Timeout:</strong> 90s per call
            </div>
            <div style={{ marginBottom: 8 }}>
              <strong style={{ color: 'var(--text)' }}>JD truncation:</strong> 12,000 chars
            </div>
            <div>
              <strong style={{ color: 'var(--text)' }}>Context:</strong> soul.md + skills.json injected as profile
            </div>
          </div>
        </div>

        {/* System Prompt */}
        <div className="ps-section">
          <div className="ps-section-title">System Prompt — Fit Review</div>
          <pre style={{
            fontSize: '.68rem', fontFamily: 'var(--font-mono)', color: 'var(--text)',
            background: 'var(--surface-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', padding: '10px 12px', whiteSpace: 'pre-wrap',
            lineHeight: 1.5, maxHeight: 200, overflowY: 'auto',
          }}>{systemPrompt}</pre>
        </div>

        {/* Response format */}
        <div className="ps-section">
          <div className="ps-section-title">Response Format</div>
          <pre style={{
            fontSize: '.68rem', fontFamily: 'var(--font-mono)', color: 'var(--accent)',
            background: 'var(--surface-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', padding: '10px 12px', whiteSpace: 'pre-wrap',
            lineHeight: 1.5,
          }}>{responseFormat}</pre>
        </div>

        {/* Polish step */}
        <div className="ps-section">
          <div className="ps-section-title">Post-Pass: JD Polish</div>
          <pre style={{
            fontSize: '.68rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)',
            background: 'var(--surface-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', padding: '10px 12px', whiteSpace: 'pre-wrap',
            lineHeight: 1.5, maxHeight: 180, overflowY: 'auto',
          }}>{polishPrompt}</pre>
        </div>

        {/* Decision flow */}
        <div className="ps-section">
          <div className="ps-section-title">Decision Flow</div>
          <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            <div>1. Job enters DB as <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--amber)' }}>qa_pending</code></div>
            <div>2. User or batch triggers LLM review</div>
            <div>3. System prompt + profile context + JD → LLM</div>
            <div>4. Pass → <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--green)' }}>qa_approved</code> + polish JD</div>
            <div>5. Fail → <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--red)' }}>qa_rejected</code></div>
            <div>6. Approved jobs eligible for tailoring</div>
          </div>
        </div>

        {/* Live LLM results feed */}
        {liveItems.length > 0 && (
          <div className="ps-section">
            <div className="ps-section-title">Live Results ({liveItems.filter(i => i.status === 'pass' || i.status === 'fail').length} completed)</div>
            <div style={{ maxHeight: 300, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {liveItems.filter(i => i.status !== 'queued').map((item) => (
                <div key={item.job_id} style={{
                  background: 'var(--surface-2)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius)', padding: '8px 10px',
                  borderLeft: `3px solid ${item.status === 'pass' ? 'var(--green)' : item.status === 'fail' ? 'var(--red)' : item.status === 'reviewing' ? 'var(--amber)' : 'var(--border)'}`,
                }}>
                  <div style={{ fontSize: '.72rem', fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.title || `Job #${item.job_id}`}
                  </div>
                  {item.status === 'reviewing' && (
                    <div style={{ fontSize: '.65rem', color: 'var(--amber)', marginTop: 3, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span className="pn-live-dot" style={{ background: 'var(--amber)' }} /> Reviewing...
                    </div>
                  )}
                  {item.reason && (
                    <div style={{ fontSize: '.65rem', color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>
                      {item.reason}
                    </div>
                  )}
                  {item.confidence != null && (
                    <div style={{ fontSize: '.62rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', marginTop: 2 }}>
                      confidence: {(item.confidence * 100).toFixed(0)}%
                    </div>
                  )}
                  {item.top_matches && item.top_matches.length > 0 && (
                    <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 4 }}>
                      {item.top_matches.map((m, i) => (
                        <span key={i} style={{
                          fontSize: '.6rem', fontFamily: 'var(--font-mono)',
                          background: 'rgba(60, 179, 113, .12)', color: 'var(--green)',
                          padding: '1px 5px', borderRadius: 8,
                        }}>{m}</span>
                      ))}
                    </div>
                  )}
                  {item.gaps && item.gaps.length > 0 && (
                    <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 3 }}>
                      {item.gaps.map((g, i) => (
                        <span key={i} style={{
                          fontSize: '.6rem', fontFamily: 'var(--font-mono)',
                          background: 'rgba(240, 80, 80, .12)', color: 'var(--red)',
                          padding: '1px 5px', borderRadius: 8,
                        }}>{g}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TailorStagePanel({ stageId, live, onClose }: { stageId: string; live: LiveStatus; onClose: () => void }) {
  const def = TAILOR_STAGE_DEFS.find(s => s.id === stageId);
  const details: Record<string, { what: string; how: string; llm: boolean }> = {
    tailor_analysis: {
      what: 'Extracts structured requirements from the job description: core responsibilities, required qualifications, preferred skills, logistics.',
      how: 'LLM parses JD text with soul.md + skills.json context. Outputs analysis.json with requirement categories and candidate-match signals.',
      llm: true,
    },
    tailor_strategy: {
      what: 'Plans which resume bullets, skills, and experiences to emphasize for this specific role.',
      how: 'LLM takes analysis.json + baseline resume and produces a targeting strategy: what to highlight, what to add, what to downplay.',
      llm: true,
    },
    tailor_resume: {
      what: 'Generates a tailored LaTeX resume based on the strategy.',
      how: 'LLM produces LaTeX source from baseline template, applying strategy decisions. Multiple drafts with QA self-review.',
      llm: true,
    },
    tailor_cover: {
      what: 'Generates a tailored LaTeX cover letter aligned with the resume.',
      how: 'LLM writes cover letter using analysis + strategy context. Draws from persona/interests.md for authentic voice.',
      llm: true,
    },
    tailor_validate: {
      what: 'Runs hard gate checks on generated documents before compilation.',
      how: 'Validates LaTeX syntax, checks for placeholder text, verifies required sections exist, confirms no hallucinated credentials.',
      llm: false,
    },
    tailor_compile: {
      what: 'Compiles LaTeX sources into final PDF documents.',
      how: 'Runs pdflatex with error capture. Outputs resume.pdf + cover_letter.pdf to output/<slug>/.',
      llm: false,
    },
  };
  const info = details[stageId];
  return (
    <div className="pipeline-sidebar">
      <SidebarHeader title={def?.label || stageId} onClose={onClose} />
      <div className="ps-body">
        <div className="ps-section">
          <div className="ps-section-title">What</div>
          <div style={{ fontSize: '.72rem', color: 'var(--text)', lineHeight: 1.6 }}>
            {info?.what}
          </div>
        </div>
        <div className="ps-section">
          <div className="ps-section-title">How</div>
          <div style={{ fontSize: '.72rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {info?.how}
          </div>
        </div>
        {info?.llm && (
          <div className="ps-section">
            <div className="ps-section-title">LLM Call</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Brain size={12} style={{ color: 'var(--purple)', opacity: .6 }} />
              <span style={{ fontSize: '.72rem', color: 'var(--purple)' }}>Uses active LLM model</span>
            </div>
          </div>
        )}
        {/* Live log tail when tailoring is running */}
        {live.tailoringRunning && live.tailoringLogTail && (
          <div className="ps-section">
            <div className="ps-section-title">
              <span className="pn-live-dot" style={{ marginRight: 6 }} />
              Live Output
            </div>
            <pre style={{
              fontSize: '.62rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)',
              background: 'var(--surface-2)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', padding: '8px 10px', whiteSpace: 'pre-wrap',
              lineHeight: 1.5, maxHeight: 300, overflowY: 'auto', wordBreak: 'break-word',
            }}>{live.tailoringLogTail}</pre>
          </div>
        )}
        <div className="ps-empty-hint" style={{ marginTop: 12 }}>
          View full traces at /ops/pipeline-inspector
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------
function SidebarHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="ps-header">
      <div className="ps-header-title">{title}</div>
      <button className="ps-close" onClick={onClose}><X size={16} /></button>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string | number; onChange: (v: string) => void }) {
  return (
    <div className="ps-field">
      <div className="ps-field-label">{label}</div>
      <input type="text" value={value} onChange={e => onChange(e.target.value)} />
    </div>
  );
}

function NumberField({ label, value, step, onChange }: { label: string; value: number; step?: number; onChange: (v: number) => void }) {
  return (
    <div className="ps-field">
      <div className="ps-field-label">{label}</div>
      <input type="number" value={value} step={step || 1}
        onChange={e => onChange(Number(e.target.value))} />
    </div>
  );
}

function TagList({ items, onUpdate }: { items: string[]; onUpdate: (v: string[]) => void }) {
  const [adding, setAdding] = useState('');
  const add = () => {
    const v = adding.trim();
    if (v && !items.includes(v)) {
      onUpdate([...items, v]);
      setAdding('');
    }
  };
  return (
    <>
      <div className="ps-tag-list">
        {items.map((item, i) => (
          <span key={i} className="ps-tag">
            {item}
            <button className="ps-tag-remove" onClick={() => onUpdate(items.filter((_, j) => j !== i))}>
              <X size={10} />
            </button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        <input type="text" value={adding} onChange={e => setAdding(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="Add..."
          style={{ flex: 1, background: 'var(--surface-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)', fontFamily: 'var(--font-mono)',
            fontSize: '.72rem', padding: '5px 8px', outline: 'none' }} />
        <button onClick={add} style={{ background: 'var(--surface-3)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', color: 'var(--text-secondary)', cursor: 'pointer', padding: '4px 8px',
          display: 'flex', alignItems: 'center' }}>
          <Plus size={12} />
        </button>
      </div>
    </>
  );
}

function ToolbarStatusChip({
  label,
  state,
  detail,
}: {
  label: string;
  state: 'running' | 'idle' | 'draft';
  detail: string;
}) {
  return (
    <div className={`pe-chip pe-chip-${state}`}>
      <span className={`pe-chip-dot pe-chip-dot-${state}`} />
      <div className="pe-chip-copy">
        <span className="pe-chip-label">{label}</span>
        <span className="pe-chip-detail">{detail}</span>
      </div>
    </div>
  );
}

function CanvasToolbar({
  live,
  dirty,
  saving,
  refreshing,
  lastPollAt,
  eventCount,
  onRefresh,
  onReset,
  onSave,
}: {
  live: LiveStatus;
  dirty: boolean;
  saving: boolean;
  refreshing: boolean;
  lastPollAt: number | null;
  eventCount: number;
  onRefresh: () => void;
  onReset: () => void;
  onSave: () => void;
}) {
  const { fitView } = useReactFlow();

  return (
    <div className="pipeline-toolbar">
      <div className="pipeline-toolbar-copy">
        <div className="pipeline-toolbar-label">Pipeline Console</div>
        <div className="pipeline-toolbar-title">Live orchestration view</div>
      </div>
      <div className="pipeline-toolbar-chips">
        <ToolbarStatusChip
          label="Scrape"
          state={live.scrapeRunning ? 'running' : 'idle'}
          detail={live.scrapeRunning && live.scrapeStartedAt ? `running ${timeAgo(live.scrapeStartedAt)}` : 'idle'}
        />
        <ToolbarStatusChip
          label="QA Review"
          state={live.qaReviewRunning ? 'running' : 'idle'}
          detail={live.qaReviewRunning && live.qaReviewProgress
            ? `${live.qaReviewProgress.completed}/${live.qaReviewProgress.total} complete`
            : 'idle'}
        />
        <ToolbarStatusChip
          label="Tailoring"
          state={live.tailoringRunning ? 'running' : 'idle'}
          detail={live.tailoringRunning ? `${fmt(live.tailoringQueue)} queued` : 'idle'}
        />
        <ToolbarStatusChip
          label="Draft"
          state={dirty ? 'draft' : 'idle'}
          detail={dirty ? 'unsaved changes' : 'in sync'}
        />
      </div>
      <div className="pipeline-toolbar-right">
        <div className="pipeline-toolbar-meta">
          <span>Synced {timeSince(lastPollAt)}</span>
          <span>{pluralize(eventCount, 'event')}</span>
        </div>
        <button className="pe-btn" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
        <button className="pe-btn" onClick={() => fitView({ padding: 0.15, maxZoom: 0.72 })}>
          Fit view
        </button>
        <button className="pe-btn" onClick={onReset} disabled={!dirty || saving}>
          Reset
        </button>
        <button className="pe-btn pe-btn-primary" onClick={onSave} disabled={!dirty || saving}>
          {saving ? 'Saving...' : 'Save config'}
        </button>
      </div>
    </div>
  );
}

function OverviewMetric({
  label,
  value,
  hint,
  tone = 'muted',
}: {
  label: string;
  value: string;
  hint: string;
  tone?: PipelineEventTone;
}) {
  return (
    <div className={`pi-metric pi-metric-${tone}`}>
      <div className="pi-metric-label">{label}</div>
      <div className="pi-metric-value">{value}</div>
      <div className="pi-metric-hint">{hint}</div>
    </div>
  );
}

function EventFeed({
  events,
  emptyLabel,
}: {
  events: PipelineEvent[];
  emptyLabel: string;
}) {
  if (events.length === 0) {
    return (
      <div className="ps-empty ps-empty-compact">
        <Activity size={24} />
        <p>{emptyLabel}</p>
      </div>
    );
  }

  return (
    <div className="pi-event-list">
      {events.map((event) => (
        <div key={event.id} className={`pi-event pi-event-${event.tone}`}>
          <div className="pi-event-header">
            <span className="pi-event-title">{event.label}</span>
            <span className="pi-event-time">{timeSince(event.createdAt)}</span>
          </div>
          {event.detail ? <div className="pi-event-detail">{event.detail}</div> : null}
        </div>
      ))}
    </div>
  );
}

function LogCard({ title, content }: { title: string; content: string }) {
  if (!content) return null;
  return (
    <div className="ps-section">
      <div className="ps-section-title">{title}</div>
      <pre className="pi-log-card">{content}</pre>
    </div>
  );
}

function GlobalOverviewPanel({
  stats,
  live,
  events,
}: {
  stats: PipelineStats | null;
  live: LiveStatus;
  events: PipelineEvent[];
}) {
  const inventory = stats?.inventory;
  return (
    <>
      <div className="ps-section">
        <div className="ps-section-title">Overview</div>
        <div className="pi-metric-grid">
          <OverviewMetric
            label="Scrape"
            value={live.scrapeRunning ? 'Running' : 'Idle'}
            hint={live.scrapeRunning && live.scrapeStartedAt ? `since ${timeAgo(live.scrapeStartedAt)}` : 'Awaiting run'}
            tone={live.scrapeRunning ? 'accent' : 'muted'}
          />
          <OverviewMetric
            label="Awaiting QA"
            value={fmt(inventory?.qa_pending)}
            hint="Current review backlog"
            tone={(inventory?.qa_pending ?? 0) > 0 ? 'amber' : 'muted'}
          />
          <OverviewMetric
            label="Ready"
            value={fmt(inventory?.qa_approved)}
            hint="Approved for tailoring"
            tone={(inventory?.qa_approved ?? 0) > 0 ? 'green' : 'muted'}
          />
          <OverviewMetric
            label="Tailor Queue"
            value={fmt(live.tailoringQueue)}
            hint={live.tailoringRunning ? (live.tailoringJob || 'Package rendering active') : 'Idle'}
            tone={live.tailoringRunning ? 'accent' : 'muted'}
          />
        </div>
      </div>

      <div className="ps-section">
        <div className="ps-section-title">Recent activity</div>
        <EventFeed events={events.slice(0, 8)} emptyLabel="No recent pipeline events yet" />
      </div>

      <LogCard title="Scrape output" content={live.scrapeLogTail} />
      <LogCard title="Tailoring output" content={live.tailoringLogTail} />
    </>
  );
}

function SelectedOverviewPanel({
  selectedNode,
  config,
  stats,
  live,
  qaStatus,
  sourceStats,
}: {
  selectedNode: { id: string; type: string };
  config: ScraperConfig;
  stats: PipelineStats | null;
  live: LiveStatus;
  qaStatus: QALlmReviewStatus | null;
  sourceStats: SourceRollupStats;
}) {
  const inventory = stats?.inventory;

  if (selectedNode.type === 'source') {
    const source = SOURCE_DEFS.find((item) => item.id === selectedNode.id);
    const boards = config.boards.filter((board) => board.board_type === selectedNode.id);
    const configuredCount = selectedNode.id === 'searxng'
      ? config.queries.length
      : selectedNode.id === 'usajobs'
        ? config.usajobs.keywords.length
        : boards.length;
    const enabledCount = selectedNode.id === 'searxng'
      ? Number(config.searxng.enabled)
      : selectedNode.id === 'usajobs'
        ? Number(config.usajobs.enabled)
        : boards.filter((board) => board.enabled).length;

    return (
      <>
        <div className="ps-section">
          <div className="ps-section-title">Selection</div>
          <div className="pi-selected-title">{source?.label || selectedNode.id}</div>
          <div className="pi-selected-copy">Provider configuration and source-side activity.</div>
        </div>
        <div className="pi-metric-grid">
          <OverviewMetric label="Configured" value={fmt(configuredCount)} hint="Queries / boards / keywords" />
          <OverviewMetric label="Enabled" value={fmt(enabledCount)} hint="Currently enabled targets" tone={enabledCount > 0 ? 'green' : 'muted'} />
          <OverviewMetric label="Last run" value={fmt(sourceStats[selectedNode.id as keyof SourceRollupStats])} hint="Items seen in last run stats" tone="accent" />
        </div>
      </>
    );
  }

  if (selectedNode.type === 'stage') {
    const stage = STAGE_DEFS.find((item) => item.id === selectedNode.id);
    const passCount = selectedNode.id === 'dedup'
      ? Math.max((stats?.raw_count ?? 0) - (stats?.dedup_dropped ?? 0), 0)
      : selectedNode.id === 'storage'
        ? (stats?.stored ?? 0)
        : null;
    const dropCount = selectedNode.id === 'dedup'
      ? (stats?.dedup_dropped ?? 0)
      : selectedNode.id === 'hard_filter'
        ? (stats?.filter_rejected ?? 0)
        : null;

    return (
      <>
        <div className="ps-section">
          <div className="ps-section-title">Selection</div>
          <div className="pi-selected-title">{stage?.label || selectedNode.id}</div>
          <div className="pi-selected-copy">{stage?.desc}</div>
        </div>
        <div className="pi-metric-grid">
          <OverviewMetric label="Order" value={String(config.pipeline_order.indexOf(selectedNode.id) + 1)} hint="Current scrape-stage order" />
          <OverviewMetric label="Pass" value={fmt(passCount)} hint="Latest passing count" tone="green" />
          <OverviewMetric label="Drop" value={fmt(dropCount)} hint="Latest drop count" tone={dropCount ? 'red' : 'muted'} />
        </div>
      </>
    );
  }

  if (selectedNode.type === 'dbOutput') {
    return (
      <>
        <div className="ps-section">
          <div className="ps-section-title">Selection</div>
          <div className="pi-selected-title">Results DB</div>
          <div className="pi-selected-copy">Persistent inventory snapshot and downstream handoff.</div>
        </div>
        <div className="pi-metric-grid">
          <OverviewMetric label="Total" value={fmt(inventory?.total)} hint="Rows in inventory" />
          <OverviewMetric label="Pending" value={fmt(inventory?.qa_pending)} hint="Awaiting QA" tone={(inventory?.qa_pending ?? 0) > 0 ? 'amber' : 'muted'} />
          <OverviewMetric label="Ready" value={fmt(inventory?.qa_approved)} hint="Approved for tailoring" tone="green" />
          <OverviewMetric label="Rejected" value={fmt(inventory?.rejected)} hint="Scraper-filter rejected" tone={(inventory?.rejected ?? 0) > 0 ? 'red' : 'muted'} />
        </div>
      </>
    );
  }

  if (selectedNode.type === 'qaReview') {
    return (
      <>
        <div className="ps-section">
          <div className="ps-section-title">Selection</div>
          <div className="pi-selected-title">QA LLM Review</div>
          <div className="pi-selected-copy">Model-assisted fit review and queue progression.</div>
        </div>
        <div className="pi-metric-grid">
          <OverviewMetric label="State" value={qaStatus?.running ? 'Running' : 'Idle'} hint={qaStatus?.resolved_model || 'No active model'} tone={qaStatus?.running ? 'accent' : 'muted'} />
          <OverviewMetric label="Progress" value={live.qaReviewProgress ? `${live.qaReviewProgress.completed}/${live.qaReviewProgress.total}` : '—'} hint="Current batch progress" />
          <OverviewMetric label="Approved" value={fmt(inventory?.qa_approved)} hint="Approved by QA" tone="green" />
          <OverviewMetric label="Rejected" value={fmt(inventory?.qa_rejected)} hint="Rejected by QA" tone={(inventory?.qa_rejected ?? 0) > 0 ? 'red' : 'muted'} />
        </div>
      </>
    );
  }

  const stage = TAILOR_STAGE_DEFS.find((item) => item.id === selectedNode.id);
  return (
    <>
      <div className="ps-section">
        <div className="ps-section-title">Selection</div>
        <div className="pi-selected-title">{stage?.label || selectedNode.id}</div>
        <div className="pi-selected-copy">{stage?.desc}</div>
      </div>
      <div className="pi-metric-grid">
        <OverviewMetric label="State" value={live.tailoringRunning ? 'Running' : 'Idle'} hint={live.tailoringRunning ? (live.tailoringJob || 'Package in progress') : 'Awaiting run'} tone={live.tailoringRunning ? 'accent' : 'muted'} />
        <OverviewMetric label="Queue" value={fmt(live.tailoringQueue)} hint="Queued tailoring jobs" />
        <OverviewMetric label="Ready pool" value={fmt(inventory?.qa_approved)} hint="Jobs ready for tailoring" tone="green" />
      </div>
    </>
  );
}

function InspectorActivityPanel({
  selectedNode,
  live,
  qaStatus,
  events,
}: {
  selectedNode: { id: string; type: string } | null;
  live: LiveStatus;
  qaStatus: QALlmReviewStatus | null;
  events: PipelineEvent[];
}) {
  const scopedEvents = selectedNode ? events.filter((event) => eventMatchesSelection(event, selectedNode)) : events;
  const qaItems = (qaStatus?.items || []).filter((item) => item.status !== 'queued').slice(0, 5);

  return (
    <>
      <div className="ps-section">
        <div className="ps-section-title">Recent activity</div>
        <EventFeed
          events={scopedEvents.slice(0, 10)}
          emptyLabel={selectedNode ? 'No recent activity for this selection yet' : 'No recent pipeline activity yet'}
        />
      </div>

      {selectedNode?.type === 'qaReview' && qaItems.length > 0 ? (
        <div className="ps-section">
          <div className="ps-section-title">Live results</div>
          <div className="pi-qa-results">
            {qaItems.map((item) => (
              <div key={item.job_id} className={`pi-qa-result pi-qa-result-${item.status}`}>
                <div className="pi-qa-result-title">{item.title || `Job #${item.job_id}`}</div>
                <div className="pi-qa-result-meta">{item.reason || item.status}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {(selectedNode?.type === 'source' || selectedNode?.type === 'stage') ? (
        <LogCard title="Scrape output" content={live.scrapeLogTail} />
      ) : null}

      {selectedNode?.type === 'tailorStage' ? (
        <LogCard title="Tailoring output" content={live.tailoringLogTail} />
      ) : null}

      {!selectedNode ? <LogCard title="Tailoring output" content={live.tailoringLogTail} /> : null}
    </>
  );
}

function PipelineInspector({
  selectedNode,
  inspectorTab,
  onTabChange,
  onClearSelection,
  config,
  stats,
  qaStatus,
  live,
  events,
  sourceStats,
  onConfigChange,
}: {
  selectedNode: { id: string; type: string } | null;
  inspectorTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  onClearSelection: () => void;
  config: ScraperConfig;
  stats: PipelineStats | null;
  qaStatus: QALlmReviewStatus | null;
  live: LiveStatus;
  events: PipelineEvent[];
  sourceStats: SourceRollupStats;
  onConfigChange: (patch: Partial<ScraperConfig>) => void;
}) {
  const tabs: InspectorTab[] = selectedNode ? ['overview', 'configure', 'activity'] : ['overview', 'activity'];
  const title = getNodeDisplayName(selectedNode);
  const subtitle = selectedNode ? 'Selected node context and controls' : 'Live summary and recent activity';

  return (
    <div className="pipeline-sidebar pipeline-inspector">
      <div className="ps-header">
        <div>
          <div className="ps-header-title">{title}</div>
          <div className="pi-header-subtitle">{subtitle}</div>
        </div>
        {selectedNode ? (
          <button className="ps-close" onClick={onClearSelection}><X size={16} /></button>
        ) : null}
      </div>

      <div className="pi-tab-row">
        {tabs.map((tab) => (
          <button
            key={tab}
            className={`pi-tab${inspectorTab === tab ? ' pi-tab-active' : ''}`}
            onClick={() => onTabChange(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="ps-body">
        {inspectorTab === 'overview' ? (
          selectedNode ? (
            <SelectedOverviewPanel
              selectedNode={selectedNode}
              config={config}
              stats={stats}
              live={live}
              qaStatus={qaStatus}
              sourceStats={sourceStats}
            />
          ) : (
            <GlobalOverviewPanel stats={stats} live={live} events={events} />
          )
        ) : null}

        {inspectorTab === 'configure' && selectedNode ? (
          <div className="pi-embedded">
            <ConfigPanel
              nodeId={selectedNode.id}
              nodeType={selectedNode.type}
              config={config}
              stats={stats}
              qaStatus={qaStatus}
              live={live}
              onChange={onConfigChange}
              onClose={onClearSelection}
            />
          </div>
        ) : null}

        {inspectorTab === 'activity' ? (
          <InspectorActivityPanel selectedNode={selectedNode} live={live} qaStatus={qaStatus} events={events} />
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layout helpers — DAG topology
// ---------------------------------------------------------------------------
// Sources fan-in left column
const SRC_X = 50;
const SRC_Y = 50;
const SRC_GAP = 142;
const SRC_LANE_W = 294;

// Ingestion stages — horizontal row
const STAGE_X = 350;
const STAGE_Y = 150;
const STAGE_GAP = 238;

// Results DB — hub node right of stages
const DB_GAP = 20;

// QA Review — below Results DB
const QA_DROP = 200;

// Tailoring — serpentine: 3 right, drop, 3 right
const TAILOR_ROW_GAP = 190;
const TAILOR_COL_GAP = 218;
const TAILOR_DROP = 140;

function buildNodes(
  config: ScraperConfig,
  stats: PipelineStats | null,
  live: LiveStatus,
  sourceStats: SourceRollupStats,
  onSelect: (id: string, type: string) => void,
  onToggleSource: (id: string) => void,
): Node[] {
  const nodes: Node[] = [];
  const inv = stats?.inventory;

  // ── Computed positions ──
  const stageCount = config.pipeline_order.length;
  const dbX = STAGE_X + stageCount * STAGE_GAP + DB_GAP;
  const dbY = STAGE_Y - 10;
  const qaX = dbX;
  const qaY = dbY + QA_DROP;

  // Tailoring serpentine: row 1 = indices 0,1,2 left-to-right; row 2 = indices 3,4,5 left-to-right (shifted right under Resume)
  const tailorBaseX = STAGE_X + 60;
  const tailorRow1Y = qaY + TAILOR_ROW_GAP;
  const tailorRow2Y = tailorRow1Y + TAILOR_DROP;

  const srcLaneH = SRC_GAP * (SOURCE_DEFS.length - 1) + 122;
  const coreLaneW = dbX - STAGE_X + 240;
  const coreLaneH = qaY - STAGE_Y + 204;
  const tailorLaneW = Math.max(TAILOR_COL_GAP * 2 + 200, dbX - tailorBaseX + 200);
  const tailorLaneH = TAILOR_DROP + 174;

  // ── Swimlanes ──
  nodes.push(
    {
      id: 'lane-sources',
      type: 'swimlane',
      position: { x: SRC_X - 20, y: SRC_Y - 44 },
      data: { label: 'Sources', subtitle: 'Search providers & board crawlers', tone: 'source', active: live.scrapeRunning },
      style: { width: SRC_LANE_W, height: srcLaneH },
      draggable: false, selectable: false, focusable: false,
    },
    {
      id: 'lane-core',
      type: 'swimlane',
      position: { x: STAGE_X - 28, y: STAGE_Y - 54 },
      data: { label: 'Ingestion & QA', subtitle: 'Process, persist, review', tone: 'stage', active: live.scrapeRunning || live.qaReviewRunning },
      style: { width: coreLaneW, height: coreLaneH },
      draggable: false, selectable: false, focusable: false,
    },
    {
      id: 'lane-tailor',
      type: 'swimlane',
      position: { x: tailorBaseX - 24, y: tailorRow1Y - 50 },
      data: { label: 'Tailoring', subtitle: 'LLM generation → PDF compilation', tone: 'tailor', active: live.tailoringRunning },
      style: { width: tailorLaneW, height: tailorLaneH },
      draggable: false, selectable: false, focusable: false,
    },
  );

  // ── Source nodes ──
  SOURCE_DEFS.forEach((src, i) => {
    let count = 0;
    let countLabel = 'items';
    let enabled = true;

    if (src.id === 'searxng') {
      count = config.queries.length;
      countLabel = 'queries';
      enabled = config.searxng.enabled;
    } else if (src.id === 'usajobs') {
      count = config.usajobs.keywords.length;
      countLabel = 'keywords';
      enabled = config.usajobs.enabled;
    } else {
      const boards = config.boards.filter((board) => board.board_type === src.id);
      count = boards.length;
      countLabel = 'boards';
      enabled = boards.some((board) => board.enabled);
    }

    const Icon = src.icon;
    nodes.push({
      id: src.id,
      type: 'source',
      position: { x: SRC_X, y: SRC_Y + i * SRC_GAP },
      data: {
        label: src.label,
        iconEl: <Icon size={16} />,
        count,
        countLabel,
        enabled,
        active: live.scrapeRunning && enabled,
        stat: sourceStats[src.id as keyof SourceRollupStats] ?? 0,
        onSelect: () => onSelect(src.id, 'source'),
        onToggle: () => onToggleSource(src.id),
      },
    });
  });

  // ── Pipeline stages (horizontal) ──
  config.pipeline_order.forEach((stageId, i) => {
    const def = STAGE_DEFS.find((stage) => stage.id === stageId);
    if (!def) return;
    const Icon = def.icon;

    let passCount: number | null = null;
    let dropCount: number | null = null;
    if (stats) {
      if (stageId === 'dedup') {
        dropCount = stats.dedup_dropped;
        passCount = stats.raw_count - stats.dedup_dropped;
      } else if (stageId === 'hard_filter') {
        dropCount = stats.filter_rejected;
      } else if (stageId === 'storage') {
        passCount = stats.stored;
      }
    }

    nodes.push({
      id: stageId,
      type: 'stage',
      position: { x: STAGE_X + i * STAGE_GAP, y: STAGE_Y },
      data: {
        label: def.label,
        desc: def.desc,
        iconEl: <Icon size={16} />,
        order: i + 1,
        passCount,
        dropCount,
        active: live.scrapeRunning,
        onSelect: () => onSelect(stageId, 'stage'),
      },
    });
  });

  // ── Results DB — hub ──
  nodes.push({
    id: 'output',
    type: 'dbOutput',
    position: { x: dbX, y: dbY },
    data: {
      inventory: inv ?? null,
      active: live.scrapeRunning || live.qaReviewRunning,
      onSelect: () => onSelect('output', 'dbOutput'),
    },
  });

  // ── QA LLM Review — below DB ──
  nodes.push({
    id: 'qaReview',
    type: 'qaReview',
    position: { x: qaX, y: qaY },
    data: {
      running: live.qaReviewRunning,
      model: live.qaReviewModel ?? null,
      pending: inv?.qa_pending ?? 0,
      passed: inv?.qa_approved ?? 0,
      failed: inv?.qa_rejected ?? 0,
      progress: live.qaReviewProgress,
      onSelect: () => onSelect('qaReview', 'qaReview'),
    },
  });

  // ── Tailoring — serpentine layout ──
  // Row 1: Analysis → Strategy → Resume Draft  (left to right)
  // Row 2: Cover Letter → Validate → Compile   (left to right, offset under Resume)
  // Resume connects DOWN to Cover Letter
  const tailorPositions: { x: number; y: number; handleIn: Position; handleOut: Position }[] = [
    // Row 1
    { x: tailorBaseX,                       y: tailorRow1Y, handleIn: Position.Top,  handleOut: Position.Right },
    { x: tailorBaseX + TAILOR_COL_GAP,      y: tailorRow1Y, handleIn: Position.Left, handleOut: Position.Right },
    { x: tailorBaseX + TAILOR_COL_GAP * 2,  y: tailorRow1Y, handleIn: Position.Left, handleOut: Position.Bottom },
    // Row 2
    { x: tailorBaseX + TAILOR_COL_GAP * 2,  y: tailorRow2Y, handleIn: Position.Top,  handleOut: Position.Right },
    { x: tailorBaseX + TAILOR_COL_GAP * 3,  y: tailorRow2Y, handleIn: Position.Left, handleOut: Position.Right },
    { x: tailorBaseX + TAILOR_COL_GAP * 4,  y: tailorRow2Y, handleIn: Position.Left, handleOut: Position.Right },
  ];

  TAILOR_STAGE_DEFS.forEach((def, i) => {
    const Icon = def.icon;
    const isFirst = i === 0;
    const isLast = i === TAILOR_STAGE_DEFS.length - 1;
    const pos = tailorPositions[i];

    nodes.push({
      id: def.id,
      type: 'tailorStage',
      position: { x: pos.x, y: pos.y },
      data: {
        label: def.label,
        desc: def.desc,
        iconEl: <Icon size={14} />,
        order: i + 1,
        isFirst,
        isLast,
        handleIn: pos.handleIn,
        handleOut: pos.handleOut,
        entryActive: live.tailoringRunning && isFirst,
        active: live.tailoringRunning,
        running: live.tailoringRunning,
        job: live.tailoringJob,
        queue: live.tailoringQueue,
        approved: isFirst ? (inv?.qa_approved ?? 0) : null,
        onSelect: () => onSelect(def.id, 'tailorStage'),
      },
    });
  });

  return nodes;
}

function buildEdges(config: ScraperConfig, live: LiveStatus): Edge[] {
  const edges: Edge[] = [];
  const firstStage = config.pipeline_order[0];
  const lastStage = config.pipeline_order[config.pipeline_order.length - 1];
  const labelBaseStyle = {
    fill: 'var(--text-secondary)',
    fontSize: 10,
    fontFamily: 'var(--font-mono)',
  };
  const labelBgStyle = {
    fill: 'var(--bg)',
    stroke: 'var(--border)',
    strokeWidth: 1,
  };

  const pushEdge = ({
    id,
    source,
    target,
    sourceHandle,
    targetHandle,
    label,
    active,
    tone,
  }: {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
    label?: string;
    active: boolean;
    tone: 'source' | 'stage' | 'output' | 'qa' | 'tailor';
  }) => {
    edges.push({
      id,
      source,
      target,
      sourceHandle,
      targetHandle,
      type: 'default',
      animated: active,
      className: `pn-edge ${active ? 'pn-edge-active' : 'pn-edge-idle'} pn-edge-${tone}`,
      style: { strokeWidth: active ? 2.4 : 1.8 },
      ...(label
        ? {
            label,
            labelStyle: labelBaseStyle,
            labelBgStyle,
            labelBgPadding: [6, 3] as [number, number],
            labelBgBorderRadius: 4,
          }
        : {}),
    });
  };

  // Sources → first pipeline stage (fan-in)
  SOURCE_DEFS.forEach((src) => {
    pushEdge({
      id: `${src.id}->${firstStage}`,
      source: src.id,
      target: firstStage,
      active: live.scrapeRunning,
      tone: 'source',
    });
  });

  // Pipeline stages chained (horizontal)
  for (let i = 0; i < config.pipeline_order.length - 1; i++) {
    pushEdge({
      id: `${config.pipeline_order[i]}->${config.pipeline_order[i + 1]}`,
      source: config.pipeline_order[i],
      target: config.pipeline_order[i + 1],
      active: live.scrapeRunning,
      tone: 'stage',
    });
  }

  // Last stage → Results DB
  pushEdge({
    id: `${lastStage}->output`,
    source: lastStage,
    target: 'output',
    active: live.scrapeRunning,
    tone: 'output',
  });

  // Results DB → QA Review (drops down)
  pushEdge({
    id: 'output->qaReview',
    source: 'output',
    target: 'qaReview',
    sourceHandle: 'bottom',
    targetHandle: 'top',
    label: 'qa_pending',
    active: live.qaReviewRunning || live.tailoringRunning,
    tone: 'qa',
  });

  // QA Review → Analysis (drops down-left to tailoring)
  pushEdge({
    id: 'qaReview->tailor_analysis',
    source: 'qaReview',
    target: 'tailor_analysis',
    sourceHandle: 'bottom',
    targetHandle: 'target',
    label: 'qa_approved',
    active: live.tailoringRunning,
    tone: 'tailor',
  });

  // Tailoring chain — serpentine edges
  const tailorIds = TAILOR_STAGE_DEFS.map(s => s.id);
  for (let i = 0; i < tailorIds.length - 1; i++) {
    pushEdge({
      id: `${tailorIds[i]}->${tailorIds[i + 1]}`,
      source: tailorIds[i],
      target: tailorIds[i + 1],
      sourceHandle: 'source',
      targetHandle: 'target',
      active: live.tailoringRunning,
      tone: 'tailor',
    });
  }

  return edges;
}

function buildLiveStatus(scrape: any, qa: any, tailor: any): LiveStatus {
  return {
    scrapeRunning: scrape?.running ?? false,
    scrapeStartedAt: scrape?.started_at ?? null,
    scrapeLogTail: scrape?.log_tail ?? '',
    qaReviewRunning: qa?.running ?? false,
    qaReviewModel: qa?.resolved_model ?? null,
    qaReviewProgress: qa?.summary
      ? { completed: qa.summary.completed, total: qa.summary.total }
      : null,
    qaReviewItems: qa?.items ?? [],
    tailoringRunning: tailor?.running ?? false,
    tailoringJob: tailor?.job?.title ?? tailor?.active_item?.title ?? null,
    tailoringQueue: tailor?.queue?.length ?? 0,
    tailoringLogTail: tailor?.log_tail ?? '',
  };
}

// ---------------------------------------------------------------------------
// Main View
// ---------------------------------------------------------------------------
export default function PipelineEditorView() {
  const [config, setConfig] = useState<ScraperConfig | null>(null);
  const [origConfig, setOrigConfig] = useState<ScraperConfig | null>(null);
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [qaStatus, setQaStatus] = useState<QALlmReviewStatus | null>(null);
  const [live, setLive] = useState<LiveStatus>(INITIAL_LIVE_STATUS);
  const [selectedNode, setSelectedNode] = useState<{ id: string; type: string } | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('overview');
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastPollAt, setLastPollAt] = useState<number | null>(null);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const snapshotRef = useRef<PipelineSnapshot | null>(null);

  const refreshLiveSnapshot = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const [nextStats, scrape, qa, tailor] = await Promise.all([
        api.getScraperPipelineStats().catch(() => null),
        api.getScrapeRunnerStatus().catch(() => null),
        api.getQALlmReviewStatus().catch(() => null),
        api.getTailoringRunnerStatus().catch(() => null),
      ]);

      const nextLive = buildLiveStatus(scrape, qa, tailor);
      const nextSnapshot = { live: nextLive, stats: nextStats };

      setStats(nextStats);
      setQaStatus(qa);
      setLive(nextLive);
      setLastPollAt(Date.now());

      const freshEvents = buildPipelineEvents(snapshotRef.current, nextSnapshot);
      if (freshEvents.length > 0) {
        setEvents((prev) => [...freshEvents.reverse(), ...prev].slice(0, 20));
      }
      snapshotRef.current = nextSnapshot;
    } catch {
      // Keep existing resilient polling behavior.
    } finally {
      if (manual) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.getScraperConfig(),
      api.getScraperPipelineStats().catch(() => null),
      api.getScrapeRunnerStatus().catch(() => null),
      api.getQALlmReviewStatus().catch(() => null),
      api.getTailoringRunnerStatus().catch(() => null),
    ])
      .then(([cfg, st, scrape, qa, tailor]) => {
        if (!active) return;
        const nextLive = buildLiveStatus(scrape, qa, tailor);
        setConfig(cfg);
        setOrigConfig(JSON.parse(JSON.stringify(cfg)));
        setStats(st);
        setQaStatus(qa);
        setLive(nextLive);
        setLastPollAt(Date.now());
        snapshotRef.current = { live: nextLive, stats: st };
      })
      .catch(e => setError(e.message));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      void refreshLiveSnapshot(false);
    }, 4000);
    return () => clearInterval(id);
  }, [refreshLiveSnapshot]);

  const dirty = useMemo(() => {
    if (!config || !origConfig) return false;
    return JSON.stringify(config) !== JSON.stringify(origConfig);
  }, [config, origConfig]);

  const sourceStats = useMemo(() => aggregateSourceStats(stats?.per_source), [stats]);

  const handleSelect = useCallback((id: string, type: string) => {
    setSelectedNode(prev => prev?.id === id ? null : { id, type });
  }, []);

  const handleToggleSource = useCallback((sourceId: string) => {
    if (!config) return;
    setConfig(prev => {
      if (!prev) return prev;
      if (sourceId === 'searxng') {
        return { ...prev, searxng: { ...prev.searxng, enabled: !prev.searxng.enabled } };
      }
      if (sourceId === 'usajobs') {
        return { ...prev, usajobs: { ...prev.usajobs, enabled: !prev.usajobs.enabled } };
      }
      // Board sources: toggle all boards of this type
      const boards = prev.boards.map(b =>
        b.board_type === sourceId ? { ...b, enabled: !prev.boards.filter(x => x.board_type === sourceId).every(x => x.enabled) } : b
      );
      return { ...prev, boards };
    });
  }, [config]);

  const handleConfigChange = useCallback((patch: Partial<ScraperConfig>) => {
    setConfig(prev => prev ? { ...prev, ...patch } : prev);
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
    } catch (e: any) {
      setError(e.message);
    }
    setSaving(false);
  }, [config]);

  const handleReset = useCallback(() => {
    if (origConfig) setConfig(JSON.parse(JSON.stringify(origConfig)));
  }, [origConfig]);

  useEffect(() => {
    setInspectorTab(selectedNode ? 'configure' : 'overview');
  }, [selectedNode]);

  // Build React Flow nodes/edges from config
  const nodes = useMemo(() => {
    if (!config) return [];
    return buildNodes(config, stats, live, sourceStats, handleSelect, handleToggleSource);
  }, [config, stats, live, sourceStats, handleSelect, handleToggleSource]);

  const edges = useMemo(() => {
    if (!config) return [];
    return buildEdges(config, live);
  }, [config, live]);

  // Handle stage reorder via drag
  const handleNodeDragStop = useCallback((_: any, node: Node) => {
    if (!config) return;
    const stageIdx = config.pipeline_order.indexOf(node.id);
    if (stageIdx < 0) return; // not a pipeline stage

    const stageNodes = config.pipeline_order.map(id => ({
      id,
      x: id === node.id ? (node.position?.x ?? 0) : (STAGE_X + config.pipeline_order.indexOf(id) * STAGE_GAP),
    }));
    stageNodes.sort((a, b) => a.x - b.x);
    const newOrder = stageNodes.map(n => n.id);

    if (JSON.stringify(newOrder) !== JSON.stringify(config.pipeline_order)) {
      setConfig(prev => prev ? { ...prev, pipeline_order: newOrder } : prev);
    }
  }, [config]);

  if (error) {
    return (
      <div className="view-container" style={{ padding: 40, color: 'var(--red)' }}>
        Error loading pipeline config: {error}
      </div>
    );
  }

  if (!config) {
    return (
      <div className="view-container">
        <div className="loading"><div className="spinner" /></div>
      </div>
    );
  }

  return (
    <div className="pipeline-editor">
      <ReactFlowProvider>
        <div className="pipeline-canvas">
          <CanvasToolbar
            live={live}
            dirty={dirty}
            saving={saving}
            refreshing={refreshing}
            lastPollAt={lastPollAt}
            eventCount={events.length}
            onRefresh={() => { void refreshLiveSnapshot(true); }}
            onReset={handleReset}
            onSave={() => { void handleSave(); }}
          />
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeDragStop={handleNodeDragStop}
            onPaneClick={() => setSelectedNode(null)}
            fitView
            fitViewOptions={{ padding: 0.06, maxZoom: 1 }}
            proOptions={{ hideAttribution: true }}
            minZoom={0.3}
            maxZoom={1.2}
            defaultEdgeOptions={{ animated: false }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
            <MiniMap pannable zoomable />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        <PipelineInspector
          selectedNode={selectedNode}
          inspectorTab={inspectorTab}
          onTabChange={setInspectorTab}
          onClearSelection={() => setSelectedNode(null)}
          config={config}
          stats={stats}
          qaStatus={qaStatus}
          live={live}
          events={events}
          sourceStats={sourceStats}
          onConfigChange={handleConfigChange}
        />
      </ReactFlowProvider>
    </div>
  );
}
