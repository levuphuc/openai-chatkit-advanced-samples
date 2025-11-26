import clsx from "clsx";

type TimeBadgeProps = {
  seconds: number | null;
  isWaiting: boolean;
  isResponding: boolean;
  className?: string;
};

export function TimeBadge({ seconds, isWaiting, isResponding, className }: TimeBadgeProps) {
  const label = seconds !== null ? `${seconds.toFixed(1)}s` : "";
  const bg = isWaiting
    ? "bg-amber-50 dark:bg-amber-950/30"
    : isResponding
      ? "bg-blue-50 dark:bg-blue-950/30"
      : "bg-slate-100 dark:bg-slate-800/60";
  const text = isWaiting
    ? "text-amber-700 dark:text-amber-300"
    : isResponding
      ? "text-blue-700 dark:text-blue-300"
      : "text-slate-600 dark:text-slate-300";

  // Always visible; if no seconds yet, render placeholder width to avoid layout shift
  const content = label || "0.0s";

  return (
    <div
      className={clsx(
        "pointer-events-none inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium shadow-sm",
        bg,
        text,
        "tabular-nums",
        className,
      )}
      aria-label="processing-time"
    >
      {content}
    </div>
  );
}
