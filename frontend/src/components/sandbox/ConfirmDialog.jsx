import {useState, useEffect, useRef} from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {cn} from "@/lib/utils";
import {Loader2} from "lucide-react";

/**
 * ConfirmDialog — a modal for Sandbox file operations.
 *
 * Modes:
 *   - "delete":  title + message + Cancel / Delete (destructive red)
 *   - "newFile": title + input + Cancel / Create
 *   - "newDir":  title + input + Cancel / Create
 *
 * @param {boolean}  open
 * @param {"delete"|"newFile"|"newDir"} mode
 * @param {string}   title
 * @param {string}   message         (delete mode)
 * @param {string}   defaultValue    (prompt mode)
 * @param {function} onCancel
 * @param {function} onConfirm       delete: () => Promise; prompt: (name) => Promise
 */
export function ConfirmDialog({
  open, mode, title, message, defaultValue = "",
  onCancel, onConfirm,
}) {
  const [value, setValue] = useState(defaultValue);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  const isPrompt = mode === "newFile" || mode === "newDir";

  // reset state when dialog opens
  useEffect(() => {
    if (open) {
      setValue(defaultValue);
      setError("");
      setBusy(false);
      // focus input after render
      if (isPrompt) {
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    }
  }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleConfirm = async () => {
    if (isPrompt) {
      const name = value.trim();
      if (!name) {
        setError("Name cannot be empty");
        return;
      }
      // basic validation: no path separators
      if (name.includes("/") || name.includes("\\")) {
        setError("Name cannot contain / or \\");
        return;
      }
    }
    setBusy(true);
    setError("");
    try {
      if (isPrompt) {
        await onConfirm(value.trim());
      } else {
        await onConfirm();
      }
    } catch (e) {
      setError(e.message || "Operation failed");
      setBusy(false);
      return; // keep dialog open on error
    }
    setBusy(false);
  };

  // Enter key submits in prompt mode
  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !busy) {
      e.preventDefault();
      handleConfirm();
    }
  };

  const confirmLabel = mode === "delete" ? "Delete" : "Create";
  const confirmClass = mode === "delete"
    ? "bg-destructive/90 text-white hover:bg-destructive"
    : "bg-accent/20 text-accent hover:bg-accent/30";

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !busy) onCancel(); }}>
      <DialogContent className="max-w-sm" onKeyDown={handleKeyDown}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {message && <DialogDescription>{message}</DialogDescription>}
        </DialogHeader>

        {isPrompt && (
          <div className="mb-1">
            <input
              ref={inputRef}
              type="text"
              value={value}
              onChange={(e) => { setValue(e.target.value); setError(""); }}
              placeholder={mode === "newDir" ? "folder-name" : "filename.ext"}
              className="w-full rounded-md border border-border/80 bg-background px-3 py-2 text-[13px] text-foreground outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30"
            />
          </div>
        )}

        {error && (
          <p className="mb-2 text-[12px] text-destructive">{error}</p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            onClick={onCancel}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-[13px] text-muted-foreground transition hover:bg-sidebar/40 hover:text-foreground disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={busy || (isPrompt && !value.trim())}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition disabled:opacity-50",
              confirmClass,
            )}
          >
            {busy && <Loader2 className="size-3 animate-spin"/>}
            {confirmLabel}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
