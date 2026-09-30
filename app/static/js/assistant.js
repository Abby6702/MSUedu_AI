// Talks to OUR Flask server only (never to Ollama directly).
// AI text is always inserted with textContent, never innerHTML, so it cannot run code.
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("assistant");
  if (!root) return;

  const csrf = root.dataset.csrf;
  const $ = (id) => document.getElementById(id);
  const history = [];          // kept in this page's memory only

  // ---------- helper: POST JSON and return the parsed answer ----------
  async function postJson(url, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 150000);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(payload),
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
      if (err.name === "AbortError") {
        throw new Error("The request took too long. Please try again.");
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------- service status banner ----------
  fetch(root.dataset.statusUrl, { credentials: "same-origin" })
    .then((r) => r.json())
    .then((s) => {
      const banner = $("aiBanner");
      if (!s.running) {
        banner.textContent = "The AI service is not available right now. " +
          "If you are the developer, make sure Ollama is running.";
        banner.hidden = false;
      } else if (!s.model_ready) {
        banner.textContent = "The AI model is not installed yet. " +
          "If you are the developer, check OLLAMA_MODEL in .env against 'ollama list'.";
        banner.hidden = false;
      }
    })
    .catch(() => { /* the banner is only a convenience */ });

  // ---------- tabs ----------
  function showTab(name) {
    const chat = name === "chat";
    $("panelChat").hidden = !chat;
    $("panelSummary").hidden = chat;
    $("tabChat").classList.toggle("active", chat);
    $("tabSummary").classList.toggle("active", !chat);
    $("tabChat").setAttribute("aria-selected", String(chat));
    $("tabSummary").setAttribute("aria-selected", String(!chat));
  }
  $("tabChat").addEventListener("click", () => showTab("chat"));
  $("tabSummary").addEventListener("click", () => showTab("summary"));

  // ---------- chat ----------
  function addMessage(kind, text) {
    const empty = $("chatEmpty");
    if (empty) empty.remove();
    const box = document.createElement("div");
    box.className = "msg msg-" + kind;
    box.textContent = text;                       // safe: text only
    $("chatLog").appendChild(box);
    $("chatLog").scrollTop = $("chatLog").scrollHeight;
  }

  async function sendChat() {
    const input = $("chatInput");
    const message = input.value.trim();
    if (!message) return;

    addMessage("user", message);
    input.value = "";
    $("chatSend").disabled = true;
    $("chatBusy").hidden = false;

    try {
      const data = await postJson(root.dataset.chatUrl, {
        message,
        subject_id: $("chatSubject").value,
        topic: $("chatTopic").value,
        history: history.slice(-10),
      });
      addMessage("ai", data.reply);
      history.push({ role: "user", content: message });
      history.push({ role: "assistant", content: data.reply });
    } catch (err) {
      addMessage("error", err.message);
    } finally {
      $("chatSend").disabled = false;
      $("chatBusy").hidden = true;
      input.focus();
    }
  }

  $("chatSend").addEventListener("click", sendChat);
  $("chatClear").addEventListener("click", () => {
    history.length = 0;
    $("chatLog").innerHTML = '<p class="empty" id="chatEmpty">Ask anything about your studies to begin.</p>';
  });

  // ---------- summarize ----------
  $("summarySend").addEventListener("click", async () => {
    const notes = $("notesInput").value.trim();
    $("summaryError").hidden = true;
    $("summaryOut").hidden = true;
    if (notes.length < 50) {
      $("summaryError").textContent = "Paste at least a few sentences of notes (50 characters or more).";
      $("summaryError").hidden = false;
      return;
    }
    $("summarySend").disabled = true;
    $("summaryBusy").hidden = false;
    try {
      const data = await postJson(root.dataset.summarizeUrl, {
        notes,
        length: $("summaryLength").value,
      });
      $("summaryOut").textContent = data.reply;   // safe: text only
      $("summaryOut").hidden = false;
    } catch (err) {
      $("summaryError").textContent = err.message;
      $("summaryError").hidden = false;
    } finally {
      $("summarySend").disabled = false;
      $("summaryBusy").hidden = true;
    }
  });
});