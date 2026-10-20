// IncuBrix EditStudio — Core Frontend Engine
// IncuBrix 2027 Graduate Hiring Assessment | Problem Statement 2

// Every UI write gets a unique retry key. Replays of the same fetch retain it,
// while a new user action receives a new key.
const incuBrixNativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
  const requestMethod = input instanceof Request ? input.method : "GET";
  const method = String(init.method || requestMethod).toUpperCase();
  const requestUrl = typeof input === "string" ? input : input.url;
  if (requestUrl.includes("/api/v1/") && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    if (!headers.has("Idempotency-Key")) {
      const key = globalThis.crypto?.randomUUID?.()
        || `ui_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      headers.set("Idempotency-Key", key);
    }
    init = { ...init, headers };
  }
  return incuBrixNativeFetch(input, init);
};

// State Management
let currentMediaId = null;
let currentTimeline = null;
let currentProjectId = null;
let currentPendingPlan = null;
let currentRenderJob = null;
let lastRenderedUrl = null;
let lastRenderedManifest = null;
let isComparingRendered = false;
let instructionProvider = "rules";

let activeClarificationSessionId = null;
let currentSelectedWord = null;
let showFlaggedOnly = false;
let currentEditingClipId = null;
let draggedSegmentId = null;
let lastClipDragAt = 0;

// DOM Elements: Navigation & Views
const landingScreenEl = document.getElementById("landing-screen");
const mainAppLayoutEl = document.getElementById("main-app-layout");
const btnHeroStart = document.getElementById("btn-hero-start");
const btnHeroStartNav = document.getElementById("btn-hero-start-nav");
const btnHeroDemo = document.getElementById("btn-hero-demo");
const btnHeroDemoNav = document.getElementById("btn-hero-demo-nav");
const btnHeroProjects = document.getElementById("btn-hero-projects");
const btnBackToLanding = document.getElementById("btn-back-to-landing");
const btnLoadDemoInline = document.getElementById("btn-load-demo-inline");

// Project Manager Modal
const projectModalEl = document.getElementById("project-modal");
const btnCloseProjectModal = document.getElementById("btn-close-project-modal");
const btnOpenProjectManager = document.getElementById("btn-open-project-manager");
const projectNameInput = document.getElementById("project-name-input");
const btnConfirmCreateProject = document.getElementById("btn-confirm-create-project");
const btnRefreshProjects = document.getElementById("btn-refresh-projects");
const recentProjectsList = document.getElementById("recent-projects-list");
const activeProjectNameEl = document.getElementById("active-project-name");

// Header & Global Controls
const serviceStatusEl = document.getElementById("service-status-text");
const serviceDotEl = document.querySelector(".status-dot");
const btnCompareToggle = document.getElementById("btn-compare-toggle");
const compareBtnText = document.getElementById("compare-btn-text");
const undoBtn = document.getElementById("btn-undo");
const redoBtn = document.getElementById("btn-redo");
const renderBtn = document.getElementById("btn-render");
const exportOtioBtn = document.getElementById("btn-export-otio");

// Media & Source Panel
const uploadZoneEl = document.getElementById("upload-zone");
const fileInputEl = document.getElementById("file-input");
const videoWrapperEl = document.getElementById("video-wrapper");
const videoPlayerEl = document.getElementById("video-player");
const videoModeIndicator = document.getElementById("video-mode-indicator");
const canvasRatioPill = document.getElementById("canvas-ratio-pill");
const mediaIdTagEl = document.getElementById("media-id-tag");

// Metadata Cards
const metadataCardEl = document.getElementById("media-metadata-card");
const activePropsCardEl = document.getElementById("active-properties-card");
const metaHashEl = document.getElementById("meta-hash");
const metaDurationEl = document.getElementById("meta-duration");
const metaResolutionEl = document.getElementById("meta-resolution");
const metaFpsEl = document.getElementById("meta-fps");
const metaAudioEl = document.getElementById("meta-audio");

const propAspectEl = document.getElementById("prop-aspect");
const propColorEl = document.getElementById("prop-color");
const propCaptionsEl = document.getElementById("prop-captions");
const propDuckingEl = document.getElementById("prop-ducking");
const historyListEl = document.getElementById("history-list");
const historyCountEl = document.getElementById("history-count");

// Instruction & AI Plan
const instructionInputEl = document.getElementById("instruction-input");
const btnGeneratePlan = document.getElementById("btn-generate-plan");
const submitInstructionBtn = document.getElementById("btn-submit-instruction");
const timelineRevTagEl = document.getElementById("timeline-revision-tag");
const timelineDurationBadge = document.getElementById("timeline-duration-badge");

const aiPlanCardEl = document.getElementById("ai-plan-card");
const planTargetDurEl = document.getElementById("plan-target-dur");
const planAspectPillEl = document.getElementById("plan-aspect-pill");
const planPromptSummaryEl = document.getElementById("plan-prompt-summary");
const planProviderNoticeEl = document.getElementById("plan-provider-notice");
const planOperationsListEl = document.getElementById("plan-operations-list");
const btnDismissPlan = document.getElementById("btn-dismiss-plan");
const btnCancelPlan = document.getElementById("btn-cancel-plan");
const btnApprovePlan = document.getElementById("btn-approve-plan");

// Outcomes & Clarifications
const outcomeCardEl = document.getElementById("outcome-card");
const outcomeBadgeEl = document.getElementById("outcome-badge");
const outcomeHashEl = document.getElementById("outcome-hash");
const outcomeMsgEl = document.getElementById("outcome-message");
const clarificationBoxEl = document.getElementById("clarification-container");
const clarQuestionEl = document.getElementById("clarification-question");
const clarOptionsListEl = document.getElementById("clarification-options");
const outcomeSummaryEl = document.getElementById("outcome-summary");
const summaryBeforeDurEl = document.getElementById("summary-before-dur");
const summaryAfterDurEl = document.getElementById("summary-after-dur");

// Multi-Track Timeline
const trackVideoEl = document.getElementById("track-video");
const trackAudioEl = document.getElementById("track-audio");
const trackCaptionsEl = document.getElementById("track-captions");
const trackTitlesEl = document.getElementById("track-titles");
const timelineDurationEl = document.getElementById("timeline-duration");
const timelineClipCountEl = document.getElementById("timeline-clip-count");

// Transcript Studio
const transcriptFileInputEl = document.getElementById("transcript-file-input");
const voiceoverFileInputEl = document.getElementById("voiceover-file-input");
const transcriptWordsContainerEl = document.getElementById("transcript-words-container");
const transcriptCountEl = document.getElementById("transcript-count");
const flaggedCountEl = document.getElementById("flagged-count");
const generateTranscriptBtn = document.getElementById("btn-generate-transcript");
const loadSampleTranscriptBtn = document.getElementById("btn-load-sample-transcript");
const exportFormatSelect = document.getElementById("export-format-select");
const exportTranscriptBtn = document.getElementById("btn-export-transcript");
const transcriptSearchInput = document.getElementById("transcript-search-input");
const searchTranscriptBtn = document.getElementById("btn-search-transcript");
const filterFlaggedBtn = document.getElementById("btn-filter-flagged");

// Inline Word Editor
const wordEditorCard = document.getElementById("word-editor-card");
const closeWordEditorBtn = document.getElementById("btn-close-word-editor");
const editWordText = document.getElementById("edit-word-text");
const editWordStart = document.getElementById("edit-word-start");
const editWordEnd = document.getElementById("edit-word-end");
const editWordSpeaker = document.getElementById("edit-word-speaker");
const saveWordBtn = document.getElementById("btn-save-word");
const deleteWordBtn = document.getElementById("btn-delete-word");

// Captions Studio
const captionFontSizeSlider = document.getElementById("caption-font-size");
const fontSizeValDisplay = document.getElementById("font-size-val");
const captionOutlineWidthSlider = document.getElementById("caption-outline-width");
const outlineWidthValDisplay = document.getElementById("outline-width-val");
const captionShadowSlider = document.getElementById("caption-shadow");
const shadowValDisplay = document.getElementById("shadow-val");
const captionFontFamilySelect = document.getElementById("caption-font-family");
const captionTextColor = document.getElementById("caption-text-color");
const captionOutlineColor = document.getElementById("caption-outline-color");
const captionBgBox = document.getElementById("caption-bg-box");
const captionBgColor = document.getElementById("caption-bg-color");
const captionVerticalPos = document.getElementById("caption-vertical-pos");
const applyCaptionStyleBtn = document.getElementById("btn-apply-caption-style");

// Titles & Audio Studio
const openingTitleText = document.getElementById("opening-title-text");
const openingTitleDur = document.getElementById("opening-title-dur");
const openingTitlePos = document.getElementById("opening-title-pos");
const btnAddOpeningTitle = document.getElementById("btn-add-opening-title");
const closingTitleText = document.getElementById("closing-title-text");
const btnAddClosingTitle = document.getElementById("btn-add-closing-title");
const bgmToggle = document.getElementById("bgm-toggle");
const bgmVolumeSlider = document.getElementById("bgm-volume-slider");
const bgmVolumeVal = document.getElementById("bgm-volume-val");
const bgmDuckingToggle = document.getElementById("bgm-ducking-toggle");
const btnApplyBgm = document.getElementById("btn-apply-bgm");

// Suggestions
const suggestionsContainer = document.getElementById("suggestions-container");
const suggestionBadge = document.getElementById("suggestion-badge");
const refreshSuggestionsBtn = document.getElementById("btn-refresh-suggestions");
const topicSearchInput = document.getElementById("topic-search-input");
const searchTopicBtn = document.getElementById("btn-search-topic");

// Render Progress Modal (Scene 10)
const renderModalEl = document.getElementById("render-modal");
const cancelRenderBtn = document.getElementById("btn-cancel-render");
const renderStageBadge = document.getElementById("render-stage-badge");
const renderStageDesc = document.getElementById("render-stage-desc");
const renderModalProgressFill = document.getElementById("render-modal-progress-fill");
const renderLogText = document.getElementById("render-log-text");

// Export Success Modal (Scene 11)
const exportSuccessModalEl = document.getElementById("export-success-modal");
const finalRenderedPlayer = document.getElementById("final-rendered-player");
const exportFilenameEl = document.getElementById("export-filename");
const exportDurationEl = document.getElementById("export-duration");
const exportResolutionEl = document.getElementById("export-resolution");
const exportSizeEl = document.getElementById("export-size");
const exportVcodecEl = document.getElementById("export-vcodec");
const exportAcodecEl = document.getElementById("export-acodec");
const btnDownloadMp4 = document.getElementById("btn-download-mp4");
const btnViewManifestModal = document.getElementById("btn-view-manifest-modal");
const btnEditAgain = document.getElementById("btn-edit-again");
const btnNewProjectFromExport = document.getElementById("btn-new-project-from-export");
const btnCloseExportModal = document.getElementById("btn-close-export-modal");
const manifestViewerBox = document.getElementById("manifest-viewer-box");
const manifestViewerJson = document.getElementById("manifest-viewer-json");

// Error Modal (Scene 12)
const errorModalEl = document.getElementById("error-modal");
const errorModalTitle = document.getElementById("error-modal-title");
const errorModalDesc = document.getElementById("error-modal-desc");
const btnCloseErrorModal = document.getElementById("btn-close-error-modal");
const btnErrorAction = document.getElementById("btn-error-action");

// Clip Edit Modal
const clipEditModalEl = document.getElementById("clip-edit-modal");
const clipModalIdText = document.getElementById("clip-modal-id-text");
const clipEditStart = document.getElementById("clip-edit-start");
const clipEditEnd = document.getElementById("clip-edit-end");
const clipEditSpeed = document.getElementById("clip-edit-speed");
const btnSaveClip = document.getElementById("btn-save-clip");
const btnDeleteClip = document.getElementById("btn-delete-clip");
const btnCloseClipModal = document.getElementById("btn-close-clip-modal");


// --- Application Initialization ---
document.addEventListener("DOMContentLoaded", async () => {
  await checkReadiness();
  setupNavigation();
  setupEventListeners();
  setupStudioTabs();
});

async function checkReadiness() {
  try {
    const res = await fetch("/api/v1/ready");
    const data = await res.json();
    const provider = data.details?.instruction_provider || "rules";
    instructionProvider = provider;
    if (data.status === "ready") {
      const mediaStatus = data.details?.transcription_library_available
        ? "FFmpeg, Storage & Local Transcription Ready"
        : "FFmpeg & Storage Ready · Local Transcription Not Installed";
      const promptStatus = ["ollama", "auto"].includes(provider)
        ? (data.details?.ollama_available ? "Local Ollama AI Ready" : "Offline Rules · Local AI unavailable")
        : "Offline Rules";
      if (submitInstructionBtn && ["ollama", "auto"].includes(provider)) {
        submitInstructionBtn.title = "Prepare a validated edit preview; approve it to apply timeline changes";
        submitInstructionBtn.innerHTML = "Preview & Review";
      }
      serviceStatusEl.textContent = `${mediaStatus} · ${promptStatus}`;
      serviceDotEl.classList.add("ready");
    } else {
      serviceStatusEl.textContent = "Degraded Engine: Inspect FFmpeg/Storage";
      serviceDotEl.classList.remove("ready");
    }
  } catch (err) {
    serviceStatusEl.textContent = "Offline: Backend Not Reachable";
    serviceDotEl.classList.remove("ready");
  }
}

// --- Navigation & View Switching ---
function showWorkspaceView() {
  landingScreenEl.classList.add("hidden");
  mainAppLayoutEl.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showLandingView() {
  mainAppLayoutEl.classList.add("hidden");
  landingScreenEl.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setupNavigation() {
  if (btnHeroStart) btnHeroStart.addEventListener("click", showWorkspaceView);
  if (btnHeroStartNav) btnHeroStartNav.addEventListener("click", showWorkspaceView);
  if (btnBackToLanding) btnBackToLanding.addEventListener("click", showLandingView);

  if (activeProjectNameEl) {
    activeProjectNameEl.addEventListener("click", async () => {
      if (!currentProjectId) return;
      const requestedName = window.prompt("Rename project", activeProjectNameEl.textContent || "");
      if (requestedName === null) return;
      const name = requestedName.trim();
      if (!name) {
        showErrorModal("Invalid Project Name", "Project name cannot be empty.");
        return;
      }
      try {
        const res = await fetch(`/api/v1/projects/${encodeURIComponent(currentProjectId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        const project = await res.json();
        if (!res.ok) throw new Error(project.detail || "Project rename failed");
        activeProjectNameEl.textContent = project.name;
      } catch (err) {
        showErrorModal("Project Rename Failed", err.message);
      }
    });
  }

  // Demo Project Exploration
  const handleLoadDemo = async () => {
    showWorkspaceView();
    await loadDemoProject();
  };

  if (btnHeroDemo) btnHeroDemo.addEventListener("click", handleLoadDemo);
  if (btnHeroDemoNav) btnHeroDemoNav.addEventListener("click", handleLoadDemo);
  if (btnLoadDemoInline) btnLoadDemoInline.addEventListener("click", handleLoadDemo);

  // Projects Modal
  const openProjects = async () => {
    projectModalEl.classList.remove("hidden");
    await fetchRecentProjects();
  };
  if (btnHeroProjects) btnHeroProjects.addEventListener("click", openProjects);
  if (btnOpenProjectManager) btnOpenProjectManager.addEventListener("click", openProjects);
  if (btnCloseProjectModal) {
    btnCloseProjectModal.addEventListener("click", () => projectModalEl.classList.add("hidden"));
  }

  // Create Project
  if (btnConfirmCreateProject) {
    btnConfirmCreateProject.addEventListener("click", async () => {
      const name = projectNameInput.value.trim() || "Untitled Project";
      try {
        const res = await fetch("/api/v1/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        const proj = await res.json();
        currentProjectId = proj.id;
        currentMediaId = null;
        currentTimeline = null;
        activeProjectNameEl.textContent = proj.name;
        projectModalEl.classList.add("hidden");
        showWorkspaceView();
        uploadZoneEl.classList.remove("hidden");
        videoWrapperEl.classList.add("hidden");
        metadataCardEl.classList.add("hidden");
        activePropsCardEl.classList.add("hidden");
        mediaIdTagEl.textContent = "No Media Loaded";
        videoPlayerEl.removeAttribute("src");
        videoPlayerEl.load();
        disableWorkspaceControls();
      } catch (e) {
        showErrorModal("Project Creation Failed", e.message);
      }
    });
  }

  if (btnRefreshProjects) {
    btnRefreshProjects.addEventListener("click", () => fetchRecentProjects());
  }

  // Error modal dismiss
  if (btnCloseErrorModal) btnCloseErrorModal.addEventListener("click", () => errorModalEl.classList.add("hidden"));
  if (btnErrorAction) btnErrorAction.addEventListener("click", () => errorModalEl.classList.add("hidden"));

  // Clip edit modal dismiss
  if (btnCloseClipModal) btnCloseClipModal.addEventListener("click", () => clipEditModalEl.classList.add("hidden"));
  if (btnCloseExportModal) btnCloseExportModal.addEventListener("click", () => exportSuccessModalEl.classList.add("hidden"));
  if (btnEditAgain) btnEditAgain.addEventListener("click", () => exportSuccessModalEl.classList.add("hidden"));
  if (btnNewProjectFromExport) {
    btnNewProjectFromExport.addEventListener("click", () => {
      exportSuccessModalEl.classList.add("hidden");
      projectModalEl.classList.remove("hidden");
      fetchRecentProjects();
    });
  }
}

async function fetchRecentProjects() {
  if (!recentProjectsList) return;
  recentProjectsList.innerHTML = `<div class="empty-state">Loading saved projects...</div>`;
  try {
    const res = await fetch("/api/v1/projects");
    const projects = await res.json();
    if (!projects || projects.length === 0) {
      recentProjectsList.innerHTML = `<div class="empty-state">No saved projects found. Create a project to begin.</div>`;
      return;
    }
    recentProjectsList.innerHTML = "";
    projects.forEach((p) => {
      const item = document.createElement("div");
      item.className = "project-card-item recent-project-row";
      item.innerHTML = `
        <div class="project-info">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="font-mono text-dim">${p.id}</span>
        </div>
        <div class="project-actions">
          <button class="btn btn-secondary btn-sm project-open">Open</button>
          <button class="btn btn-secondary btn-sm project-duplicate">Duplicate</button>
          <button class="btn btn-secondary btn-sm project-delete">Delete</button>
        </div>
      `;
      item.querySelector(".project-open").addEventListener("click", async () => {
        try {
          const projectRes = await fetch(`/api/v1/projects/${encodeURIComponent(p.id)}`);
          const project = await projectRes.json();
          if (!projectRes.ok) throw new Error(project.detail || "Failed to open project");

          currentProjectId = project.id;
          activeProjectNameEl.textContent = project.name;
          projectModalEl.classList.add("hidden");
          showWorkspaceView();

          if (project.media) {
            currentMediaId = project.media.media_id;
            displayMedia(project.media);
            enableWorkspaceControls();
            await refreshTimeline();
            await fetchSmartSuggestions();
          } else {
            currentMediaId = null;
            currentTimeline = null;
            uploadZoneEl.classList.remove("hidden");
            videoWrapperEl.classList.add("hidden");
            metadataCardEl.classList.add("hidden");
            activePropsCardEl.classList.add("hidden");
            mediaIdTagEl.textContent = "No Media Loaded";
            videoPlayerEl.removeAttribute("src");
            videoPlayerEl.load();
            disableWorkspaceControls();
          }
        } catch (err) {
          showErrorModal("Project Open Failed", err.message);
        }
      });

      item.querySelector(".project-duplicate").addEventListener("click", async () => {
        try {
          const duplicateRes = await fetch(`/api/v1/projects/${encodeURIComponent(p.id)}/duplicate`, { method: "POST" });
          const duplicate = await duplicateRes.json();
          if (!duplicateRes.ok) throw new Error(duplicate.detail || "Project duplication failed");
          await fetchRecentProjects();
        } catch (err) {
          showErrorModal("Project Duplication Failed", err.message);
        }
      });

      item.querySelector(".project-delete").addEventListener("click", async () => {
        if (!window.confirm(`Delete project “${p.name}”? Its media files will be kept.`)) return;
        try {
          const deleteRes = await fetch(`/api/v1/projects/${encodeURIComponent(p.id)}`, { method: "DELETE" });
          const deleted = await deleteRes.json();
          if (!deleteRes.ok) throw new Error(deleted.detail || "Project deletion failed");
          if (currentProjectId === p.id) {
            currentProjectId = null;
            activeProjectNameEl.textContent = "Unsaved Project";
          }
          await fetchRecentProjects();
        } catch (err) {
          showErrorModal("Project Deletion Failed", err.message);
        }
      });
      recentProjectsList.appendChild(item);
    });
  } catch (err) {
    recentProjectsList.innerHTML = `<div class="empty-state">Failed to retrieve projects: ${escapeHtml(err.message)}</div>`;
  }
}

function setupStudioTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.dataset.tab;
      const targetEl = document.getElementById(targetId);
      if (targetEl) targetEl.classList.add("active");
    });
  });
}

function setupEventListeners() {
  // Drag and drop video
  if (uploadZoneEl) {
    uploadZoneEl.addEventListener("dragover", (e) => {
      e.preventDefault();
      uploadZoneEl.classList.add("dragover");
    });
    uploadZoneEl.addEventListener("dragleave", () => uploadZoneEl.classList.remove("dragover"));
    uploadZoneEl.addEventListener("drop", (e) => {
      e.preventDefault();
      uploadZoneEl.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleVideoUpload(e.dataTransfer.files[0]);
      }
    });
  }

  if (fileInputEl) {
    fileInputEl.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        handleVideoUpload(e.target.files[0]);
      }
    });
  }

  // Quick Chips
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      instructionInputEl.value = chip.dataset.cmd;
      instructionInputEl.focus();
    });
  });

  // Plan generation vs direct submission
  if (btnGeneratePlan) {
    btnGeneratePlan.addEventListener("click", () => generateEditPlan());
  }
  if (submitInstructionBtn) {
    submitInstructionBtn.addEventListener("click", () => executeInstruction());
  }
  if (instructionInputEl) {
    instructionInputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        executeInstruction();
      }
    });
  }

  // AI Plan Card Actions
  if (btnDismissPlan) btnDismissPlan.addEventListener("click", () => aiPlanCardEl.classList.add("hidden"));
  if (btnCancelPlan) btnCancelPlan.addEventListener("click", () => aiPlanCardEl.classList.add("hidden"));
  if (btnApprovePlan) btnApprovePlan.addEventListener("click", () => approveAndApplyPlan());

  // Undo / Redo
  if (undoBtn) undoBtn.addEventListener("click", () => executeQuickEdit("undo"));
  if (redoBtn) redoBtn.addEventListener("click", () => executeQuickEdit("redo"));

  // Compare Toggle (Scene 9)
  if (btnCompareToggle) {
    btnCompareToggle.addEventListener("click", () => toggleCompareView());
  }

  // Render trigger (Scene 10)
  if (renderBtn) {
    renderBtn.addEventListener("click", () => startRenderProcess());
  }
  if (cancelRenderBtn) cancelRenderBtn.addEventListener("click", cancelRenderProcess);
  if (exportOtioBtn) exportOtioBtn.addEventListener("click", () => exportTimelineOtio());

  // View Manifest in Export Modal
  if (btnViewManifestModal) {
    btnViewManifestModal.addEventListener("click", () => {
      manifestViewerBox.classList.toggle("hidden");
    });
  }

  // Subtitle / Transcript buttons
  if (generateTranscriptBtn) {
    generateTranscriptBtn.addEventListener("click", () => triggerAutoTranscription());
  }
  if (loadSampleTranscriptBtn) {
    loadSampleTranscriptBtn.addEventListener("click", () => loadSampleTranscript());
  }
  if (exportTranscriptBtn) {
    exportTranscriptBtn.addEventListener("click", () => exportTranscript());
  }
  if (searchTranscriptBtn) {
    searchTranscriptBtn.addEventListener("click", () => searchTranscript());
  }
  if (transcriptSearchInput) {
    transcriptSearchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") searchTranscript();
    });
  }
  if (filterFlaggedBtn) {
    filterFlaggedBtn.addEventListener("click", () => toggleFilterFlagged());
  }

  // Word Editor controls
  if (closeWordEditorBtn) {
    closeWordEditorBtn.addEventListener("click", () => {
      wordEditorCard.classList.add("hidden");
      currentSelectedWord = null;
    });
  }
  if (saveWordBtn) saveWordBtn.addEventListener("click", () => saveWordEdits());
  if (deleteWordBtn) deleteWordBtn.addEventListener("click", () => deleteCurrentWord());

  // Caption Studio controls
  if (captionFontSizeSlider) {
    captionFontSizeSlider.addEventListener("input", (e) => {
      fontSizeValDisplay.textContent = e.target.value;
    });
  }
  if (captionOutlineWidthSlider) {
    captionOutlineWidthSlider.addEventListener("input", (e) => {
      outlineWidthValDisplay.textContent = e.target.value;
    });
  }
  if (captionShadowSlider) {
    captionShadowSlider.addEventListener("input", (e) => {
      shadowValDisplay.textContent = e.target.value;
    });
  }
  if (applyCaptionStyleBtn) {
    applyCaptionStyleBtn.addEventListener("click", () => applyCaptionStyleFromStudio());
  }

  // Preset buttons
  document.querySelectorAll(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyCaptionPreset(btn.dataset.preset));
  });

  // Caption Mode radio buttons
  document.querySelectorAll('input[name="caption_mode"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
      if (e.target.checked) {
        executeInstruction(`set caption mode to ${e.target.value}`);
      }
    });
  });

  // Titles & Audio Studio (Scene 8)
  if (btnAddOpeningTitle) {
    btnAddOpeningTitle.addEventListener("click", () => addOpeningTitleCard());
  }
  if (btnAddClosingTitle) {
    btnAddClosingTitle.addEventListener("click", () => addClosingTitleCard());
  }
  if (bgmVolumeSlider) {
    bgmVolumeSlider.addEventListener("input", (e) => {
      bgmVolumeVal.textContent = e.target.value;
    });
  }
  if (btnApplyBgm) {
    btnApplyBgm.addEventListener("click", () => applyBgmSettings());
  }

  // Aspect ratio buttons
  document.querySelectorAll(".aspect-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const aspect = btn.dataset.aspect;
      executeInstruction(`convert aspect ratio to ${aspect}`);
    });
  });

  // Color grade buttons
  document.querySelectorAll(".color-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const color = btn.dataset.color;
      if (color === "none") {
        executeInstruction("reset colour grade");
      } else {
        executeInstruction(`give the video a ${color} colour grade`);
      }
    });
  });

  // Audio & Transitions buttons
  const btnFade = document.getElementById("btn-fade-transition");
  if (btnFade) btnFade.addEventListener("click", () => executeInstruction("Add a smooth fade-in and fade-out."));

  const btnCrossfade = document.getElementById("btn-crossfade-transition");
  if (btnCrossfade) btnCrossfade.addEventListener("click", () => executeInstruction("Apply a crossfade between clips of 0.75 seconds."));

  const btnDissolve = document.getElementById("btn-dissolve-transition");
  if (btnDissolve) btnDissolve.addEventListener("click", () => executeInstruction("Apply a dissolve between clips of 0.75 seconds."));

  const btnBlur = document.getElementById("btn-blur-region");
  if (btnBlur) btnBlur.addEventListener("click", () => executeInstruction("Blur the video."));

  const btnDucking = document.getElementById("btn-audio-ducking");
  if (btnDucking) btnDucking.addEventListener("click", () => executeInstruction("Lower the music when someone speaks."));

  const btnNormalize = document.getElementById("btn-audio-normalize");
  if (btnNormalize) btnNormalize.addEventListener("click", () => executeInstruction("Normalize audio loudness."));

  // Suggestions
  if (refreshSuggestionsBtn) refreshSuggestionsBtn.addEventListener("click", () => fetchSmartSuggestions());
  if (searchTopicBtn) {
    searchTopicBtn.addEventListener("click", () => {
      const topic = topicSearchInput.value.trim();
      if (topic) fetchSmartSuggestions(topic);
    });
  }

  // Clip editor actions
  if (btnSaveClip) btnSaveClip.addEventListener("click", () => saveClipBoundaries());
  if (btnDeleteClip) btnDeleteClip.addEventListener("click", () => deleteTimelineClip());
}

// --- Video Upload & Metadata Inspection (Scene 3) ---
async function handleVideoUpload(file) {
  // Validate extension and type
  const allowed = [".mp4", ".mov", ".mkv", ".webm"];
  const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
  if (!allowed.includes(ext)) {
    showErrorModal("Unsupported Video Format", `The uploaded file extension "${ext}" is not supported. Please supply MP4, MOV, or MKV footage.`);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  uploadZoneEl.innerHTML = `
    <div class="upload-text">
      <div class="spinner-mini" style="margin: 0 auto 12px auto;"></div>
      <h3>Inspecting media streams with FFprobe...</h3>
      <p>Validating codecs, timestamps, and container integrity</p>
    </div>
  `;

  try {
    const res = await fetch("/api/v1/media/upload", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Media intake validation failed");
    }

    const manifest = await res.json();
    currentMediaId = manifest.media_id;

    const projectName = file.name.replace(/\.[^.]+$/, "").trim() || "Untitled Project";
    const projectRes = await fetch(
      currentProjectId ? `/api/v1/projects/${encodeURIComponent(currentProjectId)}` : "/api/v1/projects",
      {
        method: currentProjectId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentProjectId ? { media_id: currentMediaId } : { name: projectName, media_id: currentMediaId }),
      },
    );
    const projectResult = await projectRes.json();
    if (!projectRes.ok) {
      throw new Error(projectResult.detail || "Video uploaded, but could not attach it to a project");
    }
    currentProjectId = projectResult.id;
    if (projectResult.name) activeProjectNameEl.textContent = projectResult.name;

    displayMedia(manifest);
    await refreshTimeline();
    await fetchSmartSuggestions();
    enableWorkspaceControls();
  } catch (e) {
    showErrorModal("Upload & Inspection Failure", e.message);
    setTimeout(() => location.reload(), 2500);
  }
}

// Load Bundled Demo Project
async function loadDemoProject() {
  try {
    const res = await fetch("/api/v1/demo/load", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load demo project");

    currentMediaId = data.media_id;
    currentTimeline = data.timeline;
    currentProjectId = data.project?.id || null;
    if (data.project?.name) activeProjectNameEl.textContent = data.project.name;
    displayMedia(data.manifest);

    await refreshTimeline();
    await fetchSmartSuggestions();
    enableWorkspaceControls();
  } catch (err) {
    showErrorModal("Demo Project Load Failed", err.message);
  }
}

function displayMedia(manifest) {
  uploadZoneEl.classList.add("hidden");
  videoWrapperEl.classList.remove("hidden");
  videoPlayerEl.src = `/api/v1/media/${encodeURIComponent(manifest.media_id)}/source`;

  mediaIdTagEl.textContent = manifest.media_id;
  metadataCardEl.classList.remove("hidden");
  activePropsCardEl.classList.remove("hidden");

  metaHashEl.textContent = (manifest.sha256_hash || "").substring(0, 18) + "...";
  metaDurationEl.textContent = `${manifest.metadata.duration.toFixed(2)}s`;
  metaResolutionEl.textContent = `${manifest.metadata.width}x${manifest.metadata.height}`;
  metaFpsEl.textContent = `${manifest.metadata.frame_rate.toFixed(2)} fps ${manifest.metadata.is_vfr ? '(VFR)' : '(CFR)'}`;
  metaAudioEl.textContent = manifest.metadata.audio_present ? `Present (${manifest.metadata.sample_rate || 44100}Hz)` : "None";
}

function enableWorkspaceControls() {
  if (instructionInputEl) instructionInputEl.disabled = false;
  if (btnGeneratePlan) btnGeneratePlan.disabled = false;
  if (submitInstructionBtn) submitInstructionBtn.disabled = false;
  if (generateTranscriptBtn) generateTranscriptBtn.disabled = false;
  if (loadSampleTranscriptBtn) loadSampleTranscriptBtn.disabled = false;
  if (exportTranscriptBtn) exportTranscriptBtn.disabled = false;
  if (renderBtn) renderBtn.disabled = false;
  if (exportOtioBtn) exportOtioBtn.disabled = false;
  if (undoBtn) undoBtn.disabled = false;
  if (redoBtn) redoBtn.disabled = false;
}

function disableWorkspaceControls() {
  [
    instructionInputEl,
    btnGeneratePlan,
    submitInstructionBtn,
    generateTranscriptBtn,
    loadSampleTranscriptBtn,
    exportTranscriptBtn,
    renderBtn,
    exportOtioBtn,
    undoBtn,
    redoBtn,
    btnCompareToggle,
  ].forEach((control) => {
    if (control) control.disabled = true;
  });
}

// --- AI Understanding and Edit Planning (Scene 4 & Scene 5) ---
async function generateEditPlan() {
  const text = instructionInputEl.value.trim();
  if (!text || !currentMediaId) return;

  btnGeneratePlan.disabled = true;
  btnGeneratePlan.textContent = "Analyzing...";

  try {
    const res = await fetch(`/api/v1/plan/generate/${currentMediaId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: text }),
    });
    const plan = await res.json();
    if (!res.ok) throw new Error(plan.detail || "Failed to generate edit plan");

    currentPendingPlan = plan;
    displayEditPlan(plan);
  } catch (err) {
    showErrorModal("AI Interpretation Error", err.message);
  } finally {
    btnGeneratePlan.disabled = false;
    btnGeneratePlan.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
      Preview Plan
    `;
  }
}

function displayEditPlan(plan) {
  aiPlanCardEl.classList.remove("hidden");
  planPromptSummaryEl.textContent = `"${plan.original_prompt || plan.prompt || ""}"`;
  planProviderNoticeEl.textContent = plan.provider_notice || "";
  planProviderNoticeEl.classList.toggle("hidden", !plan.provider_notice);
  const targetDuration = plan.target_duration_seconds ?? plan.target_duration_s;
  planTargetDurEl.textContent = `Target: ${Number.isFinite(Number(targetDuration)) ? Number(targetDuration).toFixed(1) + 's' : 'Auto'}`;
  planAspectPillEl.textContent = `Aspect: ${plan.aspect_ratio || 'Original'}`;

  planOperationsListEl.innerHTML = "";
  if (!plan.operations || plan.operations.length === 0) {
    planOperationsListEl.innerHTML = `<div class="empty-state">No supported operations recognized for this prompt.</div>`;
    btnApprovePlan.disabled = true;
    return;
  }

  const hasOperations = plan.operations.length > 0;
  btnApprovePlan.disabled = !hasOperations;
  btnApprovePlan.title = "Apply supported edits and report unsupported or unclear parts";

  plan.operations.forEach((op, idx) => {
    const item = document.createElement("div");
    item.className = "plan-op-item";

    let statusBadgeClass = "badge-success";
    let statusBadgeText = "Validated";
    const validationStatus = op.validation_status || op.status;
    if (validationStatus === "warning") {
      statusBadgeClass = "badge-warning";
      statusBadgeText = "Warning";
    } else if (validationStatus === "unsupported") {
      statusBadgeClass = "badge-danger";
      statusBadgeText = "Unsupported";
    }

    item.innerHTML = `
      <div class="op-index font-mono">${idx + 1}</div>
      <div class="op-details">
        <div class="op-title-row">
          <strong>${formatOpName(op.type)}</strong>
          <span class="badge ${statusBadgeClass}">${statusBadgeText}</span>
        </div>
        <div class="op-desc">${escapeHtml(op.description || '')}</div>
        <div class="op-params font-mono">${formatOpParams(op.parameters)}</div>
      </div>
    `;
    planOperationsListEl.appendChild(item);
  });
}

function formatOpName(type) {
  return (type || "operation")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatOpParams(params) {
  if (!params) return "";
  const parts = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined) {
      parts.push(`${k}: ${v}`);
    }
  }
  return parts.join(" | ");
}

async function approveAndApplyPlan() {
  if (!currentPendingPlan || !currentMediaId) return;

  btnApprovePlan.disabled = true;
  btnApprovePlan.textContent = "Applying...";

  try {
    const planNeedsCaptions = (currentPendingPlan.operations || []).some((operation) => operation.type === "generate_captions");
    const transcriptWords = currentTimeline?.transcript?.words || [];
    if (planNeedsCaptions && transcriptWords.length === 0) {
      btnApprovePlan.textContent = "Transcribing audio...";
      await transcribeForApprovedCaptionPlan();
      btnApprovePlan.textContent = "Applying subtitles...";
    }

    const res = await fetch(`/api/v1/plan/apply/${currentMediaId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentPendingPlan),
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Failed to apply edit plan");

    if (!["applied", "partial"].includes(result.status)) {
      displayInstructionOutcome({
        status: result.status || "rejected",
        message: [result.message, ...(result.errors || []), ...(result.skipped_operations || [])].filter(Boolean).join("\n"),
        timeline_hash: result.timeline_hash,
      });
      await refreshTimeline();
      return;
    }

    aiPlanCardEl.classList.add("hidden");
    currentPendingPlan = null;
    displayInstructionOutcome({
      status: result.status,
      message: [result.message || "Approved edit plan successfully applied to timeline.", ...(result.skipped_operations || [])].filter(Boolean).join("\n"),
      timeline_hash: result.timeline_hash,
      before_summary: result.before_summary,
      after_summary: result.after_summary,
    });
    await refreshTimeline();
    await fetchSmartSuggestions();
    instructionInputEl.value = "";
  } catch (err) {
    showErrorModal("Plan Execution Error", err.message);
  } finally {
    btnApprovePlan.disabled = false;
    btnApprovePlan.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
      Approve & Execute Plan
    `;
  }
}

async function transcribeForApprovedCaptionPlan() {
  const startResponse = await fetch(`/api/v1/transcript/${currentMediaId}/generate`, { method: "POST" });
  const startData = await startResponse.json().catch(() => ({}));
  if (!startResponse.ok) {
    throw new Error(startData.detail || "Could not start transcription. Upload a transcript or configure a transcription provider.");
  }

  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    const statusResponse = await fetch(`/api/v1/transcript/status/${startData.job_id}`);
    const job = await statusResponse.json().catch(() => ({}));
    if (!statusResponse.ok) throw new Error(job.detail || "Could not check transcription status.");
    if (job.status === "failed") throw new Error(job.error || "Transcription failed; no subtitles were applied.");
    if (job.status === "completed") {
      await refreshTimeline();
      const words = currentTimeline?.transcript?.words || [];
      if (!words.length) throw new Error("No speech was detected. Upload an SRT/VTT or word-level transcript, then retry.");
      return;
    }
  }
  throw new Error("Transcription is taking too long. Check job status and retry after it completes.");
}

// Direct natural language instruction execution
async function executeInstruction(overrideText = null) {
  const text = overrideText || instructionInputEl.value.trim();
  if (!text || !currentMediaId) return;

  // In AI mode, never bypass the reviewed plan and apply model output directly.
  if (!overrideText && ["ollama", "auto"].includes(instructionProvider)) {
    instructionInputEl.value = text;
    await generateEditPlan();
    return;
  }

  const asksForCaptions = /\b(generate|create|add|auto)\b[\s\S]*\b(captions?|subtitles?)\b/i.test(text);
  if (asksForCaptions && !(currentTimeline?.transcript?.words || []).length) {
    try {
      submitInstructionBtn.disabled = true;
      await transcribeForApprovedCaptionPlan();
    } catch (err) {
      showErrorModal("Subtitle Transcription Error", err.message);
      submitInstructionBtn.disabled = false;
      return;
    }
  }

  submitInstructionBtn.disabled = true;
  outcomeCardEl.classList.remove("hidden");
  outcomeBadgeEl.className = "badge";
  outcomeBadgeEl.textContent = "Processing...";
  outcomeMsgEl.textContent = `Interpreting "${text}"...`;
  clarificationBoxEl.classList.add("hidden");
  outcomeSummaryEl.classList.add("hidden");

  try {
    const res = await fetch(`/api/v1/instruction/${currentMediaId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: text }),
    });
    const result = await res.json();
    displayInstructionOutcome(result);
    await refreshTimeline();
    await fetchSmartSuggestions();
  } catch (err) {
    displayInstructionOutcome({
      status: "rejected",
      message: `Network error: ${err.message}`,
      error_code: "NETWORK_ERROR",
    });
  } finally {
    submitInstructionBtn.disabled = false;
    if (!overrideText) instructionInputEl.value = "";
  }
}

async function executeQuickEdit(type) {
  if (!currentMediaId) return;
  const endpoint = type === "undo" ? "undo" : "redo";
  try {
    const res = await fetch(`/api/v1/timeline/${currentMediaId}/${endpoint}`, { method: "POST" });
    const result = await res.json();
    displayInstructionOutcome(result);
    await refreshTimeline();
    await fetchSmartSuggestions();
  } catch (err) {
    showErrorModal(`Failed to ${type}`, err.message);
  }
}

function displayInstructionOutcome(result) {
  outcomeCardEl.classList.remove("hidden");
  outcomeHashEl.textContent = result.timeline_hash ? `Hash: ${result.timeline_hash.substring(0, 16)}...` : "";

  if (result.status === "applied") {
    outcomeBadgeEl.className = "badge badge-success";
    outcomeBadgeEl.textContent = "Applied";
    outcomeMsgEl.textContent = result.message;

    if (result.before_summary && result.after_summary) {
      outcomeSummaryEl.classList.remove("hidden");
      summaryBeforeDurEl.textContent = `${result.before_summary.output_duration_s.toFixed(2)}s`;
      summaryAfterDurEl.textContent = `${result.after_summary.output_duration_s.toFixed(2)}s`;
    }
  } else if (result.status === "partial") {
    outcomeBadgeEl.className = "badge badge-warning";
    outcomeBadgeEl.textContent = "Partially Applied";
    outcomeMsgEl.textContent = result.message;
  } else if (result.status === "unsupported") {
    outcomeBadgeEl.className = "badge badge-warning";
    outcomeBadgeEl.textContent = "No Supported Edits";
    outcomeMsgEl.textContent = result.message;
  } else if (result.status === "needs_clarification") {
    outcomeBadgeEl.className = "badge badge-warning";
    outcomeBadgeEl.textContent = "Needs Clarification";
    outcomeMsgEl.textContent = result.message;

    activeClarificationSessionId = result.operation_id;
    clarQuestionEl.textContent = result.clarification_question;
    clarOptionsListEl.innerHTML = "";

    (result.options || []).forEach((opt) => {
      const btn = document.createElement("button");
      btn.className = "clarification-btn";
      btn.innerHTML = `<strong>${escapeHtml(opt.label)}</strong><br><small>${escapeHtml(opt.detail || '')}</small>`;
      btn.addEventListener("click", () => resolveClarificationChoice(opt.id));
      clarOptionsListEl.appendChild(btn);
    });

    clarificationBoxEl.classList.remove("hidden");
  } else {
    outcomeBadgeEl.className = "badge badge-danger";
    outcomeBadgeEl.textContent = "Rejected";
    outcomeMsgEl.textContent = `${result.error_code ? `[${result.error_code}] ` : ''}${result.message}`;
  }
}

async function resolveClarificationChoice(optionId) {
  if (!activeClarificationSessionId) return;
  clarificationBoxEl.classList.add("hidden");
  outcomeBadgeEl.textContent = "Applying choice...";

  try {
    const res = await fetch("/api/v1/instruction/clarify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: activeClarificationSessionId,
        selected_option_id: optionId,
      }),
    });
    const result = await res.json();
    displayInstructionOutcome(result);
    await refreshTimeline();
    await fetchSmartSuggestions();
  } catch (err) {
    showErrorModal("Clarification Error", err.message);
  }
}

// --- Multi-Track Timeline Synchronization (Scene 6) ---
async function refreshTimeline() {
  if (!currentMediaId) return;

  try {
    const res = await fetch(`/api/v1/timeline/${currentMediaId}`);
    if (!res.ok) throw new Error("Could not retrieve timeline state");

    const timeline = await res.json();
    currentTimeline = timeline;

    timelineRevTagEl.textContent = `Revision ${timeline.revision}`;
  const totalDuration = timeline.output_duration_s ?? timeline.total_output_duration ?? 0;
    timelineDurationEl.textContent = `${totalDuration.toFixed(2)}s`;
    timelineDurationBadge.textContent = `${totalDuration.toFixed(2)}s`;
    timelineClipCountEl.textContent = (timeline.clips || []).length;

    renderMultiTrackTimeline(timeline);
    updateActiveProperties(timeline);
    renderRevisionHistory(timeline.revision_history || []);
  } catch (err) {
    console.error("Timeline refresh failed:", err);
  }
}

function renderMultiTrackTimeline(timeline) {
  const clips = timeline.clips || [];
  const totalDur = timeline.output_duration_s || 1.0;

  trackVideoEl.ondragover = (event) => {
    const dragged = trackVideoEl.querySelector(".video-clip-block.is-dragging");
    if (!dragged) return;
    event.preventDefault();
    const target = event.target.closest(".video-clip-block");
    if (!target || target === dragged) return;
    const rect = target.getBoundingClientRect();
    const insertBefore = event.clientX < rect.left + rect.width / 2;
    trackVideoEl.insertBefore(dragged, insertBefore ? target : target.nextSibling);
  };
  trackVideoEl.ondrop = async (event) => {
    event.preventDefault();
    const draggedId = event.dataTransfer?.getData("text/plain") || draggedSegmentId;
    draggedSegmentId = null;
    lastClipDragAt = Date.now();
    const segmentIds = Array.from(trackVideoEl.querySelectorAll(".video-clip-block[data-segment-id]"))
      .map((element) => element.dataset.segmentId);
    if (!draggedId || segmentIds.length < 2) return;
    const existingIds = clips.map((clip) => clip.segment_id);
    if (segmentIds.every((segmentId, index) => segmentId === existingIds[index])) {
      await refreshTimeline();
      return;
    }
    try {
      const response = await fetch(`/api/v1/timeline/${currentMediaId}/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_ids: segmentIds }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Could not reorder timeline clips");
      await refreshTimeline();
    } catch (error) {
      await refreshTimeline();
      showErrorModal("Clip Reorder Failed", error.message);
    }
  };

  // Track 1: Video
  trackVideoEl.innerHTML = "";
  if (clips.length === 0) {
    trackVideoEl.innerHTML = `<div class="empty-lane">Empty timeline</div>`;
  } else {
    clips.forEach((clip, idx) => {
      const sourceStart = clip.source_start_s ?? clip.source_start;
      const sourceEnd = clip.source_end_s ?? clip.source_end;
      const dur = clip.output_duration_s ?? ((sourceEnd - sourceStart) / (clip.speed || 1));
      const pct = Math.max(8, (dur / totalDur) * 100);
      const block = document.createElement("div");
      block.className = "track-clip-block video-clip-block";
      block.draggable = true;
      block.dataset.segmentId = clip.segment_id;
      block.style.width = `${pct}%`;
      block.innerHTML = `
        <span class="clip-title">Clip ${idx + 1} (${clip.speed || 1.0}x)</span>
        <span class="clip-time">${Number(sourceStart).toFixed(1)}s - ${Number(sourceEnd).toFixed(1)}s</span>
      `;
      block.title = `Drag to reorder · Click to edit Clip ${idx + 1}`;
      block.setAttribute("aria-label", `Clip ${idx + 1}, ${Number(sourceStart).toFixed(1)} to ${Number(sourceEnd).toFixed(1)} seconds. Drag to reorder.`);
      block.addEventListener("dragstart", (event) => {
        draggedSegmentId = clip.segment_id;
        lastClipDragAt = Date.now();
        block.classList.add("is-dragging");
        event.dataTransfer?.setData("text/plain", clip.segment_id);
        if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
      });
      block.addEventListener("dragend", () => {
        block.classList.remove("is-dragging");
        draggedSegmentId = null;
        lastClipDragAt = Date.now();
      });
      block.addEventListener("click", () => {
        if (Date.now() - lastClipDragAt < 350) return;
        openClipEditModal(clip, idx);
      });
      trackVideoEl.appendChild(block);
    });
  }

  // Track 2: Audio
  trackAudioEl.innerHTML = "";
  if (clips.length === 0) {
    trackAudioEl.innerHTML = `<div class="empty-lane">Audio synchronized</div>`;
  } else {
    clips.forEach((clip, idx) => {
      const dur = clip.output_duration_s ?? ((clip.source_end_s - clip.source_start_s) / (clip.speed || 1));
      const pct = Math.max(8, (dur / totalDur) * 100);
      const block = document.createElement("div");
      block.className = "track-clip-block audio-clip-block";
      block.style.width = `${pct}%`;
      block.innerHTML = `
        <span class="clip-title">Audio Stream ${idx + 1}</span>
        <span class="clip-time">Vol: 100%</span>
      `;
      trackAudioEl.appendChild(block);
    });
  }

  // Track 3: Captions
  trackCaptionsEl.innerHTML = "";
  const transcriptWords = (timeline.transcript && timeline.transcript.words) ? timeline.transcript.words : [];
  if (transcriptWords.length === 0) {
    trackCaptionsEl.innerHTML = `<div class="empty-lane">No captions burned. Subtitles track inactive.</div>`;
  } else {
    const block = document.createElement("div");
    block.className = "track-clip-block caption-clip-block";
    block.style.width = `100%`;
    block.innerHTML = `
      <span class="clip-title">Subtitles: ${transcriptWords.length} Words (${timeline.caption_mode || 'standard'})</span>
      <span class="clip-time">Active Track</span>
    `;
    trackCaptionsEl.appendChild(block);
    renderTranscriptWords(transcriptWords);
  }

  // Track 4: Titles & Overlays
  trackTitlesEl.innerHTML = "";
  const overlays = timeline.text_overlays || (timeline.video_effects && timeline.video_effects.text_overlays) || [];
  if (overlays.length === 0) {
    trackTitlesEl.innerHTML = `<div class="empty-lane">No title overlays active. Add via Titles tab.</div>`;
  } else {
    overlays.forEach((ov) => {
      const overlayStart = ov.output_start ?? ov.source_start ?? ov.start_s ?? 0;
      const overlayEnd = ov.output_end ?? ov.source_end ?? ov.end_s ?? totalDur;
      const dur = overlayEnd - overlayStart;
      const pct = Math.max(12, (dur / totalDur) * 100);
      const block = document.createElement("div");
      block.className = "track-clip-block title-clip-block";
      block.style.width = `${pct}%`;
      block.innerHTML = `
        <span class="clip-title">"${escapeHtml(ov.text)}"</span>
        <span class="clip-time">${Number(overlayStart).toFixed(1)}s - ${Number(overlayEnd).toFixed(1)}s</span>
      `;
      trackTitlesEl.appendChild(block);
    });
  }
}

function updateActiveProperties(timeline) {
  const fx = timeline.video_effects || {};
  const aspect = timeline.aspect_ratio || fx.aspect_ratio || "original";
  propAspectEl.textContent = aspect;
  canvasRatioPill.textContent = `${propAspectEl.textContent} Canvas`;
  document.querySelectorAll(".aspect-btn").forEach((button) => {
    const selected = button.dataset.aspect === aspect;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  propColorEl.textContent = fx.color_preset || "None";
  propCaptionsEl.textContent = timeline.caption_mode || "Standard";
  propDuckingEl.textContent = (timeline.audio_ducking && timeline.audio_ducking.enabled) ? "Active (-18dB)" : "Inactive";
}

function renderRevisionHistory(history) {
  historyCountEl.textContent = `${history.length} edits`;
  historyListEl.innerHTML = "";

  if (history.length === 0) {
    historyListEl.innerHTML = `<div class="empty-state">No edits applied yet. Revision 0 is active.</div>`;
    return;
  }

  history.forEach((rev) => {
    const item = document.createElement("div");
    item.className = "history-item";

    const left = document.createElement("div");
    left.className = "history-left";
    left.innerHTML = `
      <span class="font-mono text-accent">#${rev.revision}</span>
      <span>${escapeHtml(rev.description || rev.instruction || "Edit Operation")}</span>
    `;

    const btnRestore = document.createElement("button");
    btnRestore.className = "btn btn-secondary btn-sm";
    btnRestore.textContent = "Restore";
    btnRestore.addEventListener("click", () => executeInstruction(`restore revision ${rev.revision}`));

    item.appendChild(left);
    item.appendChild(btnRestore);
    historyListEl.appendChild(item);
  });
}

function openClipEditModal(clip, idx) {
  currentEditingClipId = clip.id || idx;
  clipModalIdText.textContent = `Clip ID: ${clip.id || `clip_${idx + 1}`}`;
  clipEditStart.value = clip.source_start_s;
  clipEditEnd.value = clip.source_end_s;
  clipEditSpeed.value = clip.speed ? clip.speed.toString() : "1.0";
  clipEditModalEl.classList.remove("hidden");
}

async function saveClipBoundaries() {
  const start = parseFloat(clipEditStart.value);
  const end = parseFloat(clipEditEnd.value);
  const speed = parseFloat(clipEditSpeed.value);

  if (isNaN(start) || isNaN(end) || start >= end) {
    alert("Invalid clip start/end boundaries.");
    return;
  }

  clipEditModalEl.classList.add("hidden");
  await executeInstruction(`trim video from ${start}s to ${end}s`);
}

async function deleteTimelineClip() {
  clipEditModalEl.classList.add("hidden");
  await executeInstruction(`remove clip ${currentEditingClipId}`);
}

// --- Titles & Audio Finishing (Scene 8) ---
async function addOpeningTitleCard() {
  const text = openingTitleText.value.trim();
  if (!text || !currentMediaId) {
    alert("Please enter title text.");
    return;
  }
  const dur = parseFloat(openingTitleDur.value) || 3.5;
  const pos = openingTitlePos.value || "center";

  try {
    const res = await fetch(`/api/v1/timeline/${currentMediaId}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, duration_s: dur, position: pos }),
    });
    const result = await res.json();
    displayInstructionOutcome(result);
    await refreshTimeline();
    openingTitleText.value = "";
  } catch (e) {
    showErrorModal("Title Overlay Error", e.message);
  }
}

async function addClosingTitleCard() {
  const text = closingTitleText.value.trim();
  if (!text || !currentMediaId) {
    alert("Please enter closing title text.");
    return;
  }

  try {
    const res = await fetch(`/api/v1/timeline/${currentMediaId}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, duration_s: 3.5, position: "closing" }),
    });
    const result = await res.json();
    displayInstructionOutcome(result);
    await refreshTimeline();
    closingTitleText.value = "";
  } catch (e) {
    showErrorModal("Closing Title Overlay Error", e.message);
  }
}

async function applyBgmSettings() {
  if (!currentMediaId) return;
  const enabled = bgmToggle.checked;
  const volume = parseFloat(bgmVolumeSlider.value) / 100.0;
  const ducking = bgmDuckingToggle.checked;

  try {
    const res = await fetch(`/api/v1/timeline/${currentMediaId}/bgm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, volume, ducking }),
    });
    const result = await res.json();
    displayInstructionOutcome(result);
    await refreshTimeline();
  } catch (e) {
    showErrorModal("Audio Mixing Error", e.message);
  }
}

// --- Compare Toggle (Scene 9) ---
function toggleCompareView() {
  if (!lastRenderedUrl) return;

  isComparingRendered = !isComparingRendered;
  if (isComparingRendered) {
    videoPlayerEl.src = lastRenderedUrl;
    videoModeIndicator.textContent = "Rendered Output (Verified MP4)";
    videoModeIndicator.className = "video-mode-pill video-mode-rendered";
    compareBtnText.textContent = "Compare: Rendered";
    btnCompareToggle.classList.add("btn-accent");
  } else {
    videoPlayerEl.src = `/api/v1/media/${currentMediaId}`;
    videoModeIndicator.textContent = "Source Media";
    videoModeIndicator.className = "video-mode-pill";
    compareBtnText.textContent = "Compare: Source";
    btnCompareToggle.classList.remove("btn-accent");
  }
  videoPlayerEl.play().catch(() => {});
}

// --- Render Engine & Progress Modal (Scene 10) ---
function exportTimelineOtio() {
  if (!currentMediaId) return;
  const link = document.createElement("a");
  link.href = `/api/v1/timeline/${encodeURIComponent(currentMediaId)}/export/otio`;
  link.download = `${currentMediaId}.otio`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function startRenderProcess() {
  if (!currentMediaId) return;

  currentRenderJob = null;
  renderBtn.disabled = true;
  renderModalEl.classList.remove("hidden");
  resetRenderStepper();

  try {
    const renderOptions = {
      quality: Number(document.getElementById("export-quality")?.value || 20),
      frame_rate: Number(document.getElementById("export-frame-rate")?.value || 30),
      preset: document.getElementById("export-preset")?.value || "veryfast",
    };
    const res = await fetch(`/api/v1/render/${currentMediaId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(renderOptions),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Render process initialization rejected");

    currentRenderJob = data.job_id;
    pollRenderJob(data.job_id);
  } catch (err) {
    renderModalEl.classList.add("hidden");
    renderBtn.disabled = false;
    showErrorModal("Render Initialization Failure", err.message);
  }
}

function resetRenderStepper() {
  renderStageBadge.textContent = "Stage 1 of 6";
  renderStageDesc.textContent = "Preparing timeline graph, subtitle files, and audio assets...";
  renderModalProgressFill.style.width = "10%";
  renderLogText.textContent = "Building deterministic FFmpeg filter pipeline...\n";

  const steps = ["step-prepare", "step-clips", "step-captions", "step-audio", "step-encode", "step-validate"];
  steps.forEach((s) => {
    const el = document.getElementById(s);
    if (el) el.className = "step-item";
  });
  const first = document.getElementById("step-prepare");
  if (first) first.classList.add("active");
}

function setRenderStepActive(stepId, num, label, pct, logLine) {
  renderStageBadge.textContent = `Stage ${num} of 6`;
  renderStageDesc.textContent = label;
  renderModalProgressFill.style.width = `${pct}%`;
  if (logLine) {
    renderLogText.textContent += `[${new Date().toLocaleTimeString()}] ${logLine}\n`;
    renderLogText.scrollTop = renderLogText.scrollHeight;
  }

  const steps = ["step-prepare", "step-clips", "step-captions", "step-audio", "step-encode", "step-validate"];
  let passedCurrent = false;
  steps.forEach((s) => {
    const el = document.getElementById(s);
    if (!el) return;
    if (s === stepId) {
      el.className = "step-item active";
      passedCurrent = true;
    } else if (!passedCurrent) {
      el.className = "step-item completed";
    } else {
      el.className = "step-item";
    }
  });
}

async function pollRenderJob(jobId) {
  let simulatedStage = 1;
  const pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/v1/render/status/${jobId}`);
      const job = await res.json();

      if (job.status === "running") {
        simulatedStage++;
        if (simulatedStage === 2) {
          setRenderStepActive("step-clips", 2, "Processing cuts, playback speeds, and scale transformations...", 30, "Trimming clips and compiling complex video filter graphs...");
        } else if (simulatedStage === 3) {
          setRenderStepActive("step-captions", 3, "Compiling ASS subtitle styles & burning synchronized text...", 50, "Rendering ASS subtitle track with libass font rasterizer...");
        } else if (simulatedStage === 4) {
          setRenderStepActive("step-audio", 4, "Mixing background audio and applying speech ducking...", 70, "Applying sidechain ducking filter and EBU R128 audio normalization...");
        } else if (simulatedStage >= 5) {
          setRenderStepActive("step-encode", 5, "Encoding H.264 video (yuv420p) and AAC audio stream...", 85, "Executing FFmpeg H.264 encoder with faststart MP4 flags...");
        }
      } else if (job.status === "completed") {
        clearInterval(pollTimer);
        currentRenderJob = null;
        setRenderStepActive("step-validate", 6, "FFprobe validation passed. Final MP4 container verified.", 100, "Media verification SUCCESS. Video streams valid and playable.");

        setTimeout(() => {
          renderModalEl.classList.add("hidden");
          renderBtn.disabled = false;

          const manifest = job.result;
          lastRenderedManifest = manifest;
          lastRenderedUrl = manifest.output_url;

          // Enable Compare Toggle
          btnCompareToggle.disabled = false;
          displayExportSuccess(manifest);
        }, 800);
      } else if (job.status === "failed") {
        clearInterval(pollTimer);
        currentRenderJob = null;
        renderModalEl.classList.add("hidden");
        renderBtn.disabled = false;
        showErrorModal("Render Execution Failure", job.error || "FFmpeg process returned non-zero exit code.");
      } else if (job.status === "cancelled") {
        clearInterval(pollTimer);
        renderModalEl.classList.add("hidden");
        renderBtn.disabled = false;
        currentRenderJob = null;
        showErrorModal("Render Cancelled", "The render was stopped. Your project and source media are unchanged.");
      }
    } catch (e) {
      clearInterval(pollTimer);
      renderModalEl.classList.add("hidden");
      renderBtn.disabled = false;
      showErrorModal("Render Polling Error", e.message);
    }
  }, 1200);
}

async function cancelRenderProcess() {
  if (!currentRenderJob) {
    renderModalEl.classList.add("hidden");
    renderBtn.disabled = false;
    return;
  }
  cancelRenderBtn.disabled = true;
  cancelRenderBtn.textContent = "Stopping…";
  try {
    const response = await fetch(`/api/v1/render/cancel/${encodeURIComponent(currentRenderJob)}`, { method: "POST" });
    const job = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(job.detail || "Could not cancel the render.");
  } catch (error) {
    showErrorModal("Could Not Stop Render", error.message);
  } finally {
    cancelRenderBtn.disabled = false;
    cancelRenderBtn.textContent = "Cancel render";
  }
}

// --- Export Success Screen (Scene 11) ---
function displayExportSuccess(manifest) {
  const verification = manifest.verification || {};
  const metadata = manifest.metadata || {};
  const filename = manifest.output_filename || manifest.filename || "editora_export.mp4";
  const duration = verification.actual_duration_s ?? metadata.duration ?? 0;
  const width = verification.width ?? metadata.width;
  const height = verification.height ?? metadata.height;
  const videoCodec = verification.video_codec || metadata.video_codec;
  const audioCodec = verification.audio_codec || metadata.audio_codec;

  exportSuccessModalEl.classList.remove("hidden");
  finalRenderedPlayer.src = manifest.output_url;
  btnDownloadMp4.href = manifest.output_url;
  btnDownloadMp4.download = filename;

  exportFilenameEl.textContent = filename;
  exportDurationEl.textContent = `${Number(duration).toFixed(2)}s`;
  exportResolutionEl.textContent = width && height ? `${width}x${height}` : "Unavailable";
  exportSizeEl.textContent = formatBytes(manifest.file_size_bytes || 0);

  if (videoCodec) {
    exportVcodecEl.textContent = videoCodec.toUpperCase();
  }
  exportAcodecEl.textContent = audioCodec ? audioCodec.toUpperCase() : "No audio stream";

  manifestViewerJson.textContent = JSON.stringify(manifest, null, 2);
}

// --- Error Modal & Media Safety Guarantee (Scene 12) ---
function showErrorModal(title, message) {
  errorModalTitle.textContent = title || "Operation Error";
  errorModalDesc.textContent = message || "An unexpected error occurred while processing instructions.";
  errorModalEl.classList.remove("hidden");
}

// --- Transcript & Subtitle Studio ---
function renderTranscriptWords(words) {
  transcriptWordsContainerEl.innerHTML = "";
  transcriptCountEl.textContent = `${words.length} words`;

  const flagged = words.filter((w) => w.is_flagged || w.confidence < 0.7);
  flaggedCountEl.textContent = flagged.length;

  const wordsToDisplay = showFlaggedOnly ? flagged : words;

  if (wordsToDisplay.length === 0) {
    transcriptWordsContainerEl.innerHTML = `<div class="empty-state">${showFlaggedOnly ? "No flagged words found." : "No transcript words."}</div>`;
    return;
  }

  wordsToDisplay.forEach((w) => {
    const span = document.createElement("span");
    span.className = "transcript-word";
    if (w.is_flagged || w.confidence < 0.7) span.classList.add("flagged");
    span.textContent = w.text + " ";
    span.title = `Speaker: ${w.speaker || 'Unknown'} | Time: ${w.start.toFixed(2)}s - ${w.end.toFixed(2)}s (Confidence: ${(w.confidence * 100).toFixed(0)}%)`;

    span.addEventListener("click", () => openWordEditor(w));
    transcriptWordsContainerEl.appendChild(span);
  });
}

function openWordEditor(word) {
  currentSelectedWord = word;
  editWordText.value = word.text;
  editWordStart.value = word.start;
  editWordEnd.value = word.end;
  editWordSpeaker.value = word.speaker || "";
  wordEditorCard.classList.remove("hidden");
}

async function saveWordEdits() {
  if (!currentSelectedWord || !currentMediaId) return;

  const payload = {
    word_id: currentSelectedWord.id,
    new_text: editWordText.value.trim(),
    start: parseFloat(editWordStart.value),
    end: parseFloat(editWordEnd.value),
    speaker: editWordSpeaker.value.trim(),
  };

  try {
    const res = await fetch(`/api/v1/transcript/${currentMediaId}/word`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Failed to save word edits");

    wordEditorCard.classList.add("hidden");
    currentSelectedWord = null;
    await refreshTimeline();
  } catch (e) {
    showErrorModal("Save Word Error", e.message);
  }
}

async function deleteCurrentWord() {
  if (!currentSelectedWord || !currentMediaId) return;

  try {
    const res = await fetch(`/api/v1/transcript/${currentMediaId}/word/${currentSelectedWord.id}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete word");

    wordEditorCard.classList.add("hidden");
    currentSelectedWord = null;
    await refreshTimeline();
  } catch (e) {
    showErrorModal("Delete Word Error", e.message);
  }
}

function toggleFilterFlagged() {
  showFlaggedOnly = !showFlaggedOnly;
  filterFlaggedBtn.classList.toggle("btn-accent", showFlaggedOnly);
  if (currentTimeline && currentTimeline.transcript) {
    renderTranscriptWords(currentTimeline.transcript.words || []);
  }
}

function searchTranscript() {
  const query = transcriptSearchInput.value.toLowerCase().trim();
  const spans = transcriptWordsContainerEl.querySelectorAll(".transcript-word");
  spans.forEach((span) => {
    const match = !query || span.textContent.toLowerCase().includes(query);
    span.style.opacity = match ? "1" : "0.2";
  });
}

async function triggerAutoTranscription() {
  if (!currentMediaId) return;
  generateTranscriptBtn.disabled = true;
  generateTranscriptBtn.textContent = "Transcribing...";

  try {
    const res = await fetch(`/api/v1/transcript/${currentMediaId}/generate`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Auto-transcription error");

    pollTranscriptionJob(data.job_id);
  } catch (e) {
    showErrorModal("Transcription Error", e.message);
    generateTranscriptBtn.disabled = false;
    generateTranscriptBtn.textContent = "Auto-Transcribe";
  }
}

async function pollTranscriptionJob(jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/v1/transcript/status/${jobId}`);
      const job = await res.json();
      if (job.status === "completed") {
        clearInterval(interval);
        generateTranscriptBtn.disabled = false;
        generateTranscriptBtn.textContent = "Auto-Transcribe";
        await refreshTimeline();
        await fetchSmartSuggestions();
      } else if (job.status === "failed") {
        clearInterval(interval);
        generateTranscriptBtn.disabled = false;
        generateTranscriptBtn.textContent = "Auto-Transcribe";
        showErrorModal("Transcription Failed", job.error || "Whisper ASR execution failed.");
      }
    } catch (e) {
      clearInterval(interval);
      generateTranscriptBtn.disabled = false;
      generateTranscriptBtn.textContent = "Auto-Transcribe";
    }
  }, 1200);
}

async function loadSampleTranscript() {
  if (!currentMediaId) return;
  try {
    const sampleWords = [
      { id: "w_1", text: "Welcome", start: 0.2, end: 0.8, speaker: "Host", confidence: 0.98 },
      { id: "w_2", text: "to", start: 0.85, end: 1.0, speaker: "Host", confidence: 0.99 },
      { id: "w_3", text: "Editora", start: 1.05, end: 1.6, speaker: "Host", confidence: 0.95 },
      { id: "w_4", text: "AI,", start: 1.65, end: 2.1, speaker: "Host", confidence: 0.97 },
      { id: "w_5", text: "the", start: 2.3, end: 2.5, speaker: "Host", confidence: 0.99 },
      { id: "w_6", text: "prompt-based", start: 2.55, end: 3.3, speaker: "Host", confidence: 0.94 },
      { id: "w_7", text: "video", start: 3.35, end: 3.8, speaker: "Host", confidence: 0.99 },
      { id: "w_8", text: "editing", start: 3.85, end: 4.3, speaker: "Host", confidence: 0.96 },
      { id: "w_9", text: "engine.", start: 4.35, end: 4.9, speaker: "Host", confidence: 0.99 },
    ];

    const res = await fetch(`/api/v1/transcript/${currentMediaId}/words`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ words: sampleWords }),
    });
    if (!res.ok) throw new Error("Failed to load sample transcript words");

    await refreshTimeline();
    await fetchSmartSuggestions();
  } catch (err) {
    showErrorModal("Sample Transcript Error", err.message);
  }
}

async function exportTranscript() {
  if (!currentMediaId) return;
  const fmt = exportFormatSelect.value || "srt";
  window.open(`/api/v1/transcript/${currentMediaId}/export?format=${fmt}`, "_blank");
}

// --- Captions Studio Styling & Presets ---
function applyCaptionPreset(preset) {
  if (preset === "clean_white") {
    captionTextColor.value = "#FFFFFF";
    captionOutlineColor.value = "#000000";
    captionOutlineWidthSlider.value = 2;
    captionBgBox.checked = false;
  } else if (preset === "yellow_karaoke") {
    captionTextColor.value = "#FACC15";
    captionOutlineColor.value = "#000000";
    captionOutlineWidthSlider.value = 3;
    captionBgBox.checked = false;
    executeInstruction("set caption mode to karaoke");
  } else if (preset === "cinematic") {
    captionTextColor.value = "#E2E8F0";
    captionOutlineColor.value = "#0F172A";
    captionOutlineWidthSlider.value = 1;
    captionShadowSlider.value = 3;
  } else if (preset === "boxed") {
    captionTextColor.value = "#FFFFFF";
    captionBgBox.checked = true;
    captionBgColor.value = "#000000";
  } else if (preset === "bold_edu") {
    captionTextColor.value = "#38BDF8";
    captionOutlineColor.value = "#0369A1";
    captionOutlineWidthSlider.value = 4;
  }
  outlineWidthValDisplay.textContent = captionOutlineWidthSlider.value;
  shadowValDisplay.textContent = captionShadowSlider.value;
  applyCaptionStyleFromStudio();
}

async function applyCaptionStyleFromStudio() {
  if (!currentMediaId) return;

  const stylePayload = {
    font_family: captionFontFamilySelect.value,
    font_size: parseInt(captionFontSizeSlider.value),
    text_color: captionTextColor.value,
    outline_color: captionOutlineColor.value,
    outline_width: parseInt(captionOutlineWidthSlider.value),
    shadow_offset: parseInt(captionShadowSlider.value),
    background_box: captionBgBox.checked,
    background_color: captionBgColor.value,
    vertical_position: captionVerticalPos.value,
  };

  try {
    const res = await fetch(`/api/v1/caption-style/${currentMediaId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stylePayload),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiError(error.detail) || "Failed to update caption styling");
    }
    await refreshTimeline();
  } catch (err) {
    showErrorModal("Caption Style Error", err.message);
  }
}

// --- Smart Suggestions & Heuristics ---
async function fetchSmartSuggestions(topic = null) {
  if (!currentMediaId) return;

  try {
    let url = `/api/v1/timeline/${encodeURIComponent(currentMediaId)}/suggestions`;
    if (topic) url += `?topic=${encodeURIComponent(topic)}`;
    const res = await fetch(url);
    if (!res.ok) return;

    const data = await res.json();
    renderSmartSuggestions(data.suggestions || []);
  } catch (e) {
    console.error("Suggestions fetch error:", e);
  }
}

function renderSmartSuggestions(suggestions) {
  suggestionsContainer.innerHTML = "";
  suggestionBadge.textContent = suggestions.length;

  if (suggestions.length === 0) {
    suggestionsContainer.innerHTML = `<div class="empty-state">No editing recommendations right now. Video flow looks clean!</div>`;
    return;
  }

  suggestions.forEach((sug) => {
    const card = document.createElement("div");
    card.className = "suggestion-card";
    card.innerHTML = `
      <div class="sug-header">
        <span class="badge ${sug.type === 'silence' ? 'badge-accent' : 'badge-dim'}">${formatOpName(sug.type)}</span>
        <span class="sug-time font-mono">${sug.start_time ? sug.start_time.toFixed(1) + 's - ' + sug.end_time.toFixed(1) + 's' : ''}</span>
      </div>
      <p class="sug-text">${escapeHtml(sug.description || sug.text)}</p>
      <div class="sug-actions">
        <button class="btn btn-secondary btn-sm sug-apply-btn">Apply Suggestion</button>
      </div>
    `;

    card.querySelector(".sug-apply-btn").addEventListener("click", () => {
      executeInstruction(sug.recommended_instruction || `cut from ${sug.start_time}s to ${sug.end_time}s`);
    });

    suggestionsContainer.appendChild(card);
  });
}

// --- Utilities ---
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatApiError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return String(item);
      const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
      return `${location ? `${location}: ` : ""}${item.msg || JSON.stringify(item)}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") return detail.message || detail.msg || JSON.stringify(detail);
  return detail == null ? "" : String(detail);
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}
