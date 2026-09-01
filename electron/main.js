const { app, BrowserWindow } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn, execFileSync } = require('child_process');

const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 5000;
// Generous timeout: first run downloads the ~1.1GB GGUF model before the
// backend reports ready. Subsequent launches are fast (model already local).
const BACKEND_READY_TIMEOUT_MS = 30 * 60 * 1000;
const BACKEND_POLL_INTERVAL_MS = 1000;

const STATUS_MESSAGES = {
    starting: 'Starting up...',
    downloading_model: 'Downloading AI model (first run only, this may take several minutes)...',
    loading_model: 'Loading AI model...',
};

let mainWindow;
let backendProcess;

function resolveBackendExePath() {
    // Packaged: electron-builder's extraResources places the PyInstaller
    // onedir build at <resources>/backend/run.exe. Dev: fall back to the
    // PyInstaller output next to this repo's backend/ folder.
    const packagedPath = path.join(process.resourcesPath, 'backend', 'run.exe');
    if (fs.existsSync(packagedPath)) {
        return packagedPath;
    }
    return path.join(__dirname, '..', 'backend', 'dist', 'run', 'run.exe');
}

function startBackend() {
    const exePath = resolveBackendExePath();
    if (!fs.existsSync(exePath)) {
        console.error('Backend executable not found at', exePath);
        return null;
    }

    const proc = spawn(exePath, [], {
        cwd: path.dirname(exePath),
        windowsHide: true,
    });

    proc.stdout.on('data', (data) => console.log(`[backend] ${data}`));
    proc.stderr.on('data', (data) => console.error(`[backend] ${data}`));
    proc.on('exit', (code) => console.log(`[backend] exited with code ${code}`));

    return proc;
}

function fetchHealth() {
    return new Promise((resolve, reject) => {
        const req = http.get({ host: BACKEND_HOST, port: BACKEND_PORT, path: '/api/health', timeout: 2000 }, (res) => {
            let body = '';
            res.on('data', (chunk) => { body += chunk; });
            res.on('end', () => {
                try {
                    resolve(JSON.parse(body));
                } catch (err) {
                    reject(err);
                }
            });
        });
        req.on('error', reject);
        req.on('timeout', () => req.destroy());
    });
}

function waitForBackend(timeoutMs, onStatus) {
    const deadline = Date.now() + timeoutMs;

    return new Promise((resolve, reject) => {
        const attempt = async () => {
            try {
                const health = await fetchHealth();
                if (health.error) {
                    reject(new Error(`Backend failed to start: ${health.error}`));
                    return;
                }
                if (health.ready) {
                    resolve();
                    return;
                }
                onStatus(health.status);
            } catch (err) {
                // Not listening yet (still spawning) - keep polling.
            }

            if (Date.now() > deadline) {
                reject(new Error('Backend did not become ready in time'));
            } else {
                setTimeout(attempt, BACKEND_POLL_INTERVAL_MS);
            }
        };
        attempt();
    });
}

function loadingHtml(message) {
    return 'data:text/html;charset=utf-8,' + encodeURIComponent(`
        <html>
        <body style="display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
                     font-family:system-ui,-apple-system,sans-serif;background:#1e1e2e;color:#cdd6f4;">
            <div style="text-align:center;">
                <div>${message}</div>
            </div>
        </body>
        </html>
    `);
}

// Only one copy of the app may run at a time. Without this, a second launch
// (the NSIS installer auto-launches on finish, so installing over a running
// app is the common trigger) spawns a second backend; both bind 127.0.0.1:5000
// via SO_REUSEADDR and write the same SQLite file through separate WALs, and a
// force-kill of either (installers force-kill to replace files) can strand
// uncheckpointed WAL data - observed as the database losing rows. The lock
// makes the second instance hand off to the first and quit instead.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
    app.quit();
} else {
    app.on('second-instance', () => {
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.focus();
        }
    });
}

app.whenReady().then(async () => {
    // A losing second instance has already called app.quit(); quit is async,
    // so bail out here too rather than spawning a backend on the way out.
    if (!gotSingleInstanceLock) return;

    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        webPreferences: {
            nodeIntegration: false, // Keep it false for security
            contextIsolation: true,
        }
    });

    mainWindow.loadURL(loadingHtml('Starting up...'));

    backendProcess = startBackend();
    if (!backendProcess) {
        mainWindow.loadURL(loadingHtml('Failed to start the backend. Please reinstall the app.'));
        return;
    }

    try {
        let lastStatus = null;
        await waitForBackend(BACKEND_READY_TIMEOUT_MS, (status) => {
            if (status !== lastStatus && mainWindow) {
                lastStatus = status;
                mainWindow.loadURL(loadingHtml(STATUS_MESSAGES[status] || 'Starting up...'));
            }
        });
        mainWindow.loadFile(path.join(__dirname, 'build', 'index.html'));
    } catch (err) {
        console.error(err);
        mainWindow.loadURL(loadingHtml('The backend is taking longer than expected to start.'));
    }

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
});

function stopBackend() {
    if (backendProcess && !backendProcess.killed) {
        // The backend spawns its own child (llama-server.exe). A plain
        // .kill() only terminates backend.exe itself - Windows does not
        // propagate that to children, and a forceful kill also skips the
        // backend's own atexit cleanup - so llama-server.exe is orphaned
        // left running otherwise (confirmed while testing this). Killing
        // the whole process tree via taskkill avoids that.
        try {
            execFileSync('taskkill', ['/pid', String(backendProcess.pid), '/T', '/F']);
        } catch (err) {
            // Process may have already exited; fall back to a plain kill.
            backendProcess.kill();
        }
        backendProcess = null;
    }
}

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
    stopBackend();
    if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', stopBackend);
