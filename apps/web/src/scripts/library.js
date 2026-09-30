const page = document.querySelector(".library-page");

if (page instanceof HTMLElement) {
  const apiBase = (page.dataset.apiBase || "").replace(/\/$/, "");
  const sourceList = document.querySelector("#resume-source-list");
  const sourceCount = document.querySelector("#source-count");
  const fileInput = document.querySelector("#resume-files");
  const fileQueue = document.querySelector("#file-queue");
  const uploadFileTemplate = document.querySelector("#upload-file-template");
  const uploadStatus = document.querySelector("#upload-status");
  const dropZone = document.querySelector("#resume-drop-zone");
  const queuedFiles = new Map();
  const maxQueuedFiles = 5;

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

  const responseError = (result, fallback = "Forge could not complete that request.") => {
    const detail = Array.isArray(result?.detail) ? result.detail[0]?.msg : result?.detail;
    return typeof detail === "string" ? detail.replace(/^Value error, /, "") : fallback;
  };

  const updateQueuedFile = (item, state, message, progress = null) => {
    item.state = state;
    item.row.dataset.state = state;
    item.stateLabel.textContent = message;
    item.button.disabled = ["uploading", "processing", "complete"].includes(state);
    const labels = {
      queued: "Import",
      uploading: "Uploading",
      processing: "Working",
      complete: "Imported",
      error: "Retry",
    };
    item.buttonLabel.textContent = labels[state] || "Import";
    item.button.setAttribute(
      "aria-label",
      `${state === "error" ? "Retry importing" : state === "complete" ? "Imported" : "Import"} ${item.file.name}`,
    );
    if (state === "processing") {
      item.progress.removeAttribute("aria-valuenow");
      item.progressValue.textContent = "AI";
      item.progressFill.style.removeProperty("width");
      return;
    }
    const value = typeof progress === "number" ? Math.max(0, Math.min(100, progress)) : 0;
    item.progress.setAttribute("aria-valuenow", String(value));
    item.progressValue.textContent = `${value}%`;
    item.progressFill.style.width = `${value}%`;
  };

  const importFile = (file, onProgress, onProcessing) => new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${apiBase}/api/v1/resumes/imports`);
    request.withCredentials = true;
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.upload.addEventListener("load", onProcessing);
    request.addEventListener("load", () => {
      let result = null;
      try {
        result = request.responseText ? JSON.parse(request.responseText) : null;
      } catch {
        result = null;
      }
      if (request.status === 401) {
        window.location.assign(`/sign-in?redirect_url=${encodeURIComponent(window.location.pathname)}`);
        reject(new Error("Your session has expired."));
        return;
      }
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(responseError(result)));
        return;
      }
      resolve(result);
    });
    request.addEventListener("error", () => reject(new Error("The upload was interrupted. Try again.")));
    const payload = new FormData();
    payload.append("files", file, file.name);
    request.send(payload);
  });

  const startFileImport = async (key) => {
    const item = queuedFiles.get(key);
    if (!item || !["queued", "error"].includes(item.state)) return;
    setStatus("");
    updateQueuedFile(item, "uploading", `${formatBytes(item.file.size)} · Uploading…`, 0);
    try {
      const result = await importFile(
        item.file,
        (progress) => updateQueuedFile(
          item,
          "uploading",
          `${formatBytes(item.file.size)} · Uploading ${progress}%`,
          progress,
        ),
        () => updateQueuedFile(
          item,
          "processing",
          `${formatBytes(item.file.size)} · Converting and structuring…`,
        ),
      );
      const imported = result?.items?.[0];
      if (!imported) throw new Error("Forge returned an incomplete import response.");
      if (imported.status === "rejected") {
        throw new Error(imported.error || "This resume could not be imported.");
      }
      updateQueuedFile(item, "complete", `${formatBytes(item.file.size)} · Import complete`, 100);
      setStatus(`${item.file.name} is ready in your resume sources.`, "success");
      await refresh().catch((error) => {
        const message = error instanceof Error ? error.message : "The resume library could not be refreshed.";
        setStatus(`${item.file.name} was imported, but ${message.toLowerCase()}`, "error");
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "This resume could not be imported.";
      updateQueuedFile(item, "error", message, 0);
      setStatus(`${item.file.name}: ${message}`, "error");
    }
  };

  const addFilesToQueue = (files) => {
    if (!(fileQueue instanceof HTMLElement) || !(uploadFileTemplate instanceof HTMLTemplateElement)) return;
    if (queuedFiles.size && Array.from(queuedFiles.values()).every((item) => item.state === "complete")) {
      queuedFiles.clear();
      fileQueue.replaceChildren();
    }
    const available = Math.max(0, maxQueuedFiles - queuedFiles.size);
    const accepted = files
      .filter((file) => /\.(?:docx|pdf)$/i.test(file.name))
      .slice(0, available);
    accepted.forEach((file) => {
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      if (queuedFiles.has(key)) return;
      const fragment = uploadFileTemplate.content.cloneNode(true);
      const row = fragment.querySelector(".upload-file");
      if (!(row instanceof HTMLElement)) return;
      const type = row.querySelector(".upload-file-type");
      const name = row.querySelector(".upload-file-copy strong");
      const stateLabel = row.querySelector(".upload-file-state");
      const progress = row.querySelector(".upload-file-progress");
      const progressFill = row.querySelector(".upload-progress-fill");
      const progressValue = row.querySelector(".upload-progress-value");
      const button = row.querySelector(".upload-file-action");
      const buttonLabel = row.querySelector(".upload-action-label");
      if (!(type instanceof HTMLElement)
        || !(name instanceof HTMLElement)
        || !(stateLabel instanceof HTMLElement)
        || !(progress instanceof HTMLElement)
        || !(progressFill instanceof HTMLElement)
        || !(progressValue instanceof HTMLElement)
        || !(button instanceof HTMLButtonElement)
        || !(buttonLabel instanceof HTMLElement)) return;
      type.textContent = file.name.split(".").pop()?.toUpperCase() || "FILE";
      name.textContent = file.name;
      progress.setAttribute("aria-label", `Upload progress for ${file.name}`);
      row.dataset.fileKey = key;
      const item = {
        file,
        row,
        state: "queued",
        stateLabel,
        progress,
        progressFill,
        progressValue,
        button,
        buttonLabel,
      };
      queuedFiles.set(key, item);
      updateQueuedFile(item, "queued", `${formatBytes(file.size)} · Ready to import`, 0);
      fileQueue.append(fragment);
    });
    fileQueue.hidden = queuedFiles.size === 0;
    const skipped = files.length - accepted.length;
    if (skipped > 0) {
      setStatus(`Add up to ${maxQueuedFiles} PDF or DOCX files at a time.`, "error");
    } else if (accepted.length) {
      setStatus(`${accepted.length} resume${accepted.length === 1 ? "" : "s"} ready. Import each file when you are ready.`);
    }
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
      filetype.textContent = source.original_filename.split(".").pop()?.toUpperCase() || "FILE";
      const body = document.createElement("div");
      body.className = "source-body";
      const title = document.createElement("strong");
      title.textContent = source.display_name;
      const meta = document.createElement("div");
      meta.className = "source-meta";
      const size = document.createElement("span");
      size.textContent = formatBytes(source.byte_size);
      const state = document.createElement("span");
      state.className = "status-pill";
      state.dataset.ready = String(source.status === "ready");
      state.textContent = "Imported";
      meta.append(size, state);
      body.append(title, meta);
      if (source.warning) {
        const warning = document.createElement("p");
        warning.className = "source-warning";
        warning.textContent = source.warning;
        body.append(warning);
      }
      const actions = document.createElement("div");
      actions.className = "source-actions";
      const sourceArtifacts = new Map(
        (artifactsBySource.get(source.id) || []).map((artifact) => [artifact.kind, artifact]),
      );
      [
        ["resume_docx", "DOCX"],
        ["resume_pdf", "PDF"],
      ].forEach(([kind, label]) => {
        const artifact = sourceArtifacts.get(kind);
        if (!artifact) return;
        const download = document.createElement("a");
        download.href = `${apiBase}/api/v1/resume-source-artifacts/${artifact.id}/download`;
        download.textContent = label;
        download.setAttribute("download", artifact.filename);
        actions.append(download);
      });
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

  const refresh = async () => {
    const [sources, sourceArtifacts] = await Promise.all([
      api("/api/v1/resumes"),
      api("/api/v1/resume-source-artifacts"),
    ]);
    renderSources(sources, sourceArtifacts);
  };

  fileInput?.addEventListener("change", () => {
    if (!(fileInput instanceof HTMLInputElement)) return;
    addFilesToQueue(Array.from(fileInput.files || []));
    fileInput.value = "";
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
    if (!(event instanceof DragEvent) || !event.dataTransfer) return;
    addFilesToQueue(Array.from(event.dataTransfer.files));
  });

  fileQueue?.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("button[data-action='import-file']")
      : null;
    const row = button?.closest(".upload-file");
    if (!(button instanceof HTMLButtonElement) || !(row instanceof HTMLElement) || !row.dataset.fileKey) return;
    startFileImport(row.dataset.fileKey);
  });

  sourceList?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement) || target.dataset.action !== "delete" || !target.dataset.id) return;
    if (!window.confirm("Delete this resume and its DOCX and PDF files? Upload the source again to replace it.")) return;
    target.disabled = true;
    try {
      await api(`/api/v1/resumes/${target.dataset.id}`, { method: "DELETE" });
      await refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The resume could not be deleted.", "error");
      target.disabled = false;
    }
  });


  refresh().catch((error) => {
    setStatus(error instanceof Error ? error.message : "Your library could not be loaded.", "error");
    if (sourceCount) sourceCount.textContent = "Unavailable";
  });
}
