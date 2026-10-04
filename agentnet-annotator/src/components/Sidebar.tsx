import React from "react";
import { NavLink } from "react-router-dom";
import {
    Cog6ToothIcon,
    FilmIcon,
    PauseIcon,
    PlayIcon,
    StopIcon,
    VideoCameraIcon,
} from "@heroicons/react/24/outline";
import { useMain } from "../context/MainContext";
import { formatClock } from "../lib/format";
import { cx } from "./ui";

function NavItem({
    to,
    icon,
    label,
    count,
}: {
    to: string;
    icon: React.ReactNode;
    label: string;
    count?: number;
}) {
    return (
        <NavLink
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
                cx(
                    "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                        ? "bg-zinc-900/5 text-zinc-900 dark:bg-white/10 dark:text-white"
                        : "text-zinc-600 hover:bg-zinc-900/5 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-white"
                )
            }
        >
            <span className="h-5 w-5 shrink-0">{icon}</span>
            <span className="flex-1">{label}</span>
            {count != null && count > 0 && (
                <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                    {count}
                </span>
            )}
        </NavLink>
    );
}

function RecordingPill() {
    const { isRecording, isPaused, elapsedSeconds, togglePause, stopRecording, busy } = useMain();
    if (!isRecording) return null;
    return (
        <div
            className={cx(
                "rounded-xl p-3 ring-1",
                isPaused
                    ? "bg-amber-50 ring-amber-200 dark:bg-amber-500/10 dark:ring-amber-500/30"
                    : "bg-red-50 ring-red-200 dark:bg-red-500/10 dark:ring-red-500/30"
            )}
        >
            <div className="flex items-center gap-2 text-sm font-medium">
                <span
                    className={cx(
                        "h-2 w-2 rounded-full",
                        isPaused ? "bg-amber-500" : "animate-pulse bg-red-500"
                    )}
                />
                <span className={isPaused ? "text-amber-800 dark:text-amber-300" : "text-red-700 dark:text-red-300"}>
                    {isPaused ? "Paused" : "Recording"}
                </span>
                <span className="ml-auto font-mono tabular-nums text-zinc-700 dark:text-zinc-300">
                    {formatClock(elapsedSeconds)}
                </span>
            </div>
            <div className="mt-2 flex gap-2">
                <button
                    onClick={togglePause}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-1 rounded-md bg-white py-1 text-xs font-medium text-zinc-700 ring-1 ring-zinc-200 hover:bg-zinc-50 disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-200 dark:ring-zinc-700"
                >
                    {isPaused ? <PlayIcon className="h-3.5 w-3.5" /> : <PauseIcon className="h-3.5 w-3.5" />}
                    {isPaused ? "Resume" : "Pause"}
                </button>
                <button
                    onClick={stopRecording}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-1 rounded-md bg-white py-1 text-xs font-medium text-red-700 ring-1 ring-zinc-200 hover:bg-zinc-50 disabled:opacity-50 dark:bg-zinc-800 dark:text-red-300 dark:ring-zinc-700"
                >
                    <StopIcon className="h-3.5 w-3.5" />
                    Stop
                </button>
            </div>
        </div>
    );
}

export default function Sidebar() {
    const { recordings } = useMain();
    return (
        <aside className="flex w-60 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex h-14 items-center gap-2 px-5">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
                    c
                </div>
                <span className="text-base font-semibold tracking-tight text-zinc-900 dark:text-white">cudAI</span>
            </div>
            <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
                <NavItem to="/" label="Record" icon={<VideoCameraIcon />} />
                <NavItem to="/recordings" label="Recordings" icon={<FilmIcon />} count={recordings.length} />
                <NavItem to="/settings" label="Settings" icon={<Cog6ToothIcon />} />
            </nav>
            <div className="p-3">
                <RecordingPill />
            </div>
        </aside>
    );
}
