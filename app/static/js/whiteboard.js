// The shared whiteboard. Drawing goes to the other person through the room's socket. The server
// keeps the board while the room is open, so someone who joins late sees it too.
// Everything is drawn on a canvas, so no HTML from the other person is ever inserted.
document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("wbCanvas");
  const socket = window.roomSocket;
  if (!canvas || !socket) return;

  const $ = (id) => document.getElementById(id);
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const MAX_STROKE_POINTS = 3000;                      // same limit as the server
  let role = "", tool = "pen", ops = [], byId = new Map();
  let current = null, pending = [], timer = null, counter = 0;

  const say = (text) => { $("wbNote").textContent = text; };
  const clamp = (v) => Math.min(1, Math.max(0, Math.round(v * 10000) / 10000));
  const newId = () => {
    counter += 1;                                      // ids start with s (student) or t (tutor)
    return role[0] + Date.now().toString(36) + counter.toString(36) + Math.random().toString(36).slice(2, 6);
  };

  // ---------- drawing ----------
  function drawStroke(op, from) {
    const pts = op.points;
    if (!pts.length) return;
    ctx.strokeStyle = op.color;
    ctx.fillStyle = op.color;
    ctx.lineWidth = op.size;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const start = Math.max(0, (from || 0) - 1);        // overlap one point so pieces join up
    if (pts.length - start < 2) {                      // a single click makes a dot
      const p = pts[pts.length - 1];
      ctx.beginPath();
      ctx.arc(p[0] * W, p[1] * H, op.size / 2, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    ctx.beginPath();
    ctx.moveTo(pts[start][0] * W, pts[start][1] * H);
    for (let i = start + 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * W, pts[i][1] * H);
    ctx.stroke();
  }
  function drawText(op) {
    ctx.fillStyle = op.color;
    ctx.font = op.size + "px sans-serif";
    ctx.textBaseline = "top";
    ctx.fillText(op.text, op.x * W, op.y * H);
  }
  function drawOp(op) { if (op.kind === "text") drawText(op); else drawStroke(op, 0); }
  function redraw() {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, H);
    ops.forEach(drawOp);
  }
  function addOp(op) {
    if (byId.has(op.id)) return;
    ops.push(op);
    byId.set(op.id, op);
    drawOp(op);
  }
  function applyChunk(chunk) {
    const existing = byId.get(chunk.id);
    if (!existing) { addOp(chunk); return; }
    if (existing.kind !== "stroke" || chunk.kind !== "stroke") return;
    const from = existing.points.length;
    chunk.points.forEach((p) => existing.points.push(p));
    drawStroke(existing, from);
  }
  function loadState(list) {
    ops = list.slice();
    byId = new Map(ops.map((o) => [o.id, o]));
    redraw();
  }

  // ---------- from the server ----------
  socket.on("joined", (info) => { role = info.role; });
  socket.on("wb_state", (s) => loadState(Array.isArray(s.ops) ? s.ops : []));
  socket.on("wb_draw", applyChunk);
  socket.on("wb_add", addOp);
  socket.on("wb_remove", (m) => {
    ops = ops.filter((o) => o.id !== m.id);
    byId.delete(m.id);
    redraw();
  });
  socket.on("wb_clear", () => loadState([]));

  // ---------- to the server ----------
  function sendPoints(op, points) {
    for (let i = 0; i < points.length; i += 100) {
      socket.emit("wb_draw", { id: op.id, kind: "stroke", tool: op.tool, color: op.color,
                               size: op.size, points: points.slice(i, i + 100) });
    }
  }
  function flushNow() {
    timer = null;
    if (current && pending.length) { sendPoints(current, pending); pending = []; }
  }
  function endStroke() {
    if (!current) return;
    clearTimeout(timer);
    timer = null;
    if (pending.length) sendPoints(current, pending);
    pending = [];
    current = null;
  }

  // ---------- pointer input (mouse, finger or stylus) ----------
  function position(e) {
    const r = canvas.getBoundingClientRect();
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
  }
  function placeText(p) {
    const text = $("wbTextInput").value.trim();
    if (!text) {
      say("Type the text in the box first, then click the board where it should go.");
      $("wbTextInput").focus();
      return;
    }
    const op = { id: newId(), kind: "text", x: p[0], y: p[1], text: text.slice(0, 200),
                 color: $("wbColor").value, size: 12 + Number($("wbSize").value) * 2 };
    addOp(op);
    socket.emit("wb_draw", op);
  }
  canvas.addEventListener("pointerdown", (e) => {
    if (!role) { say("Still connecting. Try again in a moment."); return; }
    if (e.button !== undefined && e.button !== 0) return;
    const p = position(e);
    if (tool === "text") { placeText(p); return; }
    e.preventDefault();
    canvas.setPointerCapture(e.pointerId);
    const size = tool === "eraser" ? Math.min(40, Number($("wbSize").value) * 2 + 6) : Number($("wbSize").value);
    current = { id: newId(), kind: "stroke", tool, size, points: [p],
                color: tool === "eraser" ? "#ffffff" : $("wbColor").value };
    ops.push(current);
    byId.set(current.id, current);
    drawStroke(current, 0);
    pending = [p];
    timer = setTimeout(flushNow, 60);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!current) return;
    const p = position(e);
    current.points.push(p);
    drawStroke(current, current.points.length - 1);
    pending.push(p);
    if (!timer) timer = setTimeout(flushNow, 60);
    if (current.points.length >= MAX_STROKE_POINTS) {
      endStroke();
      say("That stroke reached the longest length allowed. Lift your pen and continue.");
    }
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((name) => canvas.addEventListener(name, endStroke));

  // ---------- tools ----------
  const toolButtons = { pen: $("wbPen"), eraser: $("wbEraser"), text: $("wbText") };
  function setTool(name) {
    tool = name;
    Object.entries(toolButtons).forEach(([key, b]) => b.setAttribute("aria-pressed", String(key === name)));
    $("wbTextInput").hidden = name !== "text";
    canvas.classList.toggle("text-tool", name === "text");
    say(name === "text" ? "Type your text in the box, then click the board where it should go." : "");
  }
  Object.entries(toolButtons).forEach(([key, b]) => b.addEventListener("click", () => setTool(key)));
  $("wbUndo").addEventListener("click", () => socket.emit("wb_undo"));
  $("wbRedo").addEventListener("click", () => socket.emit("wb_redo"));
  $("wbClear").addEventListener("click", () => {
    if (window.confirm("Clear the whole board for both of you? This cannot be undone.")) socket.emit("wb_clear");
  });
  redraw();
});