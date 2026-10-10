import React, { useEffect, useState } from "react";
import { DocumentDuplicateIcon, FolderOpenIcon } from "@heroicons/react/20/solid";
import { api, PipelineTimings, ReviewData } from "../../lib/api";
import { formatDate, formatDuration } from "../../lib/format";
import { Badge, Button } from "../ui";
import { useMain } from "../../context/MainContext";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section className="px-5 py-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                {title}
            </h3>
            <dl className="space-y-1.5">{children}</dl>
        </section>
    );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
    return (
        <div className="grid grid-cols-[8.5rem_1fr] gap-2 text-sm">
            <dt className="text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className="min-w-0 break-words text-zinc-800 dark:text-zinc-200">{value ?? "—"}</dd>
        </div>
    );
}

// Display names for pipeline stages (core/timing.py), in pipeline order.
const STAGES: [string, string][] = [
    ["capture_start", "Capture start"],
    ["redaction_queue_wait", "Wait for redaction"],
    ["decode", "Decode"],
    ["change_detection", "Change detection"],
    ["ocr", "OCR"],
    ["presidio", "Presidio"],
    ["mask", "Masking (OpenCV)"],
    ["encode", "Re-encode"],
    ["redact_chunk", "Redaction per chunk"],
    ["upload_file", "Upload per file"],
    ["live_events", "Live event upload"],
    ["capture_stop", "Capture stop"],
    ["stop_recording", "Stop recording"],
    ["finalize_video", "Join video"],
    ["privacy_text", "Text redaction"],
    ["reduce_actions", "Action extraction"],
    ["export", "Export"],
    ["process_recording", "Processing total"],
    ["final_upload", "Final upload"],
];

function PipelineTiming({ recordingId }: { recordingId: string }) {
    const [timings, setTimings] = useState<PipelineTimings | null>(null);
    useEffect(() => {
        api.get<PipelineTimings>(`/api/recording/${recordingId}/timings`).then(setTimings).catch(() => undefined);
    }, [recordingId]);
    if (!timings || !Object.keys(timings.stages).length) return null;
    const fmt = (v?: number) => (v == null ? "—" : v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(1)} s`);
    const rows = STAGES.filter(([key]) => timings.stages[key]?.count);
    return (
        <section className="px-5 py-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Pipeline timing
            </h3>
            {timings.chunk_lag.count > 0 && (
                <p className="mb-2 text-sm text-zinc-700 dark:text-zinc-300">
                    Capture → cloud: median {fmt(timings.chunk_lag.p50)}, worst {fmt(timings.chunk_lag.max)} over{" "}
                    {timings.chunk_lag.count} chunks
                </p>
            )}
            <table className="w-full text-xs tabular-nums">
                <thead className="text-zinc-500 dark:text-zinc-400">
                    <tr>
                        <th className="py-1 text-left font-medium">Step</th>
                        <th className="py-1 text-right font-medium">Runs</th>
                        <th className="py-1 text-right font-medium">Median</th>
                        <th className="py-1 text-right font-medium">p95</th>
                        <th className="py-1 text-right font-medium">Total</th>
                    </tr>
                </thead>
                <tbody className="text-zinc-800 dark:text-zinc-200">
                    {rows.map(([key, label]) => {
                        const s = timings.stages[key];
                        return (
                            <tr key={key}>
                                <td className="py-0.5">{label}</td>
                                <td className="py-0.5 text-right">{s.count}</td>
                                <td className="py-0.5 text-right">{fmt(s.p50)}</td>
                                <td className="py-0.5 text-right">{fmt(s.p95)}</td>
                                <td className="py-0.5 text-right">{fmt(s.total)}</td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </section>
    );
}

export default function DetailsPanel({ data }: { data: ReviewData }) {
    const { showSuccess } = useMain();
    const m = data.manifest || {};
    const env = m.environment || {};
    const video = data.video;
    const stats = m.stats || {};
    const consent = m.consent;
    const counts: Record<string, number> = stats.event_counts || {};

    return (
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            <div className="flex gap-2 px-5 py-4">
                <Button
                    size="sm"
                    icon={<FolderOpenIcon className="h-4 w-4" />}
                    onClick={() => window.electron.ipcRenderer.sendMessage("show-in-folder", data.path)}
                >
                    Show in Finder
                </Button>
                <Button
                    size="sm"
                    icon={<DocumentDuplicateIcon className="h-4 w-4" />}
                    onClick={() => {
                        navigator.clipboard.writeText(data.recording_id);
                        showSuccess("Recording ID copied");
                    }}
                >
                    Copy ID
                </Button>
            </div>

            <Section title="Recording">
                <Row label="ID" value={<span className="font-mono text-xs">{data.recording_id}</span>} />
                <Row label="Started" value={formatDate(m.start_time || data.creation_time)} />
                <Row label="Duration" value={formatDuration(video.duration)} />
                <Row label="Pauses" value={(m.pauses || []).length} />
                <Row label="Actions" value={data.actions.length} />
                <Row label="Schema" value={m.schema_version} />
            </Section>

            <Section title="Video">
                <Row
                    label="Resolution"
                    value={video.width ? `${video.width} × ${video.height} @ ${video.fps} fps` : null}
                />
                <Row
                    label="Display"
                    value={
                        data.display.logical_width
                            ? `${data.display.logical_width} × ${data.display.logical_height} pt` +
                              (data.display.scale_factor ? ` (${data.display.scale_factor}× scale)` : "")
                            : null
                    }
                />
                <Row label="Codec" value={m.video?.codec?.toUpperCase?.()} />
            </Section>

            <Section title="Apps used">
                <div className="flex flex-wrap gap-1">
                    {(stats.apps || []).length > 0 ? (
                        stats.apps.map((app: string) => <Badge key={app}>{app}</Badge>)
                    ) : (
                        <span className="text-sm text-zinc-500">—</span>
                    )}
                </div>
            </Section>

            {(stats.sites || []).length > 0 && (
                <Section title="Websites">
                    <div className="flex flex-wrap gap-1">
                        {stats.sites.map((site: string) => (
                            <Badge key={site} tone="sky">
                                {site}
                            </Badge>
                        ))}
                    </div>
                </Section>
            )}

            <Section title="Captured events">
                {Object.keys(counts).length === 0 ? (
                    <span className="text-sm text-zinc-500">—</span>
                ) : (
                    Object.entries(counts).map(([type, n]) => <Row key={type} label={type} value={n} />)
                )}
            </Section>

            <Section title="Environment">
                <Row label="Computer" value={env.model} />
                <Row
                    label="OS"
                    value={env.os ? `${env.os.name} ${env.os.version || ""} (${env.os.architecture || ""})` : null}
                />
                <Row label="Locale" value={env.locale} />
                <Row label="Keyboard" value={env.keyboard_layout?.replace("com.apple.keylayout.", "")} />
                <Row label="Time zone" value={env.timezone} />
                <Row label="Monitors" value={(env.monitors || []).length || null} />
            </Section>

            <Section title="Consent">
                <Row label="Terms version" value={consent?.version} />
                <Row label="Accepted" value={consent ? formatDate(consent.decided_at) : null} />
                <Row
                    label="Contributor"
                    value={m.contributor_id && <span className="font-mono text-xs">{m.contributor_id}</span>}
                />
            </Section>

            <PipelineTiming recordingId={data.recording_id} />
        </div>
    );
}
