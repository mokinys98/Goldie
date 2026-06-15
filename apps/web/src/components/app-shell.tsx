"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  if (pathname === "/login") return <>{children}</>;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <Link href="/bots" className="brand">
            GOLDIE
          </Link>
          <p className="brand-subtitle">Research control plane</p>
        </div>
        <nav>
          <Link className={pathname.startsWith("/bots") ? "active" : ""} href="/bots">
            Bots
          </Link>
          <Link
            className={pathname.startsWith("/strategies") ? "active" : ""}
            href="/strategies"
          >
            Strategies
          </Link>
          <Link
            className={pathname.startsWith("/collector") ? "active" : ""}
            href="/collector"
          >
            Collector
          </Link>
          <Link
            className={pathname.startsWith("/backtests") ? "active" : ""}
            href="/backtests"
          >
            Backtests
          </Link>
          <Link
            className={pathname.startsWith("/optimizations") ? "active" : ""}
            href="/optimizations"
          >
            Optimization
          </Link>
        </nav>
        <div className="sidebar-bottom">
          <span className="readonly-badge">READ ONLY</span>
          <span className="muted">No order execution</span>
          <button
            className="button button-ghost"
            onClick={() => {
              localStorage.removeItem("goldie_token");
              router.push("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
