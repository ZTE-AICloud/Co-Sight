// 工具调用状态管理
let toolCallHistory = [];
let activeToolCalls = new Map();
let toolCallCounter = 0;
let nodeToolPanels = new Map(); // 存储每个节点对应的工具面板
// 记录已因事件自动弹出的面板，避免重复创建
let autoOpenedPanels = new Set();

// 获取状态图标
function getStatusIcon(status) {
    return statusIcons[status] || "○";
}

// 工具提示防抖
let tooltipTimeout;

// 验证步骤提示框防抖
let verificationTooltipTimeout;

// 显示验证步骤提示框
function showVerificationTooltip(event, step) {
    // 清除之前的隐藏定时器
    if (verificationTooltipTimeout) {
        clearTimeout(verificationTooltipTimeout);
        verificationTooltipTimeout = null;
    }

    const tooltip = document.getElementById('verification-tooltip');
    if (!tooltip) return;

    // 计算提示框位置
    const iconRect = event.target.getBoundingClientRect();
    const tooltipWidth = 350;
    const tooltipHeight = 80;

    let left = iconRect.left + (iconRect.width / 2) - (tooltipWidth / 2);
    let top = iconRect.top - tooltipHeight - 8;

    // 确保提示框不会超出屏幕边界
    if (left < 10) {
        left = 10;
    }
    if (left + tooltipWidth > window.innerWidth - 10) {
        left = window.innerWidth - tooltipWidth - 10;
    }
    if (top < 10) {
        top = iconRect.bottom + 8;
    }

    // 设置提示框内容和位置
    tooltip.innerHTML = `
        <div style="font-weight: bold; margin-bottom: 4px;">${step.name}</div>
        <div style="font-size: 11px;">${step.description}</div>
    `;

    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
    tooltip.style.opacity = '1';
    tooltip.style.visibility = 'visible';
}

// 隐藏验证步骤提示框
function hideVerificationTooltip() {
    // 添加延迟隐藏，避免鼠标快速移动时闪烁
    verificationTooltipTimeout = setTimeout(() => {
        const tooltip = document.getElementById('verification-tooltip');
        if (tooltip) {
            tooltip.style.opacity = '0';
            tooltip.style.visibility = 'hidden';
        }
    }, 100);
}

// 显示工具提示
function showTooltip(event, d, showStatus = true) {
    // 清除之前的隐藏定时器
    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }

    // 计算工具提示位置，避免超出屏幕
    const x = event.pageX + 10;
    const y = event.pageY - 10;
    const tooltipWidth = 380;
    const tooltipHeight = 150;

    let finalX = x;
    let finalY = y;

    // 如果工具提示会超出右边界，则显示在鼠标左侧
    if (x + tooltipWidth > window.innerWidth) {
        finalX = event.pageX - tooltipWidth - 10;
    }

    // 如果工具提示会超出下边界，则显示在鼠标上方
    if (y + tooltipHeight > window.innerHeight) {
        finalY = event.pageY - tooltipHeight - 10;
    }

    const status = showStatus ? `<em>状态: ${getStatusText(d.status)}</em><br/>` : '';
    tooltip
        .style("opacity", 0)
        .style("left", finalX + "px")
        .style("top", finalY + "px")
        .html(`
            <strong>${d.name} - ${(d.fullName || d.title || '')}</strong><br/>
            <hr>
            ${status}
        `)
        .transition()
        .duration(200)
        .style("opacity", 1);
}

// 隐藏工具提示
function hideTooltip() {
    // 添加延迟隐藏，避免鼠标快速移动时闪烁
    tooltipTimeout = setTimeout(() => {
        tooltip
            .transition()
            .duration(200)
            .style("opacity", 0);
    }, 100);
}

// 获取状态文本
function getStatusText(status) {
    return statusTexts[status] || "未知";
}

// 根据节点ID获取对应的工作流程数据
function getWorkflowByNodeId(nodeId) {
    // 优先从messageService获取tool events数据
    if (typeof messageService !== 'undefined' && messageService.getStepToolEvents) {
        const stepIndex = nodeId - 1; // 节点ID从1开始，stepIndex从0开始
        const toolEvents = messageService.getStepToolEvents(stepIndex);

        if (toolEvents && toolEvents.length > 0) {
            console.log(`从tool events获取Step ${nodeId}的数据，共${toolEvents.length}个工具调用`);

            // 转换工具调用格式
            const tools = toolEvents
                // 过滤内部工具，不在面板展示
                .filter(toolEvent => toolEvent.tool_name !== 'mark_step')
                .map(toolEvent => {
                    const toolName = toolEvent.tool_name;
                    let toolResult = toolEvent.tool_result;
                    let url = null;
                    let path = null;
                    let descriptionOverride = null;

                    // 处理搜索工具的结果，提取URL
                    if (['search_baidu', 'search_google', 'search_tavily'].includes(toolName)) {
                        if (toolResult && toolResult.first_url) {
                            url = toolResult.first_url;
                        }
                    }

                    // 处理文件保存工具，提取路径
                    if (toolName === 'file_saver') {
                        try {
                            const args = JSON.parse(toolEvent.tool_args);
                            if (args.file_path) {
                                // 构造API工作区路径，例如：/api/nae-deep-research/v1/work_space/...
                                path = buildApiWorkspacePath(args.file_path);
                                // 设置描述为固定前缀 + 文件名
                                const filename = extractFileName(args.file_path);
                                if (filename) {
                                    descriptionOverride = `信息保存到:${filename}`;
                                }
                            }
                        } catch (e) {
                            console.warn('解析文件保存工具参数失败:', e);
                        }
                    }

                    // 结果文本处理
                    let resultText = '';
                    if (toolResult) {
                        if (typeof toolResult === 'string') {
                            resultText = toolResult;
                        } else if (toolResult.summary) {
                            resultText = toolResult.summary;
                        } else {
                            resultText = JSON.stringify(toolResult);
                        }
                    }

                    // file_saver 将 result 替换为描述内容，并清空描述
                    if (toolName === 'file_saver' && descriptionOverride) {
                        resultText = descriptionOverride;
                        descriptionOverride = '';
                    }

                    return {
                        tool: toolName,
                        toolName: getToolDisplayName(toolName),
                        description: descriptionOverride || `执行工具: ${getToolDisplayName(toolName)}`,
                        mode: 'sync',
                        duration: (toolEvent.duration || 0) * 1000, // 转换为毫秒
                        result: resultText,
                        url: url,
                        path: path,
                        timestamp: toolEvent.timestamp
                    };
                });

            // 获取step标题
            let stepTitle = `Step ${nodeId}`;
            if (typeof dagData !== 'undefined' && dagData.nodes) {
                const node = dagData.nodes.find(n => n.id === nodeId);
                if (node) {
                    stepTitle = node.fullName || node.title || `Step ${nodeId}`;
                }
            }

            return {
                title: stepTitle,
                tools: tools
            };
        }
    }

    // 回退到原有逻辑：从最新的 WebSocket 消息中获取工具调用信息
    const lastMessage = getLastManusStepMessage();
    if (!lastMessage || !lastMessage.data || !lastMessage.data.initData) {
        return null;
    }

    const initData = lastMessage.data.initData;
    const steps = initData.steps || [];
    const stepToolCalls = initData.step_tool_calls || {};

    // 节点ID从1开始，步骤数组从0开始
    const stepIndex = nodeId - 1;
    if (stepIndex < 0 || stepIndex >= steps.length) {
        return null;
    }

    const stepName = steps[stepIndex];
    const toolCalls = stepToolCalls[stepName];

    if (!toolCalls || !Array.isArray(toolCalls)) {
        return null;
    }

    // 转换工具调用格式
    const tools = toolCalls
        // 过滤内部工具，不在面板展示
        .filter(toolCall => toolCall.tool_name !== 'mark_step')
        .map(toolCall => {
            const toolName = toolCall.tool_name;
            let toolResult = toolCall.tool_result;
            let url = null;
            let path = null;
            let descriptionOverride = null;

            // 处理搜索工具的结果，提取URL
            if (['search_baidu', 'search_google', 'search_tavily'].includes(toolName)) {
                try {
                    const resultArray = parseSearchResults(toolResult);
                    if (Array.isArray(resultArray) && resultArray.length > 0) {
                        // 取第一个包含url字段的元素
                        const withUrl = resultArray.find(it => it && it.url) || resultArray[0];
                        url = withUrl && withUrl.url ? withUrl.url : null;
                    }
                } catch (e) {
                    console.warn('解析搜索工具结果失败:', e);
                }
            }

            // 处理文件保存工具，提取路径
            if (toolName === 'file_saver') {
                try {
                    const args = JSON.parse(toolCall.tool_args);
                    if (args.file_path) {
                        // 构造API工作区路径，例如：/api/nae-deep-research/v1/work_space/...
                        path = buildApiWorkspacePath(args.file_path);
                        // 设置描述为固定前缀 + 文件名
                        const filename = extractFileName(args.file_path);
                        if (filename) {
                            descriptionOverride = `信息保存到:${filename}`;
                        }
                    }
                } catch (e) {
                    console.warn('解析文件保存工具参数失败:', e);
                }
            }

            // 结果文本：优先使用原始字符串
            let resultText = typeof toolResult === 'string' ? toolResult : JSON.stringify(toolResult);
            // file_saver 将 result 替换为描述内容，并清空描述
            if (toolName === 'file_saver' && descriptionOverride) {
                resultText = descriptionOverride;
                descriptionOverride = '';
            }

            return {
                tool: toolName,
                toolName: getToolDisplayName(toolName),
                description: descriptionOverride || `执行工具: ${getToolDisplayName(toolName)}`,
                mode: 'sync',
                duration: 2000, // 默认持续时间
                result: resultText,
                url: url,
                path: path,
                timestamp: toolCall.timestamp
            };
        });

    return {
        title: stepName,
        tools: tools
    };
}

// 获取最新的 manus step 消息
function getLastManusStepMessage() {
    try {
        const raw = localStorage.getItem('cosight:lastManusStep');
        if (!raw) return null;
        const stored = JSON.parse(raw);
        return stored && stored.message;
    } catch (e) {
        console.warn('获取最新消息失败:', e);
        return null;
    }
}

// 获取工具显示名称
function getToolDisplayName(toolName) {
    const toolNames = {
        'search_baidu': '百度搜索',
        'search_google': '谷歌搜索',
        'search_tavily': 'Tavily搜索',
        'file_saver': '文件保存',
        'file_read': '文件读取',
        'data_analyzer': '数据分析',
        'predictor': '预测模型',
        'report_generator': '报告生成',
        'create_plan': '创建计划',
        'fetch_website_content': '获取网页内容'
    };
    return toolNames[toolName] || toolName;
}

// 解析搜索工具结果：兼容 JSON 字符串与 Python 风格单引号数组
function parseSearchResults(raw) {
    if (raw == null) return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw !== 'string') return [];
    // 优先尝试标准 JSON
    try {
        return JSON.parse(raw);
    } catch (_) { }
    // 回退：尝试将 Python 风格的单引号数组转为 JS 对象并安全求值
    try {
        // 直接用函数构造避免污染作用域；仅在受信任环境中使用
        // 原始字符串常见格式：[{'key': 'value', 'url': 'http://...'}, ...]
        // 浏览器下 eval/Function 可解析单引号 JS 对象字面量数组
        // 包装括号确保表达式上下文
        const fn = new Function('return (' + raw + ')');
        const val = fn();
        return Array.isArray(val) ? val : [];
    } catch (e) {
        console.warn('fallback 解析失败:', e);
        return [];
    }
}

// 规范化文件路径：去除盘符等，截断到 \Co-Sight\ 开头
function normalizeFilePathForFrontend(originalPath) {
    if (!originalPath || typeof originalPath !== 'string') return originalPath;
    try {
        // 统一分隔符处理副本
        const p = originalPath;
        // 优先匹配 Windows 分隔符
        let idx = p.indexOf('\\Co-Sight\\');
        if (idx === -1) {
            // 再匹配正斜杠形式（以防某些环境返回）
            idx = p.indexOf('/Co-Sight/');
            if (idx !== -1) {
                // 保持与示例一致，转回反斜杠并保留前导反斜杠
                const sliced = p.substring(idx).replace(/\//g, '\\');
                return sliced.startsWith('\\') ? sliced : '\\' + sliced;
            }
        } else {
            const sliced = p.substring(idx);
            return sliced.startsWith('\\') ? sliced : '\\' + sliced;
        }
        // 未命中关键词时，原样返回
        return originalPath;
    } catch (e) {
        return originalPath;
    }
}

// 从原始绝对路径构造 API 工作区路径：/api/nae-deep-research/v1/work_space/...
function buildApiWorkspacePath(originalPath) {
    return originalPath;
}

// 提取文件名（兼容 \ 与 /）
function extractFileName(p) {
    if (!p || typeof p !== 'string') return '';
    const unified = p.replace(/\\/g, '/');
    const idx = unified.lastIndexOf('/');
    return idx >= 0 ? unified.substring(idx + 1) : unified;
}

// 工具调用状态管理函数
function startToolCall(nodeId, tool) {
    // 过滤内部工具：mark_step 不进入面板与历史
    if (tool && (tool.tool === 'mark_step' || tool.tool_name === 'mark_step')) {
        return null;
    }
    const callId = `tool_${++toolCallCounter}_${Date.now()}`;
    const startTime = Date.now();

    const toolCall = {
        id: callId,
        nodeId: nodeId,
        duration: tool.duration,
        tool: tool.tool, // 英文名，用于映射和判断
        toolName: tool.toolName, // 中文名，用于界面显示
        description: tool.description,
        status: 'running',
        startTime: startTime,
        endTime: null,
        result: null,
        error: null,
        url: tool.url,
        path: tool.path
    };

    activeToolCalls.set(callId, toolCall);
    updateNodeToolPanel(nodeId, toolCall);

    return callId;
}

function completeToolCall(callId, result, success = true) {
    const toolCall = activeToolCalls.get(callId);
    if (!toolCall) return;

    const endTime = Date.now();
    toolCall.endTime = endTime;
    toolCall.duration = endTime - toolCall.startTime;
    toolCall.status = success ? 'completed' : 'failed';
    toolCall.result = result;

    // 移动到历史记录
    toolCallHistory.unshift(toolCall);
    activeToolCalls.delete(callId);

    updateNodeToolPanel(toolCall.nodeId, toolCall);

    // 限制历史记录数量
    if (toolCallHistory.length > 50) {
        toolCallHistory = toolCallHistory.slice(0, 50);
    }
}

function completeToolCall(callId, result, success = true) {
    const toolCall = activeToolCalls.get(callId);
    if (!toolCall) return;

    const endTime = Date.now();
    toolCall.endTime = endTime;
    toolCall.duration = endTime - toolCall.startTime;
    toolCall.status = success ? 'completed' : 'failed';
    toolCall.result = result;

    // 移动到历史记录
    toolCallHistory.unshift(toolCall);
    activeToolCalls.delete(callId);

    updateNodeToolPanel(toolCall.nodeId, toolCall);

    // 限制历史记录数量
    if (toolCallHistory.length > 50) {
        toolCallHistory = toolCallHistory.slice(0, 50);
    }
}

// 创建节点工具面板
function createNodeToolPanel(nodeId, nodeName, sticky = false) {
    const container = document.getElementById('tool-call-panels-container');
    const panelId = `tool-panel-${nodeId}`;

    // 如果面板已存在，直接显示
    let panel = document.getElementById(panelId);
    if (panel) {
        panel.classList.add('show');
        updatePanelPosition(panel, nodeId);
        return panel;
    }

    // 计算安全标题
    let safeTitle = nodeName;
    if (!safeTitle || /undefined/i.test(String(safeTitle))) {
        // 默认 Step N
        safeTitle = `Step ${nodeId}`;
    }
    // 尝试从 dagData 中获取更完整的标题：`${node.name} - ${(fullName||title||'')}`
    try {
        if (typeof dagData !== 'undefined' && dagData.nodes) {
            const node = dagData.nodes.find(n => n.id === nodeId);
            if (node) {
                const namePart = node.name || `Step ${nodeId}`;
                const detailPart = node.fullName || node.title || '';
                safeTitle = detailPart ? `${namePart} - ${detailPart}` : namePart;
            }
        }
    } catch (e) { }

    // 创建新面板
    panel = document.createElement('div');
    panel.id = panelId;
    panel.className = 'tool-call-panel';
    panel.setAttribute('data-node-id', nodeId);
    panel.setAttribute('data-sticky', sticky);

    panel.innerHTML = `
        <div class="panel-header" data-panel-id="${panelId}" data-sticky="${sticky}">
            <h3><i class="fas fa-tools"></i> <span class="panel-title" title="${safeTitle}">${safeTitle}</span></h3>
            <button class="btn-close" onclick="closeNodeToolPanel(${nodeId})">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="tool-call-list" id="tool-call-list-${nodeId}">
            <!-- 工具调用项目将动态添加到这里 -->
        </div>
    `;

    container.appendChild(panel);
    nodeToolPanels.set(nodeId, panel);

    // 绑定关闭按钮事件，避免作用域问题与拖拽干扰
    try {
        const closeBtn = panel.querySelector('.btn-close');
        const headerEl = panel.querySelector('.panel-header');
        // 确保 header 定位上下文，避免绝对定位按钮偏移
        try {
            if (headerEl) {
                const cs = window.getComputedStyle(headerEl);
                if (cs && cs.position === 'static') {
                    headerEl.style.position = 'relative';
                }
            }
        } catch (_) { }
        if (closeBtn) {
            // 强制按钮位于顶层并可命中
            try {
                closeBtn.style.position = 'absolute';
                closeBtn.style.top = '8px';
                closeBtn.style.right = '8px';
                closeBtn.style.zIndex = '10';
                closeBtn.style.pointerEvents = 'auto';
            } catch (_) { }

            // 阻止事件冒泡，避免触发header的拖拽mousedown
            closeBtn.addEventListener('mousedown', function (e) {
                console.log(`[panel:${nodeId}] close button mousedown`);
                e.stopPropagation();
            });
            closeBtn.addEventListener('click', function (e) {
                console.log(`[panel:${nodeId}] close button clicked`);
                e.preventDefault();
                e.stopPropagation();
                try {closeNodeToolPanel(nodeId);} catch (err) {console.warn(`[panel:${nodeId}] close error`, err);}
            });
        } else {
            console.warn(`[panel:${nodeId}] close button not found`);
        }
    } catch (err) {console.warn(`[panel:${nodeId}] bind close error`, err);}

    // 初始化拖拽功能
    initNodePanelDrag(panel);

    // 显示面板并定位
    panel.classList.add('show');

    // 添加调试信息
    console.log(`Creating panel for node ${nodeId}`);
    debugPanelPosition(nodeId);

    updatePanelPosition(panel, nodeId);

    return panel;
}

// 更新面板位置
function updatePanelPosition(panel, nodeId) {
    const nodeElement = findNodeElement(nodeId);
    if (!nodeElement) return;

    const nodeRect = nodeElement.getBoundingClientRect();

    // 计算面板位置（节点左侧）
    const panelWidth = 350;
    const margin = 20;
    const left = nodeRect.left - panelWidth - margin;

    // 确保面板不会超出视口边界
    const finalLeft = Math.max(10, Math.min(left, window.innerWidth - panelWidth - 10));

    // 智能计算垂直位置，考虑面板扩展方向
    const finalTop = calculateOptimalPanelTop(panel, nodeRect);

    const sticky = panel.getAttribute("data-sticky");
    // 固定贴在屏幕左侧显示
    // panel.style.left = `${finalLeft}px`;
    panel.style.left = sticky == "true" ? `${finalLeft}px` : `16px`;
    panel.style.top = `${finalTop}px`;
}

// 计算面板的最优垂直位置
function calculateOptimalPanelTop(panel, nodeRect) {
    const margin = 20;
    const panelHeight = panel.offsetHeight;

    // 直接使用相对于视口的位置（与test-panel.html保持一致）
    const idealTop = nodeRect.top + nodeRect.height / 2 - panelHeight / 2;
    const idealBottom = idealTop + panelHeight;

    let finalTop = idealTop;

    // 关键判断：面板是否会超出屏幕底部
    const willExceedBottom = idealBottom > window.innerHeight - margin;
    if (willExceedBottom) {
        // 向上扩展：将面板底部对齐到屏幕底部
        finalTop = window.innerHeight - panelHeight - margin;

        // 如果向上扩展后顶部空间不足，则居中显示
        if (finalTop < margin) {
            finalTop = Math.max(margin, (window.innerHeight - panelHeight) / 2);
        }
    } else if (idealTop < margin) {
        // 如果面板会超出屏幕顶部, 向下扩展：将面板顶部对齐到屏幕顶部
        finalTop = margin;
    } else {
        // 如果面板完全在屏幕内，保持理想位置
        finalTop = idealTop;
    }

    return finalTop;
}

// 查找节点DOM元素
function findNodeElement(nodeId) {
    const nodeTexts = document.querySelectorAll('.node-text');
    for (let textElement of nodeTexts) {
        if (textElement.id == nodeId) {
            return textElement.closest('.node');
        }
    }
    return null;
}

// 调试函数：打印面板位置信息
function debugPanelPosition(nodeId) {
    const nodeElement = findNodeElement(nodeId);
    if (nodeElement) {
        const nodeRect = nodeElement.getBoundingClientRect();
        const panel = nodeToolPanels.get(nodeId);

        console.log(`Node ${nodeId} position:`, {
            left: nodeRect.left,
            top: nodeRect.top,
            width: nodeRect.width,
            height: nodeRect.height
        });

        if (panel) {
            console.log(`Panel ${nodeId} info:`, {
                currentHeight: panel.offsetHeight,
                maxHeight: Math.min(400, window.innerHeight * 0.6),
                windowHeight: window.innerHeight
            });
        }

        console.log('Window size:', {
            width: window.innerWidth,
            height: window.innerHeight
        });
    } else {
        console.log(`Node ${nodeId} not found`);
    }
}

// 关闭节点工具面板
function closeNodeToolPanel(nodeId) {
    const panel = nodeToolPanels.get(nodeId);
    console.log(`[panel:${nodeId}] closeNodeToolPanel invoked, hasPanel=`, !!panel);
    if (panel) {
        // 清理内容观察器
        if (panel._contentObserver) {
            panel._contentObserver.disconnect();
            panel._contentObserver = null;
        }

        panel.classList.remove('show');
        // 延迟删除DOM元素，让动画完成
        setTimeout(() => {
            try {
                if (panel.parentNode) {
                    panel.parentNode.removeChild(panel);
                    console.log(`[panel:${nodeId}] panel DOM removed`);
                }
            } catch (e) {
                console.warn(`[panel:${nodeId}] remove panel error`, e);
            }
            nodeToolPanels.delete(nodeId);
            console.log(`[panel:${nodeId}] panel map entry deleted`);
        }, 300);
    } else {
        console.warn(`[panel:${nodeId}] panel not found in map`);
    }
}

// 切换节点工具面板的显示状态
function toggleNodeToolPanel(nodeId, nodeName) {
    const panel = nodeToolPanels.get(nodeId);

    if (panel && panel.classList.contains('show')) {
        // 面板存在且已显示，则关闭它
        closeNodeToolPanel(nodeId);
        return false; // 返回false表示面板被关闭
    } else {
        // 面板不存在或未显示，则创建并显示
        createNodeToolPanel(nodeId, nodeName, true);
        return true; // 返回true表示面板被打开
    }
}

// 初始化节点面板拖拽功能
function initNodePanelDrag(panel) {
    const header = panel.querySelector('.panel-header');
    let isDragging = false;
    let currentX, currentY, initialX, initialY, xOffset = 0, yOffset = 0;

    header.addEventListener('mousedown', dragStart);
    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', dragEnd);

    function dragStart(e) {
        if (!panel.classList.contains('show')) {
            return;
        }

        initialX = e.clientX - xOffset;
        initialY = e.clientY - yOffset;

        if (e.target === header || header.contains(e.target)) {
            isDragging = true;
            panel.classList.add('dragging');
        }
    }

    function drag(e) {
        if (isDragging) {
            e.preventDefault();
            currentX = e.clientX - initialX;
            currentY = e.clientY - initialY;

            xOffset = currentX;
            yOffset = currentY;

            // 使用 transform 来移动面板位置
            panel.style.transform = `translate(${currentX}px, ${currentY}px)`;
        }
    }

    function dragEnd(e) {
        if (isDragging) {
            initialX = currentX;
            initialY = currentY;
            isDragging = false;
            panel.classList.remove('dragging');
        }
    }
}

// 关闭所有验证步骤提示框
function closeAllVerificationTooltips() {
    hideVerificationTooltip();
}

// 创建验证步骤图标
function createVerificationIcons(toolCall) {
    // 获取工具对应的验证步骤ID
    const stepIds = getVerificationStepsForTool(toolCall.tool, toolCall.result || '');

    if (!stepIds || stepIds.length === 0) {
        return null;
    }

    const iconsContainer = document.createElement('div');
    iconsContainer.className = 'verification-icons';

    stepIds.forEach(stepId => {
        const step = verificationSteps.find(s => s.id === stepId);
        if (!step) return;

        const icon = document.createElement('div');
        icon.className = `verification-icon ${stepId}`;
        icon.innerHTML = `<i class="${step.icon}"></i>`;

        // 添加悬停事件
        icon.addEventListener('mouseenter', function (event) {
            showVerificationTooltip(event, step);
        });

        icon.addEventListener('mouseleave', function () {
            hideVerificationTooltip();
        });
        iconsContainer.appendChild(icon);
    });

    return iconsContainer;
}

// 创建工具调用项（使用原始的实现方式）
function createToolCallItem(toolCall) {
    const item = document.createElement('div');
    item.className = `tool-call-item ${toolCall.status}`;
    item.dataset.callId = toolCall.id;

    // 检查工具是否有url或path属性，如果有则添加点击功能
    const hasContent = toolCall.url || toolCall.path;
    if (hasContent) {
        item.style.cursor = 'pointer';
        item.title = '点击查看详情';

        // 添加点击事件
        item.addEventListener('click', function () {
            showRightPanelForTool(toolCall);
        });

        // 添加悬停效果
        item.addEventListener('mouseenter', function () {
            this.style.backgroundColor = '#f0f8ff';
        });

        item.addEventListener('mouseleave', function () {
            this.style.backgroundColor = '';
        });
    }

    const icon = document.createElement('div');
    icon.className = `tool-call-icon ${toolCall.status}`;

    let iconClass = '';
    switch (toolCall.status) {
        case 'running':
            iconClass = 'fas fa-cog loading-spinner';
            break;
        case 'completed':
            // 根据工具类型显示特定图标
            iconClass = getToolSpecificIcon(toolCall.tool);
            break;
        case 'failed':
            iconClass = 'fas fa-times';
            break;
    }
    if (toolCall.tool === 'search_baidu') {
        icon.innerHTML = `<img src="/cosight/images/baidu.png" style="width: 24px; height: 24px;">`;
    } else {
        icon.innerHTML = `<i class="${iconClass}"></i>`;
    }

    const content = document.createElement('div');
    content.className = 'tool-call-content';

    const name = document.createElement('div');
    name.className = 'tool-call-name';

    // 创建工具名称文本
    const nameText = document.createElement('span');
    nameText.textContent = toolCall.toolName;
    name.appendChild(nameText);

    // 添加验证步骤图标
    const verificationIcons = createVerificationIcons(toolCall);
    if (verificationIcons) {
        name.appendChild(verificationIcons);
    }

    // 如果有内容可查看，在工具名称后添加提示图标
    // if (hasContent) {
    //     const clickHint = document.createElement('span');
    //     clickHint.innerHTML = ' <i class="fas fa-external-link-alt" style="font-size: 10px; color: #007bff; margin-left: 5px;"></i>';
    //     name.appendChild(clickHint);
    // }

    const status = document.createElement('div');
    status.className = 'tool-call-status';
    status.textContent = toolCall.description;

    // 注释掉执行时间显示
    // const duration = document.createElement('div');
    // duration.className = 'tool-call-duration';

    // if (toolCall.status === 'running') {
    //     duration.textContent = `运行中... ${Math.floor((Date.now() - toolCall.startTime) / 1000)}s`;
    // } else if (toolCall.duration) {
    //     duration.textContent = `耗时: ${(toolCall.duration / 1000).toFixed(2)}s`;
    // }

    content.appendChild(name);
    content.appendChild(status);
    // content.appendChild(duration);

    if (toolCall.result && toolCall.status !== 'running') {
        const result = document.createElement('div');
        result.className = 'tool-call-result';
        result.textContent = typeof toolCall.result === 'string'
            ? toolCall.result
            : JSON.stringify(toolCall.result, null, 2);
        content.appendChild(result);
    }

    item.appendChild(icon);
    item.appendChild(content);

    return item;
}

// 更新节点工具面板内容
function updateNodeToolPanel(nodeId, toolCall) {
    // 过滤内部工具：mark_step 不更新面板
    if (toolCall && toolCall.tool === 'mark_step') {
        return;
    }
    let panel = nodeToolPanels.get(nodeId);
    if (!panel) {
        // 面板不存在：在首次事件到来时自动创建并展示
        try {
            if (!autoOpenedPanels.has(nodeId)) {
                let nodeName = `Step ${nodeId}`;
                try {
                    if (typeof dagData !== 'undefined' && dagData.nodes) {
                        const node = dagData.nodes.find(n => n.id === nodeId);
                        if (node) {
                            const title = node.fullName || node.title || '';
                            nodeName = title ? `Step ${nodeId} - ${title}` : `Step ${nodeId}`;
                        }
                    }
                } catch (_) { }
                panel = createNodeToolPanel(nodeId, nodeName, true);
                autoOpenedPanels.add(nodeId);
            }
        } catch (_) { }
        // 若仍未创建成功，则直接返回避免报错
        panel = nodeToolPanels.get(nodeId);
        if (!panel) return;
    }

    const toolCallList = panel.querySelector('.tool-call-list');
    if (!toolCallList) return;

    // 查找或创建工具调用项
    let toolCallItem = toolCallList.querySelector(`[data-call-id="${toolCall.id}"]`);
    const isExistingItem = !!toolCallItem;
    if (!toolCallItem) {
        // 使用原始的createToolCallItem函数创建新的工具调用项
        toolCallItem = createToolCallItem(toolCall);
        // 将新的工具调用项添加到列表的顶部（最新显示在最上面）
        toolCallList.insertBefore(toolCallItem, toolCallList.firstChild);
    } else {
        // 如果已存在，则更新内容
        const newItem = createToolCallItem(toolCall);
        toolCallList.replaceChild(newItem, toolCallItem);
        toolCallItem = newItem;
    }

    // 首次出现且具备可展示内容（url/path）时，自动在右侧展示
    try {
        if (!isExistingItem && (toolCall.url || toolCall.path)) {
            showRightPanelForTool(toolCall);
        }
    } catch (_) {}

    // 若已有记录被更新为具备可展示内容且非运行中，也自动在右侧展示
    try {
        if (isExistingItem && (toolCall.url || toolCall.path) && toolCall.status !== 'running') {
            showRightPanelForTool(toolCall);
        }
    } catch (_) {}

    // 内容更新后，重新计算面板位置以适应新的高度
    setTimeout(() => {
        const panel = nodeToolPanels.get(nodeId);
        if (panel && panel.classList.contains('show')) {
            console.log('Updating panel position after content change...');
            updatePanelPosition(panel, nodeId);
        }
    }, 100); // 进一步增加延迟时间确保DOM更新完成
}

// 获取工具调用状态图标
function getToolCallStatusIcon(status) {
    return toolCallStatusIcons[status] || 'fas fa-question-circle';
}

// 获取工具调用状态文本
function getToolCallStatusText(status) {
    return toolCallStatusTexts[status] || '未知';
}

// 根据工具类型获取特定图标
function getToolSpecificIcon(tool) {
    const toolIcons = {
        'file_read': 'fas fa-book-open',
        'file_saver': 'fas fa-save',
        'search_baidu': 'fab fa-baidu',
        'search_google': 'fab fa-google',
        'execute_code': 'fas fa-file-code',
        'create_html_report': 'fas fa-chart-line'
    };

    return toolIcons[tool] || 'fas fa-check'; // 默认使用对勾图标
}

// 添加工具调用到节点面板（用于节点点击）
function addToolCallToNodePanel(nodeId, tool) {
    // 过滤内部工具：mark_step 不添加到面板
    if (tool && (tool.tool === 'mark_step' || tool.tool_name === 'mark_step')) {
        return;
    }
    // 直接创建已完成的工具调用，不模拟执行过程
    const callId = `tool_${++toolCallCounter}_${Date.now()}`;
    const startTime = Date.now() - tool.duration; // 设置开始时间为duration之前
    const endTime = Date.now();

    const toolCall = {
        id: callId,
        nodeId: nodeId,
        duration: tool.duration,
        tool: tool.tool,
        toolName: tool.toolName,
        description: tool.description,
        status: 'completed',
        startTime: startTime,
        endTime: endTime,
        result: tool.result || `工具 ${tool.toolName} 执行完成`,
        error: null,
        url: tool.url || null,  // 添加url属性
        path: tool.path || null // 添加path属性
    };

    // 直接添加到历史记录
    toolCallHistory.unshift(toolCall);

    // 限制历史记录数量
    if (toolCallHistory.length > 50) {
        toolCallHistory = toolCallHistory.slice(0, 50);
    }

    // 直接更新面板显示
    updateNodeToolPanel(nodeId, toolCall);
}

// 更新所有面板位置
function updateAllPanelPositions() {
    nodeToolPanels.forEach((panel, nodeId) => {
        if (panel.classList.contains('show')) {
            updatePanelPosition(panel, nodeId);
        }
    });
}

// 强制更新指定面板位置（用于调试）
function forceUpdatePanelPosition(nodeId) {
    const panel = nodeToolPanels.get(nodeId);
    if (panel && panel.classList.contains('show')) {
        console.log(`Force updating panel position for node ${nodeId}`);
        updatePanelPosition(panel, nodeId);
    } else {
        console.log(`Panel for node ${nodeId} not found or not visible`);
    }
}

// 全局调试函数（可在浏览器控制台中使用）
window.debugPanel = {
    updatePosition: forceUpdatePanelPosition,
    showInfo: debugPanelPosition,
    updateAll: updateAllPanelPositions,
    panels: () => nodeToolPanels,
    // 新增：手动切换全屏模式
    toggleMaximize: () => {
        toggleMaximizePanel();
    }
};

// 输入框处理函数
function initInputHandler() {
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const initialMessageInput = document.getElementById('initial-message-input');
    const initialSendButton = document.getElementById('initial-send-button');

    // 初始化输入框处理
    if (messageInput && sendButton) {
        // 发送消息函数
        function sendMessage() {
            credibilityService.clearCredibilityData();
            const message = messageInput.value.trim();
            if (message) {
                console.log('发送消息:', message);
                // 清理之前的tool events和UI状态
                if (window.messageService && typeof window.messageService.clearStepToolEvents === 'function') {
                    window.messageService.clearStepToolEvents();
                }

                // 关闭所有已打开的工具面板
                if (nodeToolPanels && nodeToolPanels.size > 0) {
                    const panelIds = Array.from(nodeToolPanels.keys());
                    panelIds.forEach(nodeId => {
                        try {closeNodeToolPanel(nodeId);} catch (_) { }
                    });
                    if (nodeToolPanels.clear) nodeToolPanels.clear();
                }

                // 清理右侧内容
                try {cleanupAllResources();} catch (_) { }
                messageService.sendMessage(message);
                // 清空输入框
                messageInput.value = '';
            }
        }

        // 点击发送按钮
        sendButton.addEventListener('click', sendMessage);

        // 按回车键发送
        messageInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });

        // 输入框获得焦点时的样式
        messageInput.addEventListener('focus', function () {
            sendButton.style.color = '#007bff';
        });

        // 输入框失去焦点时的样式
        messageInput.addEventListener('blur', function () {
            sendButton.style.color = '#666';
        });
    }

    // 初始化输入框处理
    if (initialMessageInput && initialSendButton) {
        // 发送初始消息函数
        function sendInitialMessage() {
            credibilityService.clearCredibilityData();
            const message = initialMessageInput.value.trim();

            // 新会话开始：优先清空缓存并关闭所有已打开的step面板
            try {
                if (typeof window !== 'undefined' && typeof window.resetSessionCaches === 'function') {
                    window.resetSessionCaches();
                } else {
                    // 安全回退：尽力关闭面板与清理资源
                    try {
                        if (nodeToolPanels && nodeToolPanels.size > 0) {
                            Array.from(nodeToolPanels.keys()).forEach(id => {
                                try {closeNodeToolPanel(id);} catch (_) { }
                            });
                            if (nodeToolPanels.clear) nodeToolPanels.clear();
                        }
                    } catch (_) { }
                    try {cleanupAllResources();} catch (_) { }
                    try {localStorage.removeItem('cosight:lastManusStep');} catch (_) { }
                }
            } catch (_) { }

            // if (message) {
            console.log('发送初始消息:', message);
            // 隐藏初始输入框并显示主界面
            hideInitialInputAndShowMain(message);
            // }
        }

        // 点击发送按钮
        initialSendButton.addEventListener('click', sendInitialMessage);

        // 按回车发送
        initialMessageInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendInitialMessage();
            }
        });

        // 自动调整文本框高度
        initialMessageInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 200) + 'px';
        });

        // 页面加载完成后自动让初始输入框获得焦点
        setTimeout(() => {
            initialMessageInput.focus();
        }, 100);
    }
}

// 隐藏初始输入框并显示主界面
function hideInitialInputAndShowMain(message) {
    const initialInputContainer = document.querySelector('.initial-input-container');
    const middleContainer = document.querySelector('.middle-container');

    if (initialInputContainer && middleContainer) {
        // 隐藏初始输入框
        initialInputContainer.classList.add('hidden');

        // 延迟显示主界面，让过渡动画更流畅
        setTimeout(() => {
            middleContainer.classList.add('show');
            // 处理用户消息
            if (message) {
                messageService.sendMessage(message);
            } else {
                // todo 消息为空时，进入主界面调试
                // startSimulateWorkflow();
            }
        }, 300); // 等待初始输入框的隐藏动画完成
    }
}

function updateDynamicTitle(title) {
    const titleContainer = document.getElementById('title-container');
    const dynamicTitle = document.getElementById('dynamic-title');
    if (titleContainer && dynamicTitle) {
        dynamicTitle.textContent = title;
        titleContainer.style.opacity = '1';
    }
}

// 生成状态文本
function generateStatusText(tool, url, path) {
    if (tool === 'file_read') {
        const fileName = path ? path.split('/').pop() || path.split('\\').pop() : '未知文件';
        return `正在读取文件 ${fileName}`;
    } else if (tool === 'file_saver') {
        const fileName = path ? path.split('/').pop() || path.split('\\').pop() : '未知文件';
        return `正在保存文件 ${fileName}`;
    } else if (tool === 'search_baidu' || tool === 'search_google') {
        return `正在浏览 ${url}`;
    } else if (url) {
        return `正在浏览 ${url}`;
    } else if (path) {
        const fileName = path.split('/').pop() || path.split('\\').pop();
        return `正在处理文件 ${fileName}`;
    }
    return '正在处理...';
}

function toggleLoadingIndicator(isShow) {
    const loadingIndicator = document.getElementById('loading-indicator');
    if (loadingIndicator) {
        loadingIndicator.style.display = isShow ? 'flex' : 'none';
    }
}

// 清理iframe和相关资源
function cleanupContentResources() {
    const iframe = document.getElementById('content-iframe');
    const markdownContent = document.getElementById('markdown-content');

    if (iframe) {
        // 清理事件监听器
        iframe.onload = null;
        iframe.onerror = null;

        // 清理iframe内容
        iframe.src = 'about:blank';

        // 清理可能存在的超时定时器
        if (iframe._loadingTimeout) {
            clearTimeout(iframe._loadingTimeout);
            iframe._loadingTimeout = null;
        }
    }

    if (markdownContent) {
        // 清理markdown内容
        markdownContent.innerHTML = '';
    }

    // 隐藏加载指示器
    toggleLoadingIndicator(false);

    console.log('iframe资源清理完成');
}

// 全面的内存清理机制
function cleanupAllResources() {
    console.log('开始全面资源清理...');

    // 1. 清理iframe资源
    cleanupContentResources();

    // 2. 清理所有可能存在的定时器
    const tooltipTimeout = window.tooltipTimeout;
    const stepsTooltipTimeout = window.stepsTooltipTimeout;

    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        window.tooltipTimeout = null;
    }

    if (stepsTooltipTimeout) {
        clearTimeout(stepsTooltipTimeout);
        window.stepsTooltipTimeout = null;
    }

    // 3. 清理DOM事件监听器（如果存在）
    const rightContainer = document.getElementById('right-container');
    if (rightContainer) {
        // 移除可能的事件监听器
        rightContainer.onclick = null;
        rightContainer.onmouseover = null;
        rightContainer.onmouseout = null;
    }

    // 4. 清理工具提示
    const tooltip = d3.select('#tooltip');
    if (tooltip && !tooltip.empty()) {
        tooltip.style('opacity', 0);
    }

    const stepsTooltip = document.getElementById('steps-tooltip');
    if (stepsTooltip) {
        stepsTooltip.classList.remove('show');
    }

    // 5. 强制垃圾回收（如果浏览器支持）
    if (window.gc && typeof window.gc === 'function') {
        try {
            window.gc();
            console.log('执行了垃圾回收');
        } catch (e) {
            console.log('垃圾回收不可用');
        }
    }

    // 6. 清理可能的内存泄漏
    if (window.performance && window.performance.memory) {
        const memory = window.performance.memory;
        console.log('内存使用情况:', {
            used: Math.round(memory.usedJSHeapSize / 1024 / 1024) + 'MB',
            total: Math.round(memory.totalJSHeapSize / 1024 / 1024) + 'MB',
            limit: Math.round(memory.jsHeapSizeLimit / 1024 / 1024) + 'MB'
        });
    }

    console.log('全面资源清理完成');
}

// 检查并恢复DAG数据
function checkAndRestoreDAGData() {
    try {
        // F5刷新场景：只清理UI状态，保留localStorage数据
        resetUICaches();

        // 检查是否有保存的manus step消息
        const lastManusStep = getLastManusStepMessage();
        if (lastManusStep) {
            console.log('发现保存的DAG数据，开始恢复...');

            // 恢复DAG图
            const result = createDag({ data: lastManusStep.data, topic: 'restored' });
            if (result) {
                // 显示标题
                if (lastManusStep.data.initData && lastManusStep.data.initData.title) {
                    updateDynamicTitle(lastManusStep.data.initData.title);
                }

                // 显示主界面
                hideInitialInputAndShowMain('');

                console.log('DAG数据恢复完成');
            }
        }
    } catch (e) {
        console.warn('恢复DAG数据失败:', e);
    }
}

// 页面加载完成后初始化
// 显示右侧面板内容
function showRightPanel() {
    const rightContainer = document.getElementById('right-container');
    if (!rightContainer) return false;

    // 先清理之前的资源
    cleanupContentResources();

    // 显示右侧容器
    rightContainer.classList.add('show');

    // 切换按钮紧凑模式
    toggleButtonsCompactMode(true);
    setTimeout(() => handleResize(), 500);

    // 检查并重新定位步骤信息弹窗
    setTimeout(() => {
        const stepsTooltip = document.getElementById('steps-tooltip');
        if (stepsTooltip && stepsTooltip.classList.contains('show')) {
            // 如果步骤信息弹窗正在显示，重新计算其位置
            showStepsTooltip();
        }
    }, 300); // 稍微延迟确保布局变化完成

    return true
}

function showRightPanelForTool(toolCall) {
    const result = showRightPanel();
    if (!result) {
        return;
    }

    const url = toolCall.url;
    const path = toolCall.path;
    const tool = toolCall.tool;
    const iframe = document.getElementById('content-iframe');
    const markdownContent = document.getElementById('markdown-content');
    const statusElement = document.getElementById('right-container-status');

    if (url) {
        // 显示加载提示
        toggleLoadingIndicator(true);

        // 更新状态文本
        if (statusElement) {
            statusElement.textContent = generateStatusText(tool, url, path);
            statusElement.className = 'loading';
        }

        // 设置iframe显示
        iframe.style.display = 'block';
        markdownContent.style.display = 'none';

        // 先设置为空白页
        iframe.src = 'about:blank';

        // 等待清理完成后再加载新内容
        setTimeout(() => {
            let isBlank = true;

            // 设置加载超时机制（10秒）
            iframe._loadingTimeout = setTimeout(() => {
                if (isBlank) return;
                toggleLoadingIndicator(false);
                if (statusElement) {
                    statusElement.textContent = `加载超时: ${url}`;
                    statusElement.className = 'error';
                }
                console.warn('iframe加载超时:', url);
            }, 10000);

            // 设置加载完成事件监听器
            iframe.onload = function () {
                console.log("iframe.onload =================> ", isBlank)
                if (isBlank) {
                    return;
                }

                // 清理超时定时器
                if (iframe._loadingTimeout) {
                    clearTimeout(iframe._loadingTimeout);
                    iframe._loadingTimeout = null;
                }

                // 立即隐藏loading，避免与网页内容共存
                toggleLoadingIndicator(false);
                // 更新状态文本
                if (statusElement) {
                    statusElement.textContent = generateStatusText(tool, url, path);
                    statusElement.className = 'success';
                }
                console.log('iframe加载成功:', url);
            };

            // 设置加载错误事件监听器
            iframe.onerror = function () {
                // 清理超时定时器
                if (iframe._loadingTimeout) {
                    clearTimeout(iframe._loadingTimeout);
                    iframe._loadingTimeout = null;
                }

                // 隐藏加载提示
                toggleLoadingIndicator(false);
                // 更新状态文本
                if (statusElement) {
                    statusElement.textContent = `网页加载失败: ${url}`;
                    statusElement.className = 'error';
                }
                console.error('iframe加载失败:', url);
            };

            // 加载新内容
            iframe.src = url;
            isBlank = false;
        }, 100); // 增加延迟时间确保清理完成

    } else if (path) {
        // 根据扩展名决定渲染方式
        const fileName = path.split('/').pop() || path.split('\\').pop() || '';
        const ext = (fileName.split('.').pop() || '').toLowerCase();

        // 将绝对路径转换为相对路径（与 loadMarkdownFile 保持一致）
        let relativePath = path;
        if (relativePath.includes('workspace')) {
            const workspaceIndex = relativePath.indexOf('workspace');
            if (workspaceIndex !== -1) {
                relativePath = relativePath.substring(workspaceIndex);
            }
        }

        if (ext === 'html' || ext === 'htm') {
            // 使用 iframe 显示 HTML 文件
            toggleLoadingIndicator(true);
            if (statusElement) {
                statusElement.textContent = generateStatusText(tool, url, path);
                statusElement.className = 'loading';
            }

            iframe.style.display = 'block';
            markdownContent.style.display = 'none';

            // 清空后再加载
            iframe.src = 'about:blank';
            setTimeout(() => {
                let isBlank = true;
                iframe._loadingTimeout = setTimeout(() => {
                    if (isBlank) return;
                    toggleLoadingIndicator(false);
                    if (statusElement) {
                        statusElement.textContent = `加载超时: ${relativePath}`;
                        statusElement.className = 'error';
                    }
                    console.warn('iframe加载超时:', relativePath);
                }, 10000);

                iframe.onload = function () {
                    if (isBlank) return;
                    if (iframe._loadingTimeout) {
                        clearTimeout(iframe._loadingTimeout);
                        iframe._loadingTimeout = null;
                    }
                    toggleLoadingIndicator(false);
                    if (statusElement) {
                        statusElement.textContent = generateStatusText(tool, url, path);
                        statusElement.className = 'success';
                    }
                    console.log('HTML 文件加载成功:', relativePath);
                };

                iframe.onerror = function () {
                    if (iframe._loadingTimeout) {
                        clearTimeout(iframe._loadingTimeout);
                        iframe._loadingTimeout = null;
                    }
                    toggleLoadingIndicator(false);
                    if (statusElement) {
                        statusElement.textContent = `网页加载失败: ${relativePath}`;
                        statusElement.className = 'error';
                    }
                    console.error('HTML 文件加载失败:', relativePath);
                };

                iframe.src = relativePath;
                isBlank = false;
            }, 100);

            console.log('通过 iframe 显示 HTML 文件:', relativePath);
        } else {
            // 显示 Markdown/文本内容
            iframe.style.display = 'none';
            markdownContent.style.display = 'block';

            if (statusElement) {
                statusElement.textContent = generateStatusText(tool, url, path);
                statusElement.className = 'loading';
            }

            loadMarkdownFile(path, tool);
            console.log('显示文件内容:', path);
        }
    }
}

// 加载并显示markdown文件
function loadMarkdownFile(filePath, tool) {
    const markdownContent = document.getElementById('markdown-content');
    const statusElement = document.getElementById('right-container-status');

    // 显示加载状态
    markdownContent.innerHTML = '<div style="text-align: center; padding: 50px;"><i class="fas fa-spinner fa-spin"></i> 正在加载文件...</div>';

    // 更新状态文本
    if (statusElement) {
        statusElement.textContent = generateStatusText(tool, null, filePath);
        statusElement.className = 'loading';
    }

    // 将绝对路径转换为相对路径
    let relativePath = filePath;
    if (filePath.includes('workspace')) {
        // 提取workspace之后的路径部分
        const workspaceIndex = filePath.indexOf('workspace');
        if (workspaceIndex !== -1) {
            relativePath = filePath.substring(workspaceIndex);
        }
    }

    console.log('尝试加载文件:', relativePath);

    // 使用fetch加载文件内容
    fetch(relativePath)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // 更新状态文本
            if (statusElement) {
                const fileName = filePath.split('/').pop() || filePath.split('\\').pop();
                statusElement.textContent = `正在解析文件 ${fileName}`;
                statusElement.className = 'loading';
            }

            return response.text();
        })
        .then(content => {
            // 判断文件类型
            const fileName = filePath.split('/').pop() || filePath.split('\\').pop();
            const fileExtension = fileName.split('.').pop().toLowerCase();

            let processedContent = content;

            // 如果不是md或txt文件，认为是代码文件，用markdown代码块包裹
            // if (fileExtension !== 'md' && fileExtension !== 'txt') {
            //     processedContent = `\`\`\`${fileExtension}\n${content}\n\`\`\``;
            // }

            // 使用marked库渲染markdown
            const htmlContent = marked.parse(processedContent);
            markdownContent.innerHTML = htmlContent;

            // 更新状态文本
            if (statusElement) {
                statusElement.textContent = generateStatusText(tool, null, filePath);
                statusElement.className = 'success';
            }
        })
        .catch(error => {
            console.error('加载文件失败:', error);
            markdownContent.innerHTML = `
                <div style="text-align: center; padding: 50px; color: #f44336;">
                    <i class="fas fa-exclamation-triangle"></i>
                    <h3>文件加载失败</h3>
                    <p>无法加载文件: ${filePath}</p>
                    <p>错误信息: ${error.message}</p>
                </div>
            `;

            // 更新状态文本
            if (statusElement) {
                const fileName = filePath.split('/').pop() || filePath.split('\\').pop();
                statusElement.textContent = `文件 ${fileName} 加载失败`;
                statusElement.className = 'error';
            }
        });
}

// 切换右侧容器显示/隐藏
function toggleRightContainer() {
    const rightContainer = document.getElementById('right-container');
    if (rightContainer) {
        rightContainer.classList.toggle('show');

        const isShow = rightContainer.classList.contains('show');
        const timeout = isShow ? 0 : 350;

        setTimeout(() => {
            // 切换所有按钮的紧凑模式
            toggleButtonsCompactMode(isShow);
            setTimeout(() => {
                handleResize();

                // 检查并重新定位步骤信息弹窗
                const stepsTooltip = document.getElementById('steps-tooltip');
                if (stepsTooltip && stepsTooltip.classList.contains('show')) {
                    // 如果步骤信息弹窗正在显示，重新计算其位置
                    showStepsTooltip();
                }
            }, 500);
        }, timeout);
    }
}

function toggleMaximizePanel() {
    const leftContainer = document.querySelector('.left-container');
    const rightContainer = document.getElementById('right-container');
    const toggleIcon = document.querySelector('#toggle-maximize-btn i');

    // 使用 requestAnimationFrame 优化DOM操作
    requestAnimationFrame(() => {
        leftContainer.classList.toggle('hidden');
        rightContainer.classList.toggle('maximized');

        if (toggleIcon.classList.contains('fa-expand-alt')) {
            toggleIcon.classList.remove('fa-expand-alt');
            toggleIcon.classList.add('fa-compress-alt');

            // 批量处理面板隐藏，减少重排
            requestAnimationFrame(() => {
                nodeToolPanels.forEach(panel => {
                    panel.classList.add('tucked-left');
                });
            });
        } else {
            toggleIcon.classList.remove('fa-compress-alt');
            toggleIcon.classList.add('fa-expand-alt');

            // 批量处理面板显示，减少重排
            requestAnimationFrame(() => {
                nodeToolPanels.forEach(panel => {
                    panel.classList.remove('tucked-left');
                });
            });
        }
    });
}

// 切换按钮的紧凑模式
function toggleButtonsCompactMode(isCompact) {
    const buttons = document.querySelectorAll('.controls .btn');
    buttons.forEach(button => {
        if (isCompact) {
            button.classList.add('compact');
        } else {
            button.classList.remove('compact');
        }
    });
}

// 步骤列表tooltip相关变量
let stepsTooltipTimeout;

// 显示步骤列表tooltip
function showStepsTooltip(event) {
    // 清除之前的隐藏定时器
    if (stepsTooltipTimeout) {
        clearTimeout(stepsTooltipTimeout);
        stepsTooltipTimeout = null;
    }

    const stepsTooltip = document.getElementById('steps-tooltip');
    if (!stepsTooltip) return;

    let finalX, finalY;
    const tooltipWidth = 400;
    const tooltipHeight = 300;

    if (event) {
        // 有event参数时，使用鼠标位置
        const x = event.pageX + 10;
        const y = event.pageY - 10;

        finalX = x;
        finalY = y;

        // 如果tooltip会超出右边界，则显示在鼠标左侧
        if (x + tooltipWidth > window.innerWidth) {
            finalX = event.pageX - tooltipWidth - 10;
        }

        // 如果tooltip会超出下边界，则显示在鼠标上方
        if (y + tooltipHeight > window.innerHeight) {
            finalY = event.pageY - tooltipHeight - 10;
        }
    } else {
        // 没有event参数时，使用动态标题元素位置
        const dynamicTitle = document.getElementById('dynamic-title');
        if (!dynamicTitle) return;

        const titleRect = dynamicTitle.getBoundingClientRect();
        const scrollX = window.pageXOffset || document.documentElement.scrollLeft;
        const scrollY = window.pageYOffset || document.documentElement.scrollTop;

        // 计算动态标题的绝对位置
        const titleX = titleRect.left + scrollX;
        const titleY = titleRect.top + scrollY;
        const titleWidth = titleRect.width;
        const titleHeight = titleRect.height;

        // 将tooltip显示在动态标题的右侧
        finalX = titleX + titleWidth + 10;
        finalY = titleY + (titleHeight - tooltipHeight) / 2; // 垂直居中对齐

        // 如果tooltip会超出右边界，则显示在动态标题左侧
        if (finalX + tooltipWidth > window.innerWidth + scrollX) {
            finalX = titleX - tooltipWidth - 10;
        }

        // 如果tooltip会超出上边界，则调整到顶部对齐
        if (finalY < scrollY) {
            finalY = titleY;
        }

        // 如果tooltip会超出下边界，则调整到底部对齐
        if (finalY + tooltipHeight > window.innerHeight + scrollY) {
            finalY = titleY + titleHeight - tooltipHeight;
        }
    }

    // 生成步骤列表HTML
    const stepsHtml = generateStepsListHtml();

    stepsTooltip.style.left = finalX + "px";
    stepsTooltip.style.top = finalY + "px";
    stepsTooltip.innerHTML = stepsHtml;
    stepsTooltip.classList.add('show');
}

// 隐藏步骤列表tooltip
function hideStepsTooltip() {
    // 添加延迟隐藏，避免鼠标快速移动时闪烁
    stepsTooltipTimeout = setTimeout(() => {
        const stepsTooltip = document.getElementById('steps-tooltip');
        if (stepsTooltip) {
            stepsTooltip.classList.remove('show');
        }
    }, 100);
}

// 生成步骤列表HTML
function generateStepsListHtml() {
    const steps = dagData.nodes;
    let html = '<h4>任务步骤列表</h4>';

    steps.forEach(step => {
        const statusClass = step.status || 'not_started';
        const statusText = getStatusText(step.status);

        html += `
            <div class="step-item">
                <div class="step-status ${statusClass}"></div>
                <div class="step-text">${step.name} - ${(step.fullName || step.title || '')}</div>
            </div>
        `;
    });

    return html;
}

// 获取状态文本
function getStatusText(status) {
    const statusMap = {
        'completed': '已完成',
        'in_progress': '进行中',
        'blocked': '阻塞',
        'not_started': '未开始'
    };
    return statusMap[status] || '未知';
}

// 新会话重置：清空工具调用与面板缓存，并清理本地存储
function resetSessionCaches() {
    try {
        // 停止所有进行中的工具调用（标记为失败并移入历史，避免悬挂状态）
        if (activeToolCalls && activeToolCalls.size > 0) {
            const ids = Array.from(activeToolCalls.keys());
            ids.forEach(id => {
                try {
                    completeToolCall(id, '会话已重置，调用中止', false);
                } catch (_) { }
            });
        }

        // 清空历史与计数器
        toolCallHistory = [];
        if (activeToolCalls && activeToolCalls.clear) activeToolCalls.clear();
        toolCallCounter = 0;

        // 关闭并清空所有节点工具面板
        if (nodeToolPanels && nodeToolPanels.size > 0) {
            const panelIds = Array.from(nodeToolPanels.keys());
            panelIds.forEach(nodeId => {
                try {closeNodeToolPanel(nodeId);} catch (_) { }
            });
            if (nodeToolPanels.clear) nodeToolPanels.clear();
        }
        // 清理MessageService的tool events
        if (window.messageService && typeof window.messageService.clearStepToolEvents === 'function') {
            window.messageService.clearStepToolEvents();
        }
        // 右侧内容与资源清理
        try {cleanupAllResources();} catch (_) { }

        // 清理本地存储中的上一会话记录，避免回退读取旧数据
        try {
            localStorage.removeItem('cosight:lastManusStep');
            localStorage.removeItem('cosight:stepToolEvents');
            localStorage.removeItem('cosight:planIdByTopic');
            localStorage.removeItem('cosight:pendingRequests');
        } catch (_) { }

        // 标记全局面板容器为空
        const container = document.getElementById('tool-call-panels-container');
        if (container) {
            container.innerHTML = '';
        }

        console.log('[session] 缓存已重置');
    } catch (e) {
        console.warn('重置会话缓存时发生异常:', e);
    }
}

// F5刷新时的清理（页面加载场景）- 只清理UI状态，保留localStorage数据
function resetUICaches() {
    try {
        // 停止所有进行中的工具调用（标记为失败并移入历史，避免悬挂状态）
        if (activeToolCalls && activeToolCalls.size > 0) {
            const ids = Array.from(activeToolCalls.keys());
            ids.forEach(id => {
                try {
                    completeToolCall(id, '页面刷新，调用中止', false);
                } catch (_) {}
            });
        }

        // 清空历史与计数器
        toolCallHistory = [];
        if (activeToolCalls && activeToolCalls.clear) activeToolCalls.clear();
        toolCallCounter = 0;

        // 关闭并清空所有节点工具面板
        if (nodeToolPanels && nodeToolPanels.size > 0) {
            const panelIds = Array.from(nodeToolPanels.keys());
            panelIds.forEach(nodeId => {
                try { closeNodeToolPanel(nodeId); } catch (_) {}
            });
            if (nodeToolPanels.clear) nodeToolPanels.clear();
        }

        // 清理MessageService的tool events
        if (window.messageService && typeof window.messageService.clearStepToolEvents === 'function') {
            window.messageService.clearStepToolEvents();
        }

        // 右侧内容与资源清理
        try { cleanupAllResources(); } catch (_) {}

        // 标记全局面板容器为空
        const container = document.getElementById('tool-call-panels-container');
        if (container) {
            container.innerHTML = '';
        }

        console.log('[UI] 缓存已重置（保留localStorage数据）');
    } catch (e) {
        console.warn('重置UI缓存时发生异常:', e);
    }
}

// 暴露到全局，便于其他模块触发
if (typeof window !== 'undefined') {
    window.resetSessionCaches = resetSessionCaches;
    window.resetUICaches = resetUICaches;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        initInputHandler,
        closeAllVerificationTooltips,
        hideVerificationTooltip,
        showStepsTooltip,
        hideStepsTooltip,
        toggleRightContainer,
        toggleMaximizePanel,
        // 导出会话重置能力
        resetSessionCaches
    };
}