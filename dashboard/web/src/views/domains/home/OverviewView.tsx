import { useEffect, useState } from 'react';
import { api } from '../../../api';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    ArcElement,
    Filler
} from 'chart.js';
import { Line, Bar, Doughnut } from 'react-chartjs-2';
import { Briefcase, Link, Calendar, Percent, Clock, Database } from 'lucide-react';
import { fmt, fmtBytes, timeAgo } from '../../../utils';
import { PageHeader, PagePrimary, PageSecondary, PageView } from '../../../components/workflow/PageLayout';
import { LoadingState } from '../../../components/workflow/States';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    ArcElement,
    Filler
);

export default function OverviewView() {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [llmStatus, setLlmStatus] = useState<any>(null);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
    const [updatedLabel, setUpdatedLabel] = useState('just now');

    useEffect(() => {
        if (!lastUpdated) return;
        const tick = () => {
            const secs = Math.floor((Date.now() - lastUpdated.getTime()) / 1000);
            if (secs < 60) setUpdatedLabel(`${secs}s ago`);
            else setUpdatedLabel(`${Math.floor(secs / 60)}m ago`);
        };
        tick();
        const t = setInterval(tick, 15000);
        return () => clearInterval(t);
    }, [lastUpdated]);

    useEffect(() => {
        let interval: number;
        const load = async () => {
            try {
                const res = await api.getOverview();
                setData(res);
                setLastUpdated(new Date());
            } catch (err) {
                console.error('Failed to load overview', err);
            } finally {
                setLoading(false);
            }
        };
        const loadLlm = async () => {
            try {
                const res = await api.getLlmStatus();
                setLlmStatus(res);
            } catch { }
        };
        load();
        loadLlm();
        interval = setInterval(load, 30000) as unknown as number;
        const llmInterval = setInterval(loadLlm, 60000) as unknown as number;
        return () => { clearInterval(interval); clearInterval(llmInterval); };
    }, []);

    if (loading || !data) {
        return (
            <PageView>
                <PageHeader title="Overview" />
                <LoadingState />
            </PageView>
        );
    }

    // Charts Config
    const trendData = {
        labels: data.trend.map((d: any) => d.date.slice(5)), // MM-DD
        datasets: [
            {
                label: 'New Jobs',
                data: data.trend.map((d: any) => d.count),
                backgroundColor: '#06d6a0',
                borderRadius: 4,
            }
        ]
    };

    const cumulativeData = {
        labels: data.trend.map((d: any) => d.date.slice(5)),
        datasets: [
            {
                label: 'Total Accumulated',
                data: data.trend.reduce((acc: number[], curr: any) => {
                    acc.push((acc.length > 0 ? acc[acc.length - 1] : 0) + curr.count);
                    return acc;
                }, []),
                borderColor: '#4361ee',
                backgroundColor: 'rgba(67, 97, 238, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 2,
            }
        ]
    };

    const boardData = {
        labels: Object.keys(data.boards),
        datasets: [
            {
                data: Object.values(data.boards),
                backgroundColor: ['#4361ee', '#3a0ca3', '#7209b7', '#f72585', '#4cc9f0', '#06d6a0'],
                borderWidth: 0,
            }
        ]
    };

    const seniorityData = {
        labels: Object.keys(data.seniority),
        datasets: [
            {
                data: Object.values(data.seniority),
                backgroundColor: ['#06d6a0', '#118ab2', '#073b4c', '#ffd166', '#ef476f'],
                borderWidth: 0,
            }
        ]
    };

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
        }
    };

    const doughnutOptions = {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
            legend: { position: 'right' as const, labels: { boxWidth: 12, font: { size: 11 } } }
        }
    };

    return (
        <PageView>
            <PageHeader
                title="Overview"
                right={
                    <>
                    {llmStatus && (
                        <span
                            className={`pill ${llmStatus.enabled === false ? 'pill-unknown' : (llmStatus.available ? 'pill-success' : 'pill-fail')}`}
                            title={llmStatus.enabled === false ? 'LLM checks disabled' : (llmStatus.available ? (llmStatus.models || []).join(', ') : `LLM not reachable at ${llmStatus.url}`)}
                        >
                            {llmStatus.enabled === false ? 'LLM disabled' : (llmStatus.available ? 'LLM online' : 'LLM offline')}
                        </span>
                    )}
                    <div className="last-updated">Updated {updatedLabel}</div>
                    </>
                }
            />
            <PagePrimary>
            <div className="cards">
                <div className="card">
                    <div className="card-icon blue"><Briefcase size={20} /></div>
                    <div className="card-label">Total Jobs</div>
                    <div className="card-value">{fmt(data.total_results)}</div>
                </div>
                <div className="card">
                    <div className="card-icon purple"><Link size={20} /></div>
                    <div className="card-label">URLs Seen</div>
                    <div className="card-value">{fmt(data.total_seen)}</div>
                </div>
                <div className="card">
                    <div className="card-icon green"><Calendar size={20} /></div>
                    <div className="card-label">Today</div>
                    <div className="card-value">{fmt(data.jobs_today)}</div>
                </div>
                <div className="card">
                    <div className="card-icon cyan"><Percent size={20} /></div>
                    <div className="card-label">Dedup Ratio</div>
                    <div className="card-value">{data.dedup_ratio != null ? (data.dedup_ratio * 100).toFixed(1) + '%' : '—'}</div>
                    <div className="card-sub">results / seen</div>
                </div>
                <div className="card">
                    <div className="card-icon amber"><Clock size={20} /></div>
                    <div className="card-label">Last Run</div>
                    <div className="card-value" style={{ fontSize: '1.1rem' }}>
                        {data.last_run ? timeAgo(data.last_run.timestamp) : '—'}
                    </div>
                    <div className="card-sub">
                        {data.last_run && <span className={`pill pill-${data.last_run.status}`}>{data.last_run.status}</span>}
                    </div>
                </div>
                <div className="card">
                    <div className="card-icon red"><Database size={20} /></div>
                    <div className="card-label">DB Size</div>
                    <div className="card-value" style={{ fontSize: '1.1rem' }}>{fmtBytes(data.db_size)}</div>
                </div>
            </div>

            {data.run_health && data.run_health.length > 0 && (
                <div className="health-strip">
                    <span className="health-strip-label">Last 20 Runs</span>
                    {[...data.run_health].reverse().map((rh: any) => (
                        <div key={rh.run_id} className={`health-block ${rh.status === 'complete' ? 'success' : (rh.status === 'running' ? 'running' : 'failed')}`}>
                            <div className="health-block-tooltip">{rh.status} — {timeAgo(rh.started_at)}</div>
                        </div>
                    ))}
                </div>
            )}

            <div className="chart-container" style={{ height: '300px' }}>
                <div className="chart-title">Cumulative Growth</div>
                <Line data={cumulativeData} options={chartOptions} />
            </div>

            <div className="chart-container" style={{ height: '300px' }}>
                <div className="chart-title">Daily Discovery (Last 30 Days)</div>
                <Bar data={trendData} options={chartOptions} />
            </div>
            </PagePrimary>

            <PageSecondary>
            <div className="chart-row">
                <div className="chart-container" style={{ height: '280px' }}>
                    <div className="chart-title">By Board</div>
                    <Doughnut data={boardData} options={doughnutOptions} />
                </div>
                <div className="chart-container" style={{ height: '280px' }}>
                    <div className="chart-title">By Seniority</div>
                    <Doughnut data={seniorityData} options={doughnutOptions} />
                </div>
            </div>
            </PageSecondary>
        </PageView>
    );
}
