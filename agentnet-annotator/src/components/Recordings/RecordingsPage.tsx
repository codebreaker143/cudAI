import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    ChevronDownIcon,
    ChevronUpIcon,
    FilmIcon,
    MagnifyingGlassIcon,
} from "@heroicons/react/20/solid";
import { useMain } from "../../context/MainContext";
import { RecordingSummary } from "../../lib/api";
import { formatDate, formatDuration, isUntitled, taskTitle } from "../../lib/format";
import { Badge, Button, Card, EmptyState, PageHeader, Spinner, cx } from "../ui";

export function RecordingStatusBadge({ recording }: { recording: RecordingSummary }) {
    if (recording.status === "processing") {
        return (
            <Badge tone="sky">
                <Spinner className="h-3 w-3" /> Processing
            </Badge>
        );
    }
    if (!recording.visualizable || recording.broken) {
        return <Badge tone="neutral">No actions</Badge>;
    }
    return <Badge tone="green">Ready</Badge>;
}

type SortKey = "creation_time" | "task_name" | "duration" | "action_count";

const COLUMNS: { key: SortKey; label: string; className?: string }[] = [
    { key: "task_name", label: "Task" },
    { key: "creation_time", label: "Recorded", className: "w-48" },
    { key: "duration", label: "Duration", className: "w-24" },
    { key: "action_count", label: "Actions", className: "w-20" },
];
const TH = "px-4 py-2.5 text-left text-xs font-medium text-zinc-500 dark:text-zinc-400";

export default function RecordingsPage() {
    const { recordings, recordingsLoaded } = useMain();
    const navigate = useNavigate();
    const [query, setQuery] = useState("");
    const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
        key: "creation_time",
        desc: true,
    });

    const rows = useMemo(() => {
        const q = query.trim().toLowerCase();
        const filtered = recordings.filter(
            (r) =>
                !q ||
                r.task_name?.toLowerCase().includes(q) ||
                (r.apps || []).some((a) => a.toLowerCase().includes(q))
        );
        return filtered.sort((a, b) => {
            const av = (a[sort.key] ?? "") as any;
            const bv = (b[sort.key] ?? "") as any;
            const cmp = av < bv ? -1 : av > bv ? 1 : 0;
            return sort.desc ? -cmp : cmp;
        });
    }, [recordings, query, sort]);

    const toggleSort = (key: SortKey) =>
        setSort((prev) => ({ key, desc: prev.key === key ? !prev.desc : key !== "task_name" }));

    return (
        <div className="flex-1 overflow-y-auto">
            <PageHeader
                title="Recordings"
                description="Review, annotate and name your recorded tasks."
                actions={
                    <Button variant="primary" onClick={() => navigate("/")}>
                        New recording
                    </Button>
                }
            />
            <div className="p-8">
                <div className="mb-4 flex items-center gap-3">
                    <div className="relative w-80">
                        <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search by task or app"
                            className="block w-full rounded-lg border-0 bg-white py-2 pl-9 pr-3 text-sm text-zinc-900 shadow-sm ring-1 ring-inset ring-zinc-300 placeholder:text-zinc-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 dark:bg-zinc-900 dark:text-zinc-100 dark:ring-zinc-700"
                        />
                    </div>
                    <span className="text-sm text-zinc-500 dark:text-zinc-400">
                        {rows.length} of {recordings.length}
                    </span>
                </div>

                <Card className="overflow-hidden">
                    {!recordingsLoaded ? (
                        <div className="flex justify-center py-16 text-zinc-400">
                            <Spinner />
                        </div>
                    ) : rows.length === 0 ? (
                        <EmptyState
                            icon={<FilmIcon className="h-10 w-10" />}
                            title={recordings.length === 0 ? "No recordings yet" : "No matching recordings"}
                            description={
                                recordings.length === 0
                                    ? "Start a recording and it will appear here once processed."
                                    : "Try a different search."
                            }
                            action={
                                recordings.length === 0 && (
                                    <Button variant="primary" onClick={() => navigate("/")}>
                                        Start recording
                                    </Button>
                                )
                            }
                        />
                    ) : (
                        <table className="w-full table-fixed divide-y divide-zinc-200 dark:divide-zinc-800">
                            <thead className="bg-zinc-50 dark:bg-zinc-900/60">
                                <tr>
                                    {COLUMNS.map((col) => (
                                        <th
                                            key={col.key}
                                            className={cx(TH, col.className)}
                                        >
                                            <button
                                                onClick={() => toggleSort(col.key)}
                                                className="inline-flex items-center gap-1 hover:text-zinc-900 dark:hover:text-zinc-100"
                                            >
                                                {col.label}
                                                {sort.key === col.key &&
                                                    (sort.desc ? (
                                                        <ChevronDownIcon className="h-3.5 w-3.5" />
                                                    ) : (
                                                        <ChevronUpIcon className="h-3.5 w-3.5" />
                                                    ))}
                                            </button>
                                        </th>
                                    ))}
                                    <th className={cx(TH, "w-64")}>Apps</th>
                                    <th className={cx(TH, "w-32")}>Status</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-100 bg-white dark:divide-zinc-800 dark:bg-zinc-900">
                                {rows.map((r) => {
                                    const openable = r.status !== "processing";
                                    return (
                                        <tr
                                            key={r.name}
                                            onClick={() => openable && navigate(`/recordings/${r.name}`)}
                                            className={cx(
                                                "text-sm",
                                                openable
                                                    ? "cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                                                    : "opacity-70"
                                            )}
                                        >
                                            <td className="px-4 py-3">
                                                <div
                                                    className={cx(
                                                        "truncate font-medium",
                                                        isUntitled(r.task_name)
                                                            ? "text-zinc-400 dark:text-zinc-500"
                                                            : "text-zinc-900 dark:text-zinc-100"
                                                    )}
                                                >
                                                    {taskTitle(r.task_name)}
                                                </div>
                                                {r.task_description && (
                                                    <div className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                                                        {r.task_description}
                                                    </div>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                                                {formatDate(r.creation_time)}
                                            </td>
                                            <td className="px-4 py-3 tabular-nums text-zinc-600 dark:text-zinc-400">
                                                {formatDuration(r.duration)}
                                            </td>
                                            <td className="px-4 py-3 tabular-nums text-zinc-600 dark:text-zinc-400">
                                                {r.action_count ?? "—"}
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex gap-1 overflow-hidden">
                                                    {(r.apps || []).slice(0, 3).map((app) => (
                                                        <Badge key={app}>{app}</Badge>
                                                    ))}
                                                    {(r.apps || []).length > 3 && (
                                                        <Badge>+{(r.apps || []).length - 3}</Badge>
                                                    )}
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <RecordingStatusBadge recording={r} />
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </Card>
            </div>
        </div>
    );
}
