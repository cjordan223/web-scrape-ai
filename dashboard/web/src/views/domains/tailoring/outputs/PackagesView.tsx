import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { api } from '../../../../api';
import { MessageSquare, ChevronDown, ChevronUp, Copy, Scissors, SlidersHorizontal, X, RotateCcw, Skull } from 'lucide-react';
import { copyText, toLocalInputValue } from '../../../../utils';
import PackageChatPanel from './PackageChatTab';
import { DetailContextSection, BriefingPanel, DocumentsSideBySide, StrategyCard, JdDisplay, safePdfName } from './shared';
import PackageDossierCarousel from './PackageDossierCarousel';

type MainTab = 'briefing' | 'strategy' | 'documents' | 'jd' | 'diff' | 'editor';
type RunFilter = 'all' | 'recent_reruns' | 'latest_only' | 'previous_only' | 'with_history' | 'returned';
type TimelineMode = 'off' | 'newer_than' | 'between';
type TimelineUnit = 'hours' | 'days';

type PackageGroup = {
    key: string;
    jobId: number | null;
    title: string;
    company: string;
    items: any[];
};

function packageUpdatedAt(item: any) {
    const raw = item?.updated_at || item?.created_at || 0;
    const ts = new Date(raw).getTime();
    return Number.isFinite(ts) ? ts : 0;
}

function isTimestampedRerunSlug(slug?: string) {
    return Boolean(slug && /-\d{8}T\d{6}Z$/.test(slug));
}

function timelineUnitMs(unit: TimelineUnit) {
    return unit === 'days' ? 24 * 60 * 60 * 1000 : 60 * 60 * 1000;
}

function timelineMatches(
    item: any,
    {
        mode,
        unit,
        newerThanValue,
        betweenMinValue,
        betweenMaxValue,
    }: {
        mode: TimelineMode;
        unit: TimelineUnit;
        newerThanValue: string;
        betweenMinValue: string;
        betweenMaxValue: string;
    },
) {
    if (mode === 'off') return true;
    const ts = packageUpdatedAt(item);
    if (!ts) return false;
    const ageMs = Date.now() - ts;
    const unitMs = timelineUnitMs(unit);

    if (mode === 'newer_than') {
        const threshold = Number(newerThanValue);
        if (!Number.isFinite(threshold) || threshold < 0) return true;
        return ageMs <= threshold * unitMs;
    }

    const min = Number(betweenMinValue);
    const max = Number(betweenMaxValue);
    if (!Number.isFinite(min) || !Number.isFinite(max) || min < 0 || max < 0) return true;
    const lower = Math.min(min, max) * unitMs;
    const upper = Math.max(min, max) * unitMs;
    return ageMs >= lower && ageMs <= upper;
}

function describeTimelineFilter(
    mode: TimelineMode,
    unit: TimelineUnit,
    newerThanValue: string,
    betweenMinValue: string,
    betweenMaxValue: string,
) {
    const unitLabel = unit === 'days' ? 'day' : 'hour';
    if (mode === 'newer_than') {
        const threshold = Number(newerThanValue);
        if (!Number.isFinite(threshold) || threshold < 0) return 'Timeline off';
        return `${threshold} ${unitLabel}${threshold === 1 ? '' : 's'} or newer`;
    }
    if (mode === 'between') {
        const min = Number(betweenMinValue);
        const max = Number(betweenMaxValue);
        if (!Number.isFinite(min) || !Number.isFinite(max) || min < 0 || max < 0) return 'Timeline off';
        const lower = Math.min(min, max);
        const upper = Math.max(min, max);
        return `Between ${lower}-${upper} ${unitLabel}${upper === 1 ? '' : 's'} ago`;
    }
    return 'Timeline off';
}

const timelineInputStyle: React.CSSProperties = { borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '7px 9px', minWidth: 0 };

function TimelineControls({
    mode, setMode, unit, setUnit,
    newerThanValue, setNewerThanValue,
    betweenMinValue, setBetweenMinValue,
    betweenMaxValue, setBetweenMaxValue,
    summary,
}: {
    mode: TimelineMode; setMode: (m: TimelineMode) => void;
    unit: TimelineUnit; setUnit: (u: TimelineUnit) => void;
    newerThanValue: string; setNewerThanValue: (v: string) => void;
    betweenMinValue: string; setBetweenMinValue: (v: string) => void;
    betweenMaxValue: string; setBetweenMaxValue: (v: string) => void;
    summary: string;
}) {
    const showInputs = mode !== 'off';
    return (
        <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--border)' }}>
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '8px',
                fontFamily: 'var(--font-mono)', fontSize: '.6rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.08em',
            }}>
                <span>Timeline View</span>
                <span>{summary}</span>
            </div>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <button className={`btn btn-sm ${mode === 'newer_than' ? 'btn-primary' : 'btn-ghost'}`} style={{ fontSize: '.62rem', flex: 1 }} onClick={() => setMode('newer_than')}>Or newer</button>
                <button className={`btn btn-sm ${mode === 'between' ? 'btn-primary' : 'btn-ghost'}`} style={{ fontSize: '.62rem', flex: 1 }} onClick={() => setMode('between')}>Between ages</button>
                <button className={`btn btn-sm ${mode === 'off' ? 'btn-primary' : 'btn-ghost'}`} style={{ fontSize: '.62rem', flex: 1 }} onClick={() => setMode('off')}>All time</button>
            </div>
            {showInputs && (
                <div style={{ display: 'grid', gridTemplateColumns: mode === 'between' ? '1fr 1fr auto' : '1fr auto', gap: '6px', marginTop: '8px' }}>
                    {mode === 'newer_than' ? (
                        <input type="number" min="0" step="1" value={newerThanValue} onChange={(e) => setNewerThanValue(e.target.value)} style={timelineInputStyle} />
                    ) : (
                        <>
                            <input type="number" min="0" step="1" value={betweenMinValue} onChange={(e) => setBetweenMinValue(e.target.value)} style={timelineInputStyle} />
                            <input type="number" min="0" step="1" value={betweenMaxValue} onChange={(e) => setBetweenMaxValue(e.target.value)} style={timelineInputStyle} />
                        </>
                    )}
                    <select value={unit} onChange={(e) => setUnit(e.target.value as TimelineUnit)} style={timelineInputStyle}>
                        <option value="hours">Hours</option>
                        <option value="days">Days</option>
                    </select>
                </div>
            )}
        </div>
    );
}

function groupPackages(items: any[]): PackageGroup[] {
    const groups = new Map<string, PackageGroup>();

    for (const item of items) {
        const jobId = item?.meta?.job_id ?? null;
        const title = item?.meta?.job_title || item?.meta?.title || 'Untitled';
        const company = item?.meta?.company_name || item?.meta?.company || '--';
        const key = jobId != null ? `job:${jobId}` : `slug:${item.slug}`;
        const existing = groups.get(key);
        if (existing) {
            existing.items.push(item);
            continue;
        }
        groups.set(key, {
            key,
            jobId: typeof jobId === 'number' ? jobId : jobId != null ? Number(jobId) : null,
            title,
            company,
            items: [item],
        });
    }

    return Array.from(groups.values())
        .map((group) => ({
            ...group,
            items: [...group.items].sort((a, b) => packageUpdatedAt(b) - packageUpdatedAt(a)),
        }))
        .sort((a, b) => packageUpdatedAt(b.items[0]) - packageUpdatedAt(a.items[0]));
}

type ManualEntryItem = {
    label: string;
    value: string;
    compact?: boolean;
};

type ManualEntrySection = {
    title: string;
    items: ManualEntryItem[];
};

function escapeRegex(value: string) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function cleanLatexText(value: string) {
    if (!value) return '';
    let text = value;
    text = text.replace(/%.*$/gm, '');
    text = text.replace(/\\href\{([^}]*)\}\{([\s\S]*?)\}/g, (_match, url, label) => {
        const cleanedLabel = cleanLatexText(label).trim();
        return cleanedLabel || String(url || '').trim();
    });
    text = text.replace(/\\textbf\{([\s\S]*?)\}/g, '$1');
    text = text.replace(/\\textit\{([\s\S]*?)\}/g, '$1');
    text = text.replace(/\\(?:emph|underline|small|large|Large|Huge)\{([\s\S]*?)\}/g, '$1');
    text = text.replace(/\\(?:fa[A-Za-z]+|resumeBodySize|resumeCompanySize|resumeMetaSize|resumeHeaderRoleSize)\b/g, ' ');
    text = text.replace(/\\hfill/g, ' ');
    text = text.replace(/\\vspace\{[^}]*\}/g, '\n');
    text = text.replace(/\\\\(?:\[[^\]]*\])?/g, '\n');
    text = text.replace(/\\,/g, ' ');
    text = text.replace(/\\\//g, '/');
    text = text.replace(/\\\+/g, '+');
    text = text.replace(/\\&/g, '&');
    text = text.replace(/\\%/g, '%');
    text = text.replace(/\\#/g, '#');
    text = text.replace(/\\_/g, '_');
    text = text.replace(/\\\$/g, '$');
    text = text.replace(/\\\{/g, '{');
    text = text.replace(/\\\}/g, '}');
    text = text.replace(/\\(?:begin|end)\{[^}]*\}/g, ' ');
    text = text.replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])?/g, ' ');
    text = text.replace(/\\(?=\s|[|,+()/:.-])/g, '');
    text = text.replace(/\\(?![a-zA-Z])/g, ' ');
    text = text.replace(/[{}]/g, ' ');
    text = text.replace(/\s*\|\s*/g, ' | ');
    text = text.replace(/[ \t]+\n/g, '\n');
    text = text.replace(/\n[ \t]+/g, '\n');
    text = text.replace(/[ \t]{2,}/g, ' ');
    text = text.replace(/\n{3,}/g, '\n\n');
    return text.trim();
}

function extractSection(tex: string, name: string) {
    const match = tex.match(new RegExp(`\\\\section\\{${escapeRegex(name)}\\}([\\s\\S]*?)(?=\\\\section\\{|\\\\end\\{document\\})`));
    return match?.[1] || '';
}

function extractHeaderItems(tex: string): ManualEntrySection | null {
    const header = tex.match(/\\begin\{center\}([\s\S]*?)\\end\{center\}/)?.[1];
    if (!header) return null;

    const items: ManualEntryItem[] = [];
    const name = cleanLatexText(header.match(/\{\\Huge\s+\\textbf\{([^}]*)\}\}/)?.[1] || '');
    const role = cleanLatexText(header.match(/\{\\resumeHeaderRoleSize\s+([^}]*)\}/)?.[1] || '');
    const location = cleanLatexText(header.match(/\\faMapMarker\\\s*([\s\S]*?)\\\\(?:\[[^\]]*\])?/)?.[1] || '');

    if (name) items.push({ label: 'Name', value: name, compact: true });
    if (role) items.push({ label: 'Headline', value: role, compact: true });

    for (const match of header.matchAll(/\\href\{([^}]*)\}\{([\s\S]*?)\}/g)) {
        const url = String(match[1] || '').trim();
        const label = cleanLatexText(String(match[2] || '')) || url;
        if (!url) continue;
        if (url.startsWith('tel:')) items.push({ label: 'Phone', value: label, compact: true });
        else if (url.startsWith('mailto:')) items.push({ label: 'Email', value: label, compact: true });
        else if (url.includes('linkedin.com')) items.push({ label: 'LinkedIn', value: label, compact: true });
        else if (url.includes('github.com')) items.push({ label: 'GitHub', value: label, compact: true });
        else items.push({ label: 'Website', value: label, compact: true });
    }

    if (location) items.push({ label: 'Location', value: location, compact: true });
    return items.length ? { title: 'Contact', items } : null;
}

function extractSummaryItems(tex: string): ManualEntrySection | null {
    const block = cleanLatexText(extractSection(tex, 'PROFESSIONAL SUMMARY'));
    if (!block) return null;
    const lines = block.split('\n').map((line) => line.trim()).filter(Boolean);
    const value = lines.join(' ').replace(/\s{2,}/g, ' ').trim();
    return value ? { title: 'Summary', items: [{ label: 'Professional Summary', value }] } : null;
}

function extractSkillsItems(tex: string): ManualEntrySection | null {
    const block = extractSection(tex, 'TECHNICAL SKILLS');
    if (!block) return null;
    const items = Array.from(block.matchAll(/\\textbf\{([^}:]+):\}\s*([\s\S]*?)(?=(?:\\vspace\{)|(?:\\textbf\{)|$)/g))
        .map((match) => ({
            label: cleanLatexText(String(match[1] || '')),
            value: cleanLatexText(String(match[2] || '')),
        }))
        .filter((item) => item.label && item.value);
    return items.length ? { title: 'Skills', items } : null;
}

function extractExperienceSections(tex: string): ManualEntrySection[] {
    const block = extractSection(tex, 'WORK EXPERIENCE');
    if (!block) return [];
    const pattern = /\\resumeSubheading\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}([\s\S]*?)(?=(?:\\resumeSubheading\s*\{)|\\resumeSubHeadingListEnd|\\section\{|$)/g;
    return Array.from(block.matchAll(pattern)).map((match) => {
        const company = cleanLatexText(String(match[1] || ''));
        const location = cleanLatexText(String(match[2] || ''));
        const title = cleanLatexText(String(match[3] || ''));
        const dates = cleanLatexText(String(match[4] || ''));
        const body = String(match[5] || '');
        const bullets = Array.from(body.matchAll(/\\resumeItem\{([\s\S]*?)\}/g))
            .map((bullet) => cleanLatexText(String(bullet[1] || '')))
            .filter(Boolean);
        const items: ManualEntryItem[] = [];
        if (company) items.push({ label: 'Company', value: company, compact: true });
        if (title) items.push({ label: 'Title', value: title, compact: true });
        if (dates) items.push({ label: 'Dates', value: dates, compact: true });
        if (location) items.push({ label: 'Location', value: location, compact: true });
        bullets.forEach((bullet, index) => items.push({ label: `Bullet ${index + 1}`, value: bullet }));
        return {
            title: company ? `Experience · ${company}` : 'Experience',
            items,
        };
    }).filter((section) => section.items.length > 0);
}

function extractEducationItems(tex: string): ManualEntrySection | null {
    const block = extractSection(tex, 'EDUCATION');
    if (!block) return null;
    const subheading = block.match(/\\resumeSubheading\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}/);
    const items: ManualEntryItem[] = [];
    if (subheading) {
        const school = cleanLatexText(subheading[1] || '');
        const location = cleanLatexText(subheading[2] || '');
        const degree = cleanLatexText(subheading[3] || '');
        const dates = cleanLatexText(subheading[4] || '');
        if (school) items.push({ label: 'School', value: school, compact: true });
        if (degree) items.push({ label: 'Degree', value: degree, compact: true });
        if (dates) items.push({ label: 'Dates', value: dates, compact: true });
        if (location) items.push({ label: 'Location', value: location, compact: true });
    }
    const details = Array.from(block.matchAll(/\\item\s*\{([\s\S]*?)\}/g))
        .map((match) => cleanLatexText(String(match[1] || '')))
        .filter(Boolean);
    details.forEach((detail, index) => items.push({ label: index === 0 ? 'Honors' : `Education Detail ${index}`, value: detail }));
    return items.length ? { title: 'Education', items } : null;
}

function extractCertificationItems(tex: string): ManualEntrySection | null {
    const block = extractSection(tex, 'CERTIFICATIONS');
    if (!block) return null;
    const items = Array.from(block.matchAll(/\\item\s*\{([\s\S]*?)\}/g))
        .map((match) => cleanLatexText(String(match[1] || '')))
        .filter(Boolean)
        .map((value, index) => ({ label: `Certification ${index + 1}`, value, compact: true }));
    return items.length ? { title: 'Certifications', items } : null;
}

function buildManualEntrySections(tex: string): ManualEntrySection[] {
    if (!tex) return [];
    const sections = [
        extractHeaderItems(tex),
        extractSummaryItems(tex),
        extractSkillsItems(tex),
        ...extractExperienceSections(tex),
        extractEducationItems(tex),
        extractCertificationItems(tex),
    ].filter(Boolean) as ManualEntrySection[];

    const fullResume = cleanLatexText(extractSection(tex, 'PROFESSIONAL SUMMARY') + '\n' + extractSection(tex, 'TECHNICAL SKILLS') + '\n' + extractSection(tex, 'WORK EXPERIENCE') + '\n' + extractSection(tex, 'EDUCATION') + '\n' + extractSection(tex, 'CERTIFICATIONS'));
    if (fullResume) {
        sections.push({ title: 'Full Resume', items: [{ label: 'Resume Text', value: fullResume }] });
    }
    return sections;
}

function buildCoverLetterManualEntrySection(tex: string): ManualEntrySection | null {
    if (!tex) return null;
    const plainText = cleanLatexText(tex).replace(/\n{3,}/g, '\n\n').trim();
    if (!plainText) return null;
    return {
        title: 'Cover Letter',
        items: [{ label: 'Plain Text Cover Letter', value: plainText }],
    };
}

export default function PackagesView() {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    const [activeSlug, setActiveSlug] = useState<string | null>(null);
    const [pkgDetail, setPkgDetail] = useState<any>(null);

    // Tabs
    const [mainTab, setMainTab] = useState<MainTab>('documents');

    // Live Editor State
    const [packageDoc, setPackageDoc] = useState<'resume' | 'cover'>('resume');
    const [resumeTex, setResumeTex] = useState('');
    const [coverTex, setCoverTex] = useState('');
    const [saveStatus, setSaveStatus] = useState('');
    const [compileError, setCompileError] = useState('');
    const [previewBuster, setPreviewBuster] = useState({ resume: Date.now(), cover: Date.now() });
    const [diffBuster, setDiffBuster] = useState({ resume: Date.now(), cover: Date.now() });
    const [diffError, setDiffError] = useState('');
    const [chatOpen, setChatOpen] = useState(false);
    const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set());
    const [bulkBusy, setBulkBusy] = useState(false);
    const [applyFilter, setApplyFilter] = useState<'all' | 'unapplied' | 'applied'>('unapplied');
    const [runFilter, setRunFilter] = useState<RunFilter>('all');
    const [timelineMode, setTimelineMode] = useState<TimelineMode>('off');
    const [timelineUnit, setTimelineUnit] = useState<TimelineUnit>('hours');
    const [timelineNewerThanValue, setTimelineNewerThanValue] = useState('6');
    const [timelineBetweenMinValue, setTimelineBetweenMinValue] = useState('2');
    const [timelineBetweenMaxValue, setTimelineBetweenMaxValue] = useState('4');
    const [applyFormOpen, setApplyFormOpen] = useState(false);
    const [applyUrl, setApplyUrl] = useState('');
    const [applyAt, setApplyAt] = useState(toLocalInputValue());
    const [applyFollowUpAt, setApplyFollowUpAt] = useState('');
    const [applyNotes, setApplyNotes] = useState('');
    const [applyBusy, setApplyBusy] = useState(false);
    const [applyError, setApplyError] = useState('');
    const [regenerateBusy, setRegenerateBusy] = useState(false);
    const [regenerateMessage, setRegenerateMessage] = useState('');
    const [deleteBusy, setDeleteBusy] = useState(false);
    const [resumeChunksOpen, setResumeChunksOpen] = useState(false);
    const [copiedChunkIndex, setCopiedChunkIndex] = useState<number | null>(null);
    const [copiedAllChunks, setCopiedAllChunks] = useState(false);
    const [moreOptionsOpen, setMoreOptionsOpen] = useState(false);
    const [carouselIndex, setCarouselIndex] = useState(0);
    const [activeRunBySlug, setActiveRunBySlug] = useState<Record<string, number>>({});
    const [filtersOpen, setFiltersOpen] = useState(false);
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);


    const fetchPackages = useCallback(async () => {
        try {
            const res = await api.getPackages();
            setData(res);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadDetail = useCallback(async (slug: string) => {
        const res = await api.getPackageDetail(slug);
        setPkgDetail(res);
        setResumeTex(res.latex?.resume || '');
        setCoverTex(res.latex?.cover || '');
        setPreviewBuster({ resume: Date.now(), cover: Date.now() });
        setDiffBuster({ resume: Date.now(), cover: Date.now() });
        setSaveStatus('');
        setCompileError('');
        setDiffError('');
        setRegenerateMessage('');
        setMainTab('documents');
        setApplyFormOpen(false);
        setApplyError('');
        setApplyUrl(res.summary?.applied?.application_url || res.job_context?.url || res.summary?.meta?.url || '');
        setApplyAt(toLocalInputValue(res.summary?.applied?.applied_at || new Date().toISOString()));
        setApplyFollowUpAt(res.summary?.applied?.follow_up_at ? toLocalInputValue(res.summary.applied.follow_up_at) : '');
        setApplyNotes(res.summary?.applied?.notes || '');
        setResumeChunksOpen(false);
        setCopiedChunkIndex(null);
        setCopiedAllChunks(false);
        return res;
    }, []);

    useEffect(() => {
        fetchPackages();
        const id = setInterval(fetchPackages, 15000);
        return () => clearInterval(id);
    }, [fetchPackages]);

    useEffect(() => {
        const fetchDetail = async () => {
            if (!activeSlug) {
                setPkgDetail(null);
                return;
            }
            try {
                await loadDetail(activeSlug);
            } catch (err) {
                console.error(err);
                setPkgDetail(null);
            }
        };
        fetchDetail();
    }, [activeSlug, loadDetail]);

    const persistLatex = async (slug: string, doc: 'resume' | 'cover', content: string) => {
        await api.savePackageLatex(slug, doc, content);
        setDiffBuster(prev => ({ ...prev, [doc]: Date.now() }));
    };

    const handleLatexChange = (val: string) => {
        if (packageDoc === 'resume') setResumeTex(val);
        else setCoverTex(val);

        setSaveStatus('saving...');
        if (saveTimer.current) clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(async () => {
            try {
                await persistLatex(activeSlug!, packageDoc, val);
                setSaveStatus('saved');
            } catch {
                setSaveStatus('save failed');
            }
        }, 900);
    };

    const handleCompile = async () => {
        if (!activeSlug) return;
        const currentTex = packageDoc === 'resume' ? resumeTex : coverTex;
        setCompileError('');
        setSaveStatus('saving...');
        if (saveTimer.current) {
            clearTimeout(saveTimer.current);
            saveTimer.current = null;
        }
        try {
            await persistLatex(activeSlug, packageDoc, currentTex);
            setSaveStatus('compiling...');
            const result = await api.compilePackageDoc(activeSlug, packageDoc);
            if (!result?.ok) {
                setCompileError(result?.error || 'compile failed');
                setSaveStatus('compile failed');
                return;
            }
            setSaveStatus('compiled');
            setPreviewBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
            setDiffBuster(prev => ({ ...prev, [packageDoc]: Date.now() }));
        } catch (e: any) {
            const errorMessage = e.response?.data?.error || (e.message === 'Network Error' ? 'save failed' : 'compile failed');
            setCompileError(errorMessage);
            setSaveStatus(errorMessage === 'save failed' ? 'save failed' : 'compile failed');
        }
    };

    const handleRegenerateCover = async () => {
        if (!activeSlug) return;
        setRegenerateBusy(true);
        setRegenerateMessage('');
        setCompileError('');
        try {
            const result = await api.regeneratePackageCover(activeSlug);
            if (!result?.ok) {
                setRegenerateMessage(result?.error || 'Cover regeneration failed');
                return;
            }
            setPackageDoc('cover');
            setMainTab('documents');
            setRegenerateMessage('Cover letter regenerated');
            await fetchPackages();
            await loadDetail(activeSlug);
        } catch (e: any) {
            setRegenerateMessage(e?.response?.data?.error || 'Cover regeneration failed');
        } finally {
            setRegenerateBusy(false);
        }
    };

    const handleRequeuePackage = async (slug: string) => {
        const pkg = data.find(p => p.slug === slug);
        const label = pkg?.meta?.job_title || pkg?.meta?.title || slug;
        if (!confirm(`Return "${label}" to Ready for re-tailoring? Output files will be removed but the job will stay approved for re-queuing.`)) return;
        setDeleteBusy(true);
        try {
            await api.deletePackage(slug);
            if (activeSlug === slug) setActiveSlug(null);
            await fetchPackages();
        } catch (e: any) {
            console.error(e);
        } finally {
            setDeleteBusy(false);
        }
    };

    const handleBulkRequeue = async () => {
        const slugs = [...selectedSlugs];
        if (!slugs.length) return;
        if (!confirm(`Return ${slugs.length} job(s) to Ready for re-tailoring? Output files will be removed but the jobs will stay approved for re-queuing.`)) return;
        setDeleteBusy(true);
        try {
            await Promise.allSettled(slugs.map(slug => api.deletePackage(slug)));
            setSelectedSlugs(new Set());
            setActiveSlug(null);
            await fetchPackages();
        } finally {
            setDeleteBusy(false);
        }
    };

    const handleDeadPackage = async (slug: string) => {
        const pkg = data.find((item) => item.slug === slug);
        const label = pkg?.meta?.job_title || pkg?.meta?.title || slug;
        if (!confirm(`Mark "${label}" as dead? The package will be deleted and the job will be permanently rejected so it never resurfaces.`)) return;
        setDeleteBusy(true);
        try {
            await api.permanentlyRejectPackage(slug);
            if (activeSlug === slug) setActiveSlug(null);
            await fetchPackages();
        } catch (e: any) {
            console.error(e);
        } finally {
            setDeleteBusy(false);
        }
    };

    const handleBulkDead = async () => {
        const slugs = [...selectedSlugs].filter((slug) => {
            const item = visibleData.find((entry) => entry.slug === slug);
            return item && !item.applied;
        });
        if (!slugs.length) return;
        if (!confirm(`Mark ${slugs.length} job(s) as dead? Packages will be deleted and the jobs will be permanently rejected so they never resurface.`)) return;
        setDeleteBusy(true);
        try {
            await Promise.allSettled(slugs.map((slug) => api.permanentlyRejectPackage(slug)));
            setSelectedSlugs(new Set());
            setActiveSlug(null);
            await fetchPackages();
        } finally {
            setDeleteBusy(false);
        }
    };

    const handleMarkApplied = async () => {
        if (!activeSlug) return;
        setApplyBusy(true);
        setApplyError('');
        try {
            const payload = {
                application_url: applyUrl || null,
                applied_at: applyAt ? new Date(applyAt).toISOString() : null,
                follow_up_at: applyFollowUpAt ? new Date(applyFollowUpAt).toISOString() : null,
                notes: applyNotes || null,
            };
            await api.applyPackage(activeSlug, payload);
            await fetchPackages();
            await loadDetail(activeSlug);
        } catch (e: any) {
            setApplyError(e.response?.data?.error || 'Failed to save applied snapshot');
        } finally {
            setApplyBusy(false);
        }
    };

    const filteredData = data.filter((item) => {
        if (applyFilter === 'applied') return Boolean(item.applied);
        if (applyFilter === 'unapplied') return !item.applied;
        return true;
    }).filter((item) => timelineMatches(item, {
        mode: timelineMode,
        unit: timelineUnit,
        newerThanValue: timelineNewerThanValue,
        betweenMinValue: timelineBetweenMinValue,
        betweenMaxValue: timelineBetweenMaxValue,
    }));
    const groupedFilteredData = groupPackages(filteredData)
        .map((group) => {
            let items = group.items;
            if (runFilter === 'recent_reruns') items = items.filter((item) => isTimestampedRerunSlug(item.slug));
            if (runFilter === 'latest_only') items = items.slice(0, 1);
            if (runFilter === 'previous_only') items = items.slice(1);
            if (runFilter === 'with_history') items = group.items.length > 1 ? items : [];
            if (runFilter === 'returned') items = items.filter((item) => item.decision && item.decision !== 'qa_approved' && !item.applied);
            return { ...group, items };
        })
        .filter((group) => group.items.length > 0);
    const visibleData = groupedFilteredData.flatMap((group) => group.items);
    const selectedVisibleCount = visibleData.filter((item) => selectedSlugs.has(item.slug)).length;

    const runFilterOptions: Array<{ value: RunFilter; label: string }> = [
        { value: 'all', label: 'All Runs' },
        { value: 'recent_reruns', label: 'Recent Reruns' },
        { value: 'latest_only', label: 'Latest Only' },
        { value: 'previous_only', label: 'Previous Only' },
        { value: 'with_history', label: 'With History' },
        { value: 'returned', label: 'Returned' },
    ];
    const timelineSummary = describeTimelineFilter(
        timelineMode,
        timelineUnit,
        timelineNewerThanValue,
        timelineBetweenMinValue,
        timelineBetweenMaxValue,
    );


    useEffect(() => {
        if (activeSlug !== null && !visibleData.some((item) => item.slug === activeSlug)) {
            setActiveSlug(null);
        }
    }, [visibleData, activeSlug]);

    useEffect(() => {
        if (groupedFilteredData.length === 0) {
            if (carouselIndex !== 0) setCarouselIndex(0);
            return;
        }
        if (carouselIndex >= groupedFilteredData.length) {
            setCarouselIndex(Math.max(0, groupedFilteredData.length - 1));
        }
    }, [groupedFilteredData.length, carouselIndex]);

    const activePkg = visibleData.find(p => p.slug === activeSlug) || data.find(p => p.slug === activeSlug);
    const resumePdfKey = Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Resume.pdf'));
    const coverPdfKey = Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Cover_Letter.pdf'));
    const pdfKey = packageDoc === 'resume'
        ? Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Resume.pdf'))
        : Object.keys(activePkg?.artifacts || {}).find(k => k.endsWith('Cover_Letter.pdf'));
    const currentPdfUrl = activeSlug && pdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(pdfKey)}?v=${previewBuster[packageDoc]}`
        : '';
    const resumePdfUrl = activeSlug && resumePdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(resumePdfKey)}?v=${previewBuster.resume}`
        : '';
    const coverPdfUrl = activeSlug && coverPdfKey
        ? `/api/tailoring/runs/${encodeURIComponent(activeSlug)}/artifact/${encodeURIComponent(coverPdfKey)}?v=${previewBuster.cover}`
        : '';
    const zipDownloadUrl = activeSlug && (resumePdfUrl || coverPdfUrl)
        ? `/api/packages/${encodeURIComponent(activeSlug)}/download.zip`
        : '';
    const strategy = pkgDetail?.resume_strategy;
    const coverStrategy = pkgDetail?.cover_strategy;
    const analysis = pkgDetail?.analysis;
    const appliedSummary = pkgDetail?.summary?.applied;
    const manualEntrySections = useMemo(() => buildManualEntrySections(resumeTex), [resumeTex]);
    const fullResumeEntry = manualEntrySections.find((section) => section.title === 'Full Resume')?.items[0]?.value || '';
    const coverLetterManualEntry = useMemo(() => buildCoverLetterManualEntrySection(coverTex), [coverTex]);
    const fullCoverLetterEntry = coverLetterManualEntry?.items[0]?.value || '';

    if (loading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <div className="spinner" />
            </div>
        );
    }

    if (data.length === 0) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 'calc(100vh - 56px)', flexDirection: 'column', gap: '12px' }}>
                <span style={{ fontSize: '1.6rem', opacity: 0.2 }}>&#9998;</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.82rem', color: 'var(--text-secondary)' }}>No document packages generated yet.</span>
            </div>
        );
    }

    // Empty state is rendered inside the carousel itself; no separate early return needed.

    return (
        <div style={{ display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden', width: '100%' }}>

            {!activeSlug ? (
            <div style={{ flex: 1, minWidth: 0, display: 'flex', position: 'relative', overflow: 'hidden' }}>
            <PackageDossierCarousel
                groups={groupedFilteredData}
                activeIndex={carouselIndex}
                setActiveIndex={setCarouselIndex}
                activeRunBySlug={activeRunBySlug}
                setActiveRunBySlug={setActiveRunBySlug}
                selectedSlugs={selectedSlugs}
                onToggleSelect={(slug) => {
                    setSelectedSlugs((prev) => {
                        const next = new Set(prev);
                        if (next.has(slug)) next.delete(slug); else next.add(slug);
                        return next;
                    });
                }}
                onOpen={(slug) => setActiveSlug(slug)}
                onRequeue={handleRequeuePackage}
                onDead={handleDeadPackage}
                eyebrow={`Tailored Packages · ${visibleData.length} run${visibleData.length === 1 ? '' : 's'} across ${groupedFilteredData.length} job${groupedFilteredData.length === 1 ? '' : 's'}`}
                headerRight={
                    <>
                        {([
                            ['all', 'All'],
                            ['unapplied', 'Unapplied'],
                            ['applied', 'Applied'],
                        ] as const).map(([value, label]) => (
                            <button
                                key={value}
                                type="button"
                                className={`dossier-pill ${applyFilter === value ? 'is-on' : ''}`}
                                onClick={() => setApplyFilter(value)}
                            >
                                {label}
                            </button>
                        ))}
                        <button
                            type="button"
                            className={`dossier-pill ${filtersOpen ? 'is-on' : ''}`}
                            onClick={() => setFiltersOpen((v) => !v)}
                            title="Advanced filters"
                        >
                            <SlidersHorizontal size={12} /> Filters
                        </button>
                    </>
                }
                bulkBar={selectedVisibleCount > 0 ? (
                    <div className="dossier-bulk-bar">
                        <span className="count"><b>{selectedVisibleCount}</b>selected</span>
                        <button
                            type="button"
                            className="dossier-btn ghost"
                            disabled={deleteBusy}
                            onClick={handleBulkRequeue}
                        >
                            <RotateCcw size={14} /> {deleteBusy ? 'Re-queuing…' : 'Re-queue'}
                        </button>
                        <button
                            type="button"
                            className="dossier-btn ghost"
                            disabled={bulkBusy}
                            onClick={async () => {
                                const selected = visibleData.filter(d => selectedSlugs.has(d.slug) && d.meta?.job_id && !d.applied);
                                const jobIds = selected.map(d => d.meta.job_id);
                                if (!jobIds.length) return;
                                if (!confirm(`Return ${jobIds.length} job(s) to QA? Output files are preserved.`)) return;
                                setBulkBusy(true);
                                try {
                                    await api.rollbackToQA(jobIds);
                                    setSelectedSlugs(new Set());
                                    await fetchPackages();
                                } catch { /* noop */ }
                                finally { setBulkBusy(false); }
                            }}
                        >
                            Send Back to QA
                        </button>
                        <button
                            type="button"
                            className="dossier-btn danger"
                            disabled={deleteBusy}
                            onClick={handleBulkDead}
                        >
                            <Skull size={14} /> {deleteBusy ? 'Deleting…' : 'Dead'}
                        </button>
                        <button
                            type="button"
                            className="dossier-iconbtn"
                            title="Clear selection"
                            onClick={() => setSelectedSlugs(new Set())}
                        >
                            <X size={14} />
                        </button>
                    </div>
                ) : null}
            />
            {filtersOpen && (
                <div
                    onClick={() => setFiltersOpen(false)}
                    style={{
                        position: 'absolute', inset: 0, zIndex: 30,
                        background: 'rgba(6,8,13,0.4)', backdropFilter: 'blur(4px)',
                    }}
                >
                    <div
                        onClick={(e) => e.stopPropagation()}
                        style={{
                            position: 'absolute', top: 92, right: 40,
                            width: 380, maxWidth: 'calc(100vw - 80px)',
                            background: 'rgba(15,19,27,0.96)',
                            border: '1px solid rgba(255,255,255,0.14)',
                            borderRadius: 14,
                            padding: '18px 18px 16px',
                            boxShadow: '0 30px 60px -10px rgba(0,0,0,.6)',
                            fontFamily: 'Manrope, system-ui, sans-serif',
                            color: '#ecf1f8',
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                            <div style={{
                                fontFamily: "'IBM Plex Mono', monospace",
                                fontSize: '.62rem', letterSpacing: '.28em',
                                textTransform: 'uppercase', color: '#aab4c4',
                            }}>
                                Run Filters
                            </div>
                            <button
                                type="button"
                                onClick={() => setFiltersOpen(false)}
                                style={{
                                    background: 'transparent', border: 'none', color: '#aab4c4', cursor: 'pointer',
                                    padding: 4, display: 'inline-flex', alignItems: 'center',
                                }}
                            >
                                <X size={14} />
                            </button>
                        </div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
                            {runFilterOptions.map(({ value, label }) => (
                                <button
                                    key={value}
                                    type="button"
                                    onClick={() => setRunFilter(value)}
                                    style={{
                                        padding: '6px 12px', borderRadius: 999,
                                        fontFamily: "'IBM Plex Mono', monospace",
                                        fontSize: '.62rem', letterSpacing: '.12em', textTransform: 'uppercase',
                                        border: '1px solid rgba(255,255,255,.14)',
                                        background: runFilter === value ? 'linear-gradient(180deg, #f0e3c8 0%, #d8c79b 100%)' : 'rgba(255,255,255,.02)',
                                        color: runFilter === value ? '#0b0f17' : '#aab4c4',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                        <TimelineControls
                            mode={timelineMode} setMode={setTimelineMode}
                            unit={timelineUnit} setUnit={setTimelineUnit}
                            newerThanValue={timelineNewerThanValue} setNewerThanValue={setTimelineNewerThanValue}
                            betweenMinValue={timelineBetweenMinValue} setBetweenMinValue={setTimelineBetweenMinValue}
                            betweenMaxValue={timelineBetweenMaxValue} setBetweenMaxValue={setTimelineBetweenMaxValue}
                            summary={timelineSummary}
                        />
                    </div>
                </div>
            )}
            </div>
            ) : (
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--surface)' }}>
                <div style={{ padding: '12px 24px', borderBottom: '1px solid var(--border)', background: 'var(--bg)', display: 'flex', alignItems: 'center' }}>
                    <button onClick={() => setActiveSlug(null)} className="btn btn-secondary btn-sm" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px' }}>
                        <span style={{ fontSize: '1.2em', lineHeight: 1, display: 'inline-block' }}>&#8592;</span> <span style={{ fontWeight: 600 }}>Back to Packages</span>
                    </button>
                </div>

                {filteredData.length === 0 ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, fontFamily: 'var(--font-mono)', fontSize: '.82rem', color: 'var(--text-secondary)' }}>
                        No packages match the current filter.
                    </div>
                ) : !pkgDetail ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
                        <div className="spinner" />
                    </div>
                ) : (
                    <>
                        <DetailContextSection
                            title={pkgDetail.job_context?.title || 'Untitled'}
                            companyName={pkgDetail.summary?.meta?.company_name || pkgDetail.summary?.meta?.company}
                            jobUrl={pkgDetail.job_context?.url}
                            status={pkgDetail.summary?.status}
                            badges={(
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                    {appliedSummary && (
                                        <a
                                            className="btn btn-ghost btn-sm"
                                            href={`/pipeline/applied?application_id=${encodeURIComponent(String(appliedSummary.id))}`}
                                            style={{ fontSize: '.68rem', background: 'rgba(75,142,240,.12)', color: 'var(--accent)' }}
                                        >
                                            View Applied
                                        </a>
                                    )}
                                    {!appliedSummary && (
                                        <button
                                            className="btn btn-primary btn-sm"
                                            style={{ fontSize: '.68rem', fontWeight: 600, padding: '0 16px' }}
                                            onClick={() => setApplyFormOpen((open) => !open)}
                                        >
                                            Mark Applied
                                        </button>
                                    )}
                                    {!appliedSummary && activeSlug && (
                                        <button
                                            className="btn btn-ghost btn-sm"
                                            style={{ fontSize: '.68rem', color: 'var(--red)', fontWeight: 600, border: '1px solid rgba(217,79,79,.2)' }}
                                            disabled={deleteBusy}
                                            onClick={() => handleDeadPackage(activeSlug)}
                                        >
                                            Dead
                                        </button>
                                    )}

                                    {activeSlug && (
                                        <div style={{ position: 'relative' }} onBlur={(e) => {
                                            if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                                                setMoreOptionsOpen(false);
                                            }
                                        }}>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                style={{ fontSize: '.68rem', display: 'flex', alignItems: 'center', gap: '4px', border: '1px solid var(--border)' }}
                                                onClick={() => setMoreOptionsOpen(!moreOptionsOpen)}
                                            >
                                                More Options <ChevronDown size={12} />
                                            </button>
                                            
                                            {moreOptionsOpen && (
                                                <div style={{
                                                    position: 'absolute', top: '100%', right: 0, marginTop: '6px',
                                                    background: 'var(--surface)', border: '1px solid var(--border)',
                                                    borderRadius: '8px', padding: '6px', display: 'flex', flexDirection: 'column',
                                                    gap: '2px', zIndex: 100, minWidth: '200px',
                                                    boxShadow: '0 8px 24px rgba(0,0,0,0.3)'
                                                }}>
                                                    <a
                                                        className="btn btn-ghost btn-sm"
                                                        style={{ fontSize: '.68rem', pointerEvents: resumePdfUrl ? 'auto' : 'none', opacity: resumePdfUrl ? 1 : 0.45, justifyContent: 'flex-start' }}
                                                        href={resumePdfUrl || undefined}
                                                        download={safePdfName(pkgDetail.summary?.meta?.company_name || pkgDetail.summary?.meta?.company, pkgDetail.summary?.meta?.job_title || pkgDetail.summary?.meta?.title || pkgDetail.job_context?.title, activeSlug || 'document', 'resume')}
                                                    >
                                                        Download Resume PDF
                                                    </a>
                                                    <a
                                                        className="btn btn-ghost btn-sm"
                                                        style={{ fontSize: '.68rem', pointerEvents: coverPdfUrl ? 'auto' : 'none', opacity: coverPdfUrl ? 1 : 0.45, justifyContent: 'flex-start' }}
                                                        href={coverPdfUrl || undefined}
                                                        download={safePdfName(pkgDetail.summary?.meta?.company_name || pkgDetail.summary?.meta?.company, pkgDetail.summary?.meta?.job_title || pkgDetail.summary?.meta?.title || pkgDetail.job_context?.title, activeSlug || 'document', 'cover')}
                                                    >
                                                        Download Cover PDF
                                                    </a>
                                                    <a
                                                        className="btn btn-ghost btn-sm"
                                                        style={{ fontSize: '.68rem', pointerEvents: zipDownloadUrl ? 'auto' : 'none', opacity: zipDownloadUrl ? 1 : 0.45, justifyContent: 'flex-start' }}
                                                        href={zipDownloadUrl || undefined}
                                                        download={`${activeSlug || 'package'}.zip`}
                                                    >
                                                        Download ZIP
                                                    </a>
                                                    <div style={{ height: '1px', background: 'var(--border)', margin: '4px 0' }} />
                                                    <button
                                                        className="btn btn-ghost btn-sm"
                                                        style={{ fontSize: '.68rem', justifyContent: 'flex-start' }}
                                                        disabled={regenerateBusy}
                                                        onClick={handleRegenerateCover}
                                                    >
                                                        {regenerateBusy ? 'Regenerating Cover...' : 'Regenerate Cover'}
                                                    </button>
                                                    {!appliedSummary && activeSlug && (
                                                        <button
                                                            className="btn btn-ghost btn-sm"
                                                            style={{ fontSize: '.68rem', color: 'var(--blue, #5b9fd4)', justifyContent: 'flex-start' }}
                                                            disabled={deleteBusy}
                                                            onClick={() => handleRequeuePackage(activeSlug)}
                                                        >
                                                            Re-queue for Tailoring
                                                        </button>
                                                    )}
                                                    {!appliedSummary && pkgDetail?.summary?.meta?.job_id && (
                                                        <button
                                                            className="btn btn-ghost btn-sm"
                                                            style={{ fontSize: '.68rem', color: 'var(--amber, #d1a23b)', justifyContent: 'flex-start' }}
                                                            onClick={async () => {
                                                                const jobId = pkgDetail.summary.meta.job_id;
                                                                if (!confirm('Return this job to QA? Tailoring output files are preserved but the job will re-enter triage.')) return;
                                                                try {
                                                                    await api.rollbackToQA([jobId]);
                                                                    await fetchPackages();
                                                                } catch { }
                                                            }}
                                                        >
                                                            Send Back to QA
                                                        </button>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                            contextTab="overview"
                            onContextTabChange={() => {}}
                            analysis={analysis}
                            resumeStrategy={strategy}
                            coverStrategy={coverStrategy}
                            jobContext={pkgDetail.job_context}
                            emptyNote="No analysis or strategy data available for this package."
                            showTabsAndBody={false}
                        />

                        {applyFormOpen && !appliedSummary && (
                            <div style={{
                                borderBottom: '1px solid var(--border)', background: 'var(--surface-2)',
                                padding: '12px 20px', display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '12px',
                            }}>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Application URL</span>
                                    <input
                                        value={applyUrl}
                                        onChange={(e) => setApplyUrl(e.target.value)}
                                        style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}
                                    />
                                </label>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Applied At</span>
                                    <input
                                        type="datetime-local"
                                        value={applyAt}
                                        onChange={(e) => setApplyAt(e.target.value)}
                                        style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}
                                    />
                                </label>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Follow Up</span>
                                    <input
                                        type="datetime-local"
                                        value={applyFollowUpAt}
                                        onChange={(e) => setApplyFollowUpAt(e.target.value)}
                                        style={{ borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px' }}
                                    />
                                </label>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', gridColumn: '1 / -1' }}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Notes</span>
                                    <textarea
                                        value={applyNotes}
                                        onChange={(e) => setApplyNotes(e.target.value)}
                                        style={{
                                            minHeight: '74px', resize: 'vertical', borderRadius: '6px', border: '1px solid var(--border)',
                                            background: 'var(--surface)', color: 'var(--text)', padding: '10px 12px',
                                        }}
                                    />
                                </label>
                                <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <button className="btn btn-primary btn-sm" onClick={handleMarkApplied} disabled={applyBusy}>
                                        {applyBusy ? 'Saving Snapshot...' : 'Save Applied Snapshot'}
                                    </button>
                                    <button className="btn btn-ghost btn-sm" onClick={() => setApplyFormOpen(false)} disabled={applyBusy}>
                                        Cancel
                                    </button>
                                    {applyError && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.72rem', color: 'var(--red)' }}>{applyError}</span>}
                                </div>
                            </div>
                        )}

                        {/* ── Main tab bar ── */}
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 20px',
                            borderBottom: '1px solid var(--border)', background: 'var(--surface)', flexShrink: 0,
                        }}>
                            {([
                                { id: 'briefing', label: 'Briefing' },
                                { id: 'strategy', label: 'Strategy' },
                                { id: 'documents', label: 'Documents' },
                                { id: 'jd', label: 'Full JD' },
                                { id: 'diff', label: 'Diff' },
                                { id: 'editor', label: 'Editor' }
                            ] as const).map((tab) => (
                                <button
                                    key={tab.id}
                                    className="btn btn-ghost"
                                    onClick={() => setMainTab(tab.id as MainTab)}
                                    style={{
                                        fontSize: '.72rem', padding: '6px 12px',
                                        color: mainTab === tab.id ? 'var(--accent)' : 'var(--text-secondary)',
                                        borderBottom: mainTab === tab.id ? '2px solid var(--accent)' : '2px solid transparent',
                                        borderRadius: '0',
                                        background: 'transparent',
                                        fontWeight: mainTab === tab.id ? 600 : 400
                                    }}
                                >
                                    {tab.label}
                                </button>
                            ))}
                            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <button
                                    className="btn btn-ghost btn-sm"
                                    style={{ fontSize: '.68rem', display: 'flex', alignItems: 'center', gap: '5px' }}
                                    onClick={() => {
                                        setCopiedChunkIndex(null);
                                        setCopiedAllChunks(false);
                                        setResumeChunksOpen(true);
                                    }}
                                    disabled={manualEntrySections.length === 0 && !coverLetterManualEntry}
                                    title={manualEntrySections.length > 0 || coverLetterManualEntry ? 'Open manual-entry resume and cover-letter copy fields' : 'Resume and cover-letter text unavailable'}
                                >
                                    <Scissors size={12} /> Resume Fields
                                </button>
                                {mainTab === 'editor' && (
                                    <select
                                        value={packageDoc}
                                        onChange={(e) => setPackageDoc(e.target.value as 'resume' | 'cover')}
                                        style={{
                                            padding: '3px 8px', borderRadius: '2px', fontSize: '.72rem',
                                            fontFamily: 'var(--font-mono)',
                                            border: '1px solid var(--border-bright)', background: 'var(--surface-3)',
                                            color: 'var(--text)', outline: 'none',
                                        }}
                                    >
                                        <option value="resume">Resume</option>
                                        <option value="cover">Cover Letter</option>
                                    </select>
                                )}

                                {mainTab === 'diff' && (
                                    <button
                                        className="btn btn-ghost btn-sm"
                                        style={{ fontSize: '.68rem' }}
                                        onClick={() => {
                                            setDiffError('');
                                            setDiffBuster({ resume: Date.now(), cover: Date.now() });
                                        }}
                                    >
                                        Refresh
                                    </button>
                                )}
                                {mainTab === 'editor' && (
                                    <>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', color: 'var(--text-secondary)' }}>{saveStatus}</span>
                                        <button className="btn btn-primary btn-sm" style={{ fontSize: '.68rem' }} onClick={handleCompile}>Compile</button>
                                    </>
                                )}
                            </div>
                        </div>

                        {regenerateMessage && (
                            <div style={{
                                padding: '8px 20px',
                                borderBottom: '1px solid var(--border)',
                                background: 'var(--surface)',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '.7rem',
                                color: regenerateMessage === 'Cover letter regenerated' ? 'var(--green)' : 'var(--red)',
                            }}>
                                {regenerateMessage}
                            </div>
                        )}

                        {/* ── Main content area + chat panel ── */}
                        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

                            {/* Document / briefing / strategy view */}
                            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', background: mainTab === 'diff' || mainTab === 'editor' || mainTab === 'documents' ? '#111720' : 'var(--surface-2)' }}>
                                {mainTab === 'briefing' && (
                                    <div style={{ height: '100%', overflowY: 'auto', padding: '14px 20px' }}>
                                        <BriefingPanel analysis={analysis} />
                                    </div>
                                )}

                                {mainTab === 'strategy' && (
                                    <div style={{ height: '100%', overflowY: 'auto', padding: '14px 20px' }}>
                                        <div style={{ display: 'flex', gap: '18px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                                            <StrategyCard label="Resume Strategy" data={strategy} />
                                            <StrategyCard label="Cover Strategy" data={coverStrategy} />
                                        </div>
                                    </div>
                                )}

                                {mainTab === 'documents' && (
                                    <DocumentsSideBySide
                                        resumePdfUrl={resumePdfUrl}
                                        coverPdfUrl={coverPdfUrl}
                                        resumeDownloadName={safePdfName(pkgDetail.summary?.meta?.company_name || pkgDetail.summary?.meta?.company, pkgDetail.summary?.meta?.job_title || pkgDetail.summary?.meta?.title || pkgDetail.job_context?.title, activeSlug || 'document', 'resume')}
                                        coverDownloadName={safePdfName(pkgDetail.summary?.meta?.company_name || pkgDetail.summary?.meta?.company, pkgDetail.summary?.meta?.job_title || pkgDetail.summary?.meta?.title || pkgDetail.job_context?.title, activeSlug || 'document', 'cover')}
                                    />
                                )}

                                {mainTab === 'jd' && (
                                    <div style={{ height: '100%', overflowY: 'auto', padding: '14px 20px' }}>
                                        <div style={{ marginBottom: '10px' }}>
                                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.62rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                                Full Job Description
                                            </div>
                                            <div style={{ fontSize: '.86rem', fontWeight: 500 }}>
                                                {pkgDetail.job_context?.title || pkgDetail.summary?.meta?.title || 'Untitled'}
                                            </div>
                                        </div>
                                        <div style={{
                                            maxHeight: '100%',
                                            overflowY: 'auto',
                                            borderRadius: 4,
                                            border: '1px solid var(--border)',
                                            background: 'var(--surface-3)',
                                            padding: '12px 14px',
                                        }}>
                                            <JdDisplay text={pkgDetail.job_context?.jd_text || pkgDetail.job_context?.snippet || ''} />
                                        </div>
                                    </div>
                                )}

                                {mainTab === 'diff' && (
                                    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                                        {diffError && (
                                            <div style={{ padding: '8px 20px', fontSize: '.74rem', color: 'var(--red)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                                                {diffError}
                                            </div>
                                        )}
                                        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0', overflow: 'hidden' }}>
                                            <iframe
                                                src={activeSlug ? `/api/packages/${encodeURIComponent(activeSlug)}/diff-preview/resume?v=${diffBuster.resume}#pagemode=none&view=Fit` : ''}
                                                style={{ width: '100%', height: '100%', border: 'none', background: '#525659' }}
                                                onError={() => setDiffError('Failed to load diff preview.')}
                                            />
                                            <iframe
                                                src={activeSlug ? `/api/packages/${encodeURIComponent(activeSlug)}/diff-preview/cover?v=${diffBuster.cover}#pagemode=none&view=Fit` : ''}
                                                style={{ width: '100%', height: '100%', border: 'none', background: '#525659' }}
                                                onError={() => setDiffError('Failed to load diff preview.')}
                                            />
                                        </div>
                                    </div>
                                )}

                                {mainTab === 'editor' && (
                                    <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', overflow: 'hidden' }}>
                                        {/* LaTeX Editor */}
                                        <div style={{ display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)', overflow: 'hidden' }}>
                                            <textarea
                                                value={packageDoc === 'resume' ? resumeTex : coverTex}
                                                onChange={e => handleLatexChange(e.target.value)}
                                                style={{
                                                    flex: 1, width: '100%', padding: '12px 14px',
                                                    fontFamily: 'var(--font-mono)', fontSize: '.76rem', lineHeight: 1.6,
                                                    resize: 'none', border: 'none', outline: 'none',
                                                    background: 'var(--surface-3)', color: 'var(--text)',
                                                }}
                                            />
                                            {compileError && (
                                                <div style={{
                                                    padding: '6px 14px', fontSize: '.72rem', color: 'var(--red)',
                                                    fontFamily: 'var(--font-mono)', background: 'rgba(217,79,79,.06)',
                                                    borderTop: '1px solid var(--border)', flexShrink: 0,
                                                }}>{compileError}</div>
                                            )}
                                        </div>

                                        {/* PDF Preview */}
                                        <iframe
                                            src={currentPdfUrl ? `${currentPdfUrl}#pagemode=none&view=Fit` : ''}
                                            style={{ width: '100%', height: '100%', border: 'none', background: '#525659' }}
                                        />
                                    </div>
                                )}
                            </div>

                            {/* ── Chat bottom panel ── */}
                            {activeSlug && (
                                <div style={{
                                    flexShrink: 0, borderTop: '1px solid var(--border)',
                                    display: 'flex', flexDirection: 'column',
                                    height: chatOpen ? '340px' : '32px',
                                    transition: 'height .15s ease',
                                    overflow: 'hidden',
                                }}>
                                    {/* Toggle bar */}
                                    <button
                                        onClick={() => setChatOpen(prev => !prev)}
                                        style={{
                                            display: 'flex', alignItems: 'center', gap: '6px',
                                            padding: '6px 14px', background: 'var(--surface-2)',
                                            border: 'none', borderBottom: chatOpen ? '1px solid var(--border)' : 'none',
                                            cursor: 'pointer', flexShrink: 0,
                                            fontFamily: 'var(--font-mono)', fontSize: '.68rem', fontWeight: 600,
                                            color: 'var(--text-secondary)', textTransform: 'uppercase',
                                            letterSpacing: '.08em', width: '100%', textAlign: 'left',
                                        }}
                                    >
                                        <MessageSquare size={12} />
                                        Chat Workspace
                                        <span style={{ fontSize: '.6rem', fontWeight: 400, opacity: 0.6 }}>
                                            ({packageDoc})
                                        </span>
                                        <span style={{ fontSize: '.58rem', fontWeight: 400, opacity: 0.55 }}>
                                            q&a + edits
                                        </span>
                                        <span style={{ marginLeft: 'auto' }}>
                                            {chatOpen ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
                                        </span>
                                    </button>

                                    {/* Chat content */}
                                    {chatOpen && (
                                        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                                            <PackageChatPanel
                                                slug={activeSlug}
                                                docFocus={packageDoc}
                                                onDocUpdated={async () => {
                                                    try {
                                                        await loadDetail(activeSlug!);
                                                    } catch {}
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {resumeChunksOpen && (
                            <div className="modal-overlay" onClick={() => setResumeChunksOpen(false)}>
                                <div
                                    className="modal"
                                    onClick={(e) => e.stopPropagation()}
                                    style={{ maxWidth: '980px', width: '92%', maxHeight: '86vh' }}
                                >
                                    <div className="modal-header">
                                        <div>
                                            <div style={{ fontWeight: 600, color: 'var(--text)' }}>Resume Manual-Entry Fields</div>
                                            <div style={{ fontSize: '.74rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                                Click any field to copy just that text. Dates, companies, titles, bullets, links, the full resume, and a plain-text cover letter are separated for manual application forms.
                                            </div>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                onClick={async () => {
                                                    const ok = await copyText(fullResumeEntry);
                                                    setCopiedAllChunks(ok);
                                                    setCopiedChunkIndex(null);
                                                }}
                                                disabled={!fullResumeEntry}
                                            >
                                                <Copy size={12} /> {copiedAllChunks ? 'Copied Full Resume' : 'Copy Full Resume'}
                                            </button>
                                            <button
                                                className="btn btn-ghost btn-sm"
                                                onClick={async () => {
                                                    const ok = await copyText(fullCoverLetterEntry);
                                                    setCopiedAllChunks(ok);
                                                    setCopiedChunkIndex(null);
                                                }}
                                                disabled={!fullCoverLetterEntry}
                                            >
                                                <Copy size={12} /> Copy Cover Letter
                                            </button>
                                            <button className="btn btn-ghost btn-sm" onClick={() => setResumeChunksOpen(false)}>Close</button>
                                        </div>
                                    </div>
                                    <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                        {manualEntrySections.length === 0 && !coverLetterManualEntry ? (
                                            <div style={{ color: 'var(--text-secondary)', fontSize: '.82rem' }}>No resume or cover-letter text available for manual-entry copy.</div>
                                        ) : (
                                            [...manualEntrySections, ...(coverLetterManualEntry ? [coverLetterManualEntry] : [])].map((section, sectionIndex) => (
                                                <div key={`${section.title}-${sectionIndex}`} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '.68rem', letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                                                        {section.title}
                                                    </div>
                                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '10px' }}>
                                                        {section.items.map((item, itemIndex) => {
                                                            const copyIndex = sectionIndex * 100 + itemIndex;
                                                            const longValue = item.value.length > 120 || item.value.includes('\n');
                                                            return (
                                                                <button
                                                                    key={`${item.label}-${itemIndex}`}
                                                                    onClick={async () => {
                                                                        const ok = await copyText(item.value);
                                                                        setCopiedChunkIndex(ok ? copyIndex : null);
                                                                        setCopiedAllChunks(false);
                                                                    }}
                                                                    style={{
                                                                        textAlign: 'left',
                                                                        width: '100%',
                                                                        border: '1px solid var(--border)',
                                                                        background: copiedChunkIndex === copyIndex ? 'rgba(75, 142, 240, 0.12)' : 'var(--surface-2)',
                                                                        color: 'var(--text)',
                                                                        borderRadius: '18px',
                                                                        padding: '12px 14px',
                                                                        cursor: 'pointer',
                                                                        display: 'flex',
                                                                        flexDirection: 'column',
                                                                        gap: '6px',
                                                                        gridColumn: longValue ? '1 / -1' : undefined,
                                                                        boxShadow: copiedChunkIndex === copyIndex ? '0 0 0 1px rgba(75, 142, 240, 0.35) inset' : 'none',
                                                                    }}
                                                                    title="Click to copy"
                                                                >
                                                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                                                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '.66rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>
                                                                            {item.label}
                                                                        </span>
                                                                        <span style={{ fontSize: '.68rem', color: copiedChunkIndex === copyIndex ? 'var(--accent)' : 'var(--text-secondary)' }}>
                                                                            {copiedChunkIndex === copyIndex ? 'Copied' : 'Copy'}
                                                                        </span>
                                                                    </div>
                                                                    <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.45, fontSize: item.compact ? '.82rem' : '.8rem' }}>
                                                                        {item.value}
                                                                    </div>
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
            )}
        </div>
    );
}
