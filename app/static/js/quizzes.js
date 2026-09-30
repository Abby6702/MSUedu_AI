// Stops double-clicks on forms that take a while (generating or submitting a quiz).
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-busy]").forEach((form) => {
    const button = form.querySelector("button[type=submit]");
    const original = button ? button.textContent : "";

    form.addEventListener("submit", () => {
      if (button) {
        button.disabled = true;
        button.textContent = form.dataset.busy;
      }
      const note = form.querySelector(".busy-note");
      if (note) note.hidden = false;
    });

    // If the student presses the browser's Back button, make the form usable again.
    window.addEventListener("pageshow", (event) => {
      if (event.persisted && button) {
        button.disabled = false;
        button.textContent = original;
      }
    });
  });
});