// DAG图相关功能模块
// 包含DAG图的初始化、布局计算、节点绘制、拖拽、响应式处理等功能

// DAG图全局变量
let svg, width, height, simulation;
let tooltip = null; // 延迟初始化，等待DOM加载
let zoom = null; // 缩放功能

// 确保tooltip已初始化
function ensureTooltipInitialized() {
    if (!tooltip) {
        tooltip = d3.select("#tooltip");
    }
}

// 计算层次化布局
function calculateHierarchicalLayout() {
    const nodes = dagData.nodes;
    const edges = dagData.edges;

    // 创建邻接表
    const graph = {};
    const inDegree = {};

    // 初始化
    nodes.forEach(node => {
        graph[node.id] = [];
        inDegree[node.id] = 0;
    });

    // 构建图
    edges.forEach(edge => {
        // D3力导向图会把id替换为node对象，这里做兼容处理
        const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
        const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;

        if (graph[sourceId] && inDegree[targetId] !== undefined) {
            graph[sourceId].push(targetId);
            inDegree[targetId]++;
        }
    });

    // 拓扑排序，确定层级
    const levels = [];
    const queue = [];
    const visited = new Set();

    // 找到所有入度为0的节点（起始节点）
    nodes.forEach(node => {
        if (inDegree[node.id] === 0) {
            queue.push(node.id);
        }
    });

    console.log('入度统计:', inDegree);
    console.log('起始节点:', queue.slice());

    // 层次化遍历
    while (queue.length > 0) {
        const levelSize = queue.length;
        const currentLevel = [];

        for (let i = 0; i < levelSize; i++) {
            const nodeId = queue.shift();
            if (visited.has(nodeId)) continue;

            visited.add(nodeId);
            currentLevel.push(nodeId);

            // 添加下一层节点
            if (graph[nodeId]) { // 增加保护，防止因数据问题出错
                graph[nodeId].forEach(neighbor => {
                    inDegree[neighbor]--;
                    if (inDegree[neighbor] === 0 && !visited.has(neighbor)) {
                        queue.push(neighbor);
                    }
                });
            }
        }

        if (currentLevel.length > 0) {
            // 在每个层级内按节点ID排序，确保从左到右的顺序正确
            currentLevel.sort((a, b) => a - b);
            levels.push(currentLevel);
        }
    }

    console.log('层级分配:', levels);

    // 计算位置 - 动态调整间距以适应容器大小
    const nodePositions = {};

    // 检测是否处于分屏模式
    const rightContainer = document.getElementById('right-container');
    const isHalfScreen = rightContainer && rightContainer.classList.contains('show');

    // 计算最大层级节点数和总节点数
    const maxNodesInLevel = Math.max(...levels.map(level => level.length));
    const totalNodes = nodes.length;
    const totalLevels = levels.length;

    // 动态计算间距参数
    const minNodeSpacing = 80;  // 最小节点间距
    const minLevelWidth = 150;  // 最小层级间距
    const padding = 50;         // 上下边距
    const horizontalPadding = 200; // 左右边距

    // 根据容器大小和节点数量动态调整垂直间距
    const availableHeight = height - (2 * padding);
    const dynamicNodeSpacing = Math.max(
        minNodeSpacing,
        availableHeight / Math.max(maxNodesInLevel, 1)
    );

    // 根据容器大小和层级数量动态调整水平间距
    const availableWidth = width - (2 * horizontalPadding);
    const dynamicLevelWidth = Math.max(
        minLevelWidth,
        availableWidth / Math.max(totalLevels - 1, 1)
    );

    // 分屏模式下的额外调整
    const levelWidth = isHalfScreen ? dynamicLevelWidth * 0.6 : dynamicLevelWidth;
    const nodeSpacing = isHalfScreen ? dynamicNodeSpacing * 1.2 : dynamicNodeSpacing;

    // 计算总宽度和起始位置，使整个DAG居中
    const totalWidth = (levels.length - 1) * levelWidth;
    const startX = Math.max(horizontalPadding, (width - totalWidth) / 2);

    levels.forEach((level, levelIndex) => {
        const levelX = startX + levelIndex * levelWidth;
        const levelHeight = (level.length - 1) * nodeSpacing;
        const startY = Math.max(padding, (height / 2) - (levelHeight / 2));

        level.forEach((nodeId, nodeIndex) => {
            const y = startY + nodeIndex * nodeSpacing;
            nodePositions[nodeId] = {x: levelX, y: y};
        });
    });

    return nodePositions;
}

// 初始化DAG可视化
function initDAG() {
    // 确保tooltip已初始化
    ensureTooltipInitialized();
    
    const container = d3.select("#dag-svg");
    width = container.node().clientWidth;
    height = container.node().clientHeight;

    svg = container
        .attr("width", width)
        .attr("height", height);

    // 创建缩放功能
    zoom = d3.zoom()
        .scaleExtent([0.1, 4]) // 缩放范围：0.1x 到 4x
        .on("zoom", function (event) {
            // 应用缩放变换到主图形组
            mainGroup.attr("transform", event.transform);
        })
        .on("start", function (event) {
            // 拖动开始时改变鼠标样式
            d3.select("#dag-svg").style("cursor", "move");
        })
        .on("end", function (event) {
            // 拖动结束时恢复默认鼠标样式
            d3.select("#dag-svg").style("cursor", "default");
        });

    // 应用缩放功能到SVG
    svg.call(zoom);

    // 计算固定的层次化布局
    const nodePositions = calculateHierarchicalLayout();

    // 将位置信息添加到节点数据中
    dagData.nodes.forEach(node => {
        const pos = nodePositions[node.id];
        node.fx = pos.x; // 固定x位置
        node.fy = pos.y; // 固定y位置
    });

    // 创建力导向图模拟（仅用于拖拽功能，不用于自动布局）
    simulation = d3.forceSimulation(dagData.nodes)
        .force("link", d3.forceLink(dagData.edges).id(d => d.id).distance(150))
        .force("charge", d3.forceManyBody().strength(0)) // 关闭排斥力
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(40));

    // 创建主图形组，用于缩放和平移
    const mainGroup = svg.append("g");

    // 定义箭头标记
    svg.append("defs").append("marker")
        .attr("id", "arrowhead")
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 35) // 调整箭头位置，避免与节点重叠
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", "#FF9800");

    // 绘制边
    const link = mainGroup.append("g")
        .selectAll("line")
        .data(dagData.edges)
        .enter().append("line")
        .attr("class", d => `edge ${d.type}`)
        .attr("stroke-width", 3)
        .attr("stroke", "#FF9800")
        .attr("stroke-dasharray", "5,5")
        .attr("marker-end", "url(#arrowhead)");

    // 绘制节点
    const node = mainGroup.append("g")
        .selectAll("g")
        .data(dagData.nodes)
        .enter().append("g")
        .attr("class", "node")
        .attr("transform", d => `translate(${d.fx}, ${d.fy})`);

    // 添加节点圆圈
    node.append("circle")
        .attr("class", d => `node-circle ${d.status}`)
        .attr("r", 25)
        .on("mouseenter", function (event, d) {
            // 阻止事件冒泡，避免与拖拽冲突
            event.stopPropagation();
            showTooltip(event, d, true);
        })
        .on("mouseleave", function (event, d) {
            event.stopPropagation();
            hideTooltip();
        })
        .on("click", function (event, d) {
            event.stopPropagation();
            showStepDetails(event, d);

            // 切换节点工具面板的显示状态，使用完整的标题信息
            const panelTitle = `Step ${d.id} - ${d.title}`;
            const panelOpened = toggleNodeToolPanel(d.id, panelTitle);

            // 只有在面板被打开时才添加工具调用
            if (panelOpened) {
                // 根据节点ID获取对应的工作流程数据
                const workflow = getWorkflowByNodeId(d.id);
                if (workflow && workflow.tools) {
                    // 显示该步骤的所有工具调用
                    workflow.tools.forEach((tool, index) => {
                        addToolCallToNodePanel(d.id, tool);
                    });
                } else {
                    // 如果没有找到对应的工作流程，使用默认的工具映射
                    const tool = nodeToolMappings[d.id];
                    if (tool) {
                        addToolCallToNodePanel(d.id, tool);
                    }
                }
            }
        });

    // 添加节点文本
    node.append("text")
        .attr("class", "node-text")
        .text(d => d.name);

    // 添加状态图标
    node.append("text")
        .attr("class", "status-icon")
        .attr("x", 0)
        .attr("y", 35)
        .attr("text-anchor", "middle")
        .attr("font-size", "12px")
        .attr("fill", "#666")
        .text(d => getStatusIcon(d.status));

    // 更新位置
    simulation.on("tick", () => {
        // 更新边的位置 - 处理D3力导向图的对象引用
        link
            .attr("x1", d => {
                // D3会将source转换为节点对象，如果还是ID则按ID查找
                const sourceNode = typeof d.source === 'object' ? d.source : dagData.nodes.find(n => n.id === d.source);
                return sourceNode ? sourceNode.fx : 0;
            })
            .attr("y1", d => {
                const sourceNode = typeof d.source === 'object' ? d.source : dagData.nodes.find(n => n.id === d.source);
                return sourceNode ? sourceNode.fy : 0;
            })
            .attr("x2", d => {
                const targetNode = typeof d.target === 'object' ? d.target : dagData.nodes.find(n => n.id === d.target);
                return targetNode ? targetNode.fx : 0;
            })
            .attr("y2", d => {
                const targetNode = typeof d.target === 'object' ? d.target : dagData.nodes.find(n => n.id === d.target);
                return targetNode ? targetNode.fy : 0;
            });

        // 更新所有工具面板的位置
        updateAllPanelPositions();
    });

    // 添加指示器
    dagData.nodes.forEach(node => credibilityService.addNodeIndicators(node.id));

    updateProgress();
}

// 显示步骤详情
function showStepDetails(event, d) {
    document.getElementById("step-title").textContent = d.title;
    document.getElementById("step-description").textContent = d.description;

    // 高亮相关节点
    highlightRelatedNodes(d);
}

// 高亮相关节点
function highlightRelatedNodes(selectedNode) {
    const relatedNodeIds = new Set();
    relatedNodeIds.add(selectedNode.id);

    // 添加依赖节点
    dagData.edges.forEach(edge => {
        if (edge.target === selectedNode.id) {
            relatedNodeIds.add(edge.source);
        }
        if (edge.source === selectedNode.id) {
            relatedNodeIds.add(edge.target);
        }
    });

    // 更新节点样式
    svg.selectAll(".node")
        .select("circle")
        .style("opacity", d => relatedNodeIds.has(d.id) ? 1 : 0.3)
        .style("stroke-width", d => d.id === selectedNode.id ? 5 : 3);
}

// 重置高亮
function resetHighlight() {
    svg.selectAll(".node")
        .select("circle")
        .style("opacity", 1)
        .style("stroke-width", 3);
}

// 更新进度统计
function updateProgress() {
    const stats = {
        completed: 0,
        "in_progress": 0,
        blocked: 0,
        "not_started": 0
    };

    dagData.nodes.forEach(node => {
        stats[node.status]++;
    });

    // 更新统计数字
    document.getElementById("completed-count").textContent = stats.completed;
    document.getElementById("in-progress-count").textContent = stats["in_progress"];
    document.getElementById("blocked-count").textContent = stats.blocked;
    document.getElementById("not-started-count").textContent = stats["not_started"];

    // 更新进度条
    const total = dagData.nodes.length;
    const completed = stats.completed;
    const percentage = (completed / total) * 100;

    document.getElementById("progress-fill").style.width = percentage + "%";
    document.getElementById("progress-percentage").textContent = Math.round(percentage) + "%";

    // 更新节点状态
    updateNodeStatus();

    // 更新步骤执行总览
    updateStepProgressOverview();
}

// 更新步骤执行总览
function updateStepProgressOverview() {
    const completedList = document.getElementById('completed-steps');
    const inProgressList = document.getElementById('in-progress-steps');
    const blockedList = document.getElementById('blocked-steps');
    const notStartedList = document.getElementById('not-started-steps');

    // 清空现有列表
    completedList.innerHTML = '';
    inProgressList.innerHTML = '';
    blockedList.innerHTML = '';
    notStartedList.innerHTML = '';

    dagData.nodes.forEach(node => {
        const stepItem = document.createElement('div');
        stepItem.className = 'step-item';
        stepItem.textContent = node.name;

        // 添加事件监听器以显示自定义工具提示
        stepItem.addEventListener('mouseenter', (event) => {
            // 复用 script.js 中的 showTooltip 函数
            showTooltip(event, node, false);
        });

        stepItem.addEventListener('mouseleave', () => {
            // 复用 script.js 中的 hideTooltip 函数
            hideTooltip();
        });

        switch (node.status) {
            case 'completed':
                completedList.appendChild(stepItem);
                break;
            case 'in_progress':
                inProgressList.appendChild(stepItem);
                break;
            case 'blocked':
                blockedList.appendChild(stepItem);
                break;
            case 'not_started':
                notStartedList.appendChild(stepItem);
                break;
        }
    });
}

// 更新节点状态显示
function updateNodeStatus() {
    svg.selectAll(".node")
        .select("circle")
        .attr("class", d => `node-circle ${d.status}`);

    svg.selectAll(".status-icon")
        .text(d => getStatusIcon(d.status));
}

// 响应式处理
function handleResize() {
    if (!svg) {
        return;
    }

    // 使用父容器 .dag-container 来获取稳定的宽度，而不是SVG本身
    const dagContainer = document.querySelector('.dag-container');
    if (!dagContainer) return;

    const svgNode = document.getElementById('dag-svg');
    if (!svgNode) return;

    // 直接从SVG元素获取其当前的实际尺寸
    width = svgNode.clientWidth;
    height = svgNode.clientHeight;

    // 如果宽度或高度无效，则延迟再试一次，以避免动画过程中的中间状态
    if (width <= 0 || height <= 0) {
        setTimeout(handleResize, 50);
        return;
    }

    svg.attr("width", width).attr("height", height);

    // 重新计算层次化布局
    const nodePositions = calculateHierarchicalLayout();

    // 更新节点数据和固定位置
    dagData.nodes.forEach(node => {
        const pos = nodePositions[node.id];
        node.x = pos.x;
        node.y = pos.y;
        node.fx = pos.x; // 强制更新固定位置
        node.fy = pos.y;
    });

    // 重新绑定节点数据到模拟
    simulation.nodes(dagData.nodes);

    // 直接更新节点和边的视觉位置，以获得即时响应
    svg.selectAll(".node")
        .transition().duration(300) // 添加平滑过渡
        .attr("transform", d => `translate(${d.fx}, ${d.fy})`);

    svg.selectAll(".edge")
        .transition().duration(300) // 添加平滑过渡
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

    // 更新力导向模拟的中心并重启
    simulation.force("center", d3.forceCenter(width / 2, height / 2));
    simulation.alpha(0.5).restart();

    // 更新所有面板位置
    updateAllPanelPositions();
}

// 添加节点指示器
function addNodeIndicator(nodeElement, nodeId, groupClass, transform, fillColor, fillText) {
    const indicatorGroup = nodeElement.append("g")
        .attr("class", groupClass)
        .attr("transform", transform);

    // 状态圆圈 - 创建时不添加点击事件
    indicatorGroup.append("circle")
        .attr("r", 10)
        .attr("class", "action-circle")
        .attr("cx", 0)
        .attr("cy", 0)
        .style("cursor", "not-allowed")
        .style("fill", fillColor)
        .style("stroke", "#fff")
        .style("stroke-width", "2px");

    indicatorGroup.append("text")
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "central")
        .attr("font-size", "6px")
        .attr("fill", "white")
        .attr("x", 0)
        .attr("y", 0)
        .html(fillText);
}

// 创建DAG图 - 处理从后端推送的 lui-message-manus-step 消息
function createDag(messageData) {
    try {
        // 解析消息数据 - 根据实际数据结构调整
        // 支持多种数据格式：
        // 1. messageData.data.content (WebSocket封装后的格式)
        // 2. messageData.content (直接格式)
        // 3. messageData.data.initData (旧格式兼容)
        const initData = messageData.data?.content || messageData.content || messageData.data?.initData;
        
        // 调试日志：检查传入的数据结构
        console.log('=============== createDag 开始 ===============');
        console.log('1. 原始 messageData:', JSON.stringify(messageData, null, 2));
        console.log('2. messageData.data 存在:', !!messageData.data);
        console.log('3. messageData.data?.content 存在:', !!messageData.data?.content);
        console.log('4. messageData.data?.content:', messageData.data?.content);
        console.log('5. messageData.content 存在:', !!messageData.content);
        console.log('6. messageData.content:', messageData.content);
        console.log('7. messageData.data?.initData 存在:', !!messageData.data?.initData);
        console.log('8. 最终获取的 initData:', initData);
        console.log('9. initData?.step_notes 存在:', !!initData?.step_notes);
        console.log('10. initData?.step_notes:', initData?.step_notes);
        console.log('11. initData?.steps:', initData?.steps);
        console.log('12. initData?.step_statuses:', initData?.step_statuses);
        console.log('============================================');
        
        // 新会话检测：当 changeType=replace 或 话题/uuid 变化时，重置缓存
        // try {
        //     const changeType = messageData.data && messageData.data.changeType;
        //     const topic = messageData.topic || (messageData.data && messageData.data.topic);
        //     const uuid = messageData.data && messageData.data.uuid;

        //     // 从 localStorage 读上一次记录的会话标识
        //     const lastKey = 'cosight:lastSessionKey';
        //     const currentKey = `${topic || ''}__${uuid || ''}`;
        //     const lastSessionKey = localStorage.getItem(lastKey);

        //     const isNewSession = changeType === 'replace' || 
        //         (currentKey && lastSessionKey !== currentKey && topic !== 'restored');

        //     if (isNewSession && typeof window !== 'undefined' && typeof window.resetSessionCaches === 'function') {
        //         window.resetSessionCaches();
        //         // 记录本次会话标识
        //         localStorage.setItem(lastKey, currentKey);
        //     }
        // } catch (e) {
        //     console.warn('新会话检测失败，跳过缓存重置:', e);
        // }

        // 当 steps 为空或未提供时，不绘制且静默返回；允许 dependencies 缺省
        if (!initData || !Array.isArray(initData.steps) || initData.steps.length === 0) {
            if (svg) {
                svg.selectAll("*").remove();
            }
            dagData.nodes = [];
            dagData.edges = [];
            return true;
        }
        if (!initData.dependencies || typeof initData.dependencies !== 'object') {
            initData.dependencies = {};
        }

        // 分析dependencies的索引基准
        const depKeys = Object.keys(initData.dependencies || {}).map(k => parseInt(k)).filter(n => Number.isInteger(n));
        const depValues = [];
        Object.values(initData.dependencies || {}).forEach(arr => {
            if (Array.isArray(arr)) {
                arr.forEach(v => depValues.push(parseInt(v)));
            }
        });
        
        const minKey = depKeys.length ? Math.min(...depKeys) : 1;
        const minVal = depValues.length ? Math.min(...depValues.filter(Number.isInteger)) : 1;
        const isKeyZeroBased = minKey === 0;
        const isValZeroBased = minVal === 0;
        
        // 构建节点数据
        const nodes = initData.steps.map((step, index) => {
            const stepId = index + 1; // 步骤ID始终是1-based
            
            // 查找这个步骤的依赖关系
            let dependencies = [];
            
            // 遍历dependencies，找到以当前步骤为目标的依赖关系
            Object.keys(initData.dependencies || {}).forEach(targetKey => {
                const targetIndex = parseInt(targetKey);
                // 目标ID：若键或值任一为0基，则+1；否则保持不变（1基）
                const actualTargetId = (isKeyZeroBased || isValZeroBased) ? targetIndex + 1 : targetIndex;
                
                if (actualTargetId === stepId) {
                    // 找到了以当前步骤为目标的依赖
                    const sourceDeps = initData.dependencies[targetKey];
                    if (Array.isArray(sourceDeps)) {
                        sourceDeps.forEach(sourceIndex => {
                            // 值的基准：若为0基则+1；若为1基则保持不变
                            const sourceIdRaw = isValZeroBased ? (parseInt(sourceIndex) + 1) : parseInt(sourceIndex);
                            const maxIndexLocal = initData.steps.length;
                            // 过滤：丢弃无效索引和自依赖
                            if (!Number.isInteger(sourceIdRaw)) return;
                            if (sourceIdRaw < 1 || sourceIdRaw > maxIndexLocal) return;
                            if (sourceIdRaw === stepId) return;
                            dependencies.push(sourceIdRaw);
                        });
                    }
                }
            });
            
            console.log(`步骤${stepId}的依赖:`, dependencies);
            
            // 详细调试日志
            console.log(`======= 构建节点 ${stepId} (${step}) =======`);
            console.log('  步骤名称 (step):', step);
            console.log('  initData 对象:', initData);
            console.log('  initData.step_notes 存在:', !!initData.step_notes);
            console.log('  initData.step_notes 类型:', typeof initData.step_notes);
            console.log('  initData.step_notes 内容:', initData.step_notes);
            console.log('  initData.step_notes 的所有键:', initData.step_notes ? Object.keys(initData.step_notes) : 'N/A');
            console.log('  initData.step_notes[step] 值:', initData.step_notes ? initData.step_notes[step] : 'N/A');
            console.log('  initData.step_statuses[step] 值:', initData.step_statuses ? initData.step_statuses[step] : 'N/A');
            
            const stepNotesValue = initData.step_notes ? (initData.step_notes[step] || "") : "";
            console.log('  计算出的 stepNotesValue:', stepNotesValue);
            
            const nodeData = {
                id: stepId,
                name: `step${stepId}`,
                fullName: step,  // 保留完整名称用于其他用途
                status: initData.step_statuses[step] || "not_started",
                step_notes: stepNotesValue,
                dependencies: dependencies
            };
            
            console.log('  最终节点数据:', nodeData);
            console.log('  最终节点 step_notes 值:', nodeData.step_notes);
            console.log('  最终节点 step_notes 长度:', nodeData.step_notes ? nodeData.step_notes.length : 0);
            console.log('======================================');
            
            return nodeData;
        });

        // 构建边数据
        const edges = [];
        // 使用节点的dependencies属性构建边（此时已标准化为1基并过滤自环/越界）
        nodes.forEach(node => {
            const dependencies = node.dependencies;
            if (Array.isArray(dependencies) && dependencies.length > 0) {
                dependencies.forEach(src => {
                    // 此处 src 与 node.id 均为 1 基且有效，且非自环
                    edges.push({
                        source: src,
                        target: node.id,
                        type: "dependency"
                    });
                });
            }
        });

        // 创建新的DAG数据结构
        const newDagData = {
            nodes: nodes,
            edges: edges
        };

        console.log('构建的节点数据:', nodes);
        console.log('构建的边数据:', edges);

        // 更新全局DAG数据
        dagData.nodes = newDagData.nodes;
        dagData.edges = newDagData.edges;
        
        // 强制确保step_notes字段存在
        dagData.nodes.forEach(node => {
            if (!node.hasOwnProperty('step_notes')) {
                node.step_notes = "";
                console.log(`为节点 ${node.id} 添加缺失的step_notes字段`);
            }
        });

        // 清空现有的SVG内容
        if (svg) {
            svg.selectAll("*").remove();
        }

        // 重新初始化DAG
        initDAG();

        // 更新进度信息
        if (initData.progress) {
            updateProgressFromData(initData.progress);
        }

        return true
    } catch (error) {
        console.error('创建DAG图时发生错误:', error);
        return false;
    }
}

// 根据后端数据更新进度信息
function updateProgressFromData(progressData) {
    if (!progressData) return;

    // 更新统计数字
    const completedCount = document.getElementById("completed-count");
    const inProgressCount = document.getElementById("in-progress-count");
    const blockedCount = document.getElementById("blocked-count");
    const notStartedCount = document.getElementById("not-started-count");

    if (completedCount) completedCount.textContent = progressData.completed || 0;
    if (inProgressCount) inProgressCount.textContent = progressData.in_progress || 0;
    if (blockedCount) blockedCount.textContent = progressData.blocked || 0;
    if (notStartedCount) notStartedCount.textContent = progressData.not_started || 0;

    // 更新进度条
    const total = progressData.total || 0;
    const completed = progressData.completed || 0;
    const percentage = total > 0 ? (completed / total) * 100 : 0;

    const progressFill = document.getElementById("progress-fill");
    const progressPercentage = document.getElementById("progress-percentage");

    if (progressFill) progressFill.style.width = percentage + "%";
    if (progressPercentage) progressPercentage.textContent = Math.round(percentage) + "%";
}

// 导出DAG相关函数（如果使用模块化）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        initDAG,
        createDag,
        calculateHierarchicalLayout,
        showStepDetails,
        highlightRelatedNodes,
        resetHighlight,
        updateProgress,
        updateNodeStatus,
        handleResize,
        addNodeIndicator,
        updateProgressFromData
    };
}
