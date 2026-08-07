export function StateBadge({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`badge ${ok ? 'ok' : 'muted'}`}>{label}: {ok ? '是' : '否'}</span>
}
