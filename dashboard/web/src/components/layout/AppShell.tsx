import type { ComponentType } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Compass,
  FolderTree,
  PenTool,
  Settings,
  Archive,
  LayoutDashboard,
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
} from 'lucide-react';

type NavItem = {
  label: string;
  to: string;
  icon: ComponentType<{ size?: number }>;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

type Domain = {
  key: string;
  label: string;
  basePath: string;
  icon: ComponentType<{ size?: number }>;
  groups: NavGroup[];
};

const domains: Domain[] = [
  {
    key: 'home',
    label: 'Home',
    basePath: '/home',
    icon: Compass,
    groups: [
      {
        label: 'Control Plane',
        items: [{ label: 'Overview', to: '/home/overview', icon: LayoutDashboard }],
      },
    ],
  },
  {
    key: 'scraping',
    label: 'Scraping',
    basePath: '/scraping',
    icon: FolderTree,
    groups: [
      {
        label: 'Intake',
        items: [
          { label: 'Jobs', to: '/scraping/intake/jobs', icon: Briefcase },
          { label: 'Rejected', to: '/scraping/intake/rejected', icon: XCircle },
        ],
      },
      {
        label: 'Runs',
        items: [{ label: 'Run List', to: '/scraping/runs', icon: Activity }],
      },
      {
        label: 'Quality',
        items: [
          { label: 'Dedup & Growth', to: '/scraping/quality/dedup', icon: Layers },
          { label: 'Schedules', to: '/scraping/quality/schedules', icon: Clock },
        ],
      },
    ],
  },
  {
    key: 'tailoring',
    label: 'Tailoring',
    basePath: '/tailoring',
    icon: PenTool,
    groups: [
      {
        label: 'Triage',
        items: [{ label: 'QA', to: '/tailoring/qa', icon: CheckSquare }],
      },
      {
        label: 'Runs',
        items: [{ label: 'Manual & Traces', to: '/tailoring/runs', icon: Activity }],
      },
      {
        label: 'Outputs',
        items: [
          { label: 'Packages', to: '/tailoring/outputs/packages', icon: Package },
          { label: 'Applied', to: '/tailoring/outputs/applied', icon: Archive },
        ],
      },
    ],
  },
  {
    key: 'ops',
    label: 'Ops',
    basePath: '/ops',
    icon: Settings,
    groups: [
      {
        label: 'Data',
        items: [
          { label: 'DB Explorer', to: '/ops/data/explorer', icon: Database },
          { label: 'Archives', to: '/ops/data/archives', icon: Archive },
        ],
      },
      {
        label: 'Diagnostics',
        items: [
          { label: 'Pipeline Inspector', to: '/ops/diagnostics/pipeline', icon: GitBranch },
          { label: 'Admin Ops', to: '/ops/diagnostics/sql', icon: Terminal },
        ],
      },
    ],
  },
];

const labelBySegment: Record<string, string> = {
  home: 'Home',
  overview: 'Overview',
  scraping: 'Scraping',
  intake: 'Intake',
  jobs: 'Jobs',
  rejected: 'Rejected',
  runs: 'Runs',
  quality: 'Quality',
  dedup: 'Dedup & Growth',
  schedules: 'Schedules',
  tailoring: 'Tailoring',
  outputs: 'Outputs',
  packages: 'Packages',
  applied: 'Applied',
  ops: 'Ops',
  data: 'Data',
  explorer: 'DB Explorer',
  archives: 'Archives',
  diagnostics: 'Diagnostics',
  sql: 'Admin Ops',
  pipeline: 'Pipeline Inspector',
};

function getActiveDomain(pathname: string): Domain {
  const sorted = [...domains].sort((a, b) => b.basePath.length - a.basePath.length);
  return sorted.find((domain) => pathname.startsWith(domain.basePath)) ?? domains[0];
}

function buildBreadcrumbs(pathname: string): string[] {
  const runDetailMatch = pathname.match(/^\/scraping\/runs\/([^/]+)$/);
  if (runDetailMatch) {
    return ['Scraping', 'Runs', `Run ${runDetailMatch[1]}`];
  }

  const segments = pathname.split('/').filter(Boolean);
  if (segments.length === 0) {
    return ['Home'];
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
          <span>Job</span> Scraper
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Domains</div>
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

                {isActiveDomain && domain.groups.length > 0 && (
                  <div className="nav-nested-groups">
                    {domain.groups.map((group) => (
                      <div key={group.label} className="nav-group">
                        {group.items.map((item) => {
                          const ItemIcon = item.icon;
                          return (
                            <NavLink
                              key={item.to}
                              to={item.to}
                              className={({ isActive }) => `nav-item nav-item-nested ${isActive ? 'active' : ''}`}
                            >
                              <ItemIcon size={18} />
                              <span>{item.label}</span>
                            </NavLink>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="db-size">{dbSizeLabel}</div>
          v3.0 · Nested IA
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
