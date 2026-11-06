// 获取回放历史列表
async function loadReplayList() {
    const loadingEl = document.getElementById('loading');
    const replayListEl = document.getElementById('replay-list');
    
    loadingEl.style.display = 'flex';
    
    try {
        // 使用绝对路径
        const apiUrl = '/api/nae-deep-research/v1/replay/workspaces';
        console.log('加载回放列表:', apiUrl);
        const response = await fetch(apiUrl);
        const result = await response.json();
        
        if (result.code === 0 && result.data) {
            renderReplayList(result.data);
        } else {
            replayListEl.innerHTML = '<p class="no-data">暂无回放记录</p>';
        }
    } catch (error) {
        console.error('加载回放列表失败:', error);
        replayListEl.innerHTML = '<p class="error">加载失败，请稍后重试</p>';
    } finally {
        loadingEl.style.display = 'none';
    }
}

// 渲染回放列表
function renderReplayList(workspaces) {
    const replayListEl = document.getElementById('replay-list');
    
    if (workspaces.length === 0) {
        replayListEl.innerHTML = '<p class="no-data">暂无回放记录</p>';
        return;
    }
    
    const html = workspaces.map(workspace => `
        <div class="replay-item" data-workspace="${workspace.workspace_path}">
            <div class="replay-item-header">
                <h3 class="replay-title">${escapeHtml(workspace.title)}</h3>
                <span class="replay-time">${formatTime(workspace.created_time)}</span>
            </div>
            <div class="replay-item-info">
                <span class="replay-workspace"><i class="fas fa-folder"></i> ${workspace.workspace_name}</span>
                <span class="replay-messages"><i class="fas fa-envelope"></i> ${workspace.message_count} 条消息</span>
            </div>
            <div class="replay-item-actions">
                <button class="btn-replay" onclick="startReplay('${workspace.workspace_path}')">
                    <i class="fas fa-play"></i> 开始回放
                </button>
            </div>
        </div>
    `).join('');
    
    replayListEl.innerHTML = html;
}

// 开始回放
function startReplay(workspacePath) {
    console.log('开始回放，工作区路径:', workspacePath);
    
    // 根据当前路径决定跳转目标
    const targetPage = window.location.pathname.includes('/cosight/') 
        ? 'index.html' 
        : '/cosight/index.html';
    
    // 跳转到主页面并传递回放参数
    const replayUrl = `${targetPage}?replay=true&workspace=${encodeURIComponent(workspacePath)}`;
    console.log('跳转到:', replayUrl);
    window.location.href = replayUrl;
}

// 格式化时间
function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;
    
    // 小于1分钟
    if (diff < 60000) {
        return '刚刚';
    }
    // 小于1小时
    if (diff < 3600000) {
        return Math.floor(diff / 60000) + ' 分钟前';
    }
    // 小于1天
    if (diff < 86400000) {
        return Math.floor(diff / 3600000) + ' 小时前';
    }
    // 小于7天
    if (diff < 604800000) {
        return Math.floor(diff / 86400000) + ' 天前';
    }
    // 超过7天显示具体日期
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// HTML转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 搜索功能
document.getElementById('search-input')?.addEventListener('input', function(e) {
    const searchText = e.target.value.toLowerCase();
    const items = document.querySelectorAll('.replay-item');
    
    items.forEach(item => {
        const title = item.querySelector('.replay-title').textContent.toLowerCase();
        const workspace = item.querySelector('.replay-workspace').textContent.toLowerCase();
        
        if (title.includes(searchText) || workspace.includes(searchText)) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });
});

// 时间过滤
document.getElementById('time-filter')?.addEventListener('change', function(e) {
    const filterValue = e.target.value;
    const items = document.querySelectorAll('.replay-item');
    const now = new Date();
    
    items.forEach(item => {
        const timeText = item.querySelector('.replay-time').textContent;
        const workspacePath = item.getAttribute('data-workspace');
        
        // 从工作区路径中提取时间戳(格式: work_space/work_space_YYYYMMDD_HHMMSS_*)
        const match = workspacePath.match(/work_space_(\d{8})_(\d{6})/);
        
        if (!match) {
            item.style.display = '';
            return;
        }
        
        // 解析时间戳
        const dateStr = match[1]; // YYYYMMDD
        const timeStr = match[2]; // HHMMSS
        const year = parseInt(dateStr.substr(0, 4));
        const month = parseInt(dateStr.substr(4, 2)) - 1;
        const day = parseInt(dateStr.substr(6, 2));
        const hour = parseInt(timeStr.substr(0, 2));
        const minute = parseInt(timeStr.substr(2, 2));
        const second = parseInt(timeStr.substr(4, 2));
        
        const itemDate = new Date(year, month, day, hour, minute, second);
        const diff = now - itemDate;
        
        let shouldShow = false;
        
        switch (filterValue) {
            case 'all':
                shouldShow = true;
                break;
            case 'today':
                shouldShow = diff < 86400000; // 24小时
                break;
            case 'week':
                shouldShow = diff < 604800000; // 7天
                break;
            case 'month':
                shouldShow = diff < 2592000000; // 30天
                break;
        }
        
        item.style.display = shouldShow ? '' : 'none';
    });
});

// 页面加载时获取列表
window.addEventListener('DOMContentLoaded', () => {
    loadReplayList();
});

