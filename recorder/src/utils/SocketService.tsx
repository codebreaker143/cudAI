import { io, Socket } from "socket.io-client";
import { API_BASE, apiToken } from "../lib/api";

// Stopping finalizes and joins the video, which can take a while.
const TIMEOUTS: Record<string, number> = { stop_record: 5 * 60_000 };
const DEFAULT_TIMEOUT = 60_000;

class SocketIOService {
    private socket: Socket;

    constructor() {
        this.socket = io(API_BASE, { auth: { token: apiToken() } });
    }

    destroy() {
        this.socket.disconnect();
    }

    /** Emit `event` and wait for the backend's reply on the same event name. */
    public request(event: string, payload: Record<string, unknown> = {}): Promise<any> {
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                this.socket.off(event, onReply);
                reject(new Error("The cudAI service did not respond in time"));
            }, TIMEOUTS[event] ?? DEFAULT_TIMEOUT);

            const onReply = (data: any) => {
                clearTimeout(timeout);
                this.socket.off(event, onReply);
                if (data?.status === "succeed") {
                    resolve(data);
                } else {
                    reject(new Error(data?.message || "An unknown error occurred"));
                }
            };

            this.socket.on(event, onReply);
            this.socket.emit(event, payload);
        });
    }

    public Get(event: string): Promise<any> {
        return this.request(event);
    }

    public Post(event: string, data: Record<string, unknown>): Promise<any> {
        return this.request(event, data);
    }

    public Send(event: string, data: Record<string, unknown>): void {
        this.socket.emit(event, data);
    }

    public Listen(event: string, callback: (data: any) => void): () => void {
        this.socket.on(event, callback);
        return () => this.socket.off(event, callback);
    }
}

export default SocketIOService;
