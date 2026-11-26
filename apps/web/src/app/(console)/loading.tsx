export default function HomeLoading() {
  return (
    <div className="space-y-6">
      <div className="h-16 rounded-xl bg-muted/40 animate-pulse" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="h-28 rounded-xl border border-border bg-card animate-pulse" />
        <div className="h-28 rounded-xl border border-border bg-card animate-pulse" />
        <div className="h-28 rounded-xl border border-border bg-card animate-pulse" />
        <div className="h-28 rounded-xl border border-border bg-card animate-pulse" />
      </div>
    </div>
  );
}
