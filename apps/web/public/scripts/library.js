const page = document.querySelector(".library-page");

if (page instanceof HTMLElement) {
  const apiBase = (page.dataset.apiBase || "").replace(/\/$/, "");
  const sourceList = document.querySelector("#resume-source-list");
  const variantList = document.querySelector("#resume-variant-list");
  const sourceCount = document.querySelector("#source-count");
  const uploadForm = document.querySelector("#resume-upload-form");
  const fileInput = document.querySelector("#resume-files");
  const fileSelection = document.querySelector("#file-selection");
  const uploadStatus = document.querySelector("#upload-status");
  const dropZone = document.querySelector("#resume-drop-zone");
  const reviewDialog = document.querySelector("#resume-review-dialog");
  const reviewForm = document.querySelector("#resume-review-form");
  const reviewStatus = document.querySelector("#review-status");
  const saveDraftButton = document.querySelector("#save-draft");

  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {
      credentials: "same-origin",
      ...options,
    });
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

  const formatBytes = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const setStatus = (element, message, state = "") => {
    if (!(element instanceof HTMLElement)) return;
    element.textContent = message;
    if (state) element.dataset.state = state;
    else element.removeAttribute("data-state");
  };

  const button = (label, action, id) => {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    element.dataset.action = action;
    element.dataset.id = id;
    return element;
  };

  const renderSources = (sources) => {
    if (!(sourceList instanceof HTMLElement)) return;
    sourceList.replaceChildren();
    if (sourceCount) sourceCount.textContent = `${sources.length} source${sources.length === 1 ? "" : "s"}`;
    if (!sources.length) {
      const template = document.querySelector("#empty-sources-template");
      if (template instanceof HTMLTemplateElement) sourceList.append(template.content.cloneNode(true));
      return;
    }
    sources.forEach((source) => {
      const card = document.createElement("article");
      card.className = "source-card";
      const filetype = document.createElement("span");
      filetype.className = "source-filetype";
      filetype.textContent = source.original_filename.split(".").pop()?.toUpperCase() || "FILE";
      const body = document.createElement("div");
      body.className = "source-body";
      const title = document.createElement("strong");
      title.textContent = source.display_name;
      const meta = document.createElement("div");
      meta.className = "source-meta";
      const role = document.createElement("span");
      role.textContent = source.target_role || "No role assigned";
      const size = document.createElement("span");
      size.textContent = formatBytes(source.byte_size);
      const state = document.createElement("span");
      state.className = "status-pill";
      state.dataset.ready = String(source.status === "ready");
      state.textContent = source.status === "ready" ? "Approved" : source.status === "needs_ocr" ? "Needs text" : "Review needed";
      meta.append(role, size, state);
      body.append(title, meta);
      const actions = document.createElement("div");
      actions.className = "source-actions";
      actions.append(button(source.status === "ready" ? "Edit content" : "Review", "review", source.id));
      if (source.status !== "needs_ocr") {
        const word = document.createElement("a");
        word.href = `${apiBase}/api/v1/resumes/${source.id}/editable.docx`;
        word.textContent = "Word draft";
        word.setAttribute("download", "");
        actions.append(word);
      }
      actions.append(button("Delete", "delete", source.id));
      card.append(filetype, body, actions);
      sourceList.append(card);
    });
  };

  const renderVariants = (variants, documents) => {
    if (!(variantList instanceof HTMLElement)) return;
    variantList.replaceChildren();
    if (!variants.length) {
      const empty = document.createElement("p");
      empty.className = "variant-empty";
      empty.textContent = "Approved role versions will appear here, ready for the Axelyn standard template.";
      variantList.append(empty);
      return;
    }
    variants.forEach((variant) => {
      const card = document.createElement("article");
      card.className = "variant-card";
      const copy = document.createElement("div");
      const role = document.createElement("p");
      role.textContent = variant.target_role || "General resume";
      const name = document.createElement("h3");
      name.textContent = variant.name;
      copy.append(role, name);
      const actions = document.createElement("div");
      actions.className = "variant-actions";
      const downloads = document.createElement("div");
      downloads.className = "variant-downloads";
      const latest = new Map();
      documents
        .filter((document) => document.variant_id === variant.id)
        .forEach((document) => {
          if (!latest.has(document.media_type)) latest.set(document.media_type, document);
        });
      [
        ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "DOCX"],
        ["application/pdf", "PDF"],
      ].forEach(([mediaType, label]) => {
        const artifact = latest.get(mediaType);
        if (!artifact) return;
        const link = document.createElement("a");
        link.href = `${apiBase}/api/v1/documents/${artifact.id}/download`;
        link.textContent = `Download ${label}`;
        link.setAttribute("download", artifact.filename);
        downloads.append(link);
      });
      const generate = button("Generate DOCX + PDF", "render", variant.id);
      const arrow = document.createElement("span");
      arrow.textContent = "↓";
      generate.append(arrow);
      actions.append(downloads, generate);
      card.append(copy, actions);
      variantList.append(card);
    });
  };

  const refresh = async () => {
    const [sources, variants, documents] = await Promise.all([
      api("/api/v1/resumes"),
      api("/api/v1/resume-variants"),
      api("/api/v1/generated-documents"),
    ]);
    renderSources(sources);
    renderVariants(variants, documents);
  };

  const formPayload = () => {
    if (!(reviewForm instanceof HTMLFormElement)) return null;
    const data = new FormData(reviewForm);
    const sectionLines = (name) => String(data.get(name) || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    return {
      display_name: String(data.get("display_name") || ""),
      target_role: String(data.get("target_role") || "") || null,
      full_name: String(data.get("full_name") || ""),
      headline: String(data.get("headline") || ""),
      contact_line: String(data.get("contact_line") || ""),
      summary: String(data.get("summary") || ""),
      extracted_text: String(data.get("extracted_text") || ""),
      sections: {
        experience: sectionLines("section_experience"),
        projects: sectionLines("section_projects"),
        education: sectionLines("section_education"),
        skills: sectionLines("section_skills"),
        languages: sectionLines("section_languages"),
        additional: sectionLines("section_additional"),
      },
    };
  };

  const openReview = async (sourceId) => {
    if (!(reviewDialog instanceof HTMLDialogElement) || !(reviewForm instanceof HTMLFormElement)) return;
    setStatus(reviewStatus, "Loading extracted content…");
    reviewDialog.showModal();
    try {
      const source = await api(`/api/v1/resumes/${sourceId}`);
      const values = {
        source_id: source.id,
        display_name: source.display_name,
        target_role: source.target_role || "",
        full_name: source.draft.full_name || "",
        headline: source.draft.headline || "",
        contact_line: source.draft.contact_line || "",
        summary: source.draft.summary || "",
        extracted_text: source.draft.extracted_text || "",
        section_experience: (source.draft.sections?.experience || []).join("\n"),
        section_projects: (source.draft.sections?.projects || []).join("\n"),
        section_education: (source.draft.sections?.education || []).join("\n"),
        section_skills: (source.draft.sections?.skills || []).join("\n"),
        section_languages: (source.draft.sections?.languages || []).join("\n"),
        section_additional: (source.draft.sections?.additional || []).join("\n"),
        variant_name: source.target_role ? `${source.target_role} — Master` : source.display_name,
      };
      Object.entries(values).forEach(([key, value]) => {
        const field = reviewForm.elements.namedItem(key);
        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) field.value = value;
      });
      setStatus(reviewStatus, source.warning || "Edit the content fields, then approve this version or download a Word draft.");
    } catch (error) {
      setStatus(reviewStatus, error instanceof Error ? error.message : "The resume could not be loaded.", "error");
    }
  };

  const saveDraft = async () => {
    if (!(reviewForm instanceof HTMLFormElement)) return;
    const sourceId = String(new FormData(reviewForm).get("source_id") || "");
    const payload = formPayload();
    if (!sourceId || !payload) return;
    if (saveDraftButton instanceof HTMLButtonElement) saveDraftButton.disabled = true;
    setStatus(reviewStatus, "Saving your review…");
    try {
      await api(`/api/v1/resumes/${sourceId}/draft`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus(reviewStatus, "Review saved.", "success");
      await refresh();
    } catch (error) {
      setStatus(reviewStatus, error instanceof Error ? error.message : "The review could not be saved.", "error");
    } finally {
      if (saveDraftButton instanceof HTMLButtonElement) saveDraftButton.disabled = false;
    }
  };

  fileInput?.addEventListener("change", () => {
    if (!(fileInput instanceof HTMLInputElement) || !(fileSelection instanceof HTMLElement)) return;
    const names = Array.from(fileInput.files || []).map((file) => file.name);
    fileSelection.hidden = !names.length;
    fileSelection.textContent = names.join(" · ");
  });

  ["dragenter", "dragover"].forEach((eventName) => dropZone?.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (dropZone instanceof HTMLElement) dropZone.dataset.dragging = "true";
  }));
  ["dragleave", "drop"].forEach((eventName) => dropZone?.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (dropZone instanceof HTMLElement) dropZone.dataset.dragging = "false";
  }));
  dropZone?.addEventListener("drop", (event) => {
    if (!(event instanceof DragEvent) || !(fileInput instanceof HTMLInputElement) || !event.dataTransfer) return;
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change"));
  });

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!(uploadForm instanceof HTMLFormElement)) return;
    const submit = uploadForm.querySelector("button[type='submit']");
    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    setStatus(uploadStatus, "Reading and securing your resume files…");
    try {
      const result = await api("/api/v1/resumes/imports", { method: "POST", body: new FormData(uploadForm) });
      const rejected = result.items.filter((item) => item.status === "rejected");
      const stored = result.items.length - rejected.length;
      if (rejected.length) {
        setStatus(uploadStatus, `${stored} imported. ${rejected.map((item) => `${item.filename}: ${item.error}`).join(" ")}`, "error");
      } else {
        setStatus(uploadStatus, `${stored} resume${stored === 1 ? "" : "s"} converted into editable content. Review each one before approval.`, "success");
        uploadForm.reset();
        if (fileSelection instanceof HTMLElement) fileSelection.hidden = true;
      }
      await refresh();
    } catch (error) {
      setStatus(uploadStatus, error instanceof Error ? error.message : "The files could not be imported.", "error");
    } finally {
      if (submit instanceof HTMLButtonElement) submit.disabled = false;
    }
  });

  sourceList?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    const { action, id } = target.dataset;
    if (!id) return;
    if (action === "review") await openReview(id);
    if (action === "delete" && window.confirm("Delete this resume source and its generated documents?")) {
      target.disabled = true;
      try {
        await api(`/api/v1/resumes/${id}`, { method: "DELETE" });
        await refresh();
      } catch (error) {
        setStatus(uploadStatus, error instanceof Error ? error.message : "The resume could not be deleted.", "error");
        target.disabled = false;
      }
    }
  });

  saveDraftButton?.addEventListener("click", saveDraft);
  reviewForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!(reviewForm instanceof HTMLFormElement)) return;
    const data = new FormData(reviewForm);
    const sourceId = String(data.get("source_id") || "");
    const payload = { ...formPayload(), variant_name: String(data.get("variant_name") || "") };
    const submit = reviewForm.querySelector("button[type='submit']");
    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    setStatus(reviewStatus, "Approving this resume version…");
    try {
      await api(`/api/v1/resumes/${sourceId}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus(reviewStatus, "Version approved and ready to forge.", "success");
      await refresh();
      window.setTimeout(() => reviewDialog instanceof HTMLDialogElement && reviewDialog.close(), 450);
    } catch (error) {
      setStatus(reviewStatus, error instanceof Error ? error.message : "The version could not be approved.", "error");
    } finally {
      if (submit instanceof HTMLButtonElement) submit.disabled = false;
    }
  });

  variantList?.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-action='render']") : null;
    if (!(target instanceof HTMLButtonElement) || !target.dataset.id) return;
    const original = target.textContent;
    target.disabled = true;
    target.textContent = "Rendering with LibreOffice…";
    try {
      const bundle = await api(`/api/v1/resume-variants/${target.dataset.id}/render`, { method: "POST" });
      await refresh();
      setStatus(uploadStatus, `${bundle.documents.length} files are ready: editable DOCX and layout-stable PDF.`, "success");
    } catch (error) {
      setStatus(uploadStatus, error instanceof Error ? error.message : "The standard resume files could not be generated.", "error");
    } finally {
      target.disabled = false;
      target.textContent = original;
    }
  });

  refresh().catch((error) => {
    setStatus(uploadStatus, error instanceof Error ? error.message : "Your library could not be loaded.", "error");
    if (sourceCount) sourceCount.textContent = "Unavailable";
  });
}
