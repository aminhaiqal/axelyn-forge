const forgeForm = document.querySelector("#forge-brief-form");

if (forgeForm instanceof HTMLFormElement) {
  const apiBase = (forgeForm.dataset.apiBase || "").replace(/\/$/, "");
  const status = document.querySelector("#forge-form-status");
  const submitButton = forgeForm.querySelector("button[type='submit']");
  const jobDescription = forgeForm.elements.namedItem("job_description");
  const careerEvidence = forgeForm.elements.namedItem("career_evidence");
  const targetRole = forgeForm.elements.namedItem("target_role");
  const consent = forgeForm.elements.namedItem("consent");
  const jdCount = document.querySelector("#jd-count");
  const evidenceCount = document.querySelector("#evidence-count");
  const progressFill = document.querySelector("#rail-progress-fill");
  const briefEmpty = document.querySelector("#brief-empty");
  const briefResult = document.querySelector("#brief-result");
  const briefState = document.querySelector("#brief-state");
  let latestBrief = null;

  const updateProgress = () => {
    if (!(jobDescription instanceof HTMLTextAreaElement)
      || !(careerEvidence instanceof HTMLTextAreaElement)
      || !(targetRole instanceof HTMLInputElement)) return;

    if (jdCount) jdCount.textContent = String(jobDescription.value.length);
    if (evidenceCount) evidenceCount.textContent = String(careerEvidence.value.length);

    const outputs = forgeForm.querySelectorAll("input[name='outputs']:checked").length;
    const targetReady = targetRole.value.trim().length >= 2 && jobDescription.value.trim().length >= 100;
    const evidenceReady = careerEvidence.value.trim().length >= 100;
    const ready = targetReady && evidenceReady && outputs > 0 && consent instanceof HTMLInputElement && consent.checked;
    const completion = [targetReady, evidenceReady, outputs > 0, consent instanceof HTMLInputElement && consent.checked]
      .filter(Boolean).length;

    document.querySelector("[data-step='target']")?.setAttribute("data-state", targetReady ? "complete" : "current");
    document.querySelector("[data-step='evidence']")?.setAttribute("data-state", evidenceReady ? "complete" : targetReady ? "current" : "pending");
    document.querySelector("[data-step='brief']")?.setAttribute("data-state", latestBrief ? "complete" : ready ? "current" : "pending");
    if (progressFill instanceof HTMLElement) progressFill.style.height = `${completion * 25}%`;
  };

  const fillList = (selector, values, fallback) => {
    const list = document.querySelector(selector);
    if (!(list instanceof HTMLElement)) return;
    list.replaceChildren();
    const items = values.length ? values : [fallback];
    items.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      if (!values.length) item.dataset.empty = "true";
      list.append(item);
    });
  };

  const renderBrief = (brief) => {
    latestBrief = brief;
    if (briefEmpty instanceof HTMLElement) briefEmpty.hidden = true;
    if (briefResult instanceof HTMLElement) briefResult.hidden = false;
    if (briefState) briefState.textContent = "Brief ready";

    const score = document.querySelector("#brief-score");
    const scoreFill = document.querySelector("#brief-score-fill");
    const scoreLabel = document.querySelector("#brief-score-label");
    const reference = document.querySelector("#brief-reference");
    if (score) score.textContent = String(brief.coverage_score);
    if (scoreFill instanceof HTMLElement) scoreFill.style.width = `${brief.coverage_score}%`;
    if (scoreLabel) {
      scoreLabel.textContent = brief.coverage_score >= 70
        ? "Strong source overlap"
        : brief.coverage_score >= 40
          ? "Useful evidence, with gaps"
          : "Evidence needs development";
    }
    if (reference) reference.textContent = brief.id;

    fillList("#matched-keywords", brief.matched_keywords, "No direct matches found");
    fillList("#gap-keywords", brief.gap_keywords, "No priority gaps found");
    fillList("#evidence-highlights", brief.evidence_highlights, "Add more detailed evidence to identify a lead passage.");
    fillList("#brief-recommendations", brief.recommendations, "Keep every claim tied to evidence.");
    updateProgress();
    briefResult?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  forgeForm.addEventListener("input", updateProgress);
  forgeForm.addEventListener("change", updateProgress);
  updateProgress();

  forgeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(forgeForm);
    const outputs = data.getAll("outputs");
    const payload = {
      target_role: data.get("target_role"),
      company: data.get("company") || null,
      job_description: data.get("job_description"),
      career_evidence: data.get("career_evidence"),
      outputs,
      consent: data.get("consent") === "on",
    };

    if (!outputs.length) {
      if (status) {
        status.dataset.state = "error";
        status.textContent = "Choose at least one output focus.";
      }
      return;
    }

    if (status) {
      status.dataset.state = "pending";
      status.textContent = "Mapping role language to your evidence…";
    }
    if (briefState) briefState.textContent = "Forging brief";
    if (submitButton instanceof HTMLButtonElement) submitButton.disabled = true;

    try {
      const response = await fetch(`${apiBase}/api/v1/forge-briefs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = Array.isArray(result?.detail)
          ? result.detail[0]?.msg
          : result?.detail;
        throw new Error(typeof detail === "string" ? detail.replace(/^Value error, /, "") : "Check the source material and try again.");
      }
      renderBrief(result);
      if (status) {
        status.dataset.state = "success";
        status.textContent = "Evidence brief ready.";
      }
    } catch (error) {
      if (briefState) briefState.textContent = "Needs attention";
      if (status) {
        status.dataset.state = "error";
        status.textContent = error instanceof Error ? error.message : "The brief could not be built. Try again.";
      }
    } finally {
      if (submitButton instanceof HTMLButtonElement) submitButton.disabled = false;
    }
  });

  document.querySelector("#download-brief")?.addEventListener("click", () => {
    if (!latestBrief) return;
    const section = (title, values) => `## ${title}\n\n${values.map((value) => `- ${value}`).join("\n") || "- None"}`;
    const markdown = [
      "# Axelyn Forge evidence brief",
      `**Target:** ${latestBrief.target_role}${latestBrief.company ? ` at ${latestBrief.company}` : ""}`,
      `**Reference:** ${latestBrief.id}`,
      `**Evidence coverage:** ${latestBrief.coverage_score}%`,
      section("Supported language", latestBrief.matched_keywords),
      section("Needs verification", latestBrief.gap_keywords),
      section("Evidence to lead with", latestBrief.evidence_highlights),
      section("Document direction", latestBrief.recommendations),
      "_Generated from user-supplied evidence. Verify every claim before use._",
    ].join("\n\n");
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `axelyn-forge-${latestBrief.id}.md`;
    link.click();
    URL.revokeObjectURL(url);
  });

  document.querySelector("#start-new-brief")?.addEventListener("click", () => {
    forgeForm.reset();
    latestBrief = null;
    if (briefEmpty instanceof HTMLElement) briefEmpty.hidden = false;
    if (briefResult instanceof HTMLElement) briefResult.hidden = true;
    if (briefState) briefState.textContent = "Waiting for evidence";
    if (status) {
      status.removeAttribute("data-state");
      status.textContent = "No claims are generated at this step.";
    }
    updateProgress();
    targetRole?.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}
