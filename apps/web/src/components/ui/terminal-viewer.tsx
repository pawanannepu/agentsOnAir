"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import Ansi from "ansi-to-react";
import { Search, Copy, Check, ArrowDown, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";
import { Input } from "./input";

const MAX_RING_BUFFER_LINES = 10000;

function stripAnsi(text: string): string {
  return text.replace(
    /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g,
    ""
  );
}

export interface TerminalViewerProps {
  logs: string[];
  isStreaming?: boolean;
  className?: string;
  title?: string;
}

export function TerminalViewer({
  logs,
  isStreaming = false,
  className,
  title = "Sandbox Execution Log",
}: TerminalViewerProps) {
  const [searchQuery, setSearchQuery] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const [isPinned, setIsPinned] = React.useState(true);
  const [unreadCount, setUnreadCount] = React.useState(0);

  const parentRef = React.useRef<HTMLDivElement>(null);

  // Apply ring buffer cap
  const cappedLogs = React.useMemo(() => {
    if (logs.length <= MAX_RING_BUFFER_LINES) return logs;
    return logs.slice(logs.length - MAX_RING_BUFFER_LINES);
  }, [logs]);

  // Filter logs based on search query (case insensitive search over plain text)
  const filteredIndices = React.useMemo(() => {
    if (!searchQuery.trim()) {
      return null;
    }
    const q = searchQuery.toLowerCase();
    const indices: number[] = [];
    for (let i = 0; i < cappedLogs.length; i++) {
      if (stripAnsi(cappedLogs[i]).toLowerCase().includes(q)) {
        indices.push(i);
      }
    }
    return indices;
  }, [cappedLogs, searchQuery]);

  const displayCount =
    filteredIndices !== null ? filteredIndices.length : cappedLogs.length;

  const rowVirtualizer = useVirtualizer({
    count: displayCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 22,
    overscan: 20,
  });

  // Track scroll position to engage or disengage auto scroll pin
  const handleScroll = React.useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > 40) {
      if (isPinned) setIsPinned(false);
    } else {
      if (!isPinned) {
        setIsPinned(true);
        setUnreadCount(0);
      }
    }
  }, [isPinned]);

  // Auto scroll when new logs arrive and pinned
  React.useEffect(() => {
    if (isPinned && displayCount > 0) {
      requestAnimationFrame(() => {
        rowVirtualizer.scrollToIndex(displayCount - 1, { align: "end" });
      });
    } else if (!isPinned) {
      setUnreadCount((prev) => prev + 1);
    }
  }, [cappedLogs.length, isPinned, displayCount, rowVirtualizer]);

  const scrollToBottom = React.useCallback(() => {
    setIsPinned(true);
    setUnreadCount(0);
    requestAnimationFrame(() => {
      if (displayCount > 0) {
        rowVirtualizer.scrollToIndex(displayCount - 1, { align: "end" });
      }
    });
  }, [displayCount, rowVirtualizer]);

  // Copy plain text to clipboard
  const handleCopy = React.useCallback(async () => {
    const linesToCopy =
      filteredIndices !== null
        ? filteredIndices.map((idx) => stripAnsi(cappedLogs[idx]))
        : cappedLogs.map((line) => stripAnsi(line));
    await navigator.clipboard.writeText(linesToCopy.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [cappedLogs, filteredIndices]);

  return (
    <div
      className={cn(
        "flex flex-col h-full rounded-xl border border-border bg-zinc-950 font-mono text-xs overflow-hidden shadow-sm",
        className
      )}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-zinc-900/60 backdrop-blur">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-emerald-400" />
          <span className="font-semibold text-zinc-200">{title}</span>
          {isStreaming && (
            <span className="flex items-center gap-1.5 text-[10px] text-emerald-400 font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Search bar */}
          <div className="relative w-44 sm:w-60">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
            <Input
              type="text"
              placeholder="Search logs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-7 pl-8 pr-2 text-xs bg-zinc-900/80 border-zinc-800 text-zinc-200"
            />
          </div>

          {/* Copy button */}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="h-7 px-2.5 text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
            title="Copy clean log lines"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-400 mr-1" />
                <span className="text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5 mr-1" />
                <span>Copy</span>
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Terminal log canvas */}
      <div
        ref={parentRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto p-3 text-zinc-300 relative select-text"
        style={{ minHeight: "260px" }}
      >
        {displayCount === 0 ? (
          <div className="flex items-center justify-center h-full text-zinc-500 italic py-12">
            {searchQuery
              ? "No matching log lines found"
              : "Waiting for log stream..."}
          </div>
        ) : (
          <div
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              width: "100%",
              position: "relative",
            }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const originalIndex =
                filteredIndices !== null
                  ? filteredIndices[virtualRow.index]
                  : virtualRow.index;
              const rawLine = cappedLogs[originalIndex] || "";

              return (
                <div
                  key={virtualRow.index}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: `${virtualRow.size}px`,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  className="flex items-start hover:bg-zinc-900/50 leading-relaxed font-mono whitespace-pre-wrap break-all"
                >
                  <span className="w-12 shrink-0 select-none text-right pr-4 text-zinc-600 text-[11px]">
                    {originalIndex + 1}
                  </span>
                  <span className="flex-1">
                    <Ansi>{rawLine}</Ansi>
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* Floating scroll to bottom button when unpinned */}
        {!isPinned && (
          <button
            onClick={scrollToBottom}
            type="button"
            className="absolute bottom-4 right-4 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 shadow-lg text-xs font-medium hover:bg-emerald-500/30 transition-all animate-bounce"
          >
            <ArrowDown className="h-3.5 w-3.5" />
            <span>Scroll to bottom</span>
            {unreadCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full bg-emerald-500 text-zinc-950 text-[10px] font-bold">
                +{unreadCount}
              </span>
            )}
          </button>
        )}
      </div>

      {/* Terminal footer info */}
      <div className="px-4 py-1.5 border-t border-zinc-800 bg-zinc-900/40 flex justify-between text-[11px] text-zinc-500">
        <span>
          Showing {displayCount} {displayCount === 1 ? "line" : "lines"}
          {filteredIndices !== null && ` (filtered from ${cappedLogs.length})`}
        </span>
        <span className="flex items-center gap-2">
          <span>Auto scroll: {isPinned ? "Locked" : "Paused"}</span>
          <span>
            Buffer: {cappedLogs.length}/{MAX_RING_BUFFER_LINES}
          </span>
        </span>
      </div>
    </div>
  );
}
