import { useEffect, useState } from 'react';
import { api } from '../../../../api';
import { PageHeader, PagePrimary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { Trash2, AlertTriangle, ShieldCheck, ServerCrash } from 'lucide-react';

export default function AdminOpsView() {
    const [adminStatus, setAdminStatus] = useState<any>(null);
    const [adminLoading, setAdminLoading] = useState(true);
    const [adminError, setAdminError] = useState('');
    const [adminBusy, setAdminBusy] = useState(false);
    const [adminNotice, setAdminNotice] = useState('');
    const [confirmText, setConfirmText] = useState('');

    const loadAdminStatus = async () => {
        setAdminLoading(true);
        setAdminError('');
        try {
            const data = await api.dbAdminStatus();
            setAdminStatus(data);
        } catch (err: any) {
            setAdminError(err.response?.data?.error || err.message || 'Failed to load DB admin status');
        } finally {
            setAdminLoading(false);
        }
    };

    useEffect(() => {
        loadAdminStatus();
    }, []);

    const runAdminAction = async (action: string, tables: string[]) => {
        if (!adminStatus?.enabled) return;

        setAdminNotice('');
        setAdminError('');
        setAdminBusy(true);
        try {
            const res = await api.dbAdminAction(action, tables, confirmText);
            if (res.error) {
                setAdminError(res.error);
            } else {
                const affected = (res.affected_tables || []).length;
                setAdminNotice(`Completed action. Affected tables: ${affected}`);
                setConfirmText(''); // require re-entry for safety
                await loadAdminStatus();
            }
        } catch (err: any) {
            setAdminError(err.response?.data?.error || err.message || 'Failed to execute admin action');
        } finally {
            setAdminBusy(false);
        }
    };

    const isUnlocked = confirmText === adminStatus?.confirm_phrase;

    return (
        <PageView>
            <PageHeader title="Admin Operations" subtitle="DANGEROUS OPERATIONS · DATA DELETION" />
            <PagePrimary>

                <WorkflowPanel
                    title={
                        <span style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, fontSize: '.95rem', color: adminStatus?.enabled ? 'var(--text)' : '#dc2626' }}>
                            <ShieldCheck size={18} />
                            Admin Authorization
                        </span>
                    }
                    headerStyle={{ padding: '16px 20px', backgroundColor: adminStatus?.enabled ? 'var(--surface-2)' : '#fef2f2' }}
                    style={{ marginBottom: '24px', borderColor: adminStatus?.enabled ? 'var(--border)' : '#fecaca' }}
                >
                    <div style={{ padding: '20px' }}>
                        {adminLoading ? (
                            <div style={{ color: 'var(--text-secondary)' }}>Checking authorization...</div>
                        ) : (
                            <>
                                {!adminStatus?.enabled ? (
                                    <div style={{ color: '#b45309', display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                                        <AlertTriangle size={24} style={{ flexShrink: 0, marginTop: '2px' }} />
                                        <div>
                                            <div style={{ fontWeight: 600, marginBottom: '6px', fontSize: '1.05rem' }}>Admin Operations Disabled</div>
                                            <div>Set <code>DASHBOARD_ENABLE_DB_ADMIN=1</code> in your backend environment to enable destructive operations.</div>
                                        </div>
                                    </div>
                                ) : (
                                    <div style={{ maxWidth: '400px' }}>
                                        <div style={{ fontSize: '.85rem', color: 'var(--text)', marginBottom: '10px' }}>
                                            Type <strong>{adminStatus?.confirm_phrase}</strong> below to unlock destructive actions.
                                        </div>
                                        <input
                                            type="text"
                                            value={confirmText}
                                            onChange={(e) => setConfirmText(e.target.value)}
                                            placeholder={adminStatus?.confirm_phrase}
                                            style={{
                                                width: '100%',
                                                padding: '10px 14px',
                                                fontSize: '.95rem',
                                                fontFamily: 'var(--font-mono)',
                                                border: isUnlocked ? '1px solid var(--green)' : '1px solid var(--border-bright)',
                                                borderRadius: 'var(--radius)',
                                                backgroundColor: 'var(--surface-3)',
                                                color: 'var(--text)',
                                                outline: 'none',
                                                transition: 'border-color 0.2s',
                                                boxShadow: isUnlocked ? '0 0 0 1px var(--green)' : 'none'
                                            }}
                                        />
                                        {isUnlocked && <div style={{ marginTop: '8px', color: 'var(--green)', fontSize: '.8rem', display: 'flex', alignItems: 'center', gap: '4px' }}><ShieldCheck size={14} /> Actions unlocked</div>}
                                    </div>
                                )}
                            </>
                        )}

                        {adminError && <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '4px', color: '#dc2626', fontSize: '.85rem' }}>{adminError}</div>}
                        {!adminError && adminNotice && <div style={{ marginTop: '16px', padding: '12px', background: 'rgba(60,179,113,.1)', border: '1px solid rgba(60,179,113,.3)', borderRadius: '4px', color: 'var(--green)', fontSize: '.85rem' }}>{adminNotice}</div>}
                    </div>
                </WorkflowPanel>

                <div style={{ opacity: (!adminStatus?.enabled || !isUnlocked || adminBusy) ? 0.5 : 1, pointerEvents: (!adminStatus?.enabled || !isUnlocked || adminBusy) ? 'none' : 'auto', transition: 'opacity 0.2s' }}>
                    <h3 style={{ fontSize: '1.05rem', fontWeight: 500, marginBottom: '16px', color: 'var(--text)' }}>Quick Actions</h3>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>

                        {/* Clear Scrapes */}
                        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '20px', display: 'flex', flexDirection: 'column' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                                <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(75, 142, 240, 0.1)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <ServerCrash size={20} />
                                </div>
                                <div>
                                    <div style={{ fontWeight: 600, fontSize: '.95rem', color: 'var(--text)' }}>Clear Scrapes</div>
                                    <div style={{ fontSize: '.75rem', color: 'var(--text-secondary)' }}>Truncate runs table</div>
                                </div>
                            </div>
                            <div style={{ fontSize: '.85rem', color: 'var(--text-secondary)', marginBottom: '20px', flex: 1 }}>
                                Deletes all scraping run histories and execution logs. Does not delete actual scraped jobs.
                            </div>
                            <button className="btn" style={{ width: '100%', background: 'var(--surface-3)', border: '1px solid var(--border-bright)', color: 'var(--text)' }} onClick={() => runAdminAction('truncate_tables', ['runs'])}>
                                Delete Scrape Logs
                            </button>
                        </div>

                        {/* Clear Jobs */}
                        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '20px', display: 'flex', flexDirection: 'column' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                                <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(60, 179, 113, 0.1)', color: 'var(--green)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <Trash2 size={20} />
                                </div>
                                <div>
                                    <div style={{ fontWeight: 600, fontSize: '.95rem', color: 'var(--text)' }}>Clear Parsed Jobs</div>
                                    <div style={{ fontSize: '.75rem', color: 'var(--text-secondary)' }}>Truncate results table</div>
                                </div>
                            </div>
                            <div style={{ fontSize: '.85rem', color: 'var(--text-secondary)', marginBottom: '20px', flex: 1 }}>
                                Deletes all successfully parsed jobs and pending approvals. Will be repopulated on next scrape.
                            </div>
                            <button className="btn" style={{ width: '100%', background: 'var(--surface-3)', border: '1px solid var(--border-bright)', color: 'var(--text)' }} onClick={() => runAdminAction('truncate_tables', ['results'])}>
                                Delete Jobs
                            </button>
                        </div>

                        {/* Clear Rejections */}
                        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '20px', display: 'flex', flexDirection: 'column' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                                <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(217, 79, 79, 0.1)', color: 'var(--red)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <Trash2 size={20} />
                                </div>
                                <div>
                                    <div style={{ fontWeight: 600, fontSize: '.95rem', color: 'var(--text)' }}>Clear Rejections</div>
                                    <div style={{ fontSize: '.75rem', color: 'var(--text-secondary)' }}>Truncate rejected table</div>
                                </div>
                            </div>
                            <div style={{ fontSize: '.85rem', color: 'var(--text-secondary)', marginBottom: '20px', flex: 1 }}>
                                Deletes all records of rejected jobs. Note: Dedup functions might re-process these if scraped again.
                            </div>
                            <button className="btn" style={{ width: '100%', background: 'var(--surface-3)', border: '1px solid var(--border-bright)', color: 'var(--text)' }} onClick={() => runAdminAction('truncate_tables', ['rejected'])}>
                                Delete Rejections
                            </button>
                        </div>

                    </div>

                    <div style={{ marginTop: '24px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius)', padding: '20px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                            <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(220, 38, 38, 0.1)', color: '#dc2626', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                <AlertTriangle size={20} />
                            </div>
                            <div>
                                <div style={{ fontWeight: 600, fontSize: '.95rem', color: '#991b1b' }}>Nuke Everything</div>
                                <div style={{ fontSize: '.75rem', color: '#b91c1c' }}>Truncate all tables</div>
                            </div>
                        </div>
                        <div style={{ fontSize: '.85rem', color: '#991b1b', marginBottom: '16px' }}>
                            Warning: This will execute <code>truncate_all</code>, permanently deleting all jobs, scrapes, logs, schedules, and data from every table in the database. This action is irreversible.
                        </div>
                        <button
                            className="btn"
                            style={{ background: '#dc2626', color: '#fff', border: 'none', padding: '8px 16px', fontWeight: 600 }}
                            onClick={() => runAdminAction('truncate_all', [])}
                        >
                            Delete All Data
                        </button>
                    </div>

                </div>
            </PagePrimary>
        </PageView>
    );
}
