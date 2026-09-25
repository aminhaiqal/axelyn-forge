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
  const educationList = document.querySelector("#education-list");
  const educationEmpty = document.querySelector("#education-empty");
  const educationTemplate = document.querySelector("#education-template");
  const legacyEducation = document.querySelector("#legacy-education");
  const projectList = document.querySelector("#project-list");
  const projectEmpty = document.querySelector("#project-empty");
  const projectTemplate = document.querySelector("#project-template");
  const legacyProjects = document.querySelector("#legacy-projects");
  const skillCategoryList = document.querySelector("#skill-category-list");
  const skillCategoryEmpty = document.querySelector("#skill-category-empty");
  const skillCategoryTemplate = document.querySelector("#skill-category-template");
  const legacySkills = document.querySelector("#legacy-skills");
  const sourceInbox = document.querySelector("#source-inbox");
  const unmappedContent = document.querySelector("#unmapped-content");
  const transcriptPanel = document.querySelector("#source-transcript");
  const transcriptContent = document.querySelector("#source-transcript-content");
  const downloads = document.querySelector("#builder-downloads");
  let sourceId = new URLSearchParams(window.location.search).get("source") || "";
  let currentUnmapped = [];
  let workEntrySequence = 0;
  let educationEntrySequence = 0;
  let projectEntrySequence = 0;
  let skillCategorySequence = 0;

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

  const updateEducationEntries = () => {
    if (!(educationList instanceof HTMLElement)) return;
    Array.from(educationList.querySelectorAll(".education-card")).forEach((card, index) => {
      const number = card.querySelector("[data-education-entry-number]");
      if (number instanceof HTMLElement) number.textContent = `Entry ${String(index + 1).padStart(2, "0")}`;
    });
    if (educationEmpty instanceof HTMLElement) educationEmpty.hidden = educationList.children.length > 0;
  };

  const syncCurrentStudy = (card) => {
    const current = card.querySelector("[data-education-current][value='yes']");
    const endDate = card.querySelector("[data-education-field='end_date']");
    const endDateField = card.querySelector("[data-education-end-date-field]");
    const isCurrent = current instanceof HTMLInputElement && current.checked;
    if (endDate instanceof HTMLInputElement) {
      endDate.disabled = isCurrent;
      endDate.required = !isCurrent;
    }
    if (endDateField instanceof HTMLElement) endDateField.dataset.disabled = String(isCurrent);
  };

  const addEducation = (entry = {}, { scroll = true } = {}) => {
    if (!(educationTemplate instanceof HTMLTemplateElement) || !(educationList instanceof HTMLElement)) return;
    const fragment = educationTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".education-card");
    if (!(card instanceof HTMLElement)) return;
    card.querySelectorAll("[data-education-field]").forEach((control) => {
      const key = control.getAttribute("data-education-field");
      if (!key || !(control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement)) return;
      if (entry[key] !== undefined && entry[key] !== null) control.value = String(entry[key]);
    });
    educationEntrySequence += 1;
    const radioName = `education-current-${educationEntrySequence}`;
    card.querySelectorAll("[data-education-current]").forEach((radio) => {
      if (!(radio instanceof HTMLInputElement)) return;
      radio.name = radioName;
      radio.checked = entry.currently_studying_here
        ? radio.value === "yes"
        : radio.value === "no";
    });
    const optionalKeys = ["gpa", "honours", "relevant_coursework", "thesis_title", "thesis_description", "academic_achievements", "activities", "relevant_skills"];
    const optional = card.querySelector(".education-optional");
    if (optional instanceof HTMLElement) optional.open = optionalKeys.some((key) => String(entry[key] || "").trim());
    educationList.append(fragment);
    syncCurrentStudy(card);
    updateEducationEntries();
    if (scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const updateProjectEntries = () => {
    if (!(projectList instanceof HTMLElement)) return;
    Array.from(projectList.querySelectorAll(".project-card")).forEach((card, index) => {
      const number = card.querySelector("[data-project-entry-number]");
      if (number instanceof HTMLElement) number.textContent = `Entry ${String(index + 1).padStart(2, "0")}`;
    });
    if (projectEmpty instanceof HTMLElement) projectEmpty.hidden = projectList.children.length > 0;
  };

  const syncCurrentProject = (card) => {
    const current = card.querySelector("[data-project-current][value='yes']");
    const endDate = card.querySelector("[data-project-field='end_date']");
    const endDateField = card.querySelector("[data-project-end-date-field]");
    const isCurrent = current instanceof HTMLInputElement && current.checked;
    if (endDate instanceof HTMLInputElement) endDate.disabled = isCurrent;
    if (endDateField instanceof HTMLElement) endDateField.dataset.disabled = String(isCurrent);
  };

  const addProject = (entry = {}, { scroll = true } = {}) => {
    if (!(projectTemplate instanceof HTMLTemplateElement) || !(projectList instanceof HTMLElement)) return;
    const fragment = projectTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".project-card");
    if (!(card instanceof HTMLElement)) return;
    card.querySelectorAll("[data-project-field]").forEach((control) => {
      const key = control.getAttribute("data-project-field");
      if (!key || !(control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement)) return;
      if (entry[key] !== undefined && entry[key] !== null) control.value = String(entry[key]);
    });
    projectEntrySequence += 1;
    const radioName = `project-current-${projectEntrySequence}`;
    card.querySelectorAll("[data-project-current]").forEach((radio) => {
      if (!(radio instanceof HTMLInputElement)) return;
      radio.name = radioName;
      radio.checked = entry.currently_working_on_project
        ? radio.value === "yes"
        : radio.value === "no";
    });
    const optionalKeys = ["project_url", "repository_url", "challenge"];
    const optional = card.querySelector(".project-optional");
    if (optional instanceof HTMLElement) optional.open = optionalKeys.some((key) => String(entry[key] || "").trim());
    projectList.append(fragment);
    syncCurrentProject(card);
    updateProjectEntries();
    if (scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const updateSkillCategories = () => {
    if (!(skillCategoryList instanceof HTMLElement)) return;
    Array.from(skillCategoryList.querySelectorAll(".skill-category-card")).forEach((card, index) => {
      const number = card.querySelector("[data-skill-category-number]");
      if (number instanceof HTMLElement) number.textContent = `Category ${String(index + 1).padStart(2, "0")}`;
    });
    if (skillCategoryEmpty instanceof HTMLElement) skillCategoryEmpty.hidden = skillCategoryList.children.length > 0;
  };

  const parsedSkills = (value) => String(value || "")
    .split(/[,\n]+/)
    .map((skill) => skill.trim())
    .filter(Boolean);

  const skillValues = (card, { includeInput = false } = {}) => {
    const values = Array.from(card.querySelectorAll("[data-skill-chip]"))
      .map((chip) => chip.getAttribute("data-skill-chip") || "")
      .filter(Boolean);
    if (includeInput) {
      const input = card.querySelector("[data-skill-input]");
      if (input instanceof HTMLInputElement) values.push(...parsedSkills(input.value));
    }
    const seen = new Set();
    return values.filter((skill) => {
      const key = skill.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  const syncSkillRequirement = (card) => {
    const input = card.querySelector("[data-skill-input]");
    if (!(input instanceof HTMLInputElement)) return;
    input.required = skillValues(card).length === 0;
    input.setCustomValidity("");
  };

  const addSkillChip = (card, skill) => {
    const value = String(skill || "").trim();
    const chips = card.querySelector("[data-skill-chips]");
    if (!value || !(chips instanceof HTMLElement)) return;
    if (skillValues(card).some((existing) => existing.toLocaleLowerCase() === value.toLocaleLowerCase())) return;
    const chip = document.createElement("span");
    chip.dataset.skillChip = value;
    chip.setAttribute("role", "listitem");
    const label = document.createElement("span");
    label.textContent = value;
    chip.append(label);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.removeSkill = "";
    remove.setAttribute("aria-label", `Remove ${value}`);
    remove.textContent = "×";
    chip.append(remove);
    chips.append(chip);
  };

  const commitSkillInput = (card, { focus = true } = {}) => {
    const input = card.querySelector("[data-skill-input]");
    if (!(input instanceof HTMLInputElement)) return;
    parsedSkills(input.value).forEach((skill) => addSkillChip(card, skill));
    input.value = "";
    syncSkillRequirement(card);
    if (focus) input.focus();
  };

  const addSkillCategory = (entry = { category: "", skills: [] }, { scroll = true } = {}) => {
    if (!(skillCategoryTemplate instanceof HTMLTemplateElement) || !(skillCategoryList instanceof HTMLElement)) return;
    const fragment = skillCategoryTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".skill-category-card");
    if (!(card instanceof HTMLElement)) return;
    const category = card.querySelector("[data-skill-category]");
    if (category instanceof HTMLInputElement && entry.category) category.value = String(entry.category);
    skillCategorySequence += 1;
    const input = card.querySelector("[data-skill-input]");
    if (input instanceof HTMLInputElement) input.id = `skill-input-${skillCategorySequence}`;
    (Array.isArray(entry.skills) ? entry.skills : []).forEach((skill) => addSkillChip(card, skill));
    skillCategoryList.append(fragment);
    syncSkillRequirement(card);
    updateSkillCategories();
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
    const educationEntries = Array.from(form.querySelectorAll(".education-card")).map((card) => {
      const value = (name) => {
        const control = card.querySelector(`[data-education-field='${name}']`);
        return control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement
          ? control.value.trim()
          : "";
      };
      const current = card.querySelector("[data-education-current][value='yes']");
      const currentlyStudyingHere = current instanceof HTMLInputElement && current.checked;
      return {
        institution_name: value("institution_name"),
        qualification: value("qualification"),
        field_of_study: value("field_of_study"),
        education_level: value("education_level"),
        location: value("location"),
        start_date: value("start_date"),
        end_date: currentlyStudyingHere ? "" : value("end_date"),
        currently_studying_here: currentlyStudyingHere,
        gpa: value("gpa"),
        honours: value("honours"),
        relevant_coursework: value("relevant_coursework"),
        thesis_title: value("thesis_title"),
        thesis_description: value("thesis_description"),
        academic_achievements: value("academic_achievements"),
        activities: value("activities"),
        relevant_skills: value("relevant_skills"),
      };
    });
    const projectEntries = Array.from(form.querySelectorAll(".project-card")).map((card) => {
      const value = (name) => {
        const control = card.querySelector(`[data-project-field='${name}']`);
        return control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement
          ? control.value.trim()
          : "";
      };
      const current = card.querySelector("[data-project-current][value='yes']");
      const currentlyWorkingOnProject = current instanceof HTMLInputElement && current.checked;
      return {
        project_name: value("project_name"),
        project_type: value("project_type"),
        role: value("role"),
        project_url: value("project_url"),
        repository_url: value("repository_url"),
        start_date: value("start_date"),
        end_date: currentlyWorkingOnProject ? "" : value("end_date"),
        currently_working_on_project: currentlyWorkingOnProject,
        problem: value("problem"),
        description: value("description"),
        audience: value("audience"),
        personal_contribution: value("personal_contribution"),
        responsibilities: value("responsibilities"),
        technologies: value("technologies"),
        challenge: value("challenge"),
        deliverables: value("deliverables"),
        impact: value("impact"),
        metrics: value("metrics"),
        project_status: value("project_status"),
      };
    });
    const skillCategories = Array.from(form.querySelectorAll(".skill-category-card")).map((card) => {
      const category = card.querySelector("[data-skill-category]");
      return {
        category: category instanceof HTMLInputElement ? category.value.trim() : "",
        skills: skillValues(card, { includeInput: true }),
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
      education_entries: educationEntries,
      project_entries: projectEntries,
      skill_categories: skillCategories,
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
    updateEducationEntries();
    updateProjectEntries();
    updateSkillCategories();
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
      const importedSkills = source.draft.sections?.skills || [];
      setField("section_skills", importedSkills.join("\n"));
      if (legacySkills instanceof HTMLElement) legacySkills.hidden = importedSkills.length === 0;
      if (skillCategoryList instanceof HTMLElement) skillCategoryList.replaceChildren();
      (source.draft.skill_categories || []).forEach((entry) => addSkillCategory(entry, { scroll: false }));
      updateSkillCategories();
      const importedProjects = source.draft.sections?.projects || [];
      setField("section_projects", importedProjects.join("\n"));
      if (legacyProjects instanceof HTMLElement) legacyProjects.hidden = importedProjects.length === 0;
      if (projectList instanceof HTMLElement) projectList.replaceChildren();
      (source.draft.project_entries || []).forEach((entry) => addProject(entry, { scroll: false }));
      updateProjectEntries();
      const importedEducation = source.draft.sections?.education || [];
      setField("section_education", importedEducation.join("\n"));
      if (legacyEducation instanceof HTMLElement) legacyEducation.hidden = importedEducation.length === 0;
      if (educationList instanceof HTMLElement) educationList.replaceChildren();
      (source.draft.education_entries || []).forEach((entry) => addEducation(entry, { scroll: false }));
      updateEducationEntries();
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
  document.querySelector("#add-education")?.addEventListener("click", () => addEducation());
  educationList?.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-remove-education]") : null;
    if (!(button instanceof HTMLButtonElement)) return;
    button.closest(".education-card")?.remove();
    updateEducationEntries();
  });
  educationList?.addEventListener("change", (event) => {
    const radio = event.target instanceof Element ? event.target.closest("[data-education-current]") : null;
    if (!(radio instanceof HTMLInputElement)) return;
    const card = radio.closest(".education-card");
    if (card instanceof HTMLElement) syncCurrentStudy(card);
  });
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
  document.querySelector("#add-project")?.addEventListener("click", () => addProject());
  projectList?.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-remove-project]") : null;
    if (!(button instanceof HTMLButtonElement)) return;
    button.closest(".project-card")?.remove();
    updateProjectEntries();
  });
  projectList?.addEventListener("change", (event) => {
    const radio = event.target instanceof Element ? event.target.closest("[data-project-current]") : null;
    if (!(radio instanceof HTMLInputElement)) return;
    const card = radio.closest(".project-card");
    if (card instanceof HTMLElement) syncCurrentProject(card);
  });
  document.querySelector("#add-skill-category")?.addEventListener("click", () => addSkillCategory());
  skillCategoryList?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const card = target.closest(".skill-category-card");
    if (!(card instanceof HTMLElement)) return;
    if (target.closest("[data-remove-skill-category]")) {
      card.remove();
      updateSkillCategories();
      return;
    }
    if (target.closest("[data-add-skill]")) {
      commitSkillInput(card);
      return;
    }
    const removeSkill = target.closest("[data-remove-skill]");
    if (removeSkill) {
      removeSkill.closest("[data-skill-chip]")?.remove();
      syncSkillRequirement(card);
    }
  });
  skillCategoryList?.addEventListener("keydown", (event) => {
    const input = event.target instanceof Element ? event.target.closest("[data-skill-input]") : null;
    if (!(input instanceof HTMLInputElement) || (event.key !== "Enter" && event.key !== ",")) return;
    event.preventDefault();
    const card = input.closest(".skill-category-card");
    if (card instanceof HTMLElement) commitSkillInput(card);
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
