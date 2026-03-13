/**
 * Co-Sight Agent Management Panel
 * 智能体管理模块 — 创建、编辑、删除智能体配置
 */
const AgentService = (function () {
    const API_BASE = '/api/nae-deep-research/v1';
    let _agents = [];
    let _providers = [];
    let _availableSkills = []; // 新增：存储可用的技能列表
    let _editingAgent = null;
    let _isAddingAgent = false;

    function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function showToast(msg, type) {
        if (typeof window.showToast === 'function') { window.showToast(msg, type); return; }
        alert(msg);
    }

    /* ---------- API ---------- */
    async function fetchAgents() {
        const resp = await fetch(`${API_BASE}/deep-research/agents`);
        const json = await resp.json();
        // 后端返回 code:200 表示成功
        if (json.code !== 200 && json.code !== 0) throw new Error(json.msg || 'Failed to fetch agents');
        return (json.data && json.data.agents) || [];
    }

    async function fetchProviders() {
        const resp = await fetch(`${API_BASE}/deep-research/providers`);
        const json = await resp.json();
        if (json.code !== 200 && json.code !== 0) throw new Error(json.msg || 'Failed to fetch providers');
        return (json.data && json.data.providers) || [];
    }

    async function fetchAvailableSkills() {
        try {
            const resp = await fetch(`${API_BASE}/deep-research/available-skills`);
            const json = await resp.json();
            if (json.code !== 200 && json.code !== 0) throw new Error(json.msg || 'Failed to fetch skills');
            return (json.data && json.data.skills) || [];
        } catch (e) {
            console.warn('fetchAvailableSkills failed:', e);
            return [];
        }
    }

    async function saveAgentAPI(agentData) {
        const resp = await fetch(`${API_BASE}/deep-research/agents`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(agentData),
        });
        const json = await resp.json();
        if (json.code !== 200 && json.code !== 0) throw new Error(json.msg || 'Save failed');
        return json.data;
    }

    async function deleteAgentAPI(agentId) {
        const resp = await fetch(`${API_BASE}/deep-research/agents/${agentId}`, { method: 'DELETE' });
        const json = await resp.json();
        if (json.code !== 200 && json.code !== 0) throw new Error(json.msg || 'Delete failed');
        return json.data;
    }

    /* ---------- Panel ---------- */
    async function open() {
        try {
            _agents = await fetchAgents();
            if (window.RuntimeAgentSelector && typeof window.RuntimeAgentSelector.refresh === 'function') {
                await window.RuntimeAgentSelector.refresh();
            }
        } catch (e) {
            console.warn('fetchAgents failed:', e);
            _agents = [];
        }
        try {
            _providers = await fetchProviders();
        } catch (e) {
            console.warn('fetchProviders failed:', e);
            _providers = [];
        }
        _availableSkills = await fetchAvailableSkills();
        _editingAgent = null;
        _isAddingAgent = false;
        renderPanel();
    }

    function close() {
        const modal = document.getElementById('agent-modal');
        if (modal) {
            modal.classList.remove('show');
            modal.innerHTML = '';
        }
        document.body.style.overflow = '';
    }

    /* ============ 样式常量（内联样式，不依赖外部CSS） ============ */
    const S = {
        overlay: 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.45);backdrop-filter:blur(4px);z-index:10001;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.2s ease;',
        panel: 'position:relative;width:880px;max-width:92vw;max-height:85vh;background:#fff;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;pointer-events:auto;',
        header: 'display:flex;align-items:center;justify-content:space-between;padding:18px 24px;border-bottom:1px solid #eee;background:linear-gradient(135deg,#f8f9fa 0%,#fff 100%);',
        headerTitle: 'margin:0;font-size:20px;font-weight:600;color:#333;display:flex;align-items:center;gap:10px;',
        closeBtn: 'width:36px;height:36px;border:none;background:#f0f0f0;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#666;font-size:16px;transition:all 0.2s;',
        body: 'flex:1;overflow-y:auto;padding:24px;',
        // 卡片列表
        card: 'background:#fff;border:1px solid #e8e8e8;border-radius:12px;padding:16px 20px;margin-bottom:12px;transition:all 0.2s;',
        cardIcon: 'font-size:28px;margin-right:12px;',
        cardName: 'font-size:15px;font-weight:600;color:#333;',
        cardDesc: 'font-size:12px;color:#888;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;',
        badge: 'display:inline-block;font-size:11px;padding:2px 8px;border-radius:6px;font-weight:500;margin-left:8px;',
        badgeBuiltin: 'background:rgba(102,126,234,0.1);color:#667eea;',
        badgeDefault: 'background:rgba(255,184,77,0.1);color:#e8a317;',
        // 按钮
        btnPrimary: 'display:inline-flex;align-items:center;gap:6px;padding:7px 16px;border:none;border-radius:8px;background:linear-gradient(135deg,#43e97b 0%,#38f9d7 100%);color:#fff;font-size:13px;font-weight:500;cursor:pointer;transition:all 0.2s;',
        btnSecondary: 'display:inline-flex;align-items:center;gap:6px;padding:7px 16px;border:1px solid #ddd;border-radius:8px;background:#fff;color:#555;font-size:13px;font-weight:500;cursor:pointer;transition:all 0.2s;',
        btnDanger: 'display:inline-flex;align-items:center;gap:6px;padding:7px 16px;border:1px solid #fca5a5;border-radius:8px;background:#fee2e2;color:#dc2626;font-size:13px;font-weight:500;cursor:pointer;transition:all 0.2s;',
        btnAdd: 'display:flex;align-items:center;justify-content:center;gap:6px;width:100%;padding:12px;border:2px dashed #ddd;border-radius:12px;background:transparent;color:#888;font-size:14px;cursor:pointer;transition:all 0.2s;margin-top:16px;',
        // 表单
        formGroup: 'margin-bottom:16px;',
        formLabel: 'display:block;font-size:13px;font-weight:600;color:#555;margin-bottom:6px;',
        formInput: 'width:100%;padding:10px 14px;border:1px solid #e0e0e0;border-radius:8px;font-size:14px;color:#333;background:#fafbfc;transition:border-color 0.2s;outline:none;box-sizing:border-box;',
        formTextarea: 'width:100%;padding:10px 14px;border:1px solid #e0e0e0;border-radius:8px;font-size:13px;color:#333;background:#fafbfc;font-family:Consolas,Monaco,monospace;line-height:1.5;resize:vertical;outline:none;box-sizing:border-box;',
        formSelect: 'width:100%;padding:10px 14px;border:1px solid #e0e0e0;border-radius:8px;font-size:14px;color:#333;background:#fafbfc;outline:none;box-sizing:border-box;',
        formHint: 'font-size:12px;color:#aaa;margin-top:4px;',
        formActions: 'display:flex;align-items:center;gap:10px;margin-top:24px;padding-top:16px;border-top:1px solid #f0f0f0;',
        sectionTitle: 'font-size:18px;font-weight:700;color:#333;margin-bottom:20px;display:flex;align-items:center;gap:8px;',
    };

    function renderPanel() {
        const modal = document.getElementById('agent-modal');
        if (!modal) return;

        modal.innerHTML = `
            <div id="agent-modal-overlay" style="${S.overlay}">
                <div id="agent-modal-panel" style="${S.panel}">
                    <div style="${S.header}">
                        <h2 style="${S.headerTitle}"><i class="fas fa-robot" style="color:#667eea;"></i> 智能体管理</h2>
                        <button id="agent-modal-close" style="${S.closeBtn}" onmouseover="this.style.background='#e0e0e0'" onmouseout="this.style.background='#f0f0f0'">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div style="${S.body}" id="agent-content-area">
                        ${renderAgentContent()}
                    </div>
                </div>
            </div>
        `;

        bindModalEvents();
        bindContentEvents();
        const overlay = document.getElementById('agent-modal-overlay');
        if (overlay) {
            overlay.addEventListener('click', function (event) {
                if (event.target === overlay) {
                    AgentService.close();
                }
            });
        }

        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }

    function bindModalEvents() {
        const panel = document.getElementById('agent-modal-panel');
        if (panel) {
            panel.addEventListener('click', function (event) {
                event.stopPropagation();
            });
        }

        const closeBtn = document.getElementById('agent-modal-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () {
                close();
            });
        }
    }

    function bindContentEvents() {
        const addBtn = document.getElementById('agent-add-btn');
        if (addBtn) {
            addBtn.addEventListener('click', function () {
                startAddAgent();
            });
        }

        document.querySelectorAll('[data-agent-action="edit"]').forEach(button => {
            button.addEventListener('click', function () {
                selectAgent(this.dataset.agentId || '');
            });
        });

        const backBtn = document.getElementById('agent-back-btn');
        if (backBtn) {
            backBtn.addEventListener('click', function () {
                cancelEdit();
            });
        }

        const cancelBtn = document.getElementById('agent-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function () {
                cancelEdit();
            });
        }

        const saveBtn = document.getElementById('agent-save-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', function () {
                saveCurrentAgent();
            });
        }

        const deleteBtn = document.getElementById('agent-delete-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', function () {
                deleteCurrentAgent();
            });
        }

        const typeSelect = document.getElementById('af-type');
        if (typeSelect) {
            typeSelect.addEventListener('change', syncSkillsVisibility);
            syncSkillsVisibility();
        }
    }

    function syncSkillsVisibility() {
        const typeSelect = document.getElementById('af-type');
        const skillsContainer = document.getElementById('skills-container');
        if (!typeSelect || !skillsContainer) return;
        skillsContainer.style.display = typeSelect.value === 'actor' ? 'block' : 'none';
    }

    function renderAgentContent() {
        if (_editingAgent || _isAddingAgent) {
            return renderAgentForm(_editingAgent);
        } else {
            return renderAgentList();
        }
    }

    function renderAgentList() {
        const agentCards = _agents.length === 0
            ? '<div style="text-align:center;padding:40px;color:#aaa;font-size:14px;">暂无智能体配置</div>'
            : _agents.map(agent => {
                const defaultBadge = agent.is_default ? `<span style="${S.badge}${S.badgeDefault}"><i class="fas fa-star"></i> 默认</span>` : '';
                const builtinBadge = agent.builtin ? `<span style="${S.badge}${S.badgeBuiltin}"><i class="fas fa-lock"></i> 内置</span>` : '';

                let icon = '🤖';
                if (agent.builtin) icon = agent.name.includes('规划') ? '🧠' : '⚡';

                return `
                    <div style="${S.card}" onmouseover="this.style.borderColor='#667eea';this.style.boxShadow='0 4px 12px rgba(102,126,234,0.15)'" onmouseout="this.style.borderColor='#e8e8e8';this.style.boxShadow='none'">
                        <div style="display:flex;align-items:center;">
                            <span style="${S.cardIcon}">${icon}</span>
                            <div style="flex:1;min-width:0;">
                                <div style="display:flex;align-items:center;flex-wrap:wrap;">
                                    <span style="${S.cardName}">${escapeHtml(agent.name || '未命名智能体')}</span>
                                    ${defaultBadge}
                                    ${builtinBadge}
                                </div>
                                <div style="${S.cardDesc}">${escapeHtml(agent.description || '暂无描述')}</div>
                            </div>
                            <div style="display:flex;gap:8px;margin-left:12px;flex-shrink:0;">
                                <button type="button" style="${S.btnSecondary}" data-agent-action="edit" data-agent-id="${escapeHtml(agent.id)}">
                                    <i class="fas fa-pen"></i> 编辑
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

        return `
            <div style="${S.sectionTitle}">
                <i class="fas fa-robot" style="color:#667eea;"></i>
                智能体管理 <span style="font-size:14px;color:#888;font-weight:normal;margin-left:8px;">AI Agents</span>
            </div>
            ${agentCards}
            <button id="agent-add-btn" type="button" style="${S.btnAdd}" onmouseover="this.style.borderColor='#667eea';this.style.color='#667eea'" onmouseout="this.style.borderColor='#ddd';this.style.color='#888'">
                <i class="fas fa-plus"></i> 添加自定义智能体
            </button>
        `;
    }

    function selectAgent(agentId) {
        _editingAgent = _agents.find(a => a.id === agentId) || null;
        _isAddingAgent = false;
        refreshPanel();
    }

    function startAddAgent() {
        _editingAgent = {
            id: '',
            name: '',
            description: '',
            agent_type: 'actor',
            system_prompt: '',
            skills: [],
            provider_id: '',
            model_name: '',
            thinking_mode: null,
            enabled: true,
            is_default: false
        };
        _isAddingAgent = true;
        refreshPanel();
    }

    function refreshPanel() {
        const contentArea = document.getElementById('agent-content-area');
        if (contentArea) {
            contentArea.innerHTML = renderAgentContent();
            bindContentEvents();
        }
    }

    function renderAgentForm(agent) {
        const a = agent || {};
        const isBuiltin = a.builtin;

        // Build model options from providers
        let modelOptions = '<option value="">-- 系统默认模型 --</option>';
        _providers.forEach(p => {
            modelOptions += `<optgroup label="${escapeHtml(p.name)}">`;
            (p.models || []).forEach(m => {
                const val = `${p.id}|${m}`;
                const currentVal = `${a.provider_id}|${a.model_name}`;
                modelOptions += `<option value="${escapeHtml(val)}" ${val === currentVal ? 'selected' : ''}>${escapeHtml(m)}</option>`;
            });
            modelOptions += `</optgroup>`;
        });

        const builtinBadge = isBuiltin ? `<span style="${S.badge}${S.badgeBuiltin}"><i class="fas fa-lock"></i> 系统内置</span>` : '';

        return `
            <div style="${S.sectionTitle}">
                <button id="agent-back-btn" type="button" style="${S.btnSecondary}">
                    <i class="fas fa-arrow-left"></i> 返回
                </button>
                <span style="margin-left:8px;">${_isAddingAgent ? '✨ 创建智能体' : '✏️ 编辑智能体'}</span>
                ${builtinBadge}
            </div>

            <input type="hidden" id="af-id" value="${escapeHtml(a.id)}">

            <div style="${S.formGroup}">
                <label style="${S.formLabel}">智能体名称</label>
                <input type="text" id="af-name" style="${S.formInput}" value="${escapeHtml(a.name)}" placeholder="例如：前端开发专家" ${isBuiltin ? 'readonly' : ''} />
            </div>

            <div style="${S.formGroup}">
                <label style="${S.formLabel}">描述</label>
                <input type="text" id="af-desc" style="${S.formInput}" value="${escapeHtml(a.description)}" placeholder="该智能体的职责简介" ${isBuiltin ? 'readonly' : ''} />
            </div>

            <div style="display:flex;gap:16px;">
                <div style="${S.formGroup}flex:1;">
                    <label style="${S.formLabel}">智能体类型</label>
                    <select id="af-type" style="${S.formSelect}" ${isBuiltin ? 'disabled' : ''}>
                        <option value="actor" ${a.agent_type === 'actor' || !a.agent_type ? 'selected' : ''}>执行者 (Actor)</option>
                        <option value="planner" ${a.agent_type === 'planner' ? 'selected' : ''}>规划者 (Planner)</option>
                    </select>
                </div>
            </div>

            <div id="skills-container" style="${S.formGroup}; display: ${a.agent_type === 'planner' ? 'none' : 'block'}">
                <label style="${S.formLabel}">执行技能配置 <span style="${S.formHint}">（按住 Ctrl/Cmd 多选）</span></label>
                <select id="af-skills" style="${S.formSelect}" multiple size="6" ${isBuiltin ? 'disabled' : ''}>
                    ${_availableSkills.map(skill => {
            const selected = (a.skills || []).includes(skill.name) ? 'selected' : '';
            return `<option value="${escapeHtml(skill.name)}" ${selected}>${escapeHtml(skill.display_name_zh)} - ${escapeHtml(skill.description_zh)}</option>`;
        }).join('')}
                </select>
                <div style="${S.formHint}">仅 Actor 类型的智能体可配置执行技能。</div>
            </div>

            <div style="${S.formGroup}">
                <label style="${S.formLabel}">系统提示词 (System Prompt)</label>
                <textarea id="af-prompt" style="${S.formTextarea}" rows="12" placeholder="在这里定义智能体的身份、目标、规则和输出格式...">${escapeHtml(a.system_prompt)}</textarea>
            </div>

            <div style="${S.formGroup}">
                <label style="${S.formLabel}">Thinking Mode</label>
                <select id="af-thinking-mode" style="${S.formSelect}">
                    <option value="" ${a.thinking_mode === null || typeof a.thinking_mode === 'undefined' ? 'selected' : ''}>继承系统默认</option>
                    <option value="true" ${a.thinking_mode === true ? 'selected' : ''}>开启 thinking mode</option>
                    <option value="false" ${a.thinking_mode === false ? 'selected' : ''}>关闭 thinking mode</option>
                </select>
                <div style="${S.formHint}">不设置时使用系统默认；开启或关闭则仅对当前智能体生效。</div>
            </div>

            <div style="display:flex;gap:16px;">
                <div style="${S.formGroup}flex:1;">
                    <label style="${S.formLabel}">绑定大模型</label>
                    <select id="af-model" style="${S.formSelect}">${modelOptions}</select>
                    <div style="${S.formHint}">留空则使用全局默认大模型</div>
                </div>
                ${!isBuiltin ? `
                <div style="${S.formGroup}flex:1;">
                    <label style="${S.formLabel}">状态</label>
                    <select id="af-enabled" style="${S.formSelect}">
                        <option value="true" ${a.enabled !== false ? 'selected' : ''}>启用</option>
                        <option value="false" ${a.enabled === false ? 'selected' : ''}>停用</option>
                    </select>
                </div>
                ` : '<input type="hidden" id="af-enabled" value="true">'}
            </div>

            <div style="${S.formGroup}">
                <label style="display:flex;align-items:center;cursor:pointer;color:#555;font-size:14px;">
                    <input type="checkbox" id="af-default" ${a.is_default ? 'checked' : ''} style="margin-right:8px;width:16px;height:16px;" />
                    设为默认智能体 (启动任务时默认选中)
                </label>
            </div>

            <div style="${S.formActions}">
                ${!_isAddingAgent && !isBuiltin ? `
                    <button id="agent-delete-btn" type="button" style="${S.btnDanger}">
                        <i class="fas fa-trash"></i> 删除
                    </button>
                ` : ''}
                <div style="flex:1;"></div>
                <button id="agent-cancel-btn" type="button" style="${S.btnSecondary}">取消</button>
                <button id="agent-save-btn" type="button" style="${S.btnPrimary}">
                    <i class="fas fa-save"></i> 保存配置
                </button>
            </div>
        `;
    }

    function cancelEdit() {
        _editingAgent = null;
        _isAddingAgent = false;
        refreshPanel();
    }

    async function saveCurrentAgent() {
        const name = document.getElementById('af-name').value.trim();
        const description = document.getElementById('af-desc').value.trim();
        const systemPrompt = document.getElementById('af-prompt').value.trim();
        const modelVal = document.getElementById('af-model').value;
        const thinkingModeVal = document.getElementById('af-thinking-mode')?.value ?? '';
        const enabledEl = document.getElementById('af-enabled');
        const enabled = enabledEl ? enabledEl.value === 'true' : true;
        const isDefault = document.getElementById('af-default').checked;

        if (!name) { showToast('请输入智能体名称', 'error'); return; }

        let providerId = '', modelName = '';
        if (modelVal) {
            const parts = modelVal.split('|');
            providerId = parts[0] || '';
            modelName = parts[1] || '';
        }

        const agentType = document.getElementById('af-type')?.value || 'actor';
        let skills = [];
        if (agentType === 'actor') {
            const skillsEl = document.getElementById('af-skills');
            if (skillsEl) {
                skills = Array.from(skillsEl.selectedOptions).map(opt => opt.value);
            }
        }

        let thinkingMode = null;
        if (thinkingModeVal === 'true') {
            thinkingMode = true;
        } else if (thinkingModeVal === 'false') {
            thinkingMode = false;
        }

        const data = {
            id: _editingAgent ? _editingAgent.id : '',
            name, description,
            system_prompt: systemPrompt,
            provider_id: providerId,
            model_name: modelName,
            thinking_mode: thinkingMode,
            enabled, is_default: isDefault,
            agent_type: agentType,
            skills: skills
        };

        try {
            await saveAgentAPI(data);
            showToast('保存成功', 'success');
            _agents = await fetchAgents();
            if (window.RuntimeAgentSelector && typeof window.RuntimeAgentSelector.refresh === 'function') {
                await window.RuntimeAgentSelector.refresh();
            }
            _editingAgent = _agents.find(a => a.name === name) || null;
            _isAddingAgent = false;
            refreshPanel();
        } catch (e) {
            showToast('保存失败: ' + e.message, 'error');
        }
    }

    async function deleteCurrentAgent() {
        if (!_editingAgent || !_editingAgent.id) return;
        if (!confirm(`确定删除智能体「${_editingAgent.name}」吗？`)) return;
        try {
            await deleteAgentAPI(_editingAgent.id);
            showToast('删除成功', 'success');
            _agents = await fetchAgents();
            if (window.RuntimeAgentSelector && typeof window.RuntimeAgentSelector.refresh === 'function') {
                await window.RuntimeAgentSelector.refresh();
            }
            _editingAgent = null;
            _isAddingAgent = false;
            refreshPanel();
        } catch (e) {
            showToast('删除失败: ' + e.message, 'error');
        }
    }

    return {
        open, close, selectAgent, startAddAgent, cancelEdit,
        saveCurrentAgent, deleteCurrentAgent,
    };
})();

window.AgentService = AgentService;
