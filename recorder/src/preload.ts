import { contextBridge, ipcRenderer, IpcRendererEvent } from "electron";

// Per-launch token for the local backend, passed by the main process.
const TOKEN_ARG = "--cudai-api-token=";
const apiToken =
    process.argv.find((arg) => arg.startsWith(TOKEN_ARG))?.slice(TOKEN_ARG.length) ?? "";

contextBridge.exposeInMainWorld("electron", {
    apiToken,
    ipcRenderer: {
        sendMessage(channel: string, ...args: unknown[]) {
            ipcRenderer.send(channel, ...args);
        },
        /** Subscribe; returns a function that unsubscribes. */
        on(channel: string, func: (...args: unknown[]) => void) {
            const subscription = (_event: IpcRendererEvent, ...args: unknown[]) => func(...args);
            ipcRenderer.on(channel, subscription);
            return () => ipcRenderer.removeListener(channel, subscription);
        },
    },
});
