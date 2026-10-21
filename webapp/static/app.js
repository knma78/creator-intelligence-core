const panels = document.querySelectorAll(".panel");
const navItems = document.querySelectorAll(".nav-item");
const jobForm = document.getElementById("jobForm");
const sourceInput = document.getElementById("sourceInput");
const sourceHint = document.getElementById("sourceHint");
const limitInput = document.getElementById("limitInput");
const v3Input = document.getElementById("v3Input");
const kbInput = document.getElementById("kbInput");
const playbackCaptureInput = document.getElementById("playbackCaptureInput");
const captureDurationInput = document.getElementById("captureDurationInput");
const contentWorkOptions = document.getElementById("contentWorkOptions");
const subjectNameInput = document.getElementById("subjectNameInput");
const contentCategoryInput = document.getElementById("contentCategoryInput");
const modeInputs = [...document.querySelectorAll('input[name="mode"]')];
const startButton = document.getElementById("startButton");
const buildKbButton = document.getElementById("buildKbButton");
const buildAdvancedKbButton = document.getElementById("buildAdvancedKbButton");
const douyinAccess = document.getElementById("douyinAccess");
const douyinAccessMessage = document.getElementById("douyinAccessMessage");
const douyinLoginButton = document.getElementById("douyinLoginButton");
const bilibiliAccess = document.getElementById("bilibiliAccess");
const bilibiliAccessMessage = document.getElementById("bilibiliAccessMessage");
const bilibiliAuthButton = document.getElementById("bilibiliAuthButton");
const bilibiliEntitlementButton = document.getElementById("bilibiliEntitlementButton");
const bilibiliEntitlementStatus = document.getElementById("bilibiliEntitlementStatus");
const youtubeAccess = document.getElementById("youtubeAccess");
const youtubeAccessMessage = document.getElementById("youtubeAccessMessage");
const youtubeAuthButton = document.getElementById("youtubeAuthButton");
const refreshJobs = document.getElementById("refreshJobs");
const jobBadge = document.getElementById("jobBadge");
const cancelJobButton = document.getElementById("cancelJobButton");
const progressBar = document.getElementById("progressBar");
const progressTrack = document.getElementById("progressTrack");
const currentStage = document.getElementById("currentStage");
const progressPercent = document.getElementById("progressPercent");
const whisperProgress = document.getElementById("whisperProgress");
const whisperProgressTitle = document.getElementById("whisperProgressTitle");
const whisperProgressTime = document.getElementById("whisperProgressTime");
const whisperDeviceBadge = document.getElementById("whisperDeviceBadge");
const whisperProgressTrack = document.getElementById("whisperProgressTrack");
const whisperProgressBar = document.getElementById("whisperProgressBar");
const whisperRuntimeReason = document.getElementById("whisperRuntimeReason");
const whisperPhasePercent = document.getElementById("whisperPhasePercent");
const stopCaptureButton = document.getElementById("stopCaptureButton");
const logBox = document.getElementById("logBox");
const resultList = document.getElementById("resultList");
const resultMeta = document.getElementById("resultMeta");
const timelineItems = [...document.querySelectorAll(".timeline li")];
const reportForm = document.getElementById("reportForm");
const reportInput = document.getElementById("reportInput");
const reportTopKInput = document.getElementById("reportTopKInput");
const reportRebuildInput = document.getElementById("reportRebuildInput");
const novelForm = document.getElementById("novelForm");
const novelOperationInput = document.getElementById("novelOperationInput");
const novelLanguageInput = document.getElementById("novelLanguageInput");
const novelTargetCharsInput = document.getElementById("novelTargetCharsInput");
const novelTargetLabel = document.getElementById("novelTargetLabel");
const novelCorpusInput = document.getElementById("novelCorpusInput");
const novelNativeReviewWrap = document.getElementById("novelNativeReviewWrap");
const novelNativeReviewInput = document.getElementById("novelNativeReviewInput");
const novelRequestInput = document.getElementById("novelRequestInput");
const novelSourceField = document.getElementById("novelSourceField");
const novelSourceInput = document.getElementById("novelSourceInput");
const novelFormHint = document.getElementById("novelFormHint");
const novelSubmitButton = document.getElementById("novelSubmitButton");
const novelSkillBadge = document.getElementById("novelSkillBadge");
const novelSkillMeta = document.getElementById("novelSkillMeta");
const novelReviewBadge = document.getElementById("novelReviewBadge");
const novelReviewMeta = document.getElementById("novelReviewMeta");
const searchForm = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const searchResults = document.getElementById("searchResults");
const searchBackendMeta = document.getElementById("searchBackendMeta");
const knowledgeRefreshButton = document.getElementById("knowledgeRefreshButton");
const knowledgeBuildButton = document.getElementById("knowledgeBuildButton");
const knowledgeStatus = document.getElementById("knowledgeStatus");
const knowledgeMeta = document.getElementById("knowledgeMeta");
const knowledgeRules = document.getElementById("knowledgeRules");
const knowledgeReviewer = document.getElementById("knowledgeReviewer");
const advisorForm = document.getElementById("advisorForm");
const advisorInput = document.getElementById("advisorInput");
const advisorMinSamplesInput = document.getElementById("advisorMinSamplesInput");
const advisorResults = document.getElementById("advisorResults");
const advisorSubmitButton = document.getElementById("advisorSubmitButton");
const gapRefreshButton = document.getElementById("gapRefreshButton");
const gapDashboard = document.getElementById("gapDashboard");
const gapMeta = document.getElementById("gapMeta");
const discoveryRefreshButton = document.getElementById("discoveryRefreshButton");
const discoveryAbilityInput = document.getElementById("discoveryAbilityInput");
const discoveryMeta = document.getElementById("discoveryMeta");
const discoveryDashboard = document.getElementById("discoveryDashboard");
const candidateForm = document.getElementById("candidateForm");
const candidateNameInput = document.getElementById("candidateNameInput");
const candidatePlatformInput = document.getElementById("candidatePlatformInput");
const candidateAbilityInput = document.getElementById("candidateAbilityInput");
const candidateUrlInput = document.getElementById("candidateUrlInput");
const historyList = document.getElementById("historyList");
const productionForm = document.getElementById("productionForm");
const productionModeSelect = document.getElementById("productionModeSelect");
const productionScriptFields = document.getElementById("productionScriptFields");
const productionClipFields = document.getElementById("productionClipFields");
const productionTitleInput = document.getElementById("productionTitleInput");
const productionScriptInput = document.getElementById("productionScriptInput");
const productionScriptHint = document.getElementById("productionScriptHint");
const productionVoiceSelect = document.getElementById("productionVoiceSelect");
const productionRateSelect = document.getElementById("productionRateSelect");
const productionSourceSelect = document.getElementById("productionSourceSelect");
const productionSourceHint = document.getElementById("productionSourceHint");
const productionPlatformSelect = document.getElementById("productionPlatformSelect");
const productionTargetInput = document.getElementById("productionTargetInput");
const productionTargetField = document.getElementById("productionTargetField");
const productionFpsSelect = document.getElementById("productionFpsSelect");
const productionEngineField = document.getElementById("productionEngineField");
const productionSubtitleInput = document.getElementById("productionSubtitleInput");
const productionRefreshButton = document.getElementById("productionRefreshButton");
const productionPlanButton = document.getElementById("productionPlanButton");
const productionRenderButton = document.getElementById("productionRenderButton");
const productionPlanMeta = document.getElementById("productionPlanMeta");
const productionPlanPreview = document.getElementById("productionPlanPreview");
const productionFfmpegBadge = document.getElementById("productionFfmpegBadge");
const productionGpuBadge = document.getElementById("productionGpuBadge");
const productionCapcutBadge = document.getElementById("productionCapcutBadge");
const productionJobBadge = document.getElementById("productionJobBadge");
const productionCancelButton = document.getElementById("productionCancelButton");
const productionStage = document.getElementById("productionStage");
const productionProgressPercent = document.getElementById("productionProgressPercent");
const productionProgressTrack = document.getElementById("productionProgressTrack");
const productionProgressBar = document.getElementById("productionProgressBar");
const productionJobLog = document.getElementById("productionJobLog");
const productionFiles = document.getElementById("productionFiles");
const serverState = document.getElementById("serverState");
const runtimeStateLabel = document.getElementById("runtimeStateLabel");
const gpuStateLabel = document.getElementById("gpuStateLabel");
const modelStateLabel = document.getElementById("modelStateLabel");
const clockLabel = document.getElementById("clockLabel");

let activeJobId = null;
let pollTimer = null;
let pollInFlightKey = null;
let pollGeneration = 0;
let advisorAvailable = false;
let gapAvailable = false;
let discoveryAvailable = false;
let advancedKnowledgeAvailable = false;
let novelWritingAvailable = false;
let nativeEnglishReviewAvailable = false;
let douyinStatusTimer = null;
let whisperRuntime = null;
const platformAuthState = {
  bilibili: null,
  youtube: null,
};
let platformAuthStatusTimer = null;
let productionSources = [];
let productionRuntime = null;
let productionJobId = null;

const gapStatusLabels = {
  empty: "暂无数据",
  excellent: "优秀",
  healthy: "健康",
  watch: "需要关注",
  weak: "薄弱",
  missing: "缺失",
  learning: "学习中",
  usable: "可用",
  mature: "成熟",
  unknown: "未知",
};

const gapActionLabels = {
  collect_more_reference_videos: "补充参考视频",
  monitor: "持续观察",
};

function gapStatusLabel(value) {
  return gapStatusLabels[String(value || "").toLowerCase()] || value || "未知";
}

function gapActionLabel(value) {
  return gapActionLabels[String(value || "")] || value || "";
}

navItems.forEach((item) => {
  item.addEventListener("click", () => {
    navItems.forEach((button) => button.classList.remove("active"));
    item.classList.add("active");
    panels.forEach((panel) => panel.classList.remove("visible"));
    document.getElementById(item.dataset.panel).classList.add("visible");
    if (item.dataset.panel === "historyPanel") {
      loadHistory();
    }
    if (item.dataset.panel === "gapPanel") {
      loadGapDashboard();
    }
    if (item.dataset.panel === "knowledgePanel") {
      loadKnowledgeStatus();
    }
    if (item.dataset.panel === "discoveryPanel") {
      loadCreatorDiscovery(false);
    }
    if (item.dataset.panel === "productionPanel") {
      loadProductionWorkspace();
      if (productionJobId && productionJobId !== "creating") {
        resumeProductionWatch(productionJobId);
      }
    }
  });
});

jobForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = sourceInput.value.trim();
  if (!source) {
    setLog("请输入 UP 名、UP主页、视频链接或 BV号。");
    return;
  }
  const mode = new FormData(jobForm).get("mode");
  const authPlatform = requiredAuthPlatform(source);
  if (authPlatform && !platformAuthState[authPlatform]?.ready) {
    const label = authPlatform === "bilibili" ? "B站" : "YouTube";
    setLog(`${label}任务需要先完成一次网页登录。`);
    const button = authPlatform === "bilibili" ? bilibiliAuthButton : youtubeAuthButton;
    button.focus();
    return;
  }
  await createJob({
    source,
    mode,
    limit: limitInput.value,
    v3: v3Input.checked,
    build_kb: kbInput.checked,
    allow_playback_capture: playbackCaptureInput.checked,
    capture_duration_seconds: captureDurationInput.value,
    subject_name: mode === "content" ? subjectNameInput.value.trim() : "",
    content_category: mode === "content" ? contentCategoryInput.value : "auto",
  });
});

modeInputs.forEach((input) => {
  input.addEventListener("change", updateTaskMode);
});
updateTaskMode();

productionRefreshButton.addEventListener("click", loadProductionWorkspace);
productionModeSelect.addEventListener("change", updateProductionMode);
productionScriptInput.addEventListener("input", updateProductionSourceState);
productionSourceSelect.addEventListener("change", updateProductionSourceState);
productionPlanButton.addEventListener("click", requestProductionPlan);
productionCancelButton.addEventListener("click", cancelProductionJob);
productionForm.addEventListener("submit", startProductionJob);

function updateTaskMode() {
  const mode = new FormData(jobForm).get("mode");
  const isContent = mode === "content";
  contentWorkOptions.hidden = !isContent;
  contentWorkOptions.classList.toggle("visible", isContent);
  if (isContent) {
    sourceInput.placeholder = "输入B站电影/番剧季页面，或每行一个视频链接/BV号";
    sourceHint.textContent = "综艺、电影、动漫、纪录片及其他B站内容均可学习";
  } else {
    sourceInput.placeholder = "输入 B站视频/电影/番剧季页面、创作者主页或其他平台视频链接";
    sourceHint.textContent = "支持单视频、创作者批量、内容作品和本地媒体";
  }
}

reportForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = reportInput.value.trim();
  if (!source) {
    setLog("请输入研究问题。");
    navItems[0].click();
    return;
  }
  navItems[0].click();
  await createJob({
    source,
    mode: "report",
    limit: reportTopKInput.value,
    build_kb: reportRebuildInput.checked,
  });
});

const novelOperationHints = {
  concept: "故事设定会先建立故事契约，再给出核心冲突、世界规则和推进引擎。",
  outline: "长篇大纲会同时规划宏观结构、篇章阶梯，以及成长、关系与谜团账本。",
  chapter: "章节创作会遵循故事契约、场景转折与章节钩子检查。",
  continue: "续写会继承原文事实、人物状态和情绪连续性，并制造新的不可逆变化。",
  rewrite: "改写会保留核心意图，同时增强因果、人物能动性、代价与具体性。",
  diagnose: "诊断会按 Promise、Causality、Agency、Cost、Payoff 等质量门槛定位问题。",
  revise: "修订会根据你的目标直接交付可替换原文的新版成品。",
};
const novelSourceOperations = new Set(["continue", "rewrite", "diagnose", "revise"]);
const novelLanguageHints = {
  "zh-CN": "使用自然简体中文，保持中国网文的节奏与表达，避免翻译腔。",
  "en-US": "保留中国网文的升级、爽点与钩子，使用母语级美式英语，不做中文句法直译。",
  "en-GB": "保留中国网文的升级、爽点与钩子，使用母语级英式英语和一致拼写。",
};

novelOperationInput.addEventListener("change", updateNovelForm);
novelLanguageInput.addEventListener("change", updateNovelLanguage);
novelForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = novelRequestInput.value.trim();
  const operation = novelOperationInput.value;
  const sourceText = novelSourceInput.value.trim();
  if (!novelWritingAvailable) {
    setLog("本机 novel-writing Skill 当前不可用，请检查 Skill 状态。");
    navItems[0].click();
    return;
  }
  if (!source) {
    novelRequestInput.focus();
    return;
  }
  if (novelSourceOperations.has(operation) && !sourceText) {
    novelSourceInput.focus();
    return;
  }
  navItems[0].click();
  await createJob({
    source,
    mode: "novel",
    operation,
    output_language: novelLanguageInput.value,
    source_text: sourceText,
    target_length: novelTargetCharsInput.value,
    use_corpus_observations: novelCorpusInput.checked,
    native_english_review: novelLanguageInput.value.startsWith("en-")
      && nativeEnglishReviewAvailable
      && novelNativeReviewInput.checked,
    auto_native_revision: novelLanguageInput.value.startsWith("en-")
      && nativeEnglishReviewAvailable
      && novelNativeReviewInput.checked,
  });
});
updateNovelLanguage();

function updateNovelForm() {
  const operation = novelOperationInput.value;
  const sourceRequired = novelSourceOperations.has(operation);
  novelSourceField.hidden = !sourceRequired;
  novelSourceInput.required = sourceRequired;
  const languageHint = novelLanguageHints[novelLanguageInput.value] || "";
  const operationHint = novelOperationHints[operation] || "使用本机 novel-writing Skill 执行任务。";
  novelFormHint.textContent = `${languageHint} ${operationHint}`;
}

function updateNovelLanguage() {
  const english = novelLanguageInput.value.startsWith("en-");
  novelNativeReviewWrap.hidden = !english;
  novelTargetLabel.textContent = english ? "目标词数" : "目标字数";
  if (english && novelTargetCharsInput.value === "3000") {
    novelTargetCharsInput.value = "1500";
  } else if (!english && novelTargetCharsInput.value === "1500") {
    novelTargetCharsInput.value = "3000";
  }
  updateNovelForm();
}

buildKbButton.addEventListener("click", async () => {
  await startSystemJob("/api/kb/build", "知识库任务创建失败。");
});

buildAdvancedKbButton.addEventListener("click", async () => {
  await startSystemJob("/api/kb/advanced", "完整知识系统任务创建失败。");
});

douyinLoginButton.addEventListener("click", startDouyinLogin);
bilibiliAuthButton.addEventListener("click", () => startPlatformLogin("bilibili"));
bilibiliEntitlementButton.addEventListener("click", checkBilibiliEntitlement);
stopCaptureButton.addEventListener("click", stopPlaybackCapture);
cancelJobButton.addEventListener("click", cancelActiveJob);
youtubeAuthButton.addEventListener("click", () => startPlatformLogin("youtube"));

knowledgeBuildButton.addEventListener("click", async () => {
  await startSystemJob("/api/kb/advanced", "完整知识系统任务创建失败。");
});

knowledgeRefreshButton.addEventListener("click", loadKnowledgeStatus);
knowledgeRules.addEventListener("click", handleKnowledgeRuleReview);

refreshJobs.addEventListener("click", loadHistory);

if (gapRefreshButton) {
  gapRefreshButton.addEventListener("click", loadGapDashboard);
}

discoveryRefreshButton.addEventListener("click", () => loadCreatorDiscovery(true));

candidateForm.addEventListener("submit", addDiscoveryCandidate);

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;
  searchResults.innerHTML = `<div class="empty-state">检索中...</div>`;
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: 8 }),
  });
  const payload = await response.json();
  if (!response.ok) {
    searchResults.innerHTML = `<div class="empty-state">${escapeHtml(payload.error || "检索失败")}</div>`;
    return;
  }
  if (searchBackendMeta) {
    searchBackendMeta.textContent = `当前检索策略：${payload.backend || "lexical"}`;
  }
  renderSearchResults(payload.results || []);
});

advisorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!advisorAvailable) {
    renderServerUpgradeRequired();
    return;
  }
  const target = advisorInput.value.trim();
  if (!target) {
    advisorResults.innerHTML = `<div class="empty-state error-state">请先输入想补强的内容方向、候选 UP 类型或具体疑问。</div>`;
    return;
  }

  const buttonLabel = advisorSubmitButton.querySelector(".button-label");
  advisorSubmitButton.disabled = true;
  buttonLabel.textContent = "分析中...";
  advisorResults.innerHTML = `<div class="empty-state loading-state">正在读取知识库并调用 AI，通常需要 10 到 60 秒...</div>`;

  try {
    const response = await fetch("/api/up-advisor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target,
        min_samples: advisorMinSamplesInput.value,
      }),
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : { error: await response.text() };
    if (response.status === 404) {
      advisorAvailable = false;
      advisorSubmitButton.disabled = true;
      throw new Error("当前运行的是旧版后端，不包含 AI 顾问接口。请关闭旧服务后重新启动 Web UI。");
    }
    if (!response.ok) {
      throw new Error(payload.error || `请求失败（HTTP ${response.status}）`);
    }
    renderAdvisorResults(payload);
  } catch (error) {
    advisorResults.innerHTML = `
      <div class="empty-state error-state">
        <strong>分析没有完成</strong>
        <span>${escapeHtml(error.message || "无法连接本地服务，请确认网页服务仍在运行。")}</span>
      </div>
    `;
  } finally {
    advisorSubmitButton.disabled = !advisorAvailable;
    buttonLabel.textContent = "AI 分析";
  }
});

async function checkServerCapabilities() {
  advisorSubmitButton.disabled = true;
  if (gapRefreshButton) gapRefreshButton.disabled = true;
  discoveryRefreshButton.disabled = true;
  buildAdvancedKbButton.disabled = true;
  knowledgeBuildButton.disabled = true;
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    gapAvailable = Boolean(payload.features?.gap_analysis);
    discoveryAvailable = Boolean(payload.features?.creator_discovery);
    advancedKnowledgeAvailable = Boolean(payload.features?.advanced_knowledge);
    renderNovelSkillStatus(payload.local_skills?.["novel-writing"] || {});
    renderEnglishReviewStatus(payload.english_review || {});
    whisperRuntime = payload.whisper || null;
    if (gapRefreshButton) gapRefreshButton.disabled = !gapAvailable;
    discoveryRefreshButton.disabled = !discoveryAvailable;
    buildAdvancedKbButton.disabled = !advancedKnowledgeAvailable;
    knowledgeBuildButton.disabled = !advancedKnowledgeAvailable;
    if (!payload.features?.up_advisor) {
      throw new Error("缺少 UP 决策能力");
    }
    advisorAvailable = true;
    advisorSubmitButton.disabled = false;
    const model = payload.llm?.configured ? payload.llm.model : "AI未配置";
    const runtimeLabel = whisperRuntime?.device === "cuda"
      ? `GPU ${whisperRuntime.gpu_name || "CUDA"}`
      : `CPU${whisperRuntime?.reason ? `：${whisperRuntime.reason}` : ""}`;
    serverState.textContent = `本地服务运行中 · ${model} · Whisper ${runtimeLabel}`;
    runtimeStateLabel.textContent = "正常";
    gpuStateLabel.textContent = whisperRuntime?.device === "cuda"
      ? `GPU · ${whisperRuntime.compute_type || "CUDA"}`
      : "CPU";
    modelStateLabel.textContent = model;
    await Promise.all([loadPlatformAuthStatuses(), loadDouyinStatus()]);
  } catch (error) {
    advisorAvailable = false;
    gapAvailable = false;
    discoveryAvailable = false;
    advancedKnowledgeAvailable = false;
    renderNovelSkillStatus({ available: false, reason: "无法连接本地服务" });
    renderEnglishReviewStatus({ available: false, reason: "无法连接本地服务" });
    if (gapRefreshButton) gapRefreshButton.disabled = true;
    discoveryRefreshButton.disabled = true;
    buildAdvancedKbButton.disabled = true;
    knowledgeBuildButton.disabled = true;
    advisorSubmitButton.disabled = true;
    serverState.textContent = "后端版本过旧，需要重启";
    runtimeStateLabel.textContent = "异常";
    gpuStateLabel.textContent = "--";
    modelStateLabel.textContent = "--";
    renderServerUpgradeRequired();
  }
}

function renderNovelSkillStatus(skill) {
  novelWritingAvailable = Boolean(skill.available);
  novelSubmitButton.disabled = !novelWritingAvailable;
  novelSkillBadge.className = `novel-skill-badge ${novelWritingAvailable ? "ready" : "error"}`;
  novelSkillBadge.textContent = novelWritingAvailable ? "SKILL READY" : "SKILL UNAVAILABLE";
  if (novelWritingAvailable) {
    const capabilityCount = Array.isArray(skill.capabilities) ? skill.capabilities.length : 0;
    novelSkillMeta.textContent = `${skill.name || "novel-writing"} · ${capabilityCount} 项能力 · ${skill.fingerprint || "已加载"}`;
    novelSkillMeta.title = skill.path || "";
  } else {
    novelSkillMeta.textContent = skill.reason || "找不到本机 novel-writing Skill";
    novelSkillMeta.title = skill.path || "";
  }
}

function renderEnglishReviewStatus(runtime) {
  const skillReady = Boolean(runtime.skill?.available);
  nativeEnglishReviewAvailable = Boolean(runtime.available && skillReady);
  novelNativeReviewInput.disabled = !nativeEnglishReviewAvailable;
  const fullyReady = Boolean(
    nativeEnglishReviewAvailable && runtime.harper?.available && runtime.readability?.available
  );
  const state = fullyReady ? "ready" : (nativeEnglishReviewAvailable ? "warning" : "error");
  novelReviewBadge.className = `novel-skill-badge ${state}`;
  novelReviewBadge.textContent = fullyReady
    ? "NATIVE QA READY"
    : (nativeEnglishReviewAvailable ? "NATIVE QA CORE" : "NATIVE QA UNAVAILABLE");
  if (!nativeEnglishReviewAvailable) {
    novelReviewMeta.textContent = runtime.reason || runtime.skill?.reason || "英语质检 Skill 或审稿模型不可用";
    novelReviewMeta.title = runtime.skill?.path || "";
    return;
  }
  const harper = runtime.harper?.available ? "Harper CLI" : "内置地区检查";
  const readability = runtime.readability?.available ? "内置可读性 v2" : "可读性不可用";
  novelReviewMeta.textContent = `${runtime.review_model || "独立审稿模型"} · ${harper} · ${readability}`;
  novelReviewMeta.title = runtime.skill?.path || "";
}

async function loadPlatformAuthStatuses() {
  try {
    const response = await fetch("/api/platform-auth/status", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    renderPlatformAuthStatus("bilibili", payload.platforms?.bilibili || {});
    renderPlatformAuthStatus("youtube", payload.platforms?.youtube || {});
  } catch (error) {
    for (const platform of ["bilibili", "youtube"]) {
      renderPlatformAuthStatus(platform, {
        state: "failed",
        ready: false,
        message: error.message || "无法读取 Cookie 授权状态",
      });
    }
  }
}

async function startPlatformLogin(platform) {
  const label = platform === "bilibili" ? "B站" : "YouTube";
  const button = platform === "bilibili" ? bilibiliAuthButton : youtubeAuthButton;
  button.disabled = true;
  renderPlatformAuthStatus(platform, {
    state: "running",
    ready: false,
    message: `正在打开${label}登录窗口`,
  });
  try {
    const response = await fetch("/api/platform-auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    renderPlatformAuthStatus(platform, payload);
    setLog(`请在打开的窗口中完成${label}登录。`);
  } catch (error) {
    renderPlatformAuthStatus(platform, {
      state: "failed",
      ready: false,
      message: error.message || `无法启动${label}登录`,
    });
    setLog(error.message || `无法启动${label}登录。`);
  } finally {
    if (platformAuthState[platform]?.state !== "running") {
      button.disabled = false;
    }
  }
}

async function checkBilibiliEntitlement() {
  const source = sourceInput.value.trim();
  if (!source || !/(?:bilibili\.com|b23\.tv|BV[0-9A-Za-z]+)/i.test(source)) {
    bilibiliEntitlementStatus.textContent = "请先输入可识别的B站视频或内容季链接。";
    return;
  }
  bilibiliEntitlementButton.disabled = true;
  bilibiliEntitlementStatus.textContent = "正在分别检查账号、作品访问条件和建议采集方案...";
  try {
    const response = await fetch("/api/bilibili/entitlement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "权限检测失败");
    const eligible = payload.viewing_eligible === true
      ? "已通过"
      : payload.viewing_eligible === false
        ? "未通过"
        : "无法确认";
    const media = payload.official_subtitle_available === true
      ? "已有官方字幕"
      : payload.media_stream_available === true
      ? "可直接下载"
      : payload.media_stream_available === false
        ? "没有可下载流"
        : "将在任务中探测";
    bilibiliEntitlementStatus.textContent =
      `账号权限：${payload.account_tier || "未知"}`
      + `${payload.account_valid_until ? `（有效至 ${payload.account_valid_until}）` : ""}`
      + `；内容权限：${entitlementRequirementLabel(payload.content_requirement)}，${eligible}`
      + `；直接下载：${media}`
      + `；建议方案：${acquisitionStrategyLabel(payload.recommended_strategy)}。`;
  } catch (error) {
    bilibiliEntitlementStatus.textContent = error.message || "权限检测失败。";
  } finally {
    bilibiliEntitlementButton.disabled = false;
  }
}

async function stopPlaybackCapture() {
  if (!activeJobId) return;
  stopCaptureButton.disabled = true;
  try {
    const response = await fetch(
      `/api/jobs/${activeJobId}/stop-capture`,
      { method: "POST" },
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法停止录制");
    stopCaptureButton.textContent = "正在停止...";
  } catch (error) {
    setLog(`${logBox.textContent}\n\n${error.message || "无法停止录制。"}`);
    stopCaptureButton.disabled = false;
  }
}

function entitlementRequirementLabel(value) {
  return {
    public: "公开内容",
    vip: "大会员专享",
    purchase: "需单独购买",
  }[value] || value || "未知";
}

function acquisitionStrategyLabel(value) {
  return {
    platform_auto: "平台自动采集",
    platform_subtitle: "官方字幕",
    direct_download: "直接下载",
    browser_playback_capture: "本地播放采集",
    manual_import: "人工导入",
    local_file: "本地文件",
  }[value] || value || "未知";
}

function renderPlatformAuthStatus(platform, payload) {
  platformAuthState[platform] = payload;
  const access = platform === "bilibili" ? bilibiliAccess : youtubeAccess;
  const message = platform === "bilibili" ? bilibiliAccessMessage : youtubeAccessMessage;
  const button = platform === "bilibili" ? bilibiliAuthButton : youtubeAuthButton;
  const state = payload.ready ? "ready" : (payload.state || "required");
  const label = platform === "bilibili" ? "B站" : "YouTube";
  access.dataset.state = state;
  message.textContent = payload.message || "首次使用前需要网页登录";
  button.querySelector("span:last-child").textContent =
    payload.ready ? "重新登录" : (state === "running" ? "等待登录" : `登录${label}`);
  button.disabled = state === "running";

  if (platformAuthStatusTimer) {
    clearTimeout(platformAuthStatusTimer);
    platformAuthStatusTimer = null;
  }
  if (Object.values(platformAuthState).some((item) => item?.state === "running")) {
    platformAuthStatusTimer = setTimeout(loadPlatformAuthStatuses, 2000);
  }
}

function requiredAuthPlatform(source) {
  const value = String(source || "").trim();
  if (/^(?:[a-zA-Z]:[\\/]|\\\\|\/)/.test(value)) return null;
  if (/(?:youtube\.com|youtu\.be)/i.test(value)) return "youtube";
  if (/(?:bilibili\.com|b23\.tv)/i.test(value) || /^BV[0-9A-Za-z]+$/i.test(value)) {
    return "bilibili";
  }
  if (/(?:douyin\.com|iesdouyin\.com|xiaohongshu\.com|xhslink\.com)/i.test(value)) {
    return null;
  }
  if (/^https?:\/\//i.test(value)) return null;
  return "bilibili";
}

async function loadDouyinStatus() {
  try {
    const response = await fetch("/api/douyin/status", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    renderDouyinStatus(payload);
  } catch (error) {
    renderDouyinStatus({
      state: "failed",
      ready: false,
      message: error.message || "无法读取抖音登录状态",
    });
  }
}

async function startDouyinLogin() {
  douyinLoginButton.disabled = true;
  renderDouyinStatus({
    state: "running",
    ready: false,
    message: "正在打开抖音登录窗口",
  });
  try {
    const response = await fetch("/api/douyin/login", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法启动抖音登录");
    renderDouyinStatus(payload);
  } catch (error) {
    renderDouyinStatus({
      state: "failed",
      ready: false,
      message: error.message || "无法启动抖音登录",
    });
  } finally {
    douyinLoginButton.disabled = false;
  }
}

function renderDouyinStatus(payload) {
  const state = payload.ready ? "ready" : (payload.state || "required");
  douyinAccess.dataset.state = state;
  douyinAccessMessage.textContent = payload.message || "首次使用前需要网页登录";
  douyinLoginButton.querySelector("span:last-child").textContent =
    payload.ready ? "重新登录" : (state === "running" ? "等待登录" : "登录抖音");
  douyinLoginButton.disabled = state === "running";

  if (douyinStatusTimer) {
    clearTimeout(douyinStatusTimer);
    douyinStatusTimer = null;
  }
  if (state === "running") {
    douyinStatusTimer = setTimeout(loadDouyinStatus, 2000);
  }
}

function renderServerUpgradeRequired() {
  advisorResults.innerHTML = `
    <div class="server-upgrade-state">
      <strong>当前后端没有加载 AI 顾问功能</strong>
      <span>这是旧服务进程仍在运行导致的，不是 API Key 失效。</span>
      <span>关闭原来的命令行窗口，然后重新运行：</span>
      <code>python web_ui.py --port 7860 --open</code>
    </div>
  `;
}

function productionPayload() {
  return {
    production_mode: productionModeSelect.value,
    video_id: productionSourceSelect.value,
    title: productionTitleInput.value.trim(),
    script: productionScriptInput.value.trim(),
    voice: productionVoiceSelect.value,
    tts_rate: productionRateSelect.value,
    platform: productionPlatformSelect.value,
    target_seconds: Number(productionTargetInput.value || 60),
    fps: Number(productionFpsSelect.value || 30),
    burn_subtitles: productionSubtitleInput.checked,
  };
}

async function loadProductionWorkspace() {
  const productionActive = Boolean(productionJobId);
  productionRefreshButton.disabled = true;
  try {
    const [sourcesResponse, runtimeResponse] = await Promise.all([
      fetch("/api/production/sources", { cache: "no-store" }),
      fetch("/api/production/runtime", { cache: "no-store" }),
    ]);
    const sourcesPayload = await sourcesResponse.json();
    const runtime = await runtimeResponse.json();
    if (!sourcesResponse.ok) {
      throw new Error(sourcesPayload.error || "读取研究视频失败。");
    }
    if (!runtimeResponse.ok) {
      throw new Error(runtime.error || "读取视频生产运行时失败。");
    }
    productionSources = sourcesPayload.sources || [];
    const previous = productionSourceSelect.value;
    productionSourceSelect.innerHTML = productionSources.length
      ? productionSources.map((item) => `
          <option value="${escapeHtml(item.video_id)}">
            ${item.source_video_ready && item.subtitle_ready ? "●" : "○"}
            ${escapeHtml(item.title || item.video_id)}
          </option>
        `).join("")
      : `<option value="">暂无可用研究视频</option>`;
    if (productionSources.some((item) => item.video_id === previous)) {
      productionSourceSelect.value = previous;
    }
    productionSourceHint.classList.remove("error");
    productionScriptHint.classList.remove("error");
    renderProductionRuntime(runtime);
    updateProductionSourceState();
  } catch (error) {
    productionSourceHint.textContent = error.message || "视频生产状态加载失败。";
    productionSourceHint.classList.add("error");
    productionRuntime = null;
    productionScriptHint.textContent = error.message || "视频生产状态加载失败。";
    productionScriptHint.classList.add("error");
    updateProductionSourceState();
  } finally {
    productionRefreshButton.disabled = productionActive || Boolean(productionJobId);
  }
}

function renderProductionRuntime(runtime) {
  productionRuntime = runtime;
  const ffmpegReady = Boolean(runtime.ffmpeg?.available);
  const nvencReady = Boolean(runtime.ffmpeg?.nvenc_validated);
  productionFfmpegBadge.className =
    `production-runtime-badge ${ffmpegReady ? "ready" : "warning"}`;
  productionFfmpegBadge.textContent = ffmpegReady
    ? "FFmpeg READY"
    : "FFmpeg UNAVAILABLE";
  productionGpuBadge.className =
    `production-runtime-badge ${nvencReady ? "ready" : "warning"}`;
  productionGpuBadge.textContent = nvencReady
    ? "NVENC VERIFIED"
    : "CPU FALLBACK";
  const capcutReady = Boolean(runtime.capcut?.available);
  productionCapcutBadge.className =
    `production-runtime-badge ${capcutReady ? "ready" : "warning"}`;
  productionCapcutBadge.textContent = capcutReady
    ? "CAPCUT READY"
    : runtime.capcut?.running
      ? "CLOSE CAPCUT TO BUILD"
      : "CAPCUT OFFLINE";
  const scriptRuntime = runtime.script_video || {};
  const ttsEngine = scriptRuntime.tts?.engine === "windows-sapi-com"
    ? "WINDOWS SAPI"
    : "EDGE TTS";
  productionScriptHint.textContent = scriptRuntime.available
    ? `${scriptRuntime.visuals?.cover_count || 0} 张蒸馏封面静帧可检索 · ${ttsEngine} READY · CapCut 草稿自动生成 · 无需手动导入素材`
    : scriptRuntime.capcut?.running
      ? "请先正常关闭 CapCut，再创建新草稿。"
      : "文稿工厂运行时不完整，请检查旁白、FFmpeg、FFprobe 和 CapCut。";
}

function updateProductionMode() {
  const scriptMode = productionModeSelect.value === "script";
  productionScriptFields.hidden = !scriptMode;
  productionClipFields.hidden = scriptMode;
  const subtitleField = productionSubtitleInput.closest("label");
  subtitleField.hidden = scriptMode;
  productionTargetField.hidden = scriptMode;
  productionEngineField.hidden = scriptMode;
  productionScriptInput.disabled = !scriptMode;
  productionScriptInput.required = scriptMode;
  productionTitleInput.disabled = !scriptMode;
  productionVoiceSelect.disabled = !scriptMode;
  productionRateSelect.disabled = !scriptMode;
  productionSourceSelect.disabled = scriptMode;
  productionSourceSelect.required = !scriptMode;
  productionTargetInput.disabled = scriptMode;
  productionSubtitleInput.disabled = scriptMode;
  productionPlanPreview.innerHTML = scriptMode
    ? `<div class="empty-state">输入文稿后可预览粗分镜；正式任务会以 TTS 真实时长重新生成。</div>`
    : `<div class="empty-state">选择研究视频后生成计划；所有保留区间、评分依据和字幕重排都会写入 JSON。</div>`;
  productionPlanMeta.textContent = "尚未生成";
  updateProductionSourceState();
}

function updateProductionSourceState() {
  const productionActive = Boolean(productionJobId);
  productionModeSelect.disabled = productionActive;
  productionRefreshButton.disabled = productionActive;
  productionScriptInput.readOnly = productionActive;
  productionTitleInput.readOnly = productionActive;
  productionVoiceSelect.disabled = productionActive
    || productionModeSelect.value !== "script";
  productionRateSelect.disabled = productionActive
    || productionModeSelect.value !== "script";
  productionSourceSelect.disabled = productionActive
    || productionModeSelect.value === "script";
  productionPlatformSelect.disabled = productionActive;
  productionFpsSelect.disabled = productionActive;
  productionTargetInput.disabled = productionActive
    || productionModeSelect.value === "script";
  productionSubtitleInput.disabled = productionActive
    || productionModeSelect.value === "script";
  if (!productionActive) {
    productionScriptInput.readOnly = false;
    productionTitleInput.readOnly = false;
  }
  if (productionModeSelect.value === "script") {
    const length = productionScriptInput.value.trim().length;
    const ready = length >= 20;
    const runtimeReady = Boolean(productionRuntime?.script_video?.available);
    const runtimeFailed = productionScriptHint.classList.contains("error");
    if (runtimeFailed) {
      // Preserve the actionable workspace loading error until a refresh succeeds.
    } else if (!ready) {
      productionScriptHint.textContent = `还需要 ${Math.max(0, 20 - length)} 个字符才能开始。`;
    } else if (!runtimeReady) {
      productionScriptHint.textContent = productionRuntime?.capcut?.running
        ? `${length} 个字符 · 请先正常关闭 CapCut，再创建新草稿。`
        : `${length} 个字符 · 可预览分镜；旁白、渲染或 CapCut 运行时尚未就绪。`;
    } else {
      productionScriptHint.textContent = `${length} 个字符 · 可生成旁白、分镜、独立字幕、预览和 CapCut 草稿`;
    }
    productionPlanButton.disabled = !ready || productionActive;
    productionRenderButton.disabled = !ready || !runtimeReady || productionActive;
    return;
  }
  const source = productionSources.find(
    (item) => item.video_id === productionSourceSelect.value,
  );
  if (!source) {
    productionSourceHint.textContent = "没有找到已经完成分析的视频。";
    productionPlanButton.disabled = true;
    productionRenderButton.disabled = true;
    return;
  }
  const status = [];
  status.push(source.source_video_ready ? "源视频就绪" : "缺少本地源视频");
  status.push(source.subtitle_ready ? "时间轴字幕就绪" : "缺少有效时间轴字幕");
  if (productionRuntime?.capcut?.running) {
    status.push("请先关闭 CapCut");
  } else if (!productionRuntime?.capcut?.available) {
    status.push("CapCut 草稿环境不可用");
  }
  if (source.duration_seconds) {
    status.push(`原片 ${formatDuration(source.duration_seconds)}`);
  }
  productionSourceHint.textContent = `${source.video_id} · ${status.join(" · ")}`;
  const ready = source.source_video_ready && source.subtitle_ready;
  productionPlanButton.disabled = !ready || productionActive;
  productionRenderButton.disabled = !ready
    || !productionRuntime?.capcut?.available
    || !productionRuntime?.ffmpeg?.available
    || !productionRuntime?.ffprobe?.available
    || productionActive;
}

async function requestProductionPlan() {
  const payload = productionPayload();
  const scriptMode = payload.production_mode === "script";
  if (productionJobId
      || (scriptMode ? payload.script.length < 20 : !payload.video_id)) return;
  productionPlanButton.disabled = true;
  productionPlanMeta.textContent = "正在计算…";
  productionPlanPreview.innerHTML =
    `<div class="empty-state">正在评估字幕密度、开头钩子和结尾收束信号。</div>`;
  try {
    const response = await fetch(
      scriptMode ? "/api/production/script-plan" : "/api/production/plan",
      {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      },
    );
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "自动剪辑计划生成失败。");
    }
    renderProductionPlan(result.plan, result.capability_plan);
  } catch (error) {
    productionPlanMeta.textContent = "生成失败";
    productionPlanPreview.innerHTML =
      `<div class="empty-state">${escapeHtml(error.message || "自动剪辑计划生成失败。")}</div>`;
  } finally {
    updateProductionSourceState();
  }
}

function renderProductionPlan(plan, capabilityPlan = null) {
  const segments = plan.segments || [];
  if (plan.strategy === "distilled_rules_narrated_storyboard") {
    const scenes = plan.scenes || [];
    const inputs = plan.decision_inputs || {};
    const roleLabels = {
      hook: "钩子",
      setup: "铺垫",
      development: "展开",
      payoff: "回报",
    };
    const confidenceLabels = {
      high: "高",
      medium: "中",
      low: "低",
      fallback: "兜底",
    };
    productionPlanMeta.textContent =
      `${scenes.length} 个静帧镜头 · ${inputs.matched_scene_count || 0} 个素材镜头 · ${inputs.unique_matched_asset_count || 0} 张相关封面 · ${inputs.fallback_scene_count || 0} 个安全兜底`;
    productionPlanPreview.innerHTML = `
      <div class="production-plan-summary">
        <div class="production-plan-metric"><span>预计成片</span><strong>${Math.round(plan.output_duration_seconds || 0)}s</strong></div>
        <div class="production-plan-metric"><span>镜头数</span><strong>${scenes.length}</strong></div>
        <div class="production-plan-metric"><span>素材镜头</span><strong>${Number(inputs.matched_scene_count || 0)}</strong></div>
        <div class="production-plan-metric"><span>相关封面</span><strong>${Number(inputs.unique_matched_asset_count || 0)}</strong></div>
        <div class="production-plan-metric"><span>OpenCLIP 封面</span><strong>${Number(inputs.openclip_asset_count || 0)}</strong></div>
        <div class="production-plan-metric"><span>Agent</span><strong>不需要</strong></div>
      </div>
      ${renderCapabilityProposal(plan.capability_plan || capabilityPlan)}
      ${renderCapabilityExecution(plan.capability_execution)}
      <div class="production-segment-list">
        ${scenes.slice(0, 12).map((scene) => `
          <article class="production-segment">
            <div class="production-segment-time">${formatDuration(scene.output_start_seconds)} → ${formatDuration(scene.output_end_seconds)}</div>
            <div class="production-segment-copy">
              <strong>${escapeHtml(scene.visual?.source_title || "本地背景兜底")}</strong>
              <p>${escapeHtml(scene.script_excerpt || "")}</p>
              <div class="production-reasons">
                <span>${escapeHtml(roleLabels[scene.narrative_role] || "展开")}</span>
                <span>${escapeHtml(confidenceLabels[scene.visual?.match_confidence] || "兜底")}置信度</span>
                <span>匹配分 ${Number(scene.visual?.match_score || 0)}</span>
                <span>${escapeHtml(scene.visual?.match_scope === "script" ? "全文主题" : scene.visual?.match_scope === "scene" ? "当前旁白" : "安全兜底")}</span>
              </div>
              <div class="production-reasons">
                ${(scene.visual?.match_reasons || []).slice(0, 3).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}
              </div>
              ${(scene.capability_decisions || []).map((item) => `<p>${escapeHtml(item.rule_id)} · ${escapeHtml(item.name)}：${escapeHtml(item.reason)}（${item.changed ? "已调整边界" : "原分镜已满足"}）</p>`).join("")}
            </div>
          </article>
        `).join("")}
      </div>
    `;
    return;
  }
  const inputs = plan.decision_inputs || {};
  const decisionSignals = [
    inputs.analysis_ready ? "内容结构" : null,
    inputs.enrichment_ready ? "V3增强" : null,
    (inputs.scene_boundaries || []).length ? "场景边界" : null,
    Object.keys(inputs.audio_rhythm || {}).length ? "音频节奏" : null,
    (inputs.visual_labels || []).length ? "视觉语义" : null,
  ].filter(Boolean);
  productionPlanMeta.textContent =
    `${segments.length} 个保留区间 · ${Math.round(plan.output_duration_seconds || 0)} 秒 · ${decisionSignals.length} 类研究信号`;
  productionPlanPreview.innerHTML = `
    <div class="production-plan-summary">
      <div class="production-plan-metric">
        <span>目标时长</span>
        <strong>${Math.round(plan.target_seconds || 0)}s</strong>
      </div>
      <div class="production-plan-metric">
        <span>预计成片</span>
        <strong>${Math.round(plan.output_duration_seconds || 0)}s</strong>
      </div>
      <div class="production-plan-metric">
        <span>选择评分</span>
        <strong>${Number(plan.selection_score || 0).toFixed(1)}</strong>
      </div>
      <div class="production-plan-metric">
        <span>排除字幕</span>
        <strong>${Number(plan.excluded_caption_count || 0)}</strong>
      </div>
    </div>
    <div class="production-reasons">
      ${decisionSignals.map((signal) =>
        `<span>已使用 ${escapeHtml(signal)}</span>`).join("")}
    </div>
    <div class="production-segment-list">
      ${segments.map((segment) => `
        <article class="production-segment">
          <div class="production-segment-time">
            ${formatDuration(segment.source_start_seconds)}
            → ${formatDuration(segment.source_end_seconds)}
          </div>
          <div class="production-segment-copy">
            <strong>${escapeHtml(segment.purpose || "保留片段")}</strong>
            <p>${escapeHtml(segment.text_preview || "")}</p>
            <div class="production-reasons">
              ${(segment.reasons || []).map((reason) =>
                `<span>${escapeHtml(reason)}</span>`).join("")}
            </div>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderCapabilityExecution(execution) {
  if (!execution) return "";
  const applied = execution.applied || [];
  return `<section class="production-capability-guidance">
    <strong>实际分镜决策</strong>
    <p>采用 ${applied.length} 项候选能力，调整 ${Number(execution.changed_boundary_count || 0)} 处边界；旁白未改写。时间依据：${execution.timing_source === "tts_cue_interpolated" ? "TTS 字幕对齐估算" : "文稿长度估算"}。</p>
    ${applied.length ? "" : "<p>当前没有适合自动执行的候选，保留基础分镜。</p>"}
    ${(execution.warnings || []).map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}
    <details><summary>查看采用 / 未采用的原因</summary><ul>
    ${[...applied.map((item) => ({ ...item, decision: "采用" })), ...(execution.not_applied || []).map((item) => ({ ...item, decision: "未采用" }))].map((item) => `<li>${escapeHtml(item.decision)} ${escapeHtml(item.rule_id)} · ${escapeHtml(item.name)}：${escapeHtml(item.reason)}</li>`).join("")}
    </ul></details>
  </section>`;
}

function renderCapabilityProposal(plan) {
  if (!plan) {
    return `<div class="empty-state">创作能力候选暂不可用；不影响分镜预览。</div>`;
  }
  const selections = plan.selections || [];
  if (!selections.length) {
    return `<div class="empty-state">当前文稿没有匹配到知识库能力候选；这不会影响分镜预览。</div>`;
  }
  const layerLabels = {
    opening: "开场",
    narrative_structure: "叙事结构",
    transition: "转场",
    climax: "高潮",
    ending: "结尾",
    workflow: "工作流",
  };
  return `
    <section class="production-capability-guidance">
      <strong>知识库能力候选</strong>
      <p>以下是按文稿匹配出的创作思路，不是硬性规则，不会自动改写文稿。</p>
      <div class="production-reasons">
        ${selections.map((selection) => {
          const primary = selection.primary || {};
          const secondary = selection.secondary || [];
          const names = [primary.name, ...secondary.map((item) => item.name)]
            .filter(Boolean)
            .map(escapeHtml);
          return `<span>${escapeHtml(layerLabels[selection.layer] || selection.layer)}：${names.join(" / ")}</span>`;
        }).join("")}
      </div>
    </section>
  `;
}

async function startProductionJob(event) {
  event.preventDefault();
  const payload = productionPayload();
  const scriptMode = payload.production_mode === "script";
  if ((scriptMode ? payload.script.length < 20 : !payload.video_id)
      || productionRenderButton.disabled) return;
  productionJobId = "creating";
  updateProductionSourceState();
  productionRenderButton.disabled = true;
  productionPlanButton.disabled = true;
  productionCancelButton.hidden = true;
  productionJobBadge.className = "badge running";
  productionJobBadge.textContent = "创建任务";
  setProductionProgress(3, "正在创建视频生产任务");
  productionJobLog.textContent = "正在写入持久任务队列…";
  resetProductionFiles("正在创建新任务，输出文件将在完成后显示。");
  try {
    const response = await fetch(
      scriptMode ? "/api/production/script-render" : "/api/production/render",
      {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      },
    );
    const job = await response.json();
    if (!response.ok) {
      throw new Error(job.error || "视频生产任务创建失败。");
    }
    productionJobId = job.id;
    watchJob(job.id);
  } catch (error) {
    if (productionJobId === "creating") productionJobId = null;
    productionJobBadge.className = "badge failed";
    productionJobBadge.textContent = "创建失败";
    productionJobLog.textContent = error.message || "视频生产任务创建失败。";
    updateProductionSourceState();
  }
}

function setProductionProgress(value, stage = "") {
  const normalized = Math.max(0, Math.min(100, Number(value) || 0));
  productionProgressBar.style.width = `${normalized}%`;
  productionProgressPercent.textContent = `${Math.round(normalized)}%`;
  productionStage.textContent = stage || "等待开始";
  productionProgressTrack.setAttribute(
    "aria-valuenow",
    String(Math.round(normalized)),
  );
}

function renderProductionJob(job) {
  const isProduction = ["video_production", "script_video"].includes(
    job.payload?.mode,
  );
  if (!isProduction) {
    productionCancelButton.hidden = true;
    return;
  }
  productionJobBadge.className = `badge ${job.status || "idle"}`;
  productionJobBadge.textContent = statusLabel(job);
  const active = ["queued", "running"].includes(job.status);
  if (active) {
    if (productionJobId !== job.id) {
      resetProductionFiles("任务正在运行，输出文件将在完成后显示。");
    }
    productionJobId = job.id;
  } else if (productionJobId === job.id) {
    productionJobId = null;
  }
  productionCancelButton.hidden = !active;
  productionCancelButton.disabled = Boolean(job.cancel_requested);
  productionCancelButton.textContent = job.cancel_requested
    ? "正在取消…"
    : job.status === "queued"
      ? "取消排队"
      : "取消任务";
  updateProductionSourceState();
  setProductionProgress(job.progress || 0, progressStageLabel(job));
  productionJobLog.textContent = (job.logs || []).join("\n\n");
  productionJobLog.scrollTop = productionJobLog.scrollHeight;
  if (job.status === "failed") {
    productionFiles.classList.remove("empty");
    productionFiles.innerHTML =
      `<div class="empty-state">${escapeHtml(job.error || "视频生产失败。")}</div>`;
  } else if (job.status === "cancelled") {
    productionFiles.classList.remove("empty");
    productionFiles.innerHTML =
      `<div class="empty-state cancelled-state">任务已安全取消；不完整的临时成片已清理，研究包和剪辑计划会保留。</div>`;
  } else if (job.status === "done" && job.result) {
    renderProductionFiles(job.result.files || []);
  }
}

function resetProductionFiles(message) {
  productionFiles.classList.add("empty");
  productionFiles.innerHTML =
    `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderProductionFiles(files) {
  productionFiles.classList.remove("empty");
  productionFiles.innerHTML = files.length
    ? files.map((file) => `
        <a class="file-link" href="${file.url}" target="_blank" rel="noreferrer">
          <span class="file-title">${escapeHtml(file.label)}</span>
          <span class="file-path">${escapeHtml(file.path)}</span>
        </a>
      `).join("")
    : `<div class="empty-state">任务完成，但没有生成可展示文件。</div>`;
}

async function startSystemJob(endpoint, fallbackError) {
  navItems[0].click();
  const response = await fetch(endpoint, { method: "POST" });
  const job = await response.json();
  if (!response.ok) {
    setLog(job.error || fallbackError);
    return;
  }
  watchJob(job.id);
}

async function createJob(payload) {
  startButton.disabled = true;
  cancelJobButton.hidden = true;
  setBadge("running", "创建任务");
  setProgress(3);
  setLog("正在创建任务...");
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const job = await response.json();
  if (!response.ok) {
    startButton.disabled = false;
    setBadge("failed", "创建失败");
    setLog(job.error || "任务创建失败。");
    return;
  }
  watchJob(job.id);
}

function watchJob(jobId) {
  activeJobId = jobId;
  const generation = ++pollGeneration;
  clearInterval(pollTimer);
  pollJob(jobId, generation);
  pollTimer = setInterval(() => pollJob(jobId, generation), 750);
}

function resumeProductionWatch(jobId) {
  if (!jobId || jobId === "creating") return;
  activeJobId = jobId;
  const generation = ++pollGeneration;
  clearInterval(pollTimer);
  pollTimer = setInterval(() => pollJob(jobId, generation), 750);
}

async function pollJob(jobId = activeJobId, generation = pollGeneration) {
  if (!jobId || generation !== pollGeneration) return;
  const requestKey = `${generation}:${jobId}`;
  if (pollInFlightKey === requestKey) return;
  pollInFlightKey = requestKey;
  try {
    const response = await fetch(`/api/jobs/${jobId}`, {
      cache: "no-store",
    });
    const job = await response.json();
    if (generation !== pollGeneration || jobId !== activeJobId) return;
    if (!response.ok) {
      clearInterval(pollTimer);
      setBadge("failed", "任务丢失");
      return;
    }
    renderJob(job);
    if (["done", "failed", "cancelled"].includes(job.status)) {
      clearInterval(pollTimer);
      startButton.disabled = false;
      if (["video_production", "script_video"].includes(job.payload?.mode)) {
        if (productionJobId === job.id) productionJobId = null;
        productionCancelButton.hidden = true;
        updateProductionSourceState();
      }
      loadHistory();
    }
  } catch (error) {
    if (generation === pollGeneration && jobId === activeJobId) {
      setBadge("running", "连接恢复中");
    }
  } finally {
    if (pollInFlightKey === requestKey) pollInFlightKey = null;
  }
}

function renderJob(job) {
  renderProductionJob(job);
  setBadge(job.status, statusLabel(job));
  const active = ["queued", "running"].includes(job.status);
  cancelJobButton.hidden = !active;
  cancelJobButton.disabled = Boolean(job.cancel_requested);
  cancelJobButton.textContent = job.cancel_requested
    ? "正在取消…"
    : job.status === "queued"
      ? "取消排队"
      : "取消任务";
  setProgress(job.progress || 0, progressStageLabel(job));
  renderWhisperProgress(job);
  setTimeline(job.stage || "");
  setLog((job.logs || []).join("\n\n"));
  if (job.status === "failed") {
    resultMeta.textContent = "任务失败";
    resultList.classList.remove("empty");
    resultList.innerHTML = `<div class="empty-state">${escapeHtml(job.error || "未知错误")}</div>`;
  }
  if (job.status === "cancelled") {
    resultMeta.textContent = "任务已取消";
    resultList.classList.remove("empty");
    resultList.innerHTML = `<div class="empty-state cancelled-state">任务已安全取消；已完成的缓存会保留，重新提交时可继续复用。</div>`;
  }
  if (job.status === "done" && job.result) {
    renderFiles(job.result.files || []);
    const summary = [];
    if (job.result.type === "report") summary.push("V4报告");
    if (job.result.capcut_draft_path) summary.push("CapCut 草稿就绪");
    else if (job.result.type === "video_production") summary.push("自动成片");
    if (job.result.type === "advanced_knowledge") summary.push("知识系统已更新");
    if (job.result.type === "novel_writing") {
      summary.push(job.result.operation_label || "小说创作");
      summary.push(job.result.output_language_label || "简体中文");
      summary.push(`${job.result.output_length || job.result.output_chars || 0} ${job.result.length_unit || "字"}`);
      if (job.result.skill?.fingerprint) {
        summary.push(`Skill ${job.result.skill.fingerprint}`);
      }
      if (job.result.native_review) {
        const review = job.result.native_review;
        const decisionLabels = {
          "native-ready": "母语级通过",
          revise: "建议再修订",
          rewrite: "建议重写",
        };
        summary.push(`英语质检 ${review.score}/100`);
        summary.push(decisionLabels[review.decision] || review.decision);
        if (review.revised) summary.push("已自动修订并复检");
      }
    }
    if (job.result.success_count !== undefined) summary.push(`成功 ${job.result.success_count}`);
    if (job.result.failure_count !== undefined) summary.push(`失败 ${job.result.failure_count}`);
    if (job.result.learning_status === "complete") {
      summary.unshift(job.result.platform === "bilibili" ? "该UP已学习完毕" : "该创作者已学习完毕");
    } else if (job.result.learning_status === "complete_after_batch") {
      summary.unshift(job.result.platform === "bilibili" ? "该UP现已学习完毕" : "该创作者现已学习完毕");
    } else if (job.result.learning_status === "no_unseen_candidates") {
      summary.unshift("当前未发现可学习的新视频");
    } else if (Number(job.result.skipped_existing_count) > 0) {
      summary.push(`跳过已学习 ${job.result.skipped_existing_count}`);
    }
    if (job.result.video_id) summary.push(job.result.video_id);
    if (job.result.acquisition) {
      const acquisition = job.result.acquisition;
      const assessment = acquisition.assessment || {};
      if (assessment.account_tier) summary.push(`账号 ${assessment.account_tier}`);
      if (assessment.content_requirement) {
        summary.push(`内容 ${entitlementRequirementLabel(assessment.content_requirement)}`);
      }
      summary.push(`采集 ${acquisitionStrategyLabel(acquisition.selected_strategy)}`);
    }
    if ((job.result.warnings || []).length) {
      setLog(`${(job.logs || []).join("\n\n")}\n\n提示：\n${job.result.warnings.join("\n")}`);
      summary.push(`${job.result.warnings.length} 条降级提示`);
    }
    resultMeta.textContent = summary.join(" · ") || "完成";
    if (job.result.type === "advanced_knowledge") {
      loadKnowledgeStatus();
    }
  }
}

function progressStageLabel(job) {
  const stage = job.stage || "等待任务开始";
  const detail = job.progress_detail || {};
  const nowSeconds = Date.now() / 1000;
  if (job.cancel_requested && job.status === "running") {
    const requestedAt = Number(job.cancel_requested_at);
    const waited = Number.isFinite(requestedAt)
      ? Math.max(0, nowSeconds - requestedAt)
      : 0;
    return `正在取消 · 已等待 ${formatDuration(waited)}`;
  }
  if (job.status !== "running") return stage;

  const startedAt = Number(job.started_at);
  const elapsed = Number.isFinite(startedAt)
    ? Math.max(0, nowSeconds - startedAt)
    : 0;
  if (detail.type === "batch") {
    const current = Number(detail.current || 0);
    const total = Number(detail.total || 0);
    if (total > 0) {
      return `${stage} · ${current}/${total} · 已运行 ${formatDuration(elapsed)}`;
    }
  }
  if (detail.type === "text_generation") {
    const generated = Number(detail.generated_units || detail.generated_chars || 0);
    const target = Number(detail.target_units || detail.target_chars || 0);
    const unit = detail.unit_label || "字";
    const parts = [stage];
    if (target > 0) parts.push(`${generated}/${target} ${unit}`);
    else if (generated > 0) parts.push(`${generated} ${unit}`);
    parts.push(`已运行 ${formatDuration(elapsed)}`);
    return parts.join(" · ");
  }
  if (detail.type === "download") {
    const downloaded = Number(detail.downloaded_bytes || 0);
    const total = Number(detail.total_bytes || 0);
    const speed = Number(detail.speed_bytes_per_second || 0);
    const phase = Number(detail.phase_percent);
    const parts = [stage];
    if (Number.isFinite(phase)) parts.push(`${phase.toFixed(1)}%`);
    if (total > 0) {
      parts.push(`${formatBytes(downloaded)}/${formatBytes(total)}`);
    } else if (downloaded > 0) {
      parts.push(formatBytes(downloaded));
    }
    if (speed > 0) parts.push(`${formatBytes(speed)}/s`);
    parts.push(`已运行 ${formatDuration(elapsed)}`);
    return parts.join(" · ");
  }
  return `${stage} · 已运行 ${formatDuration(elapsed)}`;
}

async function cancelActiveJob() {
  if (!activeJobId || cancelJobButton.disabled) return;
  if (!window.confirm("确认取消当前任务？已完成的缓存会保留。")) return;

  cancelJobButton.disabled = true;
  cancelJobButton.textContent = "正在取消…";
  try {
    const response = await fetch(`/api/jobs/${activeJobId}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const payload = await response.json();
    if (!response.ok) {
      if (payload.job) renderJob(payload.job);
      throw new Error(payload.error || "取消任务失败。");
    }
    renderJob(payload);
    if (payload.status === "cancelled") {
      clearInterval(pollTimer);
      startButton.disabled = false;
      updateProductionSourceState();
      loadHistory();
    }
  } catch (error) {
    cancelJobButton.disabled = false;
    cancelJobButton.textContent = "重试取消";
    setLog(`${logBox.textContent}\n\n${error.message || "取消任务失败。"}`);
  }
}

async function cancelProductionJob() {
  if (!productionJobId || productionJobId === "creating"
      || productionCancelButton.disabled) return;
  if (!window.confirm("确认取消当前视频生产任务？已完成的缓存会保留。")) return;
  const jobId = productionJobId;
  productionCancelButton.disabled = true;
  productionCancelButton.textContent = "正在取消…";
  try {
    const response = await fetch(`/api/jobs/${jobId}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const payload = await response.json();
    if (!response.ok) {
      if (payload.job) renderProductionJob(payload.job);
      throw new Error(payload.error || "取消视频生产任务失败。");
    }
    renderProductionJob(payload);
    watchJob(jobId);
    if (payload.status === "cancelled") {
      productionJobId = null;
      updateProductionSourceState();
      loadHistory();
    }
  } catch (error) {
    productionCancelButton.disabled = false;
    productionCancelButton.textContent = "重试取消";
    productionJobLog.textContent =
      `${productionJobLog.textContent}\n\n${error.message || "取消视频生产任务失败。"}`;
  }
}

function renderFiles(files) {
  resultList.classList.remove("empty");
  if (!files.length) {
    resultList.innerHTML = `<div class="empty-state">没有可展示的输出文件。</div>`;
    return;
  }
  resultList.innerHTML = files
    .map(
      (file) => `
        <a class="file-link" href="${file.url}" target="_blank" rel="noreferrer">
          <span class="file-title">${escapeHtml(file.label)}</span>
          <span class="file-path">${escapeHtml(file.path)}</span>
        </a>
      `,
    )
    .join("");
}

async function loadHistory() {
  let response;
  let payload;
  try {
    response = await fetch("/api/jobs", { cache: "no-store" });
    payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "任务历史读取失败。");
  } catch (error) {
    historyList.innerHTML =
      `<div class="empty-state">${escapeHtml(error.message || "任务历史读取失败。")}</div>`;
    return;
  }
  const jobs = payload.jobs || [];
  const activeProductionJob = jobs
    .slice()
    .reverse()
    .find((job) => (
      ["queued", "running"].includes(job.status)
      && ["video_production", "script_video"].includes(job.payload?.mode)
    ));
  if (activeProductionJob) {
    if (!productionJobId) {
      productionJobId = activeProductionJob.id;
      resetProductionFiles("已恢复正在执行的任务，输出文件将在完成后显示。");
      watchJob(activeProductionJob.id);
    }
  } else if (productionJobId && productionJobId !== "creating") {
    const trackedJob = jobs.find((job) => job.id === productionJobId);
    if (trackedJob && ["done", "failed", "cancelled"].includes(trackedJob.status)) {
      renderProductionJob(trackedJob);
    }
  }
  if (!jobs.length) {
    historyList.innerHTML = `<div class="empty-state">暂无任务记录。</div>`;
    return;
  }
  historyList.innerHTML = jobs
    .slice()
    .reverse()
    .map((job) => {
      const source = job.payload?.video_id
        || job.payload?.source
        || job.payload?.mode
        || "";
      return `
        <button class="history-item" type="button" data-job-id="${job.id}">
          <span class="history-title">${escapeHtml(statusLabel(job))}</span>
          <span class="history-meta">${escapeHtml(source)} · ${escapeHtml(job.id)}</span>
        </button>
      `;
    })
    .join("");
  historyList.querySelectorAll("[data-job-id]").forEach((item) => {
    item.addEventListener("click", () => {
      const selectedJob = jobs.find((job) => job.id === item.dataset.jobId);
      watchJob(item.dataset.jobId);
      const targetPanel = ["video_production", "script_video"].includes(
        selectedJob?.payload?.mode,
      )
        ? "productionPanel"
        : "runPanel";
      document.querySelector(`[data-panel="${targetPanel}"]`)?.click();
    });
  });
}

function renderSearchResults(results) {
  if (!results.length) {
    searchResults.innerHTML = `<div class="empty-state">没有匹配结果。</div>`;
    return;
  }
  searchResults.innerHTML = results
    .map(
      (item) => `
        <a class="search-item" href="/api/file?path=${encodeURIComponent(item.source_path + "/video.md")}" target="_blank" rel="noreferrer">
          <span class="search-title">${escapeHtml(item.title || item.video_id)} · ${escapeHtml(String(item.score))} · ${escapeHtml(item.backend || "lexical")}</span>
          <span class="search-excerpt">${escapeHtml(item.excerpt || "")}</span>
        </a>
      `,
    )
    .join("");
}

async function loadKnowledgeStatus() {
  knowledgeStatus.innerHTML = `<div class="empty-state loading-state">正在检查本地索引和组件...</div>`;
  knowledgeRefreshButton.disabled = true;
  try {
    const response = await fetch("/api/knowledge/status", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    renderKnowledgeStatus(payload);
    await loadKnowledgeRules();
  } catch (error) {
    knowledgeStatus.innerHTML = `<div class="empty-state error-state">${escapeHtml(error.message || "状态读取失败")}</div>`;
    knowledgeMeta.textContent = "知识系统状态读取失败";
  } finally {
    knowledgeRefreshButton.disabled = false;
  }
}

async function loadKnowledgeRules() {
  knowledgeRules.innerHTML = `<div class="empty-state loading-state">正在读取规则及样本证据...</div>`;
  try {
    const response = await fetch("/api/knowledge/rules", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if (!payload.ready) {
      knowledgeRules.innerHTML = `<div class="empty-state">${escapeHtml(payload.message || "规则库尚未生成。")}</div>`;
      return;
    }
    renderKnowledgeRules(payload);
  } catch (error) {
    knowledgeRules.innerHTML = `<div class="empty-state error-state">${escapeHtml(error.message || "规则读取失败")}</div>`;
  }
}

function renderKnowledgeRules(payload) {
  const rules = payload.rules || [];
  if (!rules.length) {
    knowledgeRules.innerHTML = `<div class="empty-state">当前规则库没有规则。</div>`;
    return;
  }
  const statusLabels = {
    candidate: "候选",
    under_review: "复核中",
    validated: "已验证",
    rejected: "已驳回",
    deprecated: "已废弃",
  };
  knowledgeRules.innerHTML = rules.map((rule) => {
    const evidence = rule.evidence || {};
    const review = rule.review || {};
    const examples = evidence.examples || [];
    const condition = (rule.condition || []).join("；");
    const functionText = (rule.intended_function || []).join("；");
    const canReview = Boolean(rule.rule_id);
    return `
      <article class="knowledge-rule-card" data-review-token="${escapeHtml(rule.review_token || "")}">
        <div class="knowledge-rule-title">
          <div><strong>${escapeHtml(rule.name || rule.rule_id)}</strong><span class="muted">${escapeHtml(rule.rule_id)} · ${escapeHtml(rule.layer || "未分类")}</span></div>
          <span class="knowledge-rule-status status-${escapeHtml(rule.status || "candidate")}">${rule.review_pending ? "待完整更新 · " : ""}${escapeHtml(statusLabels[rule.status] || rule.status || "候选")}</span>
        </div>
        <p>${escapeHtml(rule.definition || "")}</p>
        <p class="muted">内容版本 ${Number(rule.content_revision || 1)}${rule.review_required_reason ? ` · ${escapeHtml(rule.review_required_reason)}` : ""}</p>
        <div class="knowledge-rule-meta"><span>条件：${escapeHtml(condition || "未标注")}</span><span>用途：${escapeHtml(functionText || "未标注")}</span></div>
        <details class="knowledge-rule-evidence">
          <summary>证据：${escapeHtml(evidence.evidence_label || "无说明")} · ${Number(evidence.video_count || 0)} 条视频 / ${Number(evidence.creator_count || 0)} 位创作者 · ${Number(evidence.located_observation_count || 0)} 条有时间定位</summary>
          ${evidence.matching_basis ? `<p>匹配依据：${escapeHtml(evidence.matching_basis)}</p>` : ""}
          ${examples.length ? `<ul>${examples.map((item) => `<li>${escapeHtml(item.author || "未知创作者")} · ${escapeHtml(item.video_id || "无视频编号")} · ${escapeHtml(String(item.matched_signal || "样本命中"))}</li>`).join("")}</ul>` : `<p class="muted">当前没有可展示的代表样本。</p>`}
        </details>
        ${review.notes ? `<p class="knowledge-review-note">上次复核：${escapeHtml(review.reviewer || "未知复核人")} · ${escapeHtml(review.notes)}</p>` : ""}
        ${canReview ? `<label class="knowledge-review-notes">复核备注<textarea data-review-notes="${escapeHtml(rule.rule_id)}" rows="2" maxlength="2000" placeholder="可记录证据是否支持定义、适用边界或反例">${escapeHtml(review.notes || "")}</textarea></label>
          <div class="knowledge-review-actions">
            <button type="button" class="primary-button" data-review-rule="${escapeHtml(rule.rule_id)}" data-review-status="validated">批准为已验证</button>
            <button type="button" class="ghost-button" data-review-rule="${escapeHtml(rule.rule_id)}" data-review-status="under_review">暂缓 / 需更多证据</button>
            <button type="button" class="ghost-button danger-button" data-review-rule="${escapeHtml(rule.rule_id)}" data-review-status="rejected">驳回</button>
          </div>` : ""}
      </article>`;
  }).join("");
}

async function handleKnowledgeRuleReview(event) {
  const button = event.target.closest("[data-review-rule]");
  if (!button) return;
  const reviewer = knowledgeReviewer.value.trim();
  if (!reviewer) {
    knowledgeReviewer.focus();
    knowledgeMeta.textContent = "请填写复核人后再登记决定。";
    return;
  }
  const ruleId = button.dataset.reviewRule;
  const notes = knowledgeRules.querySelector(`[data-review-notes="${CSS.escape(ruleId)}"]`)?.value || "";
  const buttons = [...knowledgeRules.querySelectorAll(`[data-review-rule="${CSS.escape(ruleId)}"]`)];
  buttons.forEach((item) => { item.disabled = true; });
  try {
    const response = await fetch("/api/knowledge/rules/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rule_id: ruleId, status: button.dataset.reviewStatus, reviewer, notes,
        review_token: button.closest("[data-review-token]")?.dataset.reviewToken }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    knowledgeMeta.textContent = payload.message || "复核已登记。";
    await loadKnowledgeRules();
  } catch (error) {
    knowledgeMeta.textContent = error.message || "保存复核失败。";
    buttons.forEach((item) => { item.disabled = false; });
  }
}

function renderKnowledgeStatus(payload) {
  const artifactLabels = {
    lexical: "词法索引",
    vector: "语义向量库",
    creator: "创作者知识库",
    templates: "模板库",
    gap: "能力缺口",
    discovery: "创作者发现",
    project: "项目整合报告",
  };
  const dependencyLabels = {
    spacy: "spaCy中文NLP",
    opencv: "OpenCV",
    scenedetect: "PySceneDetect",
    chromadb: "ChromaDB",
    sentence_transformers: "Sentence Transformers",
    langgraph: "LangGraph",
    yt_dlp: "yt-dlp",
  };
  const artifacts = Object.entries(payload.artifacts || {});
  const dependencies = Object.entries(payload.dependencies || {});
  const readyCount = artifacts.filter(([, item]) => item.ready).length;
  knowledgeMeta.textContent = `${readyCount}/${artifacts.length} 项本地产物就绪 · 检索策略 ${payload.search_backend || "lexical"}`;
  knowledgeStatus.innerHTML = `
    <section class="knowledge-group">
      <h3>本地产物</h3>
      <div class="status-list">
        ${artifacts.map(([key, item]) => `
          <div class="status-row">
            <span class="status-indicator ${item.ready ? "ready" : "missing"}"></span>
            <strong>${escapeHtml(artifactLabels[key] || key)}</strong>
            <span>${item.ready ? "已就绪" : (item.stale ? "已过期" : "尚未生成")}</span>
            <small>${item.stale ? escapeHtml(item.reason || "需要重建") : (item.ready && item.updated_at ? escapeHtml(new Date(item.updated_at * 1000).toLocaleString()) : "")}</small>
          </div>
        `).join("")}
      </div>
    </section>
    <section class="knowledge-group">
      <h3>开源组件</h3>
      <div class="component-grid">
        ${dependencies.map(([key, ready]) => `
          <div class="component-item ${ready ? "ready" : "missing"}">
            <span>${escapeHtml(dependencyLabels[key] || key)}</span>
            <strong>${ready ? "可用" : "缺失"}</strong>
          </div>
        `).join("")}
      </div>
      <p class="muted">语义模型：${escapeHtml(payload.semantic_model || "未配置")}</p>
    </section>
  `;
}

async function loadCreatorDiscovery(rebuild) {
  if (!discoveryAvailable) {
    discoveryDashboard.innerHTML = `<div class="empty-state">当前后端未加载创作者发现模块，请重启本地服务。</div>`;
    return;
  }
  discoveryRefreshButton.disabled = true;
  discoveryDashboard.innerHTML = `<div class="empty-state loading-state">正在读取能力缺口并生成候选池...</div>`;
  const ability = discoveryAbilityInput.value.trim();
  try {
    const endpoint = rebuild
      ? "/api/creator-discovery/rebuild"
      : `/api/creator-discovery${ability ? `?ability=${encodeURIComponent(ability)}` : ""}`;
    const response = await fetch(endpoint, {
      method: rebuild ? "POST" : "GET",
      headers: rebuild ? { "Content-Type": "application/json" } : undefined,
      body: rebuild ? JSON.stringify({ ability }) : undefined,
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    renderCreatorDiscovery(payload);
  } catch (error) {
    discoveryDashboard.innerHTML = `<div class="empty-state error-state">${escapeHtml(error.message || "创作者发现失败")}</div>`;
    discoveryMeta.textContent = "创作者发现失败";
  } finally {
    discoveryRefreshButton.disabled = false;
  }
}

function renderCreatorDiscovery(payload) {
  const gaps = payload.ability_gap || [];
  const candidates = payload.creator_candidates || [];
  const plans = payload.search_plan || [];
  const pending = candidates.filter((item) => item.status === "pending_review");
  const waiting = candidates.filter((item) => ["approved", "waiting_analyze"].includes(item.status));
  const platforms = new Set(candidates.map((item) => item.platform).filter(Boolean));
  discoveryMeta.textContent = `${payload.generated_at || "最新"} · ${candidates.length} 个候选 · AI未调用`;
  discoveryDashboard.innerHTML = `
    <div class="discovery-metrics">
      ${renderGapMetric("缺口能力", gaps.length, "项待补强")}
      ${renderGapMetric("候选池", candidates.length, "位候选")}
      ${renderGapMetric("待审核", pending.length, "位候选")}
      ${renderGapMetric("待分析", waiting.length, "位候选")}
    </div>
    <div class="discovery-columns">
      <section class="discovery-block">
        <h3>能力与搜索计划</h3>
        <div class="discovery-gap-list">
          ${gaps.map((item) => {
            const plan = plans.find((value) => value.ability === item.ability_key) || {};
            const platformRows = plan.platforms || [];
            const keywords = [...new Set(platformRows.flatMap((row) => (row.keywords || []).map((value) => value.keyword)))];
            return `
              <article class="discovery-gap-item">
                <div>
                  <strong>${escapeHtml(item.ability_name || item.ability_key)}</strong>
                  <span>缺口 ${escapeHtml(item.gap)} · 优秀创作者 ${escapeHtml(item.current_excellent_creator_count)}/${escapeHtml(item.target_creator_count)}</span>
                </div>
                <p>${platformRows.map((row) => escapeHtml(row.platform)).join(" · ") || "暂无平台建议"}</p>
                <small>${keywords.slice(0, 8).map(escapeHtml).join("、") || "暂无关键词"}</small>
              </article>
            `;
          }).join("") || `<div class="empty-state">当前没有需要发现的能力。</div>`}
        </div>
      </section>
      <section class="discovery-block">
        <h3>平台覆盖</h3>
        <div class="component-grid">
          ${[...platforms].map((platform) => `
            <div class="component-item ready">
              <span>${escapeHtml(platform)}</span>
              <strong>${candidates.filter((item) => item.platform === platform).length}</strong>
            </div>
          `).join("") || `<div class="empty-state">暂无平台数据。</div>`}
        </div>
      </section>
    </div>
    <section class="discovery-block">
      <h3>候选创作者</h3>
      <div class="candidate-list">
        ${candidates.slice(0, 60).map(renderDiscoveryCandidate).join("") || `<div class="empty-state">暂无候选创作者。</div>`}
      </div>
    </section>
  `;
  discoveryDashboard.querySelectorAll("[data-candidate-action]").forEach((button) => {
    button.addEventListener("click", () => handleCandidateAction(button.dataset.candidateAction, button.dataset.candidateId));
  });
}

function renderDiscoveryCandidate(item) {
  const statusLabels = {
    pending_review: "待审核",
    approved: "已批准",
    waiting_analyze: "等待分析",
    analyzing: "分析中",
    analyzed: "已分析",
    failed: "分析失败",
    rejected: "已拒绝",
  };
  let action = "";
  if (item.status === "pending_review") {
    action = `<button class="compact-button" type="button" data-candidate-action="approve" data-candidate-id="${escapeHtml(item.candidate_id)}">批准</button>`;
  } else if (["approved", "waiting_analyze", "failed"].includes(item.status)) {
    const ready = candidateHasAnalyzableSource(item);
    const batch = (item.platform === "bilibili"
      && (!item.source_url || item.source_url.includes("space.bilibili.com")))
      || (item.platform === "youtube" && isYoutubeChannelUrl(item.source_url));
    const label = ready ? (batch ? "分析10条" : "分析视频") : "缺视频链接";
    action = ready
      ? `<button class="compact-button primary" type="button" data-candidate-action="analyze" data-candidate-id="${escapeHtml(item.candidate_id)}">${label}</button>`
      : `<button class="compact-button" type="button" disabled title="请用上方表单补充该候选人的公开视频链接">${label}</button>`;
  }
  return `
    <article class="candidate-item">
      <div class="candidate-main">
        <strong>${escapeHtml(item.creator_name)}</strong>
        <span>${escapeHtml(item.platform)} · ${escapeHtml(item.ability)} · 置信度 ${escapeHtml(item.confidence)}</span>
        <small>${escapeHtml(item.recommend_reason || item.category || "")}</small>
      </div>
      <span class="candidate-status">${escapeHtml(statusLabels[item.status] || item.status)}</span>
      ${action}
    </article>
  `;
}

function candidateHasAnalyzableSource(item) {
  const source = String(item.source_url || "").trim();
  if (item.platform === "bilibili") return Boolean(source || item.creator_name);
  if (item.platform === "youtube") {
    return /(?:youtube\.com\/(?:watch|shorts|live)|youtu\.be\/)/i.test(source)
      || isYoutubeChannelUrl(source);
  }
  if (item.platform === "douyin") {
    return /(?:douyin\.com\/video\/\d+|v\.douyin\.com\/)/i.test(source);
  }
  if (item.platform === "xiaohongshu") {
    return /(?:xiaohongshu\.com\/(?:explore|discovery\/item)\/|xhslink\.com\/)/i.test(source);
  }
  return false;
}

function isYoutubeChannelUrl(source) {
  return /youtube\.com\/(?:@[\w.-]+|channel\/[\w-]+|c\/[\w.-]+|user\/[\w.-]+)/i.test(String(source || ""));
}

async function addDiscoveryCandidate(event) {
  event.preventDefault();
  const platform = candidatePlatformInput.value;
  const sourceUrl = candidateUrlInput.value.trim();
  if (platform !== "bilibili" && !sourceUrl) {
    discoveryMeta.textContent = "YouTube、抖音和小红书候选人需要填写公开视频链接后才能分析。";
    candidateUrlInput.focus();
    return;
  }
  const response = await fetch("/api/creator-discovery/candidates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      creator_name: candidateNameInput.value.trim(),
      platform,
      ability: candidateAbilityInput.value.trim(),
      source_url: sourceUrl,
      recommend_source: "manual_web",
      recommend_reason: "通过本地工作台手动加入候选池。",
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    discoveryMeta.textContent = payload.error || "候选人添加失败";
    return;
  }
  candidateForm.reset();
  await loadCreatorDiscovery(false);
}

async function handleCandidateAction(action, candidateId) {
  const endpoint = action === "approve"
    ? "/api/creator-discovery/approve"
    : "/api/creator-discovery/start-analysis";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_id: candidateId, limit: 10, v3: true, build_kb: true }),
  });
  const payload = await response.json();
  if (!response.ok) {
    discoveryMeta.textContent = payload.error || "候选人操作失败";
    return;
  }
  if (payload.job) {
    navItems[0].click();
    watchJob(payload.job.id);
    return;
  }
  await loadCreatorDiscovery(false);
}

function renderAdvisorResults(payload) {
  const current = payload.current_state || {};
  const target = payload.target_profile || {};
  const recommendations = payload.recommendations || [];
  const plan = payload.crawl_plan || [];
  const checklist = payload.candidate_checklist || [];
  const questions = payload.decision_questions || [];
  const seeds = payload.seed_search_queries || [];
  const files = payload.files || [];
  const ai = payload.ai_analysis || {};

  advisorResults.innerHTML = `
    ${renderAiAnalysis(ai)}

    <div class="advisor-summary">
      <div>
        <span class="metric-value">${escapeHtml(current.video_count || 0)}</span>
        <span class="metric-label">视频样本</span>
      </div>
      <div>
        <span class="metric-value">${escapeHtml(current.creator_count || 0)}</span>
        <span class="metric-label">创作者画像</span>
      </div>
      <div>
        <span class="metric-value">${escapeHtml(current.template_count || 0)}</span>
        <span class="metric-label">模板</span>
      </div>
    </div>

    <section class="advisor-block">
      <h3>目标理解</h3>
      <p>${escapeHtml(target.interpretation || "暂无")}</p>
      <div class="chip-row">
        ${(target.matched_positionings || []).map((item) => `<span class="chip">${escapeHtml(item.positioning)} · ${escapeHtml(item.score)}</span>`).join("")}
      </div>
    </section>

    <section class="advisor-block">
      <h3>建议抓取方向</h3>
      ${recommendations.length ? recommendations.map(renderRecommendation).join("") : `<div class="empty-state">暂无建议。</div>`}
    </section>

    <section class="advisor-block two-column">
      <div>
        <h3>候选判断清单</h3>
        <ul>${checklist.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
      <div>
        <h3>需要确认的问题</h3>
        <ul>${questions.map((item) => `<li>${escapeHtml(item.question)}<span>${escapeHtml(item.why_it_matters)}</span></li>`).join("")}</ul>
      </div>
    </section>

    <section class="advisor-block">
      <h3>下一批抓取计划</h3>
      ${plan.map((item) => `
        <div class="plan-item">
          <strong>Step ${escapeHtml(item.step)} · ${escapeHtml(item.target_positioning)}</strong>
          <span>抓取 ${escapeHtml(item.crawl_count)} 条 · ${escapeHtml(item.selection_rule)}</span>
          <code>${escapeHtml(item.command_hint)}</code>
        </div>
      `).join("")}
    </section>

    <section class="advisor-block">
      <h3>搜索种子</h3>
      <div class="chip-row">${seeds.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("")}</div>
    </section>

    ${files.length ? `
      <section class="advisor-block">
        <h3>输出文件</h3>
        <div class="result-list">${files.map((file) => `
          <a class="file-link" href="${file.url}" target="_blank" rel="noreferrer">
            <span class="file-title">${escapeHtml(file.label)}</span>
            <span class="file-path">${escapeHtml(file.path)}</span>
          </a>
        `).join("")}</div>
      </section>
    ` : ""}
  `;
}

function renderAiAnalysis(ai) {
  const used = Boolean(ai.used);
  const creatorTypes = Array.isArray(ai.recommended_creator_types) ? ai.recommended_creator_types : [];
  const reasons = Array.isArray(ai.reasons) ? ai.reasons : [];
  const avoid = Array.isArray(ai.avoid) ? ai.avoid : [];
  const questions = Array.isArray(ai.next_questions) ? ai.next_questions : [];
  const statusClass = used ? "success" : "warning";
  const statusText = used ? `AI 已完成 · ${ai.model || "未知模型"}` : `AI 未调用 · ${ai.model || "未配置模型"}`;

  return `
    <section class="advisor-block ai-analysis ${statusClass}">
      <div class="ai-analysis-header">
        <h3>AI 判断</h3>
        <span class="ai-status ${statusClass}">${escapeHtml(statusText)}</span>
      </div>
      ${used ? `
        <div class="ai-verdict">
          <strong>${escapeHtml(ai.judgement || "已完成判断")}</strong>
          <span>置信度 ${escapeHtml(ai.confidence ?? "-")} / 100</span>
        </div>
        <p class="ai-answer">${escapeHtml(ai.answer || "")}</p>
        ${reasons.length ? `<div><h4>判断依据</h4><ul>${reasons.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}
        ${creatorTypes.length ? `
          <div>
            <h4>优先寻找的创作者类型</h4>
            <div class="ai-type-list">${creatorTypes.map(renderAiCreatorType).join("")}</div>
          </div>
        ` : ""}
        ${avoid.length ? `<div><h4>暂不建议</h4><ul>${avoid.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}
        ${questions.length ? `<div><h4>下一轮可继续问</h4><ul>${questions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}
      ` : `
        <p class="ai-answer">${escapeHtml(ai.error || "没有配置可用的 AI 接口，下面显示本地规则建议。")}</p>
      `}
    </section>
  `;
}

function renderAiCreatorType(item) {
  return `
    <article class="ai-type-item">
      <div>
        <strong>${escapeHtml(item.positioning || "未命名类型")}</strong>
        <span>${escapeHtml(item.priority || "中")}优先级 · 建议 ${escapeHtml(item.sample_count || 5)} 条</span>
      </div>
      <p>${escapeHtml(item.why || "")}</p>
      <small>${escapeHtml(item.selection_criteria || "")}</small>
    </article>
  `;
}

function renderRecommendation(item) {
  return `
    <div class="recommendation-item">
      <div>
        <strong>${escapeHtml(item.positioning || "Unknown")}</strong>
        <span>${escapeHtml(item.action || "")}</span>
      </div>
      <p>${escapeHtml(item.reason || "")}</p>
      <p>${escapeHtml(item.ideal_candidate || "")}</p>
      <small>当前 ${escapeHtml(item.current_creator_count || 0)} 个 UP / ${escapeHtml(item.current_video_count || 0)} 条，建议新增 ${escapeHtml(item.recommended_next_videos || 0)} 条。</small>
    </div>
  `;
}

async function loadGapDashboard() {
  if (!gapDashboard) return;
  if (!gapAvailable) {
    gapDashboard.innerHTML = `<div class="empty-state loading-state">正在检查本地能力缺口分析模块...</div>`;
  } else {
    gapDashboard.innerHTML = `<div class="empty-state loading-state">正在扫描本地数据库...</div>`;
  }
  if (gapRefreshButton) gapRefreshButton.disabled = true;
  if (gapMeta) gapMeta.textContent = "正在扫描创作者、视频、能力和模板数据库";
  try {
    const response = await fetch("/api/gap-analysis", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    gapAvailable = true;
    renderGapDashboard(payload);
  } catch (error) {
    gapDashboard.innerHTML = `
      <div class="empty-state error-state">
        <strong>能力缺口分析失败</strong>
        <span>${escapeHtml(error.message || "无法扫描本地数据库。")}</span>
      </div>
    `;
    if (gapMeta) gapMeta.textContent = "能力缺口分析失败";
  } finally {
    if (gapRefreshButton) gapRefreshButton.disabled = false;
  }
}

function renderGapDashboard(payload) {
  const dashboard = payload.dashboard || payload;
  const health = dashboard.knowledge_health || payload.knowledge_health || {};
  const gaps = dashboard.gap_ranking || payload.gap_ranking || [];
  const radar = dashboard.ability_radar || payload.ability_ranking || [];
  const heatmap = dashboard.coverage_heatmap || [];
  const creators = dashboard.creator_recommendation || payload.recommended_creator || [];
  const videos = dashboard.recommended_video_count || payload.recommended_video_count || [];
  const improvements = dashboard.expected_improvement || payload.expected_improvement || [];
  const tasks = dashboard.task_priority || payload.task_priority || [];
  const history = dashboard.learning_history || payload.learning_history || [];
  const sources = payload.source_summary || dashboard.source_summary || {};
  const analyticsCount = Number(sources.analytics_video_count || 0);

  if (gapMeta) {
    gapMeta.textContent = `${payload.generated_at || "最新"} · 健康度 ${health.overall_score ?? 0} · DuckDB ${analyticsCount} 条 · ${gapStatusLabel(health.status)}`;
  }

  gapDashboard.innerHTML = `
    <div class="gap-metrics">
      ${renderGapMetric("能力健康度", health.overall_score ?? 0, gapStatusLabel(health.status))}
      ${renderGapMetric("缺失能力", health.missing_count ?? 0, "项能力")}
      ${renderGapMetric("成熟能力", health.mature_count ?? 0, "项能力")}
      ${renderGapMetric("视频样本", health.video_count_total ?? 0, "条本地样本")}
    </div>

    ${renderAnalyticsClosure(sources)}

    <div class="gap-grid">
      <section class="gap-block">
        <h3>能力雷达</h3>
        <div class="gap-bars">${radar.slice(0, 18).map(renderRadarBar).join("")}</div>
      </section>
      <section class="gap-block">
        <h3>能力覆盖热力图</h3>
        <div class="gap-heatmap">${heatmap.map(renderHeatCell).join("")}</div>
      </section>
    </div>

    <div class="gap-grid">
      <section class="gap-block">
        <h3>能力缺口排行</h3>
        ${renderGapTable(gaps)}
      </section>
      <section class="gap-block">
        <h3>补充任务优先级</h3>
        ${renderTaskList(tasks)}
      </section>
    </div>

    <div class="gap-grid">
      <section class="gap-block">
        <h3>创作者建议</h3>
        ${renderCreatorGapRecommendations(creators)}
      </section>
      <section class="gap-block">
        <h3>预期提升</h3>
        ${renderImprovementList(improvements)}
      </section>
    </div>

    <section class="gap-block">
      <h3>建议补充视频数</h3>
      ${renderVideoRecommendations(videos)}
    </section>

    <section class="gap-block">
      <h3>学习变化记录</h3>
      ${renderLearningHistory(history)}
    </section>
  `;
}

function renderAnalyticsClosure(sources) {
  const videoCount = Number(sources.analytics_video_count || 0);
  const evidenceCount = Number(sources.analytics_capability_evidence_count || 0);
  const audioCoverage = normalizeCoverage(sources.analytics_audio_coverage);
  const sceneCoverage = normalizeCoverage(sources.analytics_scene_coverage);
  const visualCoverage = normalizeCoverage(sources.analytics_visual_coverage);
  const medianTempo = sources.analytics_median_tempo_bpm;
  const medianScene = sources.analytics_median_scene_duration;
  const visualNote = visualCoverage > 0
    ? "封面语义已参与 visual / thumbnail 评分"
    : "OpenCLIP 权重尚未缓存，已快速跳过，不再阻塞任务";
  return `
    <section class="analytics-closure">
      <div class="analytics-closure-head">
        <div>
          <span class="eyebrow">STRUCTURED ANALYTICS</span>
          <h3>分析结果已经进入能力缺口</h3>
        </div>
        <span class="analytics-evidence-count">${evidenceCount} 组有效证据</span>
      </div>
      <div class="analytics-flow">
        ${renderAnalyticsSignal(
          "librosa · 音频节奏",
          audioCoverage,
          `${Number(sources.analytics_audio_ready_count || 0)}/${videoCount} 条`,
          medianTempo == null ? "等待有效音频" : `中位速度 ${escapeHtml(medianTempo)} BPM`,
          "audio",
        )}
        ${renderAnalyticsSignal(
          "PySceneDetect · 剪辑节奏",
          sceneCoverage,
          `${Number(sources.analytics_scene_ready_count || 0)}/${videoCount} 条`,
          medianScene == null ? "等待场景样本" : `中位镜头 ${escapeHtml(medianScene)} 秒`,
          "editing / camera",
        )}
        ${renderAnalyticsSignal(
          "OpenCLIP · 视觉语义",
          visualCoverage,
          `${Number(sources.analytics_visual_ready_count || 0)}/${videoCount} 条`,
          visualNote,
          "visual / thumbnail",
        )}
      </div>
      <p class="analytics-closure-note">
        DuckDB 当前汇总 ${videoCount} 条视频；上面的有效特征会直接增加对应能力的样本、来源和覆盖率，批量任务完成后会自动重算。
      </p>
    </section>
  `;
}

function renderAnalyticsSignal(label, coverage, count, note, abilities) {
  return `
    <article class="analytics-signal">
      <div class="analytics-signal-top">
        <strong>${escapeHtml(label)}</strong>
        <span>${coverage}%</span>
      </div>
      <div class="analytics-progress" aria-label="${escapeHtml(label)} 覆盖率 ${coverage}%">
        <i style="width: ${coverage}%"></i>
      </div>
      <div class="analytics-signal-meta">
        <span>${escapeHtml(count)}</span>
        <span>→ ${escapeHtml(abilities)}</span>
      </div>
      <small>${note}</small>
    </article>
  `;
}

function normalizeCoverage(value) {
  const numeric = Number(value || 0);
  const percentage = numeric <= 1 ? numeric * 100 : numeric;
  return Math.max(0, Math.min(100, Math.round(percentage)));
}

function renderGapMetric(label, value, suffix) {
  return `
    <div class="gap-metric">
      <span class="gap-metric-value">${escapeHtml(value)}</span>
      <span class="gap-metric-label">${escapeHtml(label)}</span>
      <small>${escapeHtml(suffix)}</small>
    </div>
  `;
}

function renderRadarBar(item) {
  const score = Math.max(0, Math.min(100, Number(item.score || 0)));
  return `
    <div class="radar-row">
      <span>${escapeHtml(item.ability_name || item.ability_key)}</span>
      <div class="radar-track"><div class="radar-fill ${scoreClass(score)}" style="width: ${score}%"></div></div>
      <strong>${score}</strong>
    </div>
  `;
}

function renderHeatCell(item) {
  const coverage = Math.max(0, Math.min(1, Number(item.coverage || 0)));
  const level = coverage >= 0.8 ? "high" : coverage >= 0.5 ? "mid" : "low";
  return `
    <div class="heat-cell ${level}" title="${escapeHtml(item.ability_name)} · ${Math.round(coverage * 100)}%">
      <strong>${escapeHtml(item.ability_name)}</strong>
      <span>${Math.round(coverage * 100)}% · ${escapeHtml(gapStatusLabel(item.status))}</span>
    </div>
  `;
}

function renderGapTable(gaps) {
  if (!gaps.length) return `<div class="empty-state">当前没有需要补充的能力缺口。</div>`;
  return `
    <div class="gap-table">
      ${gaps.slice(0, 12).map((item, index) => `
        <div class="gap-table-row">
          <span>${index + 1}</span>
          <strong>${escapeHtml(item.ability_name)}</strong>
          <span>${escapeHtml(gapStatusLabel(item.status))}</span>
          <span>${escapeHtml(item.priority_score)}</span>
          <small>样本缺口 ${escapeHtml(item.reference_gap)}</small>
        </div>
      `).join("")}
    </div>
  `;
}

function renderTaskList(tasks) {
  if (!tasks.length) return `<div class="empty-state">暂未生成补充任务。</div>`;
  return `
    <div class="task-list">
      ${tasks.slice(0, 10).map((item) => `
        <article class="task-item">
          <div>
            <strong>${escapeHtml(item.priority)}. ${escapeHtml(item.ability_name)}</strong>
            <span>${escapeHtml(gapActionLabel(item.action))} · 优先分 ${escapeHtml(item.priority_score)}</span>
          </div>
          <p>${escapeHtml(item.reason || "")}</p>
          <small>${escapeHtml(item.recommended_creator || "")} · 建议 ${escapeHtml(item.recommended_video_count || 0)} 条视频</small>
        </article>
      `).join("")}
    </div>
  `;
}

function renderCreatorGapRecommendations(items) {
  if (!items.length) return `<div class="empty-state">暂时没有创作者建议。</div>`;
  return `
    <div class="task-list">
      ${items.slice(0, 8).map((item) => {
        const creators = item.creators || [];
        const first = creators[0] || {};
        return `
          <article class="task-item">
            <div>
              <strong>${escapeHtml(item.ability_name)}</strong>
              <span>${escapeHtml(first.score ?? "-")}</span>
            </div>
            <p>${escapeHtml(first.creator || "需要寻找合适的UP")}</p>
            <small>${escapeHtml(first.creator_type || first.category || "")}</small>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderImprovementList(items) {
  if (!items.length) return `<div class="empty-state">暂时没有提升模拟方案。</div>`;
  return `
    <div class="task-list">
      ${items.slice(0, 10).map((item) => `
        <article class="task-item">
          <div>
            <strong>${escapeHtml(item.ability_name)}</strong>
            <span>${escapeHtml(item.current_score)} -> ${escapeHtml(item.expected_score)}</span>
          </div>
          <p>补充 ${escapeHtml(item.added_video_count)} 条视频后，预计提升 ${escapeHtml(item.score_delta)} 分</p>
          <small>${escapeHtml(item.assumption || "")}</small>
        </article>
      `).join("")}
    </div>
  `;
}

function renderVideoRecommendations(items) {
  if (!items.length) return `<div class="empty-state">暂时没有视频补充计划。</div>`;
  return `
    <div class="gap-table">
      ${items.slice(0, 16).map((item) => `
        <div class="gap-table-row video-row">
          <strong>${escapeHtml(item.ability_name)}</strong>
          <span>${escapeHtml(item.recommended_video_count)} 条视频</span>
          <small>${escapeHtml(item.video_type || "")}</small>
        </div>
      `).join("")}
    </div>
  `;
}

function renderLearningHistory(items) {
  if (!items.length) return `<div class="empty-state">还没有上一次能力缺口分析记录。</div>`;
  return `
    <div class="gap-table">
      ${items.slice(0, 10).map((item) => `
        <div class="gap-table-row">
          <strong>${escapeHtml(item.ability_name || item.generated_at)}</strong>
          <span>${escapeHtml(item.current_score ?? item.overall_score ?? "-")}</span>
          <small>${escapeHtml(item.score_delta !== undefined ? `变化 ${item.score_delta}` : `缺失 ${item.missing_count || 0} 项`)}</small>
        </div>
      `).join("")}
    </div>
  `;
}

function scoreClass(score) {
  if (score >= 80) return "high";
  if (score >= 50) return "mid";
  return "low";
}

function setBadge(status, text) {
  jobBadge.className = `badge ${status || "idle"}`;
  jobBadge.textContent = text;
}

function setProgress(value, stage = "") {
  const normalized = Math.max(0, Math.min(100, Number(value) || 0));
  progressBar.style.width = `${normalized}%`;
  progressPercent.textContent = `${Math.round(normalized)}%`;
  currentStage.textContent = stage || "等待任务开始";
  progressTrack.setAttribute("aria-valuenow", String(Math.round(normalized)));
}

function renderWhisperProgress(job) {
  const stage = String(job.stage || "");
  const runtimeDetail = job.progress_detail || {};
  if (runtimeDetail.type === "playback_capture"
      || stage.includes("本地播放采集")
      || stage.includes("等待播放")) {
    const phase = Number(runtimeDetail.phase_percent);
    const normalized = Number.isFinite(phase)
      ? Math.max(0, Math.min(100, phase))
      : 0;
    whisperProgress.hidden = false;
    stopCaptureButton.hidden = runtimeDetail.state !== "recording";
    stopCaptureButton.disabled = false;
    stopCaptureButton.textContent = "停止录制并继续分析";
    whisperProgressTitle.textContent = runtimeDetail.state === "warmup"
      ? "等待浏览器开始播放"
      : runtimeDetail.state === "finished"
        ? "系统播放音频采集完成"
        : "正在采集系统播放音频";
    whisperDeviceBadge.className = "runtime-badge";
    whisperDeviceBadge.textContent =
      `WASAPI · ${runtimeDetail.device_name || "默认输出设备"}`;
    whisperProgressBar.classList.remove("indeterminate");
    whisperProgressBar.style.width = `${normalized}%`;
    whisperPhasePercent.textContent = `${Math.round(normalized)}%`;
    whisperProgressTrack.setAttribute("aria-valuenow", String(Math.round(normalized)));
    whisperProgressTime.textContent =
      `${formatDuration(runtimeDetail.elapsed_seconds)} / `
      + `${formatDuration(runtimeDetail.duration_seconds)}`;
    whisperRuntimeReason.textContent =
      `当前音量 ${(Number(runtimeDetail.level || 0) * 100).toFixed(1)}%`
      + " · 会录制当前输出设备上的全部系统声音";
    return;
  }
  const isWhisperStage = runtimeDetail.type === "whisper"
    || stage.includes("Whisper")
    || stage.includes("字幕写入");
  if (!isWhisperStage) {
    whisperProgress.hidden = true;
    stopCaptureButton.hidden = true;
    return;
  }
  stopCaptureButton.hidden = true;
  const detail = job.progress_detail?.type === "whisper"
    ? job.progress_detail
    : {
        type: "whisper",
        state: "preparing",
        phase_percent: null,
        device: whisperRuntime?.device || "unknown",
      };

  whisperProgress.hidden = false;
  const stateLabels = {
    preparing: "Whisper 正在准备",
    loading: "Whisper 模型加载中",
    transcribing: "Whisper 音频识别中",
    retrying: "Whisper 显存保护重试",
    fallback: "Whisper 已回退CPU",
    writing: "Whisper 字幕写入中",
  };
  whisperProgressTitle.textContent = stateLabels[detail.state] || "Whisper 处理中";

  const device = String(detail.device || whisperRuntime?.device || "unknown").toLowerCase();
  whisperDeviceBadge.className = "runtime-badge";
  if (device === "cuda") {
    const gpu = detail.gpu_name || whisperRuntime?.gpu_name || "NVIDIA GPU";
    const compute = detail.compute_type || whisperRuntime?.compute_type || "";
    const batch = detail.batch_size || whisperRuntime?.batch_size || 1;
    whisperDeviceBadge.textContent = `GPU · ${gpu} · ${compute} · 批量 ${batch}`;
  } else if (device === "cpu") {
    whisperDeviceBadge.classList.add("cpu");
    whisperDeviceBadge.textContent = `CPU · ${detail.compute_type || "int8"}`;
  } else {
    whisperDeviceBadge.classList.add("failed");
    whisperDeviceBadge.textContent = "设备状态未知";
  }

  const phase = Number(detail.phase_percent);
  if (detail.phase_percent === null || !Number.isFinite(phase)) {
    whisperProgressBar.style.width = "";
    whisperProgressBar.classList.add("indeterminate");
    whisperPhasePercent.textContent = detail.state === "loading" ? "加载中" : "计算中";
    whisperProgressTrack.removeAttribute("aria-valuenow");
  } else {
    const normalized = Math.max(0, Math.min(100, phase));
    whisperProgressBar.classList.remove("indeterminate");
    whisperProgressBar.style.width = `${normalized}%`;
    whisperPhasePercent.textContent = `${Math.round(normalized)}%`;
    whisperProgressTrack.setAttribute("aria-valuenow", String(Math.round(normalized)));
  }

  const processed = Number(detail.processed_seconds);
  const duration = Number(detail.duration_seconds);
  const elapsed = Number(detail.elapsed_seconds);
  const languageSuffix = detail.detected_language
    ? ` · 语言 ${detail.detected_language}`
    : "";
  if (Number.isFinite(processed) && Number.isFinite(duration) && duration > 0) {
    whisperProgressTime.textContent =
      `${formatDuration(processed)} / ${formatDuration(duration)}`
      + (Number.isFinite(elapsed) ? ` · 已运行 ${formatDuration(elapsed)}` : "")
      + languageSuffix;
  } else if (Number.isFinite(elapsed)) {
    whisperProgressTime.textContent =
      `已运行 ${formatDuration(elapsed)}${languageSuffix}`;
  } else if (detail.detected_language) {
    whisperProgressTime.textContent = `识别语言：${detail.detected_language}`;
  } else {
    whisperProgressTime.textContent = "正在准备音频识别";
  }
  whisperRuntimeReason.textContent = detail.reason
    || whisperRuntime?.reason
    || "Whisper运行时已就绪";
}

function formatDuration(value) {
  const total = Math.max(0, Math.round(Number(value) || 0));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function setTimeline(stage) {
  const stageMap = [
    ["准备", 0],
    ["字幕缓存", 1],
    ["官方字幕", 1],
    ["提取音频", 1],
    ["Whisper", 1],
    ["字幕写入", 1],
    ["内容分析", 2],
    ["读取小说", 1],
    ["小说创作", 2],
    ["保存小说", 3],
    ["UP批量", 1],
    ["单视频", 1],
    ["V4报告", 3],
    ["V3增强", 3],
    ["知识系统", 4],
    ["知识库", 4],
    ["词法索引", 4],
    ["语义向量", 4],
    ["创作者知识库", 4],
    ["能力缺口", 4],
    ["创作者发现", 4],
    ["项目报告", 4],
    ["导出结果", 4],
    ["完成", 4],
  ];
  const activeIndex = stageMap.find((item) => stage.includes(item[0]))?.[1] ?? 0;
  timelineItems.forEach((item, index) => {
    item.classList.toggle("complete", index < activeIndex);
    item.classList.toggle("active", index === activeIndex);
  });
}

function setLog(text) {
  logBox.textContent = text || "等待任务开始。";
  logBox.scrollTop = logBox.scrollHeight;
}

function statusLabel(job) {
  if (job.status === "queued") return "排队中";
  if (job.status === "cancelled") return "已取消";
  if (job.cancel_requested) return "正在取消";
  if (job.status === "running") return job.stage || "运行中";
  if (job.status === "done") return "已完成";
  if (job.status === "failed") return "失败";
  return "等待输入";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function updateClock() {
  clockLabel.textContent = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}

updateClock();
setInterval(updateClock, 1000);
loadHistory();
checkServerCapabilities();
loadProductionWorkspace();
updateProductionMode();
