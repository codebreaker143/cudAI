import {
  app,
  BrowserWindow,
  screen,
  dialog,
  ipcMain,
  globalShortcut,
  shell,
  Notification,
  protocol,
  Menu,
  nativeImage,
  Tray,
  systemPreferences,
  nativeTheme,
} from "electron";
import { spawn, ChildProcess, execSync } from "child_process";
import axios from "axios";
import { randomBytes } from "crypto";
import path from "path";
import {
  createTray,
  PauseRecording,
  StartRecording,
  StopRecording,
  updateTrayIcon,
  APP_TITLE,
} from "./trayicon";

const log = require("electron-log");

declare const MAIN_WINDOW_WEBPACK_ENTRY: string;
declare const MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY: string;

let tray: Tray | null = null;
if (require("electron-squirrel-startup")) {
  app.quit();
}


let mainWindow: BrowserWindow | null = null;

// Shared secret for this launch: the backend rejects requests without it, so
// other local software and web pages cannot read recordings.
const API_TOKEN = randomBytes(32).toString("hex");
const API_HEADERS = { "X-Cudai-Token": API_TOKEN };
let flaskProcess: ChildProcess | null = null;

const createWindow = (): void => {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: 1100,
    minHeight: 700,
    title: APP_TITLE,
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#09090b" : "#ffffff",
    webPreferences: {
      preload: MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY,
      additionalArguments: [`--cudai-api-token=${API_TOKEN}`],
      contextIsolation: true,
      nodeIntegration: false,
      // No inspector in shipped builds.
      devTools: !app.isPackaged,
    },
  });

  mainWindow.loadURL(MAIN_WINDOW_WEBPACK_ENTRY);

  // Opt-in while developing: CUDAI_DEVTOOLS=1 npm start
  if (!app.isPackaged && process.env.CUDAI_DEVTOOLS === "1") {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
};

const startFlaskServer = (): void => {
  // Lets the backend recognise (and exclude) input to cudAI's own windows.
  const env = {
    ...process.env,
    CUDAI_APP_PID: String(process.pid),
    CUDAI_API_TOKEN: API_TOKEN,
  };
  if (app.isPackaged) {
    flaskProcess = spawn(path.join(process.resourcesPath, "backend/backend"), {
      env,
      shell: false,
    });
  } else {
    flaskProcess = spawn("python", ["api/backend.py"], {
      env: { ...env, FLASK_DEBUG: "1" },
      shell: true,
    });
  }

  flaskProcess.stdout.on("data", (data) => {
    console.log(`Flask stdout: ${data}`);
  });

  flaskProcess.stderr.on("data", (data) => {
    console.error(`Flask stderr: ${data}`);
  });

  flaskProcess.on("close", (code) => {
    console.log(`Flask process exited with code ${code}`);
  });
};

const stopFlaskServer = (): void => {
  if (flaskProcess) {
    flaskProcess.kill();
    flaskProcess = null;
  }
};

const checkFlaskServer = async (): Promise<void> => {
  try {
    await axios.get("http://127.0.0.1:5328/api/recordings", { headers: API_HEADERS });
    if (process.platform === "darwin") {
      await axios.get("http://127.0.0.1:5328/api/permissions", { headers: API_HEADERS });
    }
    createWindow();
  } catch (error) {
    console.log("Waiting for Flask server to start...");
    setTimeout(checkFlaskServer, 1000);
  }
};

app.on("ready", () => {
    if (process.platform === "darwin") {
    const accessibilityTrusted =
      systemPreferences.isTrustedAccessibilityClient(true);

    log.info(
      `Accessibility permission: ${
        accessibilityTrusted ? "granted" : "not granted"
      }`
    );

    const screenPermission =
      systemPreferences.getMediaAccessStatus("screen");

    log.info(
      `Screen recording permission: ${screenPermission}`
    );
  }
  startFlaskServer();
  log.info("Flask server started");
  checkFlaskServer();
  log.info("Checked Flask server");

  ipcMain.on("start-record-icon", () => {
    StartRecording();
    tray?.setTitle("Recording...");
  });
  ipcMain.on("stop-record-icon", () => {
    StopRecording();
  });
  ipcMain.on("pause-record-icon", () => {
    PauseRecording();
  });
  ipcMain.on("resume-record-icon", () => {
    StartRecording();
  });

  ipcMain.on("tree-start", () => {
    updateTrayIcon("red");
    tray?.setTitle("Please Don't move....");
  });

  ipcMain.on("tree-end", () => {
    updateTrayIcon("green");
    tray?.setTitle("Recording...");
  });

  globalShortcut.register("CommandOrControl+Alt+R", () => {
    mainWindow?.webContents.send("start-record");
  });

  globalShortcut.register("CommandOrControl+Alt+T", () => {
    mainWindow?.webContents.send("stop-record");
  });

  globalShortcut.register("CommandOrControl+Alt+P", () => {
    mainWindow?.webContents.send("toggle-pause-record");
  });

  ipcMain.on("minimize-window", () => {
    if (mainWindow) {
      mainWindow.minimize();
    }
  });

  ipcMain.on("maximize-window", () => {
    if (mainWindow) {
      if (mainWindow.isMaximized()) {
        mainWindow.unmaximize();
      } else {
        mainWindow.maximize();
      }
    }
  });

  // Reveal a recording (or the recordings folder) in Finder. Only paths inside
  // the cudAI data directory are allowed.
  ipcMain.on("show-in-folder", (_event, target: unknown) => {
    if (typeof target !== "string") return;
    const resolved = path.resolve(target);
    const dataDir = path.join(app.getPath("home"), "Library", "Application Support", "cudAI");
    if (process.platform === "darwin" && !resolved.startsWith(dataDir)) return;
    shell.showItemInFolder(resolved);
  });

  // Permissions setup: open the matching System Settings pane.
  ipcMain.on("open-system-settings", (_event, url: unknown) => {
    if (typeof url === "string" && url.startsWith("x-apple.systempreferences:")) {
      shell.openExternal(url);
    }
  });

  // macOS applies newly granted permissions only after a restart.
  ipcMain.on("relaunch-app", () => {
    app.relaunch();
    app.quit();
  });

  // Used by the consent screen: the app cannot be used without consent.
  ipcMain.on("quit-app", () => {
    app.quit();
  });

  ipcMain.on("get_os_system", () => {
    log.info("Received get_os_system request");
    mainWindow?.webContents.send("get_os_system_response", process.platform);
  });
});

app.whenReady().then(() => {
  tray = createTray(app);
});

const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  app.on("second-instance", (event, commandLine, workingDirectory) => {
    // Someone tried to run a second instance, we should focus our window.
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
    const url = commandLine.pop();
    console.log(`You arrived from ${url}`);
  });
}


app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("will-quit", async () => {
  if (process.platform === "win32") {
    await kill_process(5328);
  }
  stopFlaskServer();
  globalShortcut.unregisterAll();
});

function kill_process(port: number): Promise<void> {
  return new Promise((resolve, reject) => {
    console.log(`Checking for processes using port ${port}...`);

    try {
      const stdout = execSync("netstat -ano").toString();
      const lines = stdout.split("\n");
      const pids = new Set<number>();

      for (const line of lines) {
        if (line.includes(`:${port}`)) {
          const parts = line.trim().split(/\s+/);
          const pid = parseInt(parts[parts.length - 1], 10);
          if (!isNaN(pid) && pid !== 0) {
            pids.add(pid);
          }
        }
      }

      if (pids.size === 0) {
        console.log(`No processes found using port ${port}.`);
        resolve();
        return;
      }

      pids.forEach((pid) => {
        console.log(`Killing process with PID ${pid} using port ${port}.`);
        try {
          execSync(`taskkill /F /PID ${pid}`);
          console.log(`Successfully killed process with PID ${pid}.`);
        } catch (error) {
          console.error(`Failed to kill process with PID ${pid}: ${error}`);
        }
      });

      resolve();
    } catch (error) {
      console.error(`Failed to run netstat command: ${error}`);
      reject(error);
    }
  });
}
