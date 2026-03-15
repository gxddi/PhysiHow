/**
 * Exercise picker screen: list from Uni Melbourne CHESM video library, search, Start → session.
 */
import { listExercises, type ExerciseListItem } from "./api.js";

let container: HTMLElement | null = null;
let onStart: (slug: string) => void = () => {};

export function initExercisePicker(
  mountEl: HTMLElement,
  onStartCallback: (slug: string) => void
): void {
  container = mountEl;
  onStart = onStartCallback;
  container.innerHTML = `
    <div class="picker-screen">
      <header class="picker-header">
        <h1 class="picker-title">PhysiHow</h1>
        <p class="picker-subtitle">Knee & hip osteoarthritis exercises. Choose an exercise — your coach will guide you (source: Uni Melbourne CHESM).</p>
        <input type="search" id="picker-search" class="picker-search" placeholder="Search exercises..." aria-label="Search exercises" />
      </header>
      <div id="picker-list" class="picker-list">
        <p class="picker-loading">Loading exercises…</p>
      </div>
    </div>
  `;
  const searchInput = container.querySelector<HTMLInputElement>("#picker-search");
  const listEl = container.querySelector<HTMLDivElement>("#picker-list");
  if (!listEl) return;

  let exercises: ExerciseListItem[] = [];
  let filtered: ExerciseListItem[] = [];

  function renderList(items: ExerciseListItem[]): void {
    if (!listEl) return;
    if (items.length === 0) {
      listEl.innerHTML = '<p class="picker-empty">No exercises match.</p>';
      return;
    }
    listEl.innerHTML = items
      .map(
        (ex) => `
      <article class="picker-card" data-slug="${ex.slug}">
        <h2 class="picker-card-title">${escapeHtml(ex.name)}</h2>
        <a href="${escapeHtml(ex.url)}" target="_blank" rel="noopener noreferrer" class="picker-card-link">View in video library</a>
        <button type="button" class="btn btn-primary picker-card-btn">Start</button>
      </article>
    `
      )
      .join("");
    listEl.querySelectorAll(".picker-card-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest("[data-slug]");
        const slug = card?.getAttribute("data-slug");
        if (slug) onStart(slug);
      });
    });
  }

  function filterList(): void {
    const q = (searchInput?.value ?? "").trim().toLowerCase();
    filtered = q
      ? exercises.filter(
          (ex) =>
            ex.name.toLowerCase().includes(q) || ex.slug.toLowerCase().includes(q)
        )
      : exercises;
    renderList(filtered);
  }

  searchInput?.addEventListener("input", filterList);

  listExercises()
    .then((data) => {
      exercises = data.exercises ?? [];
      filtered = exercises;
      renderList(filtered);
    })
    .catch((err) => {
      if (listEl) listEl.innerHTML = `<p class="picker-error">Failed to load exercises: ${escapeHtml(err.message)}</p>`;
    });
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
