export function FieldHelp({
  label,
  metadata,
}: {
  label: string;
  metadata?: {
    description?: string;
    unit?: string;
    minimum?: number;
    maximum?: number;
    exclusiveMinimum?: number;
    default?: string | number | boolean;
    impact?: string;
  };
}) {
  const range = [
    metadata?.exclusiveMinimum !== undefined
      ? `>${metadata.exclusiveMinimum}`
      : metadata?.minimum,
    metadata?.maximum,
  ]
    .filter((value) => value !== undefined)
    .join(" - ");
  const text = [
    metadata?.description,
    metadata?.unit ? `Unit: ${metadata.unit}.` : "",
    range ? `Allowed range: ${range}.` : "",
    metadata?.default !== undefined ? `Default: ${String(metadata.default)}.` : "",
    metadata?.impact,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className="field-label">
      {label}
      <span
        role="button"
        tabIndex={0}
        className="field-help"
        aria-label={`${label}. ${text}`}
        data-tooltip={text}
      >
        ?
      </span>
    </span>
  );
}
