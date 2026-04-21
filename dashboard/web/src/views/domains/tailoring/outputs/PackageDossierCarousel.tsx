import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, ChevronDown, ExternalLink, FileText, Mail, Send, RotateCcw, Skull, Check, Layers } from 'lucide-react';
import { api } from '../../../../api';
import { timeAgo } from '../../../../utils';

const PACKAGES_RAIL_GROUP_KEY = 'tailoring.packages.railGroupByCompany';

function railCompanyKey(group: { company: string }): string {
    return (group.company || '').trim().toLowerCase() || '__unknown__';
}

function railCompanyDisplay(group: { company: string }): string {
    return (group.company || '').trim() || 'Unknown company';
}

function getInitialRailGrouping(): boolean {
    if (typeof window === 'undefined') return true;
    const v = window.localStorage.getItem(PACKAGES_RAIL_GROUP_KEY);
    return v === null ? true : v === '1';
}

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

/**
 * Stable hash for company → hue / sigil variant.
 */
function hashStr(s: string): number {
    let h = 0;
    for (let i = 0; i < s.length; i++) {
        h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h);
}

function companyInitials(name: string): string {
    const cleaned = (name || '').replace(/[^A-Za-z0-9 ]/g, ' ').trim();
    if (!cleaned) return '··';
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
        hn_hiring: 'HN Hiring',
        remoteok: 'RemoteOK',
        usajobs: 'USAJobs',
        manual: 'Manual',
    };
    return map[board.toLowerCase()] || board;
}

/**
 * Generative dossier sigil — deterministic SVG glyph derived from company hash.
 * Variants pick between a constellation, geometric monogram, satellite ring, and angular crest.
 */
function DossierSigil({ company, slug }: { company: string; slug: string }) {
    const initials = companyInitials(company);
    const seed = hashStr(company || slug);
    const variant = seed % 4;
    const palette = [
        ['#5b9fd4', '#a18cf0'],
        ['#d6a85c', '#d97a83'],
        ['#6ec3a8', '#5b9fd4'],
        ['#a18cf0', '#d6a85c'],
    ][seed % 4];

    return (
        <div className="dossier-sigil" aria-hidden>
            <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
                <defs>
                    <radialGradient id={`sigil-bg-${seed}`} cx="50%" cy="40%" r="60%">
                        <stop offset="0%" stopColor={palette[0]} stopOpacity="0.16" />
                        <stop offset="100%" stopColor={palette[1]} stopOpacity="0" />
                    </radialGradient>
                    <linearGradient id={`sigil-line-${seed}`} x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor={palette[0]} />
                        <stop offset="100%" stopColor={palette[1]} />
                    </linearGradient>
                </defs>
                <rect x="0" y="0" width="100" height="100" fill={`url(#sigil-bg-${seed})`} />
                {variant === 0 && (
                    <g stroke={`url(#sigil-line-${seed})`} strokeWidth="0.8" fill="none">
                        <circle cx="50" cy="50" r="34" opacity="0.45" />
                        <circle cx="50" cy="50" r="22" opacity="0.7" />
                        <circle cx="50" cy="50" r="10" opacity="0.95" />
                        <line x1="16" y1="50" x2="84" y2="50" opacity="0.25" />
                        <line x1="50" y1="16" x2="50" y2="84" opacity="0.25" />
                    </g>
                )}
                {variant === 1 && (
                    <g stroke={`url(#sigil-line-${seed})`} strokeWidth="0.9" fill="none">
                        <polygon points="50,12 86,40 72,84 28,84 14,40" opacity="0.55" />
                        <polygon points="50,28 72,42 64,70 36,70 28,42" opacity="0.85" />
                    </g>
                )}
                {variant === 2 && (
                    <g stroke={`url(#sigil-line-${seed})`} strokeWidth="0.9" fill="none">
                        <ellipse cx="50" cy="50" rx="38" ry="14" opacity="0.5" />
                        <ellipse cx="50" cy="50" rx="38" ry="14" opacity="0.5" transform="rotate(60 50 50)" />
                        <ellipse cx="50" cy="50" rx="38" ry="14" opacity="0.5" transform="rotate(120 50 50)" />
                        <circle cx="50" cy="50" r="6" fill={palette[0]} opacity="0.95" />
                    </g>
                )}
                {variant === 3 && (
                    <g stroke={`url(#sigil-line-${seed})`} strokeWidth="0.9" fill="none">
                        <path d="M20 80 L50 18 L80 80 Z" opacity="0.7" />
                        <path d="M30 70 L50 30 L70 70 Z" opacity="0.85" />
                        <line x1="20" y1="80" x2="80" y2="80" opacity="0.45" />
                    </g>
                )}
                <text
                    x="50"
                    y="56"
                    textAnchor="middle"
                    fontFamily="'Fraunces', serif"
                    fontSize="22"
                    fontWeight="600"
                    fill="#ecf1f8"
                    style={{ fontVariationSettings: '"opsz" 36' }}
                >
                    {initials}
                </text>
            </svg>
            <span className="ticker">CL · {String(seed).slice(0, 4).padStart(4, '0')}</span>
        </div>
    );
}

function relativePosition(diff: number): string {
    if (diff === 0) return 'pos--center';
    if (diff === -1) return 'pos--left';
    if (diff === 1) return 'pos--right';
    if (diff < 0) return 'pos--far-left';
    return 'pos--far-right';
}

type DetailMap = Record<string, any>;

function useDetailPrefetch(
    slugWindow: string[],
    details: DetailMap,
    setDetails: React.Dispatch<React.SetStateAction<DetailMap>>,
) {
    const inflight = useRef<Set<string>>(new Set());
    useEffect(() => {
        for (const slug of slugWindow) {
            if (!slug || details[slug] || inflight.current.has(slug)) continue;
            inflight.current.add(slug);
            api
                .getPackageDetail(slug)
                .then((d: any) => {
                    setDetails((prev) => ({ ...prev, [slug]: d }));
                })
                .catch(() => {})
                .finally(() => {
                    inflight.current.delete(slug);
                });
        }
    }, [slugWindow.join('|')]);
}

function MatchedSkillsRow({ requirements }: { requirements?: any[] }) {
    if (!requirements || !requirements.length) return null;
    const seen = new Set<string>();
    const skills: string[] = [];
    for (const req of requirements.slice(0, 8)) {
        const arr = Array.isArray(req?.matched_skills) ? req.matched_skills : [];
        for (const s of arr) {
            const k = String(s || '').trim();
            if (!k || seen.has(k.toLowerCase())) continue;
            seen.add(k.toLowerCase());
            skills.push(k);
            if (skills.length >= 9) break;
        }
        if (skills.length >= 9) break;
    }
    if (!skills.length) return null;
    return (
        <div className="dossier-chips">
            {skills.map((s, i) => {
                const cls = ['dossier-chip', '', 'alt', 'alt-2', 'alt-3'][i % 4];
                return (
                    <span key={`${s}-${i}`} className={cls.trim()}>
                        <span className="bullet" /> {s}
                    </span>
                );
            })}
            {skills.length >= 9 && <span className="dossier-chip-more">+ more</span>}
        </div>
    );
}

function StampForItem({ item, isLatest }: { item: PackageItem; isLatest: boolean }) {
    if (item?.applied) {
        return (
            <span className="dossier-stamp is-applied">
                <span className="dot" /> Applied
            </span>
        );
    }
    if (item?.decision && item.decision !== 'qa_approved') {
        return (
            <span className="dossier-stamp is-returned">
                <span className="dot" /> Returned
            </span>
        );
    }
    if (isLatest) {
        return (
            <span className="dossier-stamp is-latest">
                <span className="dot" /> Latest
            </span>
        );
    }
    return (
        <span className="dossier-stamp is-pending">
            <span className="dot" /> Archived
        </span>
    );
}

function ActiveDossierBody({
    group,
    item,
    detail,
    onOpen,
    onRequeue,
    onDead,
    onToggleSelect,
    isSelected,
    isLatest,
    onSwitchRun,
    activeRunIndex,
}: {
    group: PackageGroup;
    item: PackageItem;
    detail: any | undefined;
    onOpen: (slug: string) => void;
    onRequeue: (slug: string) => void;
    onDead: (slug: string) => void;
    onToggleSelect: (slug: string) => void;
    isSelected: boolean;
    isLatest: boolean;
    onSwitchRun: (idx: number) => void;
    activeRunIndex: number;
}) {
    const analysis = detail?.analysis;
    const ctx = detail?.job_context;
    const company = analysis?.company_name || group.company;
    const role = analysis?.role_title || group.title;
    const board = prettyBoard(item?.meta?.board || ctx?.board);
    const location = ctx?.location || analysis?.company_context?.locations || '';
    const seniority = ctx?.seniority || '';
    const salary = ctx?.salary_k ? `$${ctx.salary_k}k` : '';
    const whatTheyBuild =
        analysis?.company_context?.what_they_build ||
        detail?.cover_strategy?.company_hook ||
        ctx?.snippet ||
        '';
    const challenges =
        analysis?.company_context?.engineering_challenges ||
        analysis?.tone_notes ||
        '';
    const angle =
        analysis?.summary_angle ||
        detail?.cover_strategy?.closing_angle ||
        '';
    const requirements = analysis?.requirements;
    const hasResume = item?.artifacts?.['Conner_Jordan_Resume.pdf'];
    const hasCover = item?.artifacts?.['Conner_Jordan_Cover_Letter.pdf'];
    const resumePdfUrl = hasResume
        ? `/api/tailoring/runs/${encodeURIComponent(item.slug)}/artifact/${encodeURIComponent('Conner_Jordan_Resume.pdf')}`
        : '';
    const coverPdfUrl = hasCover
        ? `/api/tailoring/runs/${encodeURIComponent(item.slug)}/artifact/${encodeURIComponent('Conner_Jordan_Cover_Letter.pdf')}`
        : '';
    const externalUrl = ctx?.url || item?.meta?.url || '';
    const loadingDetail = !detail;

    return (
        <div className="dossier-card-body">
            <div className="corner-mark tl" />
            <div className="corner-mark tr" />
            <div className="corner-mark bl" />
            <div className="corner-mark br" />

            <div className="dossier-strip">
                <div className="seq">
                    Dossier <b>{group.jobId != null ? `#${group.jobId}` : '—'}</b>
                    {board && <> &nbsp;·&nbsp; {board}</>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <StampForItem item={item} isLatest={isLatest} />
                    <span className="ts">{timeAgo(item?.updated_at)}</span>
                    <button
                        type="button"
                        className={`dossier-iconbtn ${isSelected ? 'is-on' : ''}`}
                        title={isSelected ? 'Deselect' : 'Select for bulk'}
                        onClick={(e) => {
                            e.stopPropagation();
                            onToggleSelect(item.slug);
                        }}
                        style={{ width: 28, height: 28 }}
                    >
                        <Check size={14} />
                    </button>
                </div>
            </div>

            <div style={{ overflowY: 'auto', minHeight: 0, paddingRight: 4 }}>
                <div className="dossier-hero">
                    <div className="dossier-hero-text">
                        <div className="dossier-hero-meta">
                            {seniority && <span>{seniority}</span>}
                            {seniority && (location || salary || board) && <span className="sep">·</span>}
                            {location && <span>{location}</span>}
                            {location && (salary || board) && <span className="sep">·</span>}
                            {salary && <span className="accent">{salary}</span>}
                            {salary && board && <span className="sep">·</span>}
                            {board && <span>via {board}</span>}
                            {!seniority && !location && !salary && !board && <span>Job dossier</span>}
                        </div>
                        <div className="dossier-hero-company">{company}</div>
                        <div className="dossier-hero-role">
                            <span className="em">{role}</span>
                        </div>
                    </div>
                    <DossierSigil company={company} slug={item.slug} />
                </div>

                <div className="dossier-pull">
                    <span className="quote-mark">“</span>
                    {loadingDetail ? (
                        <>
                            <div className="dossier-skeleton-line" />
                            <div className="dossier-skeleton-line medium" />
                            <div className="dossier-skeleton-line short" />
                        </>
                    ) : whatTheyBuild ? (
                        <p>{whatTheyBuild}</p>
                    ) : (
                        <p style={{ color: 'var(--d-ink-3)', fontStyle: 'normal' }}>
                            No company context captured for this run.
                        </p>
                    )}
                </div>

                <div className="dossier-grid">
                    <div>
                        <div className="dossier-block-label">Engineering Frontier</div>
                        {loadingDetail ? (
                            <>
                                <div className="dossier-skeleton-line" />
                                <div className="dossier-skeleton-line medium" />
                                <div className="dossier-skeleton-line short" />
                            </>
                        ) : (
                            <div className="dossier-block-text">
                                {challenges || 'No challenge notes captured.'}
                            </div>
                        )}
                    </div>
                    <div>
                        <div className="dossier-block-label">Strategic Angle</div>
                        {loadingDetail ? (
                            <>
                                <div className="dossier-skeleton-line" />
                                <div className="dossier-skeleton-line" />
                                <div className="dossier-skeleton-line short" />
                            </>
                        ) : (
                            <div className="dossier-block-text">
                                {angle || 'No angle captured for this dossier.'}
                            </div>
                        )}
                    </div>
                </div>

                {!loadingDetail && <MatchedSkillsRow requirements={requirements} />}

                {group.items.length > 1 && (
                    <div className="dossier-runs">
                        <span style={{ marginRight: 4 }}>Runs</span>
                        {group.items.map((it, idx) => (
                            <button
                                key={it.slug}
                                type="button"
                                className={`run ${idx === activeRunIndex ? 'is-active' : ''}`}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onSwitchRun(idx);
                                }}
                                title={it.slug}
                            >
                                {idx === 0 ? 'Latest' : `−${idx}`} · {timeAgo(it.updated_at)}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <div className="dossier-actions">
                <button type="button" className="dossier-btn primary" onClick={() => onOpen(item.slug)}>
                    <FileText size={14} /> Open Dossier <span className="kbd">↵</span>
                </button>
                <a
                    className="dossier-btn"
                    href={resumePdfUrl || undefined}
                    target="_blank"
                    rel="noreferrer"
                    style={{ pointerEvents: resumePdfUrl ? 'auto' : 'none', opacity: resumePdfUrl ? 1 : 0.4 }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <FileText size={14} /> Resume
                </a>
                <a
                    className="dossier-btn"
                    href={coverPdfUrl || undefined}
                    target="_blank"
                    rel="noreferrer"
                    style={{ pointerEvents: coverPdfUrl ? 'auto' : 'none', opacity: coverPdfUrl ? 1 : 0.4 }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <Mail size={14} /> Cover
                </a>
                {externalUrl && (
                    <a
                        className="dossier-btn ghost"
                        href={externalUrl}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <ExternalLink size={14} /> Posting
                    </a>
                )}
                <span className="spacer" />
                {!item?.applied && (
                    <button
                        type="button"
                        className="dossier-btn ghost"
                        onClick={(e) => {
                            e.stopPropagation();
                            onOpen(item.slug);
                        }}
                        title="Mark applied (opens dossier)"
                    >
                        <Send size={14} /> Mark Applied
                    </button>
                )}
                {!item?.applied && (
                    <button
                        type="button"
                        className="dossier-btn ghost"
                        title="Re-queue for tailoring"
                        onClick={(e) => {
                            e.stopPropagation();
                            onRequeue(item.slug);
                        }}
                    >
                        <RotateCcw size={14} />
                    </button>
                )}
                {!item?.applied && (
                    <button
                        type="button"
                        className="dossier-btn danger"
                        title="Mark dead — permanent reject"
                        onClick={(e) => {
                            e.stopPropagation();
                            onDead(item.slug);
                        }}
                    >
                        <Skull size={14} />
                    </button>
                )}
            </div>
        </div>
    );
}

function PeekBody({ group, item }: { group: PackageGroup; item: PackageItem }) {
    return (
        <div className="dossier-peek">
            <div className="peek-eyebrow">
                {prettyBoard(item?.meta?.board) || 'Dossier'} · {timeAgo(item?.updated_at)}
            </div>
            <div className="peek-company">{group.company}</div>
            <div className="peek-role">{group.title}</div>
        </div>
    );
}

export default function PackageDossierCarousel({
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
    const [railGroupByCompany, setRailGroupByCompany] = useState<boolean>(getInitialRailGrouping);
    const [railExpandedCompanies, setRailExpandedCompanies] = useState<Set<string>>(new Set());

    useEffect(() => {
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(PACKAGES_RAIL_GROUP_KEY, railGroupByCompany ? '1' : '0');
        }
    }, [railGroupByCompany]);

    const companyRail = useMemo(() => {
        const map = new Map<string, { key: string; display: string; groups: PackageGroup[]; firstIndex: number }>();
        groups.forEach((g, idx) => {
            const key = railCompanyKey(g);
            const bucket = map.get(key);
            if (bucket) bucket.groups.push(g);
            else map.set(key, { key, display: railCompanyDisplay(g), groups: [g], firstIndex: idx });
        });
        return Array.from(map.values());
    }, [groups]);

    const activeCompanyKey = groups[safeIndex] ? railCompanyKey(groups[safeIndex]) : '';

    const toggleRailCompany = (key: string) => {
        setRailExpandedCompanies((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const isCompanyExpanded = (key: string) =>
        key === activeCompanyKey || railExpandedCompanies.has(key);

    // Resolve the active item per group (with fallback to latest run)
    const activeItemFor = (g: PackageGroup) => {
        const idx = activeRunBySlug[g.key] ?? 0;
        return g.items[Math.min(idx, g.items.length - 1)];
    };

    // Slug window for prefetch (active + neighbors)
    const slugWindow = useMemo(() => {
        const out: string[] = [];
        for (const offset of [-1, 0, 1]) {
            const g = groups[safeIndex + offset];
            if (g) out.push(activeItemFor(g)?.slug);
        }
        return out.filter(Boolean) as string[];
    }, [groups, safeIndex, activeRunBySlug]);

    useDetailPrefetch(slugWindow, details, setDetails);

    // Keyboard nav
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (
                (e.target as HTMLElement)?.tagName === 'INPUT' ||
                (e.target as HTMLElement)?.tagName === 'TEXTAREA'
            ) {
                return;
            }
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                setActiveIndex(Math.max(0, safeIndex - 1));
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                setActiveIndex(Math.min(groups.length - 1, safeIndex + 1));
            } else if (e.key === 'Enter') {
                const g = groups[safeIndex];
                if (g) {
                    const it = activeItemFor(g);
                    if (it) onOpen(it.slug);
                }
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [safeIndex, groups, activeRunBySlug]);

    // Wheel / trackpad horizontal navigation (debounced)
    const wheelLock = useRef(false);
    const onWheel = (e: React.WheelEvent) => {
        if (Math.abs(e.deltaX) < 16 && Math.abs(e.deltaY) < 16) return;
        if (wheelLock.current) return;
        const dx = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : 0;
        if (!dx) return;
        wheelLock.current = true;
        if (dx > 0) setActiveIndex(Math.min(groups.length - 1, safeIndex + 1));
        else setActiveIndex(Math.max(0, safeIndex - 1));
        setTimeout(() => {
            wheelLock.current = false;
        }, 380);
    };

    if (groups.length === 0) {
        return (
            <div className="dossier-stage">
                <div className="dossier-empty">
                    <h3>No dossiers in scope</h3>
                    <span style={{ fontFamily: 'var(--d-mono)', fontSize: '.7rem', letterSpacing: '.18em', textTransform: 'uppercase' }}>
                        adjust filters to populate the carousel
                    </span>
                </div>
            </div>
        );
    }

    const activeGroup = groups[safeIndex];
    const activeRunIdx = activeRunBySlug[activeGroup.key] ?? 0;
    const isLatestActive = activeRunIdx === 0;
    const progressPct = groups.length > 1 ? ((safeIndex + 1) / groups.length) * 100 : 100;

    return (
        <div className="dossier-stage">
            <div className="dossier-header">
                <div className="dossier-header-left">
                    <span className="dossier-eyebrow reveal-1">
                        <span className="pip" /> {eyebrow ?? 'Tailored Packages'}
                    </span>
                    <h2 className="dossier-title reveal-2">
                        Dossier <em>Carousel</em>
                    </h2>
                </div>
                <div className="dossier-header-right reveal-3">{headerRight}</div>
            </div>

            <div className="dossier-cabin">
                <div className="dossier-track" onWheel={onWheel}>
                    <button
                        type="button"
                        className="dossier-arrow left"
                        onClick={() => setActiveIndex(Math.max(0, safeIndex - 1))}
                        disabled={safeIndex <= 0}
                        aria-label="Previous dossier"
                    >
                        <ChevronLeft size={22} />
                    </button>

                    {groups.map((g, idx) => {
                        const diff = idx - safeIndex;
                        if (Math.abs(diff) > 2) return null;
                        const item = activeItemFor(g);
                        if (!item) return null;
                        const cls = `dossier-card ${relativePosition(diff)}`;
                        const detail = details[item.slug];
                        const isCenter = diff === 0;
                        return (
                            <div
                                key={g.key}
                                className={cls}
                                onClick={() => {
                                    if (!isCenter) setActiveIndex(idx);
                                }}
                                role={isCenter ? 'group' : 'button'}
                                aria-label={isCenter ? `${g.company} — ${g.title}` : `Focus dossier ${g.company}`}
                            >
                                {isCenter ? (
                                    <ActiveDossierBody
                                        group={g}
                                        item={item}
                                        detail={detail}
                                        onOpen={onOpen}
                                        onRequeue={onRequeue}
                                        onDead={onDead}
                                        onToggleSelect={onToggleSelect}
                                        isSelected={selectedSlugs.has(item.slug)}
                                        isLatest={isLatestActive}
                                        activeRunIndex={activeRunIdx}
                                        onSwitchRun={(rIdx) =>
                                            setActiveRunBySlug((prev) => ({ ...prev, [g.key]: rIdx }))
                                        }
                                    />
                                ) : (
                                    <PeekBody group={g} item={item} />
                                )}
                            </div>
                        );
                    })}

                    <button
                        type="button"
                        className="dossier-arrow right"
                        onClick={() => setActiveIndex(Math.min(groups.length - 1, safeIndex + 1))}
                        disabled={safeIndex >= groups.length - 1}
                        aria-label="Next dossier"
                    >
                        <ChevronRight size={22} />
                    </button>

                    {bulkBar}
                </div>

                <div className="dossier-strip-rail">
                    <div className="dossier-rail-meta">
                        <span>
                            <b style={{ color: 'var(--d-ink)', fontFamily: 'var(--d-display)', fontSize: '.78rem', letterSpacing: 0, marginRight: 8 }}>
                                {String(safeIndex + 1).padStart(2, '0')}
                            </b>
                            of {String(groups.length).padStart(2, '0')} dossiers
                            {railGroupByCompany && (
                                <span style={{ marginLeft: 10, opacity: 0.7 }}>
                                    · {companyRail.length} {companyRail.length === 1 ? 'company' : 'companies'}
                                </span>
                            )}
                        </span>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                            <button
                                type="button"
                                onClick={() => setRailGroupByCompany((prev) => !prev)}
                                title={railGroupByCompany ? 'Show flat per-dossier rail' : 'Group rail tiles by company'}
                                style={{
                                    display: 'inline-flex', alignItems: 'center', gap: 4,
                                    padding: '3px 9px',
                                    border: `1px solid ${railGroupByCompany ? 'var(--d-accent, #a18cf0)' : 'var(--border, rgba(255,255,255,0.14))'}`,
                                    borderRadius: 6,
                                    background: railGroupByCompany ? 'rgba(161, 140, 240, 0.14)' : 'transparent',
                                    color: railGroupByCompany ? 'var(--d-accent, #a18cf0)' : 'var(--d-ink-3, rgba(255,255,255,0.55))',
                                    fontFamily: 'var(--d-mono)',
                                    fontSize: '.66rem',
                                    fontWeight: railGroupByCompany ? 700 : 500,
                                    letterSpacing: '.06em',
                                    textTransform: 'uppercase',
                                    cursor: 'pointer',
                                }}
                            >
                                <Layers size={11} /> Group
                            </button>
                            {railGroupByCompany && companyRail.length > 0 && (
                                <button
                                    type="button"
                                    onClick={() => {
                                        const allExpanded = companyRail.every((c) => railExpandedCompanies.has(c.key));
                                        if (allExpanded) setRailExpandedCompanies(new Set());
                                        else setRailExpandedCompanies(new Set(companyRail.map((c) => c.key)));
                                    }}
                                    style={{
                                        padding: '3px 8px',
                                        border: '1px solid var(--border, rgba(255,255,255,0.14))',
                                        borderRadius: 6,
                                        background: 'transparent',
                                        color: 'var(--d-ink-3, rgba(255,255,255,0.55))',
                                        fontFamily: 'var(--d-mono)',
                                        fontSize: '.64rem',
                                        letterSpacing: '.06em',
                                        textTransform: 'uppercase',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {companyRail.every((c) => railExpandedCompanies.has(c.key)) ? 'Collapse' : 'Expand'} all
                                </button>
                            )}
                            <span className="progress">
                                <span>← / →</span>
                                <span className="bar"><i style={{ width: `${progressPct}%` }} /></span>
                            </span>
                        </span>
                    </div>
                    <div className="dossier-rail">
                        {railGroupByCompany ? (
                            companyRail.map((company) => {
                                const expanded = isCompanyExpanded(company.key);
                                const activeItem = activeItemFor(company.groups[0]);
                                const appliedCount = company.groups.filter((g) => !!activeItemFor(g)?.applied).length;
                                const returnedCount = company.groups.filter((g) => {
                                    const it = activeItemFor(g);
                                    return it?.decision && it.decision !== 'qa_approved' && !it.applied;
                                }).length;
                                const containsActive = company.key === activeCompanyKey;
                                return (
                                    <div key={`co:${company.key}`} style={{ display: 'flex', alignItems: 'stretch', gap: 6, width: '100%' }}>
                                        <button
                                            type="button"
                                            className={`rail-tile ${containsActive ? 'is-active' : ''}`}
                                            onClick={() => {
                                                toggleRailCompany(company.key);
                                                if (!containsActive) setActiveIndex(company.firstIndex);
                                            }}
                                            title={`${company.display} — ${company.groups.length} dossier${company.groups.length === 1 ? '' : 's'}`}
                                            style={{
                                                minWidth: 160,
                                                maxWidth: 240,
                                                borderLeft: '3px solid var(--d-accent, #a18cf0)',
                                                paddingLeft: 10,
                                            }}
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                <ChevronDown
                                                    size={12}
                                                    style={{
                                                        color: 'var(--d-accent, #a18cf0)',
                                                        transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)',
                                                        transition: 'transform .14s ease',
                                                        flexShrink: 0,
                                                    }}
                                                />
                                                <span className="tile-init">{companyInitials(company.display)}</span>
                                                <span className="tile-co">{company.display}</span>
                                            </div>
                                            <div className="tile-role" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                <span style={{
                                                    fontFamily: 'var(--d-mono)',
                                                    fontSize: '.6rem',
                                                    fontWeight: 700,
                                                    color: 'var(--d-accent, #a18cf0)',
                                                    background: 'rgba(161, 140, 240, 0.16)',
                                                    border: '1px solid rgba(161, 140, 240, 0.32)',
                                                    padding: '1px 7px',
                                                    borderRadius: 999,
                                                    letterSpacing: '.04em',
                                                }}>
                                                    {company.groups.length} {company.groups.length === 1 ? 'dossier' : 'dossiers'}
                                                </span>
                                                {appliedCount > 0 && (
                                                    <span style={{ fontFamily: 'var(--d-mono)', fontSize: '.58rem', fontWeight: 700, color: '#6ec3a8' }}>
                                                        ✓ {appliedCount}
                                                    </span>
                                                )}
                                                {returnedCount > 0 && (
                                                    <span style={{ fontFamily: 'var(--d-mono)', fontSize: '.58rem', fontWeight: 700, color: '#d97a83' }}>
                                                        ↩ {returnedCount}
                                                    </span>
                                                )}
                                            </div>
                                            {activeItem && company.groups.length === 1 && (
                                                <div
                                                    style={{
                                                        fontFamily: 'var(--d-mono)',
                                                        fontSize: '.58rem',
                                                        opacity: 0.55,
                                                        overflow: 'hidden',
                                                        textOverflow: 'ellipsis',
                                                        whiteSpace: 'nowrap',
                                                    }}
                                                >
                                                    {company.groups[0].title}
                                                </div>
                                            )}
                                        </button>
                                        {expanded && company.groups.length > 1 && (
                                            <div style={{ display: 'flex', gap: 4, alignItems: 'stretch', borderLeft: '1px dashed rgba(161, 140, 240, 0.28)', paddingLeft: 6 }}>
                                                {company.groups.map((g) => {
                                                    const idx = groups.indexOf(g);
                                                    const item = activeItemFor(g);
                                                    const status = item?.applied ? 'applied' : (item?.decision && item.decision !== 'qa_approved') ? 'returned' : '';
                                                    return (
                                                        <button
                                                            key={g.key}
                                                            type="button"
                                                            className={`rail-tile ${idx === safeIndex ? 'is-active' : ''}`}
                                                            onClick={() => setActiveIndex(idx)}
                                                            title={`${g.company} — ${g.title}`}
                                                            style={{ minWidth: 150 }}
                                                        >
                                                            {status && <span className={`tile-status ${status}`} />}
                                                            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                                                                <span className="tile-init">{companyInitials(g.company)}</span>
                                                                <span className="tile-co">{g.company}</span>
                                                            </div>
                                                            <div className="tile-role">{g.title}</div>
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        ) : (
                            groups.map((g, idx) => {
                                const item = activeItemFor(g);
                                const status = item?.applied ? 'applied' : (item?.decision && item.decision !== 'qa_approved') ? 'returned' : '';
                                return (
                                    <button
                                        key={g.key}
                                        type="button"
                                        className={`rail-tile ${idx === safeIndex ? 'is-active' : ''}`}
                                        onClick={() => setActiveIndex(idx)}
                                        title={`${g.company} — ${g.title}`}
                                    >
                                        {status && <span className={`tile-status ${status}`} />}
                                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                                            <span className="tile-init">{companyInitials(g.company)}</span>
                                            <span className="tile-co">{g.company}</span>
                                        </div>
                                        <div className="tile-role">{g.title}</div>
                                    </button>
                                );
                            })
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
