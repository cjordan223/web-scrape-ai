import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpen,
  Layers,
  Target,
  Building2,
  Tag,
  Hash,
  FileText,
  Sparkles,
  Filter,
  ChevronDown,
  ChevronRight,
  AlignLeft,
  Cpu,
  Wrench,
  Database,
  Cloud,
  ShieldCheck,
  Library,
  Compass,
  Quote,
} from 'lucide-react';
import { api } from '../../../api';

type Section = {
  body: string;
  chars: number;
  tags?: string[];
  exists: boolean;
  path?: string;
};

type Vignette = {
  name: string;
  path: string;
  body: string;
  chars: number;
  tags: string[];
  company_types: string[];
  skill_categories: string[];
  keywords: string[];
};

type CoreSkill = { name: string; skills: string[] };

type Stage = {
  stage: string;
  doc_type: string;
  budget_chars: number;
  diverse: boolean;
};

type Inventory = {
  candidate_profile: {
    name?: string;
    target_roles?: string[];
    positioning_summary?: string;
  };
  sections: Record<string, Section>;
  vignettes: Vignette[];
  core_skills: CoreSkill[];
  skill_buckets: Record<string, string[]>;
  category_to_vignettes: Record<string, string[]>;
  stages: Stage[];
  stats: {
    vignette_count: number;
    total_chars: number;
    avg_chars: number;
    unique_tags: number;
    unique_categories: number;
    unique_company_types: number;
    tag_counts: Record<string, number>;
    category_counts: Record<string, number>;
    company_counts: Record<string, number>;
    keyword_counts: Record<string, number>;
    core_skill_count: number;
    core_category_count: number;
  };
};

const SECTION_ORDER = ['identity', 'contributions', 'voice', 'evidence', 'motivation', 'interests'] as const;

const SECTION_META: Record<string, { label: string; tag: string; icon: typeof BookOpen; blurb: string }> = {
  identity: { label: 'Identity', tag: 'I.', icon: Compass, blurb: 'Injected at every stage. The fixed north star — who the writer is.' },
  contributions: { label: 'Contributions', tag: 'II.', icon: Target, blurb: 'Themes for analysis + resume strategy. The patterns behind the stories.' },
  voice: { label: 'Voice', tag: 'III.', icon: Quote, blurb: 'Cover-letter register: anti-patterns, tone, company-type adaptation.' },
  evidence: { label: 'Evidence', tag: 'IV.', icon: ShieldCheck, blurb: 'Compact proof points for cover strategy. Factual, role-agnostic.' },
  motivation: { label: 'Motivation', tag: 'V.', icon: Sparkles, blurb: 'Why this work matters — used in cover-letter framing.' },
  interests: { label: 'Interests', tag: 'VI.', icon: BookOpen, blurb: 'Adjacent curiosities that shape the voice at draft time.' },
};

const BUCKET_META: Record<string, { label: string; icon: typeof Cpu }> = {
  programming_languages: { label: 'Languages', icon: Cpu },
  databases: { label: 'Databases', icon: Database },
  frameworks_and_infrastructure: { label: 'Frameworks & Infrastructure', icon: Wrench },
  security_tooling: { label: 'Security Tooling', icon: ShieldCheck },
  devops_and_cloud: { label: 'DevOps & Cloud', icon: Cloud },
  ai_ml_research: { label: 'AI / ML Research', icon: Sparkles },
};

function formatVignetteName(name: string): string {
  return name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function firstSentence(body: string, limit = 180): string {
  const m = body.match(/[^.!?]+[.!?]/);
  const raw = (m ? m[0] : body).trim();
  return raw.length > limit ? raw.slice(0, limit - 1).trimEnd() + '…' : raw;
}

export default function PersonaInventoryView() {
  const [inv, setInv] = useState<Inventory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [openSection, setOpenSection] = useState<string | null>('identity');
  const [filterCategory, setFilterCategory] = useState<string | null>(null);
  const [filterCompany, setFilterCompany] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<'vignettes' | 'persona' | 'skills' | 'pipeline'>('vignettes');

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const data = await api.getPersonaInventory();
      setInv(data);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filteredVignettes = useMemo(() => {
    if (!inv) return [] as Vignette[];
    const q = search.trim().toLowerCase();
    return inv.vignettes.filter((v) => {
      if (filterCategory && !v.skill_categories.includes(filterCategory)) return false;
      if (filterCompany && !v.company_types.includes(filterCompany)) return false;
      if (q) {
        const hay = [v.name, v.body, ...v.tags, ...v.keywords, ...v.company_types, ...v.skill_categories].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [inv, filterCategory, filterCompany, search]);

  function toggle(name: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  if (loading) {
    return <div className="persona-shell"><div className="persona-empty">Loading dossier…</div></div>;
  }
  if (error || !inv) {
    return <div className="persona-shell"><div className="persona-empty">Error: {error || 'no data'}</div></div>;
  }

  const topCategories = Object.entries(inv.stats.category_counts).sort((a, b) => b[1] - a[1]);
  const topCompanies = Object.entries(inv.stats.company_counts).sort((a, b) => b[1] - a[1]);
  const topKeywords = Object.entries(inv.stats.keyword_counts).sort((a, b) => b[1] - a[1]).slice(0, 30);

  return (
    <>
      <style>{PERSONA_CSS}</style>
      <div className="persona-shell">
        {/* ── Header dossier ─────────────────────────────────── */}
        <header className="persona-hero">
          <div className="persona-hero-stamp">
            <span className="persona-hero-stamp-line">Dossier</span>
            <span className="persona-hero-stamp-line">Tailoring Persona</span>
            <span className="persona-hero-stamp-line">v5.0</span>
          </div>
          <div className="persona-hero-body">
            <div className="persona-hero-kicker">The Narrative Vault</div>
            <h1 className="persona-hero-title">
              {inv.candidate_profile.name || 'Candidate'}
              <span className="persona-hero-comma">,</span>
              <span className="persona-hero-title-sub"> rendered in parts.</span>
            </h1>
            <p className="persona-hero-lede">
              {inv.candidate_profile.positioning_summary ||
                'The persona store — vignettes, voice, evidence — injected into every tailoring pipeline.'}
            </p>
            <div className="persona-hero-roles">
              {(inv.candidate_profile.target_roles || []).slice(0, 7).map((r) => (
                <span key={r} className="persona-hero-role">{r}</span>
              ))}
              {(inv.candidate_profile.target_roles || []).length > 7 && (
                <span className="persona-hero-role muted">+{(inv.candidate_profile.target_roles || []).length - 7} more</span>
              )}
            </div>
          </div>
          <div className="persona-hero-stats">
            <StatTile label="Vignettes" value={inv.stats.vignette_count} icon={Library} />
            <StatTile label="Categories" value={inv.stats.unique_categories} icon={Layers} />
            <StatTile label="Company types" value={inv.stats.unique_company_types} icon={Building2} />
            <StatTile label="Avg chars" value={inv.stats.avg_chars.toLocaleString()} icon={AlignLeft} />
            <StatTile label="Core skills" value={inv.stats.core_skill_count} icon={Sparkles} />
          </div>
        </header>

        {/* ── Tabs ─────────────────────────────────────────────── */}
        <nav className="persona-tabs">
          {(
            [
              { id: 'vignettes', label: 'Vignettes', icon: Library },
              { id: 'persona', label: 'Persona Files', icon: BookOpen },
              { id: 'skills', label: 'Skills Inventory', icon: Layers },
              { id: 'pipeline', label: 'Stage Injection', icon: Target },
            ] as const
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`persona-tab ${tab === id ? 'active' : ''}`}
              onClick={() => setTab(id)}
            >
              <Icon size={14} />
              {label}
              <span className="persona-tab-count">
                {id === 'vignettes' && inv.vignettes.length}
                {id === 'persona' && SECTION_ORDER.length}
                {id === 'skills' && inv.stats.core_category_count}
                {id === 'pipeline' && inv.stages.length}
              </span>
            </button>
          ))}
        </nav>

        {/* ── VIGNETTES TAB ──────────────────────────────────── */}
        {tab === 'vignettes' && (
          <div className="persona-panel">
            <div className="persona-filters">
              <div className="persona-search">
                <Filter size={14} />
                <input
                  placeholder="Search body, tags, keywords…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>

              <div className="persona-filter-group">
                <span className="persona-filter-label">Skill category</span>
                <div className="persona-chips">
                  <button
                    className={`persona-chip ${filterCategory === null ? 'active' : ''}`}
                    onClick={() => setFilterCategory(null)}
                  >All</button>
                  {topCategories.map(([cat, count]) => (
                    <button
                      key={cat}
                      className={`persona-chip ${filterCategory === cat ? 'active' : ''}`}
                      onClick={() => setFilterCategory(filterCategory === cat ? null : cat)}
                    >
                      {cat}
                      <span className="persona-chip-count">{count}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="persona-filter-group">
                <span className="persona-filter-label">Company type</span>
                <div className="persona-chips">
                  <button
                    className={`persona-chip ${filterCompany === null ? 'active' : ''}`}
                    onClick={() => setFilterCompany(null)}
                  >All</button>
                  {topCompanies.map(([ct, count]) => (
                    <button
                      key={ct}
                      className={`persona-chip ${filterCompany === ct ? 'active' : ''}`}
                      onClick={() => setFilterCompany(filterCompany === ct ? null : ct)}
                    >
                      {ct}
                      <span className="persona-chip-count">{count}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="persona-filter-summary">
                Showing <strong>{filteredVignettes.length}</strong> / {inv.vignettes.length}
              </div>
            </div>

            <div className="persona-vig-grid">
              {filteredVignettes.map((v, idx) => {
                const open = expanded.has(v.name);
                return (
                  <article key={v.name} className={`persona-vig ${open ? 'open' : ''}`}>
                    <header className="persona-vig-head" onClick={() => toggle(v.name)}>
                      <div className="persona-vig-idx">
                        <span className="persona-vig-idx-no">{String(idx + 1).padStart(2, '0')}</span>
                        <span className="persona-vig-idx-total">/{inv.vignettes.length}</span>
                      </div>
                      <div className="persona-vig-title-wrap">
                        <div className="persona-vig-file">{v.path}</div>
                        <h3 className="persona-vig-title">{formatVignetteName(v.name)}</h3>
                        <p className="persona-vig-snip">{firstSentence(v.body)}</p>
                      </div>
                      <div className="persona-vig-meta">
                        <span className="persona-vig-chars">{v.chars.toLocaleString()} ch</span>
                        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </div>
                    </header>

                    <div className="persona-vig-chips">
                      {v.skill_categories.map((c) => (
                        <span key={c} className="mini-chip mini-chip-cat">
                          <Layers size={10} /> {c}
                        </span>
                      ))}
                      {v.company_types.map((c) => (
                        <span key={c} className="mini-chip mini-chip-co">
                          <Building2 size={10} /> {c}
                        </span>
                      ))}
                    </div>

                    {open && (
                      <div className="persona-vig-body">
                        <p>{v.body}</p>
                        <div className="persona-vig-footer">
                          <div className="persona-vig-kw">
                            <span className="persona-vig-kw-label"><Hash size={11} /> Keywords</span>
                            <div className="persona-vig-kw-list">
                              {v.keywords.map((k) => (<span key={k} className="kw">{k}</span>))}
                            </div>
                          </div>
                          {v.tags.length > 0 && (
                            <div className="persona-vig-kw">
                              <span className="persona-vig-kw-label"><Tag size={11} /> Tags</span>
                              <div className="persona-vig-kw-list">
                                {v.tags.map((t) => (<span key={t} className="kw tag">{t}</span>))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </div>
        )}

        {/* ── PERSONA FILES TAB ──────────────────────────────── */}
        {tab === 'persona' && (
          <div className="persona-panel">
            <div className="persona-files">
              <aside className="persona-files-nav">
                <div className="persona-files-nav-label">Files</div>
                {SECTION_ORDER.map((key) => {
                  const s = inv.sections[key];
                  const meta = SECTION_META[key];
                  const Icon = meta.icon;
                  const active = openSection === key;
                  return (
                    <button
                      key={key}
                      className={`persona-files-nav-item ${active ? 'active' : ''}`}
                      onClick={() => setOpenSection(key)}
                    >
                      <span className="persona-files-nav-tag">{meta.tag}</span>
                      <Icon size={14} />
                      <span className="persona-files-nav-name">{meta.label}</span>
                      <span className="persona-files-nav-chars">{s?.chars?.toLocaleString() || 0}</span>
                    </button>
                  );
                })}
              </aside>
              <section className="persona-files-body">
                {SECTION_ORDER.map((key) => {
                  if (openSection !== key) return null;
                  const s = inv.sections[key];
                  const meta = SECTION_META[key];
                  const Icon = meta.icon;
                  return (
                    <div key={key}>
                      <div className="persona-files-head">
                        <div className="persona-files-head-left">
                          <span className="persona-files-head-tag">{meta.tag}</span>
                          <Icon size={18} />
                          <h2>{meta.label}</h2>
                        </div>
                        <div className="persona-files-head-meta">
                          <code>{s?.path || `persona/${key}.md`}</code>
                          <span>{s?.chars?.toLocaleString() || 0} chars</span>
                        </div>
                      </div>
                      <p className="persona-files-blurb">{meta.blurb}</p>
                      <pre className="persona-files-content">{s?.body || '(not present)'}</pre>
                    </div>
                  );
                })}
              </section>
            </div>
          </div>
        )}

        {/* ── SKILLS INVENTORY TAB ───────────────────────────── */}
        {tab === 'skills' && (
          <div className="persona-panel">
            <div className="persona-skills-kicker">
              <FileText size={13} />
              Source of truth: <code>tailoring/skills.json</code>
              &nbsp;·&nbsp; injected into analyzer & writer so the LLM only claims what's real.
            </div>

            <section className="persona-skills-section">
              <h3 className="persona-section-title">
                <span className="persona-section-title-no">01</span>
                Core Skill Categories
                <span className="persona-section-title-sub">
                  — names must match vignette <code>skill_categories</code> frontmatter
                </span>
              </h3>
              <div className="persona-cores-grid">
                {inv.core_skills.map((cat, i) => {
                  const linked = inv.category_to_vignettes[cat.name] || [];
                  return (
                    <article key={cat.name} className="persona-core">
                      <header>
                        <span className="persona-core-no">{String(i + 1).padStart(2, '0')}</span>
                        <h4>{cat.name}</h4>
                      </header>
                      <div className="persona-core-skills">
                        {cat.skills.map((s) => (<span key={s} className="persona-core-skill">{s}</span>))}
                      </div>
                      <footer className="persona-core-links">
                        <span className="persona-core-links-label">
                          Linked vignettes ({linked.length})
                        </span>
                        <div>
                          {linked.length === 0 ? (
                            <span className="persona-core-empty">— no vignette scores this category —</span>
                          ) : (
                            linked.map((n) => (
                              <button
                                key={n}
                                className="persona-core-link"
                                onClick={() => { setTab('vignettes'); setFilterCategory(cat.name); setSearch(''); }}
                              >
                                {formatVignetteName(n)}
                              </button>
                            ))
                          )}
                        </div>
                      </footer>
                    </article>
                  );
                })}
              </div>
            </section>

            <section className="persona-skills-section">
              <h3 className="persona-section-title">
                <span className="persona-section-title-no">02</span>
                Flat Skill Buckets
                <span className="persona-section-title-sub">
                  — feed specific resume categories (fixed slots for languages/databases)
                </span>
              </h3>
              <div className="persona-buckets">
                {Object.entries(inv.skill_buckets).map(([key, items]) => {
                  const meta = BUCKET_META[key] || { label: key, icon: Wrench };
                  const Icon = meta.icon;
                  return (
                    <article key={key} className="persona-bucket">
                      <header>
                        <Icon size={14} />
                        <h5>{meta.label}</h5>
                        <span className="persona-bucket-count">{items.length}</span>
                      </header>
                      <div className="persona-bucket-items">
                        {items.map((i) => (<span key={i} className="persona-bucket-item">{i}</span>))}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>

            <section className="persona-skills-section">
              <h3 className="persona-section-title">
                <span className="persona-section-title-no">03</span>
                Keyword frequency across vignettes
                <span className="persona-section-title-sub">
                  — vignette scoring keys; higher count = broader anchor surface
                </span>
              </h3>
              <div className="persona-keyword-cloud">
                {topKeywords.map(([k, c]) => (
                  <span
                    key={k}
                    className="persona-kw-bubble"
                    style={{ fontSize: `${0.72 + Math.min(c, 5) * 0.1}rem`, opacity: 0.55 + Math.min(c, 5) * 0.09 }}
                  >
                    {k} <em>{c}</em>
                  </span>
                ))}
              </div>
            </section>
          </div>
        )}

        {/* ── STAGE INJECTION TAB ────────────────────────────── */}
        {tab === 'pipeline' && (
          <div className="persona-panel">
            <div className="persona-stage-intro">
              <p>
                The persona store assembles different bundles for each pipeline stage. Budgets are enforced
                per stage; <em>diverse</em> capping limits one vignette per <code>skill_category</code> so a single
                project cannot anchor a whole cover letter.
              </p>
            </div>
            <div className="persona-stages">
              {inv.stages.map((s) => (
                <article key={`${s.stage}-${s.doc_type}`} className="persona-stage">
                  <div className="persona-stage-head">
                    <span className={`persona-stage-doc persona-stage-doc-${s.doc_type}`}>{s.doc_type}</span>
                    <h4>{s.stage}</h4>
                    {s.diverse && <span className="persona-stage-diverse">diverse</span>}
                  </div>
                  <dl className="persona-stage-meta">
                    <div>
                      <dt>Budget</dt>
                      <dd>{s.budget_chars.toLocaleString()} chars</dd>
                    </div>
                    <div>
                      <dt>Includes</dt>
                      <dd>
                        {s.doc_type === 'cover'
                          ? 'identity + vignettes + voice + evidence + motivation'
                          : s.stage === 'strategy'
                          ? 'identity + vignettes + contributions'
                          : 'identity + vignettes'}
                      </dd>
                    </div>
                    <div>
                      <dt>Selection rule</dt>
                      <dd>
                        score = 3·category + 2·company_type + 1·keyword overlap
                        {s.diverse ? '; one vignette per primary category' : ''}
                      </dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
            <div className="persona-legend">
              <h4>Scoring cheat sheet</h4>
              <ul>
                <li>
                  <span className="legend-dot legend-dot-cat" />
                  <strong>Skill category match</strong> — vignette's <code>skill_categories</code> contains a category the analyzer pulled from the JD.
                </li>
                <li>
                  <span className="legend-dot legend-dot-co" />
                  <strong>Company type match</strong> — vignette's <code>company_types</code> includes the analyzer's inferred company archetype.
                </li>
                <li>
                  <span className="legend-dot legend-dot-kw" />
                  <strong>Keyword overlap</strong> — token overlap between vignette keywords and matched skills.
                </li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function StatTile({ label, value, icon: Icon }: { label: string; value: string | number; icon: typeof BookOpen }) {
  return (
    <div className="persona-stat">
      <Icon size={14} />
      <div>
        <div className="persona-stat-val">{value}</div>
        <div className="persona-stat-label">{label}</div>
      </div>
    </div>
  );
}

const PERSONA_CSS = `
.persona-shell {
  --ink: #f1ead9;
  --ink-dim: #a99b7d;
  --ink-mute: #6c6150;
  --parch: #161310;
  --parch-2: #1d1915;
  --parch-3: #25201a;
  --rule: rgba(224, 192, 120, 0.18);
  --rule-bright: rgba(224, 192, 120, 0.42);
  --ember: #d6a24a;
  --ember-2: #e7b965;
  --ember-soft: rgba(214, 162, 74, 0.14);
  --rust: #b85432;
  --moss: #6c895c;
  --font-display: 'Fraunces', 'Georgia', serif;
  --font-body: 'Manrope', 'Outfit', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', 'SF Mono', monospace;
  color: var(--ink);
  font-family: var(--font-body);
  padding: 28px 32px 80px;
  max-width: 1500px;
  margin: 0 auto;
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(214, 162, 74, 0.08), transparent 60%),
    radial-gradient(900px 400px at 110% 0%, rgba(184, 84, 50, 0.06), transparent 60%),
    linear-gradient(180deg, rgba(22, 19, 16, 0.0), rgba(22, 19, 16, 0.0));
  min-height: 100%;
}
.persona-shell code { font-family: var(--font-mono); font-size: 0.78em; color: var(--ember-2); background: var(--ember-soft); padding: 1px 6px; border-radius: 3px; }

.persona-empty { padding: 64px; text-align: center; color: var(--ink-dim); font-family: var(--font-display); font-style: italic; font-size: 1.1rem; }

/* ── Hero ────────────────────────── */
.persona-hero {
  display: grid;
  grid-template-columns: 110px 1fr auto;
  gap: 28px;
  padding: 28px 32px;
  background: linear-gradient(180deg, rgba(37, 32, 26, 0.85), rgba(22, 19, 16, 0.55));
  border: 1px solid var(--rule);
  border-radius: 4px;
  position: relative;
  overflow: hidden;
}
.persona-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    repeating-linear-gradient(0deg, transparent 0, transparent 31px, rgba(214, 162, 74, 0.04) 31px, rgba(214, 162, 74, 0.04) 32px);
  pointer-events: none;
}
.persona-hero-stamp {
  border: 1.5px solid var(--rule-bright);
  border-radius: 3px;
  padding: 10px 10px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  text-transform: uppercase;
  font-size: 0.62rem;
  letter-spacing: 0;
  color: var(--ember);
  background: rgba(214, 162, 74, 0.04);
  transform: rotate(-1.5deg);
  height: fit-content;
  align-self: center;
}
.persona-hero-stamp-line { display: block; }
.persona-hero-stamp-line:nth-child(2) { font-size: 0.68rem; letter-spacing: 0; }
.persona-hero-body { position: relative; }
.persona-hero-kicker {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: 0;
  text-transform: uppercase;
  color: var(--ember);
  margin-bottom: 12px;
}
.persona-hero-title {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 3rem;
  line-height: 1.02;
  letter-spacing: 0;
  font-variation-settings: 'opsz' 100, 'SOFT' 50;
}
.persona-hero-comma { color: var(--ember); }
.persona-hero-title-sub {
  font-style: italic;
  color: var(--ink-dim);
  font-weight: 300;
  font-size: 0.68em;
}
.persona-hero-lede {
  margin-top: 14px;
  max-width: 72ch;
  font-size: 0.98rem;
  line-height: 1.6;
  color: var(--ink);
  opacity: 0.9;
}
.persona-hero-roles { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 18px; }
.persona-hero-role {
  font-family: var(--font-mono);
  font-size: 0.68rem;
  padding: 3px 10px;
  border: 1px solid var(--rule);
  border-radius: 999px;
  color: var(--ink-dim);
  background: rgba(214, 162, 74, 0.03);
}
.persona-hero-role.muted { opacity: 0.5; }
.persona-hero-stats {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-self: center;
}
.persona-stat {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 170px;
  padding: 10px 14px;
  border-left: 2px solid var(--ember);
  background: rgba(214, 162, 74, 0.05);
  color: var(--ember);
}
.persona-stat > svg { flex-shrink: 0; }
.persona-stat-val {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 1.5rem;
  line-height: 1;
  color: var(--ink);
}
.persona-stat-label {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  letter-spacing: 0;
  text-transform: uppercase;
  color: var(--ink-dim);
  margin-top: 3px;
}

/* ── Tabs ────────────────────────── */
.persona-tabs {
  display: flex;
  gap: 0;
  margin-top: 24px;
  border-bottom: 1px solid var(--rule);
}
.persona-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 22px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--ink-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  letter-spacing: 0;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.2s;
}
.persona-tab:hover { color: var(--ink); }
.persona-tab.active { color: var(--ember); border-bottom-color: var(--ember); background: rgba(214, 162, 74, 0.04); }
.persona-tab-count {
  font-size: 0.7rem;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(214, 162, 74, 0.12);
  color: var(--ember-2);
  letter-spacing: 0;
}

.persona-panel { padding-top: 22px; }

/* ── Filters ─────────────────────── */
.persona-filters {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 18px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: rgba(22, 19, 16, 0.55);
  margin-bottom: 24px;
}
.persona-search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--rule);
}
.persona-search svg { color: var(--ember); }
.persona-search input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 0.95rem;
  outline: none;
}
.persona-search input::placeholder { color: var(--ink-mute); font-style: italic; }
.persona-filter-group { display: flex; gap: 12px; align-items: baseline; }
.persona-filter-label {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0;
  color: var(--ink-mute);
  width: 100px;
  flex-shrink: 0;
}
.persona-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.persona-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  background: transparent;
  border: 1px solid var(--rule);
  border-radius: 2px;
  color: var(--ink-dim);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  cursor: pointer;
  transition: all 0.15s;
}
.persona-chip:hover { color: var(--ink); border-color: var(--rule-bright); }
.persona-chip.active { background: var(--ember); color: var(--parch); border-color: var(--ember); font-weight: 600; }
.persona-chip-count { opacity: 0.6; font-size: 0.65rem; }
.persona-chip.active .persona-chip-count { color: var(--parch); opacity: 0.7; }
.persona-filter-summary {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--ink-mute);
  align-self: flex-end;
}
.persona-filter-summary strong { color: var(--ember); }

/* ── Vignette grid ───────────────── */
.persona-vig-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 16px;
}
.persona-vig {
  background: linear-gradient(180deg, rgba(37, 32, 26, 0.65), rgba(22, 19, 16, 0.4));
  border: 1px solid var(--rule);
  border-radius: 3px;
  overflow: hidden;
  transition: border-color 0.2s, transform 0.2s;
  position: relative;
}
.persona-vig::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--ember);
  opacity: 0;
  transition: opacity 0.2s;
}
.persona-vig:hover { border-color: var(--rule-bright); transform: translateY(-1px); }
.persona-vig:hover::before { opacity: 1; }
.persona-vig.open::before { opacity: 1; }
.persona-vig.open { border-color: var(--ember); }
.persona-vig-head {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 14px;
  padding: 14px 16px;
  cursor: pointer;
  align-items: flex-start;
}
.persona-vig-idx {
  font-family: var(--font-display);
  font-weight: 400;
  text-align: center;
  line-height: 1;
}
.persona-vig-idx-no {
  display: block;
  font-size: 1.7rem;
  color: var(--ember);
  font-variation-settings: 'opsz' 100;
}
.persona-vig-idx-total {
  font-family: var(--font-mono);
  font-size: 0.6rem;
  color: var(--ink-mute);
}
.persona-vig-file {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  color: var(--ink-mute);
  letter-spacing: 0;
  margin-bottom: 4px;
}
.persona-vig-title {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 1.2rem;
  line-height: 1.15;
  color: var(--ink);
  letter-spacing: 0;
  font-variation-settings: 'opsz' 48;
}
.persona-vig-snip {
  margin-top: 6px;
  font-size: 0.82rem;
  color: var(--ink-dim);
  line-height: 1.45;
  font-style: italic;
  font-family: var(--font-display);
}
.persona-vig-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-mute);
  font-family: var(--font-mono);
  font-size: 0.68rem;
}
.persona-vig-chars { color: var(--ember); }
.persona-vig-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  padding: 0 16px 12px;
}
.mini-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 2px;
  font-family: var(--font-mono);
  font-size: 0.62rem;
  letter-spacing: 0;
}
.mini-chip-cat { background: rgba(214, 162, 74, 0.14); color: var(--ember-2); }
.mini-chip-co { background: rgba(108, 137, 92, 0.18); color: #a3c191; }
.persona-vig-body {
  padding: 16px 20px 18px;
  border-top: 1px dashed var(--rule);
  background: rgba(0, 0, 0, 0.15);
}
.persona-vig-body > p {
  font-family: var(--font-display);
  font-size: 0.98rem;
  line-height: 1.7;
  color: var(--ink);
  font-weight: 400;
  letter-spacing: 0;
}
.persona-vig-body > p::first-letter {
  font-size: 2.8em;
  float: left;
  line-height: 0.85;
  margin: 0.05em 0.08em 0 0;
  color: var(--ember);
  font-weight: 500;
}
.persona-vig-footer { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.persona-vig-kw { display: flex; flex-direction: column; gap: 6px; }
.persona-vig-kw-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  text-transform: uppercase;
  color: var(--ink-mute);
  letter-spacing: 0;
}
.persona-vig-kw-list { display: flex; flex-wrap: wrap; gap: 4px; }
.kw {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  padding: 2px 7px;
  background: transparent;
  border: 1px solid var(--rule);
  border-radius: 1px;
  color: var(--ink-dim);
}
.kw.tag { border-style: dashed; color: var(--moss); }

/* ── Persona files ───────────────── */
.persona-files {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 28px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: rgba(22, 19, 16, 0.5);
  overflow: hidden;
}
.persona-files-nav { padding: 18px 0; border-right: 1px solid var(--rule); background: rgba(0,0,0,0.2); }
.persona-files-nav-label {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  letter-spacing: 0;
  text-transform: uppercase;
  color: var(--ink-mute);
  padding: 0 18px 12px;
  border-bottom: 1px solid var(--rule);
  margin-bottom: 10px;
}
.persona-files-nav-item {
  width: 100%;
  display: grid;
  grid-template-columns: 28px 16px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 10px 18px;
  background: transparent;
  border: none;
  border-left: 2px solid transparent;
  color: var(--ink-dim);
  font-family: var(--font-body);
  font-size: 0.9rem;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}
.persona-files-nav-item:hover { color: var(--ink); background: rgba(214, 162, 74, 0.04); }
.persona-files-nav-item.active { color: var(--ink); border-left-color: var(--ember); background: rgba(214, 162, 74, 0.08); }
.persona-files-nav-tag {
  font-family: var(--font-display);
  font-style: italic;
  color: var(--ember);
  font-size: 0.85rem;
}
.persona-files-nav-name { font-weight: 500; }
.persona-files-nav-chars {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  color: var(--ink-mute);
}

.persona-files-body { padding: 28px 32px 36px; }
.persona-files-head { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; flex-wrap: wrap; }
.persona-files-head-left { display: flex; align-items: center; gap: 10px; color: var(--ember); }
.persona-files-head h2 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 2rem;
  color: var(--ink);
  letter-spacing: 0;
}
.persona-files-head-tag {
  font-family: var(--font-display);
  font-style: italic;
  color: var(--ember);
  font-size: 1.2rem;
}
.persona-files-head-meta {
  display: flex;
  gap: 14px;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--ink-mute);
}
.persona-files-blurb {
  margin: 8px 0 22px;
  font-family: var(--font-display);
  font-style: italic;
  font-size: 1rem;
  color: var(--ink-dim);
  max-width: 70ch;
  line-height: 1.55;
  padding-left: 14px;
  border-left: 2px solid var(--ember);
}
.persona-files-content {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  line-height: 1.75;
  color: var(--ink);
  white-space: pre-wrap;
  background: rgba(0,0,0,0.35);
  padding: 22px 26px;
  border-radius: 2px;
  border: 1px solid var(--rule);
  overflow-x: auto;
  max-height: 70vh;
  overflow-y: auto;
}

/* ── Skills section ──────────────── */
.persona-skills-kicker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: var(--ember-soft);
  border-left: 2px solid var(--ember);
  color: var(--ink-dim);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  margin-bottom: 28px;
}
.persona-skills-section { margin-bottom: 44px; }
.persona-section-title {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 1.6rem;
  color: var(--ink);
  letter-spacing: 0;
  margin-bottom: 18px;
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.persona-section-title-no {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  color: var(--ember);
  letter-spacing: 0;
}
.persona-section-title-sub {
  font-family: var(--font-body);
  font-weight: 400;
  font-size: 0.82rem;
  color: var(--ink-mute);
  font-style: italic;
}

.persona-cores-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}
.persona-core {
  border: 1px solid var(--rule);
  padding: 16px;
  background: rgba(22, 19, 16, 0.5);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.persona-core header { display: flex; align-items: baseline; gap: 10px; }
.persona-core-no {
  font-family: var(--font-display);
  font-weight: 500;
  color: var(--ember);
  font-size: 1.3rem;
}
.persona-core h4 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 1.1rem;
  color: var(--ink);
  letter-spacing: 0;
}
.persona-core-skills { display: flex; flex-wrap: wrap; gap: 4px; }
.persona-core-skill {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  padding: 2px 7px;
  background: rgba(224, 192, 120, 0.04);
  border: 1px solid var(--rule);
  color: var(--ink);
  border-radius: 2px;
}
.persona-core-links {
  margin-top: auto;
  border-top: 1px dashed var(--rule);
  padding-top: 10px;
}
.persona-core-links-label {
  display: block;
  font-family: var(--font-mono);
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0;
  color: var(--ink-mute);
  margin-bottom: 5px;
}
.persona-core-links > div { display: flex; flex-wrap: wrap; gap: 4px; }
.persona-core-link {
  background: transparent;
  border: 1px solid var(--rule);
  color: var(--ember-2);
  font-family: var(--font-mono);
  font-size: 0.68rem;
  padding: 2px 7px;
  cursor: pointer;
  border-radius: 1px;
}
.persona-core-link:hover { background: var(--ember); color: var(--parch); border-color: var(--ember); }
.persona-core-empty { font-family: var(--font-display); font-style: italic; font-size: 0.78rem; color: var(--ink-mute); }

.persona-buckets {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.persona-bucket {
  border: 1px solid var(--rule);
  padding: 14px 16px;
  background: rgba(22, 19, 16, 0.35);
}
.persona-bucket header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; color: var(--ember); }
.persona-bucket h5 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 1rem;
  color: var(--ink);
  flex: 1;
}
.persona-bucket-count {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  background: var(--ember-soft);
  color: var(--ember);
  padding: 1px 7px;
  border-radius: 999px;
}
.persona-bucket-items { display: flex; flex-wrap: wrap; gap: 3px; }
.persona-bucket-item {
  font-family: var(--font-mono);
  font-size: 0.67rem;
  padding: 2px 6px;
  background: rgba(0,0,0,0.25);
  border: 1px solid var(--rule);
  color: var(--ink);
}

.persona-keyword-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  padding: 24px;
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--rule);
  line-height: 1.8;
}
.persona-kw-bubble {
  font-family: var(--font-mono);
  color: var(--ink);
  letter-spacing: 0;
}
.persona-kw-bubble em { color: var(--ember); font-style: normal; font-size: 0.7em; margin-left: 2px; }

/* ── Stage injection ─────────────── */
.persona-stage-intro {
  font-family: var(--font-display);
  font-size: 1rem;
  color: var(--ink-dim);
  line-height: 1.6;
  font-style: italic;
  padding: 16px 24px;
  border-left: 2px solid var(--ember);
  margin-bottom: 28px;
  max-width: 80ch;
}
.persona-stages {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}
.persona-stage {
  border: 1px solid var(--rule);
  padding: 18px 22px;
  background: rgba(22, 19, 16, 0.55);
  position: relative;
}
.persona-stage-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
.persona-stage-doc {
  font-family: var(--font-mono);
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0;
  padding: 2px 8px;
  border-radius: 2px;
}
.persona-stage-doc-cover { background: rgba(184, 84, 50, 0.15); color: #e08a6d; }
.persona-stage-doc-resume { background: rgba(108, 137, 92, 0.2); color: #a3c191; }
.persona-stage h4 {
  font-family: var(--font-display);
  font-weight: 500;
  color: var(--ink);
  font-size: 1.3rem;
  text-transform: capitalize;
}
.persona-stage-diverse {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  color: var(--ember);
  padding: 1px 6px;
  border: 1px solid var(--ember);
  border-radius: 1px;
  text-transform: uppercase;
  letter-spacing: 0;
}
.persona-stage-meta { display: flex; flex-direction: column; gap: 10px; }
.persona-stage-meta > div { display: grid; grid-template-columns: 90px 1fr; gap: 12px; align-items: baseline; }
.persona-stage-meta dt {
  font-family: var(--font-mono);
  font-size: 0.64rem;
  text-transform: uppercase;
  letter-spacing: 0;
  color: var(--ink-mute);
}
.persona-stage-meta dd {
  font-family: var(--font-body);
  font-size: 0.85rem;
  color: var(--ink);
  line-height: 1.5;
}

.persona-legend {
  margin-top: 36px;
  padding: 22px 26px;
  background: rgba(0,0,0,0.3);
  border: 1px dashed var(--rule);
}
.persona-legend h4 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 1.2rem;
  color: var(--ink);
  margin-bottom: 12px;
}
.persona-legend ul { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.persona-legend li {
  display: grid;
  grid-template-columns: 14px 1fr;
  gap: 10px;
  align-items: baseline;
  font-size: 0.88rem;
  color: var(--ink-dim);
  line-height: 1.5;
}
.persona-legend li strong { color: var(--ink); }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-top: 7px; }
.legend-dot-cat { background: var(--ember); }
.legend-dot-co { background: var(--moss); }
.legend-dot-kw { background: var(--rust); }

@media (max-width: 900px) {
  .persona-hero { grid-template-columns: 1fr; }
  .persona-hero-stamp { justify-self: start; }
  .persona-files { grid-template-columns: 1fr; }
  .persona-files-nav { border-right: none; border-bottom: 1px solid var(--rule); }
}
`;
