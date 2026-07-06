const { app, BrowserWindow } = require('electron');
const path = require('path');

let mainWindow;

app.whenReady().then(() => {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        webPreferences: {
            nodeIntegration: false, // Keep it false for security
            contextIsolation: true,
        }
    });

    // Load the built React app
    mainWindow.loadFile(path.join(__dirname, 'build', 'index.html'));

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
});

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
