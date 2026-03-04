import { Outlet, NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { api } from '../../api';

export default function MobileShell() {
    const [llmOk, setLlmOk] = useState<boolean | null>(null);
    const [runnerStatus, setRunnerStatus] = useState('');

    useEffect(() => {
        const poll = () => {
            api.getLlmStatus().then(d => setLlmOk(d.available ?? d.enabled ?? false)).catch(() => setLlmOk(false));
            api.getTailoringRunnerStatus().then(d => {
                setRunnerStatus(d.running ? `Running job #${d.job_id}` : '');
            }).catch(() => {});
        };
        poll();
        const id = setInterval(poll, 5000);
        return () => clearInterval(id);
    }, []);

    const shell: React.CSSProperties = {
        display: 'flex', flexDirection: 'column', height: '100dvh', width: '100vw',
        background: 'var(--bg)', color: 'var(--text)', overflow: 'hidden',
    };

    const topBar: React.CSSProperties = {
        display: 'flex', alignItems: 'center', gap: '10px',
        padding: '8px 16px', paddingTop: 'max(8px, env(safe-area-inset-top))',
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        flexShrink: 0, minHeight: '44px',
    };

    const content: React.CSSProperties = {
        flex: 1, overflow: 'auto', WebkitOverflowScrolling: 'touch' as any,
    };

    const tabBar: React.CSSProperties = {
        display: 'flex', background: 'var(--surface)', borderTop: '1px solid var(--border)',
        paddingBottom: 'max(8px, env(safe-area-inset-bottom))', flexShrink: 0,
    };

    const tabStyle = (isActive: boolean): React.CSSProperties => ({
        flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', padding: '8px 0 4px', gap: '2px',
        fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
        textTransform: 'uppercase', letterSpacing: '.06em', textDecoration: 'none',
        color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
        borderTop: isActive ? '2px solid var(--accent)' : '2px solid transparent',
    });

    return (
        <div style={shell}>
            <div style={topBar}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '.85rem', letterSpacing: '.1em' }}>OPS</span>
                <span style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: llmOk === null ? 'var(--text-secondary)' : llmOk ? 'var(--green)' : 'var(--red)',
                }} />
                {runnerStatus && (
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--amber)' }}>
                        {runnerStatus}
                    </span>
                )}
            </div>

            <div style={content}>
                <Outlet />
            </div>

            <div style={tabBar}>
                <NavLink to="/m/ingest" style={({ isActive }) => tabStyle(isActive)}>
                    <span style={{ fontSize: '1.1rem' }}>+</span>
                    <span>Ingest</span>
                </NavLink>
                <NavLink to="/m/jobs" style={({ isActive }) => tabStyle(isActive)}>
                    <span style={{ fontSize: '1.1rem' }}>&#9881;</span>
                    <span>Jobs</span>
                </NavLink>
                <NavLink to="/m/docs" style={({ isActive }) => tabStyle(isActive)}>
                    <span style={{ fontSize: '1.1rem' }}>&#9776;</span>
                    <span>Docs</span>
                </NavLink>
            </div>
        </div>
    );
}
