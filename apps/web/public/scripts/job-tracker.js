const trackerPage = document.querySelector(".tracker-page");

if (trackerPage instanceof HTMLElement) {
  const apiBase = (trackerPage.dataset.apiBase || "").replace(/\/$/, "");
  const form = document.querySelector("#application-form");
  const formStatus = document.querySelector("#application-form-status");
  const submitButton = document.querySelector("#save-application");
  const cancelButton = document.querySelector("#cancel-edit");
  const editorTitle = document.querySelector("#editor-title");
  const editorSequence = document.querySelector("#editor-sequence");
  const resumeSelect = document.querySelector("#resume-attachment");
  const resumeHelp = document.querySelector("#resume-help");
  const list = document.querySelector("#application-list");
  const count = document.querySelector("#application-count");
  const search = document.querySelector("#application-search");
  const statusFilter = document.querySelector("#status-filter");
  const statusInput = document.querySelector("#application-status");
  const appliedInput = document.querySelector("#applied-on");
  let applications = [];
  let sources = [];
  let variants = [];

  const api = async (path, options = {}) => {
    const request = { credentials: "same-origin", ...options };
    if (request.body && typeof request.body === "string") {
      request.headers = { "Content-Type": "application/json", ...(request.headers || {}) };
    }
    const response = await fetch(`${apiBase}${path}`, request);
    if (response.status === 401) {
      window.location.assign(`/sign-in?redirect_url=${encodeURIComponent(window.location.pathname)}`);
      throw new Error("Your session has expired.");
    }
    if (response.status === 204) return null;
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = Array.isArray(result?.detail) ? result.detail[0]?.msg : result?.detail;
      throw new Error(typeof detail === "string" ? detail.replace(/^Value error, /, "") : "Forge could not complete that request.");
    }
    return result;
  };

  const setFormStatus = (message, state = "") => {
    if (!(formStatus instanceof HTMLElement)) return;
    formStatus.textContent = message;
    if (state) formStatus.dataset.state = state;
    else formStatus.removeAttribute("data-state");
  };

  const titleCase = (value) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const dateLabel = (value) => {
    if (!value) return "";
    return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" })
      .format(new Date(`${value}T00:00:00`));
  };

  const textElement = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  };

  const input = (id) => document.querySelector(`#${id}`);
  const setInputValue = (id, value) => {
    const element = input(id);
    if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) {
      element.value = value || "";
    }
  };

  const updateMetrics = () => {
    const active = new Set(["applied", "screening", "interview"]);
    const values = {
      "metric-total": applications.length,
      "metric-active": applications.filter((item) => active.has(item.status)).length,
      "metric-interviews": applications.filter((item) => item.status === "interview").length,
      "metric-offers": applications.filter((item) => item.status === "offer").length,
    };
    Object.entries(values).forEach(([id, value]) => {
      const element = document.querySelector(`#${id}`);
      if (element) element.textContent = String(value).padStart(2, "0");
    });
    if (count) count.textContent = `${applications.length} record${applications.length === 1 ? "" : "s"}`;
  };

  const fillResumeOptions = (selectedApplication = null) => {
    if (!(resumeSelect instanceof HTMLSelectElement)) return;
    resumeSelect.replaceChildren();
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = sources.length ? "Choose the resume sent for this role" : "Create or import a resume first";
    resumeSelect.append(prompt);

    if (variants.length) {
      const group = document.createElement("optgroup");
      group.label = "Approved resume versions";
      variants.forEach((variant) => {
        const option = document.createElement("option");
        option.value = `variant:${variant.id}`;
        option.dataset.sourceId = variant.source_id;
        option.dataset.variantId = variant.id;
        option.textContent = `${variant.name}${variant.target_role ? ` — ${variant.target_role}` : ""}`;
        group.append(option);
      });
      resumeSelect.append(group);
    }

    const versionSourceIds = new Set(variants.map((variant) => variant.source_id));
    const draftSources = sources.filter((source) => !versionSourceIds.has(source.id));
    if (draftSources.length) {
      const group = document.createElement("optgroup");
      group.label = "Resume sources";
      draftSources.forEach((source) => {
        const option = document.createElement("option");
        option.value = `source:${source.id}`;
        option.dataset.sourceId = source.id;
        option.textContent = `${source.display_name}${source.target_role ? ` — ${source.target_role}` : ""}${source.status === "needs_ocr" ? " (needs content)" : " (source)"}`;
        option.disabled = source.status === "needs_ocr";
        group.append(option);
      });
      resumeSelect.append(group);
    }

    if (selectedApplication) {
      const selectedValue = selectedApplication.resume_variant_id
        ? `variant:${selectedApplication.resume_variant_id}`
        : selectedApplication.resume_source_id
          ? `source:${selectedApplication.resume_source_id}`
          : "";
      if (selectedValue && Array.from(resumeSelect.options).some((option) => option.value === selectedValue)) {
        resumeSelect.value = selectedValue;
      } else if (!selectedApplication.resume_source_id) {
        const archived = document.createElement("option");
        archived.value = "archived";
        archived.textContent = `${selectedApplication.resume_name} (saved attachment)`;
        archived.selected = true;
        resumeSelect.append(archived);
      }
    }

    if (resumeHelp instanceof HTMLElement) {
      resumeHelp.replaceChildren();
      if (sources.length) {
        resumeHelp.textContent = "Forge records the selected version with this application.";
      } else {
        resumeHelp.append("You need a resume before tracking an application. ");
        const link = document.createElement("a");
        link.href = "/app/resume";
        link.textContent = "Create your first resume";
        resumeHelp.append(link, ".");
      }
    }
  };

  const applicationPayload = (item, status = item.status) => ({
    company_name: item.company_name,
    job_title: item.job_title,
    job_url: item.job_url,
    location: item.location,
    work_arrangement: item.work_arrangement,
    employment_type: item.employment_type,
    status,
    applied_on: item.applied_on,
    next_action_on: item.next_action_on,
    notes: item.notes,
    resume_source_id: item.resume_source_id,
    resume_variant_id: item.resume_variant_id,
  });

  const editApplication = (item) => {
    setInputValue("application-id", item.id);
    setInputValue("company-name", item.company_name);
    setInputValue("job-title", item.job_title);
    setInputValue("job-url", item.job_url);
    setInputValue("job-location", item.location);
    setInputValue("work-arrangement", item.work_arrangement);
    setInputValue("employment-type", item.employment_type);
    setInputValue("application-status", item.status);
    setInputValue("applied-on", item.applied_on);
    setInputValue("next-action-on", item.next_action_on);
    setInputValue("application-notes", item.notes);
    fillResumeOptions(item);
    if (editorTitle) editorTitle.textContent = "Edit application";
    if (editorSequence) editorSequence.textContent = "01 / EDIT RECORD";
    if (submitButton) submitButton.firstChild.textContent = "Update application ";
    if (cancelButton instanceof HTMLButtonElement) cancelButton.hidden = false;
    setFormStatus(`Editing ${item.job_title} at ${item.company_name}.`);
    document.querySelector("#application-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const resetForm = () => {
    if (form instanceof HTMLFormElement) form.reset();
    setInputValue("application-id", "");
    fillResumeOptions();
    if (editorTitle) editorTitle.textContent = "Add an application";
    if (editorSequence) editorSequence.textContent = "01 / NEW RECORD";
    if (submitButton) submitButton.firstChild.textContent = "Save application ";
    if (cancelButton instanceof HTMLButtonElement) cancelButton.hidden = true;
    setFormStatus("");
  };

  const changeStatus = async (item, nextStatus, select) => {
    if (select instanceof HTMLSelectElement) select.disabled = true;
    try {
      const payload = applicationPayload(item, nextStatus);
      if (!payload.applied_on && nextStatus !== "saved") {
        payload.applied_on = new Date().toISOString().slice(0, 10);
      }
      const updated = await api(`/api/v1/job-applications/${encodeURIComponent(item.id)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      applications = applications.map((candidate) => candidate.id === updated.id ? updated : candidate);
      renderApplications();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "The status could not be updated.");
      if (select instanceof HTMLSelectElement) select.value = item.status;
    } finally {
      if (select instanceof HTMLSelectElement) select.disabled = false;
    }
  };

  const removeApplication = async (item, button) => {
    if (!window.confirm(`Delete the ${item.job_title} application at ${item.company_name}?`)) return;
    if (button instanceof HTMLButtonElement) button.disabled = true;
    try {
      await api(`/api/v1/job-applications/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      applications = applications.filter((candidate) => candidate.id !== item.id);
      if (input("application-id")?.value === item.id) resetForm();
      renderApplications();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "The application could not be deleted.");
      if (button instanceof HTMLButtonElement) button.disabled = false;
    }
  };

  const createApplicationCard = (item) => {
    const card = document.createElement("article");
    card.className = "application-card";

    const main = document.createElement("div");
    main.className = "application-card-main";
    const top = document.createElement("div");
    top.className = "application-card-top";
    const heading = document.createElement("h3");
    heading.append(document.createTextNode(item.job_title), textElement("span", "", item.company_name));
    const badge = textElement("span", "status-mark", titleCase(item.status));
    badge.dataset.status = item.status;
    top.append(heading, badge);

    const meta = document.createElement("ul");
    meta.className = "application-meta";
    [
      item.location,
      item.work_arrangement,
      item.employment_type,
      item.applied_on ? `Applied ${dateLabel(item.applied_on)}` : "Not applied yet",
      item.next_action_on ? `Next ${dateLabel(item.next_action_on)}` : "No follow-up date",
    ].filter(Boolean).forEach((value) => meta.append(textElement("li", "", value)));

    const attachment = document.createElement("div");
    attachment.className = "resume-attachment";
    attachment.append(textElement("span", "attachment-icon", "DOC"));
    const attachmentCopy = document.createElement("span");
    const attachmentName = textElement("strong", "", item.resume_name);
    attachmentCopy.append(attachmentName, document.createTextNode(item.resume_target_role ? `Attached resume · ${item.resume_target_role}` : "Attached resume"));
    attachment.append(attachmentCopy);
    main.append(top, meta, attachment);
    if (item.notes) main.append(textElement("p", "application-notes", item.notes));

    const actions = document.createElement("div");
    actions.className = "application-card-actions";
    const statusLabel = document.createElement("label");
    statusLabel.append(document.createTextNode("Move to"));
    const statusSelect = document.createElement("select");
    ["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"].forEach((status) => {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = titleCase(status);
      option.selected = status === item.status;
      statusSelect.append(option);
    });
    statusSelect.setAttribute("aria-label", `Change status for ${item.job_title} at ${item.company_name}`);
    statusSelect.addEventListener("change", () => changeStatus(item, statusSelect.value, statusSelect));
    statusLabel.append(statusSelect);

    const buttons = document.createElement("div");
    buttons.className = "record-actions";
    const edit = textElement("button", "", "Edit");
    edit.type = "button";
    edit.addEventListener("click", () => editApplication(item));
    buttons.append(edit);
    if (item.job_url) {
      const link = textElement("a", "", "Posting ↗");
      link.href = item.job_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      buttons.append(link);
    }
    const remove = textElement("button", "delete-application", "Delete");
    remove.type = "button";
    remove.addEventListener("click", () => removeApplication(item, remove));
    buttons.append(remove);
    actions.append(statusLabel, buttons);
    card.append(main, actions);
    return card;
  };

  function renderApplications() {
    if (!(list instanceof HTMLElement)) return;
    const query = search instanceof HTMLInputElement ? search.value.trim().toLocaleLowerCase() : "";
    const filter = statusFilter instanceof HTMLSelectElement ? statusFilter.value : "all";
    const visible = applications.filter((item) => {
      const matchesStatus = filter === "all" || item.status === filter;
      const haystack = `${item.company_name} ${item.job_title} ${item.resume_name} ${item.location || ""}`.toLocaleLowerCase();
      return matchesStatus && (!query || haystack.includes(query));
    });
    list.replaceChildren();
    updateMetrics();
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "tracker-empty";
      if (applications.length) {
        empty.append(textElement("strong", "", "No records match this view."), document.createTextNode("Try another search or status filter."));
      } else if (sources.length) {
        empty.append(textElement("strong", "", "No applications yet."), document.createTextNode("Add the first role you want to follow."));
      } else {
        empty.append(textElement("strong", "", "Start with your resume."), document.createTextNode("Create or import a resume, then return here to attach it to an application. "));
        const link = textElement("a", "", "Open resume builder");
        link.href = "/app/resume";
        empty.append(link);
      }
      list.append(empty);
      return;
    }
    visible.forEach((item) => list.append(createApplicationCard(item)));
  }

  if (cancelButton instanceof HTMLButtonElement) cancelButton.addEventListener("click", resetForm);
  if (search instanceof HTMLInputElement) search.addEventListener("input", renderApplications);
  if (statusFilter instanceof HTMLSelectElement) statusFilter.addEventListener("change", renderApplications);
  if (statusInput instanceof HTMLSelectElement && appliedInput instanceof HTMLInputElement) {
    statusInput.addEventListener("change", () => {
      if (!appliedInput.value && statusInput.value !== "saved") appliedInput.value = new Date().toISOString().slice(0, 10);
    });
  }

  if (form instanceof HTMLFormElement) form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!(resumeSelect instanceof HTMLSelectElement)) return;
    const editingId = input("application-id")?.value || "";
    const option = resumeSelect.selectedOptions[0];
    if (!editingId && !option?.dataset.sourceId) {
      setFormStatus("Choose the resume attached to this application.", "error");
      resumeSelect.focus();
      return;
    }
    const values = new FormData(form);
    const payload = {
      company_name: String(values.get("company_name") || ""),
      job_title: String(values.get("job_title") || ""),
      job_url: String(values.get("job_url") || "") || null,
      location: String(values.get("location") || "") || null,
      work_arrangement: String(values.get("work_arrangement") || "") || null,
      employment_type: String(values.get("employment_type") || "") || null,
      status: String(values.get("status") || "saved"),
      applied_on: String(values.get("applied_on") || "") || null,
      next_action_on: String(values.get("next_action_on") || "") || null,
      notes: String(values.get("notes") || "") || null,
      resume_source_id: option?.dataset.sourceId || null,
      resume_variant_id: option?.dataset.variantId || null,
    };
    if (submitButton instanceof HTMLButtonElement) submitButton.disabled = true;
    setFormStatus(editingId ? "Updating your application…" : "Saving your application…", "pending");
    try {
      const saved = await api(
        editingId ? `/api/v1/job-applications/${encodeURIComponent(editingId)}` : "/api/v1/job-applications",
        { method: editingId ? "PUT" : "POST", body: JSON.stringify(payload) },
      );
      applications = editingId
        ? applications.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...applications];
      resetForm();
      renderApplications();
      setFormStatus(editingId ? "Application updated." : "Application saved.", "success");
    } catch (error) {
      setFormStatus(error instanceof Error ? error.message : "The application could not be saved.", "error");
    } finally {
      if (submitButton instanceof HTMLButtonElement) submitButton.disabled = false;
    }
  });

  Promise.all([
    api("/api/v1/resumes"),
    api("/api/v1/resume-variants"),
    api("/api/v1/job-applications"),
  ]).then(([loadedSources, loadedVariants, loadedApplications]) => {
    sources = loadedSources;
    variants = loadedVariants;
    applications = loadedApplications;
    fillResumeOptions();
    renderApplications();
  }).catch((error) => {
    if (list) list.textContent = error instanceof Error ? error.message : "The tracker could not be loaded.";
    setFormStatus("The tracker could not be loaded. Refresh the page and try again.", "error");
  });
}
