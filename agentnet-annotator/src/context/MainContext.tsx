import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
    ReactNode,
} from "react";
import SocketIOService from "../utils/SocketService";
import { api, RecordingStatus, RecordingSummary } from "../lib/api";
import Toasts, { Toast, ToastTone } from "../components/ui/Toasts";

interface MainContextType {
    isRecording: boolean;
    isPaused: boolean;
    elapsedSeconds: number;
    busy: boolean;
    startRecording: () => Promise<void>;
    stopRecording: () => Promise<void>;
    togglePause: () => Promise<void>;
    recordings: RecordingSummary[];
    recordingsLoaded: boolean;
    fetchTasks: () => Promise<void>;
    SocketService: SocketIOService;
    notify: (message: string, tone?: ToastTone) => void;
    showSuccess: (message: string) => void;
    showError: (message: string) => void;
    showInfo: (message: string) => void;
    myos: string;
}

const MainContext = createContext<MainContextType | undefined>(undefined);

const ipc = () => window.electron.ipcRenderer;

export const MainProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    // One socket for the lifetime of the app.
    const SocketService = useMemo(() => new SocketIOService(), []);

    const [status, setStatus] = useState<RecordingStatus>({
        recording: false,
        paused: false,
        elapsed_seconds: 0,
    });
    const statusRef = useRef(status);
    statusRef.current = status;
    const [busy, setBusy] = useState(false);
    const busyRef = useRef(busy);
    busyRef.current = busy;

    const [recordings, setRecordings] = useState<RecordingSummary[]>([]);
    const [recordingsLoaded, setRecordingsLoaded] = useState(false);
    const [toasts, setToasts] = useState<Toast[]>([]);
    const [os, setOs] = useState("");

    const notify = useCallback((message: string, tone: ToastTone = "info") => {
        const id = Date.now() + Math.random();
        setToasts((prev) => [...prev, { id, message, tone }]);
        setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4500);
    }, []);
    const showSuccess = useCallback((m: string) => notify(m, "success"), [notify]);
    const showError = useCallback((m: string) => notify(m, "error"), [notify]);
    const showInfo = useCallback((m: string) => notify(m, "info"), [notify]);

    const fetchTasks = useCallback(async () => {
        try {
            const data = await api.get<{ recordings: RecordingSummary[] }>("/api/recordings");
            setRecordings(data.recordings || []);
        } catch (error: any) {
            console.error("Failed to fetch recordings:", error);
        } finally {
            setRecordingsLoaded(true);
        }
    }, []);

    const refreshStatus = useCallback(async () => {
        try {
            const data = await api.get<RecordingStatus>("/api/recording/status");
            setStatus({
                recording: !!data.recording,
                paused: !!data.paused,
                elapsed_seconds: data.elapsed_seconds || 0,
            });
            return data;
        } catch {
            return null;
        }
    }, []);

    const startRecording = useCallback(async () => {
        if (busyRef.current) return;
        if (statusRef.current.recording) {
            showInfo("A recording is already in progress");
            return;
        }
        setBusy(true);
        try {
            await SocketService.Get("start_record");
            ipc().sendMessage("start-record-icon");
            setStatus({ recording: true, paused: false, elapsed_seconds: 0 });
            showSuccess("Recording started");
            setTimeout(() => ipc().sendMessage("minimize-window"), 1200);
        } catch (error: any) {
            ipc().sendMessage("maximize-window");
            showError(error.message);
        } finally {
            setBusy(false);
        }
    }, [SocketService, showError, showInfo, showSuccess]);

    const stopRecording = useCallback(async () => {
        if (busyRef.current) return;
        if (!statusRef.current.recording) {
            showInfo("There is no recording in progress");
            return;
        }
        setBusy(true);
        ipc().sendMessage("stop-record-icon");
        try {
            await SocketService.Get("stop_record");
            showSuccess("Recording saved. Processing actions…");
        } catch (error: any) {
            showError(error.message);
        } finally {
            setStatus({ recording: false, paused: false, elapsed_seconds: 0 });
            setBusy(false);
            ipc().sendMessage("maximize-window");
            fetchTasks();
        }
    }, [SocketService, fetchTasks, showError, showInfo, showSuccess]);

    const togglePause = useCallback(async () => {
        if (busyRef.current) return;
        if (!statusRef.current.recording) {
            showInfo("There is no recording to pause");
            return;
        }
        const resuming = statusRef.current.paused;
        setBusy(true);
        try {
            await SocketService.Get(resuming ? "resume_record" : "pause_record");
            setStatus((prev) => ({ ...prev, paused: !resuming }));
            ipc().sendMessage(resuming ? "resume-record-icon" : "pause-record-icon");
            showInfo(resuming ? "Recording resumed" : "Recording paused — nothing is being captured");
        } catch (error: any) {
            showError(error.message);
        } finally {
            setBusy(false);
        }
    }, [SocketService, showError, showInfo]);

    // Startup: OS, recordings, and recover state after a window reload.
    useEffect(() => {
        const offOs = ipc().on("get_os_system_response", (value: any) => setOs(value));
        ipc().sendMessage("get_os_system");
        fetchTasks();
        refreshStatus().then((data) => {
            if (data?.recording) {
                ipc().sendMessage(data.paused ? "pause-record-icon" : "start-record-icon");
            }
        });
        const offReduced = SocketService.Listen("reduced", (response: any) => {
            fetchTasks();
            if (response?.status === "failed") {
                showError("Processing failed for the last recording");
            } else {
                showSuccess("Recording processed and ready to review");
            }
        });
        return () => {
            offOs?.();
            offReduced();
        };
    }, [SocketService, fetchTasks, refreshStatus, showError, showSuccess]);

    // Global shortcuts from the main process.
    useEffect(() => {
        const offs = [
            ipc().on("start-record", () => startRecording()),
            ipc().on("stop-record", () => stopRecording()),
            ipc().on("toggle-pause-record", () => togglePause()),
        ];
        return () => offs.forEach((off) => off?.());
    }, [startRecording, stopRecording, togglePause]);

    // Live timer while recording.
    useEffect(() => {
        if (!status.recording) return;
        const timer = setInterval(refreshStatus, 1000);
        return () => clearInterval(timer);
    }, [status.recording, refreshStatus]);

    // Keep the "processing" badge fresh until reduction finishes.
    useEffect(() => {
        if (!recordings.some((r) => r.status === "processing")) return;
        const timer = setInterval(fetchTasks, 3000);
        return () => clearInterval(timer);
    }, [recordings, fetchTasks]);

    return (
        <MainContext.Provider
            value={{
                isRecording: status.recording,
                isPaused: status.paused,
                elapsedSeconds: status.elapsed_seconds,
                busy,
                startRecording,
                stopRecording,
                togglePause,
                recordings,
                recordingsLoaded,
                fetchTasks,
                SocketService,
                notify,
                showSuccess,
                showError,
                showInfo,
                myos: os,
            }}
        >
            {children}
            <Toasts toasts={toasts} onDismiss={(id) => setToasts((p) => p.filter((t) => t.id !== id))} />
        </MainContext.Provider>
    );
};

export const useMain = () => {
    const context = useContext(MainContext);
    if (context === undefined) {
        throw new Error("useMain must be used within a MainProvider");
    }
    return context;
};
