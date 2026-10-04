import React from "react";
import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from "@headlessui/react";

export function cx(...classes: (string | false | null | undefined)[]) {
    return classes.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "warning";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
    primary:
        "bg-indigo-600 text-white hover:bg-indigo-500 focus-visible:outline-indigo-600 shadow-sm",
    secondary:
        "bg-white text-zinc-900 ring-1 ring-inset ring-zinc-300 hover:bg-zinc-50 dark:bg-zinc-800 dark:text-zinc-100 dark:ring-zinc-700 dark:hover:bg-zinc-700 shadow-sm",
    danger: "bg-red-600 text-white hover:bg-red-500 focus-visible:outline-red-600 shadow-sm",
    warning: "bg-amber-500 text-white hover:bg-amber-400 focus-visible:outline-amber-500 shadow-sm",
    ghost: "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: ButtonVariant;
    size?: "sm" | "md" | "lg";
    icon?: React.ReactNode;
    loading?: boolean;
}

export function Button({
    variant = "secondary",
    size = "md",
    icon,
    loading,
    className,
    children,
    disabled,
    ...rest
}: ButtonProps) {
    const sizes = {
        sm: "h-8 px-2.5 text-xs gap-1.5",
        md: "h-9 px-3.5 text-sm gap-2",
        lg: "h-11 px-5 text-base gap-2",
    };
    return (
        <button
            {...rest}
            disabled={disabled || loading}
            className={cx(
                "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
                "disabled:cursor-not-allowed disabled:opacity-50",
                sizes[size],
                BUTTON_VARIANTS[variant],
                className
            )}
        >
            {loading ? <Spinner className="h-4 w-4" /> : icon}
            {children}
        </button>
    );
}

export function IconButton({
    label,
    className,
    children,
    ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
    return (
        <button
            {...rest}
            aria-label={label}
            title={label}
            className={cx(
                "inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition-colors",
                "hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
                "disabled:cursor-not-allowed disabled:opacity-40",
                className
            )}
        >
            {children}
        </button>
    );
}

type BadgeTone = "neutral" | "indigo" | "green" | "amber" | "red" | "sky" | "violet";

const BADGE_TONES: Record<BadgeTone, string> = {
    neutral: "bg-zinc-100 text-zinc-700 ring-zinc-500/20 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-400/20",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-600/20 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-400/30",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-400/30",
    amber: "bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/30",
    red: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/30",
    sky: "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-400/30",
    violet: "bg-violet-50 text-violet-700 ring-violet-600/20 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-400/30",
};

export function Badge({
    tone = "neutral",
    className,
    children,
}: {
    tone?: BadgeTone;
    className?: string;
    children: React.ReactNode;
}) {
    return (
        <span
            className={cx(
                "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
                BADGE_TONES[tone],
                className
            )}
        >
            {children}
        </span>
    );
}

export function Kbd({ children }: { children: React.ReactNode }) {
    return (
        <kbd className="inline-flex min-w-[1.5rem] items-center justify-center rounded border border-zinc-300 bg-zinc-50 px-1.5 py-0.5 font-sans text-xs font-medium text-zinc-600 shadow-[0_1px_0_rgba(0,0,0,0.08)] dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            {children}
        </kbd>
    );
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
    return (
        <div
            className={cx(
                "rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900",
                className
            )}
        >
            {children}
        </div>
    );
}

export function Spinner({ className }: { className?: string }) {
    return (
        <svg className={cx("animate-spin", className || "h-5 w-5")} viewBox="0 0 24 24" fill="none" aria-hidden>
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-20" />
            <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
    );
}

export function EmptyState({
    icon,
    title,
    description,
    action,
}: {
    icon?: React.ReactNode;
    title: string;
    description?: string;
    action?: React.ReactNode;
}) {
    return (
        <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
            {icon && <div className="mb-3 text-zinc-400">{icon}</div>}
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h3>
            {description && (
                <p className="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">{description}</p>
            )}
            {action && <div className="mt-5">{action}</div>}
        </div>
    );
}

export function PageHeader({
    title,
    description,
    actions,
}: {
    title: React.ReactNode;
    description?: React.ReactNode;
    actions?: React.ReactNode;
}) {
    return (
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-zinc-200 px-8 py-6 dark:border-zinc-800">
            <div className="min-w-0">
                <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{title}</h1>
                {description && <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{description}</p>}
            </div>
            {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
    );
}

export function Modal({
    open,
    onClose,
    title,
    children,
    footer,
}: {
    open: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    footer?: React.ReactNode;
}) {
    return (
        <Dialog open={open} onClose={onClose} className="relative z-50">
            <DialogBackdrop className="fixed inset-0 bg-zinc-900/40 backdrop-blur-[2px]" />
            <div className="fixed inset-0 flex items-center justify-center p-4">
                <DialogPanel className="w-full max-w-lg rounded-xl bg-white shadow-xl ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-800">
                    <div className="px-6 pt-5">
                        <DialogTitle className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                            {title}
                        </DialogTitle>
                    </div>
                    <div className="px-6 py-4">{children}</div>
                    {footer && (
                        <div className="flex justify-end gap-2 rounded-b-xl border-t border-zinc-100 bg-zinc-50 px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900/60">
                            {footer}
                        </div>
                    )}
                </DialogPanel>
            </div>
        </Dialog>
    );
}

export function TextField({
    label,
    multiline,
    className,
    ...rest
}: {
    label: string;
    multiline?: boolean;
    className?: string;
} & React.InputHTMLAttributes<HTMLInputElement> &
    React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
    const inputClass =
        "block w-full rounded-lg border-0 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm ring-1 ring-inset ring-zinc-300 placeholder:text-zinc-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 dark:bg-zinc-800 dark:text-zinc-100 dark:ring-zinc-700";
    return (
        <label className={cx("block", className)}>
            <span className="mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300">{label}</span>
            {multiline ? (
                <textarea rows={3} {...(rest as any)} className={inputClass} />
            ) : (
                <input {...(rest as any)} className={inputClass} />
            )}
        </label>
    );
}
