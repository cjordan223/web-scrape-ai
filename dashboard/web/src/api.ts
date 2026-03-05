import axios from 'axios';

// During development, proxy to the FastAPI backend running on port 8899.
// In production, the React app is served by the FastAPI backend, so relative paths work.
const API_BASE = import.meta.env.DEV ? 'http://localhost:8899/api' : '/api';

export const apiClient = axios.create({
    baseURL: API_BASE,
});

export const api = {
    getOverview: async () => {
        const { data } = await apiClient.get('/overview');
        return data;
    },

    getJobs: async (params: Record<string, any>) => {
        const { data } = await apiClient.get('/jobs', { params });
        return data;
    },

    getRejected: async (params: Record<string, any>) => {
        const { data } = await apiClient.get('/rejected', { params });
        return data;
    },

    getRejectedStats: async () => {
        const { data } = await apiClient.get('/rejected/stats');
        return data;
    },

    approveRejected: async (id: number) => {
        const { data } = await apiClient.post(`/rejected/${id}/approve`);
        return data;
    },

    getRuns: async (params?: Record<string, any>) => {
        const { data } = await apiClient.get('/runs', { params });
        return data; // returns { runs, total, page, pages, stats }
    },

    getRun: async (runId: string) => {
        const { data } = await apiClient.get(`/runs/${runId}`);
        return data;
    },

    getRunLogs: async (runId: string, lines: number = 200) => {
        const { data } = await apiClient.get(`/runs/${runId}/logs`, { params: { lines } });
        return data;
    },

    terminateRun: async (runId: string) => {
        const { data } = await apiClient.post(`/runs/${runId}/terminate`);
        return data;
    },

    getRunsControls: async () => {
        const { data } = await apiClient.get('/runtime-controls');
        return data;
    },

    updateRunsControls: async (payload: Record<string, any>) => {
        const { data } = await apiClient.post('/runtime-controls', payload);
        return data;
    },

    setScrapeEnabled: async (enabled: boolean) => {
        return api.updateRunsControls({ scrape_enabled: enabled });
    },

    setLlmEnabled: async (enabled: boolean) => {
        return api.updateRunsControls({ llm_enabled: enabled });
    },

    runScrapeNow: async (llm_enabled: boolean) => {
        const { data } = await apiClient.post('/scrape/run', { llm_enabled_override: llm_enabled });
        return data;
    },

    getScrapeRunnerStatus: async () => {
        const { data } = await apiClient.get('/scrape/runner/status');
        return data;
    },

    getJobDetail: async (id: number) => {
        const { data } = await apiClient.get(`/jobs/${id}`);
        return data;
    },

    getTailoring: async () => {
        const { data } = await apiClient.get('/tailoring/runs');
        return data.runs;
    },

    getTailoringDetail: async (slug: string) => {
        const { data } = await apiClient.get(`/tailoring/runs/${slug}/trace`);
        return data;
    },

    getTailoringJobDetail: async (id: number) => {
        const { data } = await apiClient.get(`/tailoring/jobs/${id}`);
        return data;
    },

    getTailoringRecentJobs: async () => {
        const { data } = await apiClient.get('/tailoring/jobs/recent');
        return data;
    },

    runTailoring: async (id: number, skip_analysis: boolean) => {
        const { data } = await apiClient.post(`/tailoring/run`, { job_id: id, skip_analysis });
        return data;
    },

    getTailoringRunnerStatus: async () => {
        const { data } = await apiClient.get('/tailoring/runner/status');
        return data;
    },

    stopTailoringRunner: async (payload?: { clear_queue?: boolean; wait_seconds?: number }) => {
        const { data } = await apiClient.post('/tailoring/runner/stop', payload || {});
        return data;
    },

    queueTailoring: async (jobs: { job_id: number; skip_analysis?: boolean }[]) => {
        const { data } = await apiClient.post('/tailoring/queue', { jobs });
        return data;
    },

    getTailoringQueue: async () => {
        const { data } = await apiClient.get('/tailoring/queue');
        return data;
    },

    clearTailoringQueue: async () => {
        const { data } = await apiClient.delete('/tailoring/queue');
        return data;
    },

    getPackages: async () => {
        const { data } = await apiClient.get('/packages');
        return data.items;
    },

    getPackageDetail: async (slug: string) => {
        const { data } = await apiClient.get(`/packages/${slug}`);
        return data;
    },

    savePackageLatex: async (slug: string, docType: 'resume' | 'cover', content: string) => {
        const { data } = await apiClient.post(`/packages/${slug}/latex/${docType}`, { content });
        return data;
    },

    compilePackageDoc: async (slug: string, docType: 'resume' | 'cover') => {
        const { data } = await apiClient.post(`/packages/${slug}/compile/${docType}`);
        return data;
    },

    getRunIds: async () => {
        const { data } = await apiClient.get('/runs', { params: { page: 1, per_page: 100 } });
        return (data.runs || []).map((r: any) => r.run_id);
    },

    getActiveRun: async () => {
        const { data } = await apiClient.get('/runs/active');
        return data;
    },

    getLlmStatus: async () => {
        const { data } = await apiClient.get('/llm/status');
        return data;
    },

    getLlmModels: async () => {
        const { data } = await apiClient.get('/llm/models');
        return data;
    },

    loadLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/load', { identifier });
        return data;
    },

    unloadLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/unload', { identifier });
        return data;
    },

    ingestFetchUrl: async (url: string) => {
        const { data } = await apiClient.post('/tailoring/ingest/fetch-url', { url });
        return data;
    },

    ingestParse: async (jd_text: string) => {
        const { data } = await apiClient.post('/tailoring/ingest/parse', { jd_text });
        return data;
    },

    ingestCommit: async (fields: Record<string, any>) => {
        const { data } = await apiClient.post('/tailoring/ingest/commit', fields);
        return data;
    },

    createArchive: async (tag: string) => {
        const { data } = await apiClient.post('/tailoring/archive', { tag });
        return data;
    },

    getArchives: async () => {
        const { data } = await apiClient.get('/tailoring/archives');
        return data.archives;
    },

    getArchiveDetail: async (id: number) => {
        const { data } = await apiClient.get(`/tailoring/archives/${id}`);
        return data;
    },

    getPipelinePackages: async () => {
        const { data } = await apiClient.get('/ops/pipeline/packages');
        return data.packages;
    },

    getPipelineTrace: async (archiveId: number, slug: string) => {
        const { data } = await apiClient.get(`/ops/pipeline/trace/${archiveId}/${encodeURIComponent(slug)}`);
        return data;
    },

    getFilterStats: async () => {
        const { data } = await apiClient.get('/filters/stats');
        return data;
    },

    getScheduleLog: async (label: string, lines: number = 100) => {
        const { data } = await apiClient.get(`/schedules/${encodeURIComponent(label)}/log`, { params: { lines } });
        return data;
    },

    getDedup: async () => {
        // DedupView aggregates these
        const stats = await apiClient.get('/dedup/stats');
        const growth = await apiClient.get('/growth');
        const rejected = await apiClient.get('/rejected/stats');
        return {
            ...stats.data,
            ...growth.data,
            total_rejected: rejected.data.total,
            rejection_breakdown: rejected.data.by_stage
        };
    },

    getSchedules: async () => {
        const { data } = await apiClient.get('/schedules');
        return data.jobs;
    },

    dbQuery: async (query: string) => {
        const { data } = await apiClient.get('/db/query', { params: { sql: query } });
        return data;
    },

    dbSchema: async () => {
        const { data } = await apiClient.get('/db/schema');
        return data.tables;
    },

    dbTables: async () => {
        const { data } = await apiClient.get('/db/tables');
        return data.tables;
    },

    dbTableData: async (tableName: string, params: Record<string, any>) => {
        const { data } = await apiClient.get(`/db/table/${tableName}`, { params });
        return data;
    },

    dbAdminStatus: async () => {
        const { data } = await apiClient.get('/db/admin/status');
        return data;
    },

    dbAdminAction: async (action: string, tables: string[], confirm: string) => {
        const { data } = await apiClient.post('/db/admin/action', { action, tables, confirm });
        return data;
    },

    opsStatus: async () => {
        const { data } = await apiClient.get('/ops/status');
        return data;
    },

    opsAction: async (action: string) => {
        const { data } = await apiClient.post('/ops/action', { action });
        return data;
    },
};
