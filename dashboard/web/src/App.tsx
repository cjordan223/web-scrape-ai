import { Component, Suspense, lazy, useEffect, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';
import AppShell from './components/layout/AppShell';
import { api } from './api';

import './styles/global.css';

const JobsView = lazy(() => import('./views/domains/scraping/intake/JobsView'));
const RejectedView = lazy(() => import('./views/domains/scraping/intake/RejectedView'));
const QAView = lazy(() => import('./views/domains/tailoring/qa/QAView'));
const TailoringView = lazy(() => import('./views/domains/tailoring/runs/TailoringView'));
const IngestView = lazy(() => import('./views/domains/tailoring/runs/IngestView'));
const TailoringRejectedView = lazy(() => import('./views/domains/tailoring/rejected/RejectedView'));
const PackagesView = lazy(() => import('./views/domains/tailoring/outputs/PackagesView'));
const AppliedView = lazy(() => import('./views/domains/tailoring/outputs/AppliedView'));
const LeadsView = lazy(() => import('./views/domains/tailoring/leads/LeadsView'));
const SqlConsoleView = lazy(() => import('./views/domains/ops/diagnostics/SqlConsoleView'));
const PipelineView = lazy(() => import('./views/domains/ops/diagnostics/PipelineView'));
const PipelineEditorView = lazy(() => import('./views/domains/ops/diagnostics/PipelineEditorView'));
const LlmProvidersView = lazy(() => import('./views/domains/ops/LlmProvidersView'));
const MetricsView = lazy(() => import('./views/domains/ops/MetricsView'));
const SystemStatusView = lazy(() => import('./views/domains/ops/SystemStatusView'));
const ScraperMetricsView = lazy(() => import('./views/domains/ops/ScraperMetricsView'));
const QaReviewReportsView = lazy(() => import('./views/domains/ops/QaReviewReportsView'));
const MobileShell = lazy(() => import('./components/layout/MobileShell'));
const MobileQAView = lazy(() => import('./views/mobile/MobileQAView'));
const MobileDocsView = lazy(() => import('./views/mobile/MobileDocsView'));
const MobileJobsView = lazy(() => import('./views/mobile/MobileJobsView'));
const MobileIngestView = lazy(() => import('./views/mobile/MobileIngestView'));

function RouteLoading() {
  return (
    <div className="view-container">
      <div className="loading"><div className="spinner"></div></div>
    </div>
  );
}

const CHUNK_RELOAD_KEY = 'dashboard.chunk-reload-once';
const ASSET_RELOAD_KEY = 'dashboard.asset-reload-once';

function isRecoverableChunkError(error: unknown): error is Error {
  if (!(error instanceof Error)) return false;
  const text = `${error.name} ${error.message}`.toLowerCase();
  return (
    text.includes('dynamically imported module') ||
    text.includes('loading chunk') ||
    text.includes('chunkloaderror') ||
    text.includes('importing a module script failed') ||
    text.includes('disallowed mime type')
  );
}

class ChunkErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, _info: ErrorInfo) {
    if (typeof window === 'undefined' || !isRecoverableChunkError(error)) return;
    const hasReloaded = window.sessionStorage.getItem(CHUNK_RELOAD_KEY) === '1';
    if (!hasReloaded) {
      window.sessionStorage.setItem(CHUNK_RELOAD_KEY, '1');
      window.location.reload();
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="view-container">
          <div className="loading" style={{ flexDirection: 'column', gap: '12px', color: 'var(--text-secondary)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.82rem' }}>
              This view fell out of date after a frontend rebuild.
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => window.location.reload()}>
              Reload UI
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function LazyRoute({ children }: { children: ReactNode }) {
  return (
    <ChunkErrorBoundary>
      <Suspense fallback={<RouteLoading />}>{children}</Suspense>
    </ChunkErrorBoundary>
  );
}

function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search}`} replace />;
}

function PrefixRedirect({ from, to }: { from: string; to: string }) {
  const location = useLocation();
  const nextPath = location.pathname.startsWith(from)
    ? `${to}${location.pathname.slice(from.length)}`
    : to;
  return <Navigate to={`${nextPath}${location.search}`} replace />;
}

function SmartRedirect() {
  const isMobile = window.innerWidth < 768;
  return <Navigate to={isMobile ? '/m/qa' : '/pipeline/editor'} replace />;
}

function App() {
  const [dbSizeLabel, setDbSizeLabel] = useState('...');

  useEffect(() => {
    window.sessionStorage.removeItem(CHUNK_RELOAD_KEY);
    window.sessionStorage.removeItem(ASSET_RELOAD_KEY);
    api.getOverview().then((d: any) => {
      if (d.db_size) setDbSizeLabel(d.db_size);
    }).catch(() => { });
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SmartRedirect />} />

        <Route element={<LazyRoute><MobileShell /></LazyRoute>}>
          <Route path="/m" element={<Navigate to="/m/qa" replace />} />
          <Route path="/m/ingest" element={<LazyRoute><MobileIngestView /></LazyRoute>} />
          <Route path="/m/qa" element={<LazyRoute><MobileQAView /></LazyRoute>} />
          <Route path="/m/jobs" element={<LazyRoute><MobileJobsView /></LazyRoute>} />
          <Route path="/m/docs" element={<LazyRoute><MobileDocsView /></LazyRoute>} />
        </Route>

        <Route element={<AppShell dbSizeLabel={dbSizeLabel} />}>
          {/* Pipeline Editor — new default landing */}
          <Route path="/pipeline/editor" element={<LazyRoute><PipelineEditorView /></LazyRoute>} />

          {/* Pipeline workflow */}
          <Route path="/pipeline" element={<Navigate to="/pipeline/editor" replace />} />
          <Route path="/pipeline/ready" element={<LazyRoute><TailoringView /></LazyRoute>} />
          <Route path="/pipeline/ingest" element={<LazyRoute><IngestView /></LazyRoute>} />
          <Route path="/pipeline/editor/:runId" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/pipeline/qa" element={<LazyRoute><QAView /></LazyRoute>} />
          <Route path="/pipeline/packages" element={<LazyRoute><PackagesView /></LazyRoute>} />
          <Route path="/pipeline/applied" element={<LazyRoute><AppliedView /></LazyRoute>} />
          <Route path="/pipeline/leads" element={<LazyRoute><LeadsView /></LazyRoute>} />

          {/* Ops */}
          <Route path="/ops" element={<Navigate to="/ops/inventory" replace />} />
          <Route path="/ops/inventory" element={<LazyRoute><JobsView /></LazyRoute>} />
          <Route path="/ops/rejected" element={<Navigate to="/ops/rejected/scraper" replace />} />
          <Route path="/ops/rejected/scraper" element={<LazyRoute><RejectedView /></LazyRoute>} />
          <Route path="/ops/rejected/qa" element={<LazyRoute><TailoringRejectedView /></LazyRoute>} />
          <Route path="/ops/traces" element={<LazyRoute><PipelineView /></LazyRoute>} />
          <Route path="/ops/llm" element={<LazyRoute><LlmProvidersView /></LazyRoute>} />
          <Route path="/ops/metrics" element={<LazyRoute><MetricsView /></LazyRoute>} />
          <Route path="/ops/scraper" element={<LazyRoute><ScraperMetricsView /></LazyRoute>} />
          <Route path="/ops/qa-reports" element={<LazyRoute><QaReviewReportsView /></LazyRoute>} />
          <Route path="/ops/system" element={<LazyRoute><SystemStatusView /></LazyRoute>} />
          <Route path="/ops/admin" element={<LazyRoute><SqlConsoleView /></LazyRoute>} />

          {/* Redirects — removed views → pipeline editor */}
          <Route path="/overview" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/ops/dedup" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/ops/schedules" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/ops/explorer" element={<LegacyRedirect to="/ops/admin" />} />
          <Route path="/ops/archives" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/ops/jobs" element={<LegacyRedirect to="/ops/inventory" />} />
          <Route path="/ops/pipeline-editor" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/ops/pipeline-inspector" element={<LegacyRedirect to="/ops/traces" />} />

          {/* Legacy redirects */}
          <Route path="/home" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/home/overview" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/scraping" element={<LegacyRedirect to="/ops/inventory" />} />
          <Route path="/scraping/intake/jobs" element={<LegacyRedirect to="/ops/inventory" />} />
          <Route path="/scraping/intake/rejected" element={<LegacyRedirect to="/ops/rejected/scraper" />} />
          <Route path="/pipeline/runs" element={<PrefixRedirect from="/pipeline/runs" to="/pipeline/editor" />} />
          <Route path="/pipeline/runs/:runId" element={<PrefixRedirect from="/pipeline/runs" to="/pipeline/editor" />} />
          <Route path="/scraping/runs" element={<PrefixRedirect from="/scraping/runs" to="/pipeline/editor" />} />
          <Route path="/scraping/runs/:runId" element={<PrefixRedirect from="/scraping/runs" to="/pipeline/editor" />} />
          <Route path="/scraping/quality/dedup" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/scraping/quality/schedules" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/tailoring" element={<LegacyRedirect to="/pipeline/ready" />} />
          <Route path="/tailoring/qa" element={<LegacyRedirect to="/pipeline/ready" />} />
          <Route path="/pipeline/rejected" element={<LegacyRedirect to="/ops/rejected/qa" />} />
          <Route path="/tailoring/runs" element={<LegacyRedirect to="/pipeline/ready" />} />
          <Route path="/tailoring/outputs/packages" element={<LegacyRedirect to="/pipeline/packages" />} />
          <Route path="/tailoring/outputs/applied" element={<LegacyRedirect to="/pipeline/applied" />} />
          <Route path="/ops/data/explorer" element={<LegacyRedirect to="/ops/admin" />} />
          <Route path="/ops/data/archives" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/ops/diagnostics/sql" element={<LegacyRedirect to="/ops/admin" />} />
          <Route path="/ops/diagnostics/pipeline" element={<LegacyRedirect to="/ops/traces" />} />
          <Route path="/pipeline/jobs" element={<LegacyRedirect to="/pipeline/ready" />} />
          <Route path="/jobs" element={<LegacyRedirect to="/ops/inventory" />} />
          <Route path="/rejected" element={<LegacyRedirect to="/ops/rejected/scraper" />} />
          <Route path="/runs" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/runs/:runId" element={<PrefixRedirect from="/runs" to="/pipeline/editor" />} />
          <Route path="/packages" element={<LegacyRedirect to="/pipeline/packages" />} />
          <Route path="/applied" element={<LegacyRedirect to="/pipeline/applied" />} />
          <Route path="/dedup" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/schedules" element={<LegacyRedirect to="/pipeline/editor" />} />
          <Route path="/explorer" element={<LegacyRedirect to="/ops/admin" />} />
          <Route path="/sql" element={<LegacyRedirect to="/ops/admin" />} />

          <Route path="*" element={<Navigate to="/pipeline/editor" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
