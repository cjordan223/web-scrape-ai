import { useState } from 'react';
import { api } from '../../../../api';

interface Props {
    onSentToQa: () => void;
    onSentToReady: () => void;
    onPackageCreated?: (slug: string) => void;
}

type PackageStep = 'idle' | 'submitting' | 'queued' | 'tailoring' | 'opening' | 'error';

const ONE_CLICK_TIMEOUT_MS = 45 * 60 * 1000;
const ONE_CLICK_POLL_MS = 3000;

function sleep(ms: number) {
    return new Promise<void>((r) => setTimeout(r, ms));
}

function runUpdatedAtMs(run: { updated_at?: string | null }): number {
    if (!run?.updated_at) return 0;
    const t = new Date(run.updated_at).getTime();
    return Number.isFinite(t) ? t : 0;
}

export default function IngestTab({ onPackageCreated }: Props) {
    const [rawJd, setRawJd] = useState('');
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState<{ step: PackageStep; label: string; error?: string }>({
        step: 'idle',
        label: '',
    });
    const [submitted, setSubmitted] = useState<any>(null);

    async function waitForPackageSlug(jobId: number): Promise<string> {
        const deadline = Date.now() + ONE_CLICK_TIMEOUT_MS;
        while (Date.now() < deadline) {
            const runs = await api.getTailoring();
            const forJob = (runs || [])
                .filter((r: any) => Number(r?.meta?.job_id) === jobId)
                .sort((a: any, b: any) => runUpdatedAtMs(b) - runUpdatedAtMs(a));
            const latest = forJob[0] as { slug?: string; status?: string } | undefined;
            if (latest?.slug) {
                const status = (latest.status || '').toLowerCase();
                if (status === 'failed') {
                    throw new Error('Tailoring run failed - check Ops > Traces for this job.');
                }
                if (status === 'complete' || status === 'partial') {
                    return String(latest.slug);
                }
            }

            const items = await api.getPackages();
            const pkg = (items || []).find((p: any) => Number(p?.meta?.job_id) === jobId);
            if (pkg?.slug) return String(pkg.slug);

            const runner = await api.getTailoringRunnerStatus().catch(() => null);
            if (runner) {
                const checkItem = (it: { job_id?: number; status?: string; error?: string | null } | null | undefined) => {
                    if (!it || Number(it.job_id) !== jobId) return;
                    const status = (it.status || '').toLowerCase();
                    if (status === 'failed' || status === 'cancelled') {
                        throw new Error(it.error || `Tailoring queue item ${status}`);
                    }
                };
                checkItem(runner.active_item);
                (runner.queue || []).forEach((q: { job_id?: number; status?: string; error?: string | null }) => checkItem(q));
            }

            await sleep(ONE_CLICK_POLL_MS);
        }
        throw new Error('Package generation is still running after 45 minutes. Check Ready or Packages.');
    }

    const handleCreatePackage = async () => {
        if (!onPackageCreated) return;
        const jdText = rawJd.trim();
        if (!jdText) {
            setProgress({ step: 'error', label: '', error: 'Paste a job description first.' });
            return;
        }

        setBusy(true);
        setSubmitted(null);
        setProgress({ step: 'submitting', label: 'Parsing, validating URL, and preparing job...' });
        try {
            const res = await api.ingestPackage(jdText);
            if (!res?.ok) {
                throw new Error(res?.error || 'Failed to start package');
            }

            setSubmitted({
                jobId: res.job_id,
                title: res.fields?.title || 'Untitled',
                company: res.fields?.company || '',
                url: res.url || res.fields?.url || '',
                decision: res.decision,
                queued: res.queued,
            });
            setProgress({ step: 'queued', label: `Queued job #${res.job_id}. Waiting for tailoring...` });

            setProgress({ step: 'tailoring', label: 'Generating application package...' });
            const slug = await waitForPackageSlug(res.job_id);

            setProgress({ step: 'opening', label: 'Opening package...' });
            onPackageCreated(slug);
            setRawJd('');
            setProgress({ step: 'idle', label: '' });
        } catch (e: any) {
            setProgress({
                step: 'error',
                label: '',
                error: e?.response?.data?.error || e?.message || 'Package generation failed',
            });
        } finally {
            setBusy(false);
        }
    };

    const handleReset = () => {
        setRawJd('');
        setSubmitted(null);
        setProgress({ step: 'idle', label: '' });
    };

    const fieldStyle: React.CSSProperties = {
        fontFamily: 'var(--font-mono)',
        fontSize: '.82rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '2px',
        padding: '10px 12px',
        color: 'var(--text)',
        width: '100%',
        boxSizing: 'border-box',
    };

    const labelStyle: React.CSSProperties = {
        fontFamily: 'var(--font-mono)',
        fontSize: '.65rem',
        fontWeight: 600,
        color: 'var(--text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '.08em',
        marginBottom: '6px',
    };

    return (
        <div style={{ height: '100%', overflow: 'auto', padding: '16px 18px', boxSizing: 'border-box' }}>
            <div style={{ maxWidth: '980px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '12px', height: '100%' }}>
                <div>
                    <div style={labelStyle}>Paste Job Description</div>
                    <textarea
                        value={rawJd}
                        onChange={(e) => setRawJd(e.target.value)}
                        placeholder="Paste the full job description, including the application URL..."
                        disabled={busy}
                        style={{
                            ...fieldStyle,
                            minHeight: '420px',
                            height: 'calc(100vh - 250px)',
                            resize: 'vertical',
                            lineHeight: 1.5,
                        }}
                    />
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <button
                        type="button"
                        className="btn btn-success btn-sm"
                        onClick={handleCreatePackage}
                        disabled={busy || !rawJd.trim()}
                        title="Backend parses fields, validates URL, prepares, queues tailoring, and opens the generated package"
                    >
                        {busy ? (progress.label || 'Working...') : 'Create Application Package'}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={handleReset} disabled={busy}>
                        Reset
                    </button>
                    {progress.error && (
                        <span style={{ fontSize: '.72rem', color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>
                            {progress.error}
                        </span>
                    )}
                    {!progress.error && progress.label && (
                        <span style={{ fontSize: '.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                            {progress.label}
                        </span>
                    )}
                </div>

                {submitted && (
                    <div
                        style={{
                            border: '1px solid var(--border)',
                            background: 'rgba(15, 19, 26, 0.72)',
                            borderRadius: '6px',
                            padding: '12px',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '.76rem',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        <div style={{ ...labelStyle, marginBottom: '8px' }}>Submitted Job</div>
                        <div style={{ color: 'var(--text)' }}>
                            #{submitted.jobId} · {submitted.title}
                            {submitted.company ? ` · ${submitted.company}` : ''}
                        </div>
                        <div style={{ marginTop: '4px', overflowWrap: 'anywhere' }}>{submitted.url}</div>
                        <div style={{ marginTop: '4px' }}>
                            Decision: {submitted.decision || 'unknown'} · Queue: {submitted.queued ? 'queued' : 'already in progress'}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
