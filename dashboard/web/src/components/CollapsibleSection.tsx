import { useState } from 'react';

export function CollapsibleSection({ title, defaultOpen, children }: { title: string; defaultOpen: boolean; children: React.ReactNode }) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div style={{ marginBottom: '24px' }}>
            <div
                style={{
                    display: 'flex', alignItems: 'center', gap: '8px', marginBottom: open ? '12px' : 0,
                    paddingBottom: '6px', borderBottom: '1px solid var(--border)', cursor: 'pointer',
                }}
                onClick={() => setOpen(!open)}
            >
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.66rem', fontWeight: 600,
                    color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
                    transition: 'transform .15s', display: 'inline-block',
                    transform: open ? 'rotate(90deg)' : 'rotate(0)',
                }}>
                    ▸
                </span>
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '.7rem', fontWeight: 600,
                    color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
                }}>
                    {title}
                </span>
            </div>
            {open && children}
        </div>
    );
}
