export default function TaskDetailLoading() {
  return (
    <div className="space-y-6">
      <div className="h-16 rounded-xl bg-muted/40 animate-pulse" />
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-4 h-96 rounded-xl border border-border bg-card animate-pulse" />
        <div className="lg:col-span-8 h-[580px] rounded-xl border border-border bg-card animate-pulse" />
      </div>
    </div>
  );
}
