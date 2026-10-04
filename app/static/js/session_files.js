// Shared files. Names and details are inserted as text.
document.addEventListener("DOMContentLoaded", () => {
  const room = document.getElementById("room");
  const list = document.getElementById("fileList");
  const socket = window.roomSocket;
  if (!room || !list || !socket) return;

  const $ = (id) => document.getElementById(id);
  const url = room.dataset.filesUrl;
  const csrf = room.dataset.csrf;
  const ALLOWED = [".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt"];
  const MAX_BYTES = 5 * 1024 * 1024;
  let role = "", items = [];

  const say = (text) => { $("fileNote").textContent = text; };
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const safeUrl = (u) => typeof u === "string" && u.startsWith("/sessions/");

  function render() {
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!items.length) { list.appendChild(el("p", "empty", "No files shared yet.")); return; }
    items.forEach((f) => {
      const row = el("div", "file-row");
      row.appendChild(el("span", "file-name", f.name));
      row.appendChild(el("span", "meta", f.size + " · " + f.uploader + " · " + f.at));
      if (safeUrl(f.url)) {
        const link = el("a", "btn btn-small btn-outline", "Download");
        link.href = f.url;
        row.appendChild(link);
      }
      if (f.role === role) {
        const del = el("button", "btn btn-small btn-danger", "Remove");
        del.type = "button";
        del.setAttribute("aria-label", "Remove " + f.name);
        del.addEventListener("click", () => remove(f));
        row.appendChild(del);
      }
      list.appendChild(row);
    });
  }
  function addItem(f) {
    if (!items.some((x) => x.id === f.id)) items.push(f);
    render();
  }

  async function readJson(res) {
    if (res.status === 413) throw new Error("That file is too large. The limit is 5 MB.");
    let data = null;
    try { data = await res.json(); } catch (_) { /* not JSON */ }
    if (!res.ok || !data || !data.ok) throw new Error((data && data.error) || "Something went wrong. Please try again.");
    return data;
  }
  async function refresh() {
    try {
      const data = await readJson(await fetch(url, { credentials: "same-origin" }));
      items = data.files;
      render();
    } catch (err) {
      say(err.message);
    }
  }
  async function remove(f) {
    if (!window.confirm("Remove " + f.name + " for both of you?")) return;
    try {
      await readJson(await fetch(f.url + "/delete", {
        method: "POST", headers: { "X-CSRFToken": csrf }, credentials: "same-origin" }));
      items = items.filter((x) => x.id !== f.id);
      render();
      say("File removed.");
    } catch (err) {
      say(err.message);
    }
  }
  async function upload() {
    const input = $("fileInput");
    const file = input.files && input.files[0];
    if (!file) { say("Choose a file first."); return; }
    const ext = (file.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
    if (!ALLOWED.includes(ext)) { say("This file type is not allowed. Use PDF, DOCX, PPTX, JPG, PNG, WebP, GIF or TXT."); return; }
    if (file.size > MAX_BYTES) { say("That file is too large. The limit is 5 MB."); return; }
    const body = new FormData();
    body.append("file", file);
    $("fileSend").disabled = true;
    say("Uploading…");
    try {
      const data = await readJson(await fetch(url, {
        method: "POST", headers: { "X-CSRFToken": csrf }, body, credentials: "same-origin" }));
      addItem(data.file);
      input.value = "";
      say("File shared.");
    } catch (err) {
      say(err.message);
    } finally {
      $("fileSend").disabled = false;
    }
  }

  socket.on("joined", (info) => { role = info.role; refresh(); });
  socket.on("file_added", (m) => addItem(m.file));
  socket.on("file_removed", (m) => { items = items.filter((x) => x.id !== m.id); render(); });
  $("fileSend").addEventListener("click", upload);
});