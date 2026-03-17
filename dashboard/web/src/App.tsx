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

const OverviewView = lazy(() => import('./views/domains/home/OverviewView'));
const JobsView = lazy(() => import('./views/domains/scraping/intake/JobsView'));
const RejectedView = lazy(() => import('./views/domains/scraping/intake/RejectedView'));
const RunsView = lazy(() => import('./views/domains/scraping/runs/RunsView'));
const QAView = lazy(() => import('./views/domains/tailoring/qa/QAView'));
const TailoringView = lazy(() => import('./views/domains/tailoring/runs/TailoringView'));
const PackagesView = lazy(() => import('./views/domains/tailoring/outputs/PackagesView'));
const AppliedView = lazy(() => import('./views/domains/tailoring/outputs/AppliedView'));
const DedupView = lazy(() => import('./views/domains/scraping/quality/DedupView'));
const SchedulesView = lazy(() => import('./views/domains/scraping/quality/SchedulesView'));
const ExplorerView = lazy(() => import('./views/domains/ops/data/ExplorerView'));
const SqlConsoleView = lazy(() => import('./views/domains/ops/diagnostics/SqlConsoleView'));
const PipelineView = lazy(() => import('./views/domains/ops/diagnostics/PipelineView'));
const ArchiveView = lazy(() => import('./views/domains/ops/data/ArchiveView'));
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

function SmartRedirect() {
  const isMobile = window.innerWidth < 768;
  return <Navigate to={isMobile ? '/m/qa' : '/home/overview'} replace />;
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
          <Route path="/home" element={<Navigate to="/home/overview" replace />} />
          <Route path="/home/overview" element={<LazyRoute><OverviewView /></LazyRoute>} />

          <Route path="/scraping" element={<Navigate to="/scraping/intake/jobs" replace />} />
          <Route path="/scraping/intake/jobs" element={<LazyRoute><JobsView /></LazyRoute>} />
          <Route path="/scraping/intake/rejected" element={<LazyRoute><RejectedView /></LazyRoute>} />
          <Route path="/scraping/runs" element={<LazyRoute><RunsView /></LazyRoute>} />
          <Route path="/scraping/runs/:runId" element={<LazyRoute><RunsView /></LazyRoute>} />
          <Route path="/scraping/quality/dedup" element={<LazyRoute><DedupView /></LazyRoute>} />
          <Route path="/scraping/quality/schedules" element={<LazyRoute><SchedulesView /></LazyRoute>} />

          <Route path="/tailoring" element={<LegacyRedirect to="/tailoring/qa" />} />
          <Route path="/tailoring/qa" element={<LazyRoute><QAView /></LazyRoute>} />
          <Route path="/tailoring/runs" element={<LazyRoute><TailoringView /></LazyRoute>} />
          <Route path="/tailoring/outputs/packages" element={<LazyRoute><PackagesView /></LazyRoute>} />
          <Route path="/tailoring/outputs/applied" element={<LazyRoute><AppliedView /></LazyRoute>} />

          <Route path="/ops" element={<Navigate to="/ops/data/explorer" replace />} />
          <Route path="/ops/data/explorer" element={<LazyRoute><ExplorerView /></LazyRoute>} />
          <Route path="/ops/data/archives" element={<LazyRoute><ArchiveView /></LazyRoute>} />
          <Route path="/ops/diagnostics/sql" element={<LazyRoute><SqlConsoleView /></LazyRoute>} />
          <Route path="/ops/diagnostics/pipeline" element={<LazyRoute><PipelineView /></LazyRoute>} />

          <Route path="/overview" element={<LegacyRedirect to="/home/overview" />} />
          <Route path="/jobs" element={<LegacyRedirect to="/scraping/intake/jobs" />} />
          <Route path="/rejected" element={<LegacyRedirect to="/scraping/intake/rejected" />} />
          <Route path="/runs" element={<LegacyRedirect to="/scraping/runs" />} />
          <Route path="/packages" element={<LegacyRedirect to="/tailoring/outputs/packages" />} />
          <Route path="/applied" element={<LegacyRedirect to="/tailoring/outputs/applied" />} />
          <Route path="/dedup" element={<LegacyRedirect to="/scraping/quality/dedup" />} />
          <Route path="/schedules" element={<LegacyRedirect to="/scraping/quality/schedules" />} />
          <Route path="/explorer" element={<LegacyRedirect to="/ops/data/explorer" />} />
          <Route path="/sql" element={<LegacyRedirect to="/ops/diagnostics/sql" />} />

          <Route path="*" element={<Navigate to="/home/overview" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
