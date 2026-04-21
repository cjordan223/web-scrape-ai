import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { CheckCircle2, RefreshCw, Search, XCircle, AlertTriangle, MinusCircle, ExternalLink } from 'lucide-react';
import { api } from '../../../api';
import { fmtDate } from '../../../utils';

type ReviewSummary = {
  total?: number;
  completed?: number;
  passed?: number;
  failed?: number;
  skipped?: number;
  errors?: number;
  cancelled?: number;
};

type ReportListItem = {
  batch_id: number;
  started_at: string | null;
  ended_at: string | null;
  resolved_model: string | null;
  trigger_source: string | null;
  queued_count: number;
  report_generated_at: string | null;
  summary: ReviewSummary;
  scrape_run_ids: string[];
};

type ReportJob = {
  review_item_id: number;
  job_id: number;
  title: string;
  company: string;
  url: string;
  board: string;
  source: string;
  scrape_run_id: string;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  review_status: 'pass' | 'fail' | 'skipped' | 'error' | 'cancelled' | string;
  final_decision: string | null;
  reason: string;
  confidence: number | null;
  top_matches: string[];
  gaps: string[];
  polished: boolean;
  polished_with_llm: boolean;
};

type ReportDetail = ReportListItem & {
  generated_at: string | null;
  items: ReportJob[];
};

const panelStyle: CSSProperties = {
  border: '1px solid var(--border)',
  background: 'rgba(13, 18, 28, 0.68)',
  borderRadius: 8,
};

const headerCell: CSSProperties = {
  padding: '9px 10px',
  fontFamily: 'var(--font-mono)',
  fontSize: '.66rem',
  letterSpacing: '.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)',
};

const cell: CSSProperties = {
  padding: '10px',
  borderBottom: '1px solid rgba(255,255,255,0.06)',
  verticalAlign: 'top',
};

function pct(n: number | undefined, d: number | undefined) {
  if (!n || !d) return '0%';
  return `${Math.round((n / d) * 100)}%`;
}

function duration(start?: string | null, end?: string | null) {
  if (!start || !end) return '--';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '--';
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

function statusTone(status: string) {
  if (status === 'pass') return { color: 'var(--green)', bg: 'rgba(60,179,113,0.12)', icon: CheckCircle2 };
  if (status === 'fail') return { color: 'var(--red)', bg: 'rgba(196,68,68,0.12)', icon: XCircle };
  if (status === 'error') return { color: 'var(--amber)', bg: 'rgba(224,160,48,0.12)', icon: AlertTriangle };
  return { color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.06)', icon: MinusCircle };
}

function StatusPill({ status }: { status: string }) {
  const tone = statusTone(status);
  const Icon = tone.icon;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: tone.color, background: tone.bg, border: `1px solid ${tone.color}55`, borderRadius: 999, padding: '3px 8px', fontSize: '.72rem', fontFamily: 'var(--font-mono)' }}>
      <Icon size={12} />
      {status || 'unknown'}
    </span>
  );
}

function Metric({ label, value, tone = 'var(--text-primary)' }: { label: string; value: string | number; tone?: string }) {
  return (
    <div style={{ ...panelStyle, padding: '14px 16px' }}>
      <div style={{ color: 'var(--text-muted)', fontSize: '.72rem', textTransform: 'uppercase', letterSpacing: '.08em', fontFamily: 'var(--font-mono)' }}>{label}</div>
      <div style={{ color: tone, fontSize: 24, fontWeight: 700, marginTop: 5 }}>{value}</div>
    </div>
  );
}

export default function QaReviewReportsView() {
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getQALlmReviewReports(100);
      const items = res.items || [];
      setReports(items);
      setSelectedId((prev) => prev ?? items[0]?.batch_id ?? null);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadReports(); }, [loadReports]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    api.getQALlmReviewReport(selectedId)
      .then((res) => {
        if (!cancelled) setDetail(res.report || null);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedId]);

  const selectedSummary = detail?.summary || reports.find((r) => r.batch_id === selectedId)?.summary || {};
  const filteredJobs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (detail?.items || []).filter((item) => {
      if (statusFilter !== 'all' && item.review_status !== statusFilter) return false;
      if (!q) return true;
      return [item.title, item.company, item.url, item.board, item.source, item.reason, item.scrape_run_id]
        .some((v) => String(v || '').toLowerCase().includes(q));
    });
  }, [detail, search, statusFilter]);

  const latest = reports[0];
  const totalReviewed = reports.reduce((sum, r) => sum + (r.summary?.total || 0), 0);
  const totalPassed = reports.reduce((sum, r) => sum + (r.summary?.passed || 0), 0);
  const totalFailed = reports.reduce((sum, r) => sum + (r.summary?.failed || 0), 0);

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700 }}>QA LLM Review Reports</h1>
          <div style={{ color: 'var(--text-muted)', marginTop: 4, fontSize: 13 }}>
            {reports.length} batches · {totalReviewed} jobs reviewed · latest {latest?.ended_at ? fmtDate(latest.ended_at) : '--'}
          </div>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={loadReports} disabled={loading} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <RefreshCw size={14} />
          Refresh
        </button>
      </header>

      {error ? (
        <div style={{ ...panelStyle, padding: 14, color: 'var(--red)' }}>{error}</div>
      ) : null}

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
        <Metric label="Reports" value={reports.length} />
        <Metric label="Jobs Reviewed" value={totalReviewed} />
        <Metric label="Passed" value={`${totalPassed} · ${pct(totalPassed, totalReviewed)}`} tone="var(--green)" />
        <Metric label="Failed" value={`${totalFailed} · ${pct(totalFailed, totalReviewed)}`} tone="var(--red)" />
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: '360px minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
        <aside style={{ ...panelStyle, overflow: 'hidden' }}>
          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>Report History</strong>
            <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '.72rem' }}>{loading ? 'loading' : `${reports.length}`}</span>
          </div>
          <div style={{ maxHeight: 'calc(100vh - 330px)', overflow: 'auto' }}>
            {reports.length === 0 && !loading ? (
              <div style={{ padding: 16, color: 'var(--text-muted)' }}>No QLLM reports yet.</div>
            ) : null}
            {reports.map((report) => {
              const active = report.batch_id === selectedId;
              const s = report.summary || {};
              return (
                <button
                  key={report.batch_id}
                  type="button"
                  onClick={() => setSelectedId(report.batch_id)}
                  style={{
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
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <strong>Batch #{report.batch_id}</strong>
                    <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '.72rem' }}>{duration(report.started_at, report.ended_at)}</span>
                  </div>
                  <div style={{ marginTop: 5, color: 'var(--text-secondary)', fontSize: 12 }}>{report.ended_at ? fmtDate(report.ended_at) : 'Running'}</div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 9, flexWrap: 'wrap', fontFamily: 'var(--font-mono)', fontSize: '.7rem' }}>
                    <span style={{ color: 'var(--green)' }}>{s.passed || 0} pass</span>
                    <span style={{ color: 'var(--red)' }}>{s.failed || 0} fail</span>
                    <span style={{ color: 'var(--text-muted)' }}>{s.errors || 0} err</span>
                    <span style={{ color: 'var(--text-muted)' }}>{s.total || report.queued_count || 0} total</span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        <main style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
          <section style={{ ...panelStyle, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 20 }}>{detail ? `Batch #${detail.batch_id}` : 'Select a Report'}</h2>
                <div style={{ color: 'var(--text-muted)', marginTop: 5, fontSize: 12 }}>
                  {detailLoading ? 'Loading report...' : detail ? `${detail.resolved_model || 'unknown model'} · ${duration(detail.started_at, detail.ended_at)} · ${detail.trigger_source || 'manual'}` : '--'}
                </div>
              </div>
              <div style={{ textAlign: 'right', color: 'var(--text-muted)', fontSize: 12 }}>
                <div>Generated {detail?.generated_at ? fmtDate(detail.generated_at) : detail?.report_generated_at ? fmtDate(detail.report_generated_at) : '--'}</div>
                <div style={{ marginTop: 4 }}>Scrape runs {(detail?.scrape_run_ids || []).join(', ') || '--'}</div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 10, marginTop: 16 }}>
              <Metric label="Total" value={selectedSummary.total || 0} />
              <Metric label="Pass" value={selectedSummary.passed || 0} tone="var(--green)" />
              <Metric label="Fail" value={selectedSummary.failed || 0} tone="var(--red)" />
              <Metric label="Skipped" value={selectedSummary.skipped || 0} />
              <Metric label="Errors" value={selectedSummary.errors || 0} tone="var(--amber)" />
              <Metric label="Cancelled" value={selectedSummary.cancelled || 0} />
            </div>
          </section>

          <section style={{ ...panelStyle, overflow: 'hidden' }}>
            <div style={{ padding: 14, display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 180px', gap: 12, borderBottom: '1px solid var(--border)' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', borderRadius: 6, padding: '0 10px' }}>
                <Search size={15} color="var(--text-muted)" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search jobs, companies, reasons..."
                  style={{ width: '100%', background: 'transparent', border: 0, color: 'var(--text-primary)', outline: 0, height: 38 }}
                />
              </label>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: 6, padding: '0 10px' }}>
                <option value="all">All statuses</option>
                <option value="pass">Pass</option>
                <option value="fail">Fail</option>
                <option value="skipped">Skipped</option>
                <option value="error">Error</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>

            <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 520px)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
                <thead>
                  <tr>
                    <th style={headerCell}>Status</th>
                    <th style={headerCell}>Job</th>
                    <th style={headerCell}>Run</th>
                    <th style={headerCell}>Confidence</th>
                    <th style={headerCell}>Reason</th>
                    <th style={headerCell}>Signals</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredJobs.map((item) => (
                    <tr key={item.review_item_id}>
                      <td style={cell}><StatusPill status={item.review_status} /></td>
                      <td style={cell}>
                        <div style={{ fontWeight: 700 }}>{item.title || `Job #${item.job_id}`}</div>
                        <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{item.company || 'Unknown'} · {item.board || item.source || '--'}</div>
                        {item.url ? (
                          <a href={item.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 6, color: 'var(--blue)', fontSize: 12 }}>
                            Open JD <ExternalLink size={12} />
                          </a>
                        ) : null}
                      </td>
                      <td style={{ ...cell, fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--text-secondary)' }}>
                        {item.scrape_run_id || '--'}
                        <div style={{ marginTop: 5 }}>{item.completed_at ? fmtDate(item.completed_at) : '--'}</div>
                      </td>
                      <td style={{ ...cell, fontFamily: 'var(--font-mono)' }}>{item.confidence == null ? '--' : item.confidence.toFixed(2)}</td>
                      <td style={{ ...cell, maxWidth: 360 }}>
                        <div style={{ lineHeight: 1.45 }}>{item.reason || '--'}</div>
                        <div style={{ marginTop: 6, color: item.final_decision === 'qa_approved' ? 'var(--green)' : item.final_decision === 'qa_rejected' ? 'var(--red)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '.72rem' }}>
                          {item.final_decision || '--'}{item.polished ? ' · polished' : ''}
                        </div>
                      </td>
                      <td style={{ ...cell, maxWidth: 320 }}>
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                          {(item.top_matches || []).slice(0, 4).map((m) => (
                            <span key={`m-${item.review_item_id}-${m}`} style={{ border: '1px solid rgba(60,179,113,0.35)', color: 'var(--green)', borderRadius: 999, padding: '2px 7px', fontSize: 11 }}>{m}</span>
                          ))}
                          {(item.gaps || []).slice(0, 3).map((g) => (
                            <span key={`g-${item.review_item_id}-${g}`} style={{ border: '1px solid rgba(196,68,68,0.35)', color: 'var(--red)', borderRadius: 999, padding: '2px 7px', fontSize: 11 }}>{g}</span>
                          ))}
                          {(!item.top_matches?.length && !item.gaps?.length) ? <span style={{ color: 'var(--text-muted)' }}>--</span> : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {detail && filteredJobs.length === 0 ? (
                    <tr><td style={{ ...cell, color: 'var(--text-muted)' }} colSpan={6}>No jobs match the current filters.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </main>
      </section>
    </div>
  );
}
