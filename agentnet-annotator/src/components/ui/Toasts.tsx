import React from "react";
import {
    CheckCircleIcon,
    ExclamationTriangleIcon,
    InformationCircleIcon,
    XMarkIcon,
} from "@heroicons/react/20/solid";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
    id: number;
    message: string;
    tone: ToastTone;
}

const ICONS = {
    success: <CheckCircleIcon className="h-5 w-5 text-emerald-500" />,
    error: <ExclamationTriangleIcon className="h-5 w-5 text-red-500" />,
    info: <InformationCircleIcon className="h-5 w-5 text-indigo-500" />,
};

export default function Toasts({
    toasts,
    onDismiss,
}: {
    toasts: Toast[];
    onDismiss: (id: number) => void;
}) {
    return (
        <div
            aria-live="polite"
            className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-80 flex-col gap-2"
        >
            {toasts.map((toast) => (
                <div
                    key={toast.id}
                    className="pointer-events-auto flex items-start gap-3 rounded-lg bg-white p-3 text-sm shadow-lg ring-1 ring-zinc-200 dark:bg-zinc-800 dark:ring-zinc-700"
                >
                    <span className="mt-0.5 shrink-0">{ICONS[toast.tone]}</span>
                    <p className="flex-1 text-zinc-800 dark:text-zinc-100">{toast.message}</p>
                    <button
                        onClick={() => onDismiss(toast.id)}
                        className="shrink-0 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                        aria-label="Dismiss"
                    >
                        <XMarkIcon className="h-4 w-4" />
                    </button>
                </div>
            ))}
        </div>
    );
}
