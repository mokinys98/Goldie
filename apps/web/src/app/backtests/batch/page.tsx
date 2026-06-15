"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  BatchBacktestResult,
  Bot,
  MarketFeed,
  StrategyProfile,
} from "@/lib/types";

function inputDate(daysAgo: number): string {
  const value = new Date(Date.now() - daysAgo * 86400000);
  value.setSeconds(0, 0);
  return value.toISOString().slice(0, 16);
}

export default function BatchBacktestPage() {
  const [selected, setSelected] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState(inputDate(30));
  const [dateTo, setDateTo] = useState(inputDate(0));
  const [initialCapital, setInitialCapital] = useState("10000");
  const [spread, setSpread] = useState("2");
  const [slippage, setSlippage] = useState("1");
  const [commission, setCommission] = useState("0");
  const [results, setResults] = useState<BatchBacktestResult[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const bots = useQuery({ queryKey: ["bots"], queryFn: () => api<Bot[]>("/api/v1/bots") });
  const feeds = useQuery({ queryKey: ["market-feeds"], queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds") });
  const strategies = useQuery({ queryKey: ["strategy-profiles"], queryFn: () => api<StrategyProfile[]>("/api/v1/strategy-profiles") });
  const feedMap = new Map((feeds.data ?? []).map((feed) => [feed.id, feed]));
  const strategyMap = new Map((strategies.data ?? []).map((strategy) => [strategy.id, strategy]));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setResults(await api<BatchBacktestResult[]>("/api/v1/backtests/batch", {
        method: "POST",
        body: JSON.stringify({
          bot_ids: selected,
          date_from: new Date(dateFrom).toISOString(),
          date_to: new Date(dateTo).toISOString(),
          initial_capital: initialCapital,
          spread_points: spread,
          slippage_points: slippage,
          commission_per_trade: commission,
        }),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not queue batch backtests");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div><span className="eyebrow">HISTORICAL RESEARCH</span><h1>Batch backtest</h1><p>Select bots. Their active configuration and market feed are used automatically.</p></div>
        <Link className="button button-secondary" href="/backtests">Backtests</Link>
      </header>
      <form className="form-grid" onSubmit={submit}>
        <div className="bot-selection-grid">
          {(bots.data ?? []).map((bot) => {
            const eligible = Boolean(bot.active_config_version_id && bot.market_feed_id);
            const feed = bot.market_feed_id ? feedMap.get(bot.market_feed_id) : undefined;
            const strategy = bot.strategy_profile_id ? strategyMap.get(bot.strategy_profile_id) : undefined;
            return (
              <button
                className={`bot-selection-card ${selected.includes(bot.id) ? "selected" : ""}`}
                disabled={!eligible}
                key={bot.id}
                type="button"
                onClick={() => setSelected((current) => current.includes(bot.id) ? current.filter((id) => id !== bot.id) : [...current, bot.id])}
              >
                <strong>{bot.name}</strong>
                <span>{strategy?.name ?? "Standalone strategy"}</span>
                <span>{feed?.canonical_symbol ?? "No market feed"} · {bot.mode}</span>
                <small>{eligible ? bot.state : "Requires active config and market feed"}</small>
              </button>
            );
          })}
        </div>
        <div className="panel compact-form form-grid">
          <label>From<input required type="datetime-local" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label>To<input required type="datetime-local" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
          <label>Capital<input required type="number" min="1" step="0.01" value={initialCapital} onChange={(event) => setInitialCapital(event.target.value)} /></label>
          <label>Spread points<input required type="number" min="0" step="0.01" value={spread} onChange={(event) => setSpread(event.target.value)} /></label>
          <label>Slippage points<input required type="number" min="0" step="0.01" value={slippage} onChange={(event) => setSlippage(event.target.value)} /></label>
          <label>Commission / trade<input required type="number" min="0" step="0.01" value={commission} onChange={(event) => setCommission(event.target.value)} /></label>
        </div>
        {error && <div className="error-box">{error}</div>}
        <button className="button button-primary" disabled={!selected.length || busy}>{busy ? "Queueing..." : `Run ${selected.length} backtest(s)`}</button>
      </form>
      {!!results.length && (
        <div className="table-wrap table-actions">
          <table><thead><tr><th>Bot</th><th>Status</th><th>Result</th></tr></thead><tbody>{results.map((result) => {
            const bot = bots.data?.find((item) => item.id === result.bot_id);
            return <tr key={result.bot_id}><td>{bot?.name ?? result.bot_id}</td><td>{result.status}</td><td>{result.experiment ? <Link className="table-link" href={`/backtests/${result.experiment.id}`}>Open backtest</Link> : result.error}</td></tr>;
          })}</tbody></table>
        </div>
      )}
    </section>
  );
}
