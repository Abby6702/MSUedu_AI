// Talks to OUR Flask server only. Everything from the server is inserted as plain text,
// so it cannot run code.
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("agent");
  if (!root) return;

  const csrf = root.dataset.csrf;
  const $ = (id) => document.getElementById(id);
  let context = null;                         // subject/topic/duration of the latest suggestions

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function postJson(url, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 150000);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(payload || {}),
        signal: controller.signal,
        credentials: "same-origin",
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* not JSON */ }
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.error) || "Something went wrong. Please try again.");
      }
      return data;
    } catch (err) {
      if (err.name === "AbortError") throw new Error("The request took too long. Please try again.");
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  function add(node) {
    const empty = $("chatEmpty");
    if (empty) empty.remove();
    $("chatLog").appendChild(node);
    $("chatLog").scrollTop = $("chatLog").scrollHeight;
  }

  // ---------- service status banner ----------
  fetch(root.dataset.statusUrl, { credentials: "same-origin" })
    .then((r) => r.json())
    .then((s) => {
      if (!s.running || !s.model_ready) {
        $("aiBanner").textContent = "The AI service is not ready right now, so the coordinator " +
          "cannot understand messages. If you are the developer, check Ollama and OLLAMA_MODEL.";
        $("aiBanner").hidden = false;
      }
    })
    .catch(() => {});

  // ---------- rendering ----------
  function renderSteps(steps) {
    if (!steps || !steps.length) return;
    const box = el("details", "agent-steps");
    box.appendChild(el("summary", null, `What the coordinator did (${steps.length} step${steps.length === 1 ? "" : "s"})`));
    const list = el("ul");
    steps.forEach((s) => {
      list.appendChild(el("li", null, (s.kind === "plan" ? "Plan (AI): " : "Tool (checked code): ") + s.text));
    });
    box.appendChild(list);
    add(box);
  }

  function renderProposal(card) {
    const box = el("div", "card proposal-card");
    box.appendChild(el("h3", "card-title", card.title));
    const list = el("ul");
    card.lines.forEach((line) => list.appendChild(el("li", null, line)));
    box.appendChild(list);
    box.appendChild(el("p", "hint",
      `Prepared only. Nothing happens until you confirm. Expires in ${card.expires_minutes} minutes.`));
    const result = el("p", "proposal-result");
    const actions = el("p", "review-actions");
    const confirm = el("button", "btn", "Confirm");
    const discard = el("button", "btn btn-outline", "Discard");
    confirm.type = discard.type = "button";
    actions.append(confirm, discard);
    box.append(actions, result);

    const urlFor = (template) => template.replace("/0/", "/" + card.id + "/");
    async function finish(url, button, okClass) {
      confirm.disabled = discard.disabled = true;
      try {
        const data = await postJson(url, {});
        result.textContent = data.message;
        result.className = "proposal-result flash " + okClass;
        actions.hidden = true;
      } catch (err) {
        result.textContent = err.message;
        result.className = "proposal-result flash flash-error";
        confirm.disabled = discard.disabled = false;
        if (/already handled|expired|not found/i.test(err.message)) actions.hidden = true;
      }
    }
    confirm.addEventListener("click", () => finish(urlFor(root.dataset.confirmUrl), confirm, "flash-success"));
    discard.addEventListener("click", () => finish(urlFor(root.dataset.discardUrl), discard, "flash-info"));
    add(box);
  }

  function renderSuggestions(list, ctx) {
    list.forEach((s) => {
      const box = el("div", "card suggestion");
      box.appendChild(el("h3", "card-title", s.tutor_name));
      box.appendChild(el("p", "meta", (s.course ? s.course + " · " : "") + s.format_label));
      const why = el("ul");
      s.why.forEach((w) => why.appendChild(el("li", null, w)));
      box.appendChild(why);
      box.appendChild(el("p", null, "Open times (Philippine time). Click one to prepare a request:"));
      const slots = el("div", "slot-list");
      s.slots.forEach((slot) => {
        const b = el("button", "btn btn-small btn-outline", slot.label);
        b.type = "button";
        b.addEventListener("click", async () => {
          b.disabled = true;
          try {
            const data = await postJson(root.dataset.prepareUrl, {
              tutor_id: s.tutor_id, subject_id: ctx.subject_id, topic: ctx.topic,
              format: s.format, start: slot.start_iso, duration: ctx.duration,
            });
            renderProposal(data.proposal);
          } catch (err) {
            add(el("div", "msg msg-error", err.message));
          } finally {
            b.disabled = false;
          }
        });
        slots.appendChild(b);
      });
      box.appendChild(slots);
      add(box);
    });
  }

  // ---------- sending ----------
  async function send(message) {
    if (!message) return;
    add(el("div", "msg msg-user", message));
    $("chatInput").value = "";
    $("chatSend").disabled = true;
    $("chatBusy").hidden = false;
    try {
      const data = await postJson(root.dataset.messageUrl, { message });
      renderSteps(data.steps);
      add(el("div", "msg msg-ai", data.reply));
      if (data.context) context = data.context;
      if (data.suggestions && data.suggestions.length) renderSuggestions(data.suggestions, data.context || context);
      (data.proposals || []).forEach(renderProposal);
    } catch (err) {
      add(el("div", "msg msg-error", err.message));
    } finally {
      $("chatSend").disabled = false;
      $("chatBusy").hidden = true;
      $("chatInput").focus();
    }
  }

  $("chatSend").addEventListener("click", () => send($("chatInput").value.trim()));
  $("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("chatInput").value.trim()); }
  });
  $("chatClear").addEventListener("click", () => {
    const empty = el("p", "empty", "Ask for a tutor, a status update, or a cancellation to begin.");
    empty.id = "chatEmpty";
    $("chatLog").replaceChildren(empty);
  });
  document.querySelectorAll(".example").forEach((b) =>
    b.addEventListener("click", () => { $("chatInput").value = b.textContent; $("chatInput").focus(); }));
});