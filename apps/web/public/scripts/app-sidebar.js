const workspaceShell = document.querySelector("[data-workspace-shell]");
const workspaceSidebarToggle = document.querySelector("#workspace-sidebar-toggle");

if (workspaceShell instanceof HTMLElement && workspaceSidebarToggle instanceof HTMLButtonElement) {
  const setSidebarState = (collapsed) => {
    workspaceShell.dataset.sidebarCollapsed = String(collapsed);
    workspaceSidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    workspaceSidebarToggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    workspaceSidebarToggle.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  };

  let savedState = false;
  try {
    savedState = window.localStorage.getItem("forge-sidebar-collapsed") === "true";
  } catch {
    savedState = false;
  }
  setSidebarState(savedState);

  workspaceSidebarToggle.addEventListener("click", () => {
    const collapsed = workspaceShell.dataset.sidebarCollapsed !== "true";
    setSidebarState(collapsed);
    try {
      window.localStorage.setItem("forge-sidebar-collapsed", String(collapsed));
    } catch {
      // The sidebar still works when browser storage is unavailable.
    }
  });
}
