// Opens and closes the menu on small screens.
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("navToggle");
  const nav = document.getElementById("siteNav");

  const dashboardWelcome = document.querySelector(".dashboard-welcome-area");
  if (dashboardWelcome) {
    const quickLinks = dashboardWelcome.querySelector(".dashboard-quick-links");
    const panel = dashboardWelcome.querySelector(".quick-links-panel");
    if (quickLinks && panel) {
      const updateQuickLinks = () => {
        const isOpen = quickLinks.open;
        dashboardWelcome.classList.toggle("quick-links-expanded", isOpen);
        panel.setAttribute("aria-hidden", String(!isOpen));
        panel.inert = !isOpen;
      };
      updateQuickLinks();
      quickLinks.addEventListener("toggle", updateQuickLinks);
    }
  }

  if (!toggle || !nav) return;

  toggle.addEventListener("click", () => {
    const isOpen = nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(isOpen));
  });
});