// "Write an AI draft" on the session summary page. Text is put into boxes with .value
// (plain text). The tutor must read and edit it before saving.
document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("genDraft");
  if (!button) return;
  const status = document.getElementById("draftStatus");
  const $ = (id) => document.getElementById(id);
  const FIELDS = ["topics_covered", "strengths", "improvements", "practice"];

  button.addEventListener("click", async () => {
    const notes = $("draftNotes").value.trim();
    if (notes.length < 20) {
      status.textContent = "Write a few sentences of notes first (at least 20 characters).";
      return;
    }
    if (FIELDS.some((f) => $(f).value.trim()) &&
        !window.confirm("This replaces what is already in the boxes below. Continue?")) return;
    button.disabled = true;
    status.textContent = "Writing a draft… this can take a minute.";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 150000);
    try {
      const res = await fetch(button.dataset.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": button.dataset.csrf },
        body: JSON.stringify({ notes }),
        signal: controller.signal,
        credentials: "same-origin",
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* not JSON */ }
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.error) || "Something went wrong. Please try again.");
      }
      const draft = data.draft;
      FIELDS.forEach((f) => { $(f).value = draft[f] || ""; });
      $("next_lesson_id").value = draft.next_lesson_id ? String(draft.next_lesson_id) : "";
      $("ai_assisted").value = "1";
      status.textContent = "AI draft added below. Please read it, correct any mistakes, then save.";
    } catch (err) {
      status.textContent = err.name === "AbortError"
        ? "The request took too long. You can write the summary yourself."
        : err.message + " You can still write the summary yourself.";
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
});