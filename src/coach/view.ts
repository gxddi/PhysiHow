/**
 * Updates the coach status indicator in the session overlay.
 * CSS classes: .coach-panel-status.ready / .speaking / .error (idle = no modifier).
 */

export type StatusType = "idle" | "ready" | "speaking" | "error";

export function setCoachOverlayStatus(text: string, type: StatusType = "idle"): void {
  const el = document.getElementById("coach-overlay-status");
  if (!el) return;
  el.textContent = text;
  el.className = "coach-panel-status";
  if (type !== "idle") el.classList.add(type);
}
