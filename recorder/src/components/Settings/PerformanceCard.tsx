import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Badge, Card } from "../ui";

interface DeviceProfile {
    tier: "high" | "standard" | "low";
    automatic_tier: string;
    override: string | null;
    reason: string;
    capture_scale: "native" | "logical";
    fps: number;
    ocr_threads: number;
    hardware: { apple_silicon: boolean; performance_cores: number; memory_gb: number; on_battery: boolean };
}

const TIER_LABEL: Record<string, string> = {
    high: "High — native resolution, 30 fps",
    standard: "Standard — screen resolution, 30 fps",
    low: "Light — screen resolution, 15 fps",
};

export default function PerformanceCard() {
    const [profile, setProfile] = useState<DeviceProfile | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        api.get<DeviceProfile>("/api/device-profile").then(setProfile).catch(() => undefined);
    }, []);

    const choose = async (tier: string) => {
        setError(null);
        try {
            setProfile(await api.put<DeviceProfile>("/api/device-profile", { tier: tier || null }));
        } catch (e: any) {
            setError(e.message);
        }
    };

    if (!profile) return null;
    const hw = profile.hardware;
    return (
        <Card>
            <h2 className="flex items-center justify-between border-b border-zinc-100 px-5 py-3 text-sm font-semibold text-zinc-900 dark:border-zinc-800 dark:text-zinc-100">
                Recording quality
                <Badge tone={profile.tier === "high" ? "green" : profile.tier === "standard" ? "sky" : "amber"}>
                    {profile.tier}
                </Badge>
            </h2>
            <div className="space-y-3 px-5 py-4 text-sm text-zinc-700 dark:text-zinc-300">
                <p>
                    Next recording: <span className="font-medium">{TIER_LABEL[profile.tier]}</span>, redaction on{" "}
                    {profile.ocr_threads} CPU thread{profile.ocr_threads > 1 ? "s" : ""}
                    {profile.reason !== "hardware" && ` (${profile.reason})`}.
                </p>
                <p className="text-zinc-500 dark:text-zinc-400">
                    This Mac: {hw.apple_silicon ? "Apple silicon" : "Intel"}, {hw.performance_cores} performance cores,{" "}
                    {hw.memory_gb} GB memory{hw.on_battery ? ", on battery" : ""}. Lighter settings keep your Mac
                    responsive and redaction up to date.
                </p>
                <label className="flex items-center gap-3">
                    <span>Quality</span>
                    <select
                        value={profile.override ?? ""}
                        onChange={(e) => choose(e.target.value)}
                        className="rounded-md border-0 bg-white py-1.5 pl-2 pr-8 text-sm ring-1 ring-inset ring-zinc-300 dark:bg-zinc-800 dark:ring-zinc-700"
                    >
                        <option value="">Automatic ({profile.automatic_tier})</option>
                        <option value="high">{TIER_LABEL.high}</option>
                        <option value="standard">{TIER_LABEL.standard}</option>
                        <option value="low">{TIER_LABEL.low}</option>
                    </select>
                </label>
                {error && <p className="text-red-600">{error}</p>}
            </div>
        </Card>
    );
}
