import { Suspense, lazy, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
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
const TailoringView = lazy(() => import('./views/domains/tailoring/runs/TailoringView'));
const PackagesView = lazy(() => import('./views/domains/tailoring/outputs/PackagesView'));
const DedupView = lazy(() => import('./views/domains/scraping/quality/DedupView'));
const SchedulesView = lazy(() => import('./views/domains/scraping/quality/SchedulesView'));
const ExplorerView = lazy(() => import('./views/domains/ops/data/ExplorerView'));
const SqlConsoleView = lazy(() => import('./views/domains/ops/diagnostics/SqlConsoleView'));
const PipelineView = lazy(() => import('./views/domains/ops/diagnostics/PipelineView'));
const ArchiveView = lazy(() => import('./views/domains/ops/data/ArchiveView'));
const MobileShell = lazy(() => import('./components/layout/MobileShell'));
const MobileIngestView = lazy(() => import('./views/mobile/MobileIngestView'));
const MobileDocsView = lazy(() => import('./views/mobile/MobileDocsView'));
const MobileJobsView = lazy(() => import('./views/mobile/MobileJobsView'));

function RouteLoading() {
  return (
    <div className="view-container">
      <div className="loading"><div className="spinner"></div></div>
    </div>
  );
}

function LazyRoute({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteLoading />}>{children}</Suspense>;
}

function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search}`} replace />;
}

function SmartRedirect() {
  const isMobile = window.innerWidth < 768;
  return <Navigate to={isMobile ? '/m/ingest' : '/home/overview'} replace />;
}

function App() {
  const [dbSizeLabel, setDbSizeLabel] = useState('...');

  useEffect(() => {
    api.getOverview().then((d: any) => {
      if (d.db_size) setDbSizeLabel(d.db_size);
    }).catch(() => { });
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SmartRedirect />} />

        <Route element={<LazyRoute><MobileShell /></LazyRoute>}>
          <Route path="/m" element={<Navigate to="/m/ingest" replace />} />
          <Route path="/m/ingest" element={<LazyRoute><MobileIngestView /></LazyRoute>} />
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

          <Route path="/tailoring" element={<LegacyRedirect to="/tailoring/runs" />} />
          <Route path="/tailoring/runs" element={<LazyRoute><TailoringView /></LazyRoute>} />
          <Route path="/tailoring/outputs/packages" element={<LazyRoute><PackagesView /></LazyRoute>} />

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
