import { NavLink } from 'react-router-dom';
import {
    LayoutDashboard,
    Briefcase,
    XCircle,
    Activity,
    PenTool,
    Package,
    Layers,
    Clock,
    Database,
    Terminal,
} from 'lucide-react';

export default function Sidebar({ dbSizeLabel }: { dbSizeLabel: string }) {
    return (
        <aside className="sidebar">
            <div className="sidebar-brand">
                <span>Job</span> Scraper
            </div>
            <nav className="sidebar-nav">
                <NavLink to="/overview" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <LayoutDashboard size={18} />
                    <span>Overview</span>
                </NavLink>
                <NavLink to="/jobs" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Briefcase size={18} />
                    <span>Jobs</span>
                </NavLink>
                <NavLink to="/rejected" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <XCircle size={18} />
                    <span>Rejected</span>
                </NavLink>
                <NavLink to="/runs" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Activity size={18} />
                    <span>Runs</span>
                </NavLink>
                <NavLink to="/tailoring" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <PenTool size={18} />
                    <span>Tailoring</span>
                </NavLink>
                <NavLink to="/packages" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Package size={18} />
                    <span>Applications</span>
                </NavLink>
                <NavLink to="/dedup" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Layers size={18} />
                    <span>Dedup & Growth</span>
                </NavLink>
                <NavLink to="/schedules" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Clock size={18} />
                    <span>Schedules</span>
                </NavLink>
                <NavLink to="/explorer" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Database size={18} />
                    <span>DB Explorer</span>
                </NavLink>
                <NavLink to="/sql" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <Terminal size={18} />
                    <span>SQL Console</span>
                </NavLink>
            </nav>
            <div className="sidebar-footer">
                <div className="db-size">{dbSizeLabel}</div>
                v2.0 &middot; React UI
            </div>
        </aside>
    );
}
