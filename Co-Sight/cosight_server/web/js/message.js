class MessageService {
    constructor() {
        // 存储每个step的tool events
        this.stepToolEvents = new Map(); // stepIndex -> Array of tool events
        // 存储当前step的pending tool starts (等待complete的tool_start消息)
        this.pendingToolStarts = new Map(); // stepIndex -> Array of tool_start events

        // 恢复本地存储的step tool events
        this.restoreStepToolEvents();
    }

    receiveMessage(message) {
        console.log('MessageService.receiveMessage >>>>>>>>>>>>>> ', message);

        try {
            // 解析消息
            const messageData = typeof message === 'string' ? JSON.parse(message) : message;

            // 首次收到该topic的任意消息则清除stillPending标记
            try {
                const topic = messageData.topic;
                if (topic) {
                    const pendingRaw = localStorage.getItem('cosight:pendingRequests');
                    const pendings = pendingRaw ? JSON.parse(pendingRaw) : {};
                    if (pendings[topic] && pendings[topic].stillPending === true) {
                        pendings[topic].stillPending = false;
                        localStorage.setItem('cosight:pendingRequests', JSON.stringify(pendings));
                    }
                }
            } catch (e) {
                console.warn('更新pending标记失败:', e);
            }

            // 处理控制类结束信号，标记pending完成
            if (messageData && messageData.data && messageData.data.type === 'control-status-message') {
                try {
                    const topic = messageData.topic;
                    const pendingRaw = localStorage.getItem('cosight:pendingRequests');
                    const pendings = pendingRaw ? JSON.parse(pendingRaw) : {};
                    if (topic && pendings[topic]) {
                        delete pendings[topic];
                        localStorage.setItem('cosight:pendingRequests', JSON.stringify(pendings));
                    }
                } catch (e) {
                    console.warn('更新pending失败:', e);
                }
            }

            // 处理 lui-message-tool-event 类型的消息
            // 支持 contentType 和 type 两种字段名以保持兼容性
            const messageType = messageData.data?.contentType || messageData.data?.type;
            
            if (messageType === 'lui-message-tool-event') {
                console.log('收到 lui-message-tool-event 消息:', messageData);
                this.handleToolEvent(messageData);
                return;
            }

            // 处理 lui-message-credibility-analysis 类型的消息
            if (messageType === 'lui-message-credibility-analysis') {
                console.log('收到 lui-message-credibility-analysis 消息:', messageData);
                credibilityService.credibilityMessageHandler(messageData);
                return;
            }

            // 检查是否是 lui-message-manus-step 类型的消息
            if (messageType === 'lui-message-manus-step') {
                console.log('收到 lui-message-manus-step 消息，开始创建DAG图');
                console.log('完整消息数据:', messageData);
                this.stepMessageHandler(messageData);
            } else {
                console.log('收到其他类型的消息:', messageType || 'unknown');
            }
        } catch (error) {
            console.error('处理消息时发生错误:', error);
        }
    }

    stepMessageHandler(messageData) {
        // 调用 createDag 方法来创建DAG图
        const result = createDag(messageData);
        if (!result) {
            return;
        }

        // 成功后持久化消息到本地以便刷新恢复
        try {
            localStorage.setItem('cosight:lastManusStep', JSON.stringify({
                message: messageData,
                savedAt: Date.now()
            }));
        } catch (e) {
            console.warn('保存本地状态失败:', e);
        }

        // 获取initData，支持多种格式
        const initData = messageData.data?.content || messageData.data?.initData;
        
        // 显示标题信息
        if (initData && initData.title) {
            updateDynamicTitle(initData.title);
            showStepsTooltip();
            setTimeout(() => {
                hideStepsTooltip();
            }, 3000);
        }
        
        // 在接收到步骤状态更新后，自动关闭已完成且无运行中工具的步骤面板
        try {
            if (initData) {
                this._autoCloseCompletedStepPanels(initData);
            }
        } catch (e) {
            console.warn('自动关闭完成步骤面板时发生异常:', e);
        }
    }

    /**
     * 基于topic生成并复用稳定的planId(messageSerialNumber)
     */
    ensurePlanIdForTopic(topic) {
        try {
            const raw = localStorage.getItem('cosight:planIdByTopic');
            const map = raw ? JSON.parse(raw) : {};
            let rec = map[topic];
            if (!rec || rec.completed === true || !rec.planId) {
                const planId = (crypto && crypto.randomUUID) ? crypto.randomUUID() : `${topic}-${Date.now()}`;
                rec = { planId, stillPending: true, completed: false };
                map[topic] = rec;
                localStorage.setItem('cosight:planIdByTopic', JSON.stringify(map));
                console.log('store planIdByTopic',JSON.stringify(map));                
            }
            return rec.planId;
        } catch (e) {
            console.warn('生成/读取planId失败，退化为时间戳:', e);
            return `${topic}-${Date.now()}`;
        }
    }

    /**
     * 处理tool event消息
     */
    handleToolEvent(messageData) {
        // 兼容多种数据格式：
        // 1. messageData.data.content (标准格式，contentType字段)
        // 2. messageData.data.initData.plan (旧格式)
        // 3. messageData.data.initData (旧格式)
        const toolEventData = messageData.data?.content || messageData.data?.initData?.plan || messageData.data?.initData;
        
        if (!toolEventData) {
            console.warn('无法获取tool event数据:', messageData);
            return;
        }
        
        const stepIndex = toolEventData.step_index;
        const eventType = toolEventData.event_type;
        
        console.log(`处理tool event: ${eventType}, step: ${stepIndex}, tool: ${toolEventData.tool_name}`);
        console.log('完整的toolEventData:', toolEventData);
        
        // 特殊处理 mark_step 工具事件，更新节点的 step_notes
        if (toolEventData.tool_name === 'mark_step' && eventType === 'tool_complete') {
            this.handleMarkStepEvent(toolEventData);
        }

        // 确保stepIndex对应的数组存在
        if (!this.stepToolEvents.has(stepIndex)) {
            this.stepToolEvents.set(stepIndex, []);
        }
        if (!this.pendingToolStarts.has(stepIndex)) {
            this.pendingToolStarts.set(stepIndex, []);
        }

        const stepEvents = this.stepToolEvents.get(stepIndex);
        const pendingStarts = this.pendingToolStarts.get(stepIndex);

        if (eventType === 'tool_start') {
            // 处理tool_start消息
            const toolStartEvent = {
                ...toolEventData,
                messageData: messageData,
                timestamp: Date.now()
            };
            
            // 添加到pending列表
            pendingStarts.push(toolStartEvent);
            
            // 检查是否是该step的第一个tool event，如果是则弹出panel
            if (stepEvents.length === 0 && pendingStarts.length === 1) {
                console.log(`Step ${stepIndex} 的第一个tool event，弹出panel`);
                this.showStepPanel(stepIndex);
            }
            
            // 立即创建一个"运行中"状态的工具调用记录并显示在panel上
            const runningToolCallRecord = {
                tool_name: toolEventData.tool_name,
                tool_args: toolEventData.tool_args,
                tool_result: null,
                status: 'running',
                duration: 0,
                timestamp: toolEventData.timestamp,
                step_index: stepIndex,
                start_event: toolStartEvent,
                complete_event: null,
                messageData: messageData
            };
            
            // 添加到step events（作为临时记录）
            stepEvents.push(runningToolCallRecord);
            
            // 立即更新panel显示
            this.updateStepPanel(stepIndex, runningToolCallRecord);
            
        } else if (eventType === 'tool_complete' || eventType === 'tool_error') {
            // 处理tool_complete或tool_error消息
            // 找到对应的tool_start消息（按顺序匹配）
            const matchingStartIndex = pendingStarts.findIndex(start => 
                start.tool_name === toolEventData.tool_name
            );
            
            let toolStartEvent = null;
            if (matchingStartIndex >= 0) {
                toolStartEvent = pendingStarts.splice(matchingStartIndex, 1)[0];
            }
            
            // 找到对应的"运行中"记录并更新它（依据同名工具且处于running状态）
            const runningRecordIndex = stepEvents.findIndex(record => 
                record.tool_name === toolEventData.tool_name && 
                record.status === 'running'
            );

            if (runningRecordIndex >= 0) {
                // 更新现有的运行中记录
                const runningRecord = stepEvents[runningRecordIndex];
                runningRecord.tool_result = toolEventData.processed_result || toolEventData.raw_result;
                runningRecord.status = eventType === 'tool_complete' ? 'completed' : 'failed';
                runningRecord.duration = toolEventData.duration || 0;
                runningRecord.complete_event = toolEventData;

                console.log(`更新运行中的工具记录: ${toolEventData.tool_name}, 状态: ${runningRecord.status}`);

                // 更新step panel显示
                this.updateStepPanel(stepIndex, runningRecord);
            } else {
                // 如果没找到对应的运行中记录，创建新的完整记录（兼容旧逻辑）
                console.log(`未找到运行中的记录，创建新记录: ${toolEventData.tool_name}`);
                const toolCallRecord = {
                    tool_name: toolEventData.tool_name,
                    tool_args: toolEventData.tool_args,
                    tool_result: toolEventData.processed_result || toolEventData.raw_result,
                    status: eventType === 'tool_complete' ? 'completed' : 'failed',
                    duration: toolEventData.duration || 0,
                    timestamp: toolEventData.timestamp,
                    step_index: stepIndex,
                    start_event: toolStartEvent,
                    complete_event: toolEventData,
                    messageData: messageData
                };

                // 添加到step events
                stepEvents.push(toolCallRecord);

                // 更新step panel显示
                this.updateStepPanel(stepIndex, toolCallRecord);
            }
        }

        // 持久化最新的step tool events
        this.persistStepToolEvents();
    }

    /**
     * 处理 mark_step 工具事件，更新节点的 step_notes
     */
    handleMarkStepEvent(toolEventData) {
        try {
            const stepIndex = toolEventData.step_index;
            const nodeId = stepIndex + 1; // stepIndex从0开始，DAG节点ID从1开始
            
            // 从tool_args中提取step_notes
            let stepNotes = '';
            if (toolEventData.tool_args) {
                try {
                    const args = JSON.parse(toolEventData.tool_args);
                    stepNotes = args.step_notes || '';
                } catch (e) {
                    console.warn('解析mark_step工具参数失败:', e);
                    return;
                }
            }
            
            console.log(`handleMarkStepEvent: stepIndex=${stepIndex}, nodeId=${nodeId}, step_notes=`, stepNotes);
            
            // 更新dagData中对应节点的step_notes
            if (typeof dagData !== 'undefined' && dagData.nodes) {
                const node = dagData.nodes.find(n => n.id === nodeId);
                if (node) {
                    node.step_notes = stepNotes;
                    console.log(`已更新节点 ${nodeId} 的 step_notes:`, stepNotes);
                } else {
                    console.warn(`未找到节点 ID ${nodeId}`);
                }
            } else {
                console.warn('dagData 未定义或没有 nodes 数组');
            }
        } catch (error) {
            console.error('处理mark_step事件时发生错误:', error);
        }
    }

    /**
     * 显示step panel
     */
    showStepPanel(stepIndex) {
        // stepIndex从0开始，DAG节点从1开始，需要转换
        const nodeId = stepIndex + 1;

        // 获取step信息
        const stepName = `Step ${nodeId}`;
        let stepTitle = stepName;

        // 尝试从DAG数据获取更详细的标题
        if (typeof dagData !== 'undefined' && dagData.nodes) {
            const node = dagData.nodes.find(n => n.id === nodeId);
            if (node) {
                const nodeText = node.fullName || node.title;
                if (nodeText) {
                    stepTitle = `${stepName} - ${nodeText}`;
                }
            }
        }

        // 创建并显示panel
        if (typeof createNodeToolPanel === 'function') {
            createNodeToolPanel(nodeId, stepTitle, false);
        }
    }

    /**
     * 更新step panel显示
     */
    updateStepPanel(stepIndex, toolCallRecord) {
        const nodeId = stepIndex + 1;
        console.log(`更新Step Panel: stepIndex=${stepIndex}, nodeId=${nodeId}`, toolCallRecord);

        // 转换为main.js期望的格式
        const toolCall = this.convertToToolCallFormat(toolCallRecord, nodeId);
        console.log('转换后的toolCall:', toolCall);

        // 更新panel显示
        if (typeof updateNodeToolPanel === 'function') {
            console.log('调用updateNodeToolPanel函数');
            updateNodeToolPanel(nodeId, toolCall);
        } else {
            console.error('updateNodeToolPanel函数不存在');
        }
    }

    /**
     * 转换tool call记录为main.js期望的格式
     */
    convertToToolCallFormat(toolCallRecord, nodeId) {
        // 生成并复用稳定的UI层ID，确保一次调用仅一个banner
        if (!toolCallRecord.ui_id) {
            toolCallRecord.ui_id = `tool_${toolCallRecord.tool_name}_${toolCallRecord.step_index}_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
        }
        const callId = toolCallRecord.ui_id;

        let url = null;
        let path = null;
        let descriptionOverride = null;

        // 处理搜索工具的结果，提取URL
        if (['search_baidu', 'search_google', 'tavily_search', 'image_search', 'search_wiki'].includes(toolCallRecord.tool_name)) {
            const processedResult = toolCallRecord.tool_result;
            if (processedResult && processedResult.first_url) {
                url = processedResult.first_url;
            }
        }

        // 处理网页抓取工具，提取URL
        if (['fetch_website_content', 'fetch_website_content_with_images', 'fetch_website_images_only'].includes(toolCallRecord.tool_name)) {
            const processedResult = toolCallRecord.tool_result;
            if (processedResult && processedResult.url) {
                url = processedResult.url;
            }
        }

        // 处理文件保存工具，提取路径
        if (toolCallRecord.tool_name === 'file_saver') {
            try {
                // 优先使用 processed_result.file_path（已包含完整API路径）
                const processed = toolCallRecord.tool_result;
                let filePath = null;
                
                if (processed && processed.file_path) {
                    // processed_result.file_path 已经包含完整的 API 路径前缀
                    filePath = processed.file_path;
                } else {
                    // 回退到从 tool_args 中提取
                    const args = JSON.parse(toolCallRecord.tool_args);
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
        if (toolCallRecord.tool_name === 'file_read') {
            try {
                // 优先 processed_result.file_path
                const processed = toolCallRecord.tool_result;
                let filePath = processed && processed.file_path ? processed.file_path : null;
                if (!filePath) {
                    // 回退从 tool_args 读取 { file: "..." }
                    const args = JSON.parse(toolCallRecord.tool_args || '{}');
                    filePath = args.file || args.path || null;
                }
                if (filePath) {
                    path = buildApiWorkspacePath(filePath);
                }
            } catch (e) {
                console.warn('解析文件读取工具参数失败:', e);
            }
        }

        // 处理代码执行工具，为代码内容设置特殊标识
        if (toolCallRecord.tool_name === 'execute_code') {
            try {
                const args = JSON.parse(toolCallRecord.tool_args || '{}');
                if (args.code) {
                    // 为execute_code工具设置一个特殊的path标识，表示有代码内容可查看
                    path = 'code://execute_code';
                }
            } catch (e) {
                console.warn('解析代码执行工具参数失败:', e);
            }
        }
        
        // 结果文本
        let resultText = '';
        if (toolCallRecord.status === 'running') {
            // 运行中状态的描述
            resultText = toolCallRecord.start_event?.status_text || (window.I18nService ? window.I18nService.t('running') : '正在执行中...');
        } else if (toolCallRecord.tool_result) {
            if (typeof toolCallRecord.tool_result === 'string') {
                resultText = toolCallRecord.tool_result;
            } else if (toolCallRecord.tool_result.summary) {
                resultText = toolCallRecord.tool_result.summary;
            } else {
                resultText = JSON.stringify(toolCallRecord.tool_result);
            }
        }

        // file_saver特殊处理
        if (toolCallRecord.tool_name === 'file_saver' && descriptionOverride) {
            resultText = descriptionOverride;
            descriptionOverride = '';
        }

        // 处理网页抓取类工具：从参数或结果中提取原始 website_url，用于在右侧 iframe 中直接打开
        if (['fetch_website_content', 'fetch_website_content_with_images', 'fetch_website_images_only'].includes(toolCallRecord.tool_name)) {
            try {
                // 优先从 tool_args 中解析 website_url
                if (!url && toolCallRecord.tool_args) {
                    try {
                        const args = JSON.parse(toolCallRecord.tool_args || '{}');
                        url = args.website_url || args.url || url;
                    } catch (e) {
                        console.warn('解析网页抓取工具参数失败:', e);
                    }
                }
                // 再从结构化结果中兜底提取 url（with_images / images_only 会返回 dict，包含 url 字段）
                if (!url && toolCallRecord.tool_result && typeof toolCallRecord.tool_result === 'object') {
                    url = toolCallRecord.tool_result.url || toolCallRecord.tool_result.website_url || url;
                }
            } catch (e) {
                console.warn('为网页抓取工具提取 URL 失败:', e);
            }
        }

        // 根据状态生成合适的描述
        let statusDescription = '';
        if (toolCallRecord.status === 'running') {
            statusDescription = (window.I18nService ? `${window.I18nService.t('executing')}${getToolDisplayName(toolCallRecord.tool_name)}` : `正在执行: ${getToolDisplayName(toolCallRecord.tool_name)}`);
        } else if (toolCallRecord.status === 'completed') {
            statusDescription = (window.I18nService ? `${window.I18nService.t('execution_completed')}${getToolDisplayName(toolCallRecord.tool_name)}` : `执行完成: ${getToolDisplayName(toolCallRecord.tool_name)}`);
        } else if (toolCallRecord.status === 'failed') {
            statusDescription = (window.I18nService ? `${window.I18nService.t('execution_failed')}${getToolDisplayName(toolCallRecord.tool_name)}` : `执行失败: ${getToolDisplayName(toolCallRecord.tool_name)}`);
        } else {
            statusDescription = (window.I18nService ? `${window.I18nService.t('execute_tool')}${getToolDisplayName(toolCallRecord.tool_name)}` : `执行工具: ${getToolDisplayName(toolCallRecord.tool_name)}`);
        }

        return {
            id: callId,
            nodeId: nodeId,
            duration: (toolCallRecord.duration || 0) * 1000, // 转换为毫秒
            tool: toolCallRecord.tool_name,
            toolName: getToolDisplayName(toolCallRecord.tool_name),
            description: descriptionOverride || statusDescription,
            status: toolCallRecord.status,
            startTime: Date.now() - (toolCallRecord.duration || 0) * 1000,
            endTime: toolCallRecord.status === 'running' ? null : Date.now(),
            result: resultText,
            error: toolCallRecord.status === 'failed' ? (window.I18nService ? window.I18nService.t('tool_execution_failed') : '工具执行失败') : null,
            url: url,
            path: path,
            timestamp: toolCallRecord.timestamp,
            // 为execute_code工具保留原始参数，以便显示代码内容
            tool_args: toolCallRecord.tool_args
        };
    }

    /**
     * 持久化step tool events到localStorage
     */
    persistStepToolEvents() {
        try {
            const eventsData = {};
            this.stepToolEvents.forEach((events, stepIndex) => {
                eventsData[stepIndex] = events;
            });

            localStorage.setItem('cosight:stepToolEvents', JSON.stringify({
                events: eventsData,
                savedAt: Date.now()
            }));
        } catch (e) {
            console.warn('持久化step tool events失败:', e);
        }
    }

    /**
     * 从localStorage恢复step tool events
     */
    restoreStepToolEvents() {
        try {
            const raw = localStorage.getItem('cosight:stepToolEvents');
            if (!raw) return;

            const stored = JSON.parse(raw);
            if (stored && stored.events) {
                Object.entries(stored.events).forEach(([stepIndex, events]) => {
                    this.stepToolEvents.set(parseInt(stepIndex), events);
                });
            }
        } catch (e) {
            console.warn('恢复step tool events失败:', e);
        }
    }

    /**
     * 获取指定step的tool events
     */
    getStepToolEvents(stepIndex) {
        return this.stepToolEvents.get(stepIndex) || [];
    }

    /**
     * 清理step tool events
     */
    clearStepToolEvents() {
        this.stepToolEvents.clear();
        this.pendingToolStarts.clear();
        try {
            localStorage.removeItem('cosight:stepToolEvents');
        } catch (e) {
            console.warn('清理step tool events失败:', e);
        }
    }

    /**
     * 自动关闭已完成步骤的面板（前提：该步骤无运行中工具调用）
     */
    _autoCloseCompletedStepPanels(initData) {
        try {
            const stepStatuses = initData?.step_statuses || {};
            const steps = initData?.steps || [];
            if (!steps.length) return;

            steps.forEach((stepName, index) => {
                const status = stepStatuses[stepName];
                // 仅处理标记为 completed 的步骤
                if (status === 'completed') {
                    const stepIndex = index; // steps 为0基
                    // 确认该step无运行中的工具调用
                    const hasRunning = this._hasRunningTools(stepIndex);
                    if (!hasRunning) {
                        const nodeId = stepIndex + 1; // DAG节点从1开始
                        try {
                            if (typeof closeNodeToolPanel === 'function') {
                                closeNodeToolPanel(nodeId);
                            }
                        } catch (_) {}
                    }
                }
            });
        } catch (e) {
            console.warn('_autoCloseCompletedStepPanels error:', e);
        }
    }

    /**
     * 判断指定step是否存在运行中的工具调用
     */
    _hasRunningTools(stepIndex) {
        try {
            const events = this.getStepToolEvents(stepIndex) || [];
            // 只要存在状态为running的记录或挂起的start事件，则认为仍在运行
            if (events.some(rec => rec?.status === 'running')) return true;
            const pending = this.pendingToolStarts?.get(stepIndex) || [];
            if (pending.length > 0) return true;
        } catch (_) {}
        return false;
    }

    sendMessage(content) {
        console.log('MessageService.sendMessage >>>>>>>>>>>>>> ', content);
        // 新消息发送前清理之前的tool events和历史数据
        this.clearStepToolEvents();

        // 清理历史的planId和pending请求
        try {
            localStorage.removeItem('cosight:planIdByTopic');
            localStorage.removeItem('cosight:pendingRequests');
            console.log('清理历史localStorage数据cosight:planIdByTopic, cosight:pendingRequests');
        } catch (e) {
            console.warn('清理历史localStorage数据失败:', e);
        }
        const topic = WebSocketService.generateUUID();
        WebSocketService.subscribe(topic, this.receiveMessage.bind(this));

        // 生成并复用稳定的 planId 作为 messageSerialNumber
        const planId = this.ensurePlanIdForTopic(topic);

        const message = {
            uuid: WebSocketService.generateUUID(),
            type: "multi-modal",
            from: "human",
            timestamp: Date.now(),
            initData: [{type: "text", value: content}],
            roleInfo: {name: "admin"},
            mentions: [],
            extra: {
                fromBackEnd: {
                    actualPrompt: JSON.stringify({deepResearchEnabled: true})
                }
            },
            // 会被服务端解析的会话信息
            sessionInfo: {
                messageSerialNumber: planId
            }
        }
        // 记录pending请求，便于刷新后重发
        try {
            const pendingRaw = localStorage.getItem('cosight:pendingRequests');
            const pendings = pendingRaw ? JSON.parse(pendingRaw) : {};
            pendings[topic] = { message, savedAt: Date.now(), stillPending: true };
            localStorage.setItem('cosight:pendingRequests', JSON.stringify(pendings));
            console.log('store pendingRequests',JSON.stringify(pendings));
        } catch (e) {
            console.warn('保存pending失败:', e);
        }
        WebSocketService.sendMessage(topic, JSON.stringify(message));
    }

    /**
     * 发送回放请求
     * @param {string} workspacePath - 工作区路径，如 'work_space/work_space_20251010_161223_071211'
     * @param {string} replayPlanId - 可选的planId
     */
    sendReplay(workspacePath, replayPlanId) {
        try {
            console.log('sendReplay 被调用，参数:', { workspacePath, replayPlanId });
            
            // 解析 workspace
            let replayWorkspace = null;
            
            // 1) 优先使用传入的参数
            if (workspacePath && typeof workspacePath === 'string' && workspacePath.trim().length > 0) {
                replayWorkspace = workspacePath.trim();
                console.log('使用传入的工作区路径:', replayWorkspace);
            }
            
            // 2) 回退逻辑
            try {
                if (!replayWorkspace) {
                    // 尝试从 localStorage 读取
                    const wsRaw = localStorage.getItem('cosight:workspace');
                    if (wsRaw && typeof wsRaw === 'string' && wsRaw.trim().length > 0) {
                        replayWorkspace = wsRaw.trim();
                        console.log('从 localStorage 获取工作区路径:', replayWorkspace);
                    }
                }
                // 2) 回退到从 lastManusStep 推断
                if (!replayWorkspace) {
                    const lastStepRaw = localStorage.getItem('cosight:lastManusStep');
                    if (lastStepRaw) {
                        const lastStep = JSON.parse(lastStepRaw);
                        const initData = lastStep?.message?.data?.initData;
                        const stepFiles = initData?.step_files || {};
                        // 取第一个有 path 的文件，解析其工作空间前缀
                        outer: for (const key of Object.keys(stepFiles)) {
                            const arr = stepFiles[key];
                            if (Array.isArray(arr) && arr.length > 0) {
                                for (const item of arr) {
                                    const p = item?.path;
                                    if (typeof p === 'string') {
                                        // 示例: work_space_20250926_194936_689374/xxx/yyy
                                        const idx = p.indexOf('/');
                                        replayWorkspace = idx > 0 ? p.slice(0, idx) : p;
                                        break outer;
                                    }
                                }
                            }
                        }
                    }
                }
            } catch (e) {
                console.warn('解析workspace失败:', e);
            }

            // 解析 planId
            // 1) 优先使用传入的参数
            if (!replayPlanId || typeof replayPlanId !== 'string' || replayPlanId.trim().length === 0) {
                // 2) 尝试从 localStorage 获取
                try {
                    const planRaw = localStorage.getItem('cosight:planIdByTopic');
                    if (planRaw) {
                        const map = JSON.parse(planRaw);
                        const entries = Object.entries(map);
                        if (entries.length > 0) {
                            // 取最后一个
                            replayPlanId = entries[entries.length - 1][1];
                            console.log('从 localStorage 获取 planId:', replayPlanId);
                        }
                    }
                } catch (e) {
                    console.warn('解析planId失败:', e);
                }
            } else {
                console.log('使用传入的 planId:', replayPlanId);
            }

            // planId 是可选的，不强制要求
            if (!replayPlanId) {
                console.log('未找到 planId，将生成新的');
                replayPlanId = WebSocketService.generateUUID();
            }
            
            if (!replayWorkspace) {
                alert('未找到可用的 workspace，无法回放');
                console.error('replayWorkspace 为空');
                return;
            }
            
            console.log('最终使用的回放参数:', { replayWorkspace, replayPlanId });

            // 生成新的 topic 用于订阅这次回放
            const topic = WebSocketService.generateUUID();
            WebSocketService.subscribe(topic, this.receiveMessage.bind(this));

            const message = {
                uuid: WebSocketService.generateUUID(),
                type: 'multi-modal',
                from: 'human',
                timestamp: Date.now(),
                initData: [{ type: 'text', value: '[Replay] 请求回放' }],
                roleInfo: { name: 'admin' },
                mentions: [],
                extra: {
                    // 两处都放置以兼容服务端提取逻辑
                    replay: true,
                    replayWorkspace: replayWorkspace,
                    replayPlanId: replayPlanId,
                    fromBackEnd: {
                        actualPrompt: JSON.stringify({ deepResearchEnabled: true }),
                        replay: true,
                        replayWorkspace: replayWorkspace,
                        replayPlanId: replayPlanId
                    }
                },
                sessionInfo: {
                    // 提示服务端不要生成新的 planId
                    messageSerialNumber: replayPlanId
                }
            };

            // 记录为 pending（便于刷新后恢复订阅）
            try {
                const pendingRaw = localStorage.getItem('cosight:pendingRequests');
                const pendings = pendingRaw ? JSON.parse(pendingRaw) : {};
                pendings[topic] = { message, savedAt: Date.now(), stillPending: true };
                localStorage.setItem('cosight:pendingRequests', JSON.stringify(pendings));
            } catch (e) {
                console.warn('保存回放pending失败:', e);
            }

            WebSocketService.sendMessage(topic, JSON.stringify(message));
        } catch (e) {
            console.error('发送回放请求失败:', e);
        }
    }
}

// 创建全局实例
window.messageService = new MessageService();

// 导出类（如果使用模块化）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MessageService;
}
