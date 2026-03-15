/**
 * PhysiHow: exercise picker or camera + coach session.
 * Route by ?exercise= slug.
 */
import "./style.css";
import { initExercisePicker } from "./exercise-picker.js";
import { initSession } from "./session.js";

const APP_ID = "app";

function route(): void {
  const app = document.getElementById(APP_ID);
  if (!app) return;
  const params = new URLSearchParams(location.search);
  const exercise = params.get("exercise");
  if (exercise) {
    initSession(app, exercise, () => {
      history.replaceState({}, "", "/");
      route();
    });
  } else {
    initExercisePicker(app, (slug) => {
      history.pushState({}, "", `?exercise=${encodeURIComponent(slug)}`);
      route();
    });
  }
}

route();
window.addEventListener("popstate", route);
