import { Bar } from 'react-chartjs-2';

export function RunTimelineChart({
  data,
  options,
}: {
  data: any;
  options: any;
}) {
  return (
    <div className="chart-container">
      <div className="chart-title">Run Duration Timeline</div>
      <div style={{ height: '200px' }}>
        <Bar data={data} options={options} />
      </div>
    </div>
  );
}
