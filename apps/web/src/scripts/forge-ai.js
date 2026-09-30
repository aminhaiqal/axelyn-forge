const forgePage = document.querySelector(".forge-page");

if (forgePage instanceof HTMLElement) {
  const apiBase = (forgePage.dataset.apiBase || "").replace(/\/$/, "");
  const matchSelect = document.querySelector("#forge-match-select");
  const openButton = document.querySelector("#forge-open-case");
  const startStatus = document.querySelector("#forge-start-status");
  const workbench = document.querySelector("#forge-workbench");
  const threadList = document.querySelector("#forge-thread-list");
  const threadCount = document.querySelector("#forge-thread-count");
  const transcript = document.querySelector("#forge-transcript");
  const composer = document.querySelector("#forge-composer");
  const messageInput = document.querySelector("#forge-message");
  const sendButton = document.querySelector("#forge-send-message");
  const messageStatus = document.querySelector("#forge-message-status");
  const toolButtons = Array.from(document.querySelectorAll("[data-forge-tool]"));
  const buildButton = document.querySelector("#forge-build-resume");
  const outputMessage = document.querySelector("#forge-output-message");
  const outputResult = document.querySelector("#forge-output-result");
  const outputScore = document.querySelector("#forge-output-score");
  const outputOverview = document.querySelector("#forge-output-overview");
  const outputDownloads = document.querySelector("#forge-output-downloads");
  const outputOperations = document.querySelector("#forge-output-operations");
  let matches = [];
  let threads = [];
  let activeThread = null;

  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {
      credentials: "same-origin",
      ...options,
    });
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

  const setStatus = (element, message, state = "") => {
    if (!(element instanceof HTMLElement)) return;
    element.textContent = message;
    if (state) element.dataset.state = state;
    else element.removeAttribute("data-state");
  };

  const readableDate = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  const formatDate = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : readableDate.format(date);
  };

  const renderMatchSelect = () => {
    if (!(matchSelect instanceof HTMLSelectElement)) return;
    const selected = matchSelect.value;
    matchSelect.replaceChildren();
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = matches.length ? "Choose a saved job match" : "No saved job matches yet";
    matchSelect.append(prompt);
    matches.forEach((match) => {
      const option = document.createElement("option");
      option.value = match.id;
      option.textContent = `${match.target_role}${match.company ? ` · ${match.company}` : ""} — ${match.match_percentage}%`;
      matchSelect.append(option);
    });
    const requestedMatch = new URLSearchParams(window.location.search).get("match");
    const nextValue = [selected, requestedMatch, matches[0]?.id].find((candidate) =>
      candidate && matches.some((match) => match.id === candidate)
    );
    matchSelect.value = nextValue || "";
    if (openButton instanceof HTMLButtonElement) openButton.disabled = !matches.length;
    updateOpenButton();
  };

  const updateOpenButton = () => {
    if (!(matchSelect instanceof HTMLSelectElement) || !(openButton instanceof HTMLButtonElement)) return;
    const existing = threads.find((thread) => thread.match_id === matchSelect.value);
    openButton.firstChild.textContent = existing ? "Continue evidence review " : "Open evidence review ";
  };

  const renderThreads = () => {
    if (!(threadList instanceof HTMLElement)) return;
    threadList.replaceChildren();
    if (threadCount) threadCount.textContent = String(threads.length);
    if (!threads.length) {
      const empty = document.createElement("p");
      empty.className = "forge-thread-empty";
      empty.textContent = "Choose a saved match to open your first evidence case.";
      threadList.append(empty);
      return;
    }
    threads.forEach((thread) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "forge-thread-item";
      button.dataset.threadId = thread.id;
      button.dataset.active = activeThread?.id === thread.id ? "true" : "false";

      const date = document.createElement("span");
      date.textContent = formatDate(thread.updated_at);
      const role = document.createElement("strong");
      role.textContent = thread.target_role;
      const context = document.createElement("small");
      context.textContent = `${thread.company || "Company not specified"} · ${thread.resume_name}`;
      const score = document.createElement("i");
      score.textContent = `${thread.current_score}% · ${thread.message_count} ${thread.message_count === 1 ? "entry" : "entries"}`;
      button.append(date, role, context, score);
      threadList.append(button);
    });
  };

  const renderLedgerEntries = (selector, values, fallback) => {
    const container = document.querySelector(selector);
    if (!(container instanceof HTMLElement)) return;
    container.replaceChildren();
    if (!values.length) {
      const item = document.createElement("p");
      item.className = "forge-ledger-entry";
      item.dataset.empty = "true";
      item.textContent = fallback;
      container.append(item);
      return;
    }
    values.forEach((value) => {
      const item = document.createElement("p");
      item.className = "forge-ledger-entry";
      item.textContent = typeof value === "string" ? value : value.fact;
      container.append(item);
      if (typeof value !== "string") {
        const source = document.createElement("small");
        source.className = "forge-fact-source";
        source.textContent = value.source === "resume"
          ? `Resume source${value.evidence_ids.length ? ` · ${value.evidence_ids.join(", ")}` : ""}`
          : "Confirmed by you · source document still recommended";
        container.append(source);
      }
    });
  };

  const renderGaps = (values) => {
    const container = document.querySelector("#forge-missing-keywords");
    if (!(container instanceof HTMLElement)) return;
    container.replaceChildren();
    const gaps = values.length ? values : ["No priority keyword gaps in the current record"];
    gaps.forEach((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      container.append(item);
    });
  };

  const claimLabel = (status) => ({
    verified: "Resume verified",
    user_confirmed: "User confirmed",
    needs_evidence: "Evidence needed",
    gap: "Confirmed gap",
  })[status] || "Evidence review";

  const appendInlineFormatting = (element, value) => {
    const parts = value.split(/(\*\*[^*]+\*\*)/g);
    parts.forEach((part) => {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        const strong = document.createElement("strong");
        strong.textContent = part.slice(2, -2);
        element.append(strong);
      } else if (part) {
        element.append(document.createTextNode(part));
      }
    });
  };

  const renderAssistantText = (container, value) => {
    const clean = value.replace(
      /\s*\[(?=[^\]]*(?:legacy_|experience_|project_|skills_|profile_|education_|custom_))[^\]]+\]/gi,
      "",
    );
    let list = null;
    clean.split(/\r?\n/).forEach((rawLine) => {
      const line = rawLine.trim();
      if (!line) {
        list = null;
        return;
      }
      if (/^[-*•]\s+/.test(line)) {
        if (!(list instanceof HTMLUListElement)) {
          list = document.createElement("ul");
          container.append(list);
        }
        const item = document.createElement("li");
        appendInlineFormatting(item, line.replace(/^[-*•]\s+/, ""));
        list.append(item);
        return;
      }
      list = null;
      const paragraph = document.createElement("p");
      appendInlineFormatting(paragraph, line);
      container.append(paragraph);
    });
  };

  const renderMessages = (messages) => {
    if (!(transcript instanceof HTMLElement)) return;
    transcript.replaceChildren();
    messages.forEach((message) => {
      const article = document.createElement("article");
      article.className = "forge-message";
      article.dataset.role = message.role;

      const meta = document.createElement("div");
      meta.className = "forge-message-meta";
      const author = document.createElement("strong");
      author.textContent = message.role === "assistant" ? "Forge AI" : "You";
      const date = document.createElement("span");
      date.textContent = formatDate(message.created_at);
      meta.append(author, date);

      const body = document.createElement("div");
      body.className = "forge-message-content";
      if (message.role === "assistant") {
        renderAssistantText(body, message.content);
      } else {
        const content = document.createElement("p");
        content.textContent = message.content;
        body.append(content);
      }
      if (message.role === "assistant") {
        const status = document.createElement("span");
        status.className = "forge-claim-status";
        status.dataset.status = message.claim_status;
        status.textContent = claimLabel(message.claim_status);
        body.append(status);
      }
      if (message.citations.length) {
        const citations = document.createElement("div");
        citations.className = "forge-citations";
        citations.setAttribute("aria-label", "Resume evidence cited");
        const labelCounts = message.citations.reduce((counts, citation) => {
          counts.set(citation.label, (counts.get(citation.label) || 0) + 1);
          return counts;
        }, new Map());
        const labelIndexes = new Map();
        message.citations.forEach((citation) => {
          const item = document.createElement("span");
          const nextIndex = (labelIndexes.get(citation.label) || 0) + 1;
          labelIndexes.set(citation.label, nextIndex);
          item.textContent = labelCounts.get(citation.label) > 1
            ? `${citation.label} · evidence ${nextIndex}`
            : citation.label;
          item.title = citation.id;
          citations.append(item);
        });
        body.append(citations);
      }
      article.append(meta, body);
      transcript.append(article);
    });
  };

  const renderDocumentLinks = (documents) => {
    if (!(outputDownloads instanceof HTMLElement)) return;
    outputDownloads.replaceChildren();
    documents.forEach((documentItem) => {
      const link = document.createElement("a");
      const format = documentItem.media_type === "application/pdf" ? "PDF" : "Word";
      link.href = `${apiBase}/api/v1/job-match-documents/${encodeURIComponent(documentItem.id)}/download`;
      link.download = documentItem.filename;
      link.textContent = `Download enhanced ${format}`;
      outputDownloads.append(link);
    });
  };

  const renderSavedEnhancements = (documents) => {
    const enhanced = (documents || []).filter((documentItem) =>
      documentItem.filename.includes("forge-enhanced-resume")
    );
    if (!(outputResult instanceof HTMLElement)) return;
    if (!enhanced.length) {
      outputResult.hidden = true;
      return;
    }
    outputResult.hidden = false;
    if (outputScore) outputScore.textContent = "Saved";
    if (outputOverview) outputOverview.textContent = "Your latest enhanced Word and PDF files remain available in this evidence case.";
    renderDocumentLinks(enhanced.slice(0, 2));
    if (outputOperations instanceof HTMLElement) outputOperations.replaceChildren();
  };

  const renderEnhancement = (enhancement) => {
    if (!(outputResult instanceof HTMLElement)) return;
    outputResult.hidden = false;
    if (outputScore) outputScore.textContent = `${enhancement.projected_score}%`;
    if (outputOverview) {
      const sections = enhancement.changed_sections.length
        ? ` Changed: ${enhancement.changed_sections.join(", ")}.`
        : "";
      outputOverview.textContent = `${enhancement.overview}${sections}`;
    }
    renderDocumentLinks(enhancement.documents);
    if (!(outputOperations instanceof HTMLElement)) return;
    outputOperations.replaceChildren();
    enhancement.operations.forEach((operation) => {
      const item = document.createElement("article");
      item.className = "forge-operation";
      const heading = document.createElement("strong");
      heading.textContent = `${operation.section} · ${operation.target}`;
      const value = document.createElement("p");
      value.textContent = Array.isArray(operation.after)
        ? operation.after.join(", ")
        : operation.after;
      const evidence = document.createElement("small");
      evidence.textContent = `Evidence: ${operation.evidence.map((source) => `${source.label}${source.source === "user_confirmed" ? " (confirmed by you)" : ""}`).join(" · ")}`;
      item.append(heading, value, evidence);
      outputOperations.append(item);
    });
  };

  const renderThread = (thread, { scroll = false } = {}) => {
    activeThread = thread;
    if (workbench instanceof HTMLElement) workbench.hidden = false;
    const role = document.querySelector("#forge-case-role");
    const context = document.querySelector("#forge-case-context");
    const memoryVersion = document.querySelector("#forge-memory-version");
    const currentScore = document.querySelector("#forge-current-score");
    const scoreStatus = document.querySelector("#forge-score-status");
    const conversationState = document.querySelector("#forge-conversation-state");
    const ledgerCount = document.querySelector("#forge-ledger-count");
    const progress = document.querySelector("#forge-progress");
    if (role) role.textContent = thread.target_role;
    if (context) context.textContent = `${thread.company || "Company not specified"} · ${thread.resume_name}`;
    if (memoryVersion) memoryVersion.textContent = `v${thread.memory_version}`;
    if (currentScore) currentScore.textContent = String(thread.current_score);
    if (conversationState) conversationState.textContent = thread.status === "ready" ? "Threshold met" : "Evidence review active";
    if (ledgerCount) ledgerCount.textContent = `${thread.memory.confirmed_facts.length} ${thread.memory.confirmed_facts.length === 1 ? "fact" : "facts"}`;
    if (scoreStatus) {
      scoreStatus.textContent = thread.current_score >= 80
        ? "The current record clears 80%. Every final statement still needs to remain defensible."
        : `${80 - thread.current_score} points remain. Forge AI will stop below 80% if the facts do not support more.`;
    }
    if (progress instanceof HTMLElement) {
      progress.style.setProperty("--forge-score", `${Math.max(0, Math.min(100, thread.current_score))}%`);
      progress.style.setProperty("--forge-baseline", `${Math.max(0, Math.min(100, thread.baseline_score))}%`);
    }
    renderMessages(thread.messages);
    renderLedgerEntries("#forge-confirmed-facts", thread.memory.confirmed_facts, "No new facts have been confirmed in this discussion yet.");
    renderLedgerEntries("#forge-open-questions", thread.memory.open_questions, "No open evidence questions.");
    renderLedgerEntries("#forge-rejected-claims", thread.memory.rejected_claims, "No rejected claims are recorded.");
    renderGaps(thread.missing_keywords);
    renderSavedEnhancements(thread.documents);
    renderThreads();
    history.replaceState({}, "", `${window.location.pathname}?thread=${encodeURIComponent(thread.id)}`);
    if (scroll) workbench?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const loadThread = async (threadId, options = {}) => {
    const thread = await api(`/api/v1/forge-ai/threads/${encodeURIComponent(threadId)}`);
    renderThread(thread, options);
    return thread;
  };

  const loadThreads = async () => {
    threads = await api("/api/v1/forge-ai/threads");
    renderThreads();
    updateOpenButton();
  };

  const openSelectedMatch = async () => {
    if (!(matchSelect instanceof HTMLSelectElement) || !(openButton instanceof HTMLButtonElement)) return;
    if (!matchSelect.value) {
      setStatus(startStatus, "Choose a saved match first.", "error");
      matchSelect.focus();
      return;
    }
    openButton.disabled = true;
    setStatus(startStatus, "Opening the job description, resume snapshot, and evidence record…");
    try {
      const existing = threads.find((thread) => thread.match_id === matchSelect.value);
      const thread = existing
        ? await loadThread(existing.id)
        : await api("/api/v1/forge-ai/threads", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ match_id: matchSelect.value }),
          });
      renderThread(thread, { scroll: true });
      await loadThreads();
      setStatus(startStatus, existing ? "Evidence review reopened." : "Evidence review created. The original resume remains unchanged.", "success");
    } catch (error) {
      setStatus(startStatus, error instanceof Error ? error.message : "The evidence review could not be opened.", "error");
    } finally {
      openButton.disabled = false;
      updateOpenButton();
    }
  };

  threadList?.addEventListener("click", async (event) => {
    const target = event.target;
    const button = target instanceof Element ? target.closest("[data-thread-id]") : null;
    if (!(button instanceof HTMLButtonElement) || !button.dataset.threadId) return;
    button.disabled = true;
    try {
      await loadThread(button.dataset.threadId, { scroll: true });
      setStatus(startStatus, "Saved evidence review reopened.", "success");
    } catch (error) {
      setStatus(startStatus, error instanceof Error ? error.message : "The saved discussion could not be opened.", "error");
    } finally {
      button.disabled = false;
    }
  });

  matchSelect?.addEventListener("change", updateOpenButton);
  openButton?.addEventListener("click", openSelectedMatch);

  if (composer instanceof HTMLFormElement) {
    composer.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!activeThread || !(messageInput instanceof HTMLTextAreaElement) || !(sendButton instanceof HTMLButtonElement)) return;
      const content = messageInput.value.trim();
      if (!content) {
        setStatus(messageStatus, "Write a fact, correction, or question before submitting.", "error");
        messageInput.focus();
        return;
      }
      sendButton.disabled = true;
      messageInput.disabled = true;
      toolButtons.forEach((button) => { button.disabled = true; });
      const hasPublicLink = /https?:\/\/[^\s<>"']+/i.test(content);
      setStatus(
        messageStatus,
        hasPublicLink
          ? "Reading the linked website, separating public context from your responsibilities, and testing the evidence…"
          : "Testing your statement against the role and saved evidence…",
        "pending",
      );
      try {
        const updated = await api(`/api/v1/forge-ai/threads/${encodeURIComponent(activeThread.id)}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        });
        messageInput.value = "";
        renderThread(updated);
        await loadThreads();
        setStatus(
          messageStatus,
          hasPublicLink
            ? "The public website context and your own stated responsibilities were assessed separately. The full exchange is saved."
            : "The full exchange is saved. Working memory was compressed without discarding the transcript.",
        );
        transcript?.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (error) {
        setStatus(messageStatus, error instanceof Error ? error.message : "Forge AI could not assess that evidence.", "error");
      } finally {
        sendButton.disabled = false;
        messageInput.disabled = false;
        toolButtons.forEach((button) => { button.disabled = false; });
        messageInput.focus();
      }
    });
  }

  toolButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (!activeThread || !(messageInput instanceof HTMLTextAreaElement) || !(composer instanceof HTMLFormElement)) return;
      messageInput.value = button.dataset.forgeTool || "";
      composer.requestSubmit();
    });
  });

  if (buildButton instanceof HTMLButtonElement) {
    buildButton.addEventListener("click", async () => {
      if (!activeThread) return;
      buildButton.disabled = true;
      buildButton.firstChild.textContent = "Building evidence-cited resume ";
      setStatus(outputMessage, "Reviewing every editable line, applying supported rewrites, and rendering Word and PDF…", "pending");
      try {
        const enhancement = await api(`/api/v1/forge-ai/threads/${encodeURIComponent(activeThread.id)}/enhance`, {
          method: "POST",
        });
        renderEnhancement(enhancement);
        activeThread.documents = [...enhancement.documents, ...(activeThread.documents || [])];
        setStatus(outputMessage, `Enhanced resume created from ${enhancement.operations.length} audited ${enhancement.operations.length === 1 ? "change" : "changes"}. The uploaded source was not modified.`, "success");
        outputResult?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (error) {
        setStatus(outputMessage, error instanceof Error ? error.message : "The enhanced resume could not be built.", "error");
      } finally {
        buildButton.disabled = false;
        buildButton.firstChild.textContent = "Build DOCX + PDF ";
      }
    });
  }

  const initialize = async () => {
    try {
      [matches, threads] = await Promise.all([
        api("/api/v1/job-matches"),
        api("/api/v1/forge-ai/threads"),
      ]);
      renderMatchSelect();
      renderThreads();
      if (!matches.length) {
        setStatus(startStatus, "Run a job match first. Forge AI needs a fixed role and resume record.");
      }
      const requestedThread = new URLSearchParams(window.location.search).get("thread");
      if (requestedThread && threads.some((thread) => thread.id === requestedThread)) {
        await loadThread(requestedThread);
      }
    } catch (error) {
      if (matchSelect instanceof HTMLSelectElement) matchSelect.innerHTML = '<option value="">Evidence workspace unavailable</option>';
      if (openButton instanceof HTMLButtonElement) openButton.disabled = true;
      setStatus(startStatus, error instanceof Error ? error.message : "Forge AI could not load your private workspace.", "error");
    }
  };

  initialize();
}
