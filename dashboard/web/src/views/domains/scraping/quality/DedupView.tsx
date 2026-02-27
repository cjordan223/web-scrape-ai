import { useEffect, useState } from 'react';
import { api } from '../../../../api';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';
import { fmt } from '../../../../utils';
import { PageHeader, PagePrimary, PageSecondary, PageView } from '../../../../components/workflow/PageLayout';
import { WorkflowPanel } from '../../../../components/workflow/Panel';
import { LoadingState } from '../../../../components/workflow/States';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend
);

export default function DedupView() {
    const [data, setData] = useState<any>(null);
    const [filterStats, setFilterStats] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchAll = async () => {
            try {
                const [dedupRes, filterRes] = await Promise.all([
                    api.getDedup(),
                    api.getFilterStats()
                ]);
                setData(dedupRes);
                setFilterStats(filterRes);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        fetchAll();
    }, []);

    if (loading || !data) {
        return (
            <PageView>
                <PageHeader title="Dedup & Growth" />
                <LoadingState />
            </PageView>
        );
    }

    const freqData = {
        labels: Object.keys(data.repeat_freq || {}),
        datasets: [
            {
                label: 'URLs',
                data: Object.values(data.repeat_freq || {}),
                backgroundColor: '#4361ee',
                borderRadius: 4,
            }
        ]
    };

    const uniquenessData = {
        labels: data.run_uniqueness.map((d: any) => d.date.slice(5, 10)),
        datasets: [
            {
                label: 'Uniqueness Rate',
                data: data.run_uniqueness.map((d: any) => d.raw > 0 ? ((d.stored / d.raw) * 100).toFixed(1) : 0),
                borderColor: '#06d6a0',
                backgroundColor: 'rgba(6, 214, 160, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 2,
            }
        ]
    };

    // Daily new jobs chart
    const dailyNewData = data.run_uniqueness?.length > 0 ? {
        labels: data.run_uniqueness.map((d: any) => d.date.slice(5, 10)),
        datasets: [
            {
                label: 'New Jobs Stored',
                data: data.run_uniqueness.map((d: any) => d.stored),
                backgroundColor: '#06d6a0',
                borderRadius: 4,
            }
        ]
    } : null;

    // Filter keyword chart
    const keywordData = filterStats?.keyword_stats?.length > 0 ? {
        labels: filterStats.keyword_stats.slice(0, 15).map((k: any) => k.keyword),
        datasets: [
            {
                label: 'Matches',
                data: filterStats.keyword_stats.slice(0, 15).map((k: any) => k.count),
                backgroundColor: '#4361ee',
                borderRadius: 4,
            }
        ]
    } : null;

    const passRate = filterStats?.pass_rate != null
        ? (filterStats.pass_rate * 100).toFixed(1) + '%'
        : '—';

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
        }
    };

    return (
        <PageView>
            <PageHeader title="Deduplication & Growth" />
            <PagePrimary>
            <div className="cards">
                <div className="card">
                    <div className="card-label">Total URLs Seen</div>
                    <div className="card-value">{data.total_seen.toLocaleString()}</div>
                </div>
                <div className="card">
                    <div className="card-label">Overall Unique</div>
                    <div className="card-value">{data.total_results.toLocaleString()}</div>
                    <div className="card-sub">{((data.total_results / data.total_seen) * 100).toFixed(1)}% of total</div>
                </div>
                <div className="card">
                    <div className="card-label">High Freq URLs</div>
                    <div className="card-value">{(data.repeat_freq?.['10x+'] || 0).toLocaleString()}</div>
                    <div className="card-sub">Seen &gt;10 times</div>
                </div>
            </div>

            {/* Dedup Funnel */}
            <div className="chart-container">
                <div className="chart-title">Dedup Funnel</div>
                <div className="funnel">
                    <div className="funnel-step">
                        <div className="funnel-label">URLs Seen</div>
                        <div className="funnel-bar" style={{ width: '100%', background: 'var(--purple)' }}>{fmt(data.total_seen)}</div>
                    </div>
                    <div className="funnel-arrow">↓</div>
                    <div className="funnel-step">
                        <div className="funnel-label">Passed Filters</div>
                        <div className="funnel-bar" style={{ width: `${Math.max(5, data.total_results / data.total_seen * 100)}%`, background: 'var(--accent)' }}>{fmt(data.total_results)}</div>
                    </div>
                </div>
            </div>

            <div className="chart-row">
                <div className="chart-container" style={{ height: '300px' }}>
                    <div className="chart-title">URL Frequency Distribution</div>
                    <Bar data={freqData} options={chartOptions} />
                </div>
                <div className="chart-container" style={{ height: '300px' }}>
                    <div className="chart-title">Daily Uniqueness Rate</div>
                    <Line data={uniquenessData} options={{ ...chartOptions, scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + '%' } } } }} />
                </div>
            </div>

            {/* Daily New Jobs chart */}
            {dailyNewData && (
                <div className="chart-container" style={{ height: '300px' }}>
                    <div className="chart-title">Daily New Jobs Stored</div>
                    <Bar data={dailyNewData} options={chartOptions} />
                </div>
            )}

            {/* Filter analytics cards */}
            <div className="cards" style={{ marginBottom: '24px' }}>
                <div className="card">
                    <div className="card-label">Avg Pass Rate</div>
                    <div className="card-value">{passRate}</div>
                    <div className="card-sub">filtered / dedup across runs</div>
                </div>
                <div className="card">
                    <div className="card-label">Total Passing Jobs</div>
                    <div className="card-value">{fmt(data.total_results)}</div>
                </div>
            </div>

            {/* Top keywords chart */}
            {keywordData && (
                <div className="chart-container" style={{ height: '300px' }}>
                    <div className="chart-title">Top Matching Keywords (Passing Jobs)</div>
                    <Bar data={keywordData} options={chartOptions} />
                </div>
            )}
            </PagePrimary>

            {/* Verdict Breakdown by Stage */}
            {filterStats?.stages && filterStats.stages.length > 0 ? (
                <PageSecondary>
                <WorkflowPanel title="Verdict Breakdown by Stage" style={{ marginTop: '24px' }}>
                    {filterStats.stages.map((stage: any) => (
                        <div key={stage.stage} style={{ padding: '12px 20px', borderBottom: '1px solid var(--border)' }}>
                            <div style={{ fontWeight: 600, marginBottom: '6px' }}>{stage.stage}</div>
                            {(stage.reasons || []).slice(0, 5).map((r: any) => (
                                <div key={r.reason} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '2px 0', fontSize: '.85rem' }}>
                                    <div style={{ minWidth: '32px', textAlign: 'right', fontWeight: 600, color: 'var(--accent)' }}>{r.count}</div>
                                    <div style={{ flex: 1, color: 'var(--text-secondary)' }}>{r.reason}</div>
                                    <div style={{ width: '120px', height: '6px', background: 'var(--border)', borderRadius: '3px', overflow: 'hidden' }}>
                                        <div style={{ height: '100%', borderRadius: '3px', background: 'var(--accent)', width: `${Math.round(r.count / stage.total * 100)}%` }}></div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ))}
                </WorkflowPanel>
                </PageSecondary>
            ) : null}
        </PageView>
    );
}
