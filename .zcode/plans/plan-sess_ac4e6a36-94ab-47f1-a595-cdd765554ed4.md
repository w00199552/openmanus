## Sandbox 右键菜单 + Modal 确认（用 Radix 现成组件）

### 安装依赖

```bash
cd frontend
yarn add @radix-ui/react-context-menu @radix-ui/react-dialog
```

### 后端：新增 3 个端点 (`backend/src/openmanus/api/files.py`)

| 方法 | 路径 | 功能 |
|------|------|------|
| DELETE | `/files/delete` body `{path, workdir}` | 删除文件(`unlink`)或目录(`shutil.rmtree`) |
| POST | `/files/mkdir` body `{path, workdir}` | 创建目录 |
| POST | `/files/create` body `{path, workdir}` | 创建空文件 |

复用 `_safe_resolve(path, workdir)`。操作触发 watchdog → 前端自动刷新 tree。

### Store：新增 3 个方法 (`frontend/src/stores/SandboxStore.js`)

```javascript
async deletePath(path)    // DELETE /files/delete
async createDir(path)     // POST /files/mkdir
async createFile(path)    // POST /files/create
```

### 前端组件（新建 shadcn 风格组件）

**1. `frontend/src/components/ui/dialog.jsx`** — Radix Dialog 封装

shadcn 标准 Dialog 组件，从 popover.jsx 模板复制动画类。提供 `Dialog.Root/Trigger/Portal/Overlay/Content/Title/Description`。

**2. `frontend/src/components/ui/context-menu.jsx`** — Radix ContextMenu 封装

shadcn 标准 ContextMenu 组件。提供 `ContextMenu.Root/Trigger/Portal/Content/Item/Separator`。

**3. 新建 `frontend/src/components/sandbox/ConfirmDialog.jsx`** — 基于 Dialog 的确认弹窗

两种模式：
- **confirm**（删除确认）：标题 + 消息 + Cancel/Delete 按钮（destructive 红色）
- **prompt**（输入文件名）：标题 + Input + Cancel/Create 按钮

```jsx
<ConfirmDialog
  open={modal.open}
  mode="delete"           // or "newFile" | "newDir"
  title="Delete xxx?"
  message="This action cannot be undone."
  defaultValue=""
  onCancel={() => ...}
  onConfirm={(value) => ...}
/>
```

### 修改 `frontend/src/views/Playground.jsx`

**TreeNode 变更：**
- 用 `ContextMenu.Root` + `ContextMenu.Trigger` 包裹每个节点的 `<button>`
- 菜单项根据节点类型：
  - **目录**：New File / New Folder / Delete
  - **文件**：Delete
  - **根（空白区）**：New File / New Folder

**Playground 顶层新增状态：**
- `modal: {mode: 'delete'|'newFile'|'newDir', node, path}` — 控制弹窗
- 菜单项 onClick → 设置 modal state → ConfirmDialog 弹出 → 确认后调 sandbox API → watchdog 自动刷新 tree