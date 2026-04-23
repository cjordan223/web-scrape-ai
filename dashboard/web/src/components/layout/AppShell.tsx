import type { ComponentType } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  GitBranch,
  Briefcase,
  XCircle,
  Package,
  Terminal,
  FileCheck,
  ClipboardPaste,
  CheckSquare,
  Workflow,
  Lightbulb,
  Cpu,
  BarChart3,
  Gauge,
  Activity,
  ClipboardCheck,
  Library,
} from 'lucide-react';

type NavItem = {
  label: string;
  to: string;
  icon: ComponentType<{ size?: number }>;
  desc?: string;
  end?: boolean;
  items?: NavItem[];
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
    key: 'pipeline',
    label: 'Pipeline',
    basePath: '/pipeline',
    icon: Workflow,
    items: [
      { label: 'Editor', to: '/pipeline/editor', icon: GitBranch, desc: 'Visual pipeline control', end: true },
      { label: 'Ingest', to: '/pipeline/ingest', icon: ClipboardPaste, end: true },
      { label: 'QA', to: '/pipeline/qa', icon: CheckSquare, desc: 'Approve, reject, LLM review' },
      { label: 'Leads', to: '/pipeline/leads', icon: Lightbulb, desc: 'HN finds — browse & ingest' },
      { label: 'Ready', to: '/pipeline/ready', icon: Briefcase, desc: 'QA-approved backlog' },
      { label: 'Packages', to: '/pipeline/packages', icon: Package },
      { label: 'Applied', to: '/pipeline/applied', icon: FileCheck },
    ],
  },
  {
    key: 'ops',
    label: 'Ops',
    basePath: '/ops',
    icon: Terminal,
    items: [
      { label: 'Inventory', to: '/ops/inventory', icon: Briefcase, desc: 'All stored results' },
      {
        label: 'Rejected',
        to: '/ops/rejected',
        icon: XCircle,
        desc: 'Rejected buckets',
        items: [
          { label: 'Scraper', to: '/ops/rejected/scraper', icon: XCircle, desc: 'Scraper filter rejects' },
          { label: 'QA', to: '/ops/rejected/qa', icon: XCircle, desc: 'QA-rejected backlog' },
        ],
      },
      { label: 'Traces', to: '/ops/traces', icon: GitBranch, desc: 'Tailoring LLM traces' },
      { label: 'LLM', to: '/ops/llm', icon: Cpu, desc: 'Provider keys & models' },
      { label: 'Metrics', to: '/ops/metrics', icon: BarChart3, desc: 'Tailoring performance' },
      { label: 'Scraper', to: '/ops/scraper', icon: Activity, desc: 'Tier-aware scrape metrics' },
      { label: 'QA Reports', to: '/ops/qa-reports', icon: ClipboardCheck, desc: 'LLM review audit trail' },
      { label: 'Persona', to: '/ops/persona', icon: Library, desc: 'Vignettes, voice & skills dossier' },
      { label: 'System', to: '/ops/system', icon: Gauge, desc: 'Scheduler & config snapshot' },
      { label: 'Admin', to: '/ops/admin', icon: Terminal, desc: 'SQL console & bulk ops' },
    ],
  },
];

const labelBySegment: Record<string, string> = {
  pipeline: 'Pipeline',
  editor: 'Editor',
  ingest: 'Ingest',
  qa: 'QA',
  ready: 'Ready',
  packages: 'Packages',
  applied: 'Applied',
  rejected: 'Rejected',
  scraper: 'Scraper',
  ops: 'Ops',
  inventory: 'Inventory',
  traces: 'Traces',
  llm: 'LLM',
  metrics: 'Metrics',
  'qa-reports': 'QA Reports',
  persona: 'Persona',
  system: 'System',
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
    return ['Pipeline'];
  }

  return segments.map((segment) => labelBySegment[segment] ?? segment);
}

export default function AppShell({ dbSizeLabel }: { dbSizeLabel: string }) {
  const location = useLocation();
  const activeDomain = getActiveDomain(location.pathname);
  const breadcrumbs = buildBreadcrumbs(location.pathname);

  return (
    <>
      <header className="top-nav">
        <div className="top-nav-brand">
          <span>Tex</span>Tailor
        </div>

        <div className="top-nav-center">
          {domains.map((domain) => {
            const Icon = domain.icon;
            const isActiveDomain = activeDomain.key === domain.key;
            return (
              <NavLink
                key={domain.key}
                to={domain.basePath}
                className={({ isActive }) => `top-nav-item ${isActive || isActiveDomain ? 'active' : ''}`}
              >
                <Icon size={16} />
                {domain.label}
              </NavLink>
            );
          })}
        </div>

        <div className="top-nav-right">
          v5.0 &middot; Pipeline
        </div>
      </header>

      <div className="layout-container">
        <aside className="context-sidebar">
          <nav className="sidebar-nav">
            {activeDomain.items.map((item) => {
              const ItemIcon = item.icon;
              const hasChildren = !!item.items?.length;
              const isParentActive = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
              return (
                <div key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => `nav-item ${(isActive || isParentActive) ? 'active' : ''}`}
                  >
                    <ItemIcon size={18} />
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                      <span>{item.label}</span>
                      {item.desc && <span className="nav-desc">{item.desc}</span>}
                    </div>
                  </NavLink>

                  {hasChildren && isParentActive && (
                    <div className="nav-nested-groups">
                      {item.items!.map((child) => {
                        const ChildIcon = child.icon;
                        return (
                          <NavLink
                            key={child.to}
                            to={child.to}
                            end={child.end}
                            className={({ isActive }) => `nav-item nav-item-nested ${isActive ? 'active' : ''}`}
                          >
                            <ChildIcon size={16} />
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                              <span>{child.label}</span>
                            </div>
                          </NavLink>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
          
          <div style={{ flex: 1 }} />
          <div className="sidebar-footer">
            <div className="db-size">{dbSizeLabel}</div>
          </div>
        </aside>

        <main className="main-content">
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
        </main>
      </div>
    </>
  );
}
