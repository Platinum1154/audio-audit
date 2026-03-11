const state = {
  root: null,
  items: [],
  stats: null,
  currentIndex: -1,
  waveformImage: null,
  spectrogramImage: null,
  visualizationToken: 0,
  playbackToken: 0,
  isSeeking: false,
  autoplayAllowed: false,
};

const refs = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheRefs();
  bindEvents();
  renderStats();
  resizeCanvases();
  window.addEventListener("resize", handleResize);
});

function cacheRefs() {
  refs.browseButton = document.querySelector("#browseButton");
  refs.rootInput = document.querySelector("#rootInput");
  refs.loadButton = document.querySelector("#loadButton");
  refs.reloadButton = document.querySelector("#reloadButton");
  refs.exportButton = document.querySelector("#exportButton");
  refs.fileTitle = document.querySelector("#fileTitle");
  refs.fileSubtitle = document.querySelector("#fileSubtitle");
  refs.statusBadge = document.querySelector("#statusBadge");
  refs.positionText = document.querySelector("#positionText");
  refs.audioPlayer = document.querySelector("#audioPlayer");
  refs.seekBar = document.querySelector("#seekBar");
  refs.currentTime = document.querySelector("#currentTime");
  refs.durationText = document.querySelector("#durationText");
  refs.waveformCanvas = document.querySelector("#waveformCanvas");
  refs.spectrogramCanvas = document.querySelector("#spectrogramCanvas");
  refs.statsGrid = document.querySelector("#statsGrid");
  refs.labelList = document.querySelector("#labelList");
  refs.newLabelInput = document.querySelector("#newLabelInput");
  refs.addLabelButton = document.querySelector("#addLabelButton");
  refs.noteInput = document.querySelector("#noteInput");
  refs.fileList = document.querySelector("#fileList");
  refs.queueMeta = document.querySelector("#queueMeta");
  refs.statusMessage = document.querySelector("#statusMessage");
  refs.playPauseButton = document.querySelector("#playPauseButton");
  refs.undoButton = document.querySelector("#undoButton");
  refs.actionButtons = document.querySelectorAll("[data-action]");
}

function bindEvents() {
  refs.browseButton.addEventListener("click", browseFolder);
  refs.loadButton.addEventListener("click", () => loadRoot(refs.rootInput.value.trim()));
  refs.reloadButton.addEventListener("click", () => {
    if (state.root) {
      loadRoot(state.root.path);
    }
  });
  refs.rootInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      loadRoot(refs.rootInput.value.trim());
    }
  });
  refs.addLabelButton.addEventListener("click", addLabel);
  refs.newLabelInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addLabel();
    }
  });
  refs.playPauseButton.addEventListener("click", togglePlayback);
  refs.undoButton.addEventListener("click", undoLastAction);
  refs.actionButtons.forEach((button) => {
    button.addEventListener("click", () => applyAction(button.dataset.action));
  });

  refs.audioPlayer.addEventListener("timeupdate", () => {
    if (!refs.audioPlayer.duration || state.isSeeking) {
      drawWaveform();
      drawSpectrogram();
      return;
    }
    refs.seekBar.value = String(
      Math.round((refs.audioPlayer.currentTime / refs.audioPlayer.duration) * 1000)
    );
    refs.currentTime.textContent = formatTime(refs.audioPlayer.currentTime);
    drawWaveform();
    drawSpectrogram();
  });

  refs.audioPlayer.addEventListener("loadedmetadata", () => {
    refs.durationText.textContent = formatTime(refs.audioPlayer.duration);
    drawWaveform();
    drawSpectrogram();
  });

  refs.audioPlayer.addEventListener("ended", () => {
    const item = currentItem();
    if (item) {
      setStatus(`播放结束，等待分类: ${item.relative_path}`);
    }
  });

  refs.seekBar.addEventListener("input", () => {
    state.isSeeking = true;
    const item = currentItem();
    if (!item || !refs.audioPlayer.duration) {
      return;
    }
    const ratio = Number(refs.seekBar.value) / 1000;
    refs.audioPlayer.currentTime = ratio * refs.audioPlayer.duration;
    refs.currentTime.textContent = formatTime(refs.audioPlayer.currentTime);
    drawWaveform();
    drawSpectrogram();
  });

  refs.seekBar.addEventListener("change", () => {
    state.isSeeking = false;
  });

  refs.waveformCanvas.addEventListener("click", (event) => seekFromCanvas(event, refs.waveformCanvas));
  refs.spectrogramCanvas.addEventListener("click", (event) =>
    seekFromCanvas(event, refs.spectrogramCanvas)
  );

  document.addEventListener("keydown", handleHotkeys);
}

async function browseFolder() {
  try {
    const result = await api("/api/dialog/select-root", { method: "POST" });
    if (result.path) {
      refs.rootInput.value = result.path;
      setStatus(`已选择目录: ${result.path}`);
    } else {
      setStatus("没有选择目录");
    }
  } catch (error) {
    setStatus(error.message || "打开目录选择器失败");
  }
}

async function loadRoot(rootPath) {
  if (!rootPath) {
    setStatus("请输入目录路径");
    return;
  }

  setLoading(true);
  setStatus(`正在扫描目录: ${rootPath}`);
  try {
    const payload = await api("/api/session/load", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath }),
    });

    state.root = payload.root;
    state.items = payload.items;
    state.stats = payload.stats;
    refs.exportButton.href = `/api/roots/${payload.root.id}/export`;
    refs.rootInput.value = payload.root.path;
    renderStats();
    renderLabels();
    renderFileList();

    const selectedIndex = indexById(payload.selected_file_id);
    if (selectedIndex >= 0) {
      await setCurrentIndex(selectedIndex, { autoplay: false });
    } else {
      clearCurrentView("目录里没有可审计的音频文件");
    }

    setStatus(`已加载 ${payload.stats.total} 条音频`);
  } catch (error) {
    setStatus(error.message || "加载目录失败");
    clearCurrentView("加载失败");
  } finally {
    setLoading(false);
  }
}

function renderStats() {
  const stats = state.stats || {
    total: 0,
    pending: 0,
    approved: 0,
    removed: 0,
    skipped: 0,
    missing: 0,
  };

  const entries = [
    ["总数", stats.total],
    ["未审核", stats.pending],
    ["通过", stats.approved],
    ["移除", stats.removed],
    ["跳过", stats.skipped],
    ["缺失", stats.missing],
  ];

  refs.statsGrid.innerHTML = entries
    .map(
      ([label, value]) => `
        <div class="stat-card">
          <span class="muted">${label}</span>
          <strong>${value}</strong>
        </div>
      `
    )
    .join("");
}

function renderLabels() {
  const labels = state.root?.labels || [];
  const activeTags = currentItem()?.tags || [];

  refs.labelList.innerHTML = labels
    .map((label, index) => {
      const active = activeTags.includes(label) ? "active" : "";
      return `
        <div class="label-chip ${active}" data-label="${escapeHtml(label)}">
          <span>${index + 1}. ${escapeHtml(label)}</span>
          <button type="button" data-remove-label="${escapeHtml(label)}" aria-label="删除标签">×</button>
        </div>
      `;
    })
    .join("");

  refs.labelList.querySelectorAll(".label-chip").forEach((chip) => {
    chip.addEventListener("click", (event) => {
      if (event.target instanceof HTMLElement && event.target.dataset.removeLabel) {
        return;
      }
      const label = chip.dataset.label;
      toggleTag(label);
    });
  });

  refs.labelList.querySelectorAll("[data-remove-label]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      removeLabel(button.dataset.removeLabel);
    });
  });
}

function renderFileList() {
  refs.queueMeta.textContent = state.root
    ? `${state.root.path} · ${state.items.length} 条记录`
    : "加载目录后显示文件列表";

  if (!state.items.length) {
    refs.fileList.innerHTML = `<div class="muted">当前没有音频文件</div>`;
    return;
  }

  refs.fileList.innerHTML = state.items
    .map((item, index) => {
      const active = index === state.currentIndex ? "active" : "";
      const statusClass = statusClassName(item);
      const tags = item.tags
        .map((tag) => `<span class="tag-pill">${escapeHtml(tag)}</span>`)
        .join("");
      return `
        <div class="file-row ${active}" data-index="${index}">
          <div class="file-index">${String(index + 1).padStart(3, "0")}</div>
          <div class="file-main">
            <div class="file-name">${escapeHtml(item.filename)}</div>
            <div class="file-path">${escapeHtml(item.relative_path)}</div>
            ${tags ? `<div class="tag-pill-row">${tags}</div>` : ""}
          </div>
          <div class="file-meta">
            <span class="status-badge ${statusClass}">${statusLabel(item)}</span>
            <span class="muted">${escapeHtml(item.duration_label)}</span>
          </div>
        </div>
      `;
    })
    .join("");

  refs.fileList.querySelectorAll(".file-row").forEach((row) => {
    row.addEventListener("click", async () => {
      const index = Number(row.dataset.index);
      await setCurrentIndex(index, { autoplay: false });
    });
  });
}

async function setCurrentIndex(index, { autoplay = false } = {}) {
  if (index < 0 || index >= state.items.length) {
    return;
  }

  state.currentIndex = index;
  const item = currentItem();
  refs.noteInput.value = item.note || "";
  refs.fileTitle.textContent = item.filename;
  refs.fileSubtitle.textContent = `${item.relative_path} · ${item.original_path}`;
  refs.positionText.textContent = `${index + 1} / ${state.items.length}`;
  updateStatusBadge(item);
  renderLabels();
  renderFileList();

  if (item.missing) {
    refs.audioPlayer.removeAttribute("src");
    refs.audioPlayer.load();
    refs.durationText.textContent = item.duration_label;
    refs.currentTime.textContent = "00:00.0";
    resetVisuals("文件缺失，无法播放");
    setStatus(`文件缺失: ${item.relative_path}`);
    return;
  }

  await loadAudioForCurrentItem({ autoplay });
}

async function loadAudioForCurrentItem({ autoplay }) {
  const item = currentItem();
  if (!item) {
    return;
  }

  state.visualizationToken += 1;
  state.playbackToken += 1;
  const visualizationToken = state.visualizationToken;
  const playbackToken = state.playbackToken;
  refs.audioPlayer.pause();
  refs.audioPlayer.autoplay = autoplay;
  refs.audioPlayer.src = `${item.audio_url}?v=${Date.now()}`;
  refs.audioPlayer.load();
  refs.currentTime.textContent = "00:00.0";
  refs.durationText.textContent = item.duration_label;
  resetVisuals("正在生成可视化");

  try {
    const visualizationTask = loadVisualizations(item, visualizationToken);
    let playStarted = false;
    if (autoplay) {
      await waitForMediaReady(playbackToken);
      if (playbackToken === state.playbackToken) {
        playStarted = await safePlay();
      }
    }
    await visualizationTask;
    if (!autoplay || playStarted) {
      setStatus(`当前文件: ${item.relative_path}`);
    }
  } catch (error) {
    resetVisuals("可视化生成失败，但音频仍可播放");
    setStatus(error.message || "音频可视化生成失败");
  }
}

async function loadVisualizations(item, token) {
  const waveformUrl = buildVisualizationUrl(item, "waveform", refs.waveformCanvas);
  const spectrogramUrl = buildVisualizationUrl(item, "spectrogram", refs.spectrogramCanvas);
  const [waveformResult, spectrogramResult] = await Promise.allSettled([
    loadCanvasImage(waveformUrl),
    loadCanvasImage(spectrogramUrl),
  ]);

  if (token !== state.visualizationToken) {
    return;
  }

  state.waveformImage =
    waveformResult.status === "fulfilled" ? waveformResult.value : null;
  state.spectrogramImage =
    spectrogramResult.status === "fulfilled" ? spectrogramResult.value : null;

  if (!state.waveformImage && !state.spectrogramImage) {
    throw new Error("后端可视化生成失败");
  }

  drawWaveform();
  drawSpectrogram();
}

function buildVisualizationUrl(item, kind, canvas) {
  const width = Math.max(320, canvas.width);
  const height = Math.max(180, canvas.height);
  return `${item.visualization_base_url}/${kind}?width=${width}&height=${height}&v=${Date.now()}`;
}

function waitForMediaReady(playbackToken) {
  if (playbackToken !== state.playbackToken) {
    return Promise.resolve();
  }

  if (refs.audioPlayer.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    let settled = false;

    const cleanup = () => {
      refs.audioPlayer.removeEventListener("canplay", onReady);
      refs.audioPlayer.removeEventListener("loadeddata", onReady);
      refs.audioPlayer.removeEventListener("error", onError);
      window.clearTimeout(timeoutId);
    };

    const finish = (callback) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      callback();
    };

    const onReady = () => finish(resolve);
    const onError = () => finish(() => reject(new Error("音频加载失败")));
    const timeoutId = window.setTimeout(() => finish(resolve), 5000);

    refs.audioPlayer.addEventListener("canplay", onReady);
    refs.audioPlayer.addEventListener("loadeddata", onReady);
    refs.audioPlayer.addEventListener("error", onError);
  });
}

async function loadCanvasImage(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`请求可视化失败: ${response.status}`);
  }

  const blob = await response.blob();
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("图片加载失败"));
    };
    image.src = objectUrl;
  });
}

function drawWaveform() {
  const canvas = refs.waveformCanvas;
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;

  context.clearRect(0, 0, width, height);
  drawCanvasBackground(context, width, height);

  if (state.waveformImage) {
    context.drawImage(state.waveformImage, 0, 0, width, height);
    drawPlayhead(context, width, height);
    return;
  }

  drawCanvasMessage(context, width, height, "等待波形");
}

function drawSpectrogram() {
  const canvas = refs.spectrogramCanvas;
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);
  drawCanvasBackground(context, width, height);

  if (state.spectrogramImage) {
    context.drawImage(state.spectrogramImage, 0, 0, width, height);
    drawPlayhead(context, width, height);
    return;
  }

  drawCanvasMessage(context, width, height, "等待频谱图");
}

function drawCanvasBackground(context, width, height) {
  const gradient = context.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "rgba(255, 255, 255, 0.06)");
  gradient.addColorStop(1, "rgba(255, 255, 255, 0.01)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);
}

function drawCanvasMessage(context, width, height, message) {
  context.fillStyle = "rgba(236, 244, 239, 0.72)";
  context.font = '16px "IBM Plex Sans", "Noto Sans SC", sans-serif';
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(message, width / 2, height / 2);
}

function drawPlayhead(context, width, height) {
  if (!refs.audioPlayer.duration) {
    return;
  }

  const ratio = refs.audioPlayer.currentTime / refs.audioPlayer.duration;
  const x = Math.max(0, Math.min(width, ratio * width));
  context.save();
  context.strokeStyle = "rgba(255, 255, 255, 0.88)";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(x, 0);
  context.lineTo(x, height);
  context.stroke();
  context.restore();
}

function resetVisuals(message) {
  state.waveformImage = null;
  state.spectrogramImage = null;
  const waveContext = refs.waveformCanvas.getContext("2d");
  drawCanvasBackground(waveContext, refs.waveformCanvas.width, refs.waveformCanvas.height);
  drawCanvasMessage(waveContext, refs.waveformCanvas.width, refs.waveformCanvas.height, message);

  const spectroContext = refs.spectrogramCanvas.getContext("2d");
  drawCanvasBackground(
    spectroContext,
    refs.spectrogramCanvas.width,
    refs.spectrogramCanvas.height
  );
  drawCanvasMessage(
    spectroContext,
    refs.spectrogramCanvas.width,
    refs.spectrogramCanvas.height,
    message
  );
}

async function safePlay() {
  try {
    await refs.audioPlayer.play();
    state.autoplayAllowed = true;
    return true;
  } catch (error) {
    setStatus("浏览器阻止了自动播放，按 P 开始播放");
    return false;
  }
}

function togglePlayback() {
  if (!currentItem()) {
    return;
  }
  if (refs.audioPlayer.paused) {
    safePlay();
  } else {
    refs.audioPlayer.pause();
  }
}

async function applyAction(action) {
  const item = currentItem();
  if (!item || !state.root) {
    return;
  }

  const nextIndex = findNextIndex(state.currentIndex);

  try {
    const payload = await api(`/api/files/${item.id}/action`, {
      method: "POST",
      body: JSON.stringify({
        action,
        tags: item.tags,
        note: refs.noteInput.value.trim(),
      }),
    });
    replaceItem(payload.item);
    state.stats = payload.stats;
    renderStats();
    renderFileList();
    setStatus(`${actionLabel(action)}: ${item.relative_path}`);

    if (nextIndex >= 0) {
      await setCurrentIndex(nextIndex, { autoplay: true });
    } else {
      await setCurrentIndex(state.currentIndex, { autoplay: false });
    }
  } catch (error) {
    setStatus(error.message || "提交审核失败");
  }
}

async function undoLastAction() {
  if (!state.root) {
    return;
  }

  try {
    const payload = await api(`/api/roots/${state.root.id}/undo`, { method: "POST" });
    replaceItem(payload.item);
    state.stats = payload.stats;
    renderStats();
    renderFileList();
    const index = indexById(payload.item.id);
    if (index >= 0) {
      await setCurrentIndex(index, { autoplay: false });
    }
    setStatus(`已撤销: ${payload.item.relative_path}`);
  } catch (error) {
    setStatus(error.message || "没有可撤销的动作");
  }
}

async function addLabel() {
  if (!state.root) {
    setStatus("请先加载目录");
    return;
  }

  const label = refs.newLabelInput.value.trim();
  if (!label) {
    return;
  }

  const labels = [...(state.root.labels || []), label];
  try {
    const payload = await api(`/api/roots/${state.root.id}/labels`, {
      method: "POST",
      body: JSON.stringify({ labels }),
    });
    state.root.labels = payload.labels;
    refs.newLabelInput.value = "";
    renderLabels();
    renderFileList();
    setStatus(`已添加标签: ${label}`);
  } catch (error) {
    setStatus(error.message || "添加标签失败");
  }
}

async function removeLabel(label) {
  if (!state.root) {
    return;
  }

  const labels = (state.root.labels || []).filter((item) => item !== label);
  try {
    const payload = await api(`/api/roots/${state.root.id}/labels`, {
      method: "POST",
      body: JSON.stringify({ labels }),
    });
    state.root.labels = payload.labels;
    if (currentItem()) {
      currentItem().tags = currentItem().tags.filter((item) => item !== label);
    }
    renderLabels();
    renderFileList();
    setStatus(`已移除标签: ${label}`);
  } catch (error) {
    setStatus(error.message || "移除标签失败");
  }
}

function toggleTag(label) {
  const item = currentItem();
  if (!item || !label) {
    return;
  }

  if (item.tags.includes(label)) {
    item.tags = item.tags.filter((entry) => entry !== label);
  } else {
    item.tags = [...item.tags, label];
  }
  renderLabels();
  renderFileList();
}

function handleHotkeys(event) {
  if (isEditingText(event.target)) {
    return;
  }

  const key = event.key.toLowerCase();
  if (!currentItem() && key !== "enter") {
    return;
  }

  if (key === " ") {
    event.preventDefault();
    applyAction("approve");
    return;
  }
  if (key === "k") {
    event.preventDefault();
    applyAction("remove");
    return;
  }
  if (key === "s") {
    event.preventDefault();
    applyAction("skip");
    return;
  }
  if (key === "u") {
    event.preventDefault();
    undoLastAction();
    return;
  }
  if (key === "r") {
    event.preventDefault();
    selectPreviousItem();
    return;
  }
  if (key === "p") {
    event.preventDefault();
    togglePlayback();
    return;
  }
  if (key === "j") {
    event.preventDefault();
    seekBy(-5);
    return;
  }
  if (key === "l") {
    event.preventDefault();
    seekBy(5);
    return;
  }

  if (/^[1-9]$/.test(key) && state.root?.labels?.length) {
    event.preventDefault();
    const label = state.root.labels[Number(key) - 1];
    if (label) {
      toggleTag(label);
    }
  }
}

function seekBy(deltaSeconds) {
  if (!refs.audioPlayer.duration) {
    return;
  }
  refs.audioPlayer.currentTime = Math.max(
    0,
    Math.min(refs.audioPlayer.duration, refs.audioPlayer.currentTime + deltaSeconds)
  );
  refs.currentTime.textContent = formatTime(refs.audioPlayer.currentTime);
  drawWaveform();
  drawSpectrogram();
}

function selectPreviousItem() {
  if (state.currentIndex > 0) {
    setCurrentIndex(state.currentIndex - 1, { autoplay: false });
  }
}

function selectNextReviewItem() {
  const nextIndex = findNextIndex(state.currentIndex);
  if (nextIndex >= 0) {
    setCurrentIndex(nextIndex, { autoplay: true });
  }
}

function findNextIndex(fromIndex) {
  for (let index = fromIndex + 1; index < state.items.length; index += 1) {
    if (state.items[index].status === "pending" || state.items[index].status === "skipped") {
      return index;
    }
  }
  for (let index = fromIndex + 1; index < state.items.length; index += 1) {
    if (!state.items[index].missing) {
      return index;
    }
  }
  return -1;
}

function replaceItem(item) {
  const index = indexById(item.id);
  if (index >= 0) {
    state.items[index] = item;
  }
}

function currentItem() {
  return state.items[state.currentIndex] || null;
}

function indexById(fileId) {
  return state.items.findIndex((item) => item.id === fileId);
}

function updateStatusBadge(item) {
  refs.statusBadge.textContent = statusLabel(item);
  refs.statusBadge.className = `status-badge ${statusClassName(item)}`;
}

function clearCurrentView(message) {
  state.currentIndex = -1;
  refs.fileTitle.textContent = message;
  refs.fileSubtitle.textContent = "选择目录后开始审核";
  refs.positionText.textContent = "0 / 0";
  refs.statusBadge.textContent = "未审核";
  refs.statusBadge.className = "status-badge status-pending";
  refs.noteInput.value = "";
  refs.audioPlayer.removeAttribute("src");
  refs.audioPlayer.load();
  refs.currentTime.textContent = "00:00.0";
  refs.durationText.textContent = "--:--";
  renderFileList();
  resetVisuals(message);
}

function resizeCanvases() {
  [refs.waveformCanvas, refs.spectrogramCanvas].forEach((canvas) => {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(320, Math.floor(rect.width));
    canvas.height = Math.max(180, Math.floor(rect.height));
  });
}

async function handleResize() {
  resizeCanvases();
  drawWaveform();
  drawSpectrogram();
  const item = currentItem();
  if (item && !item.missing) {
    state.visualizationToken += 1;
    try {
      await loadVisualizations(item, state.visualizationToken);
    } catch (error) {
      setStatus(error.message || "刷新可视化失败");
    }
  }
}

function seekFromCanvas(event, canvas) {
  if (!refs.audioPlayer.duration) {
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  refs.audioPlayer.currentTime = ratio * refs.audioPlayer.duration;
  refs.currentTime.textContent = formatTime(refs.audioPlayer.currentTime);
  drawWaveform();
  drawSpectrogram();
}

function formatTime(totalSeconds) {
  if (!Number.isFinite(totalSeconds)) {
    return "--:--";
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const tenths = Math.floor((totalSeconds % 1) * 10);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function actionLabel(action) {
  if (action === "approve") return "已通过";
  if (action === "remove") return "已移除";
  return "已跳过";
}

function statusLabel(item) {
  if (item.missing) return "缺失";
  if (item.status === "approved") return "通过";
  if (item.status === "removed") return "移除";
  if (item.status === "skipped") return "跳过";
  return "未审核";
}

function statusClassName(item) {
  if (item.missing) return "status-missing";
  if (item.status === "approved") return "status-approved";
  if (item.status === "removed") return "status-removed";
  if (item.status === "skipped") return "status-skipped";
  return "status-pending";
}

function setStatus(message) {
  refs.statusMessage.textContent = message;
}

function setLoading(isLoading) {
  refs.loadButton.disabled = isLoading;
  refs.reloadButton.disabled = isLoading;
  refs.browseButton.disabled = isLoading;
}

function isEditingText(target) {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target?.isContentEditable
  );
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function heatColor(value) {
  const hue = 220 - value * 180;
  const saturation = 90;
  const lightness = 14 + value * 58;
  return hslToRgb(hue / 360, saturation / 100, lightness / 100);
}

function hslToRgb(h, s, l) {
  if (s === 0) {
    const gray = Math.round(l * 255);
    return [gray, gray, gray];
  }

  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const r = hueToRgb(p, q, h + 1 / 3);
  const g = hueToRgb(p, q, h);
  const b = hueToRgb(p, q, h - 1 / 3);
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

function hueToRgb(p, q, t) {
  let value = t;
  if (value < 0) value += 1;
  if (value > 1) value -= 1;
  if (value < 1 / 6) return p + (q - p) * 6 * value;
  if (value < 1 / 2) return q;
  if (value < 2 / 3) return p + (q - p) * (2 / 3 - value) * 6;
  return p;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = "请求失败";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  return response.json();
}
