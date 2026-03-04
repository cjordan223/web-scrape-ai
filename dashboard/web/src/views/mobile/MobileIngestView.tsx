import { useState } from 'react';
import { api } from '../../api';

const EMPTY_FIELDS = {
    title: '', company: '', url: '', seniority: '', snippet: '',
    salary_k: '', experience_years: '', jd_text: '',
};

type Mode = 'input' | 'fields' | 'done';

export default function MobileIngestView() {
    const [mode, setMode] = useState<Mode>('input');
    const [urlInput, setUrlInput] = useState('');
    const [fields, setFields] = useState({ ...EMPTY_FIELDS });
    const [busy, setBusy] = useState(false);
    const [busyLabel, setBusyLabel] = useState('');
    const [error, setError] = useState('');
    const [commitResult, setCommitResult] = useState<{ job_id: number } | null>(null);
    const [queueBusy, setQueueBusy] = useState(false);

    const resetAll = () => {
        setMode('input'); setUrlInput('');
        setFields({ ...EMPTY_FIELDS }); setBusy(false); setBusyLabel(''); setError('');
        setCommitResult(null); setQueueBusy(false);
    };

    const handleFetchAndParse = async () => {
        const url = urlInput.trim();
        if (!url) return;
        setBusy(true); setError(''); setBusyLabel('Fetching…');
        try {
            const fetchRes = await api.ingestFetchUrl(url);
            if (!fetchRes.ok) { setError(fetchRes.error || 'Fetch failed'); return; }

            setBusyLabel('Parsing…');
            const parseRes = await api.ingestParse(fetchRes.text);
            if (!parseRes.ok) { setError(parseRes.error || 'Parse failed'); return; }

            const f = parseRes.fields || {};
            setFields({
                title: f.title || '', company: f.company || '',
                url: f.url || url,
                seniority: f.seniority || '', snippet: f.snippet || '',
                salary_k: f.salary_k != null ? String(f.salary_k) : '',
                experience_years: f.experience_years != null ? String(f.experience_years) : '',
                jd_text: fetchRes.text,
            });
            setMode('fields');
        } catch (e: any) {
            setError(e?.response?.data?.error || e?.message || 'Failed');
        } finally { setBusy(false); setBusyLabel(''); }
    };

    const handleCommit = async () => {
        if (!fields.title.trim()) { setError('Title is required'); return; }
        setBusy(true); setError('');
        try {
            const payload: Record<string, any> = { ...fields };
            payload.salary_k = payload.salary_k === '' ? null : Number(payload.salary_k);
            payload.experience_years = payload.experience_years === '' ? null : Number(payload.experience_years);
            const res = await api.ingestCommit(payload);
            if (!res.ok) { setError(res.error || 'Commit failed'); return; }
            setCommitResult({ job_id: res.job_id });
        } catch (e: any) {
            setError(e?.response?.data?.error || e?.message || 'Commit failed');
        } finally { setBusy(false); }
    };

    const handleQueue = async () => {
        if (!commitResult) return;
        setQueueBusy(true);
        try {
            await api.queueTailoring([{ job_id: commitResult.job_id }]);
            setMode('done');
        } catch (e: any) {
            alert(e?.response?.data?.error || 'Queue failed');
        } finally { setQueueBusy(false); }
    };

    // -- styles --
    const wrap: React.CSSProperties = { padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '12px' };
    const label: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.65rem', fontWeight: 600,
        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
    };
    const input: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.85rem',
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: '4px', padding: '10px 12px', color: 'var(--text)',
        width: '100%', boxSizing: 'border-box',
    };
    const btn: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.8rem', fontWeight: 600,
        padding: '12px', borderRadius: '4px', border: 'none', cursor: 'pointer',
        width: '100%', minHeight: '44px',
    };
    const primaryBtn: React.CSSProperties = { ...btn, background: 'var(--accent)', color: '#fff' };
    const ghostBtn: React.CSSProperties = { ...btn, background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border)' };
    const errStyle: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--red)' };

    // -- done --
    if (mode === 'done') {
        return (
            <div style={{ ...wrap, alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
                <div style={{ fontSize: '2rem' }}>&#10003;</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.85rem', color: 'var(--green)' }}>
                    Job #{commitResult?.job_id} queued for tailoring
                </div>
                <button style={ghostBtn} onClick={resetAll}>Ingest Another</button>
            </div>
        );
    }

    // -- input: just a URL --
    if (mode === 'input') {
        return (
            <div style={wrap}>
                <div style={label}>Paste Job URL</div>
                <input
                    style={input}
                    value={urlInput}
                    onChange={e => setUrlInput(e.target.value)}
                    placeholder="LinkedIn, Greenhouse, Ashby, Indeed…"
                    type="url"
                    autoFocus
                />
                <button
                    style={{ ...primaryBtn, opacity: busy || !urlInput.trim() ? 0.5 : 1 }}
                    onClick={handleFetchAndParse}
                    disabled={busy || !urlInput.trim()}
                >
                    {busy ? busyLabel : 'Fetch & Parse'}
                </button>
                {error && <div style={errStyle}>{error}</div>}
            </div>
        );
    }

    // -- fields + commit/queue --
    return (
        <div style={wrap}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={label}>Edit Fields</div>
                <button style={{ ...ghostBtn, width: 'auto', padding: '6px 12px', minHeight: 'auto', fontSize: '.7rem' }}
                    onClick={resetAll}>Reset</button>
            </div>

            <div><div style={label}>Title *</div>
                <input style={input} value={fields.title} onChange={e => setFields(f => ({ ...f, title: e.target.value }))} /></div>

            <div><div style={label}>Company</div>
                <input style={input} value={fields.company} onChange={e => setFields(f => ({ ...f, company: e.target.value }))} /></div>

            <div><div style={label}>URL</div>
                <input style={input} value={fields.url}
                    onChange={e => setFields(f => ({ ...f, url: e.target.value }))} /></div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                <div><div style={label}>Seniority</div>
                    <select style={input} value={fields.seniority}
                        onChange={e => setFields(f => ({ ...f, seniority: e.target.value }))}>
                        <option value="">—</option>
                        {['junior', 'mid', 'senior', 'lead', 'staff', 'principal'].map(s =>
                            <option key={s} value={s}>{s}</option>)}
                    </select></div>
                <div><div style={label}>Salary (k)</div>
                    <input style={input} type="number" value={fields.salary_k}
                        onChange={e => setFields(f => ({ ...f, salary_k: e.target.value }))} /></div>
                <div><div style={label}>Exp (yrs)</div>
                    <input style={input} type="number" value={fields.experience_years}
                        onChange={e => setFields(f => ({ ...f, experience_years: e.target.value }))} /></div>
            </div>

            <div><div style={label}>Snippet</div>
                <textarea style={{ ...input, height: '60px', resize: 'vertical' }} value={fields.snippet}
                    onChange={e => setFields(f => ({ ...f, snippet: e.target.value }))} /></div>

            <div><div style={label}>JD Text</div>
                <textarea style={{ ...input, height: '120px', resize: 'vertical' }} value={fields.jd_text}
                    onChange={e => setFields(f => ({ ...f, jd_text: e.target.value }))} /></div>

            {error && <div style={errStyle}>{error}</div>}

            {!commitResult ? (
                <button style={{ ...primaryBtn, opacity: busy || !fields.title.trim() ? 0.5 : 1 }}
                    onClick={handleCommit} disabled={busy || !fields.title.trim()}>
                    {busy ? 'Committing…' : 'Commit to DB'}
                </button>
            ) : (
                <>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.78rem', color: 'var(--green)', textAlign: 'center' }}>
                        Committed — Job #{commitResult.job_id}
                    </div>
                    <button style={{ ...primaryBtn, background: 'var(--green)' }}
                        onClick={handleQueue} disabled={queueBusy}>
                        {queueBusy ? 'Queuing…' : 'Queue for Tailoring'}
                    </button>
                </>
            )}
        </div>
    );
}
