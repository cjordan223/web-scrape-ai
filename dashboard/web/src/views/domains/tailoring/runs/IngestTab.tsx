import { useState } from 'react';
import { api } from '../../../../api';

interface Props {
    onSentToQa: () => void;
}

const EMPTY_FIELDS = {
    title: '', company: '', url: '', seniority: '', snippet: '',
    salary_k: '', experience_years: '', jd_text: '',
};

export default function IngestTab({ onSentToQa }: Props) {
    const [rawJd, setRawJd] = useState('');
    const [fields, setFields] = useState({ ...EMPTY_FIELDS });
    const [parsing, setParsing] = useState(false);
    const [parseError, setParseError] = useState('');
    const [parseWarning, setParseWarning] = useState('');
    const [committing, setCommitting] = useState(false);
    const [commitResult, setCommitResult] = useState<{ job_id: number; url: string } | null>(null);
    const [commitError, setCommitError] = useState('');

    const handleParse = async () => {
        if (!rawJd.trim()) return;
        setParsing(true);
        setParseError('');
        setParseWarning('');
        setCommitResult(null);
        setCommitError('');
        try {
            const res = await api.ingestParse(rawJd);
            if (!res.ok) { setParseError(res.error || 'Parse failed'); return; }
            if (res.warning) setParseWarning(res.warning);
            const f = res.fields || {};
            setFields({
                title: f.title || '',
                company: f.company || '',
                url: f.url || '',
                seniority: f.seniority || '',
                snippet: f.snippet || '',
                salary_k: f.salary_k != null ? String(f.salary_k) : '',
                experience_years: f.experience_years != null ? String(f.experience_years) : '',
                jd_text: rawJd,
            });
        } catch (e: any) {
            setParseError(e?.response?.data?.error || 'Parse request failed');
        } finally {
            setParsing(false);
        }
    };

    const handleCommit = async () => {
        if (!fields.title.trim()) { setCommitError('Title is required'); return; }
        setCommitting(true);
        setCommitError('');
        try {
            const payload: Record<string, any> = { ...fields };
            if (payload.salary_k === '') payload.salary_k = null;
            else payload.salary_k = Number(payload.salary_k);
            if (payload.experience_years === '') payload.experience_years = null;
            else payload.experience_years = Number(payload.experience_years);
            const res = await api.ingestCommit(payload);
            if (!res.ok) { setCommitError(res.error || 'Commit failed'); return; }
            setCommitResult({ job_id: res.job_id, url: res.url });
        } catch (e: any) {
            setCommitError(e?.response?.data?.error || 'Commit request failed');
        } finally {
            setCommitting(false);
        }
    };

    const handleReset = () => {
        setRawJd('');
        setFields({ ...EMPTY_FIELDS });
        setParseError('');
        setParseWarning('');
        setCommitResult(null);
        setCommitError('');
    };

    const fieldStyle: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.78rem',
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: '2px', padding: '4px 8px', color: 'var(--text)',
        width: '100%', boxSizing: 'border-box',
    };

    const labelStyle: React.CSSProperties = {
        fontFamily: 'var(--font-mono)', fontSize: '.65rem', fontWeight: 600,
        color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
        marginBottom: '2px',
    };

    return (
        <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
            {/* Left: raw JD input */}
            <div style={{
                width: '45%', padding: '12px 16px', display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border)', overflow: 'hidden',
            }}>
                <div style={labelStyle}>Raw Job Description</div>
                <textarea
                    value={rawJd}
                    onChange={e => setRawJd(e.target.value)}
                    placeholder="Paste full job description text here..."
                    style={{
                        ...fieldStyle, flex: 1, resize: 'none', marginBottom: '8px',
                    }}
                />
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                        className="btn btn-primary btn-sm"
                        onClick={handleParse}
                        disabled={parsing || !rawJd.trim()}
                    >
                        {parsing ? 'Parsing...' : 'Parse with LLM'}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={handleReset}>Reset</button>
                    {parseError && <span style={{ fontSize: '.72rem', color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>{parseError}</span>}
                    {parseWarning && <span style={{ fontSize: '.72rem', color: 'var(--amber, #e0a030)', fontFamily: 'var(--font-mono)' }}>{parseWarning}</span>}
                </div>
            </div>

            {/* Right: editable fields + commit */}
            <div style={{
                flex: 1, padding: '12px 16px', overflow: 'auto',
                display: 'flex', flexDirection: 'column', gap: '8px',
            }}>
                <div style={labelStyle}>Extracted Fields (editable)</div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                    <div>
                        <div style={labelStyle}>Title *</div>
                        <input style={fieldStyle} value={fields.title}
                            onChange={e => setFields(f => ({ ...f, title: e.target.value }))} />
                    </div>
                    <div>
                        <div style={labelStyle}>Company</div>
                        <input style={fieldStyle} value={fields.company}
                            onChange={e => setFields(f => ({ ...f, company: e.target.value }))} />
                    </div>
                    <div>
                        <div style={labelStyle}>URL</div>
                        <input style={fieldStyle} value={fields.url} placeholder="auto-generated if blank"
                            onChange={e => setFields(f => ({ ...f, url: e.target.value }))} />
                    </div>
                    <div>
                        <div style={labelStyle}>Seniority</div>
                        <select style={fieldStyle} value={fields.seniority}
                            onChange={e => setFields(f => ({ ...f, seniority: e.target.value }))}>
                            <option value="">—</option>
                            {['junior', 'mid', 'senior', 'lead', 'staff', 'principal'].map(s =>
                                <option key={s} value={s}>{s}</option>
                            )}
                        </select>
                    </div>
                    <div>
                        <div style={labelStyle}>Salary (k)</div>
                        <input style={fieldStyle} type="number" value={fields.salary_k}
                            onChange={e => setFields(f => ({ ...f, salary_k: e.target.value }))} />
                    </div>
                    <div>
                        <div style={labelStyle}>Experience (yrs)</div>
                        <input style={fieldStyle} type="number" value={fields.experience_years}
                            onChange={e => setFields(f => ({ ...f, experience_years: e.target.value }))} />
                    </div>
                </div>

                <div>
                    <div style={labelStyle}>Snippet</div>
                    <textarea style={{ ...fieldStyle, height: '50px', resize: 'vertical' }} value={fields.snippet}
                        onChange={e => setFields(f => ({ ...f, snippet: e.target.value }))} />
                </div>

                <div style={{ flex: 1, minHeight: '80px', display: 'flex', flexDirection: 'column' }}>
                    <div style={labelStyle}>JD Text</div>
                    <textarea style={{ ...fieldStyle, flex: 1, resize: 'vertical', minHeight: '60px' }}
                        value={fields.jd_text}
                        onChange={e => setFields(f => ({ ...f, jd_text: e.target.value }))} />
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    {!commitResult ? (
                        <button
                            className="btn btn-primary btn-sm"
                            onClick={handleCommit}
                            disabled={committing || !fields.title.trim()}
                        >
                            {committing ? 'Committing...' : 'Commit to DB'}
                        </button>
                    ) : (
                        <>
                            <span style={{
                                fontFamily: 'var(--font-mono)', fontSize: '.75rem', color: 'var(--green)',
                            }}>
                                Sent to QA — Job #{commitResult.job_id}
                            </span>
                            <button
                                className="btn btn-primary btn-sm"
                                onClick={onSentToQa}
                            >
                                Open QA
                            </button>
                            <button className="btn btn-ghost btn-sm" onClick={handleReset}>Ingest Another</button>
                        </>
                    )}
                    {commitError && <span style={{ fontSize: '.72rem', color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>{commitError}</span>}
                </div>
            </div>
        </div>
    );
}
