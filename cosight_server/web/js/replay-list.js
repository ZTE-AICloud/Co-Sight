const REPLAY_API_BASE = "/api/nae-deep-research/v1/replay/workspaces";

async function loadReplayList() {
    const loadingEl = document.getElementById("loading");
    const replayListEl = document.getElementById("replay-list");

    if (loadingEl) {
        loadingEl.style.display = "flex";
    }

    try {
        const response = await fetch(REPLAY_API_BASE);
        const result = await response.json();

        if (result.code === 0 && Array.isArray(result.data)) {
            renderReplayList(result.data);
        } else {
            replayListEl.innerHTML = '<p class="no-data">暂无回放记录</p>';
        }
    } catch (error) {
        console.error("加载回放列表失败:", error);
        replayListEl.innerHTML = '<p class="error">加载失败，请稍后重试</p>';
    } finally {
        if (loadingEl) {
            loadingEl.style.display = "none";
        }
    }
}

function renderReplayList(workspaces) {
    const replayListEl = document.getElementById("replay-list");

    if (!Array.isArray(workspaces) || workspaces.length === 0) {
        replayListEl.innerHTML = '<p class="no-data">暂无回放记录</p>';
        return;
    }

    replayListEl.innerHTML = workspaces.map(workspace => `
        <div class="replay-item" data-workspace="${escapeHtml(workspace.workspace_path)}">
            <div class="replay-item-header">
                <h3 class="replay-title">${escapeHtml(workspace.title || "未命名任务")}</h3>
                <span class="replay-time">${formatTime(workspace.created_time)}</span>
            </div>
            <div class="replay-item-info">
                <span class="replay-workspace"><i class="fas fa-folder"></i> ${escapeHtml(workspace.workspace_name || "")}</span>
                <span class="replay-messages"><i class="fas fa-envelope"></i> ${Number(workspace.message_count || 0)} 条消息</span>
            </div>
            <div class="replay-item-actions">
                <button class="btn-rename" type="button" data-action="rename" data-workspace="${escapeHtml(workspace.workspace_path)}" data-title="${escapeHtml(workspace.title || "")}">
                    <i class="fas fa-pen"></i> 重命名
                </button>
                <button class="btn-delete" type="button" data-action="delete" data-workspace="${escapeHtml(workspace.workspace_path)}" data-title="${escapeHtml(workspace.title || "")}">
                    <i class="fas fa-trash"></i> 删除
                </button>
                <button class="btn-replay" type="button" data-action="replay" data-workspace="${escapeHtml(workspace.workspace_path)}">
                    <i class="fas fa-play"></i> 开始回放
                </button>
            </div>
        </div>
    `).join("");
}

function startReplay(workspacePath) {
    const targetPage = window.location.pathname.includes("/cosight/")
        ? "index.html"
        : "/cosight/index.html";
    const replayUrl = `${targetPage}?replay=true&workspace=${encodeURIComponent(workspacePath)}`;
    window.location.href = replayUrl;
}

async function renameReplay(workspacePath, currentTitle) {
    const nextTitle = window.prompt("请输入新的历史名称", currentTitle || "");
    if (nextTitle === null) {
        return;
    }

    const title = nextTitle.trim();
    if (!title) {
        window.alert("名称不能为空");
        return;
    }

    try {
        const response = await fetch(`${REPLAY_API_BASE}/rename`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_path: workspacePath,
                title,
            }),
        });
        const result = await response.json();
        if (result.code !== 0) {
            throw new Error(result.message || "重命名失败");
        }
        await loadReplayList();
    } catch (error) {
        console.error("重命名回放记录失败:", error);
        window.alert(error.message || "重命名失败");
    }
}

async function deleteReplay(workspacePath, currentTitle) {
    const title = currentTitle || workspacePath;
    if (!window.confirm(`确定删除历史记录「${title}」吗？`)) {
        return;
    }

    try {
        const response = await fetch(`${REPLAY_API_BASE}?workspace_path=${encodeURIComponent(workspacePath)}`, {
            method: "DELETE",
        });
        const result = await response.json();
        if (result.code !== 0) {
            throw new Error(result.message || "删除失败");
        }
        await loadReplayList();
    } catch (error) {
        console.error("删除回放记录失败:", error);
        window.alert(error.message || "删除失败");
    }
}

function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) {
        return "刚刚";
    }
    if (diff < 3600000) {
        return `${Math.floor(diff / 60000)} 分钟前`;
    }
    if (diff < 86400000) {
        return `${Math.floor(diff / 3600000)} 小时前`;
    }
    if (diff < 604800000) {
        return `${Math.floor(diff / 86400000)} 天前`;
    }
    return date.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
}

function filterReplayItems() {
    const searchText = (document.getElementById("search-input")?.value || "").toLowerCase();
    const filterValue = document.getElementById("time-filter")?.value || "all";
    const items = document.querySelectorAll(".replay-item");
    const now = new Date();

    items.forEach(item => {
        const title = item.querySelector(".replay-title")?.textContent.toLowerCase() || "";
        const workspace = item.querySelector(".replay-workspace")?.textContent.toLowerCase() || "";
        const workspacePath = item.getAttribute("data-workspace") || "";

        const keywordMatched = !searchText || title.includes(searchText) || workspace.includes(searchText);
        const timeMatched = matchTimeFilter(workspacePath, filterValue, now);

        item.style.display = keywordMatched && timeMatched ? "" : "none";
    });
}

function matchTimeFilter(workspacePath, filterValue, now) {
    if (filterValue === "all") {
        return true;
    }

    const match = workspacePath.match(/work_space_(\d{8})_(\d{6})/);
    if (!match) {
        return true;
    }

    const dateStr = match[1];
    const timeStr = match[2];
    const itemDate = new Date(
        Number(dateStr.slice(0, 4)),
        Number(dateStr.slice(4, 6)) - 1,
        Number(dateStr.slice(6, 8)),
        Number(timeStr.slice(0, 2)),
        Number(timeStr.slice(2, 4)),
        Number(timeStr.slice(4, 6)),
    );
    const diff = now - itemDate;

    if (filterValue === "today") {
        return diff < 86400000;
    }
    if (filterValue === "week") {
        return diff < 604800000;
    }
    if (filterValue === "month") {
        return diff < 2592000000;
    }
    return true;
}

document.getElementById("search-input")?.addEventListener("input", filterReplayItems);
document.getElementById("time-filter")?.addEventListener("change", filterReplayItems);

document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-action]");
    if (!button) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    const action = button.dataset.action;
    const workspacePath = button.dataset.workspace || "";
    const title = button.dataset.title || "";

    if (action === "replay") {
        startReplay(workspacePath);
    } else if (action === "rename") {
        renameReplay(workspacePath, title);
    } else if (action === "delete") {
        deleteReplay(workspacePath, title);
    }
});

window.addEventListener("DOMContentLoaded", () => {
    loadReplayList();
});
