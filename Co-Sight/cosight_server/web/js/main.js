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

  const tooltip = document.getElementById("verification-tooltip");
  if (!tooltip) return;

  // 计算提示框位置
  const iconRect = event.target.getBoundingClientRect();
  const tooltipWidth = 350;
  const tooltipHeight = 80;

  let left = iconRect.left + iconRect.width / 2 - tooltipWidth / 2;
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

  tooltip.style.left = left + "px";
  tooltip.style.top = top + "px";
  tooltip.style.opacity = "1";
  tooltip.style.visibility = "visible";
}

// 隐藏验证步骤提示框
function hideVerificationTooltip() {
  // 添加延迟隐藏，避免鼠标快速移动时闪烁
  verificationTooltipTimeout = setTimeout(() => {
    const tooltip = document.getElementById("verification-tooltip");
    if (tooltip) {
      tooltip.style.opacity = "0";
      tooltip.style.visibility = "hidden";
    }
  }, 100);
}

// 显示工具提示
function showTooltip(event, d, showStatus = true) {
  // 确保tooltip已初始化
  if (typeof ensureTooltipInitialized === "function") {
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
  let stepNotesHtml = "";
  if (hasStepNotes) {
    // 处理step_notes中的文件路径，转换为可点击的链接
    let notesContent = d.step_notes;

    // 检测并转换文件路径为可点击链接
    // 匹配 /api/nae-deep-research/v1/work_space/ 或 work_space/ 开头的路径
    const pathRegex =
      /(\/api\/nae-deep-research\/v1\/work_space\/[^\s\n]+|work_space\/[^\s\n]+)/g;
    notesContent = notesContent.replace(pathRegex, (match) => {
      // 提取文件名
      const fileName = match.split("/").pop();
      const fullPath = match.startsWith("/api/")
        ? match
        : `/api/nae-deep-research/v1/${match}`;
      return `<a href="#" onclick="openFileInRightPanel('${fullPath}'); event.preventDefault(); event.stopPropagation(); return false;" style="color: #4CAF50; text-decoration: underline; cursor: pointer;" title="点击查看文件">${fileName}</a>`;
    });

    stepNotesHtml = `<div style="margin-top: 8px; padding: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; max-height: 200px; overflow-y: auto;">
            <strong style="font-size: 12px;">${
              window.I18nService
                ? window.I18nService.t("step_notes")
                : "步骤说明"
            }:</strong><br/>
            <span style="font-size: 11px; line-height: 1.5; white-space: pre-wrap;">${notesContent}</span>
           </div>`;
  }
  const stepNotes = stepNotesHtml;

  const status = showStatus
    ? `<em>${
        window.I18nService ? window.I18nService.t("status") : "状态"
      }: ${getStatusText(d.status)}</em><br/>`
    : "";

  // 确保tooltip已初始化再使用
  if (!tooltip) {
    console.warn("Tooltip未初始化");
    return;
  }

  tooltip
    .style("opacity", 0)
    .style("left", finalX + "px")
    .style("top", finalY + "px")
    .html(
      `
            <strong>${d.name} - ${d.fullName || d.title || ""}</strong><br/>
            <hr>
            ${status}
            ${stepNotes}
        `
    )
    .transition()
    .duration(200)
    .style("opacity", 1);
}

// 隐藏工具提示
function hideTooltip() {
  // 确保tooltip已初始化
  if (typeof ensureTooltipInitialized === "function") {
    ensureTooltipInitialized();
  }

  // 添加延迟隐藏，避免鼠标快速移动时闪烁
  tooltipTimeout = setTimeout(() => {
    if (tooltip) {
      tooltip.transition().duration(200).style("opacity", 0);
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
    const tooltipEl = document.getElementById("tooltip");
    if (!tooltipEl) return;

    let isMouseNearTooltip = false;
    let isMouseInTooltip = false;

    // 全局监听鼠标移动，检测是否靠近 tooltip
    document.addEventListener("mousemove", function (e) {
      const style = window.getComputedStyle(tooltipEl);
      if (style.opacity === "0" || style.visibility === "hidden") {
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
          tooltipEl.classList.add("hover-active");
        }
      } else {
        if (isMouseNearTooltip && !isMouseInTooltip) {
          isMouseNearTooltip = false;
          tooltipEl.classList.remove("hover-active");
        }
      }
    });

    // 鼠标进入 tooltip 时，清除隐藏定时器，保持显示
    tooltipEl.addEventListener("mouseenter", function () {
      isMouseInTooltip = true;
      if (typeof tooltipTimeout !== "undefined" && tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
      }
      tooltipEl.classList.add("hover-active");
    });

    // 鼠标离开 tooltip 时，延迟隐藏并恢复穿透
    tooltipEl.addEventListener("mouseleave", function () {
      isMouseInTooltip = false;
      isMouseNearTooltip = false;
      tooltipEl.classList.remove("hover-active");
      if (typeof hideTooltip === "function") {
        hideTooltip();
      }
    });

    console.log("Tooltip 智能悬停行为已初始化");
  } catch (err) {
    console.warn("初始化 tooltip 行为失败:", err);
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
  return (
    statusTexts[status] ||
    (window.I18nService ? window.I18nService.t("unknown") : "未知")
  );
}

// 根据节点ID获取对应的工作流程数据
function getWorkflowByNodeId(nodeId) {
  // 优先从messageService获取tool events数据
  if (
    typeof messageService !== "undefined" &&
    messageService.getStepToolEvents
  ) {
    const stepIndex = nodeId - 1; // 节点ID从1开始，stepIndex从0开始
    const toolEvents = messageService.getStepToolEvents(stepIndex);

    if (toolEvents && toolEvents.length > 0) {
      console.log(
        `从tool events获取Step ${nodeId}的数据，共${toolEvents.length}个工具调用`
      );

      // 转换工具调用格式
      const tools = toolEvents
        // 过滤内部工具，不在面板展示
        .filter((toolEvent) => toolEvent.tool_name !== "mark_step")
        .map((toolEvent) => {
          const toolName = toolEvent.tool_name;
          let toolResult = toolEvent.tool_result;
          let url = null;
          let path = null;
          let descriptionOverride = null;

          // 处理搜索工具的结果，提取URL
          if (
            [
              "search_baidu",
              "search_google",
              "tavily_search",
              "image_search",
            ].includes(toolName)
          ) {
            if (toolResult && toolResult.first_url) {
              url = toolResult.first_url;
            }
          }

          // 处理文件保存工具，提取路径
          if (toolName === "file_saver") {
            try {
              // 优先使用 processed_result.file_path（已包含完整API路径）
              const processed = toolEvent.tool_result;
              let filePath = null;

              if (processed && processed.file_path) {
                // processed_result.file_path 已经包含完整的 API 路径前缀
                filePath = processed.file_path;
              } else {
                // 回退到从 tool_args 中提取
                const args = JSON.parse(toolEvent.tool_args || "{}");
                if (args.file_path) {
                  filePath = buildApiWorkspacePath(args.file_path);
                }
              }

              if (filePath) {
                path = filePath;
                const filename = extractFileName(filePath);
                if (filename) {
                  descriptionOverride = window.I18nService
                    ? `${window.I18nService.t("info_saved_to")}${filename}`
                    : `信息保存到:${filename}`;
                }
              }
            } catch (e) {
              console.warn("解析文件保存工具参数失败:", e);
            }
          }

          // 处理文件读取工具，提取路径
          if (toolName === "file_read") {
            try {
              // 优先 processed_result.file_path
              const processed = toolEvent.tool_result;
              let filePath =
                processed && processed.file_path ? processed.file_path : null;
              if (!filePath) {
                const args = JSON.parse(toolEvent.tool_args || "{}");
                filePath = args.file || args.path || null;
              }
              if (filePath) {
                path = buildApiWorkspacePath(filePath);
              }
            } catch (e) {
              console.warn("解析文件读取工具参数失败:", e);
            }
          }

          // 结果文本处理
          let resultText = "";
          if (toolResult) {
            if (typeof toolResult === "string") {
              resultText = toolResult;
            } else if (toolResult.summary) {
              resultText = toolResult.summary;
            } else {
              resultText = JSON.stringify(toolResult);
            }

            // 代码执行器：工具栏只显示摘要，完整内容在右侧查看
            try {
              if (
                toolName === "execute_code" &&
                typeof toolResult === "object" &&
                toolResult
              ) {
                // 优先使用 summary（简短摘要），如果没有则使用 output 的前100字符作为预览
                if (
                  toolResult.summary &&
                  typeof toolResult.summary === "string"
                ) {
                  resultText = toolResult.summary;
                } else if (
                  toolResult.output &&
                  typeof toolResult.output === "string"
                ) {
                  // 如果输出太长，只显示前100字符作为预览
                  const preview =
                    toolResult.output.length > 100
                      ? toolResult.output.substring(0, 100) + "..."
                      : toolResult.output;
                  resultText = preview;
                }
              }
            } catch (e) {
              console.warn("处理execute_code结果文本失败:", e);
            }
          }

          // file_saver 将 result 替换为描述内容，并清空描述
          if (toolName === "file_saver" && descriptionOverride) {
            resultText = descriptionOverride;
            descriptionOverride = "";
          }

          // 代码执行器：为后续点击查看代码内容设置特殊path
          if (toolName === "execute_code") {
            try {
              const args = JSON.parse(toolEvent.tool_args || "{}");
              if (args.code) {
                path = "code://execute_code";
              }
            } catch (e) {
              console.warn(
                "解析代码执行工具参数失败(getWorkflowByNodeId/toolEvents):",
                e
              );
            }
          }

          // 对于代码执行器，根据执行结果内容智能判断状态（与右侧电脑区逻辑保持一致）
          let finalStatus = toolEvent.status || "completed";
          if (toolName === "execute_code" && toolEvent.status !== "running") {
            try {
              // 获取执行结果文本
              let resultTextForCheck = "";
              if (toolResult) {
                if (typeof toolResult === "string") {
                  resultTextForCheck = toolResult;
                } else if (
                  toolResult.output &&
                  typeof toolResult.output === "string"
                ) {
                  resultTextForCheck = toolResult.output;
                } else if (
                  toolResult.summary &&
                  typeof toolResult.summary === "string"
                ) {
                  resultTextForCheck = toolResult.summary;
                }
              }

              // 检查是否包含错误信息（与右侧电脑区相同的判断逻辑）
              if (resultTextForCheck) {
                const lowered = resultTextForCheck.toLowerCase();
                const hasErrorPattern =
                  /traceback \(most recent call last\)/i.test(
                    resultTextForCheck
                  ) ||
                  /exception[:\s]/i.test(resultTextForCheck) ||
                  /error[:\s]/i.test(resultTextForCheck) ||
                  lowered.includes("nameerror") ||
                  resultTextForCheck.includes("错误");

                // 如果包含错误信息，设置为失败；否则设置为成功
                if (hasErrorPattern) {
                  finalStatus = "failed";
                } else if (toolEvent.status !== "failed") {
                  // 只有在原始状态不是明确失败时，才改为成功
                  finalStatus = "completed";
                }
              }
            } catch (e) {
              console.warn("智能判断代码执行状态失败(getWorkflowByNodeId):", e);
              // 判断失败时保持原始状态
            }
          }

          // 根据状态生成描述
          let statusDescription = "";
          if (finalStatus === "running") {
            statusDescription = window.I18nService
              ? `${window.I18nService.t("executing")}${getToolDisplayName(
                  toolName
                )}`
              : `正在执行: ${getToolDisplayName(toolName)}`;
          } else if (finalStatus === "completed") {
            statusDescription = window.I18nService
              ? `${window.I18nService.t(
                  "execution_completed"
                )}${getToolDisplayName(toolName)}`
              : `执行完成: ${getToolDisplayName(toolName)}`;
          } else if (finalStatus === "failed") {
            statusDescription = window.I18nService
              ? `${window.I18nService.t(
                  "execution_failed"
                )}${getToolDisplayName(toolName)}`
              : `执行失败: ${getToolDisplayName(toolName)}`;
          } else {
            statusDescription = window.I18nService
              ? `${window.I18nService.t("execute_tool")}${getToolDisplayName(
                  toolName
                )}`
              : `执行工具: ${getToolDisplayName(toolName)}`;
          }

          return {
            tool: toolName,
            toolName: getToolDisplayName(toolName),
            description: descriptionOverride || statusDescription,
            mode: "sync",
            duration: (toolEvent.duration || 0) * 1000, // 转换为毫秒
            result: resultText,
            url: url,
            path: path,
            timestamp: toolEvent.timestamp,
            status: finalStatus, // 添加智能判断后的状态
            // 为代码执行器等需要的场景保留原始参数及结构化结果
            tool_args: toolEvent.tool_args,
            raw_result: toolResult,
          };
        });

      // 获取step标题
      let stepTitle = `Step ${nodeId}`;
      if (typeof dagData !== "undefined" && dagData.nodes) {
        const node = dagData.nodes.find((n) => n.id === nodeId);
        if (node) {
          stepTitle = node.fullName || node.title || `Step ${nodeId}`;
        }
      }

      return {
        title: stepTitle,
        tools: tools,
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
    .filter((toolCall) => toolCall.tool_name !== "mark_step")
    .map((toolCall) => {
      const toolName = toolCall.tool_name;
      let toolResult = toolCall.tool_result;
      let url = null;
      let path = null;
      let descriptionOverride = null;

      // 处理搜索工具的结果，提取URL
      if (
        [
          "search_baidu",
          "search_google",
          "tavily_search",
          "image_search",
          "search_wiki",
        ].includes(toolName)
      ) {
        try {
          // 优先 processed_result.first_url 风格（上游已解析对象）
          if (toolResult && toolResult.first_url) {
            url = toolResult.first_url;
          } else {
            // 特殊处理 tavily_search 和 image_search 的字符串结果
            if (toolName === "tavily_search" || toolName === "image_search") {
              url = extractUrlFromSearchResult(toolResult, toolName);
            } else {
              const resultArray = parseSearchResults(toolResult);
              if (Array.isArray(resultArray) && resultArray.length > 0) {
                const withUrl =
                  resultArray.find((it) => it && it.url) || resultArray[0];
                url = withUrl && withUrl.url ? withUrl.url : null;
              }
            }
          }
        } catch (e) {
          console.warn("解析搜索工具结果失败:", e);
        }
      }

      // 处理文件保存工具，提取路径
      if (toolName === "file_saver") {
        try {
          // 优先使用 processed_result.file_path（已包含完整API路径）
          const processed = toolCall.tool_result;
          let filePath = null;

          if (processed && processed.file_path) {
            // processed_result.file_path 已经包含完整的 API 路径前缀
            filePath = processed.file_path;
          } else {
            // 回退到从 tool_args 中提取
            const args = JSON.parse(toolCall.tool_args || "{}");
            if (args.file_path) {
              filePath = buildApiWorkspacePath(args.file_path);
            }
          }

          if (filePath) {
            path = filePath;
            const filename = extractFileName(filePath);
            if (filename) {
              descriptionOverride = window.I18nService
                ? `${window.I18nService.t("info_saved_to")}${filename}`
                : `信息保存到:${filename}`;
            }
          }
        } catch (e) {
          console.warn("解析文件保存工具参数失败:", e);
        }
      }

      // 处理文件读取工具，提取路径
      if (toolName === "file_read") {
        try {
          // 优先 processed_result.file_path
          let filePath = null;
          if (
            typeof toolResult === "object" &&
            toolResult &&
            toolResult.file_path
          ) {
            filePath = toolResult.file_path;
          } else {
            const args = JSON.parse(toolCall.tool_args || "{}");
            filePath = args.file || args.path || null;
          }
          if (filePath) {
            path = buildApiWorkspacePath(filePath);
          }
        } catch (e) {
          console.warn("解析文件读取工具参数失败:", e);
        }
      }

      // 结果文本：优先使用原始字符串
      let resultText =
        typeof toolResult === "string"
          ? toolResult
          : JSON.stringify(toolResult);

      // 代码执行器：如果有结构化输出字段，则优先展示输出内容
      try {
        if (
          toolName === "execute_code" &&
          typeof toolResult === "object" &&
          toolResult
        ) {
          if (toolResult.output && typeof toolResult.output === "string") {
            resultText = toolResult.output;
          }
        }
      } catch (e) {
        console.warn("处理execute_code结果文本失败(step_tool_calls):", e);
      }
      // file_saver 将 result 替换为描述内容，并清空描述
      if (toolName === "file_saver" && descriptionOverride) {
        resultText = descriptionOverride;
        descriptionOverride = "";
      }

      // 代码执行器：为后续点击查看代码内容设置特殊path
      if (toolName === "execute_code") {
        try {
          const args = JSON.parse(toolCall.tool_args || "{}");
          if (args.code) {
            path = "code://execute_code";
          }
        } catch (e) {
          console.warn("解析代码执行工具参数失败(step_tool_calls):", e);
        }
      }

      // 对于代码执行器，根据执行结果内容智能判断状态（与右侧电脑区逻辑保持一致）
      let finalStatus = "completed"; // 默认状态
      if (toolName === "execute_code") {
        try {
          // 获取执行结果文本（step_tool_calls 中的 tool_result 可能是字符串或对象）
          let resultTextForCheck = "";
          if (toolResult) {
            if (typeof toolResult === "string") {
              // 如果是字符串，直接使用（这是 replay.json 中的格式）
              resultTextForCheck = toolResult;
            } else if (typeof toolResult === "object" && toolResult !== null) {
              // 如果是对象，优先使用 output 字段，其次使用 summary
              if (toolResult.output && typeof toolResult.output === "string") {
                resultTextForCheck = toolResult.output;
              } else if (
                toolResult.summary &&
                typeof toolResult.summary === "string"
              ) {
                resultTextForCheck = toolResult.summary;
              } else {
                // 如果都没有，尝试将整个对象转为字符串
                resultTextForCheck = JSON.stringify(toolResult);
              }
            }
          }

          // 检查是否包含错误信息（与右侧电脑区相同的判断逻辑）
          if (resultTextForCheck && resultTextForCheck.length > 0) {
            const lowered = resultTextForCheck.toLowerCase();
            const hasErrorPattern =
              /traceback \(most recent call last\)/i.test(resultTextForCheck) ||
              /exception[:\s]/i.test(resultTextForCheck) ||
              /error[:\s]/i.test(resultTextForCheck) ||
              lowered.includes("nameerror") ||
              resultTextForCheck.includes("错误");

            // 如果包含错误信息，设置为失败；否则设置为成功
            if (hasErrorPattern) {
              finalStatus = "failed";
            } else {
              finalStatus = "completed";
            }
          }
        } catch (e) {
          console.warn(
            "智能判断代码执行状态失败(step_tool_calls):",
            e,
            toolResult
          );
          // 判断失败时保持默认状态
        }
      }

      // 根据状态生成描述
      let statusDescription = "";
      if (finalStatus === "running") {
        statusDescription = window.I18nService
          ? `${window.I18nService.t("executing")}${getToolDisplayName(
              toolName
            )}`
          : `正在执行: ${getToolDisplayName(toolName)}`;
      } else if (finalStatus === "completed") {
        statusDescription = window.I18nService
          ? `${window.I18nService.t("execution_completed")}${getToolDisplayName(
              toolName
            )}`
          : `执行完成: ${getToolDisplayName(toolName)}`;
      } else if (finalStatus === "failed") {
        statusDescription = window.I18nService
          ? `${window.I18nService.t("execution_failed")}${getToolDisplayName(
              toolName
            )}`
          : `执行失败: ${getToolDisplayName(toolName)}`;
      } else {
        statusDescription = window.I18nService
          ? `${window.I18nService.t("execute_tool")}${getToolDisplayName(
              toolName
            )}`
          : `执行工具: ${getToolDisplayName(toolName)}`;
      }

      return {
        tool: toolName,
        toolName: getToolDisplayName(toolName),
        description: descriptionOverride || statusDescription,
        mode: "sync",
        duration: 2000, // 默认持续时间
        result: resultText,
        url: url,
        path: path,
        timestamp: toolCall.timestamp,
        status: finalStatus, // 添加智能判断后的状态
        // 为代码执行器等需要的场景保留原始参数及结构化结果
        tool_args: toolCall.tool_args,
        raw_result: toolResult,
      };
    });

  return {
    title: stepName,
    tools: tools,
  };
}

// 获取最新的 manus step 消息
function getLastManusStepMessage() {
  try {
    const raw = localStorage.getItem("cosight:lastManusStep");
    if (!raw) return null;
    const stored = JSON.parse(raw);
    return stored && stored.message;
  } catch (e) {
    console.warn("获取最新消息失败:", e);
    return null;
  }
}

// 获取工具显示名称
function getToolDisplayName(toolName) {
  const toolKeys = {
    search_baidu: "baidu_search",
    search_google: "google_search",
    image_search: "image_search",
    file_saver: "file_save",
    file_read: "file_read",
    execute_code: "code_executor",
    data_analyzer: "data_analyzer",
    predictor: "predictor",
    report_generator: "report_generator",
    create_plan: "create_plan",
    fetch_website_content: "fetch_website_content",
    fetch_website_content_with_images: "fetch_website_content_with_images",
    fetch_website_images_only: "fetch_website_images_only",
    tavily_search: "tavily_search",
    search_wiki: "wiki_search",
  };
  const key = toolKeys[toolName];
  if (key && window.I18nService) {
    const translated = window.I18nService.t(key);
    if (translated && translated !== key) return translated;
  }
  // 回退：原中文映射
  const toolNames = {
    search_baidu: "百度搜索",
    search_google: "谷歌搜索",
    image_search: "图片搜索",
    file_saver: "文件保存",
    file_read: "文件读取",
    execute_code: "代码执行器",
    data_analyzer: "数据分析",
    predictor: "预测模型",
    report_generator: "报告生成",
    create_plan: "创建计划",
    fetch_website_content: "获取网页内容",
    fetch_website_content_with_images: "网页内容爬取（含图片）",
    fetch_website_images_only: "网页图片提取",
    tavily_search: "Tavily搜索",
    search_wiki: "维基百科搜索",
  };
  return toolNames[toolName] || toolName;
}

// 解析搜索工具结果：兼容 JSON 字符串与 Python 风格单引号数组
function parseSearchResults(raw) {
  if (raw == null) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw !== "string") return [];
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
    const fn = new Function("return (" + raw + ")");
    const val = fn();
    return Array.isArray(val) ? val : [];
  } catch (e) {
    console.warn("fallback 解析失败:", e);
    return [];
  }
}

// 规范化文件路径：去除盘符等，截断到 \Co-Sight\ 开头
function normalizeFilePathForFrontend(originalPath) {
  if (!originalPath || typeof originalPath !== "string") return originalPath;
  try {
    // 统一分隔符处理副本
    const p = originalPath;
    // 优先匹配 Windows 分隔符
    let idx = p.indexOf("\\Co-Sight\\");
    if (idx === -1) {
      // 再匹配正斜杠形式（以防某些环境返回）
      idx = p.indexOf("/Co-Sight/");
      if (idx !== -1) {
        // 保持与示例一致，转回反斜杠并保留前导反斜杠
        const sliced = p.substring(idx).replace(/\//g, "\\");
        return sliced.startsWith("\\") ? sliced : "\\" + sliced;
      }
    } else {
      const sliced = p.substring(idx);
      return sliced.startsWith("\\") ? sliced : "\\" + sliced;
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
  if (!p || typeof p !== "string") return "";
  const unified = p.replace(/\\/g, "/");
  const idx = unified.lastIndexOf("/");
  return idx >= 0 ? unified.substring(idx + 1) : unified;
}

// 工具调用状态管理函数
function startToolCall(nodeId, tool) {
  // 过滤内部工具：mark_step 不进入面板与历史
  if (tool && (tool.tool === "mark_step" || tool.tool_name === "mark_step")) {
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
    status: "running",
    startTime: startTime,
    endTime: null,
    result: null,
    error: null,
    url: tool.url,
    path: tool.path,
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
  toolCall.result = result;

  // 对于代码执行器，根据执行结果内容智能判断状态（与右侧电脑区逻辑保持一致）
  let finalStatus = success ? "completed" : "failed";
  if (toolCall.tool === "execute_code" && success) {
    try {
      // 获取执行结果文本
      let resultTextForCheck = "";
      if (result) {
        resultTextForCheck =
          typeof result === "string" ? result : JSON.stringify(result);
      }

      // 检查是否包含错误信息（与右侧电脑区相同的判断逻辑）
      if (resultTextForCheck) {
        const lowered = resultTextForCheck.toLowerCase();
        const hasErrorPattern =
          /traceback \(most recent call last\)/i.test(resultTextForCheck) ||
          /exception[:\s]/i.test(resultTextForCheck) ||
          /error[:\s]/i.test(resultTextForCheck) ||
          lowered.includes("nameerror") ||
          resultTextForCheck.includes("错误");

        // 如果包含错误信息，设置为失败
        if (hasErrorPattern) {
          finalStatus = "failed";
        }
      }
    } catch (e) {
      console.warn("智能判断代码执行状态失败(completeToolCall):", e);
      // 判断失败时保持原始状态
    }
  }

  toolCall.status = finalStatus;

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
  const container = document.getElementById("tool-call-panels-container");
  const panelId = `tool-panel-${nodeId}`;

  // 如果面板已存在，直接显示
  let panel = document.getElementById(panelId);
  if (panel) {
    panel.classList.add("show");
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
    if (typeof dagData !== "undefined" && dagData.nodes) {
      const node = dagData.nodes.find((n) => n.id === nodeId);
      if (node) {
        const namePart = node.name || `Step ${nodeId}`;
        const detailPart = node.fullName || node.title || "";
        safeTitle = detailPart ? `${namePart} - ${detailPart}` : namePart;
      }
    }
  } catch (e) {}

  // 创建新面板
  panel = document.createElement("div");
  panel.id = panelId;
  panel.className = "tool-call-panel";
  panel.setAttribute("data-node-id", nodeId);
  panel.setAttribute("data-sticky", sticky);

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
  panel.style.position = "absolute";
  panel.style.top = "50px";
  panel.style.left = "16px";
  console.log(`[创建面板 ${nodeId}] 初始位置设置: top=50px, left=16px`);

  container.appendChild(panel);
  nodeToolPanels.set(nodeId, panel);

  // 绑定关闭按钮事件，避免作用域问题与拖拽干扰
  try {
    const closeBtn = panel.querySelector(".btn-close");
    const headerEl = panel.querySelector(".panel-header");
    // 确保 header 定位上下文，避免绝对定位按钮偏移
    try {
      if (headerEl) {
        const cs = window.getComputedStyle(headerEl);
        if (cs && cs.position === "static") {
          headerEl.style.position = "relative";
        }
      }
    } catch (_) {}
    if (closeBtn) {
      // 强制按钮位于顶层并可命中
      try {
        closeBtn.style.position = "absolute";
        closeBtn.style.top = "8px";
        closeBtn.style.right = "8px";
        closeBtn.style.zIndex = "10";
        closeBtn.style.pointerEvents = "auto";
      } catch (_) {}

      // 阻止事件冒泡，避免触发header的拖拽mousedown
      closeBtn.addEventListener("mousedown", function (e) {
        console.log(`[panel:${nodeId}] close button mousedown`);
        e.stopPropagation();
      });
      closeBtn.addEventListener("click", function (e) {
        console.log(`[panel:${nodeId}] close button clicked`);
        e.preventDefault();
        e.stopPropagation();
        try {
          closeNodeToolPanel(nodeId);
        } catch (err) {
          console.warn(`[panel:${nodeId}] close error`, err);
        }
      });
    } else {
      console.warn(`[panel:${nodeId}] close button not found`);
    }
  } catch (err) {
    console.warn(`[panel:${nodeId}] bind close error`, err);
  }

  // 初始化拖拽功能
  initNodePanelDrag(panel);

  // 显示面板并定位
  panel.classList.add("show");

  // ====== 再次强制设置位置，确保生效 ======
  panel.style.top = "50px";
  panel.style.left = "16px";

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
  const finalLeft = Math.max(
    10,
    Math.min(left, window.innerWidth - panelWidth - 10)
  );

  const sticky = panel.getAttribute("data-sticky");
  // 固定贴在屏幕左侧显示
  panel.style.left = sticky == "true" ? `${finalLeft}px` : `16px`;

  // ============== 关键修改：强制工具栏往下移 ==============
  // 不再调用 calculateOptimalPanelTop，直接设置一个固定的、远离顶部的位置
  const FORCED_TOP_OFFSET = 50; // 强制距离页面顶部 50px

  // 直接设置为固定值，不再依赖任何计算
  panel.style.top = `${FORCED_TOP_OFFSET}px`;

  console.log(`[Panel ${nodeId}] 强制设置位置: top=${FORCED_TOP_OFFSET}px`);
}

// 计算面板的最优垂直位置
function calculateOptimalPanelTop(panel, nodeRect) {
  const topMargin = 100; // 顶部留出更多空间，避免工具栏贴顶（从 20 调整为 100）
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
  const nodeTexts = document.querySelectorAll(".node-text");
  for (let textElement of nodeTexts) {
    if (textElement.textContent.includes(`Step ${nodeId}`)) {
      return textElement.closest(".node");
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
      height: nodeRect.height,
    });

    if (panel) {
      console.log(`Panel ${nodeId} info:`, {
        currentHeight: panel.offsetHeight,
        maxHeight: Math.min(400, window.innerHeight * 0.6),
        windowHeight: window.innerHeight,
      });
    }

    console.log("Window size:", {
      width: window.innerWidth,
      height: window.innerHeight,
    });
  } else {
    console.log(`Node ${nodeId} not found`);
  }
}

// 关闭节点工具面板
function closeNodeToolPanel(nodeId) {
  const panel = nodeToolPanels.get(nodeId);
  console.log(
    `[panel:${nodeId}] closeNodeToolPanel invoked, hasPanel=`,
    !!panel
  );
  if (panel) {
    // 清理内容观察器
    if (panel._contentObserver) {
      panel._contentObserver.disconnect();
      panel._contentObserver = null;
    }

    panel.classList.remove("show");
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

  if (panel && panel.classList.contains("show")) {
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
  const header = panel.querySelector(".panel-header");
  let isDragging = false;
  let currentX,
    currentY,
    initialX,
    initialY,
    xOffset = 0,
    yOffset = 0;

  header.addEventListener("mousedown", dragStart);
  document.addEventListener("mousemove", drag);
  document.addEventListener("mouseup", dragEnd);

  function dragStart(e) {
    if (!panel.classList.contains("show")) {
      return;
    }

    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;

    if (e.target === header || header.contains(e.target)) {
      isDragging = true;
      panel.classList.add("dragging");
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
      panel.classList.remove("dragging");
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
  const stepIds = getVerificationStepsForTool(
    toolCall.tool,
    toolCall.result || ""
  );

  if (!stepIds || stepIds.length === 0) {
    return null;
  }

  const iconsContainer = document.createElement("div");
  iconsContainer.className = "verification-icons";

  stepIds.forEach((stepId) => {
    const step = verificationSteps.find((s) => s.id === stepId);
    if (!step) return;

    const icon = document.createElement("div");
    icon.className = `verification-icon ${stepId}`;
    icon.innerHTML = `<i class="${step.icon}"></i>`;

    // 添加悬停事件
    icon.addEventListener("mouseenter", function (event) {
      showVerificationTooltip(event, step);
    });

    icon.addEventListener("mouseleave", function () {
      hideVerificationTooltip();
    });
    iconsContainer.appendChild(icon);
  });

  return iconsContainer;
}

// 创建工具调用项（使用原始的实现方式）
function createToolCallItem(toolCall) {
  const item = document.createElement("div");
  item.className = `tool-call-item ${toolCall.status}`;
  item.dataset.callId = toolCall.id;

  // 检查工具是否有url或path属性，如果有则添加点击功能
  const hasContent = toolCall.url || toolCall.path;
  if (hasContent) {
    item.style.cursor = "pointer";
    item.title = window.I18nService
      ? window.I18nService.t("click_to_view_details")
      : "点击查看详情";

    // 添加点击事件
    item.addEventListener("click", function () {
      showRightPanelForTool(toolCall);
    });

    // 添加悬停效果
    item.addEventListener("mouseenter", function () {
      this.style.backgroundColor = "#f0f8ff";
    });

    item.addEventListener("mouseleave", function () {
      this.style.backgroundColor = "";
    });
  }

  const icon = document.createElement("div");
  icon.className = `tool-call-icon ${toolCall.status}`;

  let iconClass = "";
  switch (toolCall.status) {
    case "running":
      iconClass = "fas fa-cog loading-spinner";
      break;
    case "completed":
      // 根据工具类型显示特定图标
      iconClass = getToolSpecificIcon(toolCall.tool);
      break;
    case "failed":
      iconClass = "fas fa-times";
      break;
  }
  if (toolCall.tool === "search_baidu") {
    icon.innerHTML = `<img src="/cosight/images/baidu.png" style="width: 24px; height: 24px;">`;
  } else {
    icon.innerHTML = `<i class="${iconClass}"></i>`;
  }

  const content = document.createElement("div");
  content.className = "tool-call-content";

  const name = document.createElement("div");
  name.className = "tool-call-name";

  // 创建工具名称文本
  const nameText = document.createElement("span");
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

  const status = document.createElement("div");
  status.className = "tool-call-status";
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

  if (toolCall.result && toolCall.status !== "running") {
    const result = document.createElement("div");
    result.className = "tool-call-result";

    // 对于代码执行器，工具卡片里只展示“成功/失败”摘要，避免与右侧状态不一致
    let displayText = "";
    if (toolCall.tool === "execute_code") {
      if (toolCall.status === "failed") {
        displayText = "代码执行失败";
      } else if (toolCall.status === "running") {
        displayText = "代码执行中...";
      } else {
        // 只要状态不是失败/运行中，一律视为成功（与右侧状态保持一致）
        displayText = "代码执行成功";
      }
    } else {
      displayText =
        typeof toolCall.result === "string"
          ? toolCall.result
          : JSON.stringify(toolCall.result, null, 2);
    }

    result.textContent = displayText;
    content.appendChild(result);
  }

  item.appendChild(icon);
  item.appendChild(content);

  return item;
}

// 更新节点工具面板内容
function updateNodeToolPanel(nodeId, toolCall) {
  // 过滤内部工具：mark_step 不更新面板
  if (toolCall && toolCall.tool === "mark_step") {
    return;
  }
  let panel = nodeToolPanels.get(nodeId);
  if (!panel) {
    // 面板不存在：在首次事件到来时自动创建并展示
    try {
      if (!autoOpenedPanels.has(nodeId)) {
        let nodeName = `Step ${nodeId}`;
        try {
          if (typeof dagData !== "undefined" && dagData.nodes) {
            const node = dagData.nodes.find((n) => n.id === nodeId);
            if (node) {
              const title = node.fullName || node.title || "";
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

  const toolCallList = panel.querySelector(".tool-call-list");
  if (!toolCallList) return;

  // 查找或创建工具调用项
  let toolCallItem = toolCallList.querySelector(
    `[data-call-id="${toolCall.id}"]`
  );
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
    if (
      isExistingItem &&
      (toolCall.url || toolCall.path) &&
      toolCall.status !== "running"
    ) {
      showRightPanelForTool(toolCall);
    }
  } catch (_) {}

  // 内容更新后，重新计算面板位置以适应新的高度
  setTimeout(() => {
    const panel = nodeToolPanels.get(nodeId);
    if (panel && panel.classList.contains("show")) {
      console.log("Updating panel position after content change...");
      updatePanelPosition(panel, nodeId);
    }
  }, 100); // 进一步增加延迟时间确保DOM更新完成
}

// 获取工具调用状态图标
function getToolCallStatusIcon(status) {
  return toolCallStatusIcons[status] || "fas fa-question-circle";
}

// 获取工具调用状态文本
function getToolCallStatusText(status) {
  return toolCallStatusTexts[status] || "未知";
}

// 根据工具类型获取特定图标
function getToolSpecificIcon(tool) {
  const toolIcons = {
    file_read: "fas fa-book-open",
    file_saver: "fas fa-save",
    search_baidu: "fab fa-baidu",
    search_google: "fab fa-google",
    tavily_search: "fas fa-search",
    image_search: "fas fa-search",
    search_wiki: "fab fa-wikipedia-w",
    execute_code: "fas fa-file-code",
    create_html_report: "fas fa-chart-line",
  };

  return toolIcons[tool] || "fas fa-check"; // 默认使用对勾图标
}

// 添加工具调用到节点面板（用于节点点击）
function addToolCallToNodePanel(nodeId, tool) {
  // 过滤内部工具：mark_step 不添加到面板
  if (tool && (tool.tool === "mark_step" || tool.tool_name === "mark_step")) {
    return;
  }
  // 直接创建已完成的工具调用，不模拟执行过程
  const callId = `tool_${++toolCallCounter}_${Date.now()}`;
  const startTime = Date.now() - tool.duration; // 设置开始时间为duration之前
  const endTime = Date.now();

  // 对于代码执行器，根据执行结果内容智能判断状态（与右侧电脑区逻辑保持一致）
  let finalStatus = tool.status || "completed";
  if (tool.tool === "execute_code" && tool.status !== "running") {
    try {
      // 获取执行结果文本
      let resultTextForCheck = "";
      if (tool.raw_result) {
        if (typeof tool.raw_result === "string") {
          resultTextForCheck = tool.raw_result;
        } else if (
          tool.raw_result.output &&
          typeof tool.raw_result.output === "string"
        ) {
          resultTextForCheck = tool.raw_result.output;
        } else if (
          tool.raw_result.summary &&
          typeof tool.raw_result.summary === "string"
        ) {
          resultTextForCheck = tool.raw_result.summary;
        }
      } else if (tool.result) {
        resultTextForCheck =
          typeof tool.result === "string"
            ? tool.result
            : JSON.stringify(tool.result);
      }

      // 检查是否包含错误信息（与右侧电脑区相同的判断逻辑）
      if (resultTextForCheck) {
        const lowered = resultTextForCheck.toLowerCase();
        const hasErrorPattern =
          /traceback \(most recent call last\)/i.test(resultTextForCheck) ||
          /exception[:\s]/i.test(resultTextForCheck) ||
          /error[:\s]/i.test(resultTextForCheck) ||
          lowered.includes("nameerror") ||
          resultTextForCheck.includes("错误");

        // 如果包含错误信息，设置为失败；否则设置为成功
        if (hasErrorPattern) {
          finalStatus = "failed";
        } else if (tool.status !== "failed") {
          // 只有在原始状态不是明确失败时，才改为成功
          finalStatus = "completed";
        }
      }
    } catch (e) {
      console.warn("智能判断代码执行状态失败(addToolCallToNodePanel):", e);
      // 判断失败时保持原始状态
    }
  }

  const toolCall = {
    id: callId,
    nodeId: nodeId,
    duration: tool.duration,
    tool: tool.tool,
    toolName: tool.toolName,
    description: tool.description,
    status: finalStatus, // 使用智能判断后的状态
    startTime: startTime,
    endTime: endTime,
    result:
      tool.result ||
      (window.I18nService
        ? window.I18nService.t("tool_execution_complete").replace(
            "{toolName}",
            tool.toolName
          )
        : `工具 ${tool.toolName} 执行完成`),
    error: finalStatus === "failed" ? "工具执行失败" : null,
    url: tool.url || null, // 添加url属性
    path: tool.path || null, // 添加path属性
    // 保留原始参数及结构化结果，便于右侧"电脑区"详细展示（特别是代码执行器）
    tool_args: tool.tool_args || null,
    raw_result: tool.raw_result || null,
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
    if (panel.classList.contains("show")) {
      // 强制设置固定位置，不调用 updatePanelPosition 避免复杂计算
      panel.style.top = "50px";
      panel.style.left = "16px";
    }
  });
}

// 强制更新指定面板位置（用于调试）
function forceUpdatePanelPosition(nodeId) {
  const panel = nodeToolPanels.get(nodeId);
  if (panel && panel.classList.contains("show")) {
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
  },
};

// 文件上传相关函数
function initFileUpload() {
  const fileInput = document.getElementById("file-input");
  const fileUploadButton = document.getElementById("file-upload-button");
  const uploadedFilesContainer = document.getElementById(
    "uploaded-files-container"
  );
  const uploadedFilesList = document.getElementById("uploaded-files-list");
  const clearFilesButton = document.getElementById("clear-files-button");

  const initialFileInput = document.getElementById("initial-file-input");
  const initialFileUploadButton = document.getElementById(
    "initial-file-upload-button"
  );
  const initialUploadedFilesContainer = document.getElementById(
    "initial-uploaded-files-container"
  );
  const initialUploadedFilesList = document.getElementById(
    "initial-uploaded-files-list"
  );
  const initialClearFilesButton = document.getElementById(
    "initial-clear-files-button"
  );

  // 显示上传的文件列表
  function displayUploadedFiles(files, container, listElement) {
    if (files.length === 0) {
      container.style.display = "none";
      return;
    }
    container.style.display = "block";
    listElement.innerHTML = "";
    files.forEach((file, index) => {
      const fileItem = document.createElement("div");
      fileItem.className = "uploaded-file-item";
      fileItem.innerHTML = `
                <span class="file-name">${file.filename || file.name}</span>
                <span class="file-size">${
                  file.size_mb ? file.size_mb + " MB" : ""
                }</span>
                <button class="remove-file-button" data-index="${index}" title="移除文件">×</button>
            `;
      listElement.appendChild(fileItem);
    });
  }

  // 处理文件上传
  async function handleFileUpload(files, container, listElement) {
    if (!files || files.length === 0) return;

    try {
      const uploadedFiles = await window.messageService.uploadFiles(files);
      const currentFiles = window.messageService.getUploadedFilesInfo();
      const allFiles = [...currentFiles, ...uploadedFiles];
      window.messageService.setUploadedFilesInfo(allFiles);
      displayUploadedFiles(allFiles, container, listElement);
    } catch (error) {
      console.error("文件上传失败:", error);
      alert("文件上传失败: " + error.message);
    }
  }

  // 主输入框文件上传
  if (fileUploadButton && fileInput) {
    fileUploadButton.addEventListener("click", () => {
      fileInput.click();
    });

    fileInput.addEventListener("change", async (e) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        await handleFileUpload(
          files,
          uploadedFilesContainer,
          uploadedFilesList
        );
        fileInput.value = ""; // 清空input，允许重复选择同一文件
      }
    });
  }

  // 初始输入框文件上传
  if (initialFileUploadButton && initialFileInput) {
    initialFileUploadButton.addEventListener("click", () => {
      initialFileInput.click();
    });

    initialFileInput.addEventListener("change", async (e) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        await handleFileUpload(
          files,
          initialUploadedFilesContainer,
          initialUploadedFilesList
        );
        initialFileInput.value = "";
      }
    });
  }

  // 清除文件
  if (clearFilesButton) {
    clearFilesButton.addEventListener("click", () => {
      window.messageService.clearUploadedFiles();
      displayUploadedFiles([], uploadedFilesContainer, uploadedFilesList);
    });
  }

  if (initialClearFilesButton) {
    initialClearFilesButton.addEventListener("click", () => {
      window.messageService.clearUploadedFiles();
      displayUploadedFiles(
        [],
        initialUploadedFilesContainer,
        initialUploadedFilesList
      );
    });
  }

  // 移除单个文件（事件委托）
  if (uploadedFilesList) {
    uploadedFilesList.addEventListener("click", (e) => {
      if (e.target.classList.contains("remove-file-button")) {
        const index = parseInt(e.target.getAttribute("data-index"));
        const files = window.messageService.getUploadedFilesInfo();
        files.splice(index, 1);
        window.messageService.setUploadedFilesInfo(files);
        displayUploadedFiles(files, uploadedFilesContainer, uploadedFilesList);
      }
    });
  }

  if (initialUploadedFilesList) {
    initialUploadedFilesList.addEventListener("click", (e) => {
      if (e.target.classList.contains("remove-file-button")) {
        const index = parseInt(e.target.getAttribute("data-index"));
        const files = window.messageService.getUploadedFilesInfo();
        files.splice(index, 1);
        window.messageService.setUploadedFilesInfo(files);
        displayUploadedFiles(
          files,
          initialUploadedFilesContainer,
          initialUploadedFilesList
        );
      }
    });
  }
}

// 输入框处理函数
function initInputHandler() {
  const messageInput = document.getElementById("message-input");
  const sendButton = document.getElementById("send-button");
  const replayButton = document.getElementById("replay-button");
  const initialMessageInput = document.getElementById("initial-message-input");
  const initialSendButton = document.getElementById("initial-send-button");

  // 初始化输入框处理
  if (messageInput && sendButton) {
    // 发送消息函数（尾部2个以上空格 => 回放）
    function sendMessage() {
      credibilityService.clearCredibilityData();
      const raw = messageInput.value;
      const endsWithMultiSpaces = /\s{2,}$/.test(raw);
      const message = raw.trim();
      if (message) {
        console.log("发送消息:", message);
        // 清理之前的tool events和UI状态
        if (
          window.messageService &&
          typeof window.messageService.clearStepToolEvents === "function"
        ) {
          window.messageService.clearStepToolEvents();
        }

        // 关闭所有已打开的工具面板
        if (nodeToolPanels && nodeToolPanels.size > 0) {
          const panelIds = Array.from(nodeToolPanels.keys());
          panelIds.forEach((nodeId) => {
            try {
              closeNodeToolPanel(nodeId);
            } catch (_) {}
          });
          if (nodeToolPanels.clear) nodeToolPanels.clear();
        }

        // 清理右侧内容
        try {
          cleanupAllResources();
        } catch (_) {}
        if (
          endsWithMultiSpaces &&
          window.messageService &&
          typeof window.messageService.sendReplay === "function"
        ) {
          window.messageService.sendReplay();
        } else {
          messageService.sendMessage(message);
        }
        // 清空输入框
        messageInput.value = "";
      }
    }

    // 点击发送按钮
    sendButton.addEventListener("click", sendMessage);

    // 按回车键发送（同样处理尾部空格触发回放）
    messageInput.addEventListener("keypress", function (e) {
      if (e.key === "Enter") {
        sendMessage();
      }
    });

    // 输入框获得焦点时的样式
    messageInput.addEventListener("focus", function () {
      sendButton.style.color = "#007bff";
    });

    // 输入框失去焦点时的样式
    messageInput.addEventListener("blur", function () {
      sendButton.style.color = "#666";
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
        if (
          typeof window !== "undefined" &&
          typeof window.resetSessionCaches === "function"
        ) {
          window.resetSessionCaches();
        } else {
          // 安全回退：尽力关闭面板与清理资源
          try {
            if (nodeToolPanels && nodeToolPanels.size > 0) {
              Array.from(nodeToolPanels.keys()).forEach((id) => {
                try {
                  closeNodeToolPanel(id);
                } catch (_) {}
              });
              if (nodeToolPanels.clear) nodeToolPanels.clear();
            }
          } catch (_) {}
          try {
            cleanupAllResources();
          } catch (_) {}
          try {
            localStorage.removeItem("cosight:lastManusStep");
          } catch (_) {}
        }
      } catch (_) {}

      console.log("发送初始消息:", message);
      // 隐藏初始输入框并显示主界面
      hideInitialInputAndShowMain(message);
      // 根据末尾空格决定回放还是正常请求
      try {
        cleanupAllResources();
      } catch (_) {}
      if (
        endsWithMultiSpaces &&
        window.messageService &&
        typeof window.messageService.sendReplay === "function"
      ) {
        window.messageService.sendReplay();
      } else if (
        window.messageService &&
        typeof window.messageService.sendMessage === "function" &&
        message
      ) {
        window.messageService.sendMessage(message);
      }
    }

    // 点击发送按钮
    initialSendButton.addEventListener("click", sendInitialMessage);

    // 按回车发送
    initialMessageInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendInitialMessage();
      }
    });

    // 自动调整文本框高度
    initialMessageInput.addEventListener("input", function () {
      this.style.height = "auto";
      this.style.height = Math.min(this.scrollHeight, 200) + "px";
    });

    // 页面加载完成后自动让初始输入框获得焦点
    setTimeout(() => {
      initialMessageInput.focus();
    }, 100);
  }
}

// 隐藏初始输入框并显示主界面
function hideInitialInputAndShowMain(message) {
  const initialInputContainer = document.querySelector(
    ".initial-input-container"
  );
  const middleContainer = document.querySelector(".middle-container");

  if (initialInputContainer && middleContainer) {
    // 隐藏初始输入框
    initialInputContainer.classList.add("hidden");

    // 延迟显示主界面，让过渡动画更流畅
    setTimeout(() => {
      middleContainer.classList.add("show");
      // 仅负责界面切换；消息发送交由调用方控制
    }, 300); // 等待初始输入框的隐藏动画完成
  }
}

function updateDynamicTitle(title) {
  const titleContainer = document.getElementById("title-container");
  const dynamicTitle = document.getElementById("dynamic-title");
  if (titleContainer && dynamicTitle) {
    dynamicTitle.textContent = title;
    titleContainer.style.opacity = "1";
  }
}

// 生成状态文本
function generateStatusText(tool, url, path, status, result) {
  if (tool === "file_read") {
    const fileName = path
      ? path.split("/").pop() || path.split("\\").pop()
      : window.I18nService
      ? window.I18nService.t("unknown_file")
      : "未知文件";
    return window.I18nService
      ? window.I18nService.t("reading_file").replace("{fileName}", fileName)
      : `正在读取文件 ${fileName}`;
  } else if (tool === "file_saver") {
    const fileName = path
      ? path.split("/").pop() || path.split("\\").pop()
      : window.I18nService
      ? window.I18nService.t("unknown_file")
      : "未知文件";
    // 如果工具已完成，显示完成信息而不是"正在保存"
    if (status && status !== "running") {
      // 如果有结果文本，优先使用结果文本
      if (result && typeof result === "string" && result.trim()) {
        return result;
      }
      // 否则显示文件已保存的信息
      return window.I18nService
        ? window.I18nService.t("file_saved").replace("{fileName}", fileName)
        : `文件已保存: ${fileName}`;
    }
    return window.I18nService
      ? window.I18nService.t("saving_file").replace("{fileName}", fileName)
      : `正在保存文件 ${fileName}`;
  } else if (
    tool === "search_baidu" ||
    tool === "search_google" ||
    tool === "tavily_search" ||
    tool === "image_search"
  ) {
    return window.I18nService
      ? window.I18nService.t("browsing_url").replace("{url}", url)
      : `正在浏览 ${url}`;
  } else if (url) {
    return window.I18nService
      ? window.I18nService.t("browsing_url").replace("{url}", url)
      : `正在浏览 ${url}`;
  } else if (path) {
    const fileName = path.split("/").pop() || path.split("\\").pop();
    return window.I18nService
      ? window.I18nService.t("processing_file").replace("{fileName}", fileName)
      : `正在处理文件 ${fileName}`;
  }
  return window.I18nService
    ? window.I18nService.t("processing")
    : "正在处理...";
}

function toggleLoadingIndicator(isShow) {
  const loadingIndicator = document.getElementById("loading-indicator");
  if (loadingIndicator) {
    loadingIndicator.style.display = isShow ? "flex" : "none";
  }
}

// 清理iframe和相关资源
function cleanupContentResources() {
  const iframe = document.getElementById("content-iframe");
  const markdownContent = document.getElementById("markdown-content");

  if (iframe) {
    // 清理事件监听器
    iframe.onload = null;
    iframe.onerror = null;

    // 清理iframe内容
    iframe.src = "about:blank";

    // 清理可能存在的超时定时器
    if (iframe._loadingTimeout) {
      clearTimeout(iframe._loadingTimeout);
      iframe._loadingTimeout = null;
    }
  }

  if (markdownContent) {
    // 清理markdown内容
    markdownContent.innerHTML = "";
  }

  // 隐藏加载指示器
  toggleLoadingIndicator(false);

  console.log("iframe资源清理完成");
}

// 全面的内存清理机制
function cleanupAllResources() {
  console.log("开始全面资源清理...");

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
  const rightContainer = document.getElementById("right-container");
  if (rightContainer) {
    // 移除可能的事件监听器
    rightContainer.onclick = null;
    rightContainer.onmouseover = null;
    rightContainer.onmouseout = null;
  }

  // 4. 清理工具提示
  const tooltip = d3.select("#tooltip");
  if (tooltip && !tooltip.empty()) {
    tooltip.style("opacity", 0);
  }

  const stepsTooltip = document.getElementById("steps-tooltip");
  if (stepsTooltip) {
    stepsTooltip.classList.remove("show");
  }

  // 5. 强制垃圾回收（如果浏览器支持）
  if (window.gc && typeof window.gc === "function") {
    try {
      window.gc();
      console.log("执行了垃圾回收");
    } catch (e) {
      console.log("垃圾回收不可用");
    }
  }

  // 6. 清理可能的内存泄漏
  if (window.performance && window.performance.memory) {
    const memory = window.performance.memory;
    console.log("内存使用情况:", {
      used: Math.round(memory.usedJSHeapSize / 1024 / 1024) + "MB",
      total: Math.round(memory.totalJSHeapSize / 1024 / 1024) + "MB",
      limit: Math.round(memory.jsHeapSizeLimit / 1024 / 1024) + "MB",
    });
  }

  console.log("全面资源清理完成");
}

// 检查并恢复DAG数据
function checkAndRestoreDAGData() {
  try {
    // F5刷新场景：只清理UI状态，保留localStorage数据
    resetUICaches();

    // 检查是否有保存的manus step消息
    const lastManusStep = getLastManusStepMessage();
    if (lastManusStep) {
      console.log("发现保存的DAG数据，开始恢复...");

      // 恢复DAG图
      const result = createDag(lastManusStep);
      if (result) {
        // 显示标题
        const initData = lastManusStep.content || lastManusStep.data?.initData;
        if (initData && initData.title) {
          updateDynamicTitle(initData.title);
        }

        // 显示主界面
        hideInitialInputAndShowMain("");

        console.log("DAG数据恢复完成");
      }
    }
  } catch (e) {
    console.warn("恢复DAG数据失败:", e);
  }
}

// 页面加载完成后初始化
// 显示右侧面板内容
function showRightPanel() {
  const rightContainer = document.getElementById("right-container");
  if (!rightContainer) return false;

  // 先清理之前的资源
  cleanupContentResources();

  // 显示右侧容器
  rightContainer.classList.add("show");

  // 切换按钮紧凑模式
  toggleButtonsCompactMode(true);
  setTimeout(() => handleResize(), 500);

  // 检查并重新定位步骤信息弹窗
  setTimeout(() => {
    const stepsTooltip = document.getElementById("steps-tooltip");
    if (stepsTooltip && stepsTooltip.classList.contains("show")) {
      // 如果步骤信息弹窗正在显示，重新计算其位置
      showStepsTooltip();
    }
  }, 300); // 稍微延迟确保布局变化完成

  return true;
}

function showRightPanelForTool(toolCall) {
  const result = showRightPanel();
  if (!result) {
    return;
  }

  const url = toolCall.url;
  const path = toolCall.path;
  const tool = toolCall.tool;
  const iframe = document.getElementById("content-iframe");
  const markdownContent = document.getElementById("markdown-content");
  const statusElement = document.getElementById("right-container-status");

  if (url) {
    // 显示加载提示
    toggleLoadingIndicator(true);

    // 更新状态文本
    if (statusElement) {
      const status = toolCall?.status;
      const result = toolCall?.result;
      statusElement.textContent = generateStatusText(
        tool,
        url,
        path,
        status,
        result
      );
      statusElement.className = "loading";
    }

    // 设置iframe显示
    iframe.style.display = "block";
    markdownContent.style.display = "none";

    // 先设置为空白页
    iframe.src = "about:blank";

    // 检查iframe嵌入是否被允许
    checkIframeEmbedding(url)
      .then((allowed) => {
        if (allowed) {
          // 允许嵌入，继续加载
          loadIframeContent(url, iframe, statusElement, tool, path);
        } else {
          // 不允许嵌入，显示错误和替代方案
          showIframeEmbeddingError(url, statusElement);
        }
      })
      .catch((error) => {
        console.warn("iframe嵌入检查失败，尝试直接加载:", error);
        // 检查失败时允许尝试加载
        loadIframeContent(url, iframe, statusElement, tool, path);
      });
  } else if (path) {
    // 处理代码执行工具的特殊情况
    if (path === "code://execute_code") {
      // 显示代码内容
      iframe.style.display = "none";
      markdownContent.style.display = "block";

      if (statusElement) {
        const status = toolCall?.status;
        const result = toolCall?.result;
        statusElement.textContent = generateStatusText(
          tool,
          url,
          path,
          status,
          result
        );
        statusElement.className = "success";
      }

      // 显示代码内容
      displayCodeContent(toolCall);
      console.log("显示代码执行内容");
      return;
    }

    // 根据扩展名决定渲染方式
    const fileName = path.split("/").pop() || path.split("\\").pop() || "";
    const ext = (fileName.split(".").pop() || "").toLowerCase();

    // 将绝对路径转换为相对路径（与 loadMarkdownFile 保持一致）
    let relativePath = path;
    // 如果路径已经是完整的API路径（以/api/开头），直接使用
    if (relativePath.startsWith("/api/")) {
      relativePath = path;
    } else if (relativePath.includes("work_space")) {
      // 提取work_space之后的路径部分
      const workspaceIndex = relativePath.indexOf("work_space");
      if (workspaceIndex !== -1) {
        relativePath = relativePath.substring(workspaceIndex);
      }
    } else if (relativePath.includes("workspace")) {
      // 兼容旧的workspace命名
      const workspaceIndex = relativePath.indexOf("workspace");
      if (workspaceIndex !== -1) {
        relativePath = relativePath.substring(workspaceIndex);
      }
    }

    if (ext === "html" || ext === "htm") {
      // 使用 iframe 显示 HTML 文件
      toggleLoadingIndicator(true);
      if (statusElement) {
        const status = toolCall?.status;
        const result = toolCall?.result;
        statusElement.textContent = generateStatusText(
          tool,
          url,
          path,
          status,
          result
        );
        statusElement.className = "loading";
      }

      iframe.style.display = "block";
      markdownContent.style.display = "none";

      // 清空后再加载
      iframe.src = "about:blank";
      setTimeout(() => {
        let isBlank = true;
        iframe._loadingTimeout = setTimeout(() => {
          if (isBlank) return;
          toggleLoadingIndicator(false);
          if (statusElement) {
            statusElement.textContent = window.I18nService
              ? window.I18nService.t("loading_timeout").replace(
                  "{url}",
                  relativePath
                )
              : `加载超时: ${relativePath}`;
            statusElement.className = "error";
          }
          console.warn("iframe加载超时:", relativePath);
        }, 10000);

        iframe.onload = function () {
          if (isBlank) return;
          if (iframe._loadingTimeout) {
            clearTimeout(iframe._loadingTimeout);
            iframe._loadingTimeout = null;
          }
          toggleLoadingIndicator(false);
          if (statusElement) {
            const status = toolCall?.status;
            const result = toolCall?.result;
            statusElement.textContent = generateStatusText(
              tool,
              url,
              path,
              status,
              result
            );
            statusElement.className = "success";
          }
          console.log("HTML 文件加载成功:", relativePath);
        };

        iframe.onerror = function () {
          if (iframe._loadingTimeout) {
            clearTimeout(iframe._loadingTimeout);
            iframe._loadingTimeout = null;
          }
          toggleLoadingIndicator(false);
          if (statusElement) {
            statusElement.textContent = window.I18nService
              ? window.I18nService.t("webpage_load_failed").replace(
                  "{url}",
                  relativePath
                )
              : `网页加载失败: ${relativePath}`;
            statusElement.className = "error";
          }
          console.error("HTML 文件加载失败:", relativePath);
        };

        iframe.src = relativePath;
        isBlank = false;
      }, 100);

      console.log("通过 iframe 显示 HTML 文件:", relativePath);
    } else {
      // 显示 Markdown/文本内容
      iframe.style.display = "none";
      markdownContent.style.display = "block";

      if (statusElement) {
        const status = toolCall?.status;
        const result = toolCall?.result;
        statusElement.textContent = generateStatusText(
          tool,
          url,
          path,
          status,
          result
        );
        statusElement.className = "loading";
      }

      loadMarkdownFile(path, tool, toolCall);
      console.log("显示文件内容:", path);
    }
  }
}

// 显示代码执行内容
function displayCodeContent(toolCall) {
  const markdownContent = document.getElementById("markdown-content");

  // 解析工具参数获取代码内容
  let codeContent = "";
  let executionResult = "";

  try {
    // 优先使用结构化结果中的 code_content / output（后端已截断与清洗）
    const processed = toolCall.raw_result;
    if (
      processed &&
      typeof processed === "object" &&
      processed.tool_type === "code_execution"
    ) {
      if (processed.code_content) {
        codeContent = processed.code_content;
      }
      if (processed.output) {
        executionResult = processed.output;
      }
    }

    // 若仍无代码内容，再尝试从工具参数中解析
    if (!codeContent) {
      try {
        const args = JSON.parse(toolCall.tool_args || "{}");
        if (args.code) {
          codeContent = args.code;
        }
      } catch (_) {
        // tool_args 可能不是 JSON，忽略解析错误
      }
    }

    // 兜底：如果依然没有代码内容，但结果里含有代码块，则尝试从结果中提取
    if (!codeContent && typeof toolCall.result === "string") {
      const text = toolCall.result;
      const fenceStart = text.indexOf("```");
      if (fenceStart >= 0) {
        const fenceEnd = text.indexOf("```", fenceStart + 3);
        if (fenceEnd > fenceStart) {
          // 去掉开头的 ```py / ``` 之类前缀
          const firstLineBreak = text.indexOf("\n", fenceStart + 3);
          const codeStart =
            firstLineBreak > 0 && firstLineBreak < fenceEnd
              ? firstLineBreak + 1
              : fenceStart + 3;
          codeContent = text.substring(codeStart, fenceEnd).trim();
        }
      }
    }

    // 如果前面没能拿到输出，则退回到 toolCall.result
    if (!executionResult && toolCall.result) {
      executionResult =
        typeof toolCall.result === "string"
          ? toolCall.result
          : JSON.stringify(toolCall.result, null, 2);
    }
  } catch (e) {
    console.warn("解析代码执行工具参数或结果失败:", e);
    if (!codeContent) {
      codeContent = "无法解析代码内容";
    }
  }

  // 计算执行状态
  // 规则说明：
  // 1）优先使用工具本身的 status（completed / running / failed）
  // 2）在 status 不是明确 failed 的情况下，再根据输出内容做一次兜底判断：
  //    - 若执行结果中包含明显的错误标记（Traceback / Exception / 'Error:' / '错误' 等），则视为失败
  //    - 否则视为成功
  let statusClass = toolCall.status || "completed";
  let statusText =
    toolCall.status === "running"
      ? "执行中"
      : toolCall.status === "failed"
      ? "失败"
      : "成功";

  try {
    // 仅当当前状态不是失败时，才根据输出内容再做一次判断，避免覆盖明确的失败状态
    if (statusClass !== "failed") {
      const textSource =
        typeof executionResult === "string" && executionResult
          ? executionResult
          : typeof toolCall.result === "string"
          ? toolCall.result
          : "";

      const lowered = (textSource || "").toLowerCase();
      const hasErrorPattern =
        /traceback \(most recent call last\)/i.test(textSource) ||
        /exception[:\s]/i.test(textSource) ||
        /error[:\s]/i.test(textSource) ||
        lowered.includes("nameerror") ||
        textSource.includes("错误");

      if (hasErrorPattern) {
        statusClass = "failed";
        statusText = "失败";
      } else {
        statusClass = "completed";
        statusText = "成功";
      }
    }
  } catch (e) {
    console.warn("解析代码执行状态失败:", e);
  }

  // 生成HTML内容
  const htmlContent = `
        <div class="code-execution-content">
            <h3><i class="fas fa-code"></i> 代码执行详情</h3>
            
            <div class="code-section">
                <h4><i class="fas fa-file-code"></i> 执行的代码</h4>
                <div class="code-block collapsible-block collapsible-code">
                    <pre><code class="language-python">${escapeHtml(
                      codeContent
                    )}</code></pre>
                </div>
                <button class="toggle-block-btn" data-target="code">展开全部</button>
            </div>
            
            ${
              executionResult
                ? `
            <div class="result-section">
                <h4><i class="fas fa-terminal"></i> 执行结果</h4>
                <div class="result-block collapsible-block collapsible-result">
                    <pre><code>${escapeHtml(executionResult)}</code></pre>
                </div>
                <button class="toggle-block-btn" data-target="result">展开全部</button>
            </div>
            `
                : ""
            }
            
            <div class="tool-info">
                <h4><i class="fas fa-info-circle"></i> 工具信息</h4>
                <ul>
                    <li><strong>工具名称:</strong> ${
                      toolCall.toolName || "代码执行器"
                    }</li>
                    <li><strong>执行状态:</strong> <span class="status-${statusClass}">${statusText}</span></li>
                    ${
                      toolCall.duration
                        ? `<li><strong>执行时间:</strong> ${(
                            toolCall.duration / 1000
                          ).toFixed(2)} 秒</li>`
                        : ""
                    }
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

            /* 折叠 / 展开区域样式 */
            .collapsible-block {
                max-height: 260px;
                overflow: auto;
                position: relative;
            }

            .collapsible-block.expanded {
                max-height: none;
            }

            .toggle-block-btn {
                margin-top: 8px;
                padding: 4px 10px;
                font-size: 12px;
                border-radius: 4px;
                border: 1px solid #3498db;
                background-color: #ffffff;
                color: #3498db;
                cursor: pointer;
            }

            .toggle-block-btn:hover {
                background-color: #ecf5ff;
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

  // 绑定折叠 / 展开按钮事件
  try {
    const container = markdownContent.querySelector(".code-execution-content");
    if (container) {
      const buttons = container.querySelectorAll(".toggle-block-btn");
      buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const target = btn.getAttribute("data-target");
          const block = container.querySelector(
            target === "code"
              ? ".collapsible-code"
              : target === "result"
              ? ".collapsible-result"
              : null
          );
          if (!block) return;

          const isExpanded = block.classList.toggle("expanded");
          btn.textContent = isExpanded ? "收起" : "展开全部";
        });
      });
    }
  } catch (e) {
    console.warn("绑定代码折叠/展开事件失败:", e);
  }
}

// HTML转义函数
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// 加载并显示markdown文件
function loadMarkdownFile(filePath, tool, toolCall) {
  const markdownContent = document.getElementById("markdown-content");
  const statusElement = document.getElementById("right-container-status");

  // 显示加载状态
  markdownContent.innerHTML = `<div style="text-align: center; padding: 50px;"><i class="fas fa-spinner fa-spin"></i> ${
    window.I18nService
      ? window.I18nService.t("loading_file")
      : "正在加载文件..."
  }</div>`;

  // 更新状态文本
  if (statusElement) {
    const status = toolCall?.status;
    const result = toolCall?.result;
    statusElement.textContent = generateStatusText(
      tool,
      null,
      filePath,
      status,
      result
    );
    statusElement.className = "loading";
  }

  // 将绝对路径转换为相对路径
  let relativePath = filePath;
  // 如果路径已经是完整的API路径（以/api/开头），直接使用
  if (filePath.startsWith("/api/")) {
    relativePath = filePath;
  } else if (filePath.includes("work_space")) {
    // 提取work_space之后的路径部分
    const workspaceIndex = filePath.indexOf("work_space");
    if (workspaceIndex !== -1) {
      relativePath = filePath.substring(workspaceIndex);
    }
  } else if (filePath.includes("workspace")) {
    // 兼容旧的workspace命名
    const workspaceIndex = filePath.indexOf("workspace");
    if (workspaceIndex !== -1) {
      relativePath = filePath.substring(workspaceIndex);
    }
  }

  console.log("尝试加载文件:", relativePath);

  // 使用fetch加载文件内容
  fetch(relativePath)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // 更新状态文本
      if (statusElement) {
        const fileName =
          filePath.split("/").pop() || filePath.split("\\").pop();
        statusElement.textContent = window.I18nService
          ? window.I18nService.t("parsing_file").replace("{fileName}", fileName)
          : `正在解析文件 ${fileName}`;
        statusElement.className = "loading";
      }

      return response.text();
    })
    .then((content) => {
      // 判断文件类型
      const fileName = filePath.split("/").pop() || filePath.split("\\").pop();
      const fileExtension = fileName.split(".").pop().toLowerCase();

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
        const status = toolCall?.status;
        const result = toolCall?.result;
        statusElement.textContent = generateStatusText(
          tool,
          null,
          filePath,
          status,
          result
        );
        statusElement.className = "success";
      }
    })
    .catch((error) => {
      console.error("加载文件失败:", error);
      markdownContent.innerHTML = `
                <div style="text-align: center; padding: 50px; color: #f44336;">
                    <i class="fas fa-exclamation-triangle"></i>
                    <h3>${
                      window.I18nService
                        ? window.I18nService.t("file_load_failed_title")
                        : "文件加载失败"
                    }</h3>
                    <p>${
                      window.I18nService
                        ? window.I18nService.t("unable_to_load_file").replace(
                            "{filePath}",
                            filePath
                          )
                        : `无法加载文件: ${filePath}`
                    }</p>
                    <p>${
                      window.I18nService
                        ? window.I18nService.t("error_message").replace(
                            "{message}",
                            error.message
                          )
                        : `错误信息: ${error.message}`
                    }</p>
                </div>
            `;

      // 更新状态文本
      if (statusElement) {
        const fileName =
          filePath.split("/").pop() || filePath.split("\\").pop();
        statusElement.textContent = window.I18nService
          ? window.I18nService.t("file_load_failed").replace(
              "{fileName}",
              fileName
            )
          : `文件 ${fileName} 加载失败`;
        statusElement.className = "error";
      }
    });
}

// 切换右侧容器显示/隐藏
function toggleRightContainer() {
  const rightContainer = document.getElementById("right-container");
  if (rightContainer) {
    rightContainer.classList.toggle("show");

    const isShow = rightContainer.classList.contains("show");
    const timeout = isShow ? 0 : 350;

    setTimeout(() => {
      // 切换所有按钮的紧凑模式
      toggleButtonsCompactMode(isShow);
      setTimeout(() => {
        handleResize();

        // 检查并重新定位步骤信息弹窗
        const stepsTooltip = document.getElementById("steps-tooltip");
        if (stepsTooltip && stepsTooltip.classList.contains("show")) {
          // 如果步骤信息弹窗正在显示，重新计算其位置
          showStepsTooltip();
        }
      }, 500);
    }, timeout);
  }
}

function toggleMaximizePanel() {
  const leftContainer = document.querySelector(".left-container");
  const rightContainer = document.getElementById("right-container");
  const toggleIcon = document.querySelector("#toggle-maximize-btn i");

  // 使用 requestAnimationFrame 优化DOM操作
  requestAnimationFrame(() => {
    leftContainer.classList.toggle("hidden");
    rightContainer.classList.toggle("maximized");

    if (toggleIcon.classList.contains("fa-expand-alt")) {
      toggleIcon.classList.remove("fa-expand-alt");
      toggleIcon.classList.add("fa-compress-alt");

      // 批量处理面板隐藏，减少重排
      requestAnimationFrame(() => {
        nodeToolPanels.forEach((panel) => {
          panel.classList.add("tucked-left");
        });
      });
    } else {
      toggleIcon.classList.remove("fa-compress-alt");
      toggleIcon.classList.add("fa-expand-alt");

      // 批量处理面板显示，减少重排
      requestAnimationFrame(() => {
        nodeToolPanels.forEach((panel) => {
          panel.classList.remove("tucked-left");
        });
      });
    }
  });
}

// 切换按钮的紧凑模式
function toggleButtonsCompactMode(isCompact) {
  const buttons = document.querySelectorAll(".controls .btn");
  buttons.forEach((button) => {
    if (isCompact) {
      button.classList.add("compact");
    } else {
      button.classList.remove("compact");
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

  const stepsTooltip = document.getElementById("steps-tooltip");
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
    const dynamicTitle = document.getElementById("dynamic-title");
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
  stepsTooltip.classList.add("show");
}

// 隐藏步骤列表tooltip
function hideStepsTooltip() {
  // 添加延迟隐藏，避免鼠标快速移动时闪烁
  stepsTooltipTimeout = setTimeout(() => {
    const stepsTooltip = document.getElementById("steps-tooltip");
    if (stepsTooltip) {
      stepsTooltip.classList.remove("show");
    }
  }, 100);
}

// 生成步骤列表HTML
function generateStepsListHtml() {
  const steps = dagData.nodes;
  let html = `<h4>${
    window.I18nService
      ? window.I18nService.t("task_steps_list")
      : "任务步骤列表"
  }</h4>`;

  steps.forEach((step) => {
    const statusClass = step.status || "not_started";
    const statusText = getStatusText(step.status);

    html += `
            <div class="step-item">
                <div class="step-status ${statusClass}"></div>
                <div class="step-text">${step.name} - ${
      step.fullName || step.title || ""
    }</div>
            </div>
        `;
  });

  return html;
}

// 获取状态文本
function getStatusText(status) {
  const statusMap = {
    completed: "已完成",
    in_progress: "进行中",
    blocked: "阻塞",
    not_started: "未开始",
  };
  return statusMap[status] || "未知";
}

// 新会话重置：清空工具调用与面板缓存，并清理本地存储
function resetSessionCaches() {
  try {
    // 停止所有进行中的工具调用（标记为失败并移入历史，避免悬挂状态）
    if (activeToolCalls && activeToolCalls.size > 0) {
      const ids = Array.from(activeToolCalls.keys());
      ids.forEach((id) => {
        try {
          completeToolCall(id, "会话已重置，调用中止", false);
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
      panelIds.forEach((nodeId) => {
        try {
          closeNodeToolPanel(nodeId);
        } catch (_) {}
      });
      if (nodeToolPanels.clear) nodeToolPanels.clear();
    }
    // 清理MessageService的tool events
    if (
      window.messageService &&
      typeof window.messageService.clearStepToolEvents === "function"
    ) {
      window.messageService.clearStepToolEvents();
    }
    // 右侧内容与资源清理
    try {
      cleanupAllResources();
    } catch (_) {}

    // 清理本地存储中的上一会话记录，避免回退读取旧数据
    try {
      localStorage.removeItem("cosight:lastManusStep");
      localStorage.removeItem("cosight:stepToolEvents");
      localStorage.removeItem("cosight:planIdByTopic");
      localStorage.removeItem("cosight:pendingRequests");
    } catch (_) {}

    // 标记全局面板容器为空
    const container = document.getElementById("tool-call-panels-container");
    if (container) {
      container.innerHTML = "";
    }

    console.log("[session] 缓存已重置");
  } catch (e) {
    console.warn("重置会话缓存时发生异常:", e);
  }
}

// F5刷新时的清理（页面加载场景）- 只清理UI状态，保留localStorage数据
function resetUICaches() {
  try {
    // 停止所有进行中的工具调用（标记为失败并移入历史，避免悬挂状态）
    if (activeToolCalls && activeToolCalls.size > 0) {
      const ids = Array.from(activeToolCalls.keys());
      ids.forEach((id) => {
        try {
          completeToolCall(id, "页面刷新，调用中止", false);
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
      panelIds.forEach((nodeId) => {
        try {
          closeNodeToolPanel(nodeId);
        } catch (_) {}
      });
      if (nodeToolPanels.clear) nodeToolPanels.clear();
    }

    // 清理MessageService的tool events
    if (
      window.messageService &&
      typeof window.messageService.clearStepToolEvents === "function"
    ) {
      window.messageService.clearStepToolEvents();
    }

    // 右侧内容与资源清理
    try {
      cleanupAllResources();
    } catch (_) {}

    // 标记全局面板容器为空
    const container = document.getElementById("tool-call-panels-container");
    if (container) {
      container.innerHTML = "";
    }

    console.log("[UI] 缓存已重置（保留localStorage数据）");
  } catch (e) {
    console.warn("重置UI缓存时发生异常:", e);
  }
}

// 暴露到全局，便于其他模块触发
if (typeof window !== "undefined") {
  window.resetSessionCaches = resetSessionCaches;
  window.resetUICaches = resetUICaches;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    initInputHandler,
    initFileUpload,
    closeAllVerificationTooltips,
    hideVerificationTooltip,
    showStepsTooltip,
    hideStepsTooltip,
    toggleRightContainer,
    toggleMaximizePanel,
    // 导出会话重置能力
    resetSessionCaches,
  };
}

// 从搜索工具结果中提取URL
function extractUrlFromSearchResult(toolResult, toolName) {
  if (!toolResult) return null;

  // 统一字符串中的 Python 常量为 JSON 常量，便于后续解析
  const normalizePythonLiterals = (s) =>
    s
      .replace(/\bNone\b/g, "null")
      .replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false")
      .replace(/\\'/g, "'");

  let parsed = null;

  // 情况1：已是对象
  if (typeof toolResult === "object") {
    parsed = toolResult;
  } else if (typeof toolResult === "string") {
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
          const fn = new Function("return (" + s + ")");
          parsed = fn();
        }
      } catch (e2) {
        console.warn("extractUrlFromSearchResult 解析失败:", e2);
        parsed = null;
      }
    }
  }

  if (!parsed) return null;

  const name = String(toolName || "").toLowerCase();

  if (name === "tavily_search" || name === "search_tavily") {
    // tavily_search 结构: { results: [ { url } ] }
    if (
      parsed.results &&
      Array.isArray(parsed.results) &&
      parsed.results.length > 0
    ) {
      const first =
        parsed.results.find((it) => it && (it.url || it.link)) ||
        parsed.results[0];
      return (first && (first.url || first.link)) || null;
    }
  } else if (name === "image_search") {
    // image_search 结构: { content: { 0: { url } } }
    if (parsed.content && typeof parsed.content === "object") {
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
      const withUrl =
        parsed.find((it) => it && (it.url || it.link)) || parsed[0];
      return (withUrl && (withUrl.url || withUrl.link)) || null;
    }
    if (parsed && typeof parsed === "object") {
      if (Array.isArray(parsed.results) && parsed.results.length > 0) {
        const first =
          parsed.results.find((it) => it && (it.url || it.link)) ||
          parsed.results[0];
        return (first && (first.url || first.link)) || null;
      }
      if (Array.isArray(parsed.items) && parsed.items.length > 0) {
        const first =
          parsed.items.find((it) => it && (it.url || it.link)) ||
          parsed.items[0];
        return (first && (first.url || first.link)) || null;
      }
    }
  }

  return null;
}

// ==================== iframe嵌入检查相关函数 ====================

/**
 * 检查URL是否允许iframe嵌入
 * @param {string} url - 要检查的URL
 * @returns {Promise<boolean>} - 是否允许嵌入
 */
async function checkIframeEmbedding(url) {
  try {
    const response = await fetch(
      "/api/nae-deep-research/v1/check-iframe-embedding",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: url }),
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();

    if (!result.allowed) {
      console.warn(`iframe嵌入被拒绝: ${url}, 原因: ${result.reason}`);
    }

    return result.allowed;
  } catch (error) {
    console.warn("iframe嵌入检查失败:", error);
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
        statusElement.textContent = window.I18nService
          ? window.I18nService.t("loading_timeout").replace("{url}", url)
          : `加载超时: ${url}`;
        statusElement.className = "error";
      }
      console.warn("iframe加载超时:", url);
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
        statusElement.className = "success";
      }
      console.log("iframe加载成功:", url);
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
        statusElement.textContent = window.I18nService
          ? window.I18nService.t("webpage_load_failed").replace("{url}", url)
          : `网页加载失败: ${url}`;
        statusElement.className = "error";
      }
      console.error("iframe加载失败:", url);
    };

    // 加载新内容
    iframe.src = url;
    isBlank = false;
  }, 100);
}

/**
 * 显示iframe嵌入错误和替代方案
 * @param {string} url - 无法嵌入的URL
 * @param {HTMLElement} statusElement - 状态显示元素
 */
function showIframeEmbeddingError(url, statusElement) {
  // 隐藏加载提示
  toggleLoadingIndicator(false);

  // 更新状态文本
  if (statusElement) {
    statusElement.textContent = `网页不允许嵌入iframe: ${url}`;
    statusElement.className = "error";
  }

  // 显示替代方案
  showAlternativeOptions(url);
}

/**
 * 显示替代操作选项
 * @param {string} url - 无法嵌入的URL
 */
function showAlternativeOptions(url) {
  const rightContent = document.querySelector(".right-content");
  if (!rightContent) return;

  // 隐藏iframe
  const iframe = document.getElementById("content-iframe");
  if (iframe) {
    iframe.style.display = "none";
  }

  // 显示替代操作面板
  const alternativePanel = document.createElement("div");
  alternativePanel.className = "iframe-alternative-panel";
  alternativePanel.innerHTML = `
        <div class="alternative-content">
            <h3><i class="fas fa-exclamation-triangle"></i> 网页无法嵌入</h3>
            <p>该网页设置了安全策略，不允许在iframe中显示。</p>
            <p class="url-info"><strong>网址:</strong> ${url}</p>
            
            <div class="alternative-actions">
                <button class="action-btn primary" onclick="openInNewWindow('${url}')">
                    <i class="fas fa-external-link-alt"></i> 在新窗口打开
                </button>
                <button class="action-btn secondary" onclick="copyUrlToClipboard('${url}')">
                    <i class="fas fa-copy"></i> 复制链接
                </button>
            </div>
            
            <div class="help-info">
                <h4><i class="fas fa-info-circle"></i> 为什么无法嵌入？</h4>
                <ul>
                    <li>网站设置了 <code>X-Frame-Options</code> 安全策略</li>
                    <li>网站使用了 <code>Content-Security-Policy</code> 限制</li>
                    <li>网站域名在黑名单中（如百度、社交媒体等）</li>
                </ul>
            </div>
        </div>
        
        <style>
            .iframe-alternative-panel {
                padding: 30px;
                text-align: center;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            .alternative-content h3 {
                color: #f39c12;
                margin-bottom: 15px;
                font-size: 1.3em;
            }
            
            .alternative-content p {
                color: #666;
                margin: 10px 0;
                line-height: 1.6;
            }
            
            .url-info {
                background: #f8f9fa;
                padding: 10px;
                border-radius: 5px;
                margin: 15px 0;
                word-break: break-all;
                font-family: monospace;
                font-size: 0.9em;
            }
            
            .alternative-actions {
                margin: 25px 0;
                display: flex;
                gap: 15px;
                justify-content: center;
                flex-wrap: wrap;
            }
            
            .action-btn {
                padding: 12px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 500;
                transition: all 0.3s ease;
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }
            
            .action-btn.primary {
                background: #007bff;
                color: white;
            }
            
            .action-btn.primary:hover {
                background: #0056b3;
                transform: translateY(-2px);
            }
            
            .action-btn.secondary {
                background: #6c757d;
                color: white;
            }
            
            .action-btn.secondary:hover {
                background: #545b62;
                transform: translateY(-2px);
            }
            
            .help-info {
                margin-top: 30px;
                text-align: left;
                background: #f8f9fa;
                padding: 20px;
                border-radius: 8px;
                border-left: 4px solid #007bff;
            }
            
            .help-info h4 {
                color: #495057;
                margin-bottom: 10px;
                font-size: 1.1em;
            }
            
            .help-info ul {
                margin: 0;
                padding-left: 20px;
                color: #666;
            }
            
            .help-info li {
                margin: 8px 0;
                line-height: 1.5;
            }
            
            .help-info code {
                background: #e9ecef;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: 'Courier New', Courier, monospace;
                font-size: 0.9em;
            }
        </style>
    `;

  // 清空现有内容并添加替代面板
  rightContent.innerHTML = "";
  rightContent.appendChild(alternativePanel);
}

/**
 * 在新窗口打开URL
 * @param {string} url - 要打开的URL
 */
function openInNewWindow(url) {
  window.open(url, "_blank", "noopener,noreferrer");
}

/**
 * 复制URL到剪贴板
 * @param {string} url - 要复制的URL
 */
async function copyUrlToClipboard(url) {
  try {
    await navigator.clipboard.writeText(url);

    // 显示复制成功提示
    const button = event.target.closest(".action-btn");
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fas fa-check"></i> 已复制!';
    button.style.background = "#28a745";

    setTimeout(() => {
      button.innerHTML = originalText;
      button.style.background = "";
    }, 2000);
  } catch (error) {
    console.error("复制失败:", error);
    alert("复制失败，请手动复制: " + url);
  }
}

// 将函数暴露到全局作用域
window.openInNewWindow = openInNewWindow;
window.copyUrlToClipboard = copyUrlToClipboard;
