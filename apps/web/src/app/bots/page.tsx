"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Bot } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function BotsPage() {
  const router = useRouter();
  const query = useQuery({
    queryKey: ["bots"],
    queryFn: () => api<Bot[]>("/api/v1/bots"),
  });

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
        <Link className="button button-primary" href="/bots/new">
          Create bot
        </Link>
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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Mode</th>
                <th>State</th>
                <th>Active config</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {query.data.map((bot) => (
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

