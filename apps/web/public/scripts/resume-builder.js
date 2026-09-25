const builderPage = document.querySelector(".builder-page");

if (builderPage instanceof HTMLElement) {
  const apiBase = (builderPage.dataset.apiBase || "").replace(/\/$/, "");
  const form = document.querySelector("#resume-builder-form");
  const status = document.querySelector("#builder-status");
  const title = document.querySelector("#builder-title");
  const saveButton = document.querySelector("#save-resume-draft");
  const submitButton = form?.querySelector("button[type='submit']");
  const customList = document.querySelector("#custom-section-list");
  const customEmpty = document.querySelector("#custom-section-empty");
  const customTemplate = document.querySelector("#custom-section-template");
  const workList = document.querySelector("#work-experience-list");
  const workEmpty = document.querySelector("#work-experience-empty");
  const workTemplate = document.querySelector("#work-experience-template");
  const legacyExperience = document.querySelector("#legacy-experience");
  const sourceInbox = document.querySelector("#source-inbox");
  const unmappedContent = document.querySelector("#unmapped-content");
  const transcriptPanel = document.querySelector("#source-transcript");
  const transcriptContent = document.querySelector("#source-transcript-content");
  const downloads = document.querySelector("#builder-downloads");
  let sourceId = new URLSearchParams(window.location.search).get("source") || "";
  let currentUnmapped = [];
  let workEntrySequence = 0;

  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, { credentials: "same-origin", ...options });
    if (response.status === 401) {
      window.location.assign(`/sign-in?redirect_url=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      throw new Error("Your session has expired.");
    }
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = Array.isArray(result?.detail) ? result.detail[0]?.msg : result?.detail;
      throw new Error(typeof detail === "string" ? detail.replace(/^Value error, /, "") : "Forge could not complete that request.");
    }
    return result;
  };

  const setStatus = (message, state = "") => {
    if (!(status instanceof HTMLElement)) return;
    status.textContent = message;
    if (state) status.dataset.state = state;
    else status.removeAttribute("data-state");
  };

  const field = (name) => form instanceof HTMLFormElement ? form.elements.namedItem(name) : null;
  const setField = (name, value) => {
    const element = field(name);
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) element.value = value || "";
  };
  const lines = (name) => {
    const element = field(name);
    return element instanceof HTMLTextAreaElement
      ? element.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
      : [];
  };

  const updateCustomEmpty = () => {
    if (customEmpty instanceof HTMLElement && customList instanceof HTMLElement) {
      customEmpty.hidden = customList.children.length > 0;
    }
  };

  const updateWorkEntries = () => {
    if (!(workList instanceof HTMLElement)) return;
    Array.from(workList.querySelectorAll(".work-experience-card")).forEach((card, index) => {
      const number = card.querySelector("[data-work-entry-number]");
      if (number instanceof HTMLElement) number.textContent = `Entry ${String(index + 1).padStart(2, "0")}`;
    });
    if (workEmpty instanceof HTMLElement) workEmpty.hidden = workList.children.length > 0;
  };

  const syncCurrentRole = (card) => {
    const current = card.querySelector("[data-work-current][value='yes']");
    const endDate = card.querySelector("[data-work-field='end_date']");
    const endDateField = card.querySelector("[data-end-date-field]");
    const isCurrent = current instanceof HTMLInputElement && current.checked;
    if (endDate instanceof HTMLInputElement) {
      endDate.disabled = isCurrent;
      endDate.required = !isCurrent;
    }
    if (endDateField instanceof HTMLElement) endDateField.dataset.disabled = String(isCurrent);
  };

  const addWorkExperience = (entry = {}, { scroll = true } = {}) => {
    if (!(workTemplate instanceof HTMLTemplateElement) || !(workList instanceof HTMLElement)) return;
    const fragment = workTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".work-experience-card");
    if (!(card instanceof HTMLElement)) return;
    card.querySelectorAll("[data-work-field]").forEach((control) => {
      const key = control.getAttribute("data-work-field");
      if (!key || !(control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement)) return;
      if (entry[key] !== undefined && entry[key] !== null) control.value = String(entry[key]);
    });
    workEntrySequence += 1;
    const radioName = `work-current-${workEntrySequence}`;
    card.querySelectorAll("[data-work-current]").forEach((radio) => {
      if (!(radio instanceof HTMLInputElement)) return;
      radio.name = radioName;
      radio.checked = entry.currently_working_here
        ? radio.value === "yes"
        : radio.value === "no";
    });
    workList.append(fragment);
    syncCurrentRole(card);
    updateWorkEntries();
    if (scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const addCustomSection = (section = { title: "", lines: [] }) => {
    if (!(customTemplate instanceof HTMLTemplateElement) || !(customList instanceof HTMLElement)) return;
    const fragment = customTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".custom-section-card");
    const titleInput = fragment.querySelector("[data-custom-title]");
    const linesInput = fragment.querySelector("[data-custom-lines]");
    if (titleInput instanceof HTMLInputElement) titleInput.value = section.title || "";
    if (linesInput instanceof HTMLTextAreaElement) linesInput.value = (section.lines || []).join("\n");
    customList.append(fragment);
    updateCustomEmpty();
    if (!section.title && card instanceof HTMLElement) card.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const renderUnmapped = (values) => {
    currentUnmapped = values || [];
    if (sourceInbox instanceof HTMLElement) sourceInbox.hidden = currentUnmapped.length === 0;
    if (unmappedContent instanceof HTMLElement) unmappedContent.textContent = currentUnmapped.join("\n");
  };

  const editableCustomSections = (draft) => {
    const customSections = Array.isArray(draft?.custom_sections)
      ? draft.custom_sections.map((section) => ({
        title: section?.title || "",
        lines: Array.isArray(section?.lines) ? [...section.lines] : [],
      }))
      : [];
    [
      ["languages", "Languages"],
      ["additional", "Additional information"],
    ].forEach(([key, title]) => {
      const legacyLines = Array.isArray(draft?.sections?.[key]) ? draft.sections[key] : [];
      if (!legacyLines.length) return;
      const existing = customSections.find((section) => section.title.toLowerCase() === title.toLowerCase());
      if (existing) {
        existing.lines = [...new Set([...existing.lines, ...legacyLines])];
      } else {
        customSections.push({ title, lines: legacyLines });
      }
    });
    return customSections;
  };

  const payload = () => {
    if (!(form instanceof HTMLFormElement)) return null;
    const selectedTemplate = form.querySelector("input[name='template_id']:checked");
    const customSections = Array.from(form.querySelectorAll(".custom-section-card")).map((card) => {
      const titleInput = card.querySelector("[data-custom-title]");
      const linesInput = card.querySelector("[data-custom-lines]");
      return {
        title: titleInput instanceof HTMLInputElement ? titleInput.value.trim() : "",
        lines: linesInput instanceof HTMLTextAreaElement
          ? linesInput.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
          : [],
      };
    }).filter((section) => section.title && section.lines.length);
    const experienceEntries = Array.from(form.querySelectorAll(".work-experience-card")).map((card) => {
      const value = (name) => {
        const control = card.querySelector(`[data-work-field='${name}']`);
        return control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement
          ? control.value.trim()
          : "";
      };
      const current = card.querySelector("[data-work-current][value='yes']");
      const currentlyWorkingHere = current instanceof HTMLInputElement && current.checked;
      return {
        company_name: value("company_name"),
        job_title: value("job_title"),
        employment_type: value("employment_type"),
        location: value("location"),
        work_arrangement: value("work_arrangement"),
        start_date: value("start_date"),
        end_date: currentlyWorkingHere ? "" : value("end_date"),
        currently_working_here: currentlyWorkingHere,
        responsibilities: value("responsibilities"),
        achievements: value("achievements"),
      };
    });
    return {
      display_name: String(field("display_name")?.value || "").trim(),
      target_role: String(field("target_role")?.value || "").trim() || null,
      template_id: selectedTemplate instanceof HTMLInputElement ? selectedTemplate.value : "ats-classic",
      full_name: String(field("full_name")?.value || "").trim(),
      headline: String(field("headline")?.value || "").trim(),
      contact_line: String(field("contact_line")?.value || "").trim(),
      summary: String(field("summary")?.value || "").trim(),
      extracted_text: String(field("extracted_text")?.value || ""),
      sections: {
        education: lines("section_education"),
        experience: lines("section_experience"),
        projects: lines("section_projects"),
        skills: lines("section_skills"),
      },
      experience_entries: experienceEntries,
      custom_sections: customSections,
    };
  };

  const showDownloads = (documents) => {
    if (!(downloads instanceof HTMLElement)) return;
    downloads.replaceChildren();
    documents.forEach((documentItem) => {
      const link = document.createElement("a");
      link.href = `${apiBase}/api/v1/documents/${documentItem.id}/download`;
      link.download = documentItem.filename;
      link.textContent = documentItem.media_type === "application/pdf" ? "Download PDF" : "Download Word";
      downloads.append(link);
    });
    downloads.hidden = documents.length === 0;
  };

  const save = async ({ generate = false } = {}) => {
    if (!(form instanceof HTMLFormElement) || !form.reportValidity()) return;
    const draft = payload();
    if (!draft) return;
    if (saveButton instanceof HTMLButtonElement) saveButton.disabled = true;
    if (submitButton instanceof HTMLButtonElement) submitButton.disabled = true;
    setStatus(sourceId ? "Saving resume content…" : "Creating your private resume source…");
    try {
      const saved = sourceId
        ? await api(`/api/v1/resumes/${sourceId}/draft`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        })
        : await api("/api/v1/resumes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
      sourceId = saved.id;
      window.history.replaceState({}, "", `/app/resume?source=${encodeURIComponent(sourceId)}`);
      setField("extracted_text", saved.draft.extracted_text || "");
      renderUnmapped(saved.unmapped_content || []);
      const transcript = saved.draft.extracted_text || "";
      if (transcriptPanel instanceof HTMLElement) transcriptPanel.hidden = !transcript;
      if (transcriptContent instanceof HTMLElement) transcriptContent.textContent = transcript;
      if (title) title.innerHTML = "Edit your<br><em>resume source.</em>";
      if (!generate) {
        setStatus("Draft saved. You can return to it from the resume library.", "success");
        return;
      }

      setStatus("Approving the version and generating Word and PDF…");
      const versionField = field("variant_name");
      let variantName = String(versionField?.value || "").trim();
      if (!variantName) {
        variantName = draft.target_role ? `${draft.target_role} — Master` : draft.display_name;
        setField("variant_name", variantName);
      }
      const variant = await api(`/api/v1/resumes/${sourceId}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload(), variant_name: variantName }),
      });
      const bundle = await api(`/api/v1/resume-variants/${variant.id}/render`, { method: "POST" });
      showDownloads(bundle.documents);
      setStatus("Your ATS-friendly Word and PDF files are ready.", "success");
      downloads?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The resume could not be saved.", "error");
    } finally {
      if (saveButton instanceof HTMLButtonElement) saveButton.disabled = false;
      if (submitButton instanceof HTMLButtonElement) submitButton.disabled = false;
    }
  };

  const load = async () => {
    updateCustomEmpty();
    updateWorkEntries();
    if (!sourceId) return;
    setStatus("Loading your private resume source…");
    try {
      const source = await api(`/api/v1/resumes/${sourceId}`);
      if (title) title.innerHTML = "Edit your<br><em>resume source.</em>";
      setField("display_name", source.display_name);
      setField("target_role", source.target_role || "");
      setField("full_name", source.draft.full_name || "");
      setField("headline", source.draft.headline || "");
      setField("contact_line", source.draft.contact_line || "");
      setField("summary", source.draft.summary || "");
      setField("extracted_text", source.draft.extracted_text || "");
      ["education", "projects", "skills"].forEach((name) => {
        setField(`section_${name}`, (source.draft.sections?.[name] || []).join("\n"));
      });
      const importedExperience = source.draft.sections?.experience || [];
      setField("section_experience", importedExperience.join("\n"));
      if (legacyExperience instanceof HTMLElement) legacyExperience.hidden = importedExperience.length === 0;
      if (workList instanceof HTMLElement) workList.replaceChildren();
      (source.draft.experience_entries || []).forEach((entry) => addWorkExperience(entry, { scroll: false }));
      updateWorkEntries();
      const templateInput = form?.querySelector(`input[name='template_id'][value='${source.draft.template_id || "ats-classic"}']`);
      if (templateInput instanceof HTMLInputElement) templateInput.checked = true;
      if (customList instanceof HTMLElement) customList.replaceChildren();
      editableCustomSections(source.draft).forEach(addCustomSection);
      updateCustomEmpty();
      renderUnmapped(source.unmapped_content || []);
      const transcript = source.draft.extracted_text || "";
      if (transcriptPanel instanceof HTMLElement) transcriptPanel.hidden = !transcript;
      if (transcriptContent instanceof HTMLElement) transcriptContent.textContent = transcript;
      const variantName = field("variant_name");
      if (variantName instanceof HTMLInputElement) variantName.value = source.target_role ? `${source.target_role} — Master` : source.display_name;
      setStatus(source.warning || "Resume loaded. Every edit stays in this private source.", "success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The resume could not be loaded.", "error");
    }
  };

  document.querySelector("#add-custom-section")?.addEventListener("click", () => addCustomSection());
  document.querySelector("#add-work-experience")?.addEventListener("click", () => addWorkExperience());
  workList?.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-remove-work-experience]") : null;
    if (!(button instanceof HTMLButtonElement)) return;
    button.closest(".work-experience-card")?.remove();
    updateWorkEntries();
  });
  workList?.addEventListener("change", (event) => {
    const radio = event.target instanceof Element ? event.target.closest("[data-work-current]") : null;
    if (!(radio instanceof HTMLInputElement)) return;
    const card = radio.closest(".work-experience-card");
    if (card instanceof HTMLElement) syncCurrentRole(card);
  });
  customList?.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-remove-custom]") : null;
    if (!(button instanceof HTMLButtonElement)) return;
    button.closest(".custom-section-card")?.remove();
    updateCustomEmpty();
  });
  document.querySelector("#keep-unmapped")?.addEventListener("click", () => {
    if (!currentUnmapped.length) return;
    addCustomSection({ title: "Imported content", lines: currentUnmapped });
    renderUnmapped([]);
  });
  saveButton?.addEventListener("click", () => save());
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    save({ generate: true });
  });
  load();
}
