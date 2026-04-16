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
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('timestamp');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const refresh = useCallback(async () => {
    try {
      const data = await api.getTailoringMetrics();
      setMetrics(data.metrics || []);
      setBaselines(data.baselines || {});
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

  if (loading) return <div className="card" style={{ padding: 24 }}>Loading metrics...</div>;

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px' }}>Baselines (averages across {baselines.run_count ?? 0} runs)</h3>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          <Stat label="Wall Time" value={dur(baselines.total_wall_time_s)} />
          <Stat label="Queue Wait" value={dur(baselines.queue_wait_s)} />
          <Stat label="Analysis" value={dur(baselines.analysis_time_s)} />
          <Stat label="Resume" value={dur(baselines.resume_time_s)} />
          <Stat label="Cover" value={dur(baselines.cover_time_s)} />
          <Stat label="LLM Time" value={dur(baselines.total_llm_time_s)} />
          <Stat label="LLM Calls" value={num(baselines.total_llm_calls)} />
          <Stat label="Resume Attempts" value={num(baselines.resume_attempts)} />
          <Stat label="Cover Attempts" value={num(baselines.cover_attempts)} />
        </div>
      </div>

      {metrics.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
          No metrics yet. Run a tailoring job to start collecting data.
        </div>
      ) : (
        <div className="card" style={{ overflow: 'auto' }}>
          <table className="data-table" style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr>
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
                <tr key={row.id}>
                  <td>{fmtDate(row.timestamp)}</td>
                  <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <span title={`${row.job_company} — ${row.job_title}`}>
                      {row.job_company ? `${row.job_company} — ` : ''}{row.job_title || row.run_slug}
                    </span>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{row.model || '—'}</td>
                  <td>{dur(row.total_wall_time_s)}</td>
                  <td>{dur(row.queue_wait_s)}</td>
                  <td>{dur(row.analysis_time_s)}</td>
                  <td>
                    {dur(row.resume_time_s)}
                    {row.resume_attempts && row.resume_attempts > 1 && (
                      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}> ({row.resume_attempts} att)</span>
                    )}
                  </td>
                  <td>
                    {dur(row.cover_time_s)}
                    {row.cover_attempts && row.cover_attempts > 1 && (
                      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}> ({row.cover_attempts} att)</span>
                    )}
                  </td>
                  <td>{dur(row.total_llm_time_s)}</td>
                  <td>{num(row.total_llm_calls)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 20, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
    </div>
  );
}

function Th({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <th
      onClick={onClick}
      style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
    >
      {children}
    </th>
  );
}
