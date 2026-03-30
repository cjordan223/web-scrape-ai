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

    getScraperConfig: async () => {
        const { data } = await apiClient.get('/scraper/config');
        return data;
    },
    saveScraperConfig: async (config: Record<string, any>) => {
        const { data } = await apiClient.post('/scraper/config', config);
        return data;
    },
    getScraperPipelineStats: async () => {
        const { data } = await apiClient.get('/scraper/pipeline/stats');
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

    getTailoringJobBriefing: async (id: number) => {
        const { data } = await apiClient.get(`/tailoring/jobs/${id}/briefing`);
        return data;
    },

    getTailoringReady: async (limit?: number, params?: Record<string, any>) => {
        const { data } = await apiClient.get('/tailoring/ready', { params: { limit, ...(params || {}) } });
        return data;
    },

    setTailoringReadyBucket: async (jobIds: number[], bucket: 'backlog' | 'next' | 'later') => {
        const { data } = await apiClient.post('/tailoring/ready/bucket', { job_ids: jobIds, bucket });
        return data;
    },

    queueTailoringBucket: async (bucket: 'next' | 'later', payload?: { limit?: number; skip_analysis?: boolean }) => {
        const { data } = await apiClient.post('/tailoring/ready/queue-bucket', { bucket, ...(payload || {}) });
        return data;
    },

    getTailoringRejected: async (limit?: number) => {
        const { data } = await apiClient.get('/tailoring/rejected', { params: { limit } });
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

    getPackages: async () => {
        const { data } = await apiClient.get('/packages');
        return data.items;
    },

    getPackageDetail: async (slug: string) => {
        const { data } = await apiClient.get(`/packages/${slug}`);
        return data;
    },

    deletePackage: async (slug: string) => {
        const { data } = await apiClient.delete(`/packages/${slug}`);
        return data;
    },

    rejectPackage: async (slug: string) => {
        const { data } = await apiClient.post(`/packages/${slug}/reject`);
        return data;
    },

    permanentlyRejectPackage: async (slug: string) => {
        const { data } = await apiClient.post(`/packages/${slug}/dead`);
        return data;
    },

    applyPackage: async (slug: string, payload: Record<string, any>) => {
        const { data } = await apiClient.post(`/packages/${slug}/apply`, payload);
        return data;
    },

    regeneratePackageCover: async (slug: string) => {
        const { data } = await apiClient.post(`/packages/${slug}/regenerate/cover`);
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

    getAppliedList: async (params?: Record<string, any>) => {
        const { data } = await apiClient.get('/applied', { params });
        return data;
    },

    getAppliedDetail: async (applicationId: number) => {
        const { data } = await apiClient.get(`/applied/${applicationId}`);
        return data;
    },

    updateAppliedTracking: async (applicationId: number, payload: Record<string, any>) => {
        const { data } = await apiClient.post(`/applied/${applicationId}/tracking`, payload);
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

    selectLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/select', { identifier });
        return data;
    },

    deselectLlmModel: async (identifier: string) => {
        const { data } = await apiClient.post('/llm/models/deselect', { identifier });
        return data;
    },

    getLlmProviders: async () => {
        const { data } = await apiClient.get('/llm/providers');
        return data;
    },

    setLlmProviderKey: async (provider: string, key: string) => {
        const { data } = await apiClient.post('/llm/providers/key', { provider, key });
        return data;
    },

    activateLlmProvider: async (provider: string, base_url?: string) => {
        const { data } = await apiClient.post('/llm/providers/activate', { provider, base_url });
        return data;
    },

    testLlmProvider: async (provider: string) => {
        const { data } = await apiClient.post('/llm/providers/test', { provider });
        return data;
    },

    // MLX management
    getMlxStatus: async () => {
        const { data } = await apiClient.get('/llm/mlx/status');
        return data;
    },
    startMlx: async (model: string, port = 8080) => {
        const { data } = await apiClient.post('/llm/mlx/start', { model, port });
        return data;
    },
    stopMlx: async () => {
        const { data } = await apiClient.post('/llm/mlx/stop');
        return data;
    },
    getMlxModels: async () => {
        const { data } = await apiClient.get('/llm/mlx/models');
        return data;
    },
    pullMlxModel: async (model_id: string) => {
        const { data } = await apiClient.post('/llm/mlx/pull', { model_id });
        return data;
    },
    getMlxPullStatus: async () => {
        const { data } = await apiClient.get('/llm/mlx/pull/status');
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

    getQAPending: async (limit?: number, params?: Record<string, any>) => {
        const { data } = await apiClient.get('/tailoring/qa', { params: { limit, ...(params || {}) } });
        return data;
    },

    getLeads: async (limit?: number, params?: Record<string, any>) => {
        const { data } = await apiClient.get('/leads', { params: { limit, ...(params || {}) } });
        return data;
    },

    scanMobileJDs: async () => {
        const { data } = await apiClient.post('/tailoring/ingest/scan-mobile');
        return data;
    },

    approveQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/approve', { job_ids: jobIds });
        return data;
    },

    llmReviewQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/llm-review', { job_ids: jobIds });
        return data;
    },

    getQALlmReviewStatus: async () => {
        const { data } = await apiClient.get('/tailoring/qa/llm-review');
        return data;
    },

    cancelQAReview: async () => {
        const { data } = await apiClient.delete('/tailoring/qa/llm-review');
        return data;
    },

    runTailoringLatest: async () => {
        const { data } = await apiClient.post('/tailoring/run-latest');
        return data;
    },

    rejectQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/reject', { job_ids: jobIds });
        return data;
    },

    permanentlyRejectQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/permanently-reject', { job_ids: jobIds });
        return data;
    },

    resetApprovedQA: async () => {
        const { data } = await apiClient.post('/tailoring/qa/reset-approved');
        return data;
    },

    undoApproveQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/undo-approve', { job_ids: jobIds });
        return data;
    },

    undoRejectQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/undo-reject', { job_ids: jobIds });
        return data;
    },

    rollbackToQA: async (jobIds: number[]) => {
        const { data } = await apiClient.post('/tailoring/qa/rollback', { job_ids: jobIds });
        return data;
    },

    packageChatSend: async (slug: string, message: string, docFocus?: string) => {
        const { data } = await apiClient.post(`/packages/${slug}/chat`, { message, doc_focus: docFocus });
        return data;
    },

    packageChatHistory: async (slug: string) => {
        const { data } = await apiClient.get(`/packages/${slug}/chat`);
        return data;
    },

    packageChatClear: async (slug: string) => {
        const { data } = await apiClient.delete(`/packages/${slug}/chat`);
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

    opsStatus: async () => {
        const { data } = await apiClient.get('/ops/status');
        return data;
    },

    opsAction: async (action: string) => {
        const { data } = await apiClient.post('/ops/action', { action });
        return data;
    },

    getTailoringMetrics: async () => {
        const { data } = await apiClient.get('/ops/tailoring/metrics');
        return data;
    },
};
