export const API_BASE = "http://127.0.0.1:5328";

/** Per-launch token the local backend requires on every request. */
export const apiToken = () => window.electron?.apiToken ?? "";

/** URL for media elements (<video>), which cannot send headers. */
export function mediaUrl(path: string): string {
    const separator = path.includes("?") ? "&" : "?";
    return `${API_BASE}${path}${separator}token=${encodeURIComponent(apiToken())}`;
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            ...init,
            headers: {
                "Content-Type": "application/json",
                "X-Cudai-Token": apiToken(),
                ...(init?.headers || {}),
            },
        });
    } catch {
        throw new ApiError("The cudAI service is not reachable. Restart the app.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === "failed") {
        throw new ApiError(data.message || data.error || `Request failed (${response.status})`);
    }
    return data as T;
}

export const api = {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body: unknown) =>
        request<T>(path, { method: "POST", body: JSON.stringify(body) }),
    put: <T>(path: string, body: unknown) =>
        request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};

/** Cloud upload of one recording. */
export interface RecordingUpload {
    state: "local_only" | "waiting" | "uploading" | "uploaded" | "error";
    bytes?: number;
    completed_at?: string;
    error?: string;
}

/** The background uploader (GET /api/upload/status). */
export interface UploadStatus {
    state: "idle" | "uploading" | "offline" | "error" | "not_configured";
    last_upload_at: number | null;
    last_error: string | null;
    configured: boolean;
    server_url: string;
    access_key_set: boolean;
}

export interface RecordingSummary {
    name: string;
    task_name: string;
    task_description: string | null;
    creation_time: string;
    status: "local" | "processing";
    visualizable: boolean;
    broken: boolean;
    duration?: number | null;
    action_count?: number | null;
    apps?: string[];
    upload?: RecordingUpload;
}

export interface Action {
    id: number;
    action: string;
    description: string;
    start_time: number;
    end_time: number | null;
    target?: Record<string, any> | null;
    [key: string]: any;
}

export interface TimelineEvent {
    t: number;
    t_video: number;
    frame: number | null;
    t_unix: number | null;
    type: "click" | "scroll" | "press" | "release" | "window" | string;
    x?: number;
    y?: number;
    button?: string;
    pressed?: boolean;
    dx?: number;
    dy?: number;
    name?: string;
    char?: string | null;
    text?: string | null;
    modifiers?: string[];
    app_name?: string;
    bundle_id?: string | null;
    window_title?: string | null;
    url?: string | null;
    is_recorder?: boolean;
    display?: number | null;
}

export interface DisplayVideo {
    index: number;
    is_main: boolean;
    builtin: boolean | null;
    bounds: { x: number; y: number; width: number | null; height: number | null };
    scale_factor: number | null;
    video_url: string;
    video_start_timestamp: number;
    width: number | null;
    height: number | null;
    duration: number | null;
    paused_gaps: PausedGap[];
}

export interface PausedGap {
    start_timestamp: number;
    end_timestamp: number;
    video_offset: number;
    frames: number;
}

export interface ReviewData {
    recording_id: string;
    path: string;
    task_name: string;
    description: string | null;
    creation_time: string;
    video_url: string;
    video_start_timestamp: number;
    video: {
        fps: number;
        width: number | null;
        height: number | null;
        duration: number | null;
        paused_gaps: PausedGap[];
    };
    display: {
        logical_width: number | null;
        logical_height: number | null;
        scale_factor?: number | null;
    };
    displays: DisplayVideo[];
    actions: Action[];
    timeline: TimelineEvent[];
    manifest: Record<string, any>;
}

export interface RecordingStatus {
    recording: boolean;
    paused: boolean;
    elapsed_seconds: number;
}
