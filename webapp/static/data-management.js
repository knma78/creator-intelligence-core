(() => {
  const panel = document.getElementById("dataProtection");
  if (!panel) return;
  const status = document.getElementById("dataTaskStatus");
  const result = document.getElementById("dataTaskResult");
  const snapshots = document.getElementById("dataSnapshotSelect");
  const quarantine = document.getElementById("dataQuarantineSelect");
  const execute = document.getElementById("dataQuarantineButton");
  const cancel = document.getElementById("dataCancelButton");
  let activeJob = "";
  let planToken = "";
  let timer;
  const bytes = (n) => `${(Number(n || 0) / 1024 / 1024).toFixed(1)} MB`;
  const labels = { protected: "长期成果", project_asset: "制作素材", source_media: "下载媒体", model: "模型", rebuildable_index: "可重建索引" };

  async function request(url, options) {
    const response = await fetch(url, { cache: "no-store", ...options });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error(value.error || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return value;
  }

  function busy(value) {
    panel.querySelectorAll("button, select, input").forEach((el) => { el.disabled = value; });
    cancel.disabled = false;
    cancel.hidden = !value;
    if (!value) execute.disabled = !planToken;
  }

  async function refresh() {
    const value = await request("/api/data/status");
    document.getElementById("dataInventorySummary").textContent =
      `${value.file_count} 个文件 · ${Object.entries(value.bytes_by_category).map(([k, n]) => `${labels[k] || k} ${bytes(n)}`).join(" · ")}\n备份位置：${value.backup_directory}`;
    const selected = snapshots.value;
    snapshots.replaceChildren(new Option("请选择备份", ""), ...value.snapshots.map((entry) =>
      new Option(`${entry.snapshot_id} · ${entry.file_count} 个文件 · 未包含 ${entry.omitted_count} 项`, entry.snapshot_id)));
    if (value.snapshots.some((x) => x.snapshot_id === selected)) snapshots.value = selected;
    else if (value.snapshots.length) snapshots.value = value.snapshots[0].snapshot_id;
    quarantine.replaceChildren(new Option("请选择隔离记录", ""), ...value.quarantines.map((entry) =>
      new Option(`${entry.quarantine_id} · ${entry.file_count} 个文件`, entry.quarantine_id)));
  }

  function showResult(operation, details) {
    result.replaceChildren();
    const message = document.createElement("p");
    if (operation === "cleanup-plan") {
      planToken = details.candidates.length ? details.plan_token : "";
      message.textContent = `可隔离 ${details.candidates.length} 个索引，共 ${bytes(details.bytes_to_quarantine)}；隔离阶段释放空间为 0。`;
      const list = document.createElement("ul");
      for (const item of [...details.candidates.map((x) => ({ ...x, reason: "已备份且重建来源存在" })), ...details.blocked]) {
        const row = document.createElement("li");
        row.textContent = `${item.key}：${item.reason}`;
        list.append(row);
      }
      result.append(list);
    } else if (operation === "backup") {
      message.textContent = `备份已校验：${details.file_count} 个文件，${bytes(details.bytes)}。位置：${details.snapshot}。未包含 ${details.omitted_count} 项下载媒体/模型。`;
    } else if (operation === "restore-drill") {
      message.textContent = `恢复演练通过：${details.file_count} 个文件。目录：${details.restored_to}。现用数据未修改；工程绝对路径仍需按恢复报告重绑定。`;
    } else if (operation === "verify") {
      message.textContent = `校验通过：${details.file_count} 个文件，${bytes(details.bytes)}。`;
    } else if (operation === "quarantine") {
      message.textContent = `已隔离 ${details.moved_count} 个索引，可通过“撤销隔离”恢复。未永久删除任何文件。`;
      planToken = "";
    } else {
      message.textContent = `已恢复 ${details.restored_count} 个隔离索引。`;
    }
    if (details.format_warning_count) {
      message.textContent += ` 注意：${details.format_warning_count} 个原始 JSON 存在格式问题，已原样保留；文件校验通过不代表这些内容可用。`;
      const warnings = document.createElement("ul");
      for (const item of details.format_warnings || []) {
        const row = document.createElement("li");
        row.textContent = `${item.key}：${item.issue}`;
        warnings.append(row);
      }
      result.append(warnings);
    }
    result.prepend(message);
  }

  async function poll() {
    if (!activeJob) return;
    try {
      const job = await request(`/api/jobs/${activeJob}`);
      status.textContent = `${job.stage || job.status} · ${job.progress || 0}% · ${(job.logs || []).slice(-1)[0] || ""}`;
      if (["done", "failed", "cancelled"].includes(job.status)) {
        activeJob = "";
        localStorage.removeItem("contentresearch.dataJob");
        if (job.status === "done") {
          const data = job.result;
          showResult(data.operation, data.details);
          status.textContent = "数据任务完成。";
          try {
            await refresh();
            if (data.operation === "backup") snapshots.value = data.details.snapshot_id;
          } catch (error) {
            status.textContent = `任务已完成，但清单刷新失败：${error.message}。可以点击“查看数据与备份”重试。`;
          }
        } else {
          status.textContent = job.error || "任务已取消。已完成的备份片段或隔离记录保留，可检查后恢复。";
        }
        busy(false);
        return;
      }
    } catch (error) {
      if (error.status === 404) {
        activeJob = "";
        localStorage.removeItem("contentresearch.dataJob");
        status.textContent = "原任务记录已不存在，请刷新清单确认结果。";
        busy(false);
        return;
      }
      status.textContent = `读取进度失败：${error.message}；正在重试。`;
    }
    timer = setTimeout(poll, 1500);
  }

  panel.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-data-operation]");
    if (!button || activeJob) return;
    const operation = button.dataset.dataOperation;
    if (!["backup", "undo-quarantine"].includes(operation) && !snapshots.value) {
      status.textContent = "请先读取并选择备份。";
      return;
    }
    if (operation === "undo-quarantine" && !quarantine.value) {
      status.textContent = "请选择隔离记录。";
      return;
    }
    busy(true);
    try {
      const job = await request(`/api/data/${operation}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshots.value, plan_token: planToken, quarantine_id: quarantine.value,
          include_media: document.getElementById("dataIncludeMedia").checked,
          include_models: document.getElementById("dataIncludeModels").checked }),
      });
      activeJob = job.id;
      localStorage.setItem("contentresearch.dataJob", job.id);
      await poll();
    } catch (error) {
      status.textContent = error.message;
      busy(false);
    }
  });
  snapshots.addEventListener("change", () => { planToken = ""; execute.disabled = true; result.replaceChildren(); });
  document.getElementById("dataInventoryButton").addEventListener("click", async () => {
    planToken = ""; execute.disabled = true;
    try { await refresh(); status.textContent = "数据清单已更新。"; }
    catch (error) { status.textContent = error.message; }
  });
  cancel.addEventListener("click", async () => {
    if (!activeJob) return;
    try { await request(`/api/jobs/${activeJob}/cancel`, { method: "POST" }); status.textContent = "已请求取消。"; }
    catch (error) { status.textContent = error.message; }
  });
  const previous = localStorage.getItem("contentresearch.dataJob");
  if (previous) { activeJob = previous; busy(true); poll(); }
  window.addEventListener("beforeunload", () => clearTimeout(timer));
})();
