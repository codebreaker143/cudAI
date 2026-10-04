import React, { memo, useEffect, useRef, useState } from "react";
import { CheckIcon, PencilSquareIcon, TrashIcon, XMarkIcon } from "@heroicons/react/20/solid";
import AdsClickIcon from "@mui/icons-material/AdsClick";
import KeyboardIcon from "@mui/icons-material/Keyboard";
import KeyboardCommandKeyIcon from "@mui/icons-material/KeyboardCommandKey";
import SwapVertIcon from "@mui/icons-material/SwapVert";
import OpenWithIcon from "@mui/icons-material/OpenWith";
import PanToolIcon from "@mui/icons-material/PanTool";
import { Action } from "../../lib/api";
import { ActionKind, actionKind, formatActionLabel, formatPrecise, targetLabel } from "../../lib/format";
import { IconButton, cx } from "../ui";

const KIND_STYLE: Record<ActionKind, { icon: React.ReactNode; className: string; name: string }> = {
    click: { icon: <AdsClickIcon fontSize="inherit" />, className: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300", name: "Click" },
    drag: { icon: <OpenWithIcon fontSize="inherit" />, className: "bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300", name: "Drag" },
    scroll: { icon: <SwapVertIcon fontSize="inherit" />, className: "bg-sky-50 text-sky-600 dark:bg-sky-500/15 dark:text-sky-300", name: "Scroll" },
    type: { icon: <KeyboardIcon fontSize="inherit" />, className: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300", name: "Type" },
    hotkey: { icon: <KeyboardCommandKeyIcon fontSize="inherit" />, className: "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300", name: "Shortcut" },
    other: { icon: <PanToolIcon fontSize="inherit" />, className: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300", name: "Action" },
};

export function ActionIcon({ kind }: { kind: ActionKind }) {
    const style = KIND_STYLE[kind];
    return (
        <span
            className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[16px]", style.className)}
            title={style.name}
        >
            {style.icon}
        </span>
    );
}

interface RowProps {
    index: number;
    action: Action;
    videoTime: number;
    active: boolean;
    selecting: boolean;
    selected: boolean;
    onSelect: (index: number, extend: boolean) => void;
    onJump: (index: number) => void;
    onEdit: (index: number, description: string) => void;
    onRemove: (index: number) => void;
}

const ActionRow = memo(function ActionRow({
    index,
    action,
    videoTime,
    active,
    selecting,
    selected,
    onSelect,
    onJump,
    onEdit,
    onRemove,
}: RowProps) {
    const [editing, setEditing] = useState(false);
    const label = formatActionLabel(action);
    const [draft, setDraft] = useState(label);
    const target = targetLabel(action);
    const rowRef = useRef<HTMLLIElement>(null);

    useEffect(() => {
        if (active) rowRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, [active]);

    const save = () => {
        const text = draft.trim();
        if (text && text !== label) onEdit(index, text);
        setEditing(false);
    };

    return (
        <li
            ref={rowRef}
            className={cx(
                "group relative flex items-start gap-3 border-l-2 px-4 py-2.5 transition-colors",
                active
                    ? "border-indigo-500 bg-indigo-50 dark:border-indigo-400 dark:bg-indigo-500/20"
                    : "border-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800/50",
                selected && "bg-violet-50 dark:bg-violet-500/10"
            )}
            onClick={(e) => {
                if (editing) return;
                if (selecting) onSelect(index, e.shiftKey);
                else onJump(index);
            }}
        >
            {selecting ? (
                <input
                    type="checkbox"
                    readOnly
                    checked={selected}
                    className="mt-1.5 h-4 w-4 rounded border-zinc-300 text-violet-600 focus:ring-violet-600"
                />
            ) : (
                <span
                    className={cx(
                        "mt-1.5 w-5 shrink-0 text-right font-mono text-[11px]",
                        active ? "font-semibold text-indigo-600 dark:text-indigo-300" : "text-zinc-400"
                    )}
                >
                    {index + 1}
                </span>
            )}
            <ActionIcon kind={actionKind(action)} />
            <div className="min-w-0 flex-1">
                {editing ? (
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        <input
                            autoFocus
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") save();
                                if (e.key === "Escape") setEditing(false);
                            }}
                            className="block w-full rounded-md border-0 px-2 py-1 text-sm text-zinc-900 ring-1 ring-inset ring-indigo-400 focus:ring-2 focus:ring-indigo-600 dark:bg-zinc-800 dark:text-zinc-100"
                        />
                        <IconButton label="Save" onClick={save}>
                            <CheckIcon className="h-4 w-4" />
                        </IconButton>
                        <IconButton label="Cancel" onClick={() => setEditing(false)}>
                            <XMarkIcon className="h-4 w-4" />
                        </IconButton>
                    </div>
                ) : (
                    <p className="break-words text-sm text-zinc-800 dark:text-zinc-200">{label}</p>
                )}
                {target && !editing && (
                    <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400" title={target}>
                        {target}
                    </p>
                )}
            </div>
            <span className="mt-1 shrink-0 font-mono text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">
                {formatPrecise(videoTime)}
            </span>
            {!selecting && !editing && (
                <div className="absolute right-2 top-1.5 hidden gap-0.5 rounded-md bg-white shadow-sm ring-1 ring-zinc-200 group-hover:flex dark:bg-zinc-800 dark:ring-zinc-700">
                    <IconButton
                        label="Edit description"
                        onClick={(e) => {
                            e.stopPropagation();
                            setDraft(label);
                            setEditing(true);
                        }}
                    >
                        <PencilSquareIcon className="h-4 w-4" />
                    </IconButton>
                    <IconButton
                        label="Remove from annotation"
                        onClick={(e) => {
                            e.stopPropagation();
                            onRemove(index);
                        }}
                        className="hover:text-red-600"
                    >
                        <TrashIcon className="h-4 w-4" />
                    </IconButton>
                </div>
            )}
        </li>
    );
});

interface Props {
    actions: Action[];
    videoStart: number;
    activeIndex: number;
    selecting: boolean;
    selection: [number, number] | null;
    onSelect: (index: number, extend: boolean) => void;
    onJump: (index: number) => void;
    onEdit: (index: number, description: string) => void;
    onRemove: (index: number) => void;
}

export default function ActionList({
    actions,
    videoStart,
    activeIndex,
    selecting,
    selection,
    onSelect,
    onJump,
    onEdit,
    onRemove,
}: Props) {
    return (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
            {actions.map((action, i) => (
                <ActionRow
                    key={action.id}
                    index={i}
                    action={action}
                    videoTime={Math.max(0, action.start_time - videoStart)}
                    active={i === activeIndex}
                    selecting={selecting}
                    selected={!!selection && i >= selection[0] && i <= selection[1]}
                    onSelect={onSelect}
                    onJump={onJump}
                    onEdit={onEdit}
                    onRemove={onRemove}
                />
            ))}
        </ul>
    );
}
