import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog requireText gating", () => {
  it("keeps the confirm button disabled until the exact phrase is typed", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog title="Activar LIVE" requireText="ACTIVAR LIVE" onConfirm={onConfirm} onCancel={() => {}}>
        <p>test</p>
      </ConfirmDialog>,
    );

    const confirmButton = screen.getByText("Confirmar");
    expect(confirmButton).toBeDisabled();

    const input = screen.getByPlaceholderText(/ACTIVAR LIVE/);
    fireEvent.change(input, { target: { value: "wrong phrase" } });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(input, { target: { value: "activar live" } }); // case-insensitive match is fine
    expect(confirmButton).not.toBeDisabled();

    fireEvent.click(confirmButton);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("has no gating when requireText is not provided", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog title="Simple action" onConfirm={onConfirm} onCancel={() => {}}>
        <p>test</p>
      </ConfirmDialog>,
    );
    expect(screen.getByText("Confirmar")).not.toBeDisabled();
  });
});
