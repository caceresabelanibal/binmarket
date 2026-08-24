import { ReactNode, useState } from "react";
import { Button } from "./ui";

export function ConfirmDialog({
  title,
  children,
  confirmLabel = "Confirmar",
  requireText,
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  requireText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const canConfirm = !requireText || text.trim().toUpperCase() === requireText.toUpperCase();

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg max-w-md w-full p-5">
        <h3 className={`text-lg font-semibold mb-3 ${danger ? "text-red-400" : "text-slate-100"}`}>{title}</h3>
        <div className="text-sm text-slate-300 space-y-2 mb-4">{children}</div>
        {requireText && (
          <input
            className="w-full mb-4 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
            placeholder={`Escribir "${requireText}" para confirmar`}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancelar
          </Button>
          <Button variant={danger ? "danger" : "primary"} disabled={!canConfirm} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
