"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StrategyProfile } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function StrategiesPage() {
  const query = useQuery({
    queryKey: ["strategy-profiles"],
    queryFn: () => api<StrategyProfile[]>("/api/v1/strategy-profiles"),
  });
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">GLOBAL CONFIGURATION</span>
          <h1>Strategies</h1>
          <p>Versioned trading configurations shared by bot instances.</p>
        </div>
        <Link className="button button-primary" href="/strategies/new">Create strategy</Link>
      </header>
      {query.isLoading && <div className="panel">Loading strategies...</div>}
      {query.error && <div className="error-box">{query.error.message}</div>}
      {query.data?.length === 0 && <div className="empty-state">No global strategies yet.</div>}
      {!!query.data?.length && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Published</th><th>Algorithm</th><th>Bots</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>
              {query.data.map((profile) => (
                <tr key={profile.id}>
                  <td><Link className="table-link" href={`/strategies/${profile.id}`}>{profile.name}</Link><span className="table-subtitle">{profile.description}</span></td>
                  <td>{profile.published_version ? `v${profile.published_version.version}` : "--"}</td>
                  <td>{profile.published_version?.config.strategy.name ?? "--"}</td>
                  <td>{profile.bot_count}</td>
                  <td><StatusPill value={profile.status} /></td>
                  <td>{new Date(profile.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
