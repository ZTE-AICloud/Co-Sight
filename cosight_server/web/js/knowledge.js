/**
 * Co-Sight Knowledge Base Management
 * 知识库管理模块 — 对接 LightRAG 服务
 */
const KnowledgeService = (function () {
    const API_BASE = '/api/nae-deep-research/v1';
    let _kbList = [];
    let _currentKbId = null;
    let _lightragStatus = 'unknown';
    let _pipelineTimer = null;          // 管线轮询定时器
    let _detailDocuments = [];          // 当前KB的文档列表
    let _detailPipeline = null;         // 当前KB的管线状态
    let _healthDetail = null;           // LightRAG 服务详情（含模型配置）

    /* ========== API ========== */
    async function fetchKBList() {
        const resp = await fetch(`${API_BASE}/deep-research/kb/list`);
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data.knowledge_bases || [];
    }

    async function createKB(name, description) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description }),
        });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function deleteKB(kbId) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}`, { method: 'DELETE' });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function uploadDocument(kbId, file) {
        const formData = new FormData();
        formData.append('file', file);
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}/documents/upload`, {
            method: 'POST',
            body: formData,
        });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function insertText(kbId, text, description) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}/documents/text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, description }),
        });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function queryKB(kbId, question, mode) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, mode: mode || 'hybrid' }),
        });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function checkHealth() {
        try {
            const resp = await fetch(`${API_BASE}/deep-research/kb/health`);
            const json = await resp.json();
            _lightragStatus = json.data?.status || 'disconnected';
            _healthDetail = json.data?.detail || null;
        } catch {
            _lightragStatus = 'disconnected';
            _healthDetail = null;
        }
        return _lightragStatus;
    }

    async function startService() {
        const resp = await fetch(`${API_BASE}/deep-research/kb/start-service`, { method: 'POST' });
        const json = await resp.json();
        if (json.code !== 0) {
            const err = new Error(json.msg);
            err.logs = json.data?.logs || [];
            throw err;
        }
        return json.data;
    }

    async function stopService() {
        const resp = await fetch(`${API_BASE}/deep-research/kb/stop-service`, { method: 'POST' });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function getDocumentStatus(kbId) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}/documents/status`);
        const json = await resp.json();
        return json.data;
    }

    async function listDocuments(kbId) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}/documents`);
        const json = await resp.json();
        return json.data;
    }

    async function getGraphLabels(kbId) {
        const resp = await fetch(`${API_BASE}/deep-research/kb/${kbId}/graph-labels`);
        const json = await resp.json();
        return json.data;
    }

    /* ========== 渲染 ========== */
    function renderModal() {
        const modal = document.getElementById('knowledge-modal');
        if (!modal) return;

        const statusHtml = _lightragStatus === 'connected'
            ? '<span class="kb-status-badge kb-status-online"><i class="fas fa-circle"></i> 已连接</span>'
            : '<span class="kb-status-badge kb-status-offline"><i class="fas fa-circle"></i> 未连接</span>';

        const serviceBtn = _lightragStatus === 'connected'
            ? '<button class="kb-service-btn kb-service-stop" onclick="event.stopPropagation(); KnowledgeService.doStopService()" title="停止服务"><i class="fas fa-stop-circle"></i> 停止服务</button>'
            : '<button class="kb-service-btn kb-service-start" onclick="event.stopPropagation(); KnowledgeService.doStartService()" title="启动服务"><i class="fas fa-play-circle"></i> 启动服务</button>';

        const contentHtml = _currentKbId
            ? renderKBDetail()
            : renderKBList();

        modal.innerHTML = `
            <div class="settings-overlay" onclick="KnowledgeService.close()"></div>
            <div class="settings-panel kb-panel">
                <div class="settings-header">
                    <h2>
                        ${_currentKbId ? '<button class="kb-back-btn" onclick="KnowledgeService.backToList()"><i class="fas fa-arrow-left"></i></button>' : ''}
                        <i class="fas fa-book"></i> 知识库管理 ${statusHtml}
                    </h2>
                    <div class="kb-header-actions">
                        ${serviceBtn}
                        <button class="settings-close-btn" onclick="KnowledgeService.close()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
                <div class="kb-body">
                    ${contentHtml}
                </div>
            </div>
        `;

        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }

    function renderKBList() {
        let cardsHtml = '';
        if (_kbList.length === 0) {
            cardsHtml = `
                <div class="kb-empty-state">
                    <div class="kb-empty-icon"><i class="fas fa-book-open"></i></div>
                    <h3>还没有知识库</h3>
                    <p>创建你的第一个知识库，上传文档构建专属知识检索能力</p>
                    <button class="kb-btn-primary-lg" onclick="KnowledgeService.showCreateForm()">
                        <i class="fas fa-plus"></i> 新建知识库
                    </button>
                </div>
                <div id="kb-create-form" class="kb-create-form" style="display:none;">
                    <div class="kb-create-form-title"><i class="fas fa-pen-fancy"></i> 新建知识库</div>
                    <input type="text" id="kb-name-input" placeholder="知识库名称（必填）" class="kb-input">
                    <input type="text" id="kb-desc-input" placeholder="描述（可选），例如：项目技术文档集合" class="kb-input">
                    <div class="kb-create-actions">
                        <button class="kb-btn-cancel" onclick="KnowledgeService.hideCreateForm()">取消</button>
                        <button class="kb-btn-primary" onclick="KnowledgeService.doCreate()"><i class="fas fa-check"></i> 创建</button>
                    </div>
                </div>
            `;
        } else {
            const cards = _kbList.map(kb => `
                <div class="kb-card" onclick="KnowledgeService.openDetail('${kb.id}')">
                    <div class="kb-card-icon-wrap">
                        <i class="fas fa-database"></i>
                    </div>
                    <div class="kb-card-body">
                        <div class="kb-card-name">${escapeHtml(kb.name)}</div>
                        <div class="kb-card-desc">${escapeHtml(kb.description || '暂无描述')}</div>
                        <div class="kb-card-footer">
                            <span class="kb-card-stat"><i class="fas fa-file-alt"></i> ${kb.doc_count || 0} 篇文档</span>
                            <span class="kb-card-stat"><i class="fas fa-clock"></i> ${formatDate(kb.created_at)}</span>
                        </div>
                    </div>
                    <button class="kb-card-delete" onclick="event.stopPropagation(); KnowledgeService.confirmDelete('${kb.id}', '${escapeHtml(kb.name)}')" title="删除">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </div>
            `).join('');

            cardsHtml = `
                <div class="kb-list-toolbar">
                    <span class="kb-list-count"><i class="fas fa-layer-group"></i> ${_kbList.length} 个知识库</span>
                    <button class="kb-btn-primary" onclick="KnowledgeService.showCreateForm()">
                        <i class="fas fa-plus"></i> 新建知识库
                    </button>
                </div>
                <div id="kb-create-form" class="kb-create-form" style="display:none;">
                    <div class="kb-create-form-title"><i class="fas fa-pen-fancy"></i> 新建知识库</div>
                    <input type="text" id="kb-name-input" placeholder="知识库名称（必填）" class="kb-input">
                    <input type="text" id="kb-desc-input" placeholder="描述（可选），例如：项目技术文档集合" class="kb-input">
                    <div class="kb-create-actions">
                        <button class="kb-btn-cancel" onclick="KnowledgeService.hideCreateForm()">取消</button>
                        <button class="kb-btn-primary" onclick="KnowledgeService.doCreate()"><i class="fas fa-check"></i> 创建</button>
                    </div>
                </div>
                <div class="kb-card-grid">${cards}</div>
            `;
        }

        return cardsHtml;
    }

    function renderKBDetail() {
        const kb = _kbList.find(k => k.id === _currentKbId);
        if (!kb) return '<div class="kb-empty-state"><p>知识库不存在</p></div>';

        return `
            <div class="kb-detail">
                <div class="kb-detail-info">
                    <div class="kb-detail-icon"><i class="fas fa-database"></i></div>
                    <div>
                        <h3>${escapeHtml(kb.name)}</h3>
                        <p class="kb-detail-desc">${escapeHtml(kb.description || '暂无描述')}</p>
                        <div class="kb-detail-stats">
                            <span><i class="fas fa-file-alt"></i> ${kb.doc_count || 0} 篇文档</span>
                            <span><i class="fas fa-calendar"></i> 创建于 ${formatDate(kb.created_at)}</span>
                        </div>
                    </div>
                </div>

                <!-- 模型状态 -->
                <div class="kb-section" id="kb-model-section">
                    <div class="kb-section-title"><i class="fas fa-microchip"></i> 模型状态</div>
                    <div id="kb-model-content" class="kb-model-content">
                        <div class="kb-pipeline-loading"><i class="fas fa-spinner fa-spin"></i> 检测中...</div>
                    </div>
                </div>

                <!-- 构建状态 / 管线监控 -->
                <div class="kb-section" id="kb-pipeline-section">
                    <div class="kb-section-title"><i class="fas fa-tasks"></i> 构建状态</div>
                    <div id="kb-pipeline-content" class="kb-pipeline-content">
                        <div class="kb-pipeline-loading"><i class="fas fa-spinner fa-spin"></i> 正在获取状态...</div>
                    </div>
                </div>

                <!-- 文档列表 -->
                <div class="kb-section" id="kb-documents-section">
                    <div class="kb-section-title">
                        <span><i class="fas fa-file-alt"></i> 文档列表</span>
                        <button class="kb-btn-icon" onclick="KnowledgeService.refreshDocuments()" title="刷新">
                            <i class="fas fa-sync-alt"></i>
                        </button>
                    </div>
                    <div id="kb-documents-content" class="kb-documents-content">
                        <div class="kb-pipeline-loading"><i class="fas fa-spinner fa-spin"></i> 加载文档列表...</div>
                    </div>
                </div>

                <!-- 上传文档 -->
                <div class="kb-section">
                    <div class="kb-section-title"><i class="fas fa-cloud-upload-alt"></i> 上传文档</div>
                    <div class="kb-upload-area" id="kb-upload-area"
                         onclick="document.getElementById('kb-file-input').click()"
                         ondragover="event.preventDefault(); this.classList.add('dragover')"
                         ondragleave="this.classList.remove('dragover')"
                         ondrop="event.preventDefault(); this.classList.remove('dragover'); KnowledgeService.handleDrop(event)">
                        <div class="kb-upload-icon"><i class="fas fa-cloud-upload-alt"></i></div>
                        <p class="kb-upload-text">拖拽文件到这里，或点击选择文件</p>
                        <span class="kb-upload-hint">支持 PDF、Word、TXT、Markdown、Excel、PPT 格式</span>
                        <input type="file" id="kb-file-input" style="display:none"
                               accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.pptx"
                               onchange="KnowledgeService.handleFileSelect(event)" multiple>
                    </div>
                    <div id="kb-upload-progress" class="kb-upload-progress" style="display:none;">
                        <div class="kb-progress-bar"><div class="kb-progress-fill" id="kb-progress-fill"></div></div>
                        <span class="kb-progress-text" id="kb-progress-text">上传中...</span>
                    </div>
                </div>

                <!-- 插入文本 -->
                <div class="kb-section">
                    <div class="kb-section-title"><i class="fas fa-pen"></i> 插入文本</div>
                    <textarea id="kb-text-input" class="kb-textarea" rows="4" placeholder="粘贴或输入要添加到知识库的文本内容..."></textarea>
                    <div class="kb-section-actions">
                        <button class="kb-btn-primary" onclick="KnowledgeService.doInsertText()">
                            <i class="fas fa-plus-circle"></i> 添加文本
                        </button>
                    </div>
                </div>

                <!-- 测试查询 -->
                <div class="kb-section">
                    <div class="kb-section-title"><i class="fas fa-search"></i> 测试查询</div>
                    <div class="kb-query-row">
                        <input type="text" id="kb-query-input" class="kb-input kb-query-input" placeholder="输入测试问题，验证知识库检索效果...">
                        <select id="kb-query-mode" class="kb-select">
                            <option value="hybrid" selected>混合模式</option>
                            <option value="local">局部模式</option>
                            <option value="global">全局模式</option>
                            <option value="naive">朴素模式</option>
                        </select>
                        <button class="kb-btn-primary" onclick="KnowledgeService.doQuery()">
                            <i class="fas fa-search"></i> 查询
                        </button>
                    </div>
                    <div id="kb-query-result" class="kb-query-result" style="display:none;"></div>
                </div>
            </div>
        `;
    }

    /* ========== 详情页数据加载 ========== */
    async function loadDetailData() {
        if (!_currentKbId) return;
        try {
            // 并行加载文档、管线、健康状态
            const [docData, pipeData] = await Promise.all([
                listDocuments(_currentKbId),
                getDocumentStatus(_currentKbId),
            ]);
            _detailDocuments = docData?.documents || [];
            _detailPipeline = pipeData || {};

            // 加载模型状态（如果还没加载过）
            if (!_healthDetail) await checkHealth();
            renderModelSection();
            renderPipelineSection();
            renderDocumentsSection();

            // 如果管线正在工作，或有文档在 PENDING / PROCESSING，启动轮询
            const hasPending = _detailDocuments.some(d => d.status === 'PENDING' || d.status === 'PROCESSING');
            if (_detailPipeline.busy || hasPending) {
                startPipelinePolling();
            } else {
                stopPipelinePolling();
            }
        } catch (e) {
            console.warn('loadDetailData error:', e);
        }
    }

    function startPipelinePolling() {
        stopPipelinePolling();
        _pipelineTimer = setInterval(async () => {
            if (!_currentKbId) { stopPipelinePolling(); return; }
            try {
                const [pipeData, docData] = await Promise.all([
                    getDocumentStatus(_currentKbId),
                    listDocuments(_currentKbId),
                ]);
                _detailPipeline = pipeData || {};
                _detailDocuments = docData?.documents || [];
                renderPipelineSection();
                renderDocumentsSection();
                if (!_detailPipeline.busy) {
                    stopPipelinePolling();
                    // 刷新KB列表以更新doc_count
                    _kbList = await fetchKBList();
                }
            } catch (e) { /* ignore */ }
        }, 3000);
    }

    function stopPipelinePolling() {
        if (_pipelineTimer) { clearInterval(_pipelineTimer); _pipelineTimer = null; }
    }

    function renderModelSection() {
        const el = document.getElementById('kb-model-content');
        if (!el) return;

        if (!_healthDetail || !_healthDetail.configuration) {
            el.innerHTML = `<div class="kb-model-row"><span class="kb-model-badge kb-model-warn"><i class="fas fa-exclamation-triangle"></i> 无法获取模型信息</span><span class="kb-model-hint">请确认 LightRAG 服务已启动</span></div>`;
            return;
        }

        const c = _healthDetail.configuration;
        const items = [];

        // LLM
        items.push({ icon: 'fa-brain', label: 'LLM 模型', value: c.llm_model || '-', binding: c.llm_binding || '-', ok: !!c.llm_model });
        // Embedding
        items.push({ icon: 'fa-vector-square', label: '嵌入模型', value: c.embedding_model || '-', binding: c.embedding_binding || '-', ok: !!c.embedding_model });
        // Rerank
        const rerankOk = c.enable_rerank && !!c.rerank_model;
        items.push({ icon: 'fa-sort-amount-up', label: '重排序模型', value: rerankOk ? c.rerank_model : '未启用', binding: c.rerank_binding || '-', ok: rerankOk });

        const html = items.map(m => `
            <div class="kb-model-item">
                <div class="kb-model-item-icon"><i class="fas ${m.icon}"></i></div>
                <div class="kb-model-item-info">
                    <div class="kb-model-item-label">${m.label}</div>
                    <div class="kb-model-item-value" title="${escapeHtml(m.value)}">${escapeHtml(m.value)}</div>
                    <div class="kb-model-item-binding">${escapeHtml(m.binding)}</div>
                </div>
                <span class="kb-model-badge ${m.ok ? 'kb-model-ok' : 'kb-model-warn'}">
                    <i class="fas ${m.ok ? 'fa-check-circle' : 'fa-exclamation-triangle'}"></i> ${m.ok ? '就绪' : '异常'}
                </span>
            </div>
        `).join('');

        el.innerHTML = `<div class="kb-model-grid">${html}</div>`;
    }

    function renderPipelineSection() {
        const el = document.getElementById('kb-pipeline-content');
        if (!el || !_detailPipeline) return;

        const p = _detailPipeline;

        if (p.busy) {
            const progress = (p.batchs > 0) ? Math.round((p.cur_batch / p.batchs) * 100) : 0;
            const historyHtml = (p.history_messages || []).slice(-30).map(m =>
                `<div class="kb-pipeline-log-line">${escapeHtml(m)}</div>`
            ).join('');

            el.innerHTML = `
                <div class="kb-pipeline-active">
                    <div class="kb-pipeline-header">
                        <span class="kb-pipeline-badge kb-badge-processing"><i class="fas fa-cog fa-spin"></i> 正在构建</span>
                        <span class="kb-pipeline-job">${escapeHtml(p.job_name || '')}</span>
                    </div>
                    <div class="kb-pipeline-progress-wrap">
                        <div class="kb-pipeline-progress-bar">
                            <div class="kb-pipeline-progress-fill" style="width:${progress}%"></div>
                        </div>
                        <span class="kb-pipeline-progress-text">${p.cur_batch || 0} / ${p.batchs || 0} 批次 (${progress}%)</span>
                    </div>
                    <div class="kb-pipeline-docs-info">
                        <span><i class="fas fa-file-alt"></i> 文档数: ${p.docs || 0}</span>
                        ${p.latest_message ? `<span class="kb-pipeline-latest-inline"><i class="fas fa-comment-dots"></i> ${escapeHtml(p.latest_message)}</span>` : ''}
                    </div>
                    <details class="kb-pipeline-log-details" ${historyHtml ? 'open' : ''}>
                        <summary><i class="fas fa-terminal"></i> 构建日志 (${(p.history_messages || []).length} 条)</summary>
                        <div class="kb-pipeline-log-scroll" id="kb-pipeline-log-scroll">${historyHtml || '<div class="kb-pipeline-log-line" style="color:#9ca3af">等待日志...</div>'}</div>
                    </details>
                </div>
            `;
            // 自动滚动到日志底部
            const logEl = document.getElementById('kb-pipeline-log-scroll');
            if (logEl) logEl.scrollTop = logEl.scrollHeight;
        } else {
            // 获取文档状态统计
            const docs = _detailDocuments || [];
            const statusCounts = { PROCESSED: 0, PROCESSING: 0, PENDING: 0, FAILED: 0 };
            docs.forEach(d => { if (statusCounts.hasOwnProperty(d.status)) statusCounts[d.status]++; });
            const total = docs.length;

            el.innerHTML = `
                <div class="kb-pipeline-idle">
                    <span class="kb-pipeline-badge kb-badge-idle"><i class="fas fa-check-circle"></i> 空闲</span>
                    <div class="kb-pipeline-stats-row">
                        <div class="kb-stat-card"><span class="kb-stat-num">${total}</span><span class="kb-stat-label">总文档</span></div>
                        <div class="kb-stat-card kb-stat-success"><span class="kb-stat-num">${statusCounts.PROCESSED}</span><span class="kb-stat-label">已完成</span></div>
                        <div class="kb-stat-card kb-stat-processing"><span class="kb-stat-num">${statusCounts.PROCESSING}</span><span class="kb-stat-label">处理中</span></div>
                        <div class="kb-stat-card kb-stat-pending"><span class="kb-stat-num">${statusCounts.PENDING}</span><span class="kb-stat-label">等待中</span></div>
                        <div class="kb-stat-card kb-stat-failed"><span class="kb-stat-num">${statusCounts.FAILED}</span><span class="kb-stat-label">失败</span></div>
                    </div>
                </div>
            `;
        }
    }

    function renderDocumentsSection() {
        const el = document.getElementById('kb-documents-content');
        if (!el) return;

        const docs = _detailDocuments || [];
        if (docs.length === 0) {
            el.innerHTML = `<div class="kb-docs-empty"><i class="fas fa-inbox"></i> 还没有文档，请上传文件或插入文本</div>`;
            return;
        }

        const statusMap = {
            'PROCESSED': { label: '已完成', cls: 'kb-doc-status-done', icon: 'fa-check-circle' },
            'PROCESSING': { label: '处理中', cls: 'kb-doc-status-proc', icon: 'fa-spinner fa-spin' },
            'PENDING': { label: '等待中', cls: 'kb-doc-status-pend', icon: 'fa-clock' },
            'FAILED': { label: '失败', cls: 'kb-doc-status-fail', icon: 'fa-times-circle' },
        };

        const rows = docs.map(doc => {
            const s = statusMap[doc.status] || { label: doc.status || '未知', cls: '', icon: 'fa-question-circle' };
            const name = doc.file_path
                ? doc.file_path.split(/[/\\]/).pop()
                : (doc.content_summary ? doc.content_summary.substring(0, 40) + '...' : doc.id?.substring(0, 12));
            const sizeStr = doc.content_length ? formatSize(doc.content_length) : '-';
            const chunks = doc.chunks_count != null ? doc.chunks_count : '-';
            const time = doc.updated_at ? formatDate(doc.updated_at) : formatDate(doc.created_at);
            const errorHtml = (doc.status === 'FAILED' && doc.error_msg)
                ? `<div class="kb-doc-error-msg"><i class="fas fa-exclamation-circle"></i> ${escapeHtml(doc.error_msg)}</div>`
                : '';

            return `
                <tr class="kb-doc-row ${doc.status === 'FAILED' ? 'kb-doc-row-failed' : ''}">
                    <td class="kb-doc-name" title="${escapeHtml(doc.file_path || doc.content_summary || '')}">
                        <i class="fas fa-file-alt"></i> ${escapeHtml(name)}
                        ${errorHtml}
                    </td>
                    <td><span class="kb-doc-status ${s.cls}"><i class="fas ${s.icon}"></i> ${s.label}</span></td>
                    <td class="kb-doc-num">${chunks}</td>
                    <td class="kb-doc-num">${sizeStr}</td>
                    <td class="kb-doc-num">${time}</td>
                </tr>
            `;
        }).join('');

        el.innerHTML = `
            <table class="kb-doc-table">
                <thead>
                    <tr>
                        <th>文档名</th>
                        <th>状态</th>
                        <th>分片数</th>
                        <th>大小</th>
                        <th>更新时间</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }

    async function refreshDocuments() {
        const btn = document.querySelector('#kb-documents-section .kb-btn-icon');
        if (btn) btn.classList.add('kb-spin');
        try {
            const [docData, pipeData] = await Promise.all([
                listDocuments(_currentKbId),
                getDocumentStatus(_currentKbId),
            ]);
            _detailDocuments = docData?.documents || [];
            _detailPipeline = pipeData || {};
            renderPipelineSection();
            renderDocumentsSection();
            if (_detailPipeline.busy && !_pipelineTimer) startPipelinePolling();
        } catch (e) {
            showToast('刷新失败: ' + e.message, 'error');
        } finally {
            if (btn) btn.classList.remove('kb-spin');
        }
    }

    /* ========== 操作 ========== */
    function showCreateForm() {
        const form = document.getElementById('kb-create-form');
        if (form) {
            form.style.display = 'block';
            const nameInput = document.getElementById('kb-name-input');
            if (nameInput) nameInput.focus();
        }
    }

    function hideCreateForm() {
        const form = document.getElementById('kb-create-form');
        if (form) form.style.display = 'none';
    }

    async function doCreate() {
        const name = document.getElementById('kb-name-input')?.value?.trim();
        const desc = document.getElementById('kb-desc-input')?.value?.trim();
        if (!name) { showToast('请输入知识库名称', 'error'); return; }
        try {
            await createKB(name, desc);
            showToast(`知识库 "${name}" 创建成功`, 'success');
            await refreshList();
        } catch (e) {
            showToast(e.message, 'error');
        }
    }

    async function confirmDelete(kbId, name) {
        if (!confirm(`确定要删除知识库 "${name}" 吗？此操作不可恢复。`)) return;
        try {
            await deleteKB(kbId);
            showToast(`知识库 "${name}" 已删除`, 'success');
            if (_currentKbId === kbId) _currentKbId = null;
            await refreshList();
        } catch (e) {
            showToast(e.message, 'error');
        }
    }

    function openDetail(kbId) {
        _currentKbId = kbId;
        _detailDocuments = [];
        _detailPipeline = null;
        _healthDetail = null;
        renderModal();
        // 渲染后异步加载文档和管线数据
        setTimeout(() => loadDetailData(), 50);
    }

    function backToList() {
        stopPipelinePolling();
        _currentKbId = null;
        _detailDocuments = [];
        _detailPipeline = null;
        renderModal();
    }

    async function handleFileSelect(event) {
        const files = event.target.files;
        if (!files || files.length === 0) return;
        await uploadFiles(Array.from(files));
    }

    async function handleDrop(event) {
        const files = event.dataTransfer?.files;
        if (!files || files.length === 0) return;
        await uploadFiles(Array.from(files));
    }

    async function uploadFiles(files) {
        const progressDiv = document.getElementById('kb-upload-progress');
        const progressFill = document.getElementById('kb-progress-fill');
        const progressText = document.getElementById('kb-progress-text');
        if (progressDiv) progressDiv.style.display = 'flex';

        let completed = 0;
        for (const file of files) {
            try {
                if (progressText) progressText.textContent = `上传中: ${file.name} (${completed + 1}/${files.length})`;
                if (progressFill) progressFill.style.width = `${(completed / files.length) * 100}%`;
                await uploadDocument(_currentKbId, file);
                completed++;
            } catch (e) {
                showToast(`上传 ${file.name} 失败: ${e.message}`, 'error');
            }
        }

        if (progressFill) progressFill.style.width = '100%';
        if (progressText) progressText.textContent = `上传完成 (${completed}/${files.length})`;
        showToast(`成功上传 ${completed} 个文件`, 'success');

        setTimeout(() => {
            if (progressDiv) progressDiv.style.display = 'none';
            if (progressFill) progressFill.style.width = '0%';
        }, 2000);

        _kbList = await fetchKBList();
        // 上传完毕后刷新文档列表和管线状态
        await loadDetailData();
    }

    async function doInsertText() {
        const text = document.getElementById('kb-text-input')?.value?.trim();
        if (!text) { showToast('请输入文本内容', 'error'); return; }
        try {
            await insertText(_currentKbId, text, '');
            showToast('文本添加成功，正在后台索引处理', 'success');
            document.getElementById('kb-text-input').value = '';
            _kbList = await fetchKBList();
            await loadDetailData();
        } catch (e) {
            showToast(e.message, 'error');
        }
    }

    async function doQuery() {
        const question = document.getElementById('kb-query-input')?.value?.trim();
        if (!question) { showToast('请输入查询问题', 'error'); return; }
        const mode = document.getElementById('kb-query-mode')?.value || 'hybrid';
        const resultDiv = document.getElementById('kb-query-result');
        if (resultDiv) {
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '<div class="kb-query-loading"><i class="fas fa-spinner fa-spin"></i> 正在检索知识库...</div>';
        }
        try {
            const result = await queryKB(_currentKbId, question, mode);
            const text = typeof result === 'string' ? result : (result?.response || JSON.stringify(result, null, 2));
            if (resultDiv) {
                resultDiv.innerHTML = `<div class="kb-query-result-header"><i class="fas fa-lightbulb"></i> 检索结果 <span class="kb-query-mode-tag">${mode}</span></div><pre class="kb-query-result-text">${escapeHtml(text)}</pre>`;
            }
        } catch (e) {
            if (resultDiv) resultDiv.innerHTML = `<div class="kb-query-error"><i class="fas fa-exclamation-triangle"></i> 查询失败: ${escapeHtml(e.message)}</div>`;
        }
    }

    async function refreshList() {
        _kbList = await fetchKBList();
        renderModal();
    }

    /* ========== 知识库选择器（嵌入到首页输入区域） ========== */
    function renderSelector(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        let selected = [];
        try {
            const raw = localStorage.getItem('cosight:selectedKBs');
            if (raw) selected = JSON.parse(raw);
        } catch (e) { /* ignore */ }

        const isEnabled = selected.length > 0;

        container.innerHTML = `
            <div class="kb-selector" style="position:relative; display:inline-block;">
                <button class="kb-selector-toggle ${isEnabled ? 'active' : ''}" onclick="event.stopPropagation(); KnowledgeService.toggleSelector('${containerId}')" title="选择知识库">
                    <i class="fas fa-book"></i>
                    <span class="kb-selector-label">${isEnabled ? selected.length + ' 个知识库已选' : '选择知识库'}</span>
                    ${isEnabled ? '<span class="kb-selector-count">' + selected.length + '</span>' : ''}
                    <i class="fas fa-chevron-down kb-selector-arrow"></i>
                </button>
                <div class="kb-selector-dropdown" id="kb-selector-dropdown-${containerId}" style="display:none;"></div>
            </div>
        `;
    }

    async function toggleSelector(containerId) {
        const dropdownId = `kb-selector-dropdown-${containerId}`;
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;

        if (dropdown.style.display !== 'none') {
            dropdown.style.display = 'none';
            return;
        }

        // 先显示 loading
        dropdown.style.display = 'block';
        dropdown.innerHTML = '<div class="kb-dropdown-loading"><i class="fas fa-spinner fa-spin"></i> 加载中...</div>';

        try {
            _kbList = await fetchKBList();
        } catch (e) {
            dropdown.innerHTML = '<div class="kb-dropdown-empty"><i class="fas fa-exclamation-circle"></i> 无法连接服务<br><small>请确认后端和 LightRAG 已启动</small></div>';
            // 点击外部关闭
            _bindDropdownClose(dropdown);
            return;
        }

        let selected = [];
        try {
            const raw = localStorage.getItem('cosight:selectedKBs');
            if (raw) selected = JSON.parse(raw);
        } catch (e) { /* ignore */ }

        if (_kbList.length === 0) {
            dropdown.innerHTML = `
                <div class="kb-dropdown-empty">
                    <i class="fas fa-inbox"></i> 暂无知识库
                    <br><a onclick="KnowledgeService.open()">前往创建</a>
                </div>
            `;
        } else {
            dropdown.innerHTML = _kbList.map(kb => `
                <label class="kb-dropdown-item">
                    <input type="checkbox" value="${kb.id}" ${selected.includes(kb.id) ? 'checked' : ''}
                           onchange="KnowledgeService.onSelectorChange()">
                    <span class="kb-dropdown-name">${escapeHtml(kb.name)}</span>
                    <span class="kb-dropdown-count">${kb.doc_count || 0} 篇</span>
                </label>
            `).join('');
        }

        _bindDropdownClose(dropdown);
    }

    function _bindDropdownClose(dropdown) {
        setTimeout(() => {
            const handler = function closeHandler(e) {
                if (!dropdown.contains(e.target) && !e.target.closest('.kb-selector-toggle')) {
                    dropdown.style.display = 'none';
                    document.removeEventListener('click', closeHandler);
                }
            };
            document.addEventListener('click', handler);
        }, 10);
    }

    function onSelectorChange() {
        const checkboxes = document.querySelectorAll('[id^="kb-selector-dropdown-"] input[type="checkbox"]');
        const selected = [];
        checkboxes.forEach(cb => { if (cb.checked) selected.push(cb.value); });
        const unique = [...new Set(selected)];
        localStorage.setItem('cosight:selectedKBs', JSON.stringify(unique));

        document.querySelectorAll('.kb-selector-label').forEach(label => {
            label.textContent = unique.length > 0 ? unique.length + ' 个知识库已选' : '选择知识库';
        });
        document.querySelectorAll('.kb-selector-toggle').forEach(toggle => {
            if (unique.length > 0) toggle.classList.add('active');
            else toggle.classList.remove('active');
        });
        // 更新计数角标
        document.querySelectorAll('.kb-selector-count').forEach(el => el.remove());
        if (unique.length > 0) {
            document.querySelectorAll('.kb-selector-toggle').forEach(toggle => {
                if (!toggle.querySelector('.kb-selector-count')) {
                    const badge = document.createElement('span');
                    badge.className = 'kb-selector-count';
                    badge.textContent = unique.length;
                    toggle.insertBefore(badge, toggle.querySelector('.kb-selector-arrow'));
                }
            });
        }

        document.querySelectorAll('[id^="kb-selector-dropdown-"] input[type="checkbox"]').forEach(cb => {
            cb.checked = unique.includes(cb.value);
        });
    }

    function getSelectedKBIds() {
        try {
            const raw = localStorage.getItem('cosight:selectedKBs');
            if (raw) return JSON.parse(raw);
        } catch (e) { /* ignore */ }
        return [];
    }

    /* ========== 生命周期 ========== */
    async function doStartService() {
        const btn = document.querySelector('.kb-service-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 启动中...';
        }
        try {
            const result = await startService();
            if (result.status === 'already_running') {
                showToast(result.message, 'success');
            } else if (result.status === 'started') {
                showToast('✅ LightRAG 服务启动成功', 'success');
            } else {
                showToast(result.message || '服务正在启动...', 'success');
            }
            await checkHealth();
            renderModal();
        } catch (e) {
            let msg = e.message;
            // 截取前 200 字符避免 toast 太长
            if (msg.length > 200) msg = msg.substring(0, 200) + '...';
            showToast('启动失败: ' + msg, 'error');
            // 如果有日志，在弹窗中显示
            if (e.logs && e.logs.length > 0) {
                const bodyEl = document.querySelector('.kb-body');
                if (bodyEl) {
                    bodyEl.innerHTML = `
                        <div class="kb-error-logs">
                            <div class="kb-section-title"><i class="fas fa-exclamation-triangle"></i> 启动失败 - 服务日志</div>
                            <pre class="kb-log-output">${escapeHtml(e.logs.join('\n'))}</pre>
                            <p style="color:#999;font-size:12px;margin-top:12px;">请检查以上日志定位问题。常见原因：缺少依赖包、端口占用、模型配置错误。</p>
                        </div>
                    `;
                }
            }
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-play-circle"></i> 启动服务';
            }
        }
    }

    async function doStopService() {
        if (!confirm('确定要停止 LightRAG 服务吗？停止后知识库将无法使用。')) return;
        const btn = document.querySelector('.kb-service-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 停止中...';
        }
        try {
            await stopService();
            showToast('LightRAG 服务已停止', 'success');
            _lightragStatus = 'disconnected';
            renderModal();
        } catch (e) {
            showToast('停止失败: ' + e.message, 'error');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-stop-circle"></i> 停止服务';
            }
        }
    }

    async function open() {
        _currentKbId = null;
        try {
            const [list] = await Promise.all([fetchKBList(), checkHealth()]);
            _kbList = list;
        } catch (e) {
            console.error('Failed to load KB data:', e);
            _kbList = [];
        }
        renderModal();
    }

    function close() {
        stopPipelinePolling();
        const modal = document.getElementById('knowledge-modal');
        if (modal) {
            modal.classList.remove('show');
            setTimeout(() => { if (modal) modal.innerHTML = ''; }, 300);
        }
        document.body.style.overflow = '';
        _currentKbId = null;
        _detailDocuments = [];
        _detailPipeline = null;
    }

    /* ========== 工具函数 ========== */
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDate(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr);
            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        } catch (e) { return isoStr; }
    }

    function formatSize(bytes) {
        if (bytes == null || bytes === 0) return '-';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function showToast(message, type) {
        const existing = document.querySelector('.settings-toast');
        if (existing) existing.remove();
        const toast = document.createElement('div');
        toast.className = `settings-toast settings-toast-${type}`;
        toast.innerHTML = `
            <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
            <span>${message}</span>
        `;
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    /* ========== 公开接口 ========== */
    return {
        open, close, backToList, openDetail,
        showCreateForm, hideCreateForm, doCreate, confirmDelete,
        handleFileSelect, handleDrop, doInsertText, doQuery,
        renderSelector, toggleSelector, onSelectorChange, getSelectedKBIds,
        doStartService, doStopService, refreshDocuments,
    };
})();

window.KnowledgeService = KnowledgeService;
