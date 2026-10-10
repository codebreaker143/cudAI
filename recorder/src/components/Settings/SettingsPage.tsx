import React, { useEffect, useState } from "react";
import { FolderOpenIcon } from "@heroicons/react/20/solid";
import { api } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { Button, Card, Kbd, PageHeader } from "../ui";
import { useMain } from "../../context/MainContext";
import TermsAndConsent from "../prerequisite/Terms";
import { PermissionList, usePermissions } from "../prerequisite/Permissions";
import CloudUploadCard from "./CloudUpload";
import PerformanceCard from "./PerformanceCard";

interface SystemInfo {
    version: string;
    schema_version: string;
    data_dir: string;
    recordings_dir: string;
    contributor_id: string;
}

interface ConsentInfo {
    current_version: string;
    accepted: boolean;
    consent: { version: string; decided_at: string } | null;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="grid grid-cols-[12rem_1fr] items-center gap-4 px-5 py-3 text-sm">
            <dt className="text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className="min-w-0 break-all text-zinc-800 dark:text-zinc-200">{children}</dd>
        </div>
    );
}

export default function SettingsPage() {
    const { myos } = useMain();
    const [info, setInfo] = useState<SystemInfo | null>(null);
    const [consent, setConsent] = useState<ConsentInfo | null>(null);
    const [showTerms, setShowTerms] = useState(false);
    const { state: permissions, refresh: refreshPermissions } = usePermissions(3000);
    const mod = myos === "darwin" ? "⌘ ⌥" : "Ctrl Alt";

    useEffect(() => {
        api.get<SystemInfo>("/api/system/info").then(setInfo).catch(() => undefined);
        api.get<ConsentInfo>("/api/consent").then(setConsent).catch(() => undefined);
    }, []);

    if (showTerms && consent) {
        return (
            <div className="flex-1 overflow-y-auto">
                <TermsAndConsent
                    version={consent.current_version}
                    accepted
                    onAccepted={() => undefined}
                    onClose={() => setShowTerms(false)}
                />
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto">
            <PageHeader title="Settings" description="Storage, cloud upload, shortcuts and the terms you accepted." />
            <div className="max-w-3xl space-y-6 p-8">
                <Card>
                    <h2 className="border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                        Permissions
                    </h2>
                    {permissions ? (
                        <PermissionList state={permissions} onChanged={refreshPermissions} />
                    ) : (
                        <p className="px-5 py-4 text-sm text-zinc-500">Checking…</p>
                    )}
                </Card>

                <Card>
                    <h2 className="border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                        Storage
                    </h2>
                    <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        <Row label="Recordings folder">
                            <div className="flex items-center gap-3">
                                <span className="font-mono text-xs">{info?.recordings_dir ?? "…"}</span>
                                {info && (
                                    <Button
                                        size="sm"
                                        icon={<FolderOpenIcon className="h-4 w-4" />}
                                        onClick={() =>
                                            window.electron.ipcRenderer.sendMessage("show-in-folder", info.recordings_dir)
                                        }
                                    >
                                        Open
                                    </Button>
                                )}
                            </div>
                        </Row>
                        <Row label="Contributor ID">
                            <span className="font-mono text-xs">{info?.contributor_id ?? "…"}</span>
                        </Row>
                    </dl>
                </Card>

                <CloudUploadCard />

                <PerformanceCard />

                <Card>
                    <h2 className="border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                        Keyboard shortcuts
                    </h2>
                    <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        <Row label="Start recording"><Kbd>{mod} R</Kbd></Row>
                        <Row label="Pause / resume"><Kbd>{mod} P</Kbd></Row>
                        <Row label="Stop recording"><Kbd>{mod} T</Kbd></Row>
                        <Row label="Review: play / pause"><Kbd>Space</Kbd></Row>
                        <Row label="Review: previous / next action"><span className="flex gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd></span></Row>
                        <Row label="Review: seek 5 s (⇧ for 1 s)"><span className="flex gap-1"><Kbd>←</Kbd><Kbd>→</Kbd></span></Row>
                        <Row label="Review: step one frame"><span className="flex gap-1"><Kbd>,</Kbd><Kbd>.</Kbd></span></Row>
                    </dl>
                </Card>

                <Card>
                    <h2 className="border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                        Recording terms
                    </h2>
                    <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        <Row label="Accepted version">{consent?.consent?.version ?? "…"}</Row>
                        <Row label="Accepted on">{formatDate(consent?.consent?.decided_at)}</Row>
                        <Row label="Terms">
                            <Button size="sm" onClick={() => setShowTerms(true)} disabled={!consent}>
                                View terms
                            </Button>
                        </Row>
                    </dl>
                </Card>

                <Card>
                    <h2 className="border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                        About
                    </h2>
                    <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        <Row label="Version">{info?.version ?? "…"}</Row>
                        <Row label="Data format">{info?.schema_version ?? "…"}</Row>
                    </dl>
                </Card>
            </div>
        </div>
    );
}
