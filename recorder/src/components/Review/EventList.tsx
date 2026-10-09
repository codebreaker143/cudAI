import React, { useEffect, useMemo, useRef, useState } from "react";
import { TimelineEvent } from "../../lib/api";
import { formatPrecise, keySymbol } from "../../lib/format";
import { Badge, cx } from "../ui";

type Filter = "all" | "mouse" | "keyboard" | "window";

const FILTERS: { key: Filter; label: string }[] = [
    { key: "all", label: "All" },
    { key: "mouse", label: "Mouse" },
    { key: "keyboard", label: "Keyboard" },
    { key: "window", label: "Apps & windows" },
];

const ROW_HEIGHT = 40;
const OVERSCAN = 10;

function matches(e: TimelineEvent, filter: Filter, showReleases: boolean) {
    if (!showReleases && (e.type === "release" || (e.type === "click" && e.pressed === false))) {
        return false;
    }
    switch (filter) {
        case "mouse":
            return e.type === "click" || e.type === "scroll";
        case "keyboard":
            return e.type === "press" || e.type === "release";
        case "window":
            return e.type === "window";
        default:
            return true;
    }
}

function describe(e: TimelineEvent): { badge: React.ReactNode; text: string } {
    switch (e.type) {
        case "click":
            return {
                badge: <Badge tone="indigo">{e.pressed ? "Mouse down" : "Mouse up"}</Badge>,
                text: `${e.button} at ${Math.round(e.x!)}, ${Math.round(e.y!)}`,
            };
        case "scroll":
            return {
                badge: <Badge tone="sky">Scroll</Badge>,
                text: `Δx ${e.dx}, Δy ${e.dy} at ${Math.round(e.x!)}, ${Math.round(e.y!)}`,
            };
        case "press":
        case "release": {
            const combo = [...(e.modifiers || []).map(keySymbol), keySymbol(e.name || "?")].join(" ");
            const typed = e.text ? `  “${e.text}”` : "";
            return {
                badge: <Badge tone={e.type === "press" ? "green" : "neutral"}>{e.type === "press" ? "Key down" : "Key up"}</Badge>,
                text: combo + typed,
            };
        }
        case "window":
            return {
                badge: <Badge tone={e.is_recorder ? "neutral" : "violet"}>{e.is_recorder ? "cudAI" : "App"}</Badge>,
                text: [e.app_name, e.window_title, e.url].filter(Boolean).join(" — "),
            };
        default:
            return { badge: <Badge>{e.type}</Badge>, text: "" };
    }
}

export default function EventList({
    events,
    currentTime,
    onJump,
}: {
    events: TimelineEvent[];
    currentTime: number;
    onJump: (time: number) => void;
}) {
    const [filter, setFilter] = useState<Filter>("all");
    const [showReleases, setShowReleases] = useState(false);
    const [scrollTop, setScrollTop] = useState(0);
    const [height, setHeight] = useState(600);
    const scrollRef = useRef<HTMLDivElement>(null);

    const rows = useMemo(
        () => events.filter((e) => matches(e, filter, showReleases)),
        [events, filter, showReleases]
    );

    const currentIndex = useMemo(() => {
        let lo = 0;
        let hi = rows.length - 1;
        let found = -1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (rows[mid].t_video <= currentTime) {
                found = mid;
                lo = mid + 1;
            } else hi = mid - 1;
        }
        return found;
    }, [rows, currentTime]);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        const observer = new ResizeObserver(() => setHeight(el.clientHeight));
        observer.observe(el);
        return () => observer.disconnect();
    }, []);

    const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
    const last = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW_HEIGHT) + OVERSCAN);

    const jumpToNow = () => {
        if (currentIndex >= 0 && scrollRef.current) {
            scrollRef.current.scrollTop = currentIndex * ROW_HEIGHT - height / 2;
        }
    };

    return (
        <div className="flex h-full flex-col">
            <div className="flex flex-wrap items-center gap-1.5 border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
                {FILTERS.map((f) => (
                    <button
                        key={f.key}
                        onClick={() => setFilter(f.key)}
                        className={cx(
                            "rounded-full px-2.5 py-1 text-xs font-medium",
                            filter === f.key
                                ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                        )}
                    >
                        {f.label}
                    </button>
                ))}
                <label className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                    <input
                        type="checkbox"
                        checked={showReleases}
                        onChange={(e) => setShowReleases(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-zinc-300 text-indigo-600 focus:ring-indigo-600"
                    />
                    Releases
                </label>
                <button
                    onClick={jumpToNow}
                    className="text-xs font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
                >
                    Go to playhead
                </button>
            </div>
            <div
                ref={scrollRef}
                className="min-h-0 flex-1 overflow-y-auto"
                onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            >
                {rows.length === 0 ? (
                    <p className="p-6 text-center text-sm text-zinc-500">No events for this filter.</p>
                ) : (
                    <div style={{ height: rows.length * ROW_HEIGHT, position: "relative" }}>
                        {rows.slice(first, last).map((e, i) => {
                            const index = first + i;
                            const { badge, text } = describe(e);
                            return (
                                <button
                                    key={index}
                                    onClick={() => onJump(e.t_video)}
                                    className={cx(
                                        "absolute inset-x-0 flex items-center gap-3 px-4 text-left text-xs",
                                        index === currentIndex
                                            ? "bg-indigo-50/70 dark:bg-indigo-500/10"
                                            : "hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                                    )}
                                    style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
                                >
                                    <span className="w-14 shrink-0 font-mono tabular-nums text-zinc-500 dark:text-zinc-400">
                                        {formatPrecise(e.t_video)}
                                    </span>
                                    <span className="w-24 shrink-0">{badge}</span>
                                    <span className="truncate text-zinc-700 dark:text-zinc-300" title={text}>
                                        {text}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
