const panels = document.querySelectorAll(".panel");
const navItems = document.querySelectorAll(".nav-item");
const jobForm = document.getElementById("jobForm");
const sourceInput = document.getElementById("sourceInput");
const sourceHint = document.getElementById("sourceHint");
const limitInput = document.getElementById("limitInput");
const v3Input = document.getElementById("v3Input");
const kbInput = document.getElementById("kbInput");
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
const youtubeAccess = document.getElementById("youtubeAccess");
const youtubeAccessMessage = document.getElementById("youtubeAccessMessage");
const youtubeAuthButton = document.getElementById("youtubeAuthButton");
const refreshJobs = document.getElementById("refreshJobs");
const jobBadge = document.getElementById("jobBadge");
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
const logBox = document.getElementById("logBox");
const resultList = document.getElementById("resultList");
const resultMeta = document.getElementById("resultMeta");
const timelineItems = [...document.querySelectorAll(".timeline li")];
const reportForm = document.getElementById("reportForm");
const reportInput = document.getElementById("reportInput");
const reportTopKInput = document.getElementById("reportTopKInput");
const reportRebuildInput = document.getElementById("reportRebuildInput");
const searchForm = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const searchResults = document.getElementById("searchResults");
const searchBackendMeta = document.getElementById("searchBackendMeta");
const knowledgeRefreshButton = document.getElementById("knowledgeRefreshButton");
const knowledgeBuildButton = document.getElementById("knowledgeBuildButton");
const knowledgeStatus = document.getElementById("knowledgeStatus");
const knowledgeMeta = document.getElementById("knowledgeMeta");
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
const serverState = document.getElementById("serverState");
const runtimeStateLabel = document.getElementById("runtimeStateLabel");
const gpuStateLabel = document.getElementById("gpuStateLabel");
const modelStateLabel = document.getElementById("modelStateLabel");
const clockLabel = document.getElementById("clockLabel");

let activeJobId = null;
let pollTimer = null;
let pollInFlight = false;
let advisorAvailable = false;
let gapAvailable = false;
let discoveryAvailable = false;
let advancedKnowledgeAvailable = false;
let douyinStatusTimer = null;
let whisperRuntime = null;
const platformAuthState = {
  bilibili: null,
  youtube: null,
};
let platformAuthStatusTimer = null;

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
    subject_name: mode === "content" ? subjectNameInput.value.trim() : "",
    content_category: mode === "content" ? contentCategoryInput.value : "auto",
  });
});

modeInputs.forEach((input) => {
  input.addEventListener("change", updateTaskMode);
});
updateTaskMode();

function updateTaskMode() {
  const mode = new FormData(jobForm).get("mode");
  const isContent = mode === "content";
  contentWorkOptions.hidden = !isContent;
  contentWorkOptions.classList.toggle("visible", isContent);
  if (isContent) {
    sourceInput.placeholder = "每行输入一个B站视频链接或BV号；多期内容会合并为同一作品";
    sourceHint.textContent = "综艺、电影、动漫、纪录片及其他B站内容均可学习";
  } else {
    sourceInput.placeholder = "输入 B站 / YouTube / 抖音视频链接、创作者主页、UP 名或本地文件路径";
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

buildKbButton.addEventListener("click", async () => {
  await startSystemJob("/api/kb/build", "知识库任务创建失败。");
});

buildAdvancedKbButton.addEventListener("click", async () => {
  await startSystemJob("/api/kb/advanced", "完整知识系统任务创建失败。");
});

douyinLoginButton.addEventListener("click", startDouyinLogin);
bilibiliAuthButton.addEventListener("click", () => startPlatformLogin("bilibili"));
youtubeAuthButton.addEventListener("click", () => startPlatformLogin("youtube"));

knowledgeBuildButton.addEventListener("click", async () => {
  await startSystemJob("/api/kb/advanced", "完整知识系统任务创建失败。");
});

knowledgeRefreshButton.addEventListener("click", loadKnowledgeStatus);

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
  clearInterval(pollTimer);
  pollJob();
  pollTimer = setInterval(pollJob, 750);
}

async function pollJob() {
  if (!activeJobId || pollInFlight) return;
  pollInFlight = true;
  try {
    const response = await fetch(`/api/jobs/${activeJobId}`, {
      cache: "no-store",
    });
    const job = await response.json();
    if (!response.ok) {
      clearInterval(pollTimer);
      setBadge("failed", "任务丢失");
      return;
    }
    renderJob(job);
    if (job.status === "done" || job.status === "failed") {
      clearInterval(pollTimer);
      startButton.disabled = false;
      loadHistory();
    }
  } catch (error) {
    setBadge("running", "连接恢复中");
  } finally {
    pollInFlight = false;
  }
}

function renderJob(job) {
  setBadge(job.status, statusLabel(job));
  setProgress(job.progress || 0, job.stage || "");
  renderWhisperProgress(job);
  setTimeline(job.stage || "");
  setLog((job.logs || []).join("\n\n"));
  if (job.status === "failed") {
    resultMeta.textContent = "任务失败";
    resultList.classList.remove("empty");
    resultList.innerHTML = `<div class="empty-state">${escapeHtml(job.error || "未知错误")}</div>`;
  }
  if (job.status === "done" && job.result) {
    renderFiles(job.result.files || []);
    const summary = [];
    if (job.result.type === "report") summary.push("V4报告");
    if (job.result.type === "advanced_knowledge") summary.push("知识系统已更新");
    if (job.result.success_count !== undefined) summary.push(`成功 ${job.result.success_count}`);
    if (job.result.failure_count !== undefined) summary.push(`失败 ${job.result.failure_count}`);
    if (job.result.video_id) summary.push(job.result.video_id);
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
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  const jobs = payload.jobs || [];
  if (!jobs.length) {
    historyList.innerHTML = `<div class="empty-state">暂无任务记录。</div>`;
    return;
  }
  historyList.innerHTML = jobs
    .slice()
    .reverse()
    .map((job) => {
      const source = job.payload?.source || job.payload?.mode || "";
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
      watchJob(item.dataset.jobId);
      navItems[0].click();
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
  } catch (error) {
    knowledgeStatus.innerHTML = `<div class="empty-state error-state">${escapeHtml(error.message || "状态读取失败")}</div>`;
    knowledgeMeta.textContent = "知识系统状态读取失败";
  } finally {
    knowledgeRefreshButton.disabled = false;
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
            <span>${item.ready ? "已就绪" : "尚未生成"}</span>
            <small>${item.ready && item.updated_at ? escapeHtml(new Date(item.updated_at * 1000).toLocaleString()) : ""}</small>
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

  if (gapMeta) {
    gapMeta.textContent = `${payload.generated_at || "最新"} · 健康度 ${health.overall_score ?? 0} · ${gapStatusLabel(health.status)}`;
  }

  gapDashboard.innerHTML = `
    <div class="gap-metrics">
      ${renderGapMetric("能力健康度", health.overall_score ?? 0, gapStatusLabel(health.status))}
      ${renderGapMetric("缺失能力", health.missing_count ?? 0, "项能力")}
      ${renderGapMetric("成熟能力", health.mature_count ?? 0, "项能力")}
      ${renderGapMetric("视频样本", health.video_count_total ?? 0, "条本地样本")}
    </div>

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
  const isWhisperStage = stage.includes("Whisper")
    || stage.includes("字幕写入");
  if (!isWhisperStage) {
    whisperProgress.hidden = true;
    return;
  }
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

function setTimeline(stage) {
  const stageMap = [
    ["准备", 0],
    ["字幕缓存", 1],
    ["官方字幕", 1],
    ["提取音频", 1],
    ["Whisper", 1],
    ["字幕写入", 1],
    ["内容分析", 2],
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
