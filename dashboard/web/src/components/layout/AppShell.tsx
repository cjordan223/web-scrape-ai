import type { ComponentType } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  GitMerge,
  Settings,
  Archive,
  Briefcase,
  XCircle,
  Activity,
  Layers,
  Clock,
  Package,
  Database,
  Terminal,
  GitBranch,
  CheckSquare,
  FileCheck,
  ClipboardPaste,
} from 'lucide-react';

type NavItem = {
  label: string;
  to: string;
  icon: ComponentType<{ size?: number }>;
  desc?: string;
  end?: boolean;
};

type Domain = {
  key: string;
  label: string;
  basePath: string;
  icon: ComponentType<{ size?: number }>;
  items: NavItem[];
};

const domains: Domain[] = [
  {
    key: 'overview',
    label: 'Overview',
    basePath: '/overview',
    icon: LayoutDashboard,
    items: [],
  },
  {
    key: 'pipeline',
    label: 'Pipeline',
    basePath: '/pipeline',
    icon: GitMerge,
    items: [
      { label: 'Ingest', to: '/pipeline/ingest', icon: ClipboardPaste, end: true },
      { label: 'Runs', to: '/pipeline/ingest/runs', icon: Activity, desc: 'Scrape ingest controls' },
      { label: 'QA', to: '/pipeline/qa', icon: CheckSquare },
      { label: 'Ready', to: '/pipeline/ready', icon: Briefcase, desc: 'QA-approved backlog' },
      { label: 'Rejected', to: '/pipeline/rejected', icon: XCircle, desc: 'QA-rejected backlog' },
      { label: 'Packages', to: '/pipeline/packages', icon: Package },
      { label: 'Applied', to: '/pipeline/applied', icon: FileCheck },
    ],
  },
  {
    key: 'ops',
    label: 'Ops',
    basePath: '/ops',
    icon: Settings,
    items: [
      { label: 'Inventory', to: '/ops/jobs', icon: Briefcase, desc: 'All stored results by workflow state' },
      { label: 'Rejected', to: '/ops/rejected', icon: XCircle, desc: 'Filtered out by pipeline' },
      { label: 'Dedup & Growth', to: '/ops/dedup', icon: Layers, desc: 'URL dedup stats & trends' },
      { label: 'Schedules', to: '/ops/schedules', icon: Clock, desc: 'Scrape schedule & history' },
      { label: 'DB Explorer', to: '/ops/explorer', icon: Database, desc: 'Browse raw tables' },
      { label: 'Archives', to: '/ops/archives', icon: Archive, desc: 'Snapshot & restore DB' },
      { label: 'Pipeline Inspector', to: '/ops/pipeline-inspector', icon: GitBranch, desc: 'Filter stage debugger' },
      { label: 'Admin', to: '/ops/admin', icon: Terminal, desc: 'SQL console & bulk ops' },
    ],
  },
];

const labelBySegment: Record<string, string> = {
  overview: 'Overview',
  pipeline: 'Pipeline',
  ingest: 'Ingest',
  qa: 'QA',
  ready: 'Ready',
  packages: 'Packages',
  applied: 'Applied',
  jobs: 'Inventory',
  rejected: 'Rejected',
  runs: 'Runs',
  ops: 'Ops',
  dedup: 'Dedup & Growth',
  schedules: 'Schedules',
  explorer: 'DB Explorer',
  archives: 'Archives',
  'pipeline-inspector': 'Pipeline Inspector',
  admin: 'Admin',
};

function getActiveDomain(pathname: string): Domain {
  const sorted = [...domains].sort((a, b) => b.basePath.length - a.basePath.length);
  return sorted.find((domain) => pathname.startsWith(domain.basePath)) ?? domains[0];
}

function buildBreadcrumbs(pathname: string): string[] {
  const runDetailMatch = pathname.match(/^\/pipeline\/ingest\/runs\/([^/]+)$/);
  if (runDetailMatch) {
    return ['Pipeline', 'Ingest', 'Runs', `Run ${runDetailMatch[1]}`];
  }

  const segments = pathname.split('/').filter(Boolean);
  if (segments.length === 0) {
    return ['Overview'];
  }

  return segments.map((segment) => labelBySegment[segment] ?? segment);
}

export default function AppShell({ dbSizeLabel }: { dbSizeLabel: string }) {
  const location = useLocation();
  const activeDomain = getActiveDomain(location.pathname);
  const breadcrumbs = buildBreadcrumbs(location.pathname);

  return (
    <>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span>Job</span>Forge
        </div>

        <nav className="sidebar-nav">
          {domains.map((domain) => {
            const Icon = domain.icon;
            const isActiveDomain = activeDomain.key === domain.key;

            return (
              <div key={domain.key} className="nav-domain-container">
                <NavLink
                  to={domain.basePath}
                  className={({ isActive }) => `nav-item ${isActive || isActiveDomain ? 'active' : ''}`}
                >
                  <Icon size={18} />
                  <span>{domain.label}</span>
                </NavLink>

                {isActiveDomain && domain.items.length > 0 && (
                  <div className="nav-nested-groups">
                    <div className="nav-group">
                      {domain.items.map((item) => {
                        const ItemIcon = item.icon;
                        return (
                          <NavLink
                            key={item.to}
                            to={item.to}
                            end={item.end}
                            className={({ isActive }) => `nav-item nav-item-nested ${isActive ? 'active' : ''}`}
                          >
                            <ItemIcon size={18} />
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                              <span>{item.label}</span>
                              {item.desc && <span className="nav-desc">{item.desc}</span>}
                            </div>
                          </NavLink>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="db-size">{dbSizeLabel}</div>
          v4.0 · Flat IA
        </div>
      </aside>

      <div className="main">
        <div className="page-chrome">
          <div className="breadcrumbs">
            {breadcrumbs.map((crumb, idx) => (
              <span key={`${crumb}-${idx}`} className="crumb">
                {crumb}
                {idx < breadcrumbs.length - 1 && <span className="crumb-sep">/</span>}
              </span>
            ))}
          </div>
        </div>

        <Outlet />
      </div>
    </>
  );
}
