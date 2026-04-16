export function fmt(num: number | undefined | null): string {
    if (num === undefined || num === null) return '—';
    return num.toLocaleString();
}

export function fmtBytes(bytes: number | undefined | null): string {
    if (!bytes && bytes !== 0) return '—';
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function timeAgo(isoDate: string | undefined | null): string {
    if (!isoDate) return 'Never';
    const d = new Date(isoDate);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

export function fmtDate(isoDate: string | undefined | null): string {
    if (!isoDate) return '—';
    const d = new Date(isoDate);
    return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    });
}

export function fmtDuration(seconds: number | undefined | null): string {
    if (seconds == null) return '—';
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    if (m === 0) return `${s}s`;
    return `${m}m ${s}s`;
}

export type SourceFilter = 'scrape' | 'manual_ingest' | 'mobile_ingest';

export function sourceMeta(source?: SourceFilter | string) {
    if (source === 'manual_ingest') return { label: 'Manual Ingest', color: 'var(--amber, #e0a030)', background: 'rgba(224, 160, 48, 0.12)', border: 'rgba(224, 160, 48, 0.35)' };
    if (source === 'mobile_ingest') return { label: 'Mobile Ingest', color: 'var(--cyan, #2ab8cc)', background: 'rgba(42, 184, 204, 0.12)', border: 'rgba(42, 184, 204, 0.35)' };
    return { label: 'Scrape', color: 'var(--accent)', background: 'rgba(75, 142, 240, 0.12)', border: 'rgba(75, 142, 240, 0.35)' };
}

export function normalizeSource(source?: string): SourceFilter {
    const value = (source || '').trim().toLowerCase();
    if (value === 'manual' || value === 'manual_ingest' || value === 'manual-ingest') return 'manual_ingest';
    if (value === 'mobile' || value === 'mobile_ingest' || value === 'mobile-ingest') return 'mobile_ingest';
    return 'scrape';
}

export function compactHost(url?: string) {
    if (!url) return '';
    try {
        return new URL(url).hostname.replace(/^www\./, '');
    } catch {
        return url.replace(/^https?:\/\//, '').split('/')[0] || url;
    }
}

export function toLocalInputValue(isoDate?: string | null) {
    const date = isoDate ? new Date(isoDate) : new Date();
    const offsetMs = date.getTimezoneOffset() * 60_000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export async function copyText(text: string): Promise<boolean> {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch {
            // Fall through to legacy path.
        }
    }

    if (typeof document === 'undefined') return false;

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-9999px';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    try {
        return document.execCommand('copy');
    } catch {
        return false;
    } finally {
        document.body.removeChild(textarea);
    }
}
