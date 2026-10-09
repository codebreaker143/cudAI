import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router-dom";
import { ArrowLeftIcon, PencilSquareIcon, ScissorsIcon } from "@heroicons/react/20/solid";
import { useMain } from "../../context/MainContext";
import { Action, ReviewData, api, mediaUrl } from "../../lib/api";
import { actionKind, formatActionLabel, formatDate, formatDuration, isUntitled } from "../../lib/format";
import { Badge, Button, EmptyState, Modal, Spinner, TextField, cx } from "../ui";
import VideoPlayer, { ClickMark, GapSpan, TimelineMarker, VideoPlayerHandle } from "./VideoPlayer";
import ActionList from "./ActionList";
import EventList from "./EventList";
import DetailsPanel from "./DetailsPanel";

type Tab = "actions" | "events" | "details";

// Show an action a moment before it happens.
const PRE_ROLL = 0.4;

function TaskHeader({
    data,
    onSaved,
}: {
    data: ReviewData;
    onSaved: (name: string, description: string) => void;
}) {
    const { showError, showSuccess } = useMain();
    const [editing, setEditing] = useState(false);
    const [name, setName] = useState(data.task_name);
    const [description, setDescription] = useState(data.description || "");
    const [saving, setSaving] = useState(false);
    const untitled = isUntitled(data.task_name);

    const save = async () => {
        if (!name.trim()) return;
        setSaving(true);
        try {
            await api.post(`/api/recording/${data.recording_id}/task`, {
                task_name: name,
                description,
            });
            onSaved(name.trim(), description.trim());
            setEditing(false);
            showSuccess("Task details saved");
        } catch (e: any) {
            showError(e.message);
        } finally {
            setSaving(false);
        }
    };

    const apps: string[] = data.manifest?.stats?.apps || [];

    return (
        <div className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
            <Link
                to="/recordings"
                className="mb-2 inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
            >
                <ArrowLeftIcon className="h-3.5 w-3.5" /> Recordings
            </Link>
            {editing ? (
                <div className="grid max-w-2xl gap-3">
                    <TextField
                        label="Task name"
                        value={name}
                        autoFocus
                        onChange={(e: any) => setName(e.target.value)}
                        placeholder="e.g. Create a purchase order in SAP"
                    />
                    <TextField
                        label="Description"
                        multiline
                        value={description}
                        onChange={(e: any) => setDescription(e.target.value)}
                        placeholder="What was the goal and what inputs were used?"
                    />
                    <div className="flex gap-2">
                        <Button variant="primary" size="sm" loading={saving} onClick={save} disabled={!name.trim()}>
                            Save
                        </Button>
                        <Button size="sm" onClick={() => setEditing(false)}>
                            Cancel
                        </Button>
                    </div>
                </div>
            ) : (
                <div className="group flex items-start gap-2">
                    <div className="min-w-0">
                        <h1
                            className={cx(
                                "truncate text-lg font-semibold tracking-tight",
                                untitled ? "text-zinc-400" : "text-zinc-900 dark:text-zinc-50"
                            )}
                        >
                            {untitled ? "Untitled task" : data.task_name}
                        </h1>
                        {data.description && (
                            <p className="mt-0.5 line-clamp-2 text-sm text-zinc-600 dark:text-zinc-400">
                                {data.description}
                            </p>
                        )}
                    </div>
                    <Button
                        size="sm"
                        variant={untitled ? "primary" : "ghost"}
                        icon={<PencilSquareIcon className="h-4 w-4" />}
                        onClick={() => {
                            setName(untitled ? "" : data.task_name);
                            setDescription(data.description || "");
                            setEditing(true);
                        }}
                    >
                        {untitled ? "Name this task" : "Edit"}
                    </Button>
                </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                <span>{formatDate(data.manifest?.start_time || data.creation_time)}</span>
                <span>·</span>
                <span>{formatDuration(data.video.duration)}</span>
                <span>·</span>
                <span>{data.actions.length} actions</span>
                {apps.length > 0 && <span>·</span>}
                {apps.map((app) => (
                    <Badge key={app}>{app}</Badge>
                ))}
            </div>
        </div>
    );
}

export default function ReviewPage() {
    const { recordingId } = useParams();
    const { showError, showSuccess, fetchTasks } = useMain();
    const [data, setData] = useState<ReviewData | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [actions, setActions] = useState<Action[]>([]);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [time, setTime] = useState(0);
    const [tab, setTab] = useState<Tab>("actions");
    const [displayIndex, setDisplayIndex] = useState(0);
    const [selecting, setSelecting] = useState(false);
    const [selection, setSelection] = useState<[number, number] | null>(null);
    const [anchor, setAnchor] = useState<number | null>(null);
    const [subtaskOpen, setSubtaskOpen] = useState(false);
    const [subtaskName, setSubtaskName] = useState("");
    const [subtaskDescription, setSubtaskDescription] = useState("");
    const [creating, setCreating] = useState(false);
    const playerRef = useRef<VideoPlayerHandle>(null);
    const lastTime = useRef(0);

    const load = useCallback(async () => {
        setLoadError(null);
        try {
            const review = await api.get<ReviewData>(`/api/recording/${recordingId}/review`);
            setData(review);
            setActions(review.actions);
            setDirty(false);
        } catch (e: any) {
            setLoadError(e.message);
        }
    }, [recordingId]);

    useEffect(() => {
        setData(null);
        load();
    }, [load]);

    const blocker = useBlocker(({ currentLocation, nextLocation }) =>
        dirty && currentLocation.pathname !== nextLocation.pathname
    );

    const videoStart = data?.video_start_timestamp ?? 0;
    const actionTimes = useMemo(
        () => actions.map((a) => Math.max(0, a.start_time - videoStart)),
        [actions, videoStart]
    );

    const activeIndex = useMemo(() => {
        let index = -1;
        for (let i = 0; i < actionTimes.length; i++) {
            if (actionTimes[i] - PRE_ROLL <= time) index = i;
            else break;
        }
        return index;
    }, [actionTimes, time]);

    // The player reports ~60 times a second; re-render at most ~10 times.
    const onTimeChange = useCallback((t: number) => {
        if (Math.abs(t - lastTime.current) >= 0.1) {
            lastTime.current = t;
            setTime(t);
        }
    }, []);

    const jumpToAction = useCallback(
        (index: number) => {
            if (index < 0 || index >= actionTimes.length) return;
            playerRef.current?.seek(Math.max(0, actionTimes[index] - PRE_ROLL));
        },
        [actionTimes]
    );

    const prevAction = useCallback(() => {
        // Go to the start of the current action, or the previous one if already there.
        const current = activeIndex;
        if (current >= 0 && time - (actionTimes[current] - PRE_ROLL) > 1) jumpToAction(current);
        else jumpToAction(Math.max(0, current - 1));
    }, [activeIndex, actionTimes, time, jumpToAction]);

    const nextAction = useCallback(() => jumpToAction(activeIndex + 1), [activeIndex, jumpToAction]);

    const onEdit = useCallback((index: number, description: string) => {
        setActions((prev) => prev.map((a, i) => (i === index ? { ...a, description } : a)));
        setDirty(true);
    }, []);

    const onRemove = useCallback((index: number) => {
        setActions((prev) => prev.filter((_, i) => i !== index));
        setDirty(true);
    }, []);

    const onSelect = useCallback(
        (index: number, extend: boolean) => {
            if (extend && anchor !== null) {
                setSelection([Math.min(anchor, index), Math.max(anchor, index)]);
            } else {
                setAnchor(index);
                setSelection([index, index]);
            }
        },
        [anchor]
    );

    const saveAnnotations = async () => {
        if (!data) return;
        setSaving(true);
        try {
            await api.post(`/api/recording/${data.recording_id}/confirm`, actions);
            showSuccess("Annotations saved");
            setDirty(false);
            await load();
            fetchTasks();
        } catch (e: any) {
            showError(e.message);
        } finally {
            setSaving(false);
        }
    };

    const createSubtask = async () => {
        if (!data || !selection) return;
        setCreating(true);
        try {
            await api.post(`/api/recording/${data.recording_id}/cut`, {
                cutTaskName: subtaskName.trim(),
                cutDescription: subtaskDescription.trim(),
                valMin: selection[0] + 1,
                valMax: selection[1] + 1,
            });
            showSuccess(`Sub-task “${subtaskName.trim()}” created`);
            setSubtaskOpen(false);
            setSelecting(false);
            setSelection(null);
            setSubtaskName("");
            setSubtaskDescription("");
            fetchTasks();
            load();
        } catch (e: any) {
            showError(e.message);
        } finally {
            setCreating(false);
        }
    };

    const markers: TimelineMarker[] = useMemo(
        () =>
            actions.map((a, i) => ({
                time: actionTimes[i],
                kind: actionKind(a),
                label: formatActionLabel(a),
            })),
        [actions, actionTimes]
    );

    const display = data?.displays.find((d) => d.index === displayIndex) ?? data?.displays[0];
    // This display's video starts slightly after/before the main one.
    const timeOffset = display && data ? display.video_start_timestamp - data.video_start_timestamp : 0;

    const clicks: ClickMark[] = useMemo(() => {
        if (!data || !display?.bounds.width || !display.bounds.height) return [];
        const { x: bx, y: by, width: w, height: h } = display.bounds;
        return data.timeline
            .filter(
                (e) =>
                    e.type === "click" &&
                    e.pressed &&
                    e.x != null &&
                    e.y != null &&
                    (e.display == null ? display.index === 0 : e.display === display.index)
            )
            .map((e) => ({ time: e.t_video, x: (e.x! - bx) / w!, y: (e.y! - by) / h! }))
            .filter((c) => c.x >= 0 && c.x <= 1 && c.y >= 0 && c.y <= 1);
    }, [data, display]);

    const gaps: GapSpan[] = useMemo(
        () =>
            (display?.paused_gaps || []).map((g) => ({
                start: g.video_offset + timeOffset,
                end: g.video_offset + timeOffset + g.frames / (data?.video.fps || 30),
            })),
        [data, display, timeOffset]
    );

    if (loadError) {
        return (
            <div className="flex-1">
                <EmptyState
                    title="This recording can't be opened"
                    description={loadError}
                    action={
                        <Link to="/recordings">
                            <Button>Back to recordings</Button>
                        </Link>
                    }
                />
            </div>
        );
    }

    if (!data) {
        return (
            <div className="flex flex-1 items-center justify-center text-zinc-400">
                <Spinner className="h-6 w-6" />
            </div>
        );
    }

    const shown = display ?? data.displays[0];
    const aspect =
        shown?.width && shown?.height
            ? shown.width / shown.height
            : shown?.bounds.width && shown?.bounds.height
            ? shown.bounds.width / shown.bounds.height
            : 16 / 10;

    const TABS: { key: Tab; label: string; count?: number }[] = [
        { key: "actions", label: "Actions", count: actions.length },
        { key: "events", label: "Events", count: data.timeline.length },
        { key: "details", label: "Details" },
    ];

    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <TaskHeader
                data={data}
                onSaved={(task_name, description) => {
                    setData({ ...data, task_name, description });
                    fetchTasks();
                }}
            />

            <div className="flex min-h-0 flex-1">
                <div className="flex min-w-0 flex-1 flex-col">
                    {data.displays.length > 1 && (
                        <div className="flex items-center gap-1 border-b border-zinc-800 bg-zinc-950 px-4 py-2">
                            {data.displays.map((d, i) => (
                                <button
                                    key={d.index}
                                    onClick={() => setDisplayIndex(d.index)}
                                    className={cx(
                                        "rounded-md px-2.5 py-1 text-xs font-medium",
                                        d.index === shown.index
                                            ? "bg-white/15 text-white"
                                            : "text-zinc-400 hover:bg-white/10 hover:text-zinc-200"
                                    )}
                                >
                                    {d.is_main ? "Main display" : `Display ${i + 1}`}
                                    {d.width ? ` · ${d.width}×${d.height}` : ""}
                                </button>
                            ))}
                        </div>
                    )}
                    <div className="min-h-0 flex-1">
                        <VideoPlayer
                            key={shown.index}
                            ref={playerRef}
                            src={mediaUrl(shown.video_url)}
                            timeOffset={timeOffset}
                            initialTime={lastTime.current}
                            aspect={aspect}
                            knownDuration={shown.duration}
                            markers={markers}
                            clicks={clicks}
                            gaps={gaps}
                            onTimeChange={onTimeChange}
                            onPrevAction={prevAction}
                            onNextAction={nextAction}
                        />
                    </div>
                </div>

                <aside className="flex min-h-0 w-[26rem] shrink-0 flex-col border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                    <div className="flex border-b border-zinc-200 px-2 dark:border-zinc-800">
                        {TABS.map((t) => (
                            <button
                                key={t.key}
                                onClick={() => setTab(t.key)}
                                className={cx(
                                    "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-3 text-sm font-medium",
                                    tab === t.key
                                        ? "border-indigo-500 text-zinc-900 dark:text-white"
                                        : "border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                                )}
                            >
                                {t.label}
                                {t.count != null && (
                                    <span className="rounded-full bg-zinc-100 px-1.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                                        {t.count}
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>

                    {tab === "actions" && (
                        <>
                            <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
                                {selecting ? (
                                    <>
                                        <span className="text-xs text-zinc-600 dark:text-zinc-400">
                                            {selection
                                                ? `Steps ${selection[0] + 1}–${selection[1] + 1} selected`
                                                : "Click the first step, shift-click the last"}
                                        </span>
                                        <div className="ml-auto flex gap-1.5">
                                            <Button
                                                size="sm"
                                                variant="primary"
                                                disabled={!selection || dirty}
                                                title={dirty ? "Save your changes first" : undefined}
                                                onClick={() => setSubtaskOpen(true)}
                                            >
                                                Create sub-task
                                            </Button>
                                            <Button
                                                size="sm"
                                                onClick={() => {
                                                    setSelecting(false);
                                                    setSelection(null);
                                                }}
                                            >
                                                Cancel
                                            </Button>
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            icon={<ScissorsIcon className="h-4 w-4" />}
                                            onClick={() => setSelecting(true)}
                                            disabled={actions.length === 0}
                                        >
                                            Split into sub-task
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant="primary"
                                            className="ml-auto"
                                            disabled={!dirty}
                                            loading={saving}
                                            onClick={saveAnnotations}
                                        >
                                            {dirty ? "Save changes" : "Saved"}
                                        </Button>
                                    </>
                                )}
                            </div>
                            <div className="min-h-0 flex-1 overflow-y-auto">
                                {actions.length === 0 ? (
                                    <EmptyState
                                        title="No actions detected"
                                        description="No clicks, typing or scrolling were captured in this recording."
                                    />
                                ) : (
                                    <ActionList
                                        actions={actions}
                                        videoStart={videoStart}
                                        activeIndex={activeIndex}
                                        selecting={selecting}
                                        selection={selection}
                                        onSelect={onSelect}
                                        onJump={jumpToAction}
                                        onEdit={onEdit}
                                        onRemove={onRemove}
                                    />
                                )}
                            </div>
                        </>
                    )}
                    {tab === "events" && (
                        <div className="min-h-0 flex-1">
                            <EventList
                                events={data.timeline}
                                currentTime={time}
                                onJump={(t) => playerRef.current?.seek(t)}
                            />
                        </div>
                    )}
                    {tab === "details" && (
                        <div className="min-h-0 flex-1 overflow-y-auto">
                            <DetailsPanel data={data} />
                        </div>
                    )}
                </aside>
            </div>

            <Modal
                open={subtaskOpen}
                onClose={() => setSubtaskOpen(false)}
                title="Create sub-task"
                footer={
                    <>
                        <Button onClick={() => setSubtaskOpen(false)}>Cancel</Button>
                        <Button
                            variant="primary"
                            loading={creating}
                            disabled={!subtaskName.trim()}
                            onClick={createSubtask}
                        >
                            Create
                        </Button>
                    </>
                }
            >
                <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
                    Steps {selection ? selection[0] + 1 : 0}–{selection ? selection[1] + 1 : 0} become a new
                    recording with their own video, events and annotations. The original is kept.
                </p>
                <div className="grid gap-3">
                    <TextField
                        label="Task name"
                        autoFocus
                        value={subtaskName}
                        onChange={(e: any) => setSubtaskName(e.target.value)}
                        placeholder="e.g. Approve an invoice"
                    />
                    <TextField
                        label="Description"
                        multiline
                        value={subtaskDescription}
                        onChange={(e: any) => setSubtaskDescription(e.target.value)}
                    />
                </div>
            </Modal>

            <Modal
                open={blocker.state === "blocked"}
                onClose={() => blocker.reset?.()}
                title="Discard unsaved changes?"
                footer={
                    <>
                        <Button onClick={() => blocker.reset?.()}>Keep editing</Button>
                        <Button variant="danger" onClick={() => blocker.proceed?.()}>
                            Discard
                        </Button>
                    </>
                }
            >
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    You edited or removed actions in this recording. Leaving now discards those changes.
                </p>
            </Modal>
        </div>
    );
}
