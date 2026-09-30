const trackerPage = document.querySelector(".tracker-page");

if (trackerPage instanceof HTMLElement) {
  const apiBase = (trackerPage.dataset.apiBase || "").replace(/\/$/, "");
  const form = document.querySelector("#application-form");
  const formStatus = document.querySelector("#application-form-status");
  const submitButton = document.querySelector("#save-application");
  const cancelButton = document.querySelector("#cancel-edit");
  const openApplicationButton = document.querySelector("#open-application");
  const applicationDialog = document.querySelector("#application-dialog");
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
  const interviewDialog = document.querySelector("#interview-dialog");
  const interviewDialogContext = document.querySelector("#interview-dialog-context");
  const interviewOutput = document.querySelector("#interview-brief-output");
  const interviewStatus = document.querySelector("#interview-status");
  const interviewJobDescription = document.querySelector("#interview-job-description");
  const interviewFocus = document.querySelector("#interview-focus");
  const generateInterviewButton = document.querySelector("#generate-interview-brief");
  const closeInterviewButton = document.querySelector("#close-interview-dialog");
  let applications = [];
  let sources = [];
  let activeInterviewApplication = null;

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
      const error = new Error(typeof detail === "string" ? detail.replace(/^Value error, /, "") : "Forge could not complete that request.");
      error.status = response.status;
      throw error;
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
    prompt.textContent = sources.length ? "Choose the resume sent for this role" : "Import a resume first";
    resumeSelect.append(prompt);

    if (sources.length) {
      const group = document.createElement("optgroup");
      group.label = "Resume sources";
      sources.forEach((source) => {
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
      const selectedValue = selectedApplication.resume_source_id
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
        link.href = "/app";
        link.textContent = "Import your first resume";
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
    if (editorSequence) editorSequence.textContent = "EDIT APPLICATION";
    if (submitButton) submitButton.firstChild.textContent = "Update application ";
    setFormStatus(`Editing ${item.job_title} at ${item.company_name}.`);
    if (applicationDialog instanceof HTMLDialogElement && !applicationDialog.open) {
      applicationDialog.showModal();
    }
  };

  const resetForm = () => {
    if (form instanceof HTMLFormElement) form.reset();
    setInputValue("application-id", "");
    fillResumeOptions();
    if (editorTitle) editorTitle.textContent = "Add an application";
    if (editorSequence) editorSequence.textContent = "NEW APPLICATION";
    if (submitButton) submitButton.firstChild.textContent = "Save application ";
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

  const setInterviewStatus = (message, state = "") => {
    if (!(interviewStatus instanceof HTMLElement)) return;
    interviewStatus.textContent = message;
    if (state) interviewStatus.dataset.state = state;
    else interviewStatus.removeAttribute("data-state");
  };

  const evidenceList = (items) => {
    const evidence = document.createElement("div");
    evidence.className = "interview-evidence";
    (items || []).forEach((item) => evidence.append(textElement("span", "", item)));
    if (!evidence.childElementCount) {
      evidence.append(textElement("span", "is-gap", "No resume evidence — prepare an honest gap response"));
    }
    return evidence;
  };

  const briefSection = (sequence, title) => {
    const heading = document.createElement("header");
    heading.className = "brief-section-heading";
    heading.append(textElement("span", "", sequence), textElement("h3", "", title));
    return heading;
  };

  const simpleList = (items) => {
    const listElement = document.createElement("ol");
    items.forEach((item) => listElement.append(textElement("li", "", item)));
    return listElement;
  };

  const renderInterviewEmpty = () => {
    if (!(interviewOutput instanceof HTMLElement)) return;
    interviewOutput.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "interview-brief-empty";
    empty.append(
      textElement("span", "", "01 / READY"),
      textElement("strong", "", "Turn the application into a focused interview plan."),
      textElement("p", "", "Forge will surface likely questions, the evidence to use, honest gaps, and useful questions to ask the interviewer."),
    );
    interviewOutput.append(empty);
  };

  const renderInterviewBrief = (brief) => {
    if (!(interviewOutput instanceof HTMLElement)) return;
    interviewOutput.replaceChildren();

    const overview = document.createElement("section");
    overview.className = "brief-overview";
    overview.append(
      textElement("span", "brief-sequence", "01 / POSITIONING"),
      textElement("h3", "", brief.role_summary),
      textElement("p", "", brief.positioning),
    );

    const coverage = document.createElement("section");
    coverage.className = "brief-section";
    coverage.append(briefSection("02", "Role coverage"));
    const coverageGrid = document.createElement("div");
    coverageGrid.className = "coverage-grid";
    brief.coverage.forEach((item) => {
      const card = document.createElement("article");
      card.className = "coverage-item";
      const assessment = textElement("span", "coverage-assessment", titleCase(item.assessment));
      assessment.dataset.assessment = item.assessment;
      card.append(
        assessment,
        textElement("h4", "", item.requirement),
        textElement("p", "", item.rationale),
        evidenceList(item.evidence),
      );
      coverageGrid.append(card);
    });
    coverage.append(coverageGrid);

    const questions = document.createElement("section");
    questions.className = "brief-section";
    questions.append(briefSection("03", "Likely interview questions"));
    const questionList = document.createElement("div");
    questionList.className = "interview-question-list";
    brief.questions.forEach((item, index) => {
      const details = document.createElement("details");
      if (index === 0) details.open = true;
      const summary = document.createElement("summary");
      summary.append(
        textElement("span", "", String(index + 1).padStart(2, "0")),
        document.createTextNode(item.question),
      );
      const content = document.createElement("div");
      content.className = "question-content";
      const intent = document.createElement("p");
      intent.append(
        textElement("strong", "", "What they are testing"),
        document.createTextNode(item.interviewer_intent),
      );
      const plan = document.createElement("p");
      plan.append(
        textElement("strong", "", "Answer plan"),
        document.createTextNode(item.answer_plan),
      );
      content.append(intent, plan, evidenceList(item.evidence));
      details.append(summary, content);
      questionList.append(details);
    });
    questions.append(questionList);

    const actions = document.createElement("section");
    actions.className = "brief-section brief-final-grid";
    const ask = document.createElement("div");
    ask.append(briefSection("04", "Questions to ask"), simpleList(brief.questions_to_ask));
    const prepare = document.createElement("div");
    prepare.append(briefSection("05", "Before the interview"), simpleList(brief.preparation_actions));
    actions.append(ask, prepare);

    if (brief.facts_to_confirm?.length) {
      const confirm = document.createElement("div");
      confirm.className = "facts-to-confirm";
      confirm.append(briefSection("06", "Confirm in your own words"), simpleList(brief.facts_to_confirm));
      actions.append(confirm);
    }

    const generatedOn = brief.updated_at ? dateLabel(brief.updated_at.slice(0, 10)) : "now";
    const metadata = textElement("p", "brief-metadata", `Generated privately with ${brief.model} · ${generatedOn}`);
    interviewOutput.append(overview, coverage, questions, actions, metadata);
  };

  const openInterviewBrief = async (item) => {
    if (!(interviewDialog instanceof HTMLDialogElement)) return;
    activeInterviewApplication = item;
    if (interviewDialogContext) {
      interviewDialogContext.textContent = `${item.job_title} · ${item.company_name} · ${item.resume_name}`;
    }
    if (interviewJobDescription instanceof HTMLTextAreaElement) interviewJobDescription.value = "";
    if (interviewFocus instanceof HTMLInputElement) {
      interviewFocus.value = item.status === "interview" ? "Upcoming interview" : "";
    }
    renderInterviewEmpty();
    setInterviewStatus("Checking for a saved brief…", "pending");
    interviewDialog.showModal();
    try {
      const brief = await api(`/api/v1/job-applications/${encodeURIComponent(item.id)}/interview-brief`);
      if (activeInterviewApplication?.id !== item.id) return;
      renderInterviewBrief(brief);
      setInterviewStatus("Saved brief loaded.", "success");
    } catch (error) {
      if (activeInterviewApplication?.id !== item.id) return;
      if (error?.status === 404) setInterviewStatus("No brief yet. Add context and generate one.");
      else setInterviewStatus(error instanceof Error ? error.message : "The saved brief could not be loaded.", "error");
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
    const prepare = textElement("button", "ai-prep-action", "AI prep");
    prepare.type = "button";
    prepare.addEventListener("click", () => openInterviewBrief(item));
    buttons.append(prepare);
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
        empty.append(textElement("strong", "", "Start with your resume."), document.createTextNode("Import a resume, then return here to attach it to an application. "));
        const link = textElement("a", "", "Open resume library");
        link.href = "/app";
        empty.append(link);
      }
      list.append(empty);
      return;
    }
    visible.forEach((item) => list.append(createApplicationCard(item)));
  }

  if (closeInterviewButton instanceof HTMLButtonElement && interviewDialog instanceof HTMLDialogElement) {
    closeInterviewButton.addEventListener("click", () => interviewDialog.close());
    interviewDialog.addEventListener("click", (event) => {
      if (event.target === interviewDialog) interviewDialog.close();
    });
    interviewDialog.addEventListener("close", () => {
      activeInterviewApplication = null;
      setInterviewStatus("");
    });
  }
  if (generateInterviewButton instanceof HTMLButtonElement) {
    generateInterviewButton.addEventListener("click", async () => {
      if (!activeInterviewApplication) return;
      const applicationId = activeInterviewApplication.id;
      generateInterviewButton.disabled = true;
      setInterviewStatus("Building an evidence-grounded brief…", "pending");
      try {
        const brief = await api(
          `/api/v1/job-applications/${encodeURIComponent(applicationId)}/interview-brief`,
          {
            method: "POST",
            body: JSON.stringify({
              job_description: interviewJobDescription instanceof HTMLTextAreaElement
                ? interviewJobDescription.value
                : null,
              focus: interviewFocus instanceof HTMLInputElement ? interviewFocus.value : null,
            }),
          },
        );
        if (activeInterviewApplication?.id !== applicationId) return;
        renderInterviewBrief(brief);
        setInterviewStatus("Interview brief saved to this application.", "success");
      } catch (error) {
        if (activeInterviewApplication?.id !== applicationId) return;
        setInterviewStatus(error instanceof Error ? error.message : "Forge could not generate the brief.", "error");
      } finally {
        generateInterviewButton.disabled = false;
      }
    });
  }

  if (applicationDialog instanceof HTMLDialogElement) {
    applicationDialog.addEventListener("click", (event) => {
      if (event.target === applicationDialog) applicationDialog.close();
    });
    applicationDialog.addEventListener("close", resetForm);
  }
  if (openApplicationButton instanceof HTMLButtonElement && applicationDialog instanceof HTMLDialogElement) {
    openApplicationButton.addEventListener("click", () => {
      resetForm();
      applicationDialog.showModal();
      window.setTimeout(() => input("company-name")?.focus(), 0);
    });
  }
  if (cancelButton instanceof HTMLButtonElement && applicationDialog instanceof HTMLDialogElement) {
    cancelButton.addEventListener("click", () => applicationDialog.close());
  }
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
      renderApplications();
      if (applicationDialog instanceof HTMLDialogElement) applicationDialog.close();
    } catch (error) {
      setFormStatus(error instanceof Error ? error.message : "The application could not be saved.", "error");
    } finally {
      if (submitButton instanceof HTMLButtonElement) submitButton.disabled = false;
    }
  });

  Promise.all([
    api("/api/v1/resumes"),
    api("/api/v1/job-applications"),
  ]).then(([loadedSources, loadedApplications]) => {
    sources = loadedSources;
    applications = loadedApplications;
    fillResumeOptions();
    renderApplications();
  }).catch((error) => {
    if (list) list.textContent = error instanceof Error ? error.message : "The tracker could not be loaded.";
    setFormStatus("The tracker could not be loaded. Refresh the page and try again.", "error");
  });
}
