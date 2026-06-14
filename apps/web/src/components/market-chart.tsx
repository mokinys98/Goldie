"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  LineSeries,
  LineStyle,
  type BarData,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
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

type LegendValues = {
  open: number;
  high: number;
  low: number;
  close: number;
};

type MarketChartProps = {
  candles: MarketChartPoint[];
  precision?: number;
  bid?: string | null;
  ask?: string | null;
  symbol?: string;
  timeframe?: string;
};

// TradingView Lightweight Charts(TM) Copyright (c) 2025 TradingView, Inc.
export function MarketChart({
  candles,
  precision = 2,
  bid,
  ask,
  symbol,
  timeframe = "M1",
}: MarketChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>(null);
  const bidLineRef = useRef<IPriceLine | null>(null);
  const askLineRef = useRef<IPriceLine | null>(null);
  const hasOhlcData = candles.some(hasOhlc);
  const [style, setStyle] = useState<"candles" | "line">(
    hasOhlcData ? "candles" : "line",
  );
  const [showGrid, setShowGrid] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [legend, setLegend] = useState<LegendValues | null>(null);
  const useCandles = hasOhlcData && style === "candles";
  const safePrecision = Math.max(0, Math.min(10, Math.trunc(precision)));
  const minMove = 10 ** -safePrecision;

  const chartData = useMemo(
    () => normalizeData(candles, useCandles),
    [candles, useCandles],
  );
  const chartDataRef = useRef(chartData);
  chartDataRef.current = chartData;
  const chartReady = chartData.length >= 2;
  const latestOhlc = useMemo(() => latestLegend(candles), [candles]);

  useEffect(() => {
    if (!hasOhlcData) setStyle("line");
  }, [hasOhlcData]);

  useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === wrapperRef.current);
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !chartReady) return;

    const gridColor = showGrid ? "#23262d" : "#111318";
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        background: { type: ColorType.Solid, color: "#111318" },
        textColor: "#8f949e",
        fontFamily: "inherit",
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
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
    const priceFormat = {
      type: "price" as const,
      precision: safePrecision,
      minMove,
    };
    const series = useCandles
      ? chart.addSeries(CandlestickSeries, {
          upColor: "#2fbf8f",
          downColor: "#e45b64",
          borderVisible: false,
          wickUpColor: "#2fbf8f",
          wickDownColor: "#e45b64",
          priceFormat,
        })
      : chart.addSeries(LineSeries, {
          color: "#e8bd58",
          lineWidth: 2,
          priceLineVisible: true,
          lastValueVisible: true,
          priceFormat,
        });

    seriesRef.current = series;
    series.setData(chartDataRef.current as never);
    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      const item = param.seriesData.get(series);
      if (item && "open" in item) {
        const bar = item as BarData;
        setLegend({
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        });
      } else if (!param.time) {
        setLegend(null);
      }
    });

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      bidLineRef.current = null;
      askLineRef.current = null;
    };
  }, [showGrid, useCandles, safePrecision, minMove, chartReady]);

  useEffect(() => {
    if (!seriesRef.current || chartData.length < 2) return;
    seriesRef.current.setData(chartData as never);
  }, [chartData]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    if (bidLineRef.current) series.removePriceLine(bidLineRef.current);
    if (askLineRef.current) series.removePriceLine(askLineRef.current);
    bidLineRef.current = createQuoteLine(series, bid, "BID", "#5aa7ff");
    askLineRef.current = createQuoteLine(series, ask, "ASK", "#e8bd58");
  }, [bid, ask, useCandles]);

  const toggleFullscreen = async () => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    if (document.fullscreenElement === wrapper) {
      await document.exitFullscreen();
    } else {
      await wrapper.requestFullscreen();
    }
  };

  if (!chartReady) {
    return <div className="chart-empty">Waiting for completed M1 candles...</div>;
  }

  const visibleLegend = legend ?? latestOhlc;
  return (
    <div ref={wrapperRef} className="chart-shell">
      <div className="chart-toolbar">
        <div className="chart-identity">
          <strong>{symbol ?? "Market"}</strong>
          <span>{timeframe}</span>
          {visibleLegend && (
            <div className="chart-ohlc">
              <span>O {formatPrice(visibleLegend.open, safePrecision)}</span>
              <span>H {formatPrice(visibleLegend.high, safePrecision)}</span>
              <span>L {formatPrice(visibleLegend.low, safePrecision)}</span>
              <span>C {formatPrice(visibleLegend.close, safePrecision)}</span>
            </div>
          )}
        </div>
        <div className="chart-actions">
          {hasOhlcData && (
            <>
              <button
                className={style === "candles" ? "active" : ""}
                onClick={() => setStyle("candles")}
                type="button"
              >
                Candles
              </button>
              <button
                className={style === "line" ? "active" : ""}
                onClick={() => setStyle("line")}
                type="button"
              >
                Line
              </button>
            </>
          )}
          <button
            className={showGrid ? "active" : ""}
            onClick={() => setShowGrid((value) => !value)}
            type="button"
          >
            Grid
          </button>
          <button onClick={() => chartRef.current?.timeScale().fitContent()} type="button">
            Fit
          </button>
          <button onClick={() => void toggleFullscreen()} type="button">
            {isFullscreen ? "Exit full screen" : "Full screen"}
          </button>
        </div>
      </div>
      <div ref={containerRef} className="chart" aria-label="Interactive market chart" />
    </div>
  );
}

function hasOhlc(point: MarketChartPoint): boolean {
  return point.open !== undefined && point.high !== undefined && point.low !== undefined;
}

function normalizeData(
  points: MarketChartPoint[],
  useCandles: boolean,
): Array<CandlestickData | LineData> {
  const byTime = new Map<number, CandlestickData | LineData>();

  for (const point of points) {
    const milliseconds = Date.parse(point.opened_at);
    const close = Number(point.close);
    if (!Number.isFinite(milliseconds) || !Number.isFinite(close)) continue;

    const time = Math.floor(milliseconds / 1000) as UTCTimestamp;
    if (useCandles && hasOhlc(point)) {
      const open = Number(point.open);
      const high = Number(point.high);
      const low = Number(point.low);
      if ([open, high, low].every(Number.isFinite)) {
        byTime.set(time, { time, open, high, low, close });
      }
    } else {
      byTime.set(time, { time, value: close });
    }
  }

  return [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time));
}

function latestLegend(points: MarketChartPoint[]): LegendValues | null {
  const point = [...points].reverse().find(hasOhlc);
  if (!point) return null;
  const values = {
    open: Number(point.open),
    high: Number(point.high),
    low: Number(point.low),
    close: Number(point.close),
  };
  return Object.values(values).every(Number.isFinite) ? values : null;
}

function createQuoteLine(
  series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">,
  value: string | null | undefined,
  title: string,
  color: string,
): IPriceLine | null {
  const price = Number(value);
  if (!Number.isFinite(price)) return null;
  return series.createPriceLine({
    price,
    title,
    color,
    lineWidth: 1,
    lineStyle: LineStyle.Dashed,
    axisLabelVisible: true,
  });
}

function formatPrice(value: number, precision: number): string {
  return value.toFixed(precision);
}
