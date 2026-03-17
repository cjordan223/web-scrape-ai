import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../../../../api';
import { Send, Trash2 } from 'lucide-react';

type ChatMode = 'edit' | 'application_answer' | 'general';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    mode?: ChatMode;
    docUpdated?: 'resume' | 'cover';
    edits?: { old_preview: string; new_preview: string; applied: boolean; reason?: string; match_mode?: string }[];
}

interface Props {
    slug: string;
    docFocus: 'resume' | 'cover';
    onDocUpdated?: () => void;
}

const APPLICATION_HINTS = [
    'application question',
    'additional information',
    'help me answer',
    'supplemental question',
    'why do you want',
    'why are you interested',
    'tell us about',
    'please share anything else',
    'short answer',
];

const EDIT_HINTS = [
    'edit',
    'rewrite',
    'revise',
    'retailor',
    'tailor',
    'update',
    'change',
    'fix',
    'tighten',
    'shorten',
    'condense',
    'expand',
    'rephrase',
    'add',
    'remove',
    'swap',
    'improve',
];

const DOC_HINTS = [
    'resume',
    'cover letter',
    'cover',
    'summary',
    'bullet',
    'skills',
    'paragraph',
    'letter',
];

function detectDraftMode(message: string, docFocus: 'resume' | 'cover'): ChatMode {
    const lower = message.trim().toLowerCase();
    if (!lower) return 'general';
    if (lower.startsWith('/edit')) return 'edit';
    if (lower.startsWith('/answer') || lower.startsWith('/application')) return 'application_answer';
    if (APPLICATION_HINTS.some((hint) => lower.includes(hint))) return 'application_answer';
    if (EDIT_HINTS.some((hint) => lower.includes(hint)) && (DOC_HINTS.some((hint) => lower.includes(hint)) || !!docFocus)) {
        return 'edit';
    }
    return 'general';
}

function modeLabel(mode: ChatMode) {
    return mode === 'application_answer' ? 'application answer' : mode;
}

function modeTone(mode: ChatMode) {
    if (mode === 'application_answer') {
        return {
            border: '1px solid rgba(60,179,113,.2)',
            color: 'var(--green)',
            background: 'rgba(60,179,113,.08)',
        };
    }
    if (mode === 'edit') {
        return {
            border: '1px solid rgba(75,142,240,.2)',
            color: 'var(--accent)',
            background: 'rgba(75,142,240,.08)',
        };
    }
    return {
        border: '1px solid var(--border)',
        color: 'var(--text-secondary)',
        background: 'var(--surface-3)',
    };
}

function buildStarterPrompts(docFocus: 'resume' | 'cover') {
    return [
        {
            label: 'Answer Question',
            prompt: 'Help me answer this application question:\n\n[Paste the application prompt here]\n\nUse only facts supported by this package.',
        },
        {
            label: 'Retailor Resume',
            prompt: 'Retailor the resume for this role. Tighten the summary and the most relevant bullets to better match the JD.',
        },
        {
            label: 'Tighten Cover',
            prompt: 'Tighten the cover letter for this role. Improve clarity, structure, and specificity without inventing facts.',
        },
        {
            label: 'Explain Fit',
            prompt: 'Why is my background a credible fit for this role? Give me 4 concise bullets I can reuse in applications.',
        },
        {
            label: `Edit ${docFocus === 'resume' ? 'Resume' : 'Cover'}`,
            prompt: `Update the ${docFocus}. Keep the strongest evidence, fix the weakest phrasing, and stay grounded in the current package.`,
        },
    ];
}

export default function PackageChatPanel({ slug, docFocus, onDocUpdated }: Props) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const scrollRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const draftMode = detectDraftMode(input, docFocus);
    const starters = buildStarterPrompts(docFocus);

    const scrollToBottom = useCallback(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        api.packageChatHistory(slug).then(res => {
            if (!cancelled) setMessages(res.messages || []);
        }).catch(() => {});
        return () => { cancelled = true; };
    }, [slug]);

    useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

    const send = async () => {
        const msg = input.trim();
        if (!msg || loading) return;
        setInput('');
        setError('');
        setMessages(prev => [...prev, { role: 'user', content: msg }]);
        setLoading(true);
        try {
            const res = await api.packageChatSend(slug, msg, docFocus);
            if (res.ok) {
                const assistantMsg: Message = { role: 'assistant', content: res.reply, mode: res.mode, docUpdated: res.doc_updated };
                if (res.edits) assistantMsg.edits = res.edits;
                setMessages(prev => [...prev, assistantMsg]);
                if (res.doc_updated && onDocUpdated) {
                    onDocUpdated();
                }
            } else {
                setError(res.error || 'Unknown error');
            }
        } catch (e: any) {
            setError(e.response?.data?.error || e.message || 'Request failed');
        } finally {
            setLoading(false);
            inputRef.current?.focus();
        }
    };

    const clearChat = async () => {
        await api.packageChatClear(slug);
        setMessages([]);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    };

    const fillPrompt = (prompt: string) => {
        setInput(prompt);
        requestAnimationFrame(() => {
            inputRef.current?.focus();
        });
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            {/* Messages */}
            <div ref={scrollRef} style={{
                flex: 1, overflowY: 'auto', padding: '8px 12px',
                display: 'flex', flexDirection: 'column', gap: '8px',
            }}>
                {messages.length === 0 && !loading && (
                    <div style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        padding: '16px', opacity: 0.5,
                    }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)' }}>
                            Ask about fit, draft application answers, or request targeted edits to either document.
                        </span>
                    </div>
                )}
                {messages.map((msg, i) => (
                    <div key={i} style={{
                        alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                        maxWidth: '90%',
                    }}>
                        {msg.role === 'assistant' && (msg.mode || msg.docUpdated) && (
                            <div style={{ display: 'flex', gap: '6px', marginBottom: '4px', flexWrap: 'wrap' }}>
                                {msg.mode && (
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.58rem', letterSpacing: '.05em',
                                        textTransform: 'uppercase', padding: '2px 6px', borderRadius: '999px',
                                        border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface)',
                                    }}>
                                        {msg.mode === 'application_answer' ? 'application answer' : msg.mode}
                                    </span>
                                )}
                                {msg.docUpdated && (
                                    <span style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.58rem', letterSpacing: '.05em',
                                        textTransform: 'uppercase', padding: '2px 6px', borderRadius: '999px',
                                        border: '1px solid rgba(60,179,113,.25)', color: 'var(--green)', background: 'rgba(60,179,113,.08)',
                                    }}>
                                        updated {msg.docUpdated}
                                    </span>
                                )}
                            </div>
                        )}
                        <div style={{
                            padding: '6px 10px', borderRadius: '5px',
                            fontSize: '.74rem', lineHeight: 1.5,
                            background: msg.role === 'user' ? 'var(--accent-light)' : 'var(--surface-3)',
                            border: `1px solid ${msg.role === 'user' ? 'rgba(75,142,240,.2)' : 'var(--border)'}`,
                            color: 'var(--text)',
                            whiteSpace: 'pre-wrap',
                        }}>
                            {renderContent(msg.content)}
                        </div>
                        {msg.edits && msg.edits.length > 0 && (
                            <div style={{ marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                {msg.edits.map((edit, j) => (
                                    <div key={j} style={{
                                        fontFamily: 'var(--font-mono)', fontSize: '.6rem',
                                        padding: '2px 6px', borderRadius: '2px',
                                        background: edit.applied ? 'rgba(60,179,113,.08)' : 'rgba(217,79,79,.08)',
                                        color: edit.applied ? 'var(--green)' : 'var(--red)',
                                        border: `1px solid ${edit.applied ? 'rgba(60,179,113,.15)' : 'rgba(217,79,79,.15)'}`,
                                    }}>
                                        {edit.applied ? 'APPLIED' : 'FAILED'}
                                        {edit.match_mode === 'flex_whitespace' ? ' (flex)' : ''}: {edit.old_preview.slice(0, 50)}...
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
                {loading && (
                    <div style={{ alignSelf: 'flex-start' }}>
                        <div style={{
                            padding: '6px 10px', borderRadius: '5px',
                            background: 'var(--surface-3)', border: '1px solid var(--border)',
                            fontFamily: 'var(--font-mono)', fontSize: '.7rem', color: 'var(--text-secondary)',
                        }}>
                            Waiting for LLM...
                        </div>
                    </div>
                )}
            </div>

            {error && (
                <div style={{
                    padding: '4px 12px', fontSize: '.68rem', color: 'var(--red)',
                    fontFamily: 'var(--font-mono)', background: 'rgba(217,79,79,.06)',
                    borderTop: '1px solid var(--border)', flexShrink: 0,
                }}>
                    {error}
                </div>
            )}

            {/* Input bar */}
            <div style={{
                flexShrink: 0, borderTop: '1px solid var(--border)', background: 'var(--surface)',
                padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: '6px',
            }}>
                <div style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: '8px', flexWrap: 'wrap',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', letterSpacing: '.08em',
                            textTransform: 'uppercase', color: 'var(--text-secondary)',
                        }}>
                            mode preview
                        </span>
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', letterSpacing: '.05em',
                            textTransform: 'uppercase', padding: '2px 6px', borderRadius: '999px',
                            ...modeTone(draftMode),
                        }}>
                            {modeLabel(draftMode)}
                        </span>
                        <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: '.58rem', letterSpacing: '.05em',
                            textTransform: 'uppercase', padding: '2px 6px', borderRadius: '999px',
                            border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-3)',
                        }}>
                            focus {docFocus}
                        </span>
                    </div>
                    <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: '.6rem', color: 'var(--text-secondary)', opacity: 0.85,
                    }}>
                        Name “resume” or “cover” explicitly to edit the other document.
                    </span>
                </div>

                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {starters.map((starter) => (
                        <button
                            key={starter.label}
                            type="button"
                            onClick={() => fillPrompt(starter.prompt)}
                            style={{
                                fontFamily: 'var(--font-mono)', fontSize: '.6rem', fontWeight: 600,
                                padding: '4px 7px', borderRadius: '999px', cursor: 'pointer',
                                background: 'var(--surface-3)', border: '1px solid var(--border)',
                                color: 'var(--text-secondary)',
                            }}
                        >
                            {starter.label}
                        </button>
                    ))}
                </div>

                <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-end' }}>
                <textarea
                    ref={inputRef}
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask a question, request an edit, or draft an application answer..."
                    rows={1}
                    style={{
                        flex: 1, padding: '6px 8px', borderRadius: '3px',
                        fontSize: '.74rem', lineHeight: 1.4, resize: 'none',
                        border: '1px solid var(--border-bright)', background: 'var(--surface-3)',
                        color: 'var(--text)', outline: 'none',
                        minHeight: '32px', maxHeight: '80px',
                    }}
                    onInput={e => {
                        const t = e.currentTarget;
                        t.style.height = 'auto';
                        t.style.height = Math.min(t.scrollHeight, 80) + 'px';
                    }}
                />
                <button
                    onClick={send}
                    disabled={loading || !input.trim()}
                    className="btn btn-primary btn-sm"
                    style={{ display: 'flex', alignItems: 'center', padding: '4px 8px', alignSelf: 'center' }}
                >
                    <Send size={12} />
                </button>
                <button
                    onClick={clearChat}
                    className="btn btn-ghost btn-sm"
                    title="Clear chat history"
                    style={{ alignSelf: 'center', opacity: messages.length ? 1 : 0.3, padding: '4px 6px' }}
                    disabled={!messages.length}
                >
                    <Trash2 size={12} />
                </button>
                </div>
            </div>
        </div>
    );
}

function renderContent(text: string) {
    // Strip <<<EDIT...EDIT>>> blocks from display (they're shown as badges)
    const cleaned = text.replace(/<<<EDIT\s*\nOLD:\s*\n[\s\S]*?\nEDIT>>>/g, '').trim();

    const parts = cleaned.split(/(```[\s\S]*?```)/g);
    return parts.map((part, i) => {
        if (part.startsWith('```') && part.endsWith('```')) {
            const inner = part.slice(3, -3).replace(/^(?:latex|tex)\n/, '');
            return (
                <pre key={i} style={{
                    margin: '4px 0', padding: '6px 8px', borderRadius: '3px',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    fontSize: '.68rem', lineHeight: 1.45, overflowX: 'auto',
                    whiteSpace: 'pre-wrap',
                }}>
                    {inner}
                </pre>
            );
        }
        return <span key={i}>{part}</span>;
    });
}
