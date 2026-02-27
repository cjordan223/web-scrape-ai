interface Verdict {
    stage: string;
    passed: boolean;
    reason: string;
    [key: string]: any;
}

interface VerdictChipsProps {
    verdicts: Verdict[];
}

export default function VerdictChips({ verdicts }: VerdictChipsProps) {
    return (
        <div className="verdicts-grid">
            {verdicts.map((v, idx) => (
                <div key={idx} className={`verdict-chip ${v.stage === 'llm_review' ? 'llm' : (v.passed ? 'pass' : 'fail')}`}>
                    <div className={`verdict-dot ${v.stage === 'llm_review' ? 'llm' : (v.passed ? 'pass' : 'fail')}`}>
                        {v.stage === 'llm_review' ? '🧠' : (v.passed ? '✓' : '✗')}
                    </div>
                    <div>
                        <div className="verdict-stage" style={v.stage === 'llm_review' ? { color: 'var(--purple)' } : (!v.passed ? { color: 'var(--red)' } : {})}>
                            {v.stage === 'llm_review' ? 'AI Review' : v.stage}
                        </div>
                        <div className="verdict-reason">{v.reason}</div>
                    </div>
                </div>
            ))}
        </div>
    );
}
