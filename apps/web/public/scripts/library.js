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

  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, { credentials: "same-origin", ...options });
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

  const setStatus = (message, state = "") => {
    if (!(uploadStatus instanceof HTMLElement)) return;
    uploadStatus.textContent = message;
    if (state) uploadStatus.dataset.state = state;
    else uploadStatus.removeAttribute("data-state");
  };

  const formatBytes = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const renderSources = (sources, artifacts) => {
    if (!(sourceList instanceof HTMLElement)) return;
    const artifactsBySource = new Map();
    artifacts.forEach((artifact) => {
      const current = artifactsBySource.get(artifact.source_id) || [];
      current.push(artifact);
      artifactsBySource.set(artifact.source_id, current);
    });
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
      filetype.textContent = source.media_type === "application/vnd.axelyn.resume+json"
        ? "FORM"
        : source.original_filename.split(".").pop()?.toUpperCase() || "FILE";
      const body = document.createElement("div");
      body.className = "source-body";
      const title = document.createElement("strong");
      title.textContent = source.display_name;
      const meta = document.createElement("div");
      meta.className = "source-meta";
      const role = document.createElement("span");
      role.textContent = source.target_role || "No role assigned";
      const size = document.createElement("span");
      size.textContent = source.media_type === "application/vnd.axelyn.resume+json" ? "Created in Forge" : formatBytes(source.byte_size);
      const state = document.createElement("span");
      state.className = "status-pill";
      state.dataset.ready = String(source.status === "ready");
      state.textContent = source.status === "ready" ? "Approved" : source.status === "needs_ocr" ? "Needs content" : "Draft";
      meta.append(role, size, state);
      body.append(title, meta);
      const actions = document.createElement("div");
      actions.className = "source-actions";
      const edit = document.createElement("a");
      edit.href = `/app/resume?source=${encodeURIComponent(source.id)}`;
      edit.textContent = source.status === "ready" ? "Edit resume" : "Continue editing";
      actions.append(edit);
      const sourceArtifacts = new Map(
        (artifactsBySource.get(source.id) || []).map((artifact) => [artifact.kind, artifact]),
      );
      [
        ["source_docx", "Source DOCX"],
        ["sdt_template", "SDT template"],
        ["resume_json", "JSON"],
        ["resume_schema", "JSON Schema"],
      ].forEach(([kind, label]) => {
        const artifact = sourceArtifacts.get(kind);
        if (!artifact) return;
        const download = document.createElement("a");
        download.href = `${apiBase}/api/v1/resume-source-artifacts/${artifact.id}/download`;
        download.textContent = label;
        download.setAttribute("download", artifact.filename);
        actions.append(download);
      });
      if (!sourceArtifacts.size && source.status !== "needs_ocr") {
        const word = document.createElement("a");
        word.href = `${apiBase}/api/v1/resumes/${source.id}/editable.docx`;
        word.textContent = "Word draft";
        word.setAttribute("download", "");
        actions.append(word);
      }
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete";
      remove.dataset.action = "delete";
      remove.dataset.id = source.id;
      actions.append(remove);
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
      empty.textContent = "Approved resume versions will appear here with their latest Word and PDF files.";
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
      documents.filter((item) => item.variant_id === variant.id).forEach((item) => {
        if (!latest.has(item.media_type)) latest.set(item.media_type, item);
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
      const generate = document.createElement("button");
      generate.type = "button";
      generate.dataset.action = "render";
      generate.dataset.id = variant.id;
      generate.innerHTML = "Generate Word + PDF <span aria-hidden=\"true\">↓</span>";
      actions.append(downloads, generate);
      card.append(copy, actions);
      variantList.append(card);
    });
  };

  const refresh = async () => {
    const [sources, variants, documents, sourceArtifacts] = await Promise.all([
      api("/api/v1/resumes"),
      api("/api/v1/resume-variants"),
      api("/api/v1/generated-documents"),
      api("/api/v1/resume-source-artifacts"),
    ]);
    renderSources(sources, sourceArtifacts);
    renderVariants(variants, documents);
  };

  fileInput?.addEventListener("change", () => {
    if (!(fileInput instanceof HTMLInputElement) || !(fileSelection instanceof HTMLElement)) return;
    const names = Array.from(fileInput.files || []).map((file) => file.name);
    fileSelection.hidden = !names.length;
    fileSelection.textContent = names.join(" · ");
  });
  ["dragenter", "dragover"].forEach((name) => dropZone?.addEventListener(name, (event) => {
    event.preventDefault();
    if (dropZone instanceof HTMLElement) dropZone.dataset.dragging = "true";
  }));
  ["dragleave", "drop"].forEach((name) => dropZone?.addEventListener(name, (event) => {
    event.preventDefault();
    if (dropZone instanceof HTMLElement) dropZone.dataset.dragging = "false";
  }));
  dropZone?.addEventListener("drop", (event) => {
    if (!(event instanceof DragEvent) || !(fileInput instanceof HTMLInputElement) || !event.dataTransfer) return;
    const transfer = new DataTransfer();
    Array.from(event.dataTransfer.files).slice(0, 5).forEach((file) => transfer.items.add(file));
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change"));
  });

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!(uploadForm instanceof HTMLFormElement)) return;
    const submit = uploadForm.querySelector("button[type='submit']");
    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    setStatus("Converting to Word and building your private resume package…");
    try {
      const result = await api("/api/v1/resumes/imports", { method: "POST", body: new FormData(uploadForm) });
      const rejected = result.items.filter((item) => item.status === "rejected");
      const stored = result.items.length - rejected.length;
      if (rejected.length) {
        setStatus(`${stored} imported. ${rejected.map((item) => `${item.filename}: ${item.error}`).join(" ")}`, "error");
      } else {
        setStatus(`${stored} resume${stored === 1 ? "" : "s"} converted into Word, an SDT template, JSON, and JSON Schema.`, "success");
        uploadForm.reset();
        if (fileSelection instanceof HTMLElement) fileSelection.hidden = true;
      }
      await refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The files could not be imported.", "error");
    } finally {
      if (submit instanceof HTMLButtonElement) submit.disabled = false;
    }
  });

  sourceList?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement) || target.dataset.action !== "delete" || !target.dataset.id) return;
    if (!window.confirm("Delete this resume source and its generated documents?")) return;
    target.disabled = true;
    try {
      await api(`/api/v1/resumes/${target.dataset.id}`, { method: "DELETE" });
      await refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The resume could not be deleted.", "error");
      target.disabled = false;
    }
  });

  variantList?.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-action='render']") : null;
    if (!(target instanceof HTMLButtonElement) || !target.dataset.id) return;
    const original = target.innerHTML;
    target.disabled = true;
    target.textContent = "Rendering with LibreOffice…";
    try {
      const bundle = await api(`/api/v1/resume-variants/${target.dataset.id}/render`, { method: "POST" });
      await refresh();
      setStatus(`${bundle.documents.length} files are ready: editable Word and layout-stable PDF.`, "success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The resume files could not be generated.", "error");
    } finally {
      target.disabled = false;
      target.innerHTML = original;
    }
  });

  refresh().catch((error) => {
    setStatus(error instanceof Error ? error.message : "Your library could not be loaded.", "error");
    if (sourceCount) sourceCount.textContent = "Unavailable";
  });
}
