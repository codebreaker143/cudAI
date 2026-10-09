import React, {
    forwardRef,
    useCallback,
    useEffect,
    useImperativeHandle,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import {
    ArrowsPointingOutIcon,
    ChevronLeftIcon,
    ChevronRightIcon,
    PauseIcon,
    PlayIcon,
} from "@heroicons/react/20/solid";
import { formatClock, formatPrecise, ActionKind } from "../../lib/format";
import { cx } from "../ui";

export interface TimelineMarker {
    time: number;
    kind: ActionKind;
    label: string;
}

export interface ClickMark {
    time: number;
    x: number; // 0..1 of the video width
    y: number; // 0..1 of the video height
}

export interface GapSpan {
    start: number;
    end: number;
}

export interface VideoPlayerHandle {
    seek: (time: number) => void;
    togglePlay: () => void;
    play: () => void;
    pause: () => void;
}

export const KIND_COLORS: Record<ActionKind, string> = {
    click: "bg-indigo-500",
    drag: "bg-violet-500",
    scroll: "bg-sky-500",
    type: "bg-emerald-500",
    hotkey: "bg-amber-500",
    other: "bg-zinc-400",
};

const SPEEDS = [0.5, 1, 1.5, 2, 4];
const CLICK_VISIBLE = 0.8; // seconds a click indicator stays on screen

interface Props {
    src: string;
    /**
     * This video's start minus the shared timeline's start (seconds). All
     * times passed in and reported out are on the shared timeline.
     */
    timeOffset?: number;
    /** Shared-timeline position to open at. */
    initialTime?: number;
    aspect: number; // width / height
    knownDuration?: number | null;
    markers: TimelineMarker[];
    clicks: ClickMark[];
    gaps: GapSpan[];
    onTimeChange: (time: number) => void;
    onPrevAction: () => void;
    onNextAction: () => void;
}

const VideoPlayer = forwardRef<VideoPlayerHandle, Props>(function VideoPlayer(
    {
        src,
        timeOffset = 0,
        initialTime = 0,
        aspect,
        knownDuration,
        markers,
        clicks,
        gaps,
        onTimeChange,
        onPrevAction,
        onNextAction,
    },
    ref
) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const stageRef = useRef<HTMLDivElement>(null);
    const rootRef = useRef<HTMLDivElement>(null);
    const trackRef = useRef<HTMLDivElement>(null);
    const [playing, setPlaying] = useState(false);
    const [time, setTime] = useState(0);
    const [duration, setDuration] = useState(knownDuration || 0);
    const [rate, setRate] = useState(1);
    const [hover, setHover] = useState<{ x: number; time: number } | null>(null);
    const [scrubbing, setScrubbing] = useState(false);
    const [box, setBox] = useState({ width: 0, height: 0 });
    const [error, setError] = useState<string | null>(null);
    const [started, setStarted] = useState(false);

    // `time` is this video's own clock; the shared timeline is time + offset.
    const updateTime = useCallback(
        (t: number) => {
            setTime(t);
            onTimeChange(t + timeOffset);
        },
        [onTimeChange, timeOffset]
    );

    /** Seek to a shared-timeline time. */
    const seek = useCallback(
        (sharedTime: number) => {
            const video = videoRef.current;
            if (!video) return;
            const t = sharedTime - timeOffset;
            const clamped = Math.max(0, Math.min(t, (video.duration || duration) - 0.01));
            video.currentTime = clamped;
            setStarted(true);
            updateTime(clamped);
        },
        [duration, timeOffset, updateTime]
    );

    const togglePlay = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        if (video.paused) video.play();
        else video.pause();
    }, []);

    useImperativeHandle(ref, () => ({
        seek,
        togglePlay,
        play: () => videoRef.current?.play(),
        pause: () => videoRef.current?.pause(),
    }));

    // Smooth time updates while playing.
    useEffect(() => {
        if (!playing) return;
        let frame = 0;
        const tick = () => {
            if (videoRef.current) updateTime(videoRef.current.currentTime);
            frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frame);
    }, [playing, updateTime]);

    // Fit the video box to the stage so overlays align with the picture.
    useLayoutEffect(() => {
        const stage = stageRef.current;
        if (!stage) return;
        const fit = () => {
            const { width, height } = stage.getBoundingClientRect();
            if (width / height > aspect) setBox({ width: height * aspect, height });
            else setBox({ width, height: width / aspect });
        };
        fit();
        const observer = new ResizeObserver(fit);
        observer.observe(stage);
        return () => observer.disconnect();
    }, [aspect]);

    // Keyboard shortcuts (ignored while typing).
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const target = e.target as HTMLElement;
            if (target.closest("input, textarea, select, [contenteditable=true]")) return;
            const video = videoRef.current;
            if (!video) return;
            const frame = 1 / 30;
            switch (e.key) {
                case " ":
                case "k":
                    e.preventDefault();
                    togglePlay();
                    break;
                case "ArrowLeft":
                    e.preventDefault();
                    seek(video.currentTime + timeOffset - (e.shiftKey ? 1 : 5));
                    break;
                case "ArrowRight":
                    e.preventDefault();
                    seek(video.currentTime + timeOffset + (e.shiftKey ? 1 : 5));
                    break;
                case ",":
                    video.pause();
                    seek(video.currentTime + timeOffset - frame);
                    break;
                case ".":
                    video.pause();
                    seek(video.currentTime + timeOffset + frame);
                    break;
                case "ArrowUp":
                case "j":
                    e.preventDefault();
                    onPrevAction();
                    break;
                case "ArrowDown":
                case "l":
                    e.preventDefault();
                    onNextAction();
                    break;
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [seek, togglePlay, onPrevAction, onNextAction, timeOffset]);

    const ratioFromEvent = (clientX: number) => {
        const rect = trackRef.current!.getBoundingClientRect();
        return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    };

    const onTrackPointerDown = (e: React.PointerEvent) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        setScrubbing(true);
        seek(ratioFromEvent(e.clientX) * duration + timeOffset);
    };
    const onTrackPointerMove = (e: React.PointerEvent) => {
        const ratio = ratioFromEvent(e.clientX);
        const rect = trackRef.current!.getBoundingClientRect();
        setHover({ x: ratio * rect.width, time: ratio * duration });
        if (scrubbing) seek(ratio * duration + timeOffset);
    };

    // Props are on the shared timeline; convert to this video's clock.
    const pct = (sharedTime: number) =>
        duration > 0 ? `${((sharedTime - timeOffset) / duration) * 100}%` : "0%";
    const sharedNow = time + timeOffset;
    const visibleClicks = useMemo(
        () => clicks.filter((c) => sharedNow >= c.time && sharedNow - c.time < CLICK_VISIBLE),
        [clicks, sharedNow]
    );
    const inGap = gaps.some((g) => sharedNow >= g.start && sharedNow < g.end);

    return (
        <div ref={rootRef} className="flex h-full flex-col bg-zinc-950">
            <div ref={stageRef} className="relative flex min-h-0 flex-1 items-center justify-center">
                <div className="relative" style={{ width: box.width, height: box.height }}>
                    <video
                        ref={videoRef}
                        src={src}
                        preload="auto"
                        className="h-full w-full cursor-pointer bg-black"
                        onClick={togglePlay}
                        onPlay={() => {
                            setPlaying(true);
                            setStarted(true);
                        }}
                        onPause={() => {
                            setPlaying(false);
                            if (videoRef.current) updateTime(videoRef.current.currentTime);
                        }}
                        onSeeked={() => videoRef.current && updateTime(videoRef.current.currentTime)}
                        onLoadedMetadata={() => {
                            const video = videoRef.current;
                            if (!video) return;
                            if (video.duration && isFinite(video.duration)) setDuration(video.duration);
                            if (initialTime > 0) {
                                video.currentTime = Math.max(0, initialTime - timeOffset);
                                updateTime(video.currentTime);
                                setStarted(true);
                            }
                        }}
                        onError={() => setError("This video could not be loaded.")}
                    />
                    {visibleClicks.map((c, i) => {
                        const age = (sharedNow - c.time) / CLICK_VISIBLE;
                        return (
                            <span
                                key={`${c.time}-${i}`}
                                className="pointer-events-none absolute rounded-full border-2 border-indigo-400 bg-indigo-400/25"
                                style={{
                                    left: `${c.x * 100}%`,
                                    top: `${c.y * 100}%`,
                                    width: 18 + age * 40,
                                    height: 18 + age * 40,
                                    transform: "translate(-50%, -50%)",
                                    opacity: 1 - age,
                                }}
                            />
                        );
                    })}
                    {inGap && (
                        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                            <span className="rounded-full bg-amber-500/90 px-3 py-1 text-xs font-medium text-white">
                                Recording paused — nothing captured
                            </span>
                        </div>
                    )}
                    {!playing && !started && !error && (
                        <button
                            onClick={togglePlay}
                            className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white backdrop-blur transition hover:bg-black/70"
                            aria-label="Play"
                        >
                            <PlayIcon className="ml-1 h-8 w-8" />
                        </button>
                    )}
                    {error && (
                        <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-300">
                            {error}
                        </div>
                    )}
                </div>
            </div>

            {/* Timeline */}
            <div className="border-t border-white/10 px-4 pb-3 pt-4">
                <div
                    ref={trackRef}
                    className="group relative h-8 cursor-pointer touch-none select-none"
                    onPointerDown={onTrackPointerDown}
                    onPointerMove={onTrackPointerMove}
                    onPointerUp={() => setScrubbing(false)}
                    onPointerLeave={() => !scrubbing && setHover(null)}
                >
                    <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-white/15 transition-all group-hover:h-2">
                        {gaps.map((g, i) => (
                            <div
                                key={i}
                                className="absolute inset-y-0 bg-amber-400/40"
                                style={{
                                    left: pct(g.start),
                                    width: duration > 0 ? `${((g.end - g.start) / duration) * 100}%` : "0%",
                                }}
                                title="Paused"
                            />
                        ))}
                        <div className="absolute inset-y-0 left-0 rounded-full bg-indigo-500" style={{ width: pct(sharedNow) }} />
                    </div>
                    {markers.map((m, i) => (
                        <div
                            key={i}
                            className={cx(
                                "pointer-events-none absolute top-0 h-2 w-0.5 -translate-x-1/2 rounded-full",
                                KIND_COLORS[m.kind]
                            )}
                            style={{ left: pct(m.time) }}
                        />
                    ))}
                    <div
                        className="pointer-events-none absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow ring-2 ring-indigo-500"
                        style={{ left: pct(sharedNow) }}
                    />
                    {hover && (
                        <div
                            className="pointer-events-none absolute -top-7 -translate-x-1/2 rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] text-white"
                            style={{ left: hover.x }}
                        >
                            {formatPrecise(hover.time + timeOffset)}
                        </div>
                    )}
                </div>

                <div className="mt-1 flex items-center gap-1 text-white">
                    <button
                        onClick={onPrevAction}
                        className="rounded p-1.5 text-zinc-300 hover:bg-white/10 hover:text-white"
                        title="Previous action (↑)"
                    >
                        <ChevronLeftIcon className="h-5 w-5" />
                    </button>
                    <button
                        onClick={togglePlay}
                        className="rounded p-1.5 hover:bg-white/10"
                        title={playing ? "Pause (Space)" : "Play (Space)"}
                    >
                        {playing ? <PauseIcon className="h-5 w-5" /> : <PlayIcon className="h-5 w-5" />}
                    </button>
                    <button
                        onClick={onNextAction}
                        className="rounded p-1.5 text-zinc-300 hover:bg-white/10 hover:text-white"
                        title="Next action (↓)"
                    >
                        <ChevronRightIcon className="h-5 w-5" />
                    </button>
                    <span className="ml-2 font-mono text-xs tabular-nums text-zinc-300">
                        {formatClock(sharedNow)} / {formatClock(duration + timeOffset)}
                    </span>
                    <div className="ml-auto flex items-center gap-1">
                        <select
                            value={rate}
                            onChange={(e) => {
                                const r = Number(e.target.value);
                                setRate(r);
                                if (videoRef.current) videoRef.current.playbackRate = r;
                            }}
                            className="rounded border-0 bg-white/10 py-1 pl-2 pr-7 text-xs text-white focus:ring-1 focus:ring-indigo-400"
                            title="Playback speed"
                        >
                            {SPEEDS.map((s) => (
                                <option key={s} value={s} className="text-zinc-900">
                                    {s}×
                                </option>
                            ))}
                        </select>
                        <button
                            onClick={() => rootRef.current?.requestFullscreen()}
                            className="rounded p-1.5 text-zinc-300 hover:bg-white/10 hover:text-white"
                            title="Full screen"
                        >
                            <ArrowsPointingOutIcon className="h-4 w-4" />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
});

export default VideoPlayer;
