import { useEffect, useMemo, useRef, useState } from 'react';
import { BriefcaseBusiness, Check, ExternalLink, FileText, Mail, RotateCcw, Send, Skull } from 'lucide-react';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';

type PackageItem = any;

export type PackageGroup = {
    key: string;
    jobId: number | null;
    title: string;
    company: string;
    items: PackageItem[];
};

type Props = {
    groups: PackageGroup[];
    activeIndex: number;
    setActiveIndex: (n: number) => void;
    activeRunBySlug: Record<string, number>;
    setActiveRunBySlug: React.Dispatch<React.SetStateAction<Record<string, number>>>;
    selectedSlugs: Set<string>;
    onToggleSelect: (slug: string) => void;
    onOpen: (slug: string) => void;
    onRequeue: (slug: string) => void;
    onDead: (slug: string) => void;
    bulkBar?: React.ReactNode;
    headerRight?: React.ReactNode;
    eyebrow?: React.ReactNode;
};

type DetailMap = Record<string, any>;

function packageUpdatedAt(item: PackageItem) {
    const raw = item?.updated_at || item?.created_at || 0;
    const ts = new Date(raw).getTime();
    return Number.isFinite(ts) ? ts : 0;
}

function companyKey(group: { company: string }): string {
    return (group.company || '').trim().toLowerCase() || '__unknown__';
}

function companyDisplay(group: { company: string }): string {
    return (group.company || '').trim() || 'Unknown company';
}

function companyInitials(name: string): string {
    const cleaned = (name || '').replace(/[^A-Za-z0-9 ]/g, ' ').trim();
    if (!cleaned) return '--';
    const parts = cleaned.split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
}

function prettyBoard(board?: string) {
    if (!board) return '';
    const map: Record<string, string> = {
        greenhouse: 'Greenhouse',
        lever: 'Lever',
        ashby: 'Ashby',
        searxng: 'SearXNG',
        usajobs: 'USAJobs',
        manual: 'Manual',
    };
    return map[board.toLowerCase()] || board;
}

function statusLabel(item: PackageItem, isLatest: boolean) {
    if (item?.applied) return 'Applied';
    if (item?.decision && item.decision !== 'qa_approved') return 'Returned';
    if (isLatest) return 'Latest';
    return 'Previous';
}

function statusClass(item: PackageItem, isLatest: boolean) {
    if (item?.applied) return 'applied';
    if (item?.decision && item.decision !== 'qa_approved') return 'returned';
    if (isLatest) return 'latest';
    return 'previous';
}

function useDetailPrefetch(
    slugs: string[],
    details: DetailMap,
    setDetails: React.Dispatch<React.SetStateAction<DetailMap>>,
) {
    const inflight = useRef<Set<string>>(new Set());

    useEffect(() => {
        for (const slug of slugs) {
            if (!slug || details[slug] || inflight.current.has(slug)) continue;
            inflight.current.add(slug);
            api
                .getPackageDetail(slug)
                .then((detail: any) => {
                    setDetails((prev) => ({ ...prev, [slug]: detail }));
                })
                .catch(() => {})
                .finally(() => {
                    inflight.current.delete(slug);
                });
        }
    }, [slugs.join('|')]);
}

function MatchedSkills({ requirements }: { requirements?: any[] }) {
    const skills = useMemo(() => {
        const seen = new Set<string>();
        const out: string[] = [];
        for (const req of requirements || []) {
            const arr = Array.isArray(req?.matched_skills) ? req.matched_skills : [];
            for (const value of arr) {
                const skill = String(value || '').trim();
                const key = skill.toLowerCase();
                if (!skill || seen.has(key)) continue;
                seen.add(key);
                out.push(skill);
                if (out.length >= 10) return out;
            }
        }
        return out;
    }, [requirements]);

    if (!skills.length) return null;
    return (
        <div className="pkg-inbox-skills">
            {skills.map((skill) => (
                <span key={skill}>{skill}</span>
            ))}
        </div>
    );
}

export default function PackageCompanyInbox({
    groups,
    activeIndex,
    setActiveIndex,
    activeRunBySlug,
    setActiveRunBySlug,
    selectedSlugs,
    onToggleSelect,
    onOpen,
    onRequeue,
    onDead,
    bulkBar,
    headerRight,
    eyebrow,
}: Props) {
    const safeIndex = Math.max(0, Math.min(activeIndex, groups.length - 1));
    const [details, setDetails] = useState<DetailMap>({});

    const activeItemFor = (group: PackageGroup) => {
        const runIndex = activeRunBySlug[group.key] ?? 0;
        return group.items[Math.min(runIndex, group.items.length - 1)];
    };

    const companies = useMemo(() => {
        const map = new Map<string, {
            key: string;
            display: string;
            groups: PackageGroup[];
            firstIndex: number;
            latestTs: number;
            appliedCount: number;
            unappliedCount: number;
            returnedCount: number;
            historyCount: number;
        }>();

        groups.forEach((group, index) => {
            const key = companyKey(group);
            const latestItem = group.items[0];
            const bucket = map.get(key) ?? {
                key,
                display: companyDisplay(group),
                groups: [],
                firstIndex: index,
                latestTs: 0,
                appliedCount: 0,
                unappliedCount: 0,
                returnedCount: 0,
                historyCount: 0,
            };
            bucket.groups.push(group);
            bucket.latestTs = Math.max(bucket.latestTs, packageUpdatedAt(latestItem));
            bucket.appliedCount += latestItem?.applied ? 1 : 0;
            bucket.unappliedCount += latestItem?.applied ? 0 : 1;
            bucket.returnedCount += latestItem?.decision && latestItem.decision !== 'qa_approved' && !latestItem.applied ? 1 : 0;
            bucket.historyCount += group.items.length > 1 ? 1 : 0;
            if (!map.has(key)) map.set(key, bucket);
        });

        return Array.from(map.values()).sort((a, b) => b.latestTs - a.latestTs);
    }, [groups]);

    const activeGroup = groups[safeIndex];
    const activeCompanyKey = activeGroup ? companyKey(activeGroup) : '';
    const activeCompany = companies.find((company) => company.key === activeCompanyKey) ?? companies[0];
    const activeRunIndex = activeGroup ? activeRunBySlug[activeGroup.key] ?? 0 : 0;
    const activeItem = activeGroup ? activeItemFor(activeGroup) : null;
    const detail = activeItem ? details[activeItem.slug] : null;

    const prefetchSlugs = useMemo(() => {
        const out = new Set<string>();
        if (activeItem?.slug) out.add(activeItem.slug);
        for (const group of activeCompany?.groups || []) {
            const item = activeItemFor(group);
            if (item?.slug) out.add(item.slug);
            if (out.size >= 6) break;
        }
        return Array.from(out);
    }, [activeItem?.slug, activeCompany?.key, activeRunBySlug]);

    useDetailPrefetch(prefetchSlugs, details, setDetails);

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            const tagName = (event.target as HTMLElement)?.tagName;
            if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT') return;
            if (!groups.length || !activeCompany) return;

            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault();
                const companyIndex = companies.findIndex((company) => company.key === activeCompany.key);
                const nextCompanyIndex = event.key === 'ArrowLeft'
                    ? Math.max(0, companyIndex - 1)
                    : Math.min(companies.length - 1, companyIndex + 1);
                setActiveIndex(companies[nextCompanyIndex]?.firstIndex ?? safeIndex);
                return;
            }

            if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                event.preventDefault();
                const localIndex = activeCompany.groups.findIndex((group) => group.key === activeGroup?.key);
                const nextLocalIndex = event.key === 'ArrowUp'
                    ? Math.max(0, localIndex - 1)
                    : Math.min(activeCompany.groups.length - 1, localIndex + 1);
                const nextGroup = activeCompany.groups[nextLocalIndex];
                const nextIndex = groups.findIndex((group) => group.key === nextGroup?.key);
                if (nextIndex >= 0) setActiveIndex(nextIndex);
                return;
            }

            if (event.key === 'Enter' && activeItem?.slug) {
                event.preventDefault();
                onOpen(activeItem.slug);
            }
        };

        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [groups, companies, activeCompany?.key, activeGroup?.key, activeItem?.slug, safeIndex]);

    if (!groups.length) {
        return (
            <div className="pkg-inbox-stage">
                <div className="pkg-inbox-empty">
                    <BriefcaseBusiness size={28} />
                    <h3>No packages in scope</h3>
                    <span>Adjust filters to show document packages.</span>
                </div>
            </div>
        );
    }

    const companyIndex = companies.findIndex((company) => company.key === activeCompany?.key);
    const activeJobIndex = activeCompany?.groups.findIndex((group) => group.key === activeGroup?.key) ?? -1;
    const analysis = detail?.analysis;
    const ctx = detail?.job_context;
    const companyName = analysis?.company_name || activeGroup?.company || activeCompany?.display || 'Unknown company';
    const roleTitle = analysis?.role_title || activeGroup?.title || 'Untitled role';
    const board = prettyBoard(activeItem?.meta?.board || ctx?.board);
    const externalUrl = ctx?.url || activeItem?.meta?.url || '';
    const summary =
        analysis?.company_context?.what_they_build ||
        detail?.cover_strategy?.company_hook ||
        ctx?.snippet ||
        '';
    const angle =
        analysis?.summary_angle ||
        detail?.cover_strategy?.closing_angle ||
        '';
    const resumePdfUrl = activeItem?.artifacts?.['Conner_Jordan_Resume.pdf']
        ? `/api/tailoring/runs/${encodeURIComponent(activeItem.slug)}/artifact/${encodeURIComponent('Conner_Jordan_Resume.pdf')}`
        : '';
    const coverPdfUrl = activeItem?.artifacts?.['Conner_Jordan_Cover_Letter.pdf']
        ? `/api/tailoring/runs/${encodeURIComponent(activeItem.slug)}/artifact/${encodeURIComponent('Conner_Jordan_Cover_Letter.pdf')}`
        : '';
    const previewActions = activeItem ? (
        <div className="pkg-preview-actions pkg-preview-actions-top">
            {!activeItem.applied && (
                <button type="button" className="primary" onClick={() => onOpen(activeItem.slug)}>
                    <Send size={15} /> Mark Applied
                </button>
            )}
            <button type="button" onClick={() => onOpen(activeItem.slug)}>
                <FileText size={15} /> Open Full Dossier
            </button>
            <a
                href={resumePdfUrl || undefined}
                target="_blank"
                rel="noreferrer"
                aria-disabled={!resumePdfUrl}
                className={!resumePdfUrl ? 'is-disabled' : ''}
            >
                <FileText size={15} /> Resume
            </a>
            <a
                href={coverPdfUrl || undefined}
                target="_blank"
                rel="noreferrer"
                aria-disabled={!coverPdfUrl}
                className={!coverPdfUrl ? 'is-disabled' : ''}
            >
                <Mail size={15} /> Cover
            </a>
            {externalUrl && (
                <a href={externalUrl} target="_blank" rel="noreferrer">
                    <ExternalLink size={15} /> Posting
                </a>
            )}
            {!activeItem.applied && (
                <button type="button" onClick={() => onRequeue(activeItem.slug)}>
                    <RotateCcw size={15} /> Requeue
                </button>
            )}
            {!activeItem.applied && (
                <button type="button" className="danger" onClick={() => onDead(activeItem.slug)}>
                    <Skull size={15} /> Dead
                </button>
            )}
        </div>
    ) : null;

    return (
        <div className="pkg-inbox-stage">
            <div className="pkg-inbox-header">
                <div>
                    <div className="pkg-inbox-eyebrow">{eyebrow ?? 'Tailored packages'}</div>
                    <h2>Company Inbox</h2>
                </div>
                <div className="pkg-inbox-header-actions">{headerRight}</div>
            </div>

            <div className="pkg-inbox-grid">
                <aside className="pkg-inbox-companies" aria-label="Companies">
                    <div className="pkg-inbox-pane-title">
                        <span>Companies</span>
                        <b>{companies.length}</b>
                    </div>
                    <div className="pkg-inbox-company-list">
                        {companies.map((company, index) => (
                            <button
                                type="button"
                                key={company.key}
                                className={`pkg-company-row ${company.key === activeCompany?.key ? 'is-active' : ''}`}
                                onClick={() => setActiveIndex(company.firstIndex)}
                            >
                                <span className="pkg-company-mark">{companyInitials(company.display)}</span>
                                <span className="pkg-company-copy">
                                    <span className="name">{company.display}</span>
                                    <span className="meta">
                                        {company.groups.length} job{company.groups.length === 1 ? '' : 's'}
                                        {' / '}
                                        {timeAgo(new Date(company.latestTs).toISOString())}
                                    </span>
                                </span>
                                <span className="pkg-company-counts">
                                    {company.unappliedCount > 0 && <span className="pending">{company.unappliedCount}</span>}
                                    {company.appliedCount > 0 && <span className="applied">{company.appliedCount}</span>}
                                    {company.historyCount > 0 && <span className="history">{company.historyCount}</span>}
                                </span>
                                <span className="pkg-company-index">{index + 1}</span>
                            </button>
                        ))}
                    </div>
                </aside>

                <section className="pkg-inbox-jobs" aria-label={`${activeCompany?.display || 'Selected company'} packages`}>
                    <div className="pkg-inbox-pane-title">
                        <span>{activeCompany?.display || 'Jobs'}</span>
                        <b>{activeCompany?.groups.length || 0}</b>
                    </div>
                    <div className="pkg-job-list">
                        {(activeCompany?.groups || []).map((group, index) => {
                            const item = activeItemFor(group);
                            const groupIndex = groups.findIndex((candidate) => candidate.key === group.key);
                            const runIndex = activeRunBySlug[group.key] ?? 0;
                            const isActive = group.key === activeGroup?.key;
                            const selected = item?.slug ? selectedSlugs.has(item.slug) : false;
                            return (
                                <article
                                    key={group.key}
                                    className={`pkg-job-row ${isActive ? 'is-active' : ''}`}
                                    onClick={() => {
                                        if (groupIndex >= 0) setActiveIndex(groupIndex);
                                    }}
                                >
                                    <button
                                        type="button"
                                        className={`pkg-job-select ${selected ? 'is-on' : ''}`}
                                        title={selected ? 'Deselect package' : 'Select package'}
                                        onClick={(event) => {
                                            event.stopPropagation();
                                            if (item?.slug) onToggleSelect(item.slug);
                                        }}
                                    >
                                        <Check size={13} />
                                    </button>
                                    <div className="pkg-job-main">
                                        <div className="pkg-job-topline">
                                            <span>{group.title}</span>
                                            <em>{index + 1}</em>
                                        </div>
                                        <div className="pkg-job-meta">
                                            {prettyBoard(item?.meta?.board) || 'Package'}
                                            {' / '}
                                            {timeAgo(item?.updated_at)}
                                            {group.items.length > 1 && <> / {group.items.length} runs</>}
                                        </div>
                                        {group.items.length > 1 && (
                                            <div className="pkg-run-tabs" onClick={(event) => event.stopPropagation()}>
                                                {group.items.map((run, runIdx) => (
                                                    <button
                                                        key={run.slug}
                                                        type="button"
                                                        className={runIdx === runIndex ? 'is-active' : ''}
                                                        onClick={() => setActiveRunBySlug((prev) => ({ ...prev, [group.key]: runIdx }))}
                                                        title={run.slug}
                                                    >
                                                        {runIdx === 0 ? 'Latest' : `Run ${runIdx + 1}`}
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    {item && (
                                        <span className={`pkg-status ${statusClass(item, runIndex === 0)}`}>
                                            {statusLabel(item, runIndex === 0)}
                                        </span>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                </section>

                <section className="pkg-inbox-preview" aria-label="Package preview">
                    {activeItem ? (
                        <>
                            <div className="pkg-preview-card">
                                <div className="pkg-preview-head">
                                    <div className="pkg-preview-mark">{companyInitials(companyName)}</div>
                                    <div>
                                        <div className="pkg-preview-kicker">
                                            Company {companyIndex + 1} / Job {activeJobIndex + 1}
                                        </div>
                                        <h3>{companyName}</h3>
                                        <p>{roleTitle}</p>
                                    </div>
                                </div>

                                {previewActions}

                                <div className="pkg-preview-facts">
                                    <span>{board || 'Package'}</span>
                                    <span>{timeAgo(activeItem.updated_at)}</span>
                                    <span>{statusLabel(activeItem, activeRunIndex === 0)}</span>
                                </div>

                                <div className="pkg-preview-section">
                                    <h4>Company Signal</h4>
                                    {detail ? (
                                        <p>{summary || 'No company context captured for this package.'}</p>
                                    ) : (
                                        <div className="pkg-preview-skeleton" />
                                    )}
                                </div>

                                <div className="pkg-preview-section">
                                    <h4>Strategy Angle</h4>
                                    {detail ? (
                                        <p>{angle || 'No strategy angle captured for this package.'}</p>
                                    ) : (
                                        <div className="pkg-preview-skeleton short" />
                                    )}
                                </div>

                                <MatchedSkills requirements={analysis?.requirements} />

                                {activeGroup && activeGroup.items.length > 1 && (
                                    <div className="pkg-preview-runs">
                                        {activeGroup.items.map((run, index) => (
                                            <button
                                                key={run.slug}
                                                type="button"
                                                className={index === activeRunIndex ? 'is-active' : ''}
                                                onClick={() => setActiveRunBySlug((prev) => ({ ...prev, [activeGroup.key]: index }))}
                                            >
                                                {index === 0 ? 'Latest' : `Run ${index + 1}`} <span>{timeAgo(run.updated_at)}</span>
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="pkg-inbox-empty">
                            <BriefcaseBusiness size={28} />
                            <h3>No package selected</h3>
                            <span>Choose a job to preview actions.</span>
                        </div>
                    )}
                </section>
            </div>

            {bulkBar}
        </div>
    );
}
