// 模拟进度推进
function simulateProgress() {
    const steps = progressSteps;

    let currentStep = 0;
    const interval = setInterval(() => {
        if (currentStep < steps.length) {
            const step = steps[currentStep];
            const node = dagData.nodes.find(n => n.id === step.nodeId);
            if (node) {
                node.status = step.status;
                updateProgress();

                // 添加动画效果
                const nodeElement = svg.selectAll(".node")
                    .filter(d => d.id === step.nodeId);

                nodeElement.select("circle")
                    .transition()
                    .duration(300)
                    .attr("r", 30)
                    .transition()
                    .duration(300)
                    .attr("r", 25);
            }
            currentStep++;
        } else {
            clearInterval(interval);
        }
    }, 1000);
}

// 重置进度
function resetProgress() {
    dagData.nodes.forEach(node => {
        node.status = "not_started";
    });
    updateProgress();
    resetHighlight();
}

// 测试布局优化效果
function testLayoutOptimization() {
    console.log('测试布局优化效果');

    // 创建包含更多节点的测试数据
    const testMessageData = {
        "topic": "test-topic",
        "data": {
            "type": "lui-message-manus-step",
            "uuid": "test-uuid",
            "timestamp": Date.now(),
            "from": "ai",
            "changeType": "replace",
            "initData": {
                "title": "测试任务：复杂DAG布局优化",
                "steps": [
                    "步骤1：数据收集和预处理",
                    "步骤2：数据清洗和验证",
                    "步骤3：特征工程和选择",
                    "步骤4：模型训练和验证",
                    "步骤5：模型评估和调优",
                    "步骤6：结果分析和解释",
                    "步骤7：报告生成和可视化",
                    "步骤8：部署和监控",
                    "步骤9：性能优化",
                    "步骤10：用户反馈收集",
                    "步骤11：系统维护和更新",
                    "步骤12：文档更新和培训",
                    "步骤13：质量保证和测试",
                    "步骤14：风险评估和管理",
                    "步骤15：项目总结和归档"
                ],
                "step_files": {},
                "step_statuses": {},
                "step_notes": {},
                "step_details": {},
                "dependencies": {
                    "2": [1],
                    "3": [2],
                    "4": [3],
                    "5": [4],
                    "6": [5],
                    "7": [6],
                    "8": [7],
                    "9": [8],
                    "10": [9],
                    "11": [10],
                    "12": [11],
                    "13": [12],
                    "14": [13],
                    "15": [14]
                },
                "progress": {
                    "total": 15,
                    "completed": 0,
                    "in_progress": 0,
                    "blocked": 0,
                    "not_started": 15
                },
                "result": "",
                "status_text": "正在执行中"
            }
        }
    };

    // 调用 createDag 方法
    createDag(testMessageData);

    // 自动适应屏幕
    setTimeout(() => {
        fitToScreen();
    }, 500);

    console.log('布局优化测试完成，请查看DAG图是否适应屏幕大小');
}

// 适应屏幕大小
function fitToScreen() {
    if (!svg || !dagData.nodes.length) return;

    // 计算所有节点的边界框
    const nodes = dagData.nodes;
    const padding = 50; // 上下边距
    const horizontalPadding = 200; // 左右边距

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    nodes.forEach(node => {
        if (node.fx !== undefined && node.fy !== undefined) {
            minX = Math.min(minX, node.fx);
            minY = Math.min(minY, node.fy);
            maxX = Math.max(maxX, node.fx);
            maxY = Math.max(maxY, node.fy);
        }
    });

    // 添加节点半径
    const nodeRadius = 25;
    minX -= nodeRadius;
    minY -= nodeRadius;
    maxX += nodeRadius;
    maxY += nodeRadius;

    // 计算缩放比例
    const graphWidth = maxX - minX;
    const graphHeight = maxY - minY;
    const scaleX = (width - 2 * horizontalPadding) / graphWidth;
    const scaleY = (height - 2 * padding) / graphHeight;
    const scale = Math.min(scaleX, scaleY, 1); // 不超过原始大小

    // 计算居中位置
    const centerX = (width - graphWidth * scale) / 2 - minX * scale;
    const centerY = (height - graphHeight * scale) / 2 - minY * scale;

    // 应用变换
    const transform = d3.zoomIdentity
        .translate(centerX, centerY)
        .scale(scale);

    svg.transition().duration(750).call(
        zoom.transform,
        transform
    );
}

// 测试函数 - 用于验证 createDag 方法
function testCreateDag() {
    console.log('开始测试 createDag 方法');

    // 模拟从后端收到的消息数据
    const testMessageData = {
        "topic": "test-topic",
        "data": {
            "type": "lui-message-manus-step",
            "uuid": "test-uuid",
            "timestamp": Date.now(),
            "from": "ai",
            "changeType": "replace",
            "initData": {
                "title": "测试任务：2025年江苏足球联赛球队表现分析与成绩预测报告",
                "steps": [
                    "收集2025年江苏足球联赛基本信息（参赛球队、赛制、赛程等）",
                    "收集各球队历史表现数据和球员阵容信息",
                    "分析各球队近期比赛表现和技术统计数据",
                    "评估各球队的战术特点和比赛风格",
                    "识别各球队的强项和弱项",
                    "分析球队之间的对战记录和相互克制关系",
                    "建立预测模型并输入相关数据",
                    "进行模拟预测并生成初步排名预测",
                    "验证预测结果的合理性并进行调整",
                    "撰写完整的分析报告包含详细分析和预测结果"
                ],
                "step_files": {},
                "step_statuses": {
                    "收集2025年江苏足球联赛基本信息（参赛球队、赛制、赛程等）": "not_started",
                    "收集各球队历史表现数据和球员阵容信息": "not_started",
                    "分析各球队近期比赛表现和技术统计数据": "not_started",
                    "评估各球队的战术特点和比赛风格": "not_started",
                    "识别各球队的强项和弱项": "not_started",
                    "分析球队之间的对战记录和相互克制关系": "not_started",
                    "建立预测模型并输入相关数据": "not_started",
                    "进行模拟预测并生成初步排名预测": "not_started",
                    "验证预测结果的合理性并进行调整": "not_started",
                    "撰写完整的分析报告包含详细分析和预测结果": "not_started"
                },
                "step_notes": {},
                "step_details": {},
                "dependencies": {
                    "2": [1],
                    "3": [2],
                    "4": [3],
                    "5": [4],
                    "6": [3],
                    "7": [5, 6],
                    "8": [7],
                    "9": [8],
                    "10": [9]
                },
                "progress": {
                    "total": 10,
                    "completed": 0,
                    "in_progress": 0,
                    "blocked": 0,
                    "not_started": 10
                },
                "result": "",
                "status_text": "正在执行中"
            }
        }
    };

    // 调用 createDag 方法
    const result = createDag(testMessageData);
    if (!result) {
        return;
    }

    // 显示标题信息
    updateDynamicTitle(testMessageData.data.initData.title);
    showStepsTooltip();
    setTimeout(() => {
        hideStepsTooltip();
    }, 3000);
}

// 重置缩放
function resetZoom() {
    if (zoom && svg) {
        svg.transition().duration(750).call(
            zoom.transform,
            d3.zoomIdentity
        );
    }
}

function highlightToolCall(toolCallId) {
    // 高亮工具调用项
    const toolCallItems = document.querySelectorAll('.tool-call-item');
    toolCallItems.forEach(item => {
        if (item.dataset.callId === toolCallId) {
            item.classList.add('highlighted');
            setTimeout(() => {
                item.classList.remove('highlighted');
                item.classList.add('connected');
            }, 2000);
        }
    });
}

function startSimulateWorkflow() {
    updateDynamicTitle("江苏足球联赛球队表现分析与预测报告");
    initDAG();
    showStepsTooltip();
    setTimeout(() => {
        hideStepsTooltip();
    }, 5000);

    // 开始完整的工作流程
    startCompleteWorkflow();
}

// 完整工作流程执行函数
function startCompleteWorkflow() {
    console.log('开始执行完整工作流程...');

    // 1、执行步骤0
    executeStep0WithCallback(() => {
        console.log('步骤0完成，开始并发执行步骤1和步骤2');

        // 2、等步骤0执行完成之后，并发执行步骤1和步骤2
        executeSteps1And2Concurrently(() => {
            console.log('步骤1和步骤2完成，开始并发执行步骤3和步骤4');

            // 3、等步骤1和步骤2执行完成之后，并发执行步骤3和步骤4
            executeSteps3And4Concurrently(() => {
                console.log('步骤3和步骤4完成，开始执行步骤5');

                // 4、等步骤3和步骤4执行完成之后，执行步骤5
                executeStep5WithCallback(() => {
                    console.log('所有步骤完成！');
                    toggleMaximizePanel();
                });
            });
        });
    });
}

// 执行步骤0并等待完成
function executeStep0WithCallback(callback) {
    simulateStep0Workflow();

    // 监听步骤0的完成状态
    const checkStep0Completion = () => {
        const node0 = dagData.nodes.find(n => n.id === 0);
        if (node0 && node0.status === 'completed') {
            console.log('步骤0已完成');
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(0, credibilityLevels[0]);
            callback();
        } else {
            // 每500ms检查一次
            setTimeout(checkStep0Completion, 500);
        }
    };

    // 延迟开始检查，给步骤0一些时间开始执行
    setTimeout(checkStep0Completion, 1000);
}

// 并发执行步骤1和步骤2
function executeSteps1And2Concurrently(callback) {
    // 关闭步骤0的工具调用面板
    closeNodeToolPanel(0);

    // 激活节点1和节点2
    const node1 = dagData.nodes.find(n => n.id === 1);
    const node2 = dagData.nodes.find(n => n.id === 2);
    if (node1) {
        node1.status = 'in_progress';
        credibilityService.addNodeIndicators(1); // 添加运行状态指示器
    }
    if (node2) {
        node2.status = 'in_progress';
        credibilityService.addNodeIndicators(2); // 添加运行状态指示器
    }
    updateProgress();

    // 创建并显示工具面板
    createNodeToolPanel(1, 'Step 1 - ' + node1.title);
    createNodeToolPanel(2, 'Step 2 - ' + node2.title);

    // 并发执行步骤1和步骤2
    executeConcurrentWorkflowSteps(step1Workflow, 0, 1);
    executeConcurrentWorkflowSteps(step2Workflow, 0, 2);

    // 监听步骤1和步骤2的完成状态
    let step1Completed = false;
    let step2Completed = false;

    const checkSteps1And2Completion = () => {
        const node1 = dagData.nodes.find(n => n.id === 1);
        const node2 = dagData.nodes.find(n => n.id === 2);

        if (node1 && node1.status === 'completed' && !step1Completed) {
            step1Completed = true;
            console.log('步骤1已完成');
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(1, credibilityLevels[1]);
        }

        if (node2 && node2.status === 'completed' && !step2Completed) {
            step2Completed = true;
            console.log('步骤2已完成');
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(2, credibilityLevels[2]);
        }

        if (step1Completed && step2Completed) {
            console.log('步骤1和步骤2都已完成');
            callback();
        } else {
            // 每500ms检查一次
            setTimeout(checkSteps1And2Completion, 500);
        }
    };

    // 延迟开始检查
    setTimeout(checkSteps1And2Completion, 1000);
}

// 并发执行步骤3和步骤4
function executeSteps3And4Concurrently(callback) {
    // 关闭步骤1和步骤2的工具调用面板
    closeNodeToolPanel(1);
    closeNodeToolPanel(2);

    // 激活节点3和节点4
    const node3 = dagData.nodes.find(n => n.id === 3);
    const node4 = dagData.nodes.find(n => n.id === 4);
    if (node3) {
        node3.status = 'in_progress';
        credibilityService.addNodeIndicators(3); // 添加运行状态指示器
    }
    if (node4) {
        node4.status = 'in_progress';
        credibilityService.addNodeIndicators(4); // 添加运行状态指示器
    }
    updateProgress();

    // 创建并显示工具面板
    createNodeToolPanel(3, 'Step 3 - ' + node3.title);
    createNodeToolPanel(4, 'Step 4 - ' + node4.title);

    // 并发执行步骤3和步骤4
    executeConcurrentWorkflowSteps(step3Workflow, 0, 3);
    executeConcurrentWorkflowSteps(step4Workflow, 0, 4);

    // 监听步骤3和步骤4的完成状态
    let step3Completed = false;
    let step4Completed = false;

    const checkSteps3And4Completion = () => {
        const node3 = dagData.nodes.find(n => n.id === 3);
        const node4 = dagData.nodes.find(n => n.id === 4);

        if (node3 && node3.status === 'completed' && !step3Completed) {
            step3Completed = true;
            console.log('步骤3已完成');
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(3, credibilityLevels[3]);
        }

        if (node4 && node4.status === 'completed' && !step4Completed) {
            step4Completed = true;
            console.log('步骤4已完成');
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(4, credibilityLevels[4]);
        }

        if (step3Completed && step4Completed) {
            console.log('步骤3和步骤4都已完成');
            callback();
        } else {
            // 每500ms检查一次
            setTimeout(checkSteps3And4Completion, 500);
        }
    };

    // 延迟开始检查
    setTimeout(checkSteps3And4Completion, 1000);
}

// 执行步骤5并等待完成
function executeStep5WithCallback(callback) {
    console.log('开始执行步骤5，先进行资源清理...');

    // 1. 关闭步骤3和步骤4的工具调用面板
    closeNodeToolPanel(3);
    closeNodeToolPanel(4);

    // 2. 执行全面资源清理
    cleanupAllResources();

    // 3. 等待更长时间确保前面的步骤完全完成和资源清理完毕
    setTimeout(() => {
        console.log('资源清理完成，开始执行步骤5工作流程...');

        // 4. 再次清理iframe资源，确保干净的状态
        cleanupContentResources();

        // 5. 等待iframe清理完成
        setTimeout(() => {
            simulateStep5Workflow();

            // 监听步骤5的完成状态
            const checkStep5Completion = () => {
                const node5 = dagData.nodes.find(n => n.id === 5);
                if (node5 && node5.status === 'completed') {
                    console.log('步骤5已完成');
                    // 更新运行状态指示器
                    credibilityService.updateNodeCredibilityIndicator(5, credibilityLevels[5]);
                    callback();
                } else {
                    // 每500ms检查一次
                    setTimeout(checkStep5Completion, 500);
                }
            };

            // 延迟开始检查
            setTimeout(checkStep5Completion, 1000);
        }, 500); // 等待iframe清理完成

    }, 1000); // 等待前面的步骤完全完成和资源清理
}

// STEP0 工作流程模拟
function simulateStep0Workflow() {
    // 激活STEP0节点
    const nodeId = 0;
    const node = dagData.nodes.find(n => n.id === nodeId);
    if (node) {
        node.status = 'in_progress';
        credibilityService.addNodeIndicators(0); // 添加运行状态指示器
        updateProgress();
    }

    // 创建并显示Step 0的工具面板
    createNodeToolPanel(0, 'Step 0 - ' + node.title);

    executeWorkflowSteps(step0Workflow, 0, 0);
}

function executeWorkflowSteps(workflow, index, nodeId) {
    if (index >= workflow.tools.length) {
        // 工作流程完成
        const node = dagData.nodes.find(n => n.id === nodeId);
        if (node) {
            node.status = 'completed';
            updateProgress();
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(nodeId - 1, credibilityLevels[nodeId - 1]);
        }
        return;
    }

    const step = workflow.tools[index];

    // 更新工作流程步骤状态
    setTimeout(() => {
        // 同时更新工具调用状态
        const toolCallId = startToolCall(nodeId, step);

        // 高亮工具调用项
        highlightToolCall(toolCallId);

        // 检查工具是否有url或path属性，如果有则显示右侧面板
        if (step.url || step.path) {
            showRightPanelForTool(step);
        }

        setTimeout(() => {
            completeToolCall(toolCallId, step.result, true);

            // 继续下一个步骤
            setTimeout(() => {
                executeWorkflowSteps(workflow, index + 1, nodeId);
            }, 500);
        }, step.duration);
    }, 500);
}

// 并发执行工作流程步骤（递归函数）
function executeConcurrentWorkflowSteps(workflow, index, nodeId) {
    if (index >= workflow.tools.length) {
        // 工作流程完成
        const node = dagData.nodes.find(n => n.id === nodeId);
        if (node) {
            node.status = 'completed';
            updateProgress();
            // 更新运行状态指示器
            credibilityService.updateNodeCredibilityIndicator(nodeId - 1, credibilityLevels[nodeId - 1]);
        }
        return;
    }

    const step = workflow.tools[index];
    // 更新工作流程步骤状态
    setTimeout(() => {
        // 同时更新工具调用状态
        const toolCallId = startToolCall(nodeId, step);

        // 高亮工具调用项
        highlightToolCall(toolCallId);

        // 检查工具是否有url或path属性，如果有则显示右侧面板
        if (step.url || step.path) {
            showRightPanelForTool(step);
        }

        setTimeout(() => {
            const result = step.result || `并发执行完成：${step.tool} 获取了相关数据`;
            completeToolCall(toolCallId, result, true);

            // 继续执行下一个步骤
            setTimeout(() => {
                executeConcurrentWorkflowSteps(workflow, index + 1, nodeId);
            }, 500);
        }, step.duration);
    }, 500);
}

function simulateStep5Workflow() {
    // 激活STEP5节点
    const nodeId = 5;
    const node = dagData.nodes.find(n => n.id === nodeId);
    if (node) {
        node.status = 'in_progress';
        credibilityService.addNodeIndicators(5); // 添加运行状态指示器
        updateProgress();
    }

    // 创建并显示Step 5的工具面板
    createNodeToolPanel(5, 'Step 5 - ' + node.title);

    executeWorkflowSteps(step5Workflow, 0, 5);
}

function testStepData(number) {
    const messages = [message1, message2, message3, message4, message5, message6, message7, message8];
    messageService.stepMessageHandler(messages[number - 1]);
}

function testCredibilityMessage(stepIndex) {
    const credibilities = [credibility1, credibility2, credibility3, credibility4];
    credibilityService.credibilityMessageHandler(credibilities[stepIndex]);
}

// 将测试函数添加到全局作用域，方便在控制台调用
window.simulateProgress = simulateProgress;
window.resetProgress = resetProgress;
window.testLayoutOptimization = testLayoutOptimization;
window.fitToScreen = fitToScreen;
window.testCreateDag = testCreateDag;
window.resetZoom = resetZoom;
window.testStepData = testStepData;
window.testCredibilityMessage = testCredibilityMessage;

// 导出DAG相关函数（如果使用模块化）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        simulateProgress,
        resetProgress,
        fitToScreen,
        testCreateDag,
        resetZoom,

        simulateStep0Workflow,
        simulateStep5Workflow,
        startSimulateWorkflow
    };
}