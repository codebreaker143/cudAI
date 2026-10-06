import type { Action } from "./api";

/** Recordings without a task name get "Recording-<date> (Untitled)". */
export function isUntitled(taskName: string | null | undefined): boolean {
    return !taskName || /\(Untitled\)$/.test(taskName);
}

export function taskTitle(taskName: string | null | undefined): string {
    return isUntitled(taskName) ? "Untitled task" : taskName!;
}

/** 83.4 -> "1:23", 3723 -> "1:02:03" */
export function formatClock(seconds: number | null | undefined): string {
    if (seconds == null || !isFinite(seconds) || seconds < 0) return "0:00";
    const s = Math.floor(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, "0");
    return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** 83.46 -> "1:23.4" */
export function formatPrecise(seconds: number): string {
    if (!isFinite(seconds) || seconds < 0) return "0:00.0";
    const tenths = Math.floor((seconds % 1) * 10);
    return `${formatClock(seconds)}.${tenths}`;
}

export function formatDuration(seconds: number | null | undefined): string {
    if (seconds == null || !isFinite(seconds)) return "—";
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    if (m < 60) return `${m}m ${Math.round(seconds % 60)}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function formatDate(value: string | null | undefined): string {
    if (!value) return "—";
    const date = new Date(value.replace(" ", "T"));
    if (isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
    });
}

const KEY_SYMBOLS: Record<string, string> = {
    cmd: "⌘",
    alt: "⌥",
    option: "⌥",
    shift: "⇧",
    ctrl: "⌃",
    enter: "↩",
    return: "↩",
    tab: "⇥",
    esc: "Esc",
    escape: "Esc",
    backspace: "⌫",
    delete: "⌦",
    space: "Space",
    up: "↑",
    down: "↓",
    left: "←",
    right: "→",
    caps_lock: "⇪",
    page_up: "PgUp",
    page_down: "PgDn",
    home: "Home",
    end: "End",
};

export function keySymbol(name: string): string {
    const base = name.replace(/_(l|r|gr)$/, "");
    if (KEY_SYMBOLS[base]) return KEY_SYMBOLS[base];
    return name.length === 1 ? name.toUpperCase() : name;
}

/**
 * Reducer descriptions look like "⌨️ Press: $cmd$ + c" or "Scroll ⬇️×32".
 * Turn them into clean, human-readable labels.
 */
export function formatActionLabel(action: Action): string {
    let text = action.description || action.action;
    text = text.replace(/^⌨️\s*/, "").replace(/\s+$/, "");
    text = text.replace(/\$([a-z0-9_]+)\$/gi, (_, key) => keySymbol(key));
    text = text.replace(/⬇️/g, "↓").replace(/⬆️/g, "↑").replace(/⬅️/g, "←").replace(/➡️/g, "→");
    text = text.replace(/^Type:\s*/, "Type “").replace(/^(Type “.*)$/, "$1”");
    return text;
}

export type ActionKind = "click" | "drag" | "scroll" | "type" | "hotkey" | "other";

export function actionKind(action: Action): ActionKind {
    const a = action.action;
    if (a.includes("drag")) return "drag";
    if (a.includes("click")) return "click";
    if (a === "scroll") return "scroll";
    if (a === "type") return "type";
    if (a === "press" || a === "long_press") return "hotkey";
    return "other";
}

/** Best label for the UI element an action targeted, if known. */
export function targetLabel(action: Action): string | null {
    const t = action.target;
    if (!t || t.mark === false) return null;
    const label = t.title || t.description || (typeof t.value === "string" ? t.value : null);
    const role = t.role_description || t.role;
    if (label && role) return `${label} · ${role}`;
    return label || role || null;
}
