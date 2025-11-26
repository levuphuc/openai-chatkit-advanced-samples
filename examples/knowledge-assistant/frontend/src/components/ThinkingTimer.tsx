import { useEffect, useState } from "react";
import clsx from "clsx";

type ThinkingTimerProps = {
  isWaiting: boolean;
  isResponding: boolean;
  startTime: number | null;
  className?: string;
};

export function ThinkingTimer({ isWaiting, isResponding, startTime, className }: ThinkingTimerProps) {
  const [elapsed, setElapsed] = useState(0);
  const isActive = isWaiting || isResponding;

  useEffect(() => {
    if (!isActive || startTime === null) {
      setElapsed(0);
      return;
    }

    const interval = setInterval(() => {
      const now = Date.now();
      const diff = (now - startTime) / 1000; // Convert to seconds
      setElapsed(diff);
    }, 100); // Update every 100ms for smooth animation

    return () => clearInterval(interval);
  }, [isActive, startTime]);

  if (!isActive || startTime === null) {
    return null;
  }

  const label = isWaiting ? "Đang chờ phản hồi..." : "Đang trả lời...";
  const bgColor = isWaiting
    ? "bg-amber-50 dark:bg-amber-950/30"
    : "bg-blue-50 dark:bg-blue-950/30";
  const textColor = isWaiting
    ? "text-amber-700 dark:text-amber-300"
    : "text-blue-700 dark:text-blue-300";
  const dotColor = isWaiting ? "bg-amber-500" : "bg-blue-500";

  return (
    <div
      className={clsx(
        "flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium shadow-sm",
        bgColor,
        textColor,
        className
      )}
    >
      <div className="flex gap-1">
        <span className={clsx("inline-block h-1.5 w-1.5 animate-bounce rounded-full", dotColor)} style={{ animationDelay: "0ms" }} />
        <span className={clsx("inline-block h-1.5 w-1.5 animate-bounce rounded-full", dotColor)} style={{ animationDelay: "150ms" }} />
        <span className={clsx("inline-block h-1.5 w-1.5 animate-bounce rounded-full", dotColor)} style={{ animationDelay: "300ms" }} />
      </div>
      <span className="tabular-nums">
        {label} {elapsed.toFixed(1)}s
      </span>
    </div>
  );
}
