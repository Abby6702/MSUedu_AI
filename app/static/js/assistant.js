// Talks to OUR Flask server only. Everything shown is built safely with
// createElement and textContent, so AI or user text can never run as code.
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("assistant");
  if (!root) return;

  const csrf = root.dataset.csrf;
  const base = root.dataset.convUrl;               // /student/assistant/conversations
  const $ = (id) => document.getElementById(id);
  const state = { id: null, busy: false, lastAi: null, regen: null };
  const EMPTY_TEXT = "Ask anything about your studies to begin.";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function clearNode(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  // ---------- talking to the server ----------
  async function api(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 150000);
    try {
      const res = await fetch(url, Object.assign(
        { credentials: "same-origin", signal: controller.signal }, options || {}));
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
  const post = (url, payload) => api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    body: JSON.stringify(payload || {}),
  });

  // ---------- a small, safe Markdown renderer ----------
  const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/;
  function addInline(parent, text) {
    text.split(INLINE).forEach((part) => {
      if (!part) return;
      if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
        parent.appendChild(el("code", null, part.slice(1, -1)));
      } else if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
        parent.appendChild(el("strong", null, part.slice(2, -2)));
      } else {
        parent.appendChild(document.createTextNode(part));
      }
    });
  }
  function codeBlock(lines) {
    const code = lines.join("\n");
    const box = el("div", "code-block");
    const bar = el("div", "code-bar");
    const copy = el("button", "btn btn-small btn-outline", "Copy code");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(code); copy.textContent = "Copied"; }
      catch (_) { copy.textContent = "Copy failed"; }
      setTimeout(() => { copy.textContent = "Copy code"; }, 1500);
    });
    bar.appendChild(copy);
    const pre = el("pre");
    pre.appendChild(el("code", null, code));
    box.append(bar, pre);
    return box;
  }
  function renderMarkdown(text) {
    const out = el("div", "md");
    let para = [], list = null, fence = null;
    const flushPara = () => {
      if (!para.length) return;
      const p = el("p");
      addInline(p, para.join(" "));
      out.appendChild(p);
      para = [];
    };
    for (const line of text.replace(/\r/g, "").split("\n")) {
      if (fence !== null) {
        if (line.trim().startsWith("```")) { out.appendChild(codeBlock(fence)); fence = null; }
        else fence.push(line);
        continue;
      }
      if (line.trim().startsWith("```")) { flushPara(); list = null; fence = []; continue; }
      const item = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
      if (item) {
        flushPara();
        const ordered = /\d/.test(item[1]);
        if (!list || list.ordered !== ordered) {
          list = { ordered, node: el(ordered ? "ol" : "ul") };
          out.appendChild(list.node);
        }
        const li = el("li");
        addInline(li, item[2]);
        list.node.appendChild(li);
        continue;
      }
      list = null;
      const head = line.match(/^#{1,4}\s+(.*)$/);
      if (head) { flushPara(); const h = el("h4"); addInline(h, head[1]); out.appendChild(h); continue; }
      if (!line.trim()) { flushPara(); continue; }
      para.push(line.trim());
    }
    if (fence !== null) out.appendChild(codeBlock(fence));   // an answer that was cut off mid-code
    flushPara();
    return out;
  }

  // ---------- the chat window ----------
  function resetLog() {
    clearNode($("chatLog"));
    $("chatLog").appendChild(el("p", "empty", EMPTY_TEXT)).id = "chatEmpty";
    state.lastAi = null;
    state.regen = null;
  }
  function addMessage(role, text) {
    const empty = $("chatEmpty");
    if (empty) empty.remove();
    const box = el("div", "msg msg-" + role);
    if (role === "ai") {
      box.classList.add("rendered");
      box.appendChild(el("p", "ai-label", "AI tutor (AI-generated, may contain mistakes)"));
      box.appendChild(renderMarkdown(text));
      if (state.regen) state.regen.remove();
      state.regen = el("button", "btn btn-small btn-outline", "Regenerate");
      state.regen.type = "button";
      state.regen.addEventListener("click", regenerate);
      box.appendChild(state.regen);
      state.lastAi = box;
    } else {
      box.textContent = text;
    }
    $("chatLog").appendChild(box);
    $("chatLog").scrollTop = $("chatLog").scrollHeight;
    return box;
  }
  function setBusy(busy) {
    state.busy = busy;
    ["chatSend", "chatClear", "newChat"].forEach((id) => { $(id).disabled = busy; });
    if (state.regen) state.regen.disabled = busy;
    $("chatBusy").hidden = !busy;
  }
  function thinking() {
    const box = el("div", "msg msg-ai thinking", "AI tutor is thinking…");
    $("chatLog").appendChild(box);
    $("chatLog").scrollTop = $("chatLog").scrollHeight;
    return box;
  }

  // ---------- context (subject and lesson) ----------
  function lockContext(conv) {
    $("chatSubject").value = conv.subject_id ? String(conv.subject_id) : "";
    $("chatLesson").value = conv.lesson_id ? String(conv.lesson_id) : "";
    $("chatSubject").disabled = $("chatLesson").disabled = true;
    $("contextNote").textContent = "Context for this conversation: " +
      (conv.lesson_title || conv.subject_name || "none") + ". Start a new conversation to change it.";
  }
  function unlockContext() {
    $("chatSubject").disabled = $("chatLesson").disabled = false;
    $("contextNote").textContent = "Context is chosen before the first message. A lesson also sets the subject.";
  }
  $("chatLesson").addEventListener("change", () => {
    const option = $("chatLesson").selectedOptions[0];
    if (option && option.dataset.subject) $("chatSubject").value = option.dataset.subject;
  });

  // ---------- the conversation list ----------
  async function refreshList() {
    const list = $("convList");
    try {
      const data = await api(base);
      clearNode(list);
      if (!data.conversations.length) list.appendChild(el("p", "empty", "No saved conversations yet."));
      data.conversations.forEach((c) => {
        const row = el("div", "conv-item");
        const open = el("button", "conv-open" + (c.id === state.id ? " active" : ""));
        open.type = "button";
        open.appendChild(el("span", "conv-title", c.title));
        open.appendChild(el("span", "meta", (c.context ? c.context + " · " : "") + c.updated));
        open.addEventListener("click", () => openConversation(c.id));
        const del = el("button", "btn btn-small btn-danger", "Delete");
        del.type = "button";
        del.setAttribute("aria-label", "Delete conversation " + c.title);
        del.addEventListener("click", () => removeConversation(c.id));
        row.append(open, del);
        list.appendChild(row);
      });
    } catch (err) {
      clearNode(list);
      list.appendChild(el("p", "empty", "Could not load your conversations."));
    }
  }
  async function openConversation(id) {
    if (state.busy) return;
    try {
      const data = await api(`${base}/${id}`);
      state.id = id;
      resetLog();
      lockContext(data.conversation);
      data.messages.forEach((m) => addMessage(m.role === "assistant" ? "ai" : "user", m.content));
      refreshList();
    } catch (err) {
      addMessage("error", err.message);
    }
  }
  async function removeConversation(id) {
    if (state.busy || !window.confirm("Delete this conversation? This cannot be undone.")) return;
    try {
      await post(`${base}/${id}/delete`);
      if (state.id === id) startNew();
      refreshList();
    } catch (err) {
      addMessage("error", err.message);
    }
  }
  function startNew() {
    state.id = null;
    resetLog();
    unlockContext();
    refreshList();
  }
  $("newChat").addEventListener("click", () => { if (!state.busy) startNew(); });

  // ---------- sending, regenerating, clearing ----------
  async function sendChat() {
    const input = $("chatInput");
    const message = input.value.trim();
    if (!message || state.busy) return;
    setBusy(true);
    let userBox = null, indicator = null;
    try {
      if (!state.id) {
        const created = await post(base, {
          subject_id: $("chatSubject").value, lesson_id: $("chatLesson").value });
        state.id = created.conversation.id;
        lockContext(created.conversation);
      }
      userBox = addMessage("user", message);
      input.value = "";
      indicator = thinking();
      const data = await post(`${base}/${state.id}/messages`, { message });
      indicator.remove();
      addMessage("ai", data.reply);
      refreshList();
    } catch (err) {
      if (indicator) indicator.remove();
      if (userBox) userBox.remove();          // it was not saved, so put it back in the box
      input.value = message;
      addMessage("error", err.message);
    } finally {
      setBusy(false);
      input.focus();
    }
  }
  async function regenerate() {
    if (state.busy || !state.id || !state.lastAi) return;
    setBusy(true);
    const indicator = thinking();
    try {
      const data = await post(`${base}/${state.id}/regenerate`);
      indicator.remove();
      state.lastAi.remove();
      addMessage("ai", data.reply);
    } catch (err) {
      indicator.remove();
      addMessage("error", err.message);
    } finally {
      setBusy(false);
    }
  }
  $("chatSend").addEventListener("click", sendChat);
  $("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  $("chatClear").addEventListener("click", async () => {
    if (state.busy) return;
    if (!state.id) { resetLog(); return; }
    if (!window.confirm("Clear all messages in this conversation?")) return;
    try {
      await post(`${base}/${state.id}/clear`);
      resetLog();
      refreshList();
    } catch (err) {
      addMessage("error", err.message);
    }
  });

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

  // ---------- notes summary ----------
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
      const data = await post(root.dataset.summarizeUrl, { notes, length: $("summaryLength").value });
      $("summaryOut").textContent = data.reply;
      $("summaryOut").hidden = false;
    } catch (err) {
      $("summaryError").textContent = err.message;
      $("summaryError").hidden = false;
    } finally {
      $("summarySend").disabled = false;
      $("summaryBusy").hidden = true;
    }
  });

  // ---------- service status banner ----------
  fetch(root.dataset.statusUrl, { credentials: "same-origin" })
    .then((r) => r.json())
    .then((s) => {
      if (!s.running || !s.model_ready) {
        $("aiBanner").textContent = "The AI service is not ready right now. " +
          "If you are the developer, check the AI settings in .env (and that Ollama is running, if you use it).";
        $("aiBanner").hidden = false;
      }
    })
    .catch(() => { /* the banner is only a convenience */ });

  refreshList();
});