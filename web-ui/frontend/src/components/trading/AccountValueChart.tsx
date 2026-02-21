import { useMemo } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import dayjs from 'dayjs';
import { PortfolioPoint } from '../../services/api';
import './AccountValueChart.css';

interface Props {
  data: PortfolioPoint[];
}

const INITIAL_DEPOSIT = parseFloat(import.meta.env.VITE_INITIAL_DEPOSIT || '100');

const AccountValueChart = ({ data }: Props) => {
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return [];
    return data.map((p) => ({
      time: dayjs(p.timestamp).valueOf(),
      label: dayjs(p.timestamp).format('MM/DD HH:mm'),
      value: p.total_value,
    }));
  }, [data]);

  const { minVal, maxVal } = useMemo(() => {
    if (chartData.length === 0) return { minVal: 90, maxVal: 120 };
    const values = chartData.map((d) => d.value);
    const min = Math.min(...values, INITIAL_DEPOSIT);
    const max = Math.max(...values, INITIAL_DEPOSIT);
    const pad = (max - min) * 0.15 || 5;
    return {
      minVal: Math.floor(min - pad),
      maxVal: Math.ceil(max + pad),
    };
  }, [chartData]);

  if (chartData.length === 0) {
    return (
      <div className="account-value-chart">
        <div className="chart-empty">Waiting for portfolio data...</div>
      </div>
    );
  }

  const lineColor = '#000000';

  return (
    <div className="account-value-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="rgba(0,0,0,0.08)"
            vertical={false}
          />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fontFamily: "'Courier New', monospace", fill: '#666' }}
            tickLine={{ stroke: 'rgba(0,0,0,0.15)' }}
            axisLine={{ stroke: 'rgba(0,0,0,0.15)' }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[minVal, maxVal]}
            tick={{ fontSize: 11, fontFamily: "'Courier New', monospace", fill: '#666' }}
            tickLine={{ stroke: 'rgba(0,0,0,0.15)' }}
            axisLine={{ stroke: 'rgba(0,0,0,0.15)' }}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
          />
          <Tooltip
            contentStyle={{
              fontFamily: "'Courier New', monospace",
              fontSize: 12,
              border: '1px solid #000',
              borderRadius: 0,
              backgroundColor: '#fff',
            }}
            formatter={(value: number) => [`$${value.toFixed(2)}`, 'Total Value']}
            labelFormatter={(label: string) => label}
          />
          <ReferenceLine
            y={INITIAL_DEPOSIT}
            stroke="#999"
            strokeDasharray="5 5"
            strokeWidth={1}
            label={{
              value: `$${INITIAL_DEPOSIT} baseline`,
              position: 'right',
              fontSize: 10,
              fontFamily: "'Courier New', monospace",
              fill: '#999',
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={lineColor}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: lineColor, stroke: '#fff', strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default AccountValueChart;
