export function MarketChart({
  candles,
}: {
  candles: Array<{ close: string; opened_at: string }>;
}) {
  if (candles.length < 2) {
    return <div className="chart-empty">Waiting for completed M1 candles...</div>;
  }
  const values = candles.map((item) => Number(item.close));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 92 - ((value - min) / span) * 80;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="chart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img">
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <div className="chart-labels">
        <span>{min.toFixed(2)}</span>
        <span>{max.toFixed(2)}</span>
      </div>
    </div>
  );
}

