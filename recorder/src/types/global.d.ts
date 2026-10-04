declare global {
    interface Window {
        electron: {
            /** Token every request to the local backend must carry. */
            apiToken: string;
            ipcRenderer: {
                sendMessage(channel: string, ...args: unknown[]): void;
                /** Subscribe; returns a function that unsubscribes. */
                on(channel: string, func: (...args: unknown[]) => void): () => void;
            };
        };
    }
}

export {};
