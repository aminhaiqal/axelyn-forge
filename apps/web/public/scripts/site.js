const form = document.querySelector("#service-request-form");
const formStatus = document.querySelector("#form-status");
const serviceSelect = form?.elements.namedItem("service_id");
const apiBase = (form?.dataset.apiBase || "").replace(/\/$/, "");

document.querySelectorAll("[data-select-service]").forEach((button) => {
  button.addEventListener("click", () => {
    if (serviceSelect instanceof HTMLSelectElement) {
      serviceSelect.value = button.dataset.selectService || "";
    }
    document.querySelector("#request")?.scrollIntoView({ behavior: "smooth" });
    window.setTimeout(() => serviceSelect?.focus(), 500);
  });
});

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!formStatus) return;

  const button = form.querySelector("button[type='submit']");
  const data = new FormData(form);
  const payload = {
    service_id: data.get("service_id"),
    full_name: data.get("full_name"),
    email: data.get("email"),
    company: data.get("company") || null,
    project_summary: data.get("project_summary"),
    job_posting_url: data.get("job_posting_url") || null,
    timeline: data.get("timeline") || null,
    consent: data.get("consent") === "on",
  };

  formStatus.dataset.state = "pending";
  formStatus.textContent = "Sending your brief…";
  if (button instanceof HTMLButtonElement) button.disabled = true;

  try {
    const response = await fetch(`${apiBase}/api/v1/service-requests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof result?.detail === "string"
        ? result.detail
        : "Check the form and try again.";
      throw new Error(detail);
    }
    form.reset();
    formStatus.dataset.state = "success";
    formStatus.textContent = `${result.message} Reference: ${result.id}`;
  } catch (error) {
    formStatus.dataset.state = "error";
    formStatus.textContent = error instanceof Error
      ? error.message
      : "The request could not be sent. Try again.";
  } finally {
    if (button instanceof HTMLButtonElement) button.disabled = false;
  }
});
