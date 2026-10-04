import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
    ArrowRightIcon,
    EyeSlashIcon,
    KeyIcon,
    PauseIcon,
    PlayIcon,
    StopIcon,
    VideoCameraIcon,
} from "@heroicons/react/24/solid";
import { useMain } from "../../context/MainContext";
import { formatClock, formatDate, formatDuration, isUntitled, taskTitle } from "../../lib/format";
import { Button, Card, Kbd, PageHeader, cx } from "../ui";
import { RecordingStatusBadge } from "../Recordings/RecordingsPage";

function StatusDisplay() {
    const { isRecording, isPaused, elapsedSeconds } = useMain();
    const state = !isRecording ? "ready" : isPaused ? "paused" : "recording";
    const styles = {
        ready: {
            ring: "ring-zinc-200 dark:ring-zinc-800",
            dot: "bg-zinc-300 dark:bg-zinc-600",
            label: "Ready to record",
            text: "text-zinc-500 dark:text-zinc-400",
        },
        recording: {
            ring: "ring-red-200 dark:ring-red-500/30",
            dot: "bg-red-500 animate-pulse",
            label: "Recording",
            text: "text-red-600 dark:text-red-400",
        },
        paused: {
            ring: "ring-amber-200 dark:ring-amber-500/30",
            dot: "bg-amber-500",
            label: "Paused — nothing is being captured",
            text: "text-amber-700 dark:text-amber-400",
        },
    }[state];

    return (
        <div className="flex flex-col items-center">
            <div
                className={cx(
                    "flex h-40 w-40 flex-col items-center justify-center rounded-full bg-white ring-8 dark:bg-zinc-900",
                    styles.ring
                )}
            >
                <span className={cx("mb-2 h-3 w-3 rounded-full", styles.dot)} />
                <span className="font-mono text-3xl font-semibold tabular-nums tracking-tight text-zinc-900 dark:text-zinc-50">
                    {formatClock(elapsedSeconds)}
                </span>
            </div>
            <p className={cx("mt-4 text-sm font-medium", styles.text)}>{styles.label}</p>
        </div>
    );
}

function Controls() {
    const { isRecording, isPaused, busy, startRecording, stopRecording, togglePause, myos } = useMain();
    const mod = myos === "darwin" ? "⌘ ⌥" : "Ctrl Alt";

    return (
        <div className="mt-8 flex flex-col items-center gap-4">
            {!isRecording ? (
                <Button
                    variant="primary"
                    size="lg"
                    loading={busy}
                    icon={<VideoCameraIcon className="h-5 w-5" />}
                    onClick={startRecording}
                    className="min-w-[14rem]"
                >
                    Start recording
                </Button>
            ) : (
                <div className="flex gap-3">
                    <Button
                        variant={isPaused ? "primary" : "warning"}
                        size="lg"
                        disabled={busy}
                        icon={isPaused ? <PlayIcon className="h-5 w-5" /> : <PauseIcon className="h-5 w-5" />}
                        onClick={togglePause}
                        className="min-w-[9rem]"
                    >
                        {isPaused ? "Resume" : "Pause"}
                    </Button>
                    <Button
                        variant="danger"
                        size="lg"
                        loading={busy}
                        icon={<StopIcon className="h-5 w-5" />}
                        onClick={stopRecording}
                        className="min-w-[9rem]"
                    >
                        Stop
                    </Button>
                </div>
            )}
            <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-zinc-500 dark:text-zinc-400">
                <span className="flex items-center gap-1.5">
                    <Kbd>{mod} R</Kbd> Start
                </span>
                <span className="flex items-center gap-1.5">
                    <Kbd>{mod} P</Kbd> Pause / resume
                </span>
                <span className="flex items-center gap-1.5">
                    <Kbd>{mod} T</Kbd> Stop
                </span>
            </div>
        </div>
    );
}

function A11yToggle() {
    const { SocketService, isRecording } = useMain();
    const [enabled, setEnabled] = useState(false);
    useEffect(() => {
        SocketService.Send("toggle_generate_window_a11y", { flag: false });
    }, [SocketService]);
    return (
        <label className="mt-8 flex max-w-md items-start gap-3 rounded-lg p-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
            <input
                type="checkbox"
                checked={enabled}
                disabled={isRecording}
                onChange={() => {
                    SocketService.Send("toggle_generate_window_a11y", { flag: !enabled });
                    setEnabled(!enabled);
                }}
                className="mt-0.5 h-4 w-4 rounded border-zinc-300 text-indigo-600 focus:ring-indigo-600"
            />
            <span>
                <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                    Capture full window accessibility trees
                </span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                    Richer UI structure for every screen change. Uses more CPU; set before starting.
                </span>
            </span>
        </label>
    );
}

const TIPS = [
    {
        icon: <EyeSlashIcon className="h-5 w-5 text-indigo-500" />,
        title: "Close what you don't want captured",
        text: "Everything on your main display is recorded, including notifications.",
    },
    {
        icon: <KeyIcon className="h-5 w-5 text-indigo-500" />,
        title: "Pause for passwords and personal data",
        text: "Keystrokes are recorded. Pause before entering credentials or payment details.",
    },
    {
        icon: <PlayIcon className="h-5 w-5 text-indigo-500" />,
        title: "One task per recording",
        text: "Perform a single workflow end to end, then name it when you review.",
    },
];

export default function Homepage() {
    const { recordings } = useMain();
    const navigate = useNavigate();
    const recent = [...recordings]
        .sort((a, b) => (a.creation_time < b.creation_time ? 1 : -1))
        .slice(0, 5);

    return (
        <div className="flex-1 overflow-y-auto">
            <PageHeader
                title="Record"
                description="Capture a computer task: screen, mouse, keyboard and the apps you use."
            />
            <div className="grid gap-6 p-8 xl:grid-cols-[1fr_22rem]">
                <Card className="flex flex-col items-center px-8 py-12">
                    <StatusDisplay />
                    <Controls />
                    <A11yToggle />
                </Card>

                <div className="flex flex-col gap-6">
                    <Card className="p-5">
                        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Before you record</h2>
                        <ul className="mt-4 space-y-4">
                            {TIPS.map((tip) => (
                                <li key={tip.title} className="flex gap-3">
                                    <span className="mt-0.5 shrink-0">{tip.icon}</span>
                                    <span>
                                        <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                                            {tip.title}
                                        </span>
                                        <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                                            {tip.text}
                                        </span>
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </Card>

                    <Card>
                        <div className="flex items-center justify-between px-5 pt-4">
                            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Recent recordings</h2>
                            <Link
                                to="/recordings"
                                className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
                            >
                                View all <ArrowRightIcon className="h-3 w-3" />
                            </Link>
                        </div>
                        {recent.length === 0 ? (
                            <p className="px-5 py-6 text-sm text-zinc-500 dark:text-zinc-400">No recordings yet.</p>
                        ) : (
                            <ul className="mt-2 divide-y divide-zinc-100 dark:divide-zinc-800">
                                {recent.map((r) => (
                                    <li key={r.name}>
                                        <button
                                            disabled={r.status === "processing"}
                                            onClick={() => navigate(`/recordings/${r.name}`)}
                                            className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-zinc-50 disabled:cursor-default disabled:hover:bg-transparent dark:hover:bg-zinc-800/50"
                                        >
                                            <span className="min-w-0 flex-1">
                                                <span
                                                    className={cx(
                                                        "block truncate text-sm font-medium",
                                                        isUntitled(r.task_name)
                                                            ? "text-zinc-400 dark:text-zinc-500"
                                                            : "text-zinc-800 dark:text-zinc-200"
                                                    )}
                                                >
                                                    {taskTitle(r.task_name)}
                                                </span>
                                                <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                                                    {formatDate(r.creation_time)} · {formatDuration(r.duration)}
                                                </span>
                                            </span>
                                            <RecordingStatusBadge recording={r} />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Card>
                </div>
            </div>
        </div>
    );
}
