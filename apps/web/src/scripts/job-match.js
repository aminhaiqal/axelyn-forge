const matchPage = document.querySelector(".match-page");

if (matchPage instanceof HTMLElement) {
  const apiBase = (matchPage.dataset.apiBase || "").replace(/\/$/, "");
  const form = document.querySelector("#job-match-form");
  const resumeSelect = document.querySelector("#match-resume-select");
  const resumeHelp = document.querySelector("#resume-select-help");
  const description = form?.elements.namedItem("job_description");
  const count = document.querySelector("#job-description-count");
  const fileInput = document.querySelector("#job-files");
  const fileList = document.querySelector("#job-file-list");
  const dropZone = document.querySelector("#job-drop-zone");
  const formStatus = document.querySelector("#job-match-status");
  const submitButton = form?.querySelector("button[type='submit']");
  const workspace = document.querySelector("#match-workspace");
  const resultShell = document.querySelector("#match-result-shell");
  const resultPanel = document.querySelector("#match-result");
  const resultState = document.querySelector("#match-result-state");
  const tailorBlock = document.querySelector("#tailor-block");
  const generateButton = document.querySelector("#generate-tailored-resume");
  const downloads = document.querySelector("#tailor-downloads");
  const historyList = document.querySelector("#match-history-list");
  const historyCount = document.querySelector("#match-history-count");
  let latestMatch = null;

  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {
      credentials: "same-origin",
      ...options,
    });
    if (response.status === 401) {
      window.location.assign(`/sign-in?redirect_url=${encodeURIComponent(window.location.pathname)}`);
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
    if (!(formStatus instanceof HTMLElement)) return;
    formStatus.textContent = message;
    if (state) formStatus.dataset.state = state;
    else formStatus.removeAttribute("data-state");
  };

  const fillList = (selector, values, fallback) => {
    const list = document.querySelector(selector);
    if (!(list instanceof HTMLElement)) return;
    list.replaceChildren();
    (values.length ? values : [fallback]).forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      list.append(item);
    });
  };

  const fillKeywords = (selector, values, fallback) => {
    const container = document.querySelector(selector);
    if (!(container instanceof HTMLElement)) return;
    container.replaceChildren();
    (values.length ? values : [fallback]).forEach((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      if (!values.length) item.dataset.empty = "true";
      container.append(item);
    });
  };

  const renderFiles = () => {
    if (!(fileInput instanceof HTMLInputElement) || !(fileList instanceof HTMLElement)) return;
    const files = Array.from(fileInput.files || []);
    fileList.hidden = files.length === 0;
    fileList.textContent = files.map((file) => `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`).join("\n");
  };

  const loadResumes = async () => {
    if (!(resumeSelect instanceof HTMLSelectElement)) return;
    try {
      const resumes = await api("/api/v1/resumes");
      resumeSelect.replaceChildren();
      const prompt = document.createElement("option");
      prompt.value = "";
      prompt.textContent = resumes.length ? "Choose a resume source" : "No resume sources yet";
      resumeSelect.append(prompt);
      resumes.forEach((resume) => {
        const option = document.createElement("option");
        option.value = resume.id;
        option.textContent = `${resume.display_name}${resume.target_role ? ` — ${resume.target_role}` : ""}${resume.status === "needs_ocr" ? " (needs text)" : ""}`;
        option.disabled = resume.status === "needs_ocr";
        resumeSelect.append(option);
      });
      if (!resumes.length && resumeHelp instanceof HTMLElement) {
        resumeHelp.innerHTML = 'Import and review a resume in your <a href="/app">resume library</a> first.';
      }
    } catch (error) {
      resumeSelect.innerHTML = '<option value="">Resume library unavailable</option>';
      setStatus(error instanceof Error ? error.message : "Could not load your resumes.", "error");
    }
  };

  const renderDownloads = (documents) => {
    if (!(downloads instanceof HTMLElement)) return;
    downloads.replaceChildren();
    documents.forEach((documentItem) => {
      const link = document.createElement("a");
      const isPdf = documentItem.media_type === "application/pdf";
      link.href = `${apiBase}/api/v1/job-match-documents/${documentItem.id}/download`;
      link.download = documentItem.filename;
      link.textContent = `Download ${isPdf ? "PDF" : "Word"}`;
      downloads.append(link);
    });
    downloads.hidden = documents.length === 0;
  };

  const historyDate = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  const renderHistory = (matches) => {
    if (!(historyList instanceof HTMLElement)) return;
    historyList.replaceChildren();
    if (historyCount) historyCount.textContent = `${matches.length} saved ${matches.length === 1 ? "match" : "matches"}`;
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "history-message";
      empty.textContent = "Your completed job-match analyses will appear here.";
      historyList.append(empty);
      return;
    }
    matches.forEach((match) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "match-history-item";
      item.dataset.matchId = match.id;

      const role = document.createElement("div");
      role.className = "history-role";
      const date = document.createElement("span");
      const parsedDate = new Date(match.created_at);
      date.textContent = Number.isNaN(parsedDate.getTime()) ? match.created_at : historyDate.format(parsedDate);
      const title = document.createElement("h3");
      title.textContent = match.target_role;
      const company = document.createElement("p");
      company.textContent = match.company || "Company not specified";
      role.append(date, title, company);

      const resume = document.createElement("span");
      resume.className = "history-resume";
      resume.textContent = `${match.resume_name}${match.has_documents ? " · Files ready" : ""}`;

      const score = document.createElement("div");
      score.className = "history-score";
      score.dataset.state = match.match_state;
      const percentage = document.createElement("strong");
      percentage.textContent = `${match.match_percentage}%`;
      const label = document.createElement("span");
      label.textContent = match.match_label;
      score.append(percentage, label);

      item.append(role, resume, score);
      historyList.append(item);
    });
  };

  const loadHistory = async () => {
    if (!(historyList instanceof HTMLElement)) return;
    try {
      renderHistory(await api("/api/v1/job-matches"));
    } catch (error) {
      historyList.replaceChildren();
      const message = document.createElement("p");
      message.className = "history-message";
      message.textContent = error instanceof Error ? error.message : "Match history is unavailable.";
      historyList.append(message);
      if (historyCount) historyCount.textContent = "Unavailable";
    }
  };

  const generateTailored = async () => {
    if (!latestMatch || !(generateButton instanceof HTMLButtonElement)) return;
    generateButton.disabled = true;
    generateButton.firstChild.textContent = "Generating Word and PDF ";
    if (resultState) resultState.textContent = "Building documents";
    try {
      const bundle = await api(`/api/v1/job-matches/${latestMatch.id}/tailor`, { method: "POST" });
      renderDownloads(bundle.documents);
      generateButton.hidden = true;
      const message = document.querySelector("#tailor-message");
      if (message) message.textContent = "Your evidence-grounded Word and PDF files are ready.";
      if (resultState) resultState.textContent = "Documents ready";
      loadHistory();
    } catch (error) {
      generateButton.disabled = false;
      generateButton.firstChild.textContent = "Try generation again ";
      const message = document.querySelector("#tailor-message");
      if (message) message.textContent = error instanceof Error ? error.message : "Documents could not be generated.";
      if (resultState) resultState.textContent = "Generation needs attention";
    }
  };

  const renderResult = (result, { autoGenerate = true } = {}) => {
    latestMatch = result;
    if (workspace instanceof HTMLElement) workspace.dataset.hasResult = "true";
    if (resultShell instanceof HTMLElement) resultShell.hidden = false;
    if (resultPanel instanceof HTMLElement) resultPanel.hidden = false;
    if (resultState) resultState.textContent = result.match_label;
    const score = document.querySelector("#match-score");
    const label = document.querySelector("#match-label");
    const marker = document.querySelector("#match-score-marker");
    const verdict = document.querySelector("#match-verdict");
    const reference = document.querySelector("#match-reference");
    if (score) score.textContent = String(result.match_percentage);
    if (label) label.textContent = result.match_label;
    if (marker instanceof HTMLElement) marker.style.left = `${Math.max(1, Math.min(99, result.match_percentage))}%`;
    if (verdict) verdict.textContent = result.reasons[0] || "Analysis complete.";
    if (reference) reference.textContent = result.id;
    fillList("#match-reasons", result.reasons.slice(1), "The percentage reflects the priority language supported by this resume.");
    fillKeywords("#match-keywords", result.matched_keywords, "No direct evidence found");
    fillList("#match-evidence", result.evidence_highlights, "No strong evidence passage was found in this resume.");
    fillKeywords("#missing-keywords", result.missing_keywords, "No priority gaps found");
    fillList("#match-recommendations", result.recommendations, "Keep every claim tied to evidence you can verify.");

    const existingDocuments = Array.isArray(result.documents) ? result.documents : [];
    renderDownloads(existingDocuments);
    if (tailorBlock instanceof HTMLElement) tailorBlock.hidden = result.match_state === "no_match";
    if (generateButton instanceof HTMLButtonElement) {
      generateButton.hidden = existingDocuments.length > 0;
      generateButton.disabled = false;
      generateButton.firstChild.textContent = "Generate tailored resume ";
    }
    const tailorMessage = document.querySelector("#tailor-message");
    if (tailorMessage) {
      tailorMessage.textContent = existingDocuments.length
        ? "Your saved evidence-grounded Word and PDF files are ready."
        : result.match_state === "match"
        ? "Strong fit found. Forge is creating both formats now."
        : "Forge can prioritize supported evidence without adding claims.";
    }
    resultPanel?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (autoGenerate && result.match_state === "match" && !existingDocuments.length) generateTailored();
  };

  historyList?.addEventListener("click", async (event) => {
    const target = event.target;
    const item = target instanceof Element ? target.closest("[data-match-id]") : null;
    if (!(item instanceof HTMLButtonElement) || !item.dataset.matchId) return;
    item.disabled = true;
    try {
      const result = await api(`/api/v1/job-matches/${item.dataset.matchId}`);
      renderResult(result, { autoGenerate: false });
      setStatus(`Opened saved ${result.match_label.toLowerCase()} analysis from ${historyDate.format(new Date(result.created_at))}.`, "success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The saved match could not be opened.", "error");
    } finally {
      item.disabled = false;
    }
  });

  if (description instanceof HTMLTextAreaElement) {
    description.addEventListener("input", () => {
      if (count) count.textContent = String(description.value.length);
    });
  }
  if (fileInput instanceof HTMLInputElement) fileInput.addEventListener("change", renderFiles);
  if (dropZone instanceof HTMLElement && fileInput instanceof HTMLInputElement) {
    ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.dataset.dragging = "true";
    }));
    ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, () => delete dropZone.dataset.dragging));
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      if (!event.dataTransfer?.files.length) return;
      const transfer = new DataTransfer();
      Array.from(event.dataTransfer.files).slice(0, 5).forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
      renderFiles();
    });
  }

  if (generateButton instanceof HTMLButtonElement) generateButton.addEventListener("click", generateTailored);
  if (form instanceof HTMLFormElement) form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const selectedFiles = fileInput instanceof HTMLInputElement
      ? Array.from(fileInput.files || [])
      : [];
    values.delete("files");
    selectedFiles.forEach((file) => values.append("files", file));
    const hasText = String(values.get("job_description") || "").trim().length > 0;
    const hasFiles = selectedFiles.some((file) => file.size > 0);
    if (!hasText && !hasFiles) {
      setStatus("Paste the job description or attach at least one readable file.", "error");
      description?.focus();
      return;
    }
    if (submitButton instanceof HTMLButtonElement) submitButton.disabled = true;
    setStatus("Extracting the role and comparing it with your resume evidence…");
    if (resultState) resultState.textContent = "Analyzing evidence";
    try {
      const result = await api("/api/v1/job-matches", { method: "POST", body: values });
      renderResult(result);
      loadHistory();
      setStatus(`${result.match_label}: ${result.match_percentage}% evidence coverage.`, "success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The match could not be analyzed.", "error");
      if (resultState) resultState.textContent = "Needs attention";
    } finally {
      if (submitButton instanceof HTMLButtonElement) submitButton.disabled = false;
    }
  });

  loadResumes();
  loadHistory();
}
