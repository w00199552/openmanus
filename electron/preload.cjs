const {contextBridge, ipcRenderer} = require("electron");

// Expose window control APIs to the renderer
contextBridge.exposeInMainWorld("electron", {
  platform: process.platform,
  isElectron: true,
  window: {
    minimize: () => ipcRenderer.invoke("window:minimize"),
    maximizeToggle: () => ipcRenderer.invoke("window:maximize"),
    close: () => ipcRenderer.invoke("window:close"),
    isMaximized: () => ipcRenderer.invoke("window:isMaximized"),
  },
});
