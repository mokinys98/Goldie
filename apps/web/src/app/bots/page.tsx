"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Bot } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function BotsPage() {
  const router = useRouter();
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [configFilter, setConfigFilter] = useState("");
  const query = useQuery({
    queryKey: ["bots"],
    queryFn: () => api<Bot[]>("/api/v1/bots"),
  });
  const bots = useMemo(() => query.data ?? [], [query.data]);
  const modes = useMemo(() => [...new Set(bots.map((bot) => bot.mode))].sort(), [bots]);
  const states = useMemo(() => [...new Set(bots.map((bot) => bot.state))].sort(), [bots]);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredBots = bots.filter((bot) => (
    (!normalizedSearch
      || bot.name.toLocaleLowerCase().includes(normalizedSearch)
      || bot.description.toLocaleLowerCase().includes(normalizedSearch))
    && (!modeFilter || bot.mode === modeFilter)
    && (!stateFilter || bot.state === stateFilter)
    && (!configFilter
      || (configFilter === "active" ? bot.active_config_version_id : !bot.active_config_version_id))
  ));
  const filtersActive = Boolean(search || modeFilter || stateFilter || configFilter);

  function clearFilters() {
    setSearch("");
    setModeFilter("");
    setStateFilter("");
    setConfigFilter("");
  }

  if (query.error instanceof ApiError && query.error.status === 401) {
    router.push("/login");
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">LOCAL WORKSPACE</span>
          <h1>Bot instances</h1>
          <p>Independent read-only research configurations.</p>
        </div>
        <div className="button-row">
          <Link className="button button-secondary" href="/bots/performance">Performance</Link>
          <Link className="button button-primary" href="/bots/new">Create bot</Link>
        </div>
      </header>

      {query.isLoading && <div className="panel">Loading bots...</div>}
      {query.error && <div className="error-box">{query.error.message}</div>}
      {query.data?.length === 0 && (
        <div className="empty-state">
          <h2>No bot instances</h2>
          <p>Create the first shadow bot and activate its configuration.</p>
        </div>
      )}
      {!!query.data?.length && (
        <>
          <div className="panel bot-filter-panel">
            <label className="bot-filter-search">
              Search bot
              <input
                type="search"
                placeholder="Name or description..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
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
            <label>
              Active config
              <select value={configFilter} onChange={(event) => setConfigFilter(event.target.value)}>
                <option value="">Any config state</option>
                <option value="active">Active</option>
                <option value="draft">Draft only</option>
              </select>
            </label>
            <div className="bot-filter-summary">
              <span aria-live="polite">Showing <strong>{filteredBots.length}</strong> of {bots.length} bots</span>
              <button className="button button-secondary" disabled={!filtersActive} type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          </div>
          {!filteredBots.length ? (
            <div className="empty-state bot-filter-empty">
              <h2>No matching bots</h2>
              <p>Adjust the search or filters to show more rows.</p>
              <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Mode</th>
                    <th>State</th>
                    <th>Active config</th>
                    <th>Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBots.map((bot) => (
                    <tr key={bot.id}>
                      <td>
                        <Link className="table-link" href={`/bots/${bot.id}`}>
                          {bot.name}
                        </Link>
                        <span className="table-subtitle">{bot.description}</span>
                      </td>
                      <td><StatusPill value={bot.mode} /></td>
                      <td><StatusPill value={bot.state} /></td>
                      <td>{bot.active_config_version_id ? "Active" : "Draft only"}</td>
                      <td>{new Date(bot.updated_at).toLocaleString()}</td>
                      <td><button className="button button-danger" onClick={async () => {
                        if (!window.confirm(`Archive ${bot.name}? Historical results will remain.`)) return;
                        await api(`/api/v1/bots/${bot.id}`, { method: "DELETE" });
                        await client.invalidateQueries({ queryKey: ["bots"] });
                      }}>Delete</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

