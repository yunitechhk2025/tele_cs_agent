import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import type { ObservabilityStageTrendSeries } from '../types';

export type StageTrendMetricKey = 'avg_ms' | 'p50_ms' | 'p95_ms' | 'p99_ms';

interface StageTrendChartProps {
  stages: ObservabilityStageTrendSeries[];
  selectedStageKeys: string[];
  metricKey: StageTrendMetricKey;
}

function formatLatency(value: number | null | undefined) {
  if (value == null) return '-';
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`;
  return `${value}ms`;
}

export default function StageTrendChart({
  stages,
  selectedStageKeys,
  metricKey,
}: StageTrendChartProps) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  const option = useMemo(() => {
    const selected = stages.filter((stage) => selectedStageKeys.includes(stage.stage_key));
    const bucketLabels: string[] = [];
    const bucketOrder = new Map<string, string>();
    selected.forEach((stage) => {
      stage.points.forEach((point) => {
        if (!bucketOrder.has(point.bucket_label)) {
          bucketOrder.set(point.bucket_label, point.bucket_start);
          bucketLabels.push(point.bucket_label);
        }
      });
    });
    bucketLabels.sort((a, b) =>
      String(bucketOrder.get(a)).localeCompare(String(bucketOrder.get(b))),
    );

    return {
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: number) => formatLatency(value),
      },
      legend: {
        type: 'scroll',
        top: 0,
      },
      grid: {
        left: 44,
        right: 20,
        top: 48,
        bottom: 36,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: bucketLabels,
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value: number) => formatLatency(value),
        },
      },
      series: selected.map((stage) => {
        const pointMap = new Map(
          stage.points.map((point) => [point.bucket_label, point[metricKey]]),
        );
        return {
          name: stage.stage_label || stage.stage_key,
          type: 'line',
          smooth: true,
          symbolSize: 6,
          connectNulls: false,
          data: bucketLabels.map((label) => pointMap.get(label) ?? null),
        };
      }),
    };
  }, [metricKey, selectedStageKeys, stages]);

  useEffect(() => {
    if (!chartRef.current) return undefined;
    const chart = echarts.init(chartRef.current);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [option]);

  return <div ref={chartRef} style={{ width: '100%', height: 320 }} />;
}
