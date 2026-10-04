import React, { useCallback, useEffect, useState } from "react";
import { CheckCircleIcon, ExclamationCircleIcon } from "@heroicons/react/20/solid";
import { api } from "../../lib/api";
import { Button, Card, cx } from "../ui";

export interface PermissionItem {
    label: string;
    reason: string;
    settings_url: string;
    granted: boolean;
}

export interface PermissionState {
    all_granted: boolean;
    permissions: Record<string, PermissionItem>;
}

export function usePermissions(pollMs = 0) {
    const [state, setState] = useState<PermissionState | null>(null);
    const refresh = useCallback(async () => {
        try {
            setState(await api.get<PermissionState>("/api/permissions"));
        } catch {
            // Backend still starting: retry until it answers.
            setTimeout(refresh, 1000);
        }
    }, []);
    useEffect(() => {
        refresh();
        if (!pollMs) return;
        const timer = setInterval(refresh, pollMs);
        return () => clearInterval(timer);
    }, [refresh, pollMs]);
    return { state, refresh };
}

export function PermissionList({
    state,
    onChanged,
}: {
    state: PermissionState;
    onChanged: () => void;
}) {
    const [requested, setRequested] = useState<Record<string, boolean>>({});

    const allow = async (name: string, item: PermissionItem) => {
        if (!requested[name]) {
            // First time: macOS shows its own prompt.
            setRequested((r) => ({ ...r, [name]: true }));
            await api.post("/api/permissions/request", { name }).catch(() => undefined);
            onChanged();
        } else {
            window.electron.ipcRenderer.sendMessage("open-system-settings", item.settings_url);
        }
    };

    return (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {Object.entries(state.permissions).map(([name, item]) => (
                <li key={name} className="flex items-center gap-4 px-5 py-4">
                    {item.granted ? (
                        <CheckCircleIcon className="h-6 w-6 shrink-0 text-emerald-500" />
                    ) : (
                        <ExclamationCircleIcon className="h-6 w-6 shrink-0 text-amber-500" />
                    )}
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{item.label}</p>
                        <p className="text-xs text-zinc-500 dark:text-zinc-400">{item.reason}</p>
                    </div>
                    {item.granted ? (
                        <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">Allowed</span>
                    ) : (
                        <Button size="sm" variant="primary" onClick={() => allow(name, item)}>
                            {requested[name] ? "Open System Settings" : "Allow"}
                        </Button>
                    )}
                </li>
            ))}
        </ul>
    );
}

export default function PermissionsSetup({ onContinue }: { onContinue: () => void }) {
    const { state, refresh } = usePermissions(2000);

    useEffect(() => {
        if (state?.all_granted) onContinue();
    }, [state, onContinue]);

    return (
        <div className="flex h-full items-center justify-center overflow-y-auto bg-zinc-50 px-6 py-12 dark:bg-zinc-950">
            <div className="w-full max-w-xl">
                <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                    Allow cudAI to record
                </h1>
                <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                    macOS needs your permission for each part of a recording. Without all three, recordings
                    would be incomplete, so recording stays off until they are allowed.
                </p>
                <Card className="mt-6">
                    {state ? (
                        <PermissionList state={state} onChanged={refresh} />
                    ) : (
                        <p className="px-5 py-6 text-sm text-zinc-500">Checking permissions…</p>
                    )}
                </Card>
                <div
                    className={cx(
                        "mt-6 rounded-lg p-4 text-sm",
                        "bg-indigo-50 text-indigo-900 dark:bg-indigo-500/10 dark:text-indigo-200"
                    )}
                >
                    <p className="font-medium">Already allowed it in System Settings?</p>
                    <p className="mt-1 text-indigo-800/80 dark:text-indigo-200/80">
                        macOS applies new permissions after cudAI restarts.
                    </p>
                    <Button
                        className="mt-3"
                        size="sm"
                        onClick={() => window.electron.ipcRenderer.sendMessage("relaunch-app")}
                    >
                        Restart cudAI
                    </Button>
                </div>
            </div>
        </div>
    );
}
