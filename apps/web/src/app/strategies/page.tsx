"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StrategyProfile } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function StrategiesPage() {
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [algorithmFilter, setAlgorithmFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [botUsageFilter, setBotUsageFilter] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const query = useQuery({
    queryKey: ["strategy-profiles"],
    queryFn: () => api<StrategyProfile[]>("/api/v1/strategy-profiles"),
  });
  const strategies = useMemo(() => query.data ?? [], [query.data]);
  const algorithms = useMemo(
    () => [...new Set(strategies.map((profile) => profile.config.strategy.name))].sort(),
    [strategies],
  );
  const statuses = useMemo(
    () => [...new Set(strategies.map((profile) => profile.status))].sort(),
    [strategies],
  );
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredStrategies = strategies.filter((profile) => (
    (!normalizedSearch
      || profile.name.toLocaleLowerCase().includes(normalizedSearch)
      || profile.description.toLocaleLowerCase().includes(normalizedSearch))
    && (!algorithmFilter || profile.config.strategy.name === algorithmFilter)
    && (!statusFilter || profile.status === statusFilter)
    && (!botUsageFilter
      || (botUsageFilter === "with-bots" ? profile.bot_count > 0 : profile.bot_count === 0))
  ));
  const filtersActive = Boolean(search || algorithmFilter || statusFilter || botUsageFilter);

  function clearFilters() {
    setSearch("");
    setAlgorithmFilter("");
    setStatusFilter("");
    setBotUsageFilter("");
  }

  async function deleteStrategy(profile: StrategyProfile) {
    const linkedBots = profile.bot_count === 1 ? "1 linked bot" : `${profile.bot_count} linked bots`;
    if (!window.confirm(`Archive ${profile.name}? ${linkedBots} and historical results will remain.`)) return;

    setDeletingId(profile.id);
    setDeleteError("");
    try {
      await api(`/api/v1/strategy-profiles/${profile.id}`, { method: "DELETE" });
      await client.invalidateQueries({ queryKey: ["strategy-profiles"] });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Strategy could not be deleted.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">GLOBAL CONFIGURATION</span>
          <h1>Strategies</h1>
          <p>Current trading configurations shared by bot instances.</p>
        </div>
        <div className="button-row">
          <Link className="button button-secondary" href="/strategies/bulk">
            Bulk bots creation
          </Link>
          <Link className="button button-primary" href="/strategies/new">Create strategy</Link>
        </div>
      </header>
      {query.isLoading && <div className="panel">Loading strategies...</div>}
      {query.error && <div className="error-box">{query.error.message}</div>}
      {deleteError && <div className="error-box" role="alert">{deleteError}</div>}
      {query.data?.length === 0 && <div className="empty-state">No global strategies yet.</div>}
      {!!query.data?.length && (
        <>
          <div className="panel bot-filter-panel">
            <label className="bot-filter-search">
              Search strategy
              <input
                type="search"
                placeholder="Name or description..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <label>
              Algorithm
              <select value={algorithmFilter} onChange={(event) => setAlgorithmFilter(event.target.value)}>
                <option value="">All algorithms</option>
                {algorithms.map((algorithm) => <option key={algorithm} value={algorithm}>{algorithm}</option>)}
              </select>
            </label>
            <label>
              Status
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">All statuses</option>
                {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
            <label>
              Bots
              <select value={botUsageFilter} onChange={(event) => setBotUsageFilter(event.target.value)}>
                <option value="">Any bot count</option>
                <option value="with-bots">With bots</option>
                <option value="without-bots">No bots</option>
              </select>
            </label>
            <div className="bot-filter-summary">
              <span aria-live="polite">Showing <strong>{filteredStrategies.length}</strong> of {strategies.length} strategies</span>
              <button className="button button-secondary" disabled={!filtersActive} type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          </div>
          {!filteredStrategies.length ? (
            <div className="empty-state bot-filter-empty">
              <h2>No matching strategies</h2>
              <p>Adjust the search or filters to show more rows.</p>
              <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>Algorithm</th><th>Bots</th><th>Status</th><th>Updated</th><th>Actions</th></tr></thead>
                <tbody>
                  {filteredStrategies.map((profile) => (
                    <tr key={profile.id}>
                      <td><Link className="table-link" href={`/strategies/${profile.id}`}>{profile.name}</Link><span className="table-subtitle">{profile.description}</span></td>
                      <td>{profile.config.strategy.name}</td>
                      <td>{profile.bot_count}</td>
                      <td><StatusPill value={profile.status} /></td>
                      <td>{new Date(profile.updated_at).toLocaleString()}</td>
                      <td>
                        <button
                          className="button button-danger"
                          disabled={deletingId !== null}
                          type="button"
                          onClick={() => deleteStrategy(profile)}
                        >
                          {deletingId === profile.id ? "Deleting..." : "Delete"}
                        </button>
                      </td>
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
