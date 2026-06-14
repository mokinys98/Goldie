"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  LineSeries,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";

type MarketChartPoint = {
  opened_at: string;
  close: string;
  open?: string;
  high?: string;
  low?: string;
};

// TradingView Lightweight Charts(TM) Copyright (c) 2025 TradingView, Inc.
export function MarketChart({ candles }: { candles: MarketChartPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const isCandlestick = candles.some(hasOhlc);

  const chartData = useMemo(
    () => normalizeData(candles, isCandlestick),
    [candles, isCandlestick],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        background: { type: ColorType.Solid, color: "#111318" },
        textColor: "#8f949e",
        fontFamily: "inherit",
      },
      grid: {
        vertLines: { color: "#23262d" },
        horzLines: { color: "#23262d" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "#343841",
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: "#343841",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        barSpacing: 9,
      },
      localization: { locale: "lt-LT" },
    });

    chartRef.current = chart;
    if (isCandlestick) {
      candlestickSeriesRef.current = chart.addSeries(CandlestickSeries, {
        upColor: "#2fbf8f",
        downColor: "#e45b64",
        borderVisible: false,
        wickUpColor: "#2fbf8f",
        wickDownColor: "#e45b64",
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });
    } else {
      lineSeriesRef.current = chart.addSeries(LineSeries, {
        color: "#e8bd58",
        lineWidth: 2,
        priceLineVisible: true,
        lastValueVisible: true,
      });
    }

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candlestickSeriesRef.current = null;
      lineSeriesRef.current = null;
    };
  }, [isCandlestick]);

  useEffect(() => {
    if (isCandlestick) {
      candlestickSeriesRef.current?.setData(chartData as CandlestickData[]);
    } else {
      lineSeriesRef.current?.setData(chartData as LineData[]);
    }
    chartRef.current?.timeScale().fitContent();
  }, [chartData, isCandlestick]);

  if (chartData.length < 2) {
    return <div className="chart-empty">Waiting for completed M1 candles...</div>;
  }

  return <div ref={containerRef} className="chart" aria-label="Interactive market chart" />;
}

function hasOhlc(point: MarketChartPoint): boolean {
  return point.open !== undefined && point.high !== undefined && point.low !== undefined;
}

function normalizeData(
  points: MarketChartPoint[],
  isCandlestick: boolean,
): Array<CandlestickData | LineData> {
  const byTime = new Map<number, CandlestickData | LineData>();

  for (const point of points) {
    const milliseconds = Date.parse(point.opened_at);
    const close = Number(point.close);
    if (!Number.isFinite(milliseconds) || !Number.isFinite(close)) continue;

    const time = Math.floor(milliseconds / 1000) as UTCTimestamp;
    if (isCandlestick && hasOhlc(point)) {
      const open = Number(point.open);
      const high = Number(point.high);
      const low = Number(point.low);
      if ([open, high, low].every(Number.isFinite)) {
        byTime.set(time, { time, open, high, low, close });
      }
    } else if (!isCandlestick) {
      byTime.set(time, { time, value: close });
    }
  }

  return [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time));
}
