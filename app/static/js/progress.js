// "Write an AI draft" button on the session record page.
// The reply is shown with .value (plain text) and the tutor must review it before saving.
document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("genSummary");
  if (!button) return;

  const status = document.getElementById("genStatus");
  const field = (id) => document.getElementById(id).value.trim();

  button.addEventListener("click", async () => {
    status.textContent = "Writing a draft… this can take a minute.";
    button.disabled = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 150000);
    try {
      const res = await fetch(button.dataset.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": button.dataset.csrf },
        body: JSON.stringify({
          topics: field("topics_covered"),
          outcomes: field("outcomes"),
          next_steps: field("next_steps"),
        }),
        signal: controller.signal,
        credentials: "same-origin",
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* not JSON */ }
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.error) || "Something went wrong. Please try again.");
      }
      document.getElementById("summary_text").value = data.reply;
      document.getElementById("ai_assisted").value = "1";
      status.textContent = "AI draft added below. Please read it, correct any mistakes, then save.";
    } catch (err) {
      status.textContent = err.name === "AbortError"
        ? "The request took too long. You can write the recap yourself."
        : err.message + " You can still write the recap yourself.";
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
});