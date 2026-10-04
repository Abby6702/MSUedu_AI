// Switches between the Whiteboard and Files tabs (from the tabs or the control buttons).
document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);
  const panels = { board: [$("tabBoard"), $("panelBoard")], files: [$("tabFiles"), $("panelFiles")] };
  if (!panels.board[0] || !panels.files[0]) return;

  function show(name, scroll) {
    Object.entries(panels).forEach(([key, [tab, panel]]) => {
      const active = key === name;
      panel.hidden = !active;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    if (scroll) panels[name][1].scrollIntoView({ behavior: "smooth", block: "start" });
  }
  panels.board[0].addEventListener("click", () => show("board"));
  panels.files[0].addEventListener("click", () => show("files"));
  if ($("btnBoard")) $("btnBoard").addEventListener("click", () => show("board", true));
  if ($("btnFiles")) $("btnFiles").addEventListener("click", () => show("files", true));
});