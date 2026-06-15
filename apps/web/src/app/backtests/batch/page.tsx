"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
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
  const [search, setSearch] = useState("");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [strategyFilter, setStrategyFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
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
  const allBots = bots.data ?? [];
  const symbols = useMemo(
    () => [...new Set((feeds.data ?? []).map((feed) => feed.canonical_symbol))].sort(),
    [feeds.data],
  );
  const strategyOptions = useMemo(
    () => [...(strategies.data ?? [])].sort((left, right) => left.name.localeCompare(right.name)),
    [strategies.data],
  );
  const modes = useMemo(
    () => [...new Set((bots.data ?? []).map((bot) => bot.mode))].sort(),
    [bots.data],
  );
  const states = useMemo(
    () => [...new Set((bots.data ?? []).map((bot) => bot.state))].sort(),
    [bots.data],
  );
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredBots = allBots.filter((bot) => {
    const feed = bot.market_feed_id ? feedMap.get(bot.market_feed_id) : undefined;
    return (
      (!normalizedSearch || bot.name.toLocaleLowerCase().includes(normalizedSearch))
      && (!symbolFilter || feed?.canonical_symbol === symbolFilter)
      && (!strategyFilter || (
        strategyFilter === "standalone"
          ? !bot.strategy_profile_id
          : bot.strategy_profile_id === strategyFilter
      ))
      && (!modeFilter || bot.mode === modeFilter)
      && (!stateFilter || bot.state === stateFilter)
    );
  });
  const filtersActive = Boolean(search || symbolFilter || strategyFilter || modeFilter || stateFilter);

  function clearFilters() {
    setSearch("");
    setSymbolFilter("");
    setStrategyFilter("");
    setModeFilter("");
    setStateFilter("");
  }

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
        <div className="panel bot-filter-panel">
          <label className="bot-filter-search">
            Search by bot name
            <input
              type="search"
              placeholder="Any part of the name..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label>
            Currency
            <select value={symbolFilter} onChange={(event) => setSymbolFilter(event.target.value)}>
              <option value="">All currencies</option>
              {symbols.map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}
            </select>
          </label>
          <label>
            Strategy
            <select value={strategyFilter} onChange={(event) => setStrategyFilter(event.target.value)}>
              <option value="">All strategies</option>
              <option value="standalone">Standalone strategy</option>
              {strategyOptions.map((strategy) => <option key={strategy.id} value={strategy.id}>{strategy.name}</option>)}
            </select>
          </label>
          <label>
            Mode
            <select value={modeFilter} onChange={(event) => setModeFilter(event.target.value)}>
              <option value="">All modes</option>
              {modes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
            </select>
          </label>
          <label>
            State
            <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}>
              <option value="">All states</option>
              {states.map((state) => <option key={state} value={state}>{state}</option>)}
            </select>
          </label>
          <div className="bot-filter-summary">
            <span aria-live="polite" data-testid="bot-filter-count">Showing <strong>{filteredBots.length}</strong> of {allBots.length} bots</span>
            <button className="button button-secondary" disabled={!filtersActive} type="button" onClick={clearFilters}>Clear filters</button>
          </div>
        </div>
        <div className="bot-selection-grid">
          {filteredBots.map((bot) => {
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
        {!filteredBots.length && !bots.isLoading && (
          <div className="empty-state bot-filter-empty">
            <h2>No matching bots</h2>
            <p>Adjust the search or filters to show more cards.</p>
            <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button>
          </div>
        )}
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
