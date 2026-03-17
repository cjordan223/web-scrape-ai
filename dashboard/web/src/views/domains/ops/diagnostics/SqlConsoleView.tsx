import { useEffect, useState } from 'react';
import { api } from '../../../../api';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { Trash2, AlertTriangle, FolderX, FileX, Database, RefreshCw } from 'lucide-react';

interface ActionDef {
    action: string;
    label: string;
    desc: string;
    icon: React.ReactNode;
    danger?: boolean;
}

const SECTIONS: { title: string; subtitle: string; actions: ActionDef[] }[] = [
    {
        title: 'Scraping Pipeline',
        subtitle: 'jobs.db — scraping tables',
        actions: [
            {
                action: 'clear_scrape_runs',
                label: 'Clear Run History',
                desc: 'Delete all scraping run records. Does not delete jobs.',
                icon: <Database size={16} />,
            },
            {
                action: 'clear_jobs',
                label: 'Clear Parsed Jobs',
                desc: 'Delete all results/jobs. Repopulated on next scrape.',
                icon: <Trash2 size={16} />,
            },
            {
                action: 'clear_rejected',
                label: 'Clear Rejections',
                desc: 'Delete all rejected job records.',
                icon: <Trash2 size={16} />,
            },
            {
                action: 'clear_seen_urls',
                label: 'Clear URL Cache',
                desc: 'Delete dedup seen_urls. All URLs will re-process on next scrape.',
                icon: <Trash2 size={16} />,
                danger: true,
            },
            {
                action: 'clear_scraping_all',
                label: 'Clear All Scraping Data',
                desc: 'Wipes runs, results, rejected, and seen_urls.',
                icon: <AlertTriangle size={16} />,
                danger: true,
            },
        ],
    },
    {
        title: 'Tailoring Pipeline',
        subtitle: 'tailoring/output — filesystem',
        actions: [
            {
                action: 'clear_tailoring_logs',
                label: 'Clear Runner Logs',
                desc: 'Delete log files from tailoring/output/_runner_logs/.',
                icon: <FileX size={16} />,
            },
            {
                action: 'clear_tailoring_failed',
                label: 'Purge Failed Runs',
                desc: 'Delete output directories for runs with failed/error/unknown status.',
                icon: <FolderX size={16} />,
                danger: true,
            },
            {
                action: 'clear_tailoring_partial',
                label: 'Purge Partial Runs',
                desc: 'Delete output directories for runs with partial status.',
                icon: <FolderX size={16} />,
                danger: true,
            },
            {
                action: 'clear_tailoring_succeeded',
                label: 'Purge Succeeded Runs',
                desc: 'Delete output directories for runs with complete/succeeded status.',
                icon: <FolderX size={16} />,
                danger: true,
            },
            {
                action: 'clear_tailoring_runs',
                label: 'Purge All Runs',
                desc: 'Delete every tailoring output directory and clear tailoring-only manual/mobile ingest jobs. Irreversible.',
                icon: <AlertTriangle size={16} />,
                danger: true,
            },
        ],
    },
];

function ActionCard({ def, busy, onRun, disabled }: {
    def: ActionDef;
    busy: boolean;
    onRun: () => void;
    disabled: boolean;
}) {
    const [confirming, setConfirming] = useState(false);

    const handleClick = () => {
        if (def.danger && !confirming) {
            setConfirming(true);
            return;
        }
        setConfirming(false);
        onRun();
    };

    return (
        <div style={{
            background: 'var(--surface)', border: `1px solid ${def.danger ? 'var(--border-bright)' : 'var(--border)'}`,
            borderRadius: 'var(--radius)', padding: '14px 16px',
            display: 'flex', alignItems: 'center', gap: '14px',
            opacity: disabled ? 0.45 : 1,
        }}>
            <div style={{ color: def.danger ? 'var(--red)' : 'var(--text-secondary)', flexShrink: 0 }}>
                {def.icon}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 500, fontSize: '.85rem', color: 'var(--text)', marginBottom: '2px' }}>{def.label}</div>
                <div style={{ fontSize: '.75rem', color: 'var(--text-secondary)' }}>{def.desc}</div>
            </div>
            {confirming ? (
                <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                    <button
                        className="btn btn-sm"
                        style={{ background: 'var(--red)', color: '#fff', border: 'none', fontWeight: 600 }}
                        disabled={disabled || busy}
                        onClick={handleClick}
                    >Confirm</button>
                    <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setConfirming(false)}
                    >Cancel</button>
                </div>
            ) : (
                <button
                    className={`btn btn-sm ${def.danger ? '' : 'btn-ghost'}`}
                    style={def.danger ? { background: 'transparent', border: '1px solid var(--red)', color: 'var(--red)' } : {}}
                    disabled={disabled || busy}
                    onClick={handleClick}
                >
                    {busy ? <RefreshCw size={13} className="spin" /> : 'Run'}
                </button>
            )}
        </div>
    );
}

export default function AdminOpsView() {
    const [status, setStatus] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [busyAction, setBusyAction] = useState<string | null>(null);
    const [results, setResults] = useState<Record<string, { ok: boolean; msg: string }>>({});

    const loadStatus = async () => {
        setLoading(true);
        try {
            const data = await api.opsStatus();
            setStatus(data);
        } catch (err: any) {
            setStatus({ error: err.response?.data?.error || err.message });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { loadStatus(); }, []);

    const runAction = async (action: string) => {
        setBusyAction(action);
        setResults(r => ({ ...r, [action]: undefined as any }));
        try {
            const res = await api.opsAction(action);
            const msg = res.removed !== undefined
                ? `Removed ${Array.isArray(res.removed) ? res.removed.length : res.removed} item(s)`
                : res.affected_tables
                    ? `Cleared: ${res.affected_tables.join(', ')}`
                    : 'Done';
            setResults(r => ({ ...r, [action]: { ok: true, msg } }));
            await loadStatus();
        } catch (err: any) {
            const msg = err.response?.data?.error || err.message || 'Failed';
            setResults(r => ({ ...r, [action]: { ok: false, msg } }));
        } finally {
            setBusyAction(null);
        }
    };

    const disabled = !!busyAction;

    return (
        <PageView>
            <PageHeader title="Admin Operations" subtitle="WORKFLOW MANAGEMENT · DATA CLEANUP" />
            <PagePrimary>

                {/* Status bar */}
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '12px',
                    padding: '10px 16px', marginBottom: '24px',
                    background: 'var(--surface-2)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', fontFamily: 'var(--font-mono)', fontSize: '.8rem',
                }}>
                    {loading ? (
                        <span style={{ color: 'var(--text-secondary)' }}>Loading...</span>
                    ) : status?.error ? (
                        <span style={{ color: 'var(--red)' }}>{status.error}</span>
                    ) : (
                        <>
                            {status?.db_tables && (status.db_tables as { name: string; row_count: number }[]).map(({ name, row_count }) => (
                                <span key={name} style={{ color: 'var(--text-secondary)' }}>{name}: <span style={{ color: 'var(--text)' }}>{row_count}</span></span>
                            ))}
                            {status?.tailoring && (
                                <>
                                    <span style={{ color: 'var(--border-bright)' }}>|</span>
                                    <span style={{ color: 'var(--text-secondary)' }}>
                                        tailoring runs: <span style={{ color: 'var(--text)' }}>{status.tailoring.total_runs}</span>
                                        <span style={{ color: 'var(--text-secondary)' }}> (</span>
                                        <span style={{ color: 'var(--red)' }}>{status.tailoring.failed_runs || 0} failed</span>
                                        <span style={{ color: 'var(--text-secondary)' }}>, </span>
                                        <span style={{ color: 'var(--amber)' }}>{status.tailoring.partial_runs || 0} partial</span>
                                        <span style={{ color: 'var(--text-secondary)' }}>, </span>
                                        <span style={{ color: 'var(--green)' }}>{status.tailoring.succeeded_runs || 0} succeeded</span>
                                        {(status.tailoring.unknown_runs || 0) > 0 && (
                                            <>
                                                <span style={{ color: 'var(--text-secondary)' }}>, </span>
                                                <span style={{ color: 'var(--text-secondary)' }}>{status.tailoring.unknown_runs || 0} unknown</span>
                                            </>
                                        )}
                                        <span style={{ color: 'var(--text-secondary)' }}>)</span>
                                    </span>
                                    <span style={{ color: 'var(--text-secondary)' }}>
                                        logs: <span style={{ color: 'var(--text)' }}>{status.tailoring.log_files}</span>
                                    </span>
                                </>
                            )}
                            <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto', fontSize: '.72rem' }} onClick={loadStatus}>
                                <RefreshCw size={12} />
                            </button>
                        </>
                    )}
                </div>

                {/* Workflow sections */}
                {SECTIONS.map(section => (
                    <div key={section.title} style={{ marginBottom: '28px' }}>
                        <div style={{ marginBottom: '12px' }}>
                            <span style={{ fontWeight: 600, fontSize: '.9rem', color: 'var(--text)' }}>{section.title}</span>
                            <span style={{ marginLeft: '8px', fontSize: '.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{section.subtitle}</span>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {section.actions.map(def => (
                                <div key={def.action}>
                                    <ActionCard
                                        def={def}
                                        busy={busyAction === def.action}
                                        disabled={disabled}
                                        onRun={() => runAction(def.action)}
                                    />
                                    {results[def.action] && (
                                        <div style={{
                                            padding: '4px 10px', marginTop: '4px',
                                            fontSize: '.75rem', fontFamily: 'var(--font-mono)',
                                            color: results[def.action].ok ? 'var(--green)' : 'var(--red)',
                                        }}>
                                            {results[def.action].ok ? '✓' : '✗'} {results[def.action].msg}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}

                {/* Nuclear */}
                <div style={{ marginTop: '8px', padding: '16px', background: 'var(--surface)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', opacity: disabled ? 0.45 : 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                        <AlertTriangle size={16} style={{ color: 'var(--red)', flexShrink: 0 }} />
                        <span style={{ fontWeight: 600, fontSize: '.9rem', color: 'var(--red)' }}>Nuke Everything</span>
                        <span style={{ fontSize: '.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>all DB tables + all tailoring output</span>
                    </div>
                    <NukeButton disabled={disabled} busy={busyAction === 'nuke_all'} onRun={() => runAction('nuke_all')} />
                    {results['nuke_all'] && (
                        <div style={{ marginTop: '6px', fontSize: '.75rem', fontFamily: 'var(--font-mono)', color: results['nuke_all'].ok ? 'var(--green)' : 'var(--red)' }}>
                            {results['nuke_all'].ok ? '✓' : '✗'} {results['nuke_all'].msg}
                        </div>
                    )}
                </div>

            </PagePrimary>
        </PageView>
    );
}

function NukeButton({ disabled, busy, onRun }: { disabled: boolean; busy: boolean; onRun: () => void }) {
    const [step, setStep] = useState(0);
    return (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {step === 0 && (
                <button className="btn btn-sm" style={{ border: '1px solid var(--red)', color: 'var(--red)', background: 'transparent' }}
                    disabled={disabled} onClick={() => setStep(1)}>
                    Delete All Data
                </button>
            )}
            {step === 1 && (
                <>
                    <span style={{ fontSize: '.78rem', color: 'var(--text-secondary)' }}>Are you sure?</span>
                    <button className="btn btn-sm" style={{ background: 'var(--red)', color: '#fff', border: 'none', fontWeight: 700 }}
                        disabled={disabled || busy}
                        onClick={() => { setStep(0); onRun(); }}>
                        {busy ? <RefreshCw size={13} className="spin" /> : 'Yes, nuke it'}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setStep(0)}>Cancel</button>
                </>
            )}
        </div>
    );
}
