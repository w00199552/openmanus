const {app, BrowserWindow, ipcMain} = require("electron");
const path = require("path");

const isDev = !app.isPackaged;

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    frame: false,          // 去掉默认白色标题栏(无边框窗口)
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    // mainWindow.webContents.openDevTools();  //暂时注释,需要时手动打开
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
  }

  // 当窗口最大化时,通知前端切换 CSS(未来扩展用,当前无实际效果)
  const syncMaximized = () => {
    const maximized = mainWindow?.isMaximized() || false;
    mainWindow?.webContents.executeJavaScript(
      `document.documentElement.dataset.maximized = ${maximized ? '"1"' : '""'};`
    ).catch(() => {});
  };
  mainWindow.on("maximize", syncMaximized);
  mainWindow.on("unmaximize", syncMaximized);
  mainWindow.webContents.once("did-finish-load", syncMaximized);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// IPC: window controls (called from preload → renderer)
ipcMain.handle("window:minimize", () => {
  mainWindow?.minimize();
});

ipcMain.handle("window:maximize", () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize();
    return false;
  } else {
    mainWindow?.maximize();
    return true;
  }
});

ipcMain.handle("window:close", () => {
  mainWindow?.close();
});

ipcMain.handle("window:isMaximized", () => {
  return mainWindow?.isMaximized() || false;
});

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
