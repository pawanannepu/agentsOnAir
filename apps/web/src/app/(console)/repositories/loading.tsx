export default function RepositoriesLoading() {
  return (
    <div className="space-y-6">
      <div className="h-14 rounded-xl bg-muted/40 animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="h-56 rounded-xl border border-border bg-card animate-pulse" />
        <div className="h-56 rounded-xl border border-border bg-card animate-pulse" />
        <div className="h-56 rounded-xl border border-border bg-card animate-pulse" />
      </div>
    </div>
  );
}
