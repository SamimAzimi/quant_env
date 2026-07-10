interface Props {
  label: string;
  value: string;           // ISO string with Z suffix, or ''
  onChange: (iso: string) => void;
}

/**
 * Date + time picker that reads/writes UTC, not the browser's local zone.
 * The native datetime-local input's value is taken verbatim as UTC and
 * suffixed with Z — what you pick is what gets stored.
 */
export default function UtcDateTimeInput({ label, value, onChange }: Props) {
  const local = value ? value.replace('Z', '').slice(0, 16) : '';
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="datetime-local"
        value={local}
        onChange={(e) => onChange(e.target.value ? `${e.target.value}:00Z` : '')}
      />
    </label>
  );
}
