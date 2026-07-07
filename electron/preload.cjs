const { contextBridge } = require("electron");

// preload: expose safe APIs to the renderer (frontend) via window.electron
// Add more as needed (file dialogs, clipboard, etc.)
contextBridge.exposeInMainWorld("electron", {
  platform: process.platform,
  isElectron: true,
});
