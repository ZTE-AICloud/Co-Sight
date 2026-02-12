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
    // 确保tooltip已初始化
    if (typeof ensureTooltipInitialized === 'function') {
        ensureTooltipInitialized();
    }
    
    // 清除之前的隐藏定时器
    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }

    // 计算工具提示位置，避免超出屏幕
    const x = event.pageX + 10;
    const y = event.pageY - 10;
    const tooltipWidth = 450;
    // 如果有step_notes，需要更大的高度空间
    const hasStepNotes = d.step_notes && d.step_notes.trim();
    const tooltipHeight = hasStepNotes ? 400 : 150;

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
    
    // 构建step_notes显示内容
    let stepNotesHtml = '';
    if (hasStepNotes) {
        // 处理step_notes中的文件路径，转换为可点击的链接
        let notesContent = d.step_notes;
        
        // 检测并转换文件路径为可点击链接
        // 匹配 /api/nae-deep-research/v1/work_space/ 或 work_space/ 开头的路径
        const pathRegex = /(\/api\/nae-deep-research\/v1\/work_space\/[^\s\n]+|work_space\/[^\s\n]+)/g;
        notesContent = notesContent.replace(pathRegex, (match) => {
            // 提取文件名
            const fileName = match.split('/').pop();
            const fullPath = match.startsWith('/api/') ? match : `/api/nae-deep-research/v1/${match}`;
            return `<a href="#" onclick="openFileInRightPanel('${fullPath}'); event.preventDefault(); event.stopPropagation(); return false;" style="color: #4CAF50; text-decoration: underline; cursor: pointer;" title="点击查看文件">${fileName}</a>`;
        });
        
        stepNotesHtml = `<div style="margin-top: 8px; padding: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; max-height: 200px; overflow-y: auto;">
            <strong style="font-size: 12px;">${(window.I18nService ? window.I18nService.t('step_notes') : '步骤说明')}:</strong><br/>
            <span style="font-size: 11px; line-height: 1.5; white-space: pre-wrap;">${notesContent}</span>
           </div>`;
    }
    const stepNotes = stepNotesHtml;
    
    const status = showStatus ? `<em>${(window.I18nService ? window.I18nService.t('status') : '状态')}: ${getStatusText(d.status)}</em><br/>` : '';
    
    // 确保tooltip已初始化再使用
    if (!tooltip) {
        console.warn('Tooltip未初始化');
        return;
    }
    
    tooltip
        .style("opacity", 0)
        .style("left", finalX + "px")
        .style("top", finalY + "px")
        .html(`
            <strong>${d.name} - ${(d.fullName || d.title || '')}</strong><br/>
            <hr>
            ${status}
            ${stepNotes}
        `)
        .transition()
        .duration(200)
        .style("opacity", 1);
}

// 隐藏工具提示
function hideTooltip() {
    // 确保tooltip已初始化
    if (typeof ensureTooltipInitialized === 'function') {
        ensureTooltipInitialized();
    }
    
    // 添加延迟隐藏，避免鼠标快速移动时闪烁
    tooltipTimeout = setTimeout(() => {
        if (tooltip) {
            tooltip
                .transition()
                .duration(200)
                .style("opacity", 0);
        }
    }, 100);
}

// 初始化 tooltip 的智能鼠标悬停行为：
// 1. 默认 pointer-events: none，不挡住节点
// 2. 鼠标靠近时（距离 < 30px），启用 pointer-events: auto，可以进入 tooltip 并滚动
// 3. 鼠标真正进入 tooltip 后，保持显示并可滚动
// 4. 鼠标离开 tooltip 时，恢复 pointer-events: none 并隐藏
(function initTooltipBehavior() {
    try {
        const tooltipEl = document.getElementById('tooltip');
        if (!tooltipEl) return;

        let isMouseNearTooltip = false;
        let isMouseInTooltip = false;

        // 全局监听鼠标移动，检测是否靠近 tooltip
        document.addEventListener('mousemove', function(e) {
            const style = window.getComputedStyle(tooltipEl);
            if (style.opacity === '0' || style.visibility === 'hidden') {
                return;
            }

            const rect = tooltipEl.getBoundingClientRect();
            const x = e.clientX;
            const y = e.clientY;

            // 计算鼠标到 tooltip 的距离
            const distance = getDistanceToRect(x, y, rect);

            // 如果距离 < 30px，启用 pointer-events
            if (distance < 30) {
                if (!isMouseNearTooltip) {
                    isMouseNearTooltip = true;
                    tooltipEl.classList.add('hover-active');
                }
            } else {
                if (isMouseNearTooltip && !isMouseInTooltip) {
                    isMouseNearTooltip = false;
                    tooltipEl.classList.remove('hover-active');
                }
            }
        });

        // 鼠标进入 tooltip 时，清除隐藏定时器，保持显示
        tooltipEl.addEventListener('mouseenter', function() {
            isMouseInTooltip = true;
            if (typeof tooltipTimeout !== 'undefined' && tooltipTimeout) {
                clearTimeout(tooltipTimeout);
                tooltipTimeout = null;
            }
            tooltipEl.classList.add('hover-active');
        });

        // 鼠标离开 tooltip 时，延迟隐藏并恢复穿透
        tooltipEl.addEventListener('mouseleave', function() {
            isMouseInTooltip = false;
            isMouseNearTooltip = false;
            tooltipEl.classList.remove('hover-active');
            if (typeof hideTooltip === 'function') {
                hideTooltip();
            }
        });

        console.log('Tooltip 智能悬停行为已初始化');
    } catch (err) {
        console.warn('初始化 tooltip 行为失败:', err);
    }

    // 计算点到矩形的最短距离
    function getDistanceToRect(x, y, rect) {
        const dx = Math.max(rect.left - x, 0, x - rect.right);
        const dy = Math.max(rect.top - y, 0, y - rect.bottom);
        return Math.sqrt(dx * dx + dy * dy);
    }
})();

// 获取状态文本
function getStatusText(status) {
    return statusTexts[status] || (window.I18nService ? window.I18nService.t('unknown') : '未知');
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
                if (['search_baidu', 'search_google', 'tavily_search', 'image_search'].includes(toolName)) {
                    if (toolResult && toolResult.first_url) {
                        url = toolResult.first_url;
                    }
                }

                // 处理文件保存工具，提取路径
                if (toolName === 'file_saver') {
                    try {
                        // 优先使用 processed_result.file_path（已包含完整API路径）
                        const processed = toolEvent.tool_result;
                        let filePath = null;
                        
                        if (processed && processed.file_path) {
                            // processed_result.file_path 已经包含完整的 API 路径前缀
                            filePath = processed.file_path;
                        } else {
                            // 回退到从 tool_args 中提取
                            const args = JSON.parse(toolEvent.tool_args || '{}');
                            if (args.file_path) {
                                filePath = buildApiWorkspacePath(args.file_path);
                            }
                        }
                        
                        if (filePath) {
                            path = filePath;
                            const filename = extractFileName(filePath);
                            if (filename) {
                                descriptionOverride = (window.I18nService ? `${window.I18nService.t('info_saved_to')}${filename}` : `信息保存到:${filename}`);
                            }
                        }
                    } catch (e) {
                        console.warn('解析文件保存工具参数失败:', e);
                    }
                }

                // 处理文件读取工具，提取路径
                if (toolName === 'file_read') {
                    try {
                        // 优先 processed_result.file_path
                        const processed = toolEvent.tool_result;
                        let filePath = processed && processed.file_path ? processed.file_path : null;
                        if (!filePath) {
                            const args = JSON.parse(toolEvent.tool_args || '{}');
                            filePath = args.file || args.path || null;
                        }
                        if (filePath) {
                            path = buildApiWorkspacePath(filePath);
                        }
                    } catch (e) {
                        console.warn('解析文件读取工具参数失败:', e);
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
                    description: descriptionOverride || ((window.I18nService ? `${window.I18nService.t('execute_tool')}${getToolDisplayName(toolName)}` : `执行工具: ${getToolDisplayName(toolName)}`)),
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
        if (['search_baidu', 'search_google', 'tavily_search', 'image_search', 'search_wiki'].includes(toolName)) {
            try {
                // 优先 processed_result.first_url 风格（上游已解析对象）
                if (toolResult && toolResult.first_url) {
                    url = toolResult.first_url;
                } else {
                    // 特殊处理 tavily_search 和 image_search 的字符串结果
                    if (toolName === 'tavily_search' || toolName === 'image_search') {
                        url = extractUrlFromSearchResult(toolResult, toolName);
                    } else {
                        const resultArray = parseSearchResults(toolResult);
                        if (Array.isArray(resultArray) && resultArray.length > 0) {
                            const withUrl = resultArray.find(it => it && it.url) || resultArray[0];
                            url = withUrl && withUrl.url ? withUrl.url : null;
                        }
                    }
                }
            } catch (e) {
                console.warn('解析搜索工具结果失败:', e);
            }
        }

        // 处理文件保存工具，提取路径
        if (toolName === 'file_saver') {
            try {
                // 优先使用 processed_result.file_path（已包含完整API路径）
                const processed = toolCall.tool_result;
                let filePath = null;
                
                if (processed && processed.file_path) {
                    // processed_result.file_path 已经包含完整的 API 路径前缀
                    filePath = processed.file_path;
                } else {
                    // 回退到从 tool_args 中提取
                    const args = JSON.parse(toolCall.tool_args || '{}');
                    if (args.file_path) {
                        filePath = buildApiWorkspacePath(args.file_path);
                    }
                }
                
                if (filePath) {
                    path = filePath;
                    const filename = extractFileName(filePath);
                    if (filename) {
                        descriptionOverride = (window.I18nService ? `${window.I18nService.t('info_saved_to')}${filename}` : `信息保存到:${filename}`);
                    }
                }
            } catch (e) {
                console.warn('解析文件保存工具参数失败:', e);
            }
        }

        // 处理文件读取工具，提取路径
        if (toolName === 'file_read') {
            try {
                // 优先 processed_result.file_path
                let filePath = null;
                if (typeof toolResult === 'object' && toolResult && toolResult.file_path) {
                    filePath = toolResult.file_path;
                } else {
                    const args = JSON.parse(toolCall.tool_args || '{}');
                    filePath = args.file || args.path || null;
                }
                if (filePath) {
                    path = buildApiWorkspacePath(filePath);
                }
            } catch (e) {
                console.warn('解析文件读取工具参数失败:', e);
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
            description: descriptionOverride || ((window.I18nService ? `${window.I18nService.t('execute_tool')}${getToolDisplayName(toolName)}` : `执行工具: ${getToolDisplayName(toolName)}`)),
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
    const toolKeys = {
        'search_baidu': 'baidu_search',
        'search_google': 'google_search',
        'image_search': 'image_search',
        'file_saver': 'file_save',
        'file_read': 'file_read',
        'execute_code': 'code_executor',
        'data_analyzer': 'data_analyzer',
        'predictor': 'predictor',
        'report_generator': 'report_generator',
        'create_plan': 'create_plan',
        'fetch_website_content': 'fetch_website_content',
        'fetch_website_content_with_images': 'fetch_website_content_with_images',
        'fetch_website_images_only': 'fetch_website_images_only',
        'tavily_search': 'tavily_search',
        'search_wiki': 'wiki_search'
    };
    const key = toolKeys[toolName];
    if (key && window.I18nService) {
        const translated = window.I18nService.t(key);
        if (translated && translated !== key) return translated;
    }
    // 回退：原中文映射
    const toolNames = {
        'search_baidu': '百度搜索',
        'search_google': '谷歌搜索',
        'image_search': '图片搜索',
        'file_saver': '文件保存',
        'file_read': '文件读取',
        'execute_code': '代码执行器',
        'data_analyzer': '数据分析',
        'predictor': '预测模型',
        'report_generator': '报告生成',
        'create_plan': '创建计划',
        'fetch_website_content': '获取网页内容',
        'fetch_website_content_with_images': '网页内容爬取（含图片）',
        'fetch_website_images_only': '网页图片提取',
        'tavily_search': 'Tavily搜索',
        'search_wiki': '维基百科搜索'
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
    } catch (_) {}
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
     if (!originalPath || typeof originalPath !== 'string') return originalPath;

    // 若已是完整URL或已是API路径，直接返回
    if (/^https?:\/\//i.test(originalPath)) return originalPath;
    if (originalPath.startsWith('/api/')) return originalPath;

    // 统一分隔符
    const p = originalPath.replace(/\\/g, '/');

    // work_space: 支持 "work_space/xxx" 或 "/.../work_space/xxx"
    if (p.startsWith('work_space/')) {
        return `/api/nae-deep-research/v1/${p}`;
    }
    const wsIdx = p.indexOf('/work_space/');
    if (wsIdx !== -1) {
        const rel = p.substring(wsIdx + 1); // "work_space/..."
        return `/api/nae-deep-research/v1/${rel}`;
    }

    // skills: 支持 "skills/xxx" 或 "/.../skills/xxx"
    if (p.startsWith('skills/')) {
        return `/api/nae-deep-research/v1/${p}`;
    }
    const skillsIdx = p.indexOf('/skills/');
    if (skillsIdx !== -1) {
        const rel = p.substring(skillsIdx + 1); // "skills/..."
        return `/api/nae-deep-research/v1/${rel}`;
    }

    // 其它情况保持原样，避免影响既有逻辑
    return originalPath;
}

// ==================== Skills Modal（只读展示） ====================
let _skillsLoadedOnce = false;

function openSkillsModal() {
    const modal = document.getElementById('skills-modal');
    if (!modal) return;
    modal.style.display = 'block';
    // 先 display 再下一帧加 class，确保过渡动画生效
    requestAnimationFrame(() => {
        modal.classList.add('is-open');
    });

    // 首次打开时加载一次
    if (!_skillsLoadedOnce) {
        _skillsLoadedOnce = true;
        loadAgentTeam();
    }
}

function closeSkillsModal() {
    const modal = document.getElementById('skills-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    // 等动画结束再隐藏，避免突兀（用 transitionend 更稳）
    const content = modal.querySelector('.skills-modal-content');
    if (!content) {
        modal.style.display = 'none';
        return;
    }
    const onEnd = (e) => {
        if (e && e.target !== content) return;
        content.removeEventListener('transitionend', onEnd);
        // 只有在关闭状态才隐藏
        if (!modal.classList.contains('is-open')) {
            modal.style.display = 'none';
        }
    };
    content.addEventListener('transitionend', onEnd);
    // 兜底：如果浏览器不触发 transitionend
    setTimeout(() => onEnd({ target: content }), 500);
}

async function fetchSkillsCatalog() {
    const resp = await fetch('/api/nae-deep-research/v1/deep-research/skills', {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
    });
    if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
    }
    const json = await resp.json();
    const data = json && json.data ? json.data : {};
    const skills = Array.isArray(data.skills) ? data.skills : [];
    // 统一为 {name, description}
    return skills.map(s => ({
        name: (s && s.name) ? String(s.name) : '',
        description: (s && s.description) ? String(s.description) : '',
    })).filter(s => !!s.name);
}

function buildSkillsMap(skillsCatalog) {
    const map = new Map();
    (Array.isArray(skillsCatalog) ? skillsCatalog : []).forEach(s => {
        if (!s || !s.name) return;
        map.set(String(s.name), {
            name: String(s.name),
            description: s.description ? String(s.description) : '',
        });
    });
    return map;
}

async function fetchAgents() {
    const resp = await fetch('/api/nae-deep-research/v1/deep-research/agents', {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
    });
    if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
    }
    const json = await resp.json();
    const data = json && json.data ? json.data : {};
    return Array.isArray(data.agents) ? data.agents : [];
}

async function loadAgentTeam() {
    const statusEl = document.getElementById('skills-modal-status');
    const listEl = document.getElementById('skills-list');
    if (!statusEl || !listEl) return;

    statusEl.textContent = '加载中...';
    listEl.innerHTML = '';

    try {
        const [skillsCatalog, agents] = await Promise.all([fetchSkillsCatalog(), fetchAgents()]);
        const skillMap = buildSkillsMap(skillsCatalog);

        if (!agents || agents.length === 0) {
            statusEl.textContent = '共 0 个 Agent';
            listEl.innerHTML = '<div class="skills-modal-status">未发现 Agent（请确认 actor 目录下存在 agent_card.json）</div>';
            return;
        }

        function getSkillName(sn) {
            if (sn == null) return '';
            if (typeof sn === 'string') return String(sn).trim();
            if (typeof sn === 'object' && sn !== null) {
                return String(sn.skill_name || sn.name || sn.skill_id || '').trim();
            }
            return '';
        }

        const processedAgents = agents.map(a => {
            const aid = (a && a.agent_id) ? String(a.agent_id) : '';
            const normalizedSkills = (Array.isArray(a.skills) ? a.skills : []).map(sn => getSkillName(sn)).filter(Boolean);
            return { ...a, skills: normalizedSkills };
        });

        const agentOrder = ['task_actor', 'task_act_actor', 'openclaw'];
        const sortedAgents = [...processedAgents].sort((a, b) => {
            const ai = agentOrder.indexOf((a && a.agent_id) ? String(a.agent_id) : '');
            const bi = agentOrder.indexOf((b && b.agent_id) ? String(b.agent_id) : '');
            if (ai >= 0 && bi >= 0) return ai - bi;
            if (ai >= 0) return -1;
            if (bi >= 0) return 1;
            return 0;
        });

        const agentAvatarMap = {
            'task_actor': '/cosight/images/report-document-file-svgrepo-com.svg',
            'task_act_actor': '/cosight/images/report-document-file-svgrepo-com.svg',
            'openclaw': '/cosight/images/openclaw.svg'
        };
        let matchedCount = 0;
        listEl.innerHTML = sortedAgents.map(a => {
            const agentId = (a && a.agent_id) ? String(a.agent_id) : '';
            const aid = (a && a.agent_name) ? String(a.agent_name) : agentId;
            const adesc = a && a.agent_description ? String(a.agent_description) : '';
            const askills = Array.isArray(a && a.skills) ? a.skills : [];
            const avatarSrc = agentAvatarMap[agentId];
            const avatarHtml = avatarSrc
                ? `<img class="agent-item-avatar" src="${escapeHtml(avatarSrc)}" alt="">`
                : '';

            const skillsHtml = askills.map(sn => {
                const key = getSkillName(sn);
                const meta = skillMap.get(key);
                if (meta) {
                    matchedCount += 1;
                    return `
                        <details class="skill-item skill-collapse">
                            <summary class="skill-item-header">
                                <span class="skill-item-label">技能</span>
                                <span class="skill-item-name">${escapeHtml(meta.name)}</span>
                                <span class="collapse-icon" aria-hidden="true"></span>
                            </summary>
                            <div class="skill-item-desc">${escapeHtml(meta.description)}</div>
                        </details>
                    `;
                }
                return `
                    <details class="skill-item skill-item-missing skill-collapse">
                        <summary class="skill-item-header">
                            <span class="skill-item-label">技能</span>
                            <span class="skill-item-name">${escapeHtml(key)}</span>
                            <span class="collapse-icon" aria-hidden="true"></span>
                        </summary>
                        <div class="skill-item-desc">未找到对应技能（请确认 skills 目录/名称是否存在）</div>
                    </details>
                `;
            }).join('');

            return `
                <details class="agent-item agent-collapse">
                    <summary class="agent-item-header">
                        ${avatarHtml}
                        <span class="agent-item-name">${escapeHtml(aid)}</span>
                        <span class="collapse-icon" aria-hidden="true"></span>
                    </summary>
                    <div class="agent-item-body">
                        ${adesc ? `<div class="agent-item-desc">${escapeHtml(adesc)}</div>` : ''}
                        <div class="agent-item-skills">
                            ${skillsHtml || '<div class="skills-modal-status">该智能体未配置技能</div>'}
                        </div>
                    </div>
                </details>
            `;
        }).join('');

        statusEl.textContent = `共 ${sortedAgents.length} 个 Agent，已匹配 ${matchedCount} 个技能`;
    } catch (e) {
        console.warn('加载 Agent Team 失败:', e);
        statusEl.textContent = '加载失败';
        listEl.innerHTML = `<div class="skills-modal-status">无法加载 Agent Team：${escapeHtml(String(e))}</div>`;
    }
}

async function importSkillZip(file) {
    const statusEl = document.getElementById('skills-modal-status');
    if (statusEl) {
        statusEl.textContent = '正在导入...';
        statusEl.className = 'skills-modal-status';
    }

    const fd = new FormData();
    fd.append('file', file);

    const resp = await fetch('/api/nae-deep-research/v1/deep-research/skills/import', {
        method: 'POST',
        body: fd
    });
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok || !json || json.code !== 0) {
        const msg = (json && (json.msg || json.message)) ? (json.msg || json.message) : `导入失败 (HTTP ${resp.status})`;
        throw new Error(msg);
    }
    return json;
}

function initSkillsImportUI() {
    const btn = document.getElementById('skills-import-btn');
    const input = document.getElementById('skills-import-file');
    if (!btn || !input) return;

    btn.addEventListener('click', () => input.click());
    input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        // reset input so selecting same file triggers change again
        input.value = '';
        if (!file) return;

        const name = (file.name || '').toLowerCase();
        if (!name.endsWith('.zip')) {
            alert('只支持 .zip 格式的压缩包');
            return;
        }

        try {
            await importSkillZip(file);
            await loadAgentTeam();
            alert('导入成功');
        } catch (e) {
            alert(`导入失败：${e && e.message ? e.message : String(e)}`);
        }
    });
}

// DOM就绪后初始化导入入口
document.addEventListener('DOMContentLoaded', () => {
    initSkillsImportUI();
});

// 将 Skills 弹窗函数显式挂到 window，确保 inline onclick 可用
try {
    window.openSkillsModal = openSkillsModal;
    window.closeSkillsModal = closeSkillsModal;
} catch (e) {
    // ignore
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
    } catch (e) {}

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

    // ====== 在添加到 DOM 之前就强制设置位置 ======
    panel.style.position = 'absolute';
    panel.style.top = '50px';
    panel.style.left = '16px';
    console.log(`[创建面板 ${nodeId}] 初始位置设置: top=50px, left=16px`);
    
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
        } catch (_) {}
        if (closeBtn) {
            // 强制按钮位于顶层并可命中
            try {
                closeBtn.style.position = 'absolute';
                closeBtn.style.top = '8px';
                closeBtn.style.right = '8px';
                closeBtn.style.zIndex = '10';
                closeBtn.style.pointerEvents = 'auto';
            } catch (_) {}

            // 阻止事件冒泡，避免触发header的拖拽mousedown
            closeBtn.addEventListener('mousedown', function(e) { 
                console.log(`[panel:${nodeId}] close button mousedown`);
                e.stopPropagation();
            });
            closeBtn.addEventListener('click', function(e) {
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

    // ====== 再次强制设置位置，确保生效 ======
    panel.style.top = '50px';
    panel.style.left = '16px';
    
    // 添加调试信息
    console.log(`Creating panel for node ${nodeId}`);
    console.log(`[面板创建后] panel.style.top = ${panel.style.top}`);
    debugPanelPosition(nodeId);

    // 注释掉 updatePanelPosition，避免覆盖我们的固定位置
    // updatePanelPosition(panel, nodeId);

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

    const sticky = panel.getAttribute("data-sticky");
    // 固定贴在屏幕左侧显示
    panel.style.left = sticky == "true" ? `${finalLeft}px` : `16px`;
    
    // ============== 关键修改：强制工具栏往下移 ==============
    // 不再调用 calculateOptimalPanelTop，直接设置一个固定的、远离顶部的位置
    const FORCED_TOP_OFFSET = 50;  // 强制距离页面顶部 50px
    
    // 直接设置为固定值，不再依赖任何计算
    panel.style.top = `${FORCED_TOP_OFFSET}px`;
    
    console.log(`[Panel ${nodeId}] 强制设置位置: top=${FORCED_TOP_OFFSET}px`);
}

// 计算面板的最优垂直位置
function calculateOptimalPanelTop(panel, nodeRect) {
    const topMargin = 100;  // 顶部留出更多空间，避免工具栏贴顶（从 20 调整为 100）
    const bottomMargin = 20;
    const panelHeight = panel.offsetHeight;
    const baseOffset = 80; // 整体向下偏移

    // 直接使用相对于视口的位置（与test-panel.html保持一致）
    const idealTop = nodeRect.top + nodeRect.height / 2 - panelHeight / 2;
    const idealBottom = idealTop + panelHeight;

    let finalTop = idealTop;

    // 关键判断：面板是否会超出屏幕底部
    const willExceedBottom = idealBottom > window.innerHeight - bottomMargin;
    if (willExceedBottom) {
        // 向上扩展：将面板底部对齐到屏幕底部
        finalTop = window.innerHeight - panelHeight - bottomMargin;

        // 如果向上扩展后顶部空间不足，则居中显示
        if (finalTop < topMargin) {
            finalTop = Math.max(topMargin, (window.innerHeight - panelHeight) / 2);
        }
    } else if (idealTop < topMargin) {
        // 如果面板会超出屏幕顶部, 向下扩展：将面板顶部至少从 topMargin 开始
        finalTop = topMargin;
    } else {
        // 如果面板完全在屏幕内，保持理想位置
        finalTop = idealTop;
    }

    // 应用整体下移偏移量，并再次夹取边界（确保不会低于 topMargin）
    finalTop = Math.min(
        Math.max(finalTop + baseOffset, topMargin),
        window.innerHeight - panelHeight - bottomMargin
    );

    return finalTop;
}

// 查找节点DOM元素
function findNodeElement(nodeId) {
    const nodeTexts = document.querySelectorAll('.node-text');
    for (let textElement of nodeTexts) {
        if (textElement.textContent.includes(`Step ${nodeId}`)) {
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
        item.title = (window.I18nService ? window.I18nService.t('click_to_view_details') : '点击查看详情');

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
                } catch (_) {}
                panel = createNodeToolPanel(nodeId, nodeName, true);
                autoOpenedPanels.add(nodeId);
            }
        } catch (_) {}
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
        'tavily_search': 'fas fa-search',
        'image_search': 'fas fa-search',
        'search_wiki': 'fab fa-wikipedia-w',
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
        result: tool.result || (window.I18nService ? window.I18nService.t('tool_execution_complete').replace('{toolName}', tool.toolName) : `工具 ${tool.toolName} 执行完成`),
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
            // 强制设置固定位置，不调用 updatePanelPosition 避免复杂计算
            panel.style.top = '50px';
            panel.style.left = '16px';
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

// 斜杠命令补全：输入 / 后弹出 /openclaw 等，支持 Tab/点击补全
var SLASH_COMMANDS = [
    { cmd: '/openclaw', desc: '使用 OpenClaw 对话' }
];
var slashPopover = null;
var slashPopoverSelectedIndex = 0;
var slashPopoverInput = null;
var slashPopoverPrefix = '';

function getSlashPrefix(el) {
    if (!el || typeof el.value === 'undefined') return null;
    var start = el.selectionStart != null ? el.selectionStart : el.value.length;
    var textBefore = el.value.slice(0, start);
    var match = textBefore.match(/\/(\w*)$/);
    return match ? '/' + match[1] : null;
}

function showSlashPopover(el, prefix) {
    slashPopoverPrefix = prefix || '/';
    var filtered = SLASH_COMMANDS.filter(function (c) {
        return c.cmd.indexOf(slashPopoverPrefix) === 0;
    });
    if (filtered.length === 0) {
        hideSlashPopover();
        return;
    }
    slashPopoverInput = el;
    slashPopoverSelectedIndex = 0;
    if (!slashPopover) {
        slashPopover = document.createElement('div');
        slashPopover.className = 'slash-command-popover';
        slashPopover.setAttribute('role', 'listbox');
        document.body.appendChild(slashPopover);
    }
    slashPopover.innerHTML = '';
    filtered.forEach(function (item, idx) {
        var div = document.createElement('div');
        div.className = 'slash-command-item' + (idx === 0 ? ' selected' : '');
        div.setAttribute('role', 'option');
        div.setAttribute('data-cmd', item.cmd);
        div.innerHTML = '<span class="slash-cmd">' + escapeHtml(item.cmd) + '</span> <span class="slash-desc">' + escapeHtml(item.desc) + '</span>';
        div.addEventListener('click', function () {
            applySlashCommand(slashPopoverInput, item.cmd);
            hideSlashPopover();
        });
        slashPopover.appendChild(div);
    });
    positionSlashPopover(el);
    slashPopover.style.display = 'block';
}

function positionSlashPopover(el) {
    if (!slashPopover || !el) return;
    var rect = el.getBoundingClientRect();
    slashPopover.style.position = 'fixed';
    slashPopover.style.left = rect.left + 'px';
    slashPopover.style.top = (rect.bottom + 4) + 'px';
    slashPopover.style.minWidth = Math.max(rect.width, 200) + 'px';
}

function hideSlashPopover() {
    if (slashPopover) {
        slashPopover.style.display = 'none';
        slashPopoverInput = null;
    }
}

function applySlashCommand(el, cmd) {
    if (!el || !cmd) return;
    var start = el.selectionStart != null ? el.selectionStart : el.value.length;
    var textBefore = el.value.slice(0, start);
    var textAfter = el.value.slice(start);
    var match = textBefore.match(/\/(\w*)$/);
    var from = match ? start - match[0].length : start;
    var newValue = el.value.slice(0, from) + cmd + ' ' + textAfter;
    el.value = newValue;
    el.selectionStart = el.selectionEnd = from + cmd.length + 1;
    el.focus();
}

function getFilteredSlashCommands() {
    if (!slashPopover || !slashPopoverInput) return [];
    var prefix = getSlashPrefix(slashPopoverInput) || '/';
    return SLASH_COMMANDS.filter(function (c) { return c.cmd.indexOf(prefix) === 0; });
}

function onSlashKeydown(el, e) {
    if (!slashPopover || slashPopover.style.display !== 'block' || slashPopoverInput !== el) return;
    var items = slashPopover.querySelectorAll('.slash-command-item');
    if (items.length === 0) return;
    if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault();
        e.stopImmediatePropagation(); // 仅补全到输入框，不触发回车发送
        var cmd = getFilteredSlashCommands()[slashPopoverSelectedIndex];
        if (cmd) {
            applySlashCommand(el, cmd.cmd);
            hideSlashPopover();
        }
        return;
    }
    if (e.key === 'Escape') {
        e.preventDefault();
        hideSlashPopover();
        return;
    }
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        slashPopoverSelectedIndex = (slashPopoverSelectedIndex + 1) % items.length;
        items.forEach(function (item, i) {
            item.classList.toggle('selected', i === slashPopoverSelectedIndex);
        });
        return;
    }
    if (e.key === 'ArrowUp') {
        e.preventDefault();
        slashPopoverSelectedIndex = (slashPopoverSelectedIndex - 1 + items.length) % items.length;
        items.forEach(function (item, i) {
            item.classList.toggle('selected', i === slashPopoverSelectedIndex);
        });
        return;
    }
}

function attachSlashCompletion(inputEl) {
    if (!inputEl) return;
    inputEl.addEventListener('input', function () {
        var prefix = getSlashPrefix(this);
        if (prefix !== null) {
            showSlashPopover(this, prefix);
        } else {
            hideSlashPopover();
        }
    });
    inputEl.addEventListener('keydown', function (e) {
        var prefix = getSlashPrefix(this);
        if (prefix !== null && !slashPopover) showSlashPopover(this, prefix);
        onSlashKeydown(this, e);
    });
    inputEl.addEventListener('blur', function () {
        setTimeout(hideSlashPopover, 150);
    });
}

// 输入框处理函数
function initInputHandler() {
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const replayButton = document.getElementById('replay-button');
    const initialMessageInput = document.getElementById('initial-message-input');
    const initialSendButton = document.getElementById('initial-send-button');

    // 斜杠命令补全：绑定到两个输入框
    attachSlashCompletion(messageInput);
    attachSlashCompletion(initialMessageInput);

    // 初始化输入框处理
    if (messageInput && sendButton) {
        // 发送消息函数（尾部2个以上空格 => 回放）
        function sendMessage() {
            credibilityService.clearCredibilityData();
            const raw = messageInput.value;
            const endsWithMultiSpaces = /\s{2,}$/.test(raw);
            const message = raw.trim();
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
                if (endsWithMultiSpaces && window.messageService && typeof window.messageService.sendReplay === 'function') {
                    window.messageService.sendReplay();
                } else {
                    messageService.sendMessage(message);
                }
                // 清空输入框
                messageInput.value = '';
            }
        }

        // 点击发送按钮
        sendButton.addEventListener('click', sendMessage);

        // 按回车键发送（同样处理尾部空格触发回放）
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

    // 回放按钮功能已禁用
    // 绑定回放按钮
    if (replayButton) {
        // 回放功能已隐藏，注释掉事件监听器
        /*
        replayButton.addEventListener('click', function () {
            try {
                credibilityService.clearCredibilityData();
            } catch (_) {}
            try {
                // 关闭现有面板与清理资源，尽量与发送一致
                if (nodeToolPanels && nodeToolPanels.size > 0) {
                    const panelIds = Array.from(nodeToolPanels.keys());
                    panelIds.forEach(nodeId => { try { closeNodeToolPanel(nodeId); } catch (_) {} });
                    if (nodeToolPanels.clear) nodeToolPanels.clear();
                }
                try { cleanupAllResources(); } catch (_) {}
            } catch (_) {}
            if (window.messageService && typeof window.messageService.sendReplay === 'function') {
                window.messageService.sendReplay();
            }
        });
        */
    }

    // 初始化输入框处理
    if (initialMessageInput && initialSendButton) {
        // 发送初始消息函数
        function sendInitialMessage() {
            credibilityService.clearCredibilityData();
            const raw = initialMessageInput.value;
            const endsWithMultiSpaces = /\s{2,}$/.test(raw);
            const message = raw.trim();
            
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
                    } catch (_) {}
                    try { cleanupAllResources(); } catch (_) {}
                    try { localStorage.removeItem('cosight:lastManusStep'); } catch (_) {}
                }
            } catch (_) {}
            
            console.log('发送初始消息:', message);
            // 隐藏初始输入框并显示主界面
            hideInitialInputAndShowMain(message);
            // 根据末尾空格决定回放还是正常请求
            try { cleanupAllResources(); } catch (_) {}
            if (endsWithMultiSpaces && window.messageService && typeof window.messageService.sendReplay === 'function') {
                window.messageService.sendReplay();
            } else if (window.messageService && typeof window.messageService.sendMessage === 'function' && message) {
                window.messageService.sendMessage(message);
            }
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
            // 仅负责界面切换；消息发送交由调用方控制
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
        const fileName = path ? path.split('/').pop() || path.split('\\').pop() : (window.I18nService ? window.I18nService.t('unknown_file') : '未知文件');
        return (window.I18nService ? window.I18nService.t('reading_file').replace('{fileName}', fileName) : `正在读取文件 ${fileName}`);
    } else if (tool === 'file_saver') {
        const fileName = path ? path.split('/').pop() || path.split('\\').pop() : (window.I18nService ? window.I18nService.t('unknown_file') : '未知文件');
        return (window.I18nService ? window.I18nService.t('saving_file').replace('{fileName}', fileName) : `正在保存文件 ${fileName}`);
    } else if (tool === 'search_baidu' || tool === 'search_google' || tool === 'tavily_search'|| tool === 'image_search') {
        return (window.I18nService ? window.I18nService.t('browsing_url').replace('{url}', url) : `正在浏览 ${url}`);
    } else if (url) {
        return (window.I18nService ? window.I18nService.t('browsing_url').replace('{url}', url) : `正在浏览 ${url}`);
    } else if (path) {
        const fileName = path.split('/').pop() || path.split('\\').pop();
        return (window.I18nService ? window.I18nService.t('processing_file').replace('{fileName}', fileName) : `正在处理文件 ${fileName}`);
    }
    return (window.I18nService ? window.I18nService.t('processing') : '正在处理...');
}

function toggleLoadingIndicator(isShow) {
    const loadingIndicator = document.getElementById('loading-indicator');
    if (loadingIndicator) {
        loadingIndicator.style.display = isShow ? 'flex' : 'none';
    }
}

// 清理iframe和相关资源
function cleanupContentResources() {
    const rightContainer = document.getElementById('right-container');
    const iframe = document.getElementById('content-iframe');
    const markdownContent = document.getElementById('markdown-content');

    if (rightContainer) rightContainer.classList.remove('openclaw-view');
    if (iframe) {
        // 清理事件监听器
        iframe.onload = null;
        iframe.onerror = null;

        // 必须先清 srcdoc，否则后续设置 src 不会生效（HTML5 中 srcdoc 优先于 src）
        iframe.removeAttribute('srcdoc');
        iframe.srcdoc = '';

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
            const result = createDag(lastManusStep);
            if (result) {
                // 显示标题
                const initData = lastManusStep.content || lastManusStep.data?.initData;
                if (initData && initData.title) {
                    updateDynamicTitle(initData.title);
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

/**
 * 点击 DAG 的 step 节点时，在电脑区展示：有 OpenClaw 对话则展示对话，否则展示步骤占位页
 * @param {number} nodeId - DAG 节点 id（1-based，step1=1, step2=2）
 */
function showOpenClawStepInRightPanel(nodeId) {
    window.__rightPanelShowingFile = null;
    // 先打开右侧电脑区，确保点击节点时面板一定有变化
    if (!showRightPanel()) return;
    var rightContainer = document.getElementById('right-container');
    var iframe = document.getElementById('content-iframe');
    var markdownContent = document.getElementById('markdown-content');
    var statusElement = document.getElementById('right-container-status');
    if (rightContainer) rightContainer.classList.add('openclaw-view');
    if (markdownContent) markdownContent.style.display = 'none';
    if (iframe) iframe.style.display = 'block';

    var topic = window.__cosightCurrentTopic;
    var stepIndex = nodeId - 1;
    var list = (topic && window.__openclawStepByTopic && window.__openclawStepByTopic[topic])
        ? (window.__openclawStepByTopic[topic][stepIndex]) : null;

    if (list && list.length > 0) {
        iframe.srcdoc = buildOpenClawChatHtmlFromMetadataList(list);
        if (statusElement) {
            statusElement.textContent = 'OpenClaw 对话 - Step ' + nodeId;
            statusElement.className = 'success';
        }
    } else {
        // 无 OpenClaw 对话时在电脑区显示步骤占位页，保证“有变化”
        var stepTitle = 'Step ' + nodeId;
        try {
            if (typeof dagData !== 'undefined' && dagData.nodes) {
                var node = dagData.nodes.find(function (n) { return n.id === nodeId; });
                if (node) stepTitle = node.fullName || node.title || ('Step ' + nodeId);
            }
        } catch (_) {}
        var esc = function (s) {
            return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };
        iframe.srcdoc = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:sans-serif;padding:24px;color:#555;} .step-title{font-size:1.2em;margin-bottom:12px;}</style></head><body><div class="step-title">' + esc(stepTitle) + '</div><p>该步骤暂无 OpenClaw 对话。</p><p>可查看左侧节点工具面板中的工具调用与结果。</p></body></html>';
        if (statusElement) {
            statusElement.textContent = 'Step ' + nodeId + ' - 步骤详情';
            statusElement.className = '';
        }
    }
}

/**
 * OpenClaw 消息在右侧 content-iframe 中展示
 * 后端格式：type "multi-modal", source "openclaw", changeType replace/append, data.metadata 或 data.initData 纯文本
 * 按 topic 累积 metadata 列表，生成对话式 iframe 页面
 */
function showOpenClawInIframe(messageData) {
    if (window.__rightPanelShowingFile) {
        return;
    }
    const topic = messageData.topic;
    const metadataList = (topic && window.__openclawMessagesByTopic && window.__openclawMessagesByTopic[topic]) || [];
    const payload = messageData.data?.payload;
    const messages = payload && Array.isArray(payload.messages) ? payload.messages : null;
    const initData = messageData.data?.content || messageData.data?.initData;

    if (metadataList.length === 0 && !messages && !initData) {
        console.warn('showOpenClawInIframe: 无 metadata 列表、无 payload.messages、无 initData');
        return;
    }

    if (!showRightPanel()) return;

    const rightContainer = document.getElementById('right-container');
    const iframe = document.getElementById('content-iframe');
    const markdownContent = document.getElementById('markdown-content');
    const statusElement = document.getElementById('right-container-status');

    if (rightContainer) rightContainer.classList.add('openclaw-view');
    if (iframe) iframe.style.display = 'block';
    if (markdownContent) markdownContent.style.display = 'none';
    if (statusElement) {
        statusElement.textContent = 'OpenClaw 对话';
        statusElement.className = 'success';
    }

    if (metadataList.length > 0) {
        if (iframe) iframe.srcdoc = buildOpenClawChatHtmlFromMetadataList(metadataList);
        return;
    }

    if (messages) {
        if (iframe) iframe.srcdoc = buildOpenClawChatHtml(messages);
        return;
    }

    // 仅 initData 纯文本（错误或单条回复）：生成单条助手消息展示
    if (initData && Array.isArray(initData) && initData.length > 0 && initData[0].type === 'text' && initData[0].value) {
        var single = [{ messageType: 'text', role: 'assistant', content: initData[0].value }];
        if (iframe) iframe.srcdoc = buildOpenClawChatHtmlFromMetadataList(single);
    }
}

/**
 * 根据 OpenClaw 流式 metadata 列表生成 iframe 内对话 HTML
 * metadata 来自 backend data.metadata：messageType text|thinking|toolCall|toolResult|completion
 */
function buildOpenClawChatHtmlFromMetadataList(metadataList) {
    var roleLabel = { user: '用户', assistant: '助手', toolResult: '工具结果' };
    var roleClass = { user: 'oc-msg-user', assistant: 'oc-msg-assistant', toolResult: 'oc-msg-tool' };
    var typeLabel = { text: '消息', thinking: '思考', toolCall: '工具调用', toolResult: '工具结果', completion: '完成' };

    var listHtml = (metadataList || []).map(function (meta) {
        var msgType = meta.messageType || 'text';
        if (msgType === 'completion') {
            var total = meta.totalSegments || 0;
            return '<div class="oc-msg oc-msg-completion"><div class="oc-msg-body">共 ' + total + ' 个片段</div></div>';
        }
        var role = meta.role || 'assistant';
        var label = roleLabel[role] || role;
        var typeTag = typeLabel[msgType] || msgType;
        var cls = roleClass[role] || 'oc-msg-assistant';
        var body = '';

        if (msgType === 'text' && meta.content !== undefined) {
            body = '<div class="oc-content-text">' + escapeHtml(String(meta.content)).replace(/\n/g, '<br>') + '</div>';
        } else if (msgType === 'thinking' && meta.content !== undefined) {
            var text = String(meta.content);
            var short = text.length > 400 ? text.slice(0, 400) + '…' : text;
            body = '<details class="oc-content-thinking"><summary>' + escapeHtml(typeTag) + '</summary><pre class="oc-thinking-pre">' + escapeHtml(short) + '</pre></details>';
        } else if (msgType === 'toolCall') {
            var toolName = meta.toolName || 'tool';
            var argsStr = meta.arguments ? JSON.stringify(meta.arguments) : '{}';
            body = '<div class="oc-content-toolcall"><span class="oc-tool-name">' + escapeHtml(toolName) + '</span><pre class="oc-tool-args">' + escapeHtml(argsStr) + '</pre></div>';
        } else if (msgType === 'toolResult') {
            var toolName = meta.toolName || 'tool';
            var resultText = meta.content !== undefined ? String(meta.content) : '';
            if (resultText.length > 600) resultText = resultText.slice(0, 600) + '\n…';
            var errCls = meta.isError ? ' oc-tool-error' : '';
            body = '<div class="oc-tool-result' + errCls + '"><span class="oc-tool-result-name">' + escapeHtml(toolName) + '</span><pre class="oc-tool-result-body">' + escapeHtml(resultText) + '</pre></div>';
        } else {
            body = '<div class="oc-content-text">' + escapeHtml(JSON.stringify(meta)) + '</div>';
        }

        return '<div class="oc-msg ' + cls + '"><div class="oc-msg-label">' + escapeHtml(label) + ' · ' + escapeHtml(typeTag) + '</div><div class="oc-msg-body">' + body + '</div></div>';
    }).join('');

    var css = '*{box-sizing:border-box} body{margin:0;padding:20px;font-family:\'Segoe UI\',system-ui,sans-serif;background:linear-gradient(160deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);color:#e8e8e8;min-height:100vh}' +
        '.oc-header{text-align:center;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.12)} .oc-header h1{font-size:1.35rem;font-weight:600;margin:0;color:#fff}' +
        '.oc-messages{display:flex;flex-direction:column;gap:16px}' +
        '.oc-msg{background:rgba(255,255,255,0.06);border-radius:12px;padding:14px 18px;border:1px solid rgba(255,255,255,0.08)}' +
        '.oc-msg-user{border-left:4px solid rgba(59,130,246,0.8)} .oc-msg-assistant{border-left:4px solid rgba(99,102,241,0.8)} .oc-msg-tool{border-left:4px solid rgba(156,163,175,0.8)}' +
        '.oc-msg-completion{opacity:0.85}' +
        '.oc-msg-label{font-size:0.75rem;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:8px}' +
        '.oc-msg-body{font-size:0.95rem;line-height:1.55}' +
        '.oc-content-text{white-space:pre-wrap;word-break:break-word}' +
        '.oc-content-thinking{font-size:0.85rem;color:rgba(255,255,255,0.85)} .oc-content-thinking summary{cursor:pointer}' +
        '.oc-thinking-pre,.oc-tool-args,.oc-tool-result-body{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;font-size:0.85rem;max-height:220px;overflow-y:auto}' +
        '.oc-content-toolcall{margin-top:8px} .oc-tool-name{font-weight:600;color:#c7d2fe}' +
        '.oc-tool-result-name{font-weight:600;color:rgba(255,255,255,0.9)} .oc-tool-error .oc-tool-result-body{color:#fca5a5}';

    return '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>OpenClaw 对话</title><style>' + css + '</style></head><body><div class="oc-header"><h1>OpenClaw 对话</h1></div><div class="oc-messages">' + listHtml + '</div></body></html>';
}

/**
 * 根据 payload.messages（旧格式）生成对话 iframe HTML
 */
function buildOpenClawChatHtml(messages) {
    var roleLabel = { user: '用户', assistant: '助手', toolResult: '工具结果' };
    var roleClass = { user: 'oc-msg-user', assistant: 'oc-msg-assistant', toolResult: 'oc-msg-tool' };

    function renderContentItems(items) {
        if (!items || !Array.isArray(items)) return '';
        return items.map(function (item) {
            if (item.type === 'text' && item.text) {
                return '<div class="oc-content-text">' + escapeHtml(item.text).replace(/\n/g, '<br>') + '</div>';
            }
            if (item.type === 'thinking' && item.thinking) {
                var short = item.thinking.length > 300 ? item.thinking.slice(0, 300) + '…' : item.thinking;
                return '<details class="oc-content-thinking"><summary>思考</summary><pre class="oc-thinking-pre">' + escapeHtml(short) + '</pre></details>';
            }
            if (item.type === 'toolCall' && item.name) {
                var argsStr = item.arguments ? JSON.stringify(item.arguments) : '{}';
                return '<div class="oc-content-toolcall"><span class="oc-tool-name">' + escapeHtml(item.name) + '</span><pre class="oc-tool-args">' + escapeHtml(argsStr) + '</pre></div>';
            }
            return '';
        }).join('');
    }

    var listHtml = messages.map(function (msg) {
        var role = msg.role || 'assistant';
        var label = roleLabel[role] || role;
        var cls = roleClass[role] || 'oc-msg-assistant';
        var body = '';
        if (role === 'toolResult') {
            var toolName = msg.toolName || 'tool';
            var errCls = msg.isError ? ' oc-tool-error' : '';
            var text = (msg.content && msg.content[0] && msg.content[0].text) ? msg.content[0].text : '';
            if (text.length > 800) text = text.slice(0, 800) + '\n…';
            body = '<div class="oc-tool-result' + errCls + '"><span class="oc-tool-result-name">' + escapeHtml(toolName) + '</span><pre class="oc-tool-result-body">' + escapeHtml(text) + '</pre></div>';
        } else {
            body = renderContentItems(msg.content);
        }
        return '<div class="oc-msg ' + cls + '"><div class="oc-msg-label">' + escapeHtml(label) + '</div><div class="oc-msg-body">' + body + '</div></div>';
    }).join('');

    var css = '*{box-sizing:border-box} body{margin:0;padding:20px;font-family:\'Segoe UI\',system-ui,sans-serif;background:linear-gradient(160deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);color:#e8e8e8;min-height:100vh}' +
        '.oc-header{text-align:center;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.12)} .oc-header h1{font-size:1.35rem;font-weight:600;margin:0;color:#fff}' +
        '.oc-messages{display:flex;flex-direction:column;gap:16px}' +
        '.oc-msg{background:rgba(255,255,255,0.06);border-radius:12px;padding:14px 18px;border:1px solid rgba(255,255,255,0.08)}' +
        '.oc-msg-user{border-left:4px solid rgba(59,130,246,0.8)} .oc-msg-assistant{border-left:4px solid rgba(99,102,241,0.8)} .oc-msg-tool{border-left:4px solid rgba(156,163,175,0.8)}' +
        '.oc-msg-label{font-size:0.75rem;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:8px}' +
        '.oc-msg-body{font-size:0.95rem;line-height:1.55}' +
        '.oc-content-text{white-space:pre-wrap;word-break:break-word}' +
        '.oc-content-thinking summary{cursor:pointer}' +
        '.oc-thinking-pre,.oc-tool-args,.oc-tool-result-body{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;font-size:0.85rem;max-height:220px;overflow-y:auto}' +
        '.oc-content-toolcall .oc-tool-name{font-weight:600;color:#c7d2fe}' +
        '.oc-tool-result-name{font-weight:600} .oc-tool-error .oc-tool-result-body{color:#fca5a5}';
    return '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>OpenClaw 对话</title><style>' + css + '</style></head><body><div class="oc-header"><h1>OpenClaw 对话</h1></div><div class="oc-messages">' + listHtml + '</div></body></html>';
}

/** 工作区静态文件 API 前缀，用于补全 work_space 路径，避免相对路径导致 404/卡住 */
var FILE_BASE_URL = '/api/nae-deep-research/v1';

/**
 * 将 work_space/... 或 workspace/... 路径转为可请求的完整 URL（避免相对路径 404）
 * @param {string} pathOrRelative - 相对路径如 work_space/xxx/file.md 或已是 /api/... 的路径
 * @returns {string} 用于 fetch/iframe 的 URL
 */
function toWorkSpaceFileUrl(pathOrRelative) {
    if (!pathOrRelative || typeof pathOrRelative !== 'string') return pathOrRelative;
    if (pathOrRelative.indexOf('/api/') === 0) return pathOrRelative;
    var s = pathOrRelative.replace(/^\/+/, '');
    if (s.indexOf('work_space') === 0 || s.indexOf('workspace') === 0) return FILE_BASE_URL + '/' + s;
    return pathOrRelative;
}

/**
 * 在右侧电脑区打开指定文件（供 tooltip/step_notes 中的文件链接调用）
 * 设置 __rightPanelShowingFile 防止后续 OpenClaw 流式消息覆盖 iframe
 * @param {string} fullPath - 文件路径，如 /api/nae-deep-research/v1/work_space/.../xxx.html 或 work_space/.../xxx.md
 */
function openFileInRightPanel(fullPath) {
    if (!fullPath || typeof fullPath !== 'string') return;
    var path = fullPath.trim();
    if (!path) return;
    // 若非以 /api/ 开头，补全为 API 路径
    if (path.indexOf('/api/') !== 0 && path.indexOf('work_space') !== -1) {
        path = '/api/nae-deep-research/v1/' + (path.charAt(0) === '/' ? path.slice(1) : path);
    }
    window.__rightPanelShowingFile = { path: path, at: Date.now() };
    var toolCall = {
        url: null,
        path: path,
        tool: 'file_saver',
        toolName: (typeof window.I18nService !== 'undefined' && window.I18nService.t('file_saver')) ? window.I18nService.t('file_saver') : '保存文件'
    };
    showRightPanelForTool(toolCall);
}

function showRightPanelForTool(toolCall) {
    const result = showRightPanel();
    if (!result) {
        return;
    }
    // 标记当前右侧正在显示文件，避免 OpenClaw 消息覆盖
    if (toolCall.path && toolCall.path !== 'code://execute_code') {
        window.__rightPanelShowingFile = { path: toolCall.path, at: Date.now() };
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

        // 先清 srcdoc 再设 src，否则 srcdoc 会一直占优导致后续加载无效
        if (iframe.srcdoc) {
            iframe.removeAttribute('srcdoc');
            iframe.srcdoc = '';
        }
        iframe.src = 'about:blank';

        // 本站同源的可嵌入 API（如 search-results）直接加载，不走外部嵌入检查
        if (isOwnEmbeddableApiUrl(url)) {
            loadIframeContent(url, iframe, statusElement, tool, path);
        } else {
            // 检查 iframe 嵌入是否被允许
            checkIframeEmbedding(url).then(allowed => {
                if (allowed) {
                    loadIframeContent(url, iframe, statusElement, tool, path);
                } else {
                    showIframeEmbeddingError(url, statusElement);
                }
            }).catch(error => {
                console.warn('iframe嵌入检查失败，尝试直接加载:', error);
                loadIframeContent(url, iframe, statusElement, tool, path);
            });
        }

    } else if (path) {
        // 处理代码执行工具的特殊情况
        if (path === 'code://execute_code') {
            // 显示代码内容
            iframe.style.display = 'none';
            markdownContent.style.display = 'block';

            if (statusElement) {
                statusElement.textContent = generateStatusText(tool, url, path);
                statusElement.className = 'success';
            }

            // 显示代码内容
            displayCodeContent(toolCall);
            console.log('显示代码执行内容');
            return;
        }

        // 根据扩展名决定渲染方式
        const fileName = path.split('/').pop() || path.split('\\').pop() || '';
        const ext = (fileName.split('.').pop() || '').toLowerCase();

        // 将绝对路径转换为相对路径（与 loadMarkdownFile 保持一致）
        let relativePath = path;
        // 如果路径已经是完整的API路径（以/api/开头），直接使用
        if (relativePath.startsWith('/api/')) {
            relativePath = path;
        } else if (relativePath.includes('work_space')) {
            // 提取work_space之后的路径部分
            const workspaceIndex = relativePath.indexOf('work_space');
            if (workspaceIndex !== -1) {
                relativePath = relativePath.substring(workspaceIndex);
            }
        } else if (relativePath.includes('workspace')) {
            // 兼容旧的workspace命名
            const workspaceIndex = relativePath.indexOf('workspace');
            if (workspaceIndex !== -1) {
                relativePath = relativePath.substring(workspaceIndex);
            }
        }
        // 统一将 work_space/skills 的本地绝对路径映射为后端可访问的 API 路径
        relativePath = buildApiWorkspacePath(relativePath);

        if (ext === 'html' || ext === 'htm') {
            // 项目外路径（无 work_space）：通过 read-file API 取内容再用 srcdoc 显示，避免 iframe.src 导致 404
            var isExternalPath = path.indexOf('/api/') !== 0 && path.indexOf('work_space') === -1 && path.indexOf('workspace') === -1;
            if (isExternalPath) {
                toggleLoadingIndicator(true);
                if (statusElement) {
                    statusElement.textContent = generateStatusText(tool, url, path);
                    statusElement.className = 'loading';
                }
                iframe.style.display = 'block';
                markdownContent.style.display = 'none';
                iframe.src = 'about:blank';
                var apiUrl = '/api/nae-deep-research/v1/read-file?file_path=' + encodeURIComponent(path);
                fetch(apiUrl)
                    .then(function (res) {
                        if (!res.ok) throw new Error('HTTP error! status: ' + res.status);
                        return res.json();
                    })
                    .then(function (data) {
                        if (data.code === 0 && data.data && data.data.content) {
                            iframe.srcdoc = data.data.content;
                            if (statusElement) {
                                statusElement.textContent = generateStatusText(tool, url, path);
                                statusElement.className = 'success';
                            }
                            console.log('项目外 HTML 已通过 read-file 加载:', path);
                        } else {
                            throw new Error(data.message || '读取文件失败');
                        }
                    })
                    .catch(function (err) {
                        console.error('加载项目外 HTML 失败:', path, err);
                        if (statusElement) {
                            statusElement.textContent = (window.I18nService ? window.I18nService.t('webpage_load_failed').replace('{url}', path) : '网页加载失败: ' + path) + ' - ' + (err && err.message ? err.message : '');
                            statusElement.className = 'error';
                        }
                    })
                    .finally(function () { toggleLoadingIndicator(false); });
                return;
            }

            // 工作区内 HTML：优先用 read-file + srcdoc 显示，避免 iframe.src 加载时 onload 不触发导致一直转圈
            toggleLoadingIndicator(true);
            if (statusElement) {
                statusElement.textContent = generateStatusText(tool, url, path);
                statusElement.className = 'loading';
            }
            iframe.style.display = 'block';
            markdownContent.style.display = 'none';
            iframe.src = 'about:blank';

            // read-file 需要「相对 work_space 目录」的路径，如 work_space_xxx/文件.html
            var pathForApi = relativePath.replace(/^.*?work_space\//, '');
            var readFileUrl = FILE_BASE_URL + '/read-file?file_path=' + encodeURIComponent(pathForApi);
            var fetchPromise = fetch(readFileUrl).then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            });
            var FETCH_HTML_TIMEOUT_MS = 15000;
            var timeoutPromise = new Promise(function (_, reject) {
                setTimeout(function () { reject(new Error('请求超时')); }, FETCH_HTML_TIMEOUT_MS);
            });
            Promise.race([fetchPromise, timeoutPromise])
                .then(function (data) {
                    if (data.code === 0 && data.data && data.data.content) {
                        iframe.srcdoc = data.data.content;
                        if (statusElement) {
                            statusElement.textContent = generateStatusText(tool, url, path);
                            statusElement.className = 'success';
                        }
                        console.log('工作区 HTML 已通过 read-file 加载:', relativePath);
                    } else {
                        throw new Error(data.message || '读取失败');
                    }
                })
                .catch(function (err) {
                    console.error('工作区 HTML read-file 失败:', relativePath, err);
                    if (statusElement) {
                        statusElement.textContent = (window.I18nService ? window.I18nService.t('webpage_load_failed').replace('{url}', relativePath) : '网页加载失败: ' + relativePath) + ' - ' + (err && err.message ? err.message : '');
                        statusElement.className = 'error';
                    }
                })
                .finally(function () { toggleLoadingIndicator(false); });
        } else {
            // 显示 Markdown/文本内容
            iframe.style.display = 'none';
            markdownContent.style.display = 'block';

            if (statusElement) {
                statusElement.textContent = generateStatusText(tool, url, path);
                statusElement.className = 'loading';
            }
        loadMarkdownFile(relativePath, tool);
        }
    } else {
        // 该工具无 URL/路径可预览时，仍更新电脑区状态与占位内容，保证点击有反馈
        var toolLabel = (toolCall.toolName || tool || '工具') + '';
        var safeLabel = toolLabel.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        if (iframe) {
            iframe.style.display = 'block';
            iframe.srcdoc = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:sans-serif;padding:24px;color:#555;}</style></head><body><p>' + safeLabel + '</p><p>该工具无链接或文件可预览。</p></body></html>';
        }
        if (markdownContent) markdownContent.style.display = 'none';
        if (statusElement) {
            statusElement.textContent = toolLabel || '工具详情';
            statusElement.className = '';
        }
    }
}

// 显示代码执行内容
function displayCodeContent(toolCall) {
    const markdownContent = document.getElementById('markdown-content');
    
    // 解析工具参数获取代码内容
    let codeContent = '';
    let executionResult = '';
    
    try {
        // 从工具调用记录中获取代码参数
        const args = JSON.parse(toolCall.tool_args || '{}');
        codeContent = args.code || '';
        
        // 获取执行结果
        if (toolCall.result) {
            executionResult = toolCall.result;
        }
    } catch (e) {
        console.warn('解析代码执行工具参数失败:', e);
        codeContent = '无法解析代码内容';
    }
    
    // 生成HTML内容
    const htmlContent = `
        <div class="code-execution-content">
            <h3><i class="fas fa-code"></i> 代码执行详情</h3>
            
            <div class="code-section">
                <h4><i class="fas fa-file-code"></i> 执行的代码</h4>
                <div class="code-block">
                    <pre><code class="language-python">${escapeHtml(codeContent)}</code></pre>
                </div>
            </div>
            
            ${executionResult ? `
            <div class="result-section">
                <h4><i class="fas fa-terminal"></i> 执行结果</h4>
                <div class="result-block">
                    <pre><code>${escapeHtml(executionResult)}</code></pre>
                </div>
            </div>
            ` : ''}
            
            <div class="tool-info">
                <h4><i class="fas fa-info-circle"></i> 工具信息</h4>
                <ul>
                    <li><strong>工具名称:</strong> ${toolCall.toolName || '代码执行器'}</li>
                    <li><strong>执行状态:</strong> <span class="status-${toolCall.status}">${toolCall.status === 'completed' ? '已完成' : toolCall.status === 'running' ? '执行中' : '失败'}</span></li>
                    ${toolCall.duration ? `<li><strong>执行时间:</strong> ${(toolCall.duration / 1000).toFixed(2)} 秒</li>` : ''}
                </ul>
            </div>
        </div>
        
        <style>
            .code-execution-content {
                padding: 20px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
            }
            
            .code-execution-content h3 {
                color: #2c3e50;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }
            
            .code-execution-content h4 {
                color: #34495e;
                margin: 20px 0 10px 0;
                font-size: 1.1em;
            }
            
            .code-block, .result-block {
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 8px;
                padding: 15px;
                margin: 10px 0;
                overflow-x: auto;
            }
            
            .code-block pre, .result-block pre {
                margin: 0;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            
            .code-block code {
                font-family: 'Courier New', Courier, monospace;
                font-size: 14px;
                color: #2c3e50;
            }
            
            .result-block code {
                font-family: 'Courier New', Courier, monospace;
                font-size: 14px;
                color: #27ae60;
            }
            
            .tool-info {
                background: #ecf0f1;
                border-radius: 8px;
                padding: 15px;
                margin-top: 20px;
            }
            
            .tool-info ul {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            
            .tool-info li {
                margin: 8px 0;
                padding: 5px 0;
            }
            
            .status-completed {
                color: #27ae60;
                font-weight: bold;
            }
            
            .status-running {
                color: #f39c12;
                font-weight: bold;
            }
            
            .status-failed {
                color: #e74c3c;
                font-weight: bold;
            }
        </style>
    `;
    
    markdownContent.innerHTML = htmlContent;
}

// HTML转义函数
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function isImageExtension(ext) {
    if (!ext) return false;
    const e = String(ext).toLowerCase();
    return ['gif', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'svg'].includes(e);
}

function renderImagePreview(originalFilePath, relativePath, tool) {
    const markdownContent = document.getElementById('markdown-content');
    const statusElement = document.getElementById('right-container-status');
    const iframe = document.getElementById('content-iframe');

    if (iframe) iframe.style.display = 'none';
    if (markdownContent) markdownContent.style.display = 'block';

    if (statusElement) {
        statusElement.textContent = generateStatusText(tool, null, originalFilePath);
        statusElement.className = 'loading';
    }

    const safeSrc = escapeHtml(relativePath);
    if (markdownContent) {
        markdownContent.innerHTML = `
            <div style="padding: 10px;">
                <div style="color: rgba(0,0,0,0.65); font-size: 13px; margin-bottom: 10px;">
                    图片预览：${escapeHtml(originalFilePath)}
                </div>
                <div style="display:flex; justify-content:center; align-items:center;">
                    <img id="cosight-image-preview" src="${safeSrc}" alt="image"
                         style="max-width: 100%; max-height: calc(100vh - 220px); border-radius: 10px; border: 1px solid rgba(0,0,0,0.08); background:#fff;" />
                </div>
            </div>
        `;
    }

    // 监听加载成功/失败，更新状态栏
    try {
        const img = document.getElementById('cosight-image-preview');
        if (img) {
            img.onload = () => {
                if (statusElement) {
                    statusElement.textContent = generateStatusText(tool, null, originalFilePath);
                    statusElement.className = 'success';
                }
            };
            img.onerror = () => {
                if (statusElement) {
                    statusElement.textContent = `图片加载失败: ${originalFilePath}`;
                    statusElement.className = 'error';
                }
            };
        }
    } catch (e) {
        // ignore
    }
}


// 加载并显示markdown文件
function loadMarkdownFile(filePath, tool) {
    const markdownContent = document.getElementById('markdown-content');
    const statusElement = document.getElementById('right-container-status');

    // 显示加载状态
    markdownContent.innerHTML = `<div style="text-align: center; padding: 50px;"><i class="fas fa-spinner fa-spin"></i> ${(window.I18nService ? window.I18nService.t('loading_file') : '正在加载文件...')}</div>`;

    // 更新状态文本
    if (statusElement) {
        statusElement.textContent = generateStatusText(tool, null, filePath);
        statusElement.className = 'loading';
    }

    // 将绝对路径转换为相对路径
    let relativePath = filePath;
    let useApiEndpoint = false; // 标记是否使用 API 端点读取文件
    
    // 如果路径已经是完整的API路径（以/api/开头），直接使用
    if (filePath.startsWith('/api/')) {
        relativePath = filePath;
    } else if (filePath.includes('work_space')) {
        // 提取work_space之后的路径部分
        const workspaceIndex = filePath.indexOf('work_space');
        if (workspaceIndex !== -1) {
            relativePath = filePath.substring(workspaceIndex);
        }
    } else if (filePath.includes('workspace')) {
        // 兼容旧的workspace命名
        const workspaceIndex = filePath.indexOf('workspace');
        if (workspaceIndex !== -1) {
            relativePath = filePath.substring(workspaceIndex);
        }
    } else {
        // 如果路径不包含 work_space 或 workspace，说明是工作区外的文件
        // 使用 API 端点来读取
        useApiEndpoint = true;
    }

    // skills/work_space 统一走 API 路径，避免请求到 /home/... 或 /cosight/work_space...
    relativePath = buildApiWorkspacePath(relativePath);

    console.log('尝试加载文件:', relativePath, '使用API端点:', useApiEndpoint);

    // 图片文件：不要按文本读取，直接预览
    const fileNameForExt = filePath.split('/').pop() || filePath.split('\\').pop() || '';
    const extForExt = (fileNameForExt.split('.').pop() || '').toLowerCase();
    if (isImageExtension(extForExt)) {
        renderImagePreview(filePath, relativePath, tool);
        return;
    }
    // 根据文件路径类型选择不同的加载方式
    let fetchPromise;
    if (useApiEndpoint) {
        // 对于工作区外的文件，使用 API 端点读取
        const apiUrl = `/api/nae-deep-research/v1/read-file?file_path=${encodeURIComponent(filePath)}`;
        fetchPromise = fetch(apiUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.code === 0 && data.data && data.data.content) {
                    return data.data.content;
                } else {
                    throw new Error(data.message || '读取文件失败');
                }
            });
    } else {
        // 对于工作区内的文件，使用完整 API URL 请求静态文件，避免相对路径 404/卡住
        var workSpaceUrl = toWorkSpaceFileUrl(relativePath);
        fetchPromise = fetch(workSpaceUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.text();
            });
    }

    // 统一加超时，防止请求挂起导致电脑区一直“正在加载”
    var FETCH_FILE_TIMEOUT_MS = 15000;
    var timeoutPromise = new Promise(function (_, reject) {
        setTimeout(function () { reject(new Error('请求超时')); }, FETCH_FILE_TIMEOUT_MS);
    });
    fetchPromise = Promise.race([fetchPromise, timeoutPromise]);

    // 更新状态文本
    if (statusElement) {
        const fileName = filePath.split('/').pop() || filePath.split('\\').pop();
        statusElement.textContent = (window.I18nService ? window.I18nService.t('parsing_file').replace('{fileName}', fileName) : `正在解析文件 ${fileName}`);
        statusElement.className = 'loading';
    }

    fetchPromise
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
                    <h3>${(window.I18nService ? window.I18nService.t('file_load_failed_title') : '文件加载失败')}</h3>
                    <p>${(window.I18nService ? window.I18nService.t('unable_to_load_file').replace('{filePath}', filePath) : `无法加载文件: ${filePath}`)}</p>
                    <p>${(window.I18nService ? window.I18nService.t('error_message').replace('{message}', error.message) : `错误信息: ${error.message}`)}</p>
                </div>
            `;

            // 更新状态文本
            if (statusElement) {
                const fileName = filePath.split('/').pop() || filePath.split('\\').pop();
                statusElement.textContent = (window.I18nService ? window.I18nService.t('file_load_failed').replace('{fileName}', fileName) : `文件 ${fileName} 加载失败`);
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
    let html = `<h4>${(window.I18nService ? window.I18nService.t('task_steps_list') : '任务步骤列表')}</h4>`;

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
        } catch (_) {}

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

// 从搜索工具结果中提取URL
function extractUrlFromSearchResult(toolResult, toolName) {
    if (!toolResult) return null;

    // 统一字符串中的 Python 常量为 JSON 常量，便于后续解析
    const normalizePythonLiterals = (s) => s
        .replace(/\bNone\b/g, 'null')
        .replace(/\bTrue\b/g, 'true')
        .replace(/\bFalse\b/g, 'false')
        .replace(/\\'/g, "'");

    let parsed = null;

    // 情况1：已是对象
    if (typeof toolResult === 'object') {
        parsed = toolResult;
    } else if (typeof toolResult === 'string') {
        let s = toolResult.trim();
        // 优先尝试 JSON 解析
        try {
            parsed = JSON.parse(s);
        } catch (_) {
            // 尝试规范化 Python 风格并解析
            try {
                s = normalizePythonLiterals(s);
                // 先尝试 JSON
                try {
                    parsed = JSON.parse(s);
                } catch (__) {
                    // 再尝试函数求值（受信任环境）
                    const fn = new Function('return (' + s + ')');
                    parsed = fn();
                }
            } catch (e2) {
                console.warn('extractUrlFromSearchResult 解析失败:', e2);
                parsed = null;
            }
        }
    }

    if (!parsed) return null;

    const name = String(toolName || '').toLowerCase();

    if (name === 'tavily_search' || name === 'search_tavily') {
        // tavily_search 结构: { results: [ { url } ] }
        if (parsed.results && Array.isArray(parsed.results) && parsed.results.length > 0) {
            const first = parsed.results.find(it => it && (it.url || it.link)) || parsed.results[0];
            return (first && (first.url || first.link)) || null;
        }
    } else if (name === 'image_search') {
        // image_search 结构: { content: { 0: { url } } }
        if (parsed.content && typeof parsed.content === 'object') {
            for (const key in parsed.content) {
                const item = parsed.content[key];
                if (item && (item.url || item.link)) {
                    return item.url || item.link;
                }
            }
        }
        // 兜底：若存在 images 数组且为可浏览链接
        if (Array.isArray(parsed.images) && parsed.images.length > 0) {
            return parsed.images[0] || null;
        }
    } else {
        // 其它搜索工具的兜底处理：数组或对象里找 url/link
        if (Array.isArray(parsed) && parsed.length > 0) {
            const withUrl = parsed.find(it => it && (it.url || it.link)) || parsed[0];
            return (withUrl && (withUrl.url || withUrl.link)) || null;
        }
        if (parsed && typeof parsed === 'object') {
            if (Array.isArray(parsed.results) && parsed.results.length > 0) {
                const first = parsed.results.find(it => it && (it.url || it.link)) || parsed.results[0];
                return (first && (first.url || first.link)) || null;
            }
            if (Array.isArray(parsed.items) && parsed.items.length > 0) {
                const first = parsed.items.find(it => it && (it.url || it.link)) || parsed.items[0];
                return (first && (first.url || first.link)) || null;
            }
        }
    }

    return null;
}

// ==================== iframe嵌入检查相关函数 ====================

/**
 * 判断是否为本站可嵌入 API 的 path（如 /api/nae-deep-research/v1/search-results），
 * 仅看 path 不要求同源，避免后端返回带 127.0.0.1 等 host 时与当前页 origin 不一致导致误判。
 * @param {string} url - 要检查的 URL（可为相对路径或绝对路径）
 * @returns {boolean}
 */
function isOwnEmbeddableApiUrl(url) {
    if (!url || typeof url !== 'string') return false;
    try {
        var pathname;
        var s = url.trim();
        if (s.indexOf('/') === 0) {
            pathname = s.split('?')[0];
        } else if (s.indexOf('http') === 0) {
            try {
                pathname = new URL(s).pathname;
            } catch (_) {
                return false;
            }
        } else {
            return false;
        }
        return pathname.indexOf('/api/nae-deep-research/') === 0;
    } catch (_) {
        return false;
    }
}

/**
 * 检查URL是否允许iframe嵌入
 * @param {string} url - 要检查的URL
 * @returns {Promise<boolean>} - 是否允许嵌入
 */
async function checkIframeEmbedding(url) {
    try {
        const response = await fetch('/api/nae-deep-research/v1/check-iframe-embedding', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        
        if (!result.allowed) {
            console.warn(`iframe嵌入被拒绝: ${url}, 原因: ${result.reason}`);
        }
        
        return result.allowed;
    } catch (error) {
        console.warn('iframe嵌入检查失败:', error);
        // 检查失败时允许尝试加载
        return true;
    }
}

/**
 * 加载iframe内容
 * @param {string} url - 要加载的URL
 * @param {HTMLElement} iframe - iframe元素
 * @param {HTMLElement} statusElement - 状态显示元素
 * @param {string} tool - 工具名称
 * @param {string} path - 路径
 */
function loadIframeContent(url, iframe, statusElement, tool, path) {
    // 等待清理完成后再加载新内容
    setTimeout(() => {
        let isBlank = true;

        // 设置加载超时机制（15秒，比原来更长）
        iframe._loadingTimeout = setTimeout(() => {
            if (isBlank) return;
            toggleLoadingIndicator(false);
            if (statusElement) {
                statusElement.textContent = (window.I18nService ? window.I18nService.t('loading_timeout').replace('{url}', url) : `加载超时: ${url}`);
                statusElement.className = 'error';
            }
            console.warn('iframe加载超时:', url);
        }, 15000);

        // 设置加载完成事件监听器
        iframe.onload = function () {
            if (isBlank) return;

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
                statusElement.textContent = (window.I18nService ? window.I18nService.t('webpage_load_failed').replace('{url}', url) : `网页加载失败: ${url}`);
                statusElement.className = 'error';
            }
            console.error('iframe加载失败:', url);
        };

        // 加载新内容
        iframe.src = url;
        isBlank = false;
    }, 100);
}

/**
 * 外链不允许嵌入时：仅更新状态文案，不显示无法嵌入模版页（避免 srcdoc 导致后续点击工具卡片无反应）
 * @param {string} url - 无法嵌入的URL
 * @param {HTMLElement} statusElement - 状态显示元素
 */
function showIframeEmbeddingError(url, statusElement) {
    toggleLoadingIndicator(false);
    if (statusElement) {
        statusElement.textContent = `网页不允许嵌入iframe: ${url}`;
        statusElement.className = 'error';
    }
    const iframe = document.getElementById('content-iframe');
    if (iframe) {
        iframe.style.display = 'block';
        iframe.removeAttribute('srcdoc');
        iframe.srcdoc = '';
        iframe.src = 'about:blank';
    }
}

/**
 * 在新窗口打开URL
 * @param {string} url - 要打开的URL
 */
function openInNewWindow(url) {
    window.open(url, '_blank', 'noopener,noreferrer');
}

/**
 * 复制URL到剪贴板
 * @param {string} url - 要复制的URL
 */
async function copyUrlToClipboard(url) {
    try {
        await navigator.clipboard.writeText(url);
        
        // 显示复制成功提示
        const button = event.target.closest('.action-btn');
        const originalText = button.innerHTML;
        button.innerHTML = '<i class="fas fa-check"></i> 已复制!';
        button.style.background = '#28a745';
        
        setTimeout(() => {
            button.innerHTML = originalText;
            button.style.background = '';
        }, 2000);
        
    } catch (error) {
        console.error('复制失败:', error);
        alert('复制失败，请手动复制: ' + url);
    }
}

// 将函数暴露到全局作用域（DAG 节点点击、工具栏卡片等依赖）
window.openInNewWindow = openInNewWindow;
window.copyUrlToClipboard = copyUrlToClipboard;
window.showOpenClawStepInRightPanel = showOpenClawStepInRightPanel;
window.showRightPanel = showRightPanel;
window.showRightPanelForTool = showRightPanelForTool;