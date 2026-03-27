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
                        const hasChildren = !!item.items?.length;
                        const isParentActive = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
                        return (
                          <div key={item.to}>
                            <NavLink
                              to={item.to}
                              end={item.end}
                              className={({ isActive }) => `nav-item nav-item-nested ${(isActive || isParentActive) ? 'active' : ''}`}
                            >
                              <ItemIcon size={18} />
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                                <span>{item.label}</span>
                                {item.desc && <span className="nav-desc">{item.desc}</span>}
                              </div>
                            </NavLink>

                            {hasChildren && isParentActive && (
                              <div className="nav-nested-groups nav-nested-groups-deep">
                                <div className="nav-group">
                                  {item.items!.map((child) => {
                                    const ChildIcon = child.icon;
                                    return (
                                      <NavLink
                                        key={child.to}
                                        to={child.to}
                                        end={child.end}
                                        className={({ isActive }) => `nav-item nav-item-nested nav-item-nested-deep ${isActive ? 'active' : ''}`}
                                      >
                                        <ChildIcon size={18} />
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                                          <span>{child.label}</span>
                                          {child.desc && <span className="nav-desc">{child.desc}</span>}
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
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="db-size">{dbSizeLabel}</div>
          v5.0 · Pipeline
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
