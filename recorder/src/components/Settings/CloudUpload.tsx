import React, { useEffect, useState } from "react";
import { api, UploadStatus } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { Badge, Button, Card, TextField } from "../ui";

const STATE_LABEL: Record<UploadStatus["state"], { text: string; tone: "green" | "sky" | "amber" | "red" | "neutral" }> = {
    idle: { text: "Connected", tone: "green" },
    uploading: { text: "Uploading", tone: "sky" },
    offline: { text: "Waiting for network", tone: "amber" },
    error: { text: "Error", tone: "red" },
    not_configured: { text: "Not set up", tone: "neutral" },
};

export function useUploadStatus(intervalMs: number) {
    const [status, setStatus] = useState<UploadStatus | null>(null);
    useEffect(() => {
        let alive = true;
        const load = () =>
            api.get<UploadStatus>("/api/upload/status")
                .then((s) => alive && setStatus(s))
                .catch(() => undefined);
        load();
        const timer = setInterval(load, intervalMs);
        return () => {
            alive = false;
            clearInterval(timer);
        };
    }, [intervalMs]);
    return [status, setStatus] as const;
}

export default function CloudUploadCard() {
    const [status, setStatus] = useUploadStatus(3000);
    const [serverUrl, setServerUrl] = useState<string | null>(null);
    const [accessKey, setAccessKey] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saved, setSaved] = useState(false);

    const url = serverUrl ?? status?.server_url ?? "";
    const label = status ? STATE_LABEL[status.state] : null;

    const save = async () => {
        setSaving(true);
        setError(null);
        setSaved(false);
        try {
            const body: Record<string, string> = { server_url: url };
            if (accessKey) body.access_key = accessKey;
            setStatus(await api.put<UploadStatus>("/api/upload/config", body));
            setAccessKey("");
            setServerUrl(null);
            setSaved(true);
        } catch (e: any) {
            setError(e.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Card>
            <h2 className="flex items-center justify-between border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                Cloud upload
                {label && <Badge tone={label.tone}>{label.text}</Badge>}
            </h2>
            <div className="space-y-4 px-5 py-4 text-sm">
                <p className="text-zinc-600 dark:text-zinc-400">
                    New recordings upload automatically while you record, in 10-second parts. A copy
                    stays on this computer.
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                    <TextField
                        label="Server address"
                        placeholder="https://ingest.example.com"
                        value={url}
                        onChange={(e) => setServerUrl(e.target.value)}
                        spellCheck={false}
                    />
                    <TextField
                        label="Access key"
                        type="password"
                        placeholder={status?.access_key_set ? "•••••••• (saved)" : "Provided by cudAI"}
                        value={accessKey}
                        onChange={(e) => setAccessKey(e.target.value)}
                        autoComplete="off"
                    />
                </div>
                <div className="flex items-center gap-3">
                    <Button size="sm" onClick={save} disabled={saving || (!url && !accessKey)}>
                        {saving ? "Saving…" : "Save"}
                    </Button>
                    {saved && !error && <span className="text-emerald-600">Saved</span>}
                    {error && <span className="text-red-600">{error}</span>}
                </div>
                {status?.last_upload_at && (
                    <p className="text-zinc-500 dark:text-zinc-400">
                        Last upload: {formatDate(new Date(status.last_upload_at * 1000).toISOString())}
                    </p>
                )}
                {status?.redaction && (
                    <p className="text-zinc-500 dark:text-zinc-400">
                        On-device redaction:{" "}
                        {status.redaction.backlog
                            ? `${status.redaction.backlog} chunk${status.redaction.backlog > 1 ? "s" : ""} waiting`
                            : "up to date"}
                        {status.redaction.last_seconds != null &&
                            ` · last chunk took ${status.redaction.last_seconds} s`}
                        {status.last_lag_seconds != null && ` · ${status.last_lag_seconds} s behind live`}
                    </p>
                )}
                {status?.redaction?.last_error && (
                    <p className="break-all text-red-600">Redaction: {status.redaction.last_error}</p>
                )}
                {status?.last_error && status.state !== "idle" && (
                    <p className="break-all text-red-600">{status.last_error}</p>
                )}
            </div>
        </Card>
    );
}
