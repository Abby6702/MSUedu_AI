// The tutor's AI panel in the live room. Everything from the server is shown as plain text,
// so AI content cannot run as code. Nothing here is sent to the student.
document.addEventListener("DOMContentLoaded", () => {
  const panel = document.getElementById("aiPanel");
  const toggle = document.getElementById("btnAi");
  if (!panel || !toggle) return;

  const $ = (id) => document.getElementById(id);
  const url = panel.dataset.url, csrf = panel.dataset.csrf;
  const LABELS = { exercises: "Generate exercises", explain: "Explain topic", quiz: "Create quiz",
                   hint: "Give hints", next_lesson: "Recommend next lesson" };
  const buttons = Array.from(panel.querySelectorAll("[data-action]"));
  const groups = Array.from(panel.querySelectorAll("[data-for]"));
  let action = "exercises", lastText = "";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function clearOutput() {
    while ($("aiOut").firstChild) $("aiOut").removeChild($("aiOut").firstChild);
    $("aiError").hidden = true;
    lastText = "";
  }
  function choose(name) {
    action = name;
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.action === name)));
    groups.forEach((g) => { g.hidden = !g.dataset.for.split(" ").includes(name); });
    $("aiGo").textContent = LABELS[name];
    clearOutput();
  }
  buttons.forEach((b) => b.addEventListener("click", () => choose(b.dataset.action)));

  toggle.addEventListener("click", () => {
    const show = panel.hidden;
    panel.hidden = !show;
    toggle.setAttribute("aria-pressed", String(show));
    if (show) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  function payload() {
    return {
      action,
      topic: $("aiTopic").value,
      level: $("aiLevel").value,
      count: Number(action === "quiz" ? $("aiQuizCount").value : $("aiCount").value),
      include_answers: $("aiAnswers").checked,
      difficulty: $("aiDifficulty").value,
      types: Array.from(panel.querySelectorAll("input[name=aiType]:checked")).map((i) => i.value),
      problem: $("aiProblem").value,
      attempt: $("aiAttempt").value,
      notes: $("aiNotes").value,
    };
  }

  function addCopy() {
    const copy = el("button", "btn btn-small btn-outline", "Copy");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(lastText); copy.textContent = "Copied"; }
      catch (_) { copy.textContent = "Copy failed"; }
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    $("aiOut").appendChild(copy);
  }

  function render(data) {
    clearOutput();
    $("aiOut").appendChild(el("p", "ai-label", "AI draft for you to check. It can contain mistakes."));
    if (data.kind === "text") {
      lastText = data.text;
      $("aiOut").appendChild(el("div", "ai-text", data.text));
    } else if (data.kind === "quiz") {
      const lines = [];
      data.questions.forEach((q, i) => {
        const box = el("div", "ai-item");
        box.appendChild(el("p", null, (i + 1) + ". " + q.question));
        lines.push((i + 1) + ". " + q.question);
        if (q.options) {
          const list = el("ul");
          q.options.forEach((o, n) => {
            const line = String.fromCharCode(65 + n) + ". " + o;
            list.appendChild(el("li", null, line));
            lines.push("   " + line);
          });
          box.appendChild(list);
        }
        box.appendChild(el("p", "meta", "Answer: " + q.answer));
        box.appendChild(el("p", "meta", "Why: " + q.explanation));
        lines.push("   Answer: " + q.answer, "   Why: " + q.explanation, "");
        $("aiOut").appendChild(box);
      });
      lastText = lines.join("\n");
    } else if (data.kind === "lesson") {
      const box = el("div", "ai-item");
      box.appendChild(el("p", null, "Suggested lesson: " + data.lesson.title + " (topic: " + data.lesson.topic + ")"));
      box.appendChild(el("p", "meta", data.reason));
      $("aiOut").appendChild(box);
      lastText = data.lesson.title + " (" + data.lesson.topic + "): " + data.reason;
    }
    addCopy();
  }

  $("aiGo").addEventListener("click", async () => {
    clearOutput();
    $("aiGo").disabled = true;
    $("aiBusy").hidden = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 150000);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(payload()),
        signal: controller.signal,
        credentials: "same-origin",
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* not JSON */ }
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.error) || "Something went wrong. Please try again.");
      }
      render(data);
    } catch (err) {
      $("aiError").textContent = err.name === "AbortError"
        ? "The request took too long. Please try again." : err.message;
      $("aiError").hidden = false;
    } finally {
      clearTimeout(timer);
      $("aiGo").disabled = false;
      $("aiBusy").hidden = true;
    }
  });

  choose("exercises");
});