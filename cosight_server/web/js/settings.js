/**
 * Co-Sight Settings Panel
 * 设置弹窗模块 — 查看和修改 .env 配置 + 大模型供应商管理
 */
const SettingsService = (function () {
    const API_BASE = '/api/nae-deep-research/v1';
    let _currentData = null;   // 缓存当前配置数据
    let _activeGroup = null;   // 当前选中的分组
    let _providers = [];        // 供应商列表（含原始 api_key 脱敏值）
    let _editingProvider = null; // 当前正在编辑的供应商
    let _isAddingProvider = false;

    // 模型分组 key 前缀映射（与后端一致）
    const MODEL_GROUPS = ['default_model', 'plan_model', 'act_model', 'tool_model', 'vision_model', 'credibility_model', 'browser_model'];
    const GROUP_TARGET_MAP = {
        'default_model': 'default',
        'plan_model': 'plan',
        'act_model': 'act',
        'tool_model': 'tool',
        'vision_model': 'vision',
        'credibility_model': 'credibility',
        'browser_model': 'browser',
    };

    /* ---------- API ---------- */
    async function fetchSettings() {
        const resp = await fetch(`${API_BASE}/deep-research/settings`);
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data.groups;
    }

    async function postSettings(settings) {
        const resp = await fetch(`${API_BASE}/deep-research/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ settings }),
        });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg);
        return json.data;
    }

    async function fetchProviders() {
        const resp = await fetch(`${API_BASE}/deep-research/providers`);
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg || json.message);
        return json.data.providers || [];
    }

    async function postProviders(providers) {
        const resp = await fetch(`${API_BASE}/deep-research/providers`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ providers }),
        });
        const json = await resp.json();
        if (json.code !== 0) throw new Error(json.msg || json.message);
        return json.data;
    }

    async function testProviderAPI(providerId, model) {
        const resp = await fetch(`${API_BASE}/deep-research/providers/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider_id: providerId, model }),
        });
        return await resp.json();
    }

    async function applyProviderToGroup(providerId, modelName, targetGroup) {
        const resp = await fetch(`${API_BASE}/deep-research/providers/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider_id: providerId, model_name: modelName, target_group: targetGroup }),
        });
        return await resp.json();
    }

    /* ---------- 渲染 ---------- */
    function renderModal(groups, isInitialRender = true) {
        _currentData = groups;
        const modal = document.getElementById('settings-modal');
        if (!modal) return;

        // 默认选中第一个分组（大模型）
        if (!_activeGroup) {
            _activeGroup = 'providers';
        }

        if (isInitialRender) {
            // 构建侧边栏：先加"大模型"，再加原有分组
            const sidebarItems = `
                <div class="settings-sidebar-item ${'providers' === _activeGroup ? 'active' : ''}" 
                     data-group="providers" onclick="SettingsService.switchGroup('providers')">
                    <i class="fas fa-cube"></i>
                    <span>大模型</span>
                </div>
            ` + groups.map(g => `
                <div class="settings-sidebar-item ${g.group === _activeGroup ? 'active' : ''}" 
                     data-group="${g.group}" onclick="SettingsService.switchGroup('${g.group}')">
                    <i class="fas ${g.icon}"></i>
                    <span>${g.label_zh}</span>
                </div>
            `).join('');

            const contentHtml = _activeGroup === 'providers'
                ? renderProvidersPage()
                : renderSettingsContent(groups);

            modal.innerHTML = `
                <div class="settings-overlay" onclick="SettingsService.close()"></div>
                <div class="settings-panel">
                    <div class="settings-header">
                        <h2><i class="fas fa-cog"></i> 设置</h2>
                        <button class="settings-close-btn" onclick="SettingsService.close()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="settings-body">
                        <div class="settings-sidebar">${sidebarItems}</div>
                        <div class="settings-content" id="settings-content-area">${contentHtml}</div>
                    </div>
                    <div class="settings-footer">
                        <div class="settings-footer-hint">
                            <i class="fas fa-info-circle"></i>
                            修改配置后需要重启服务才能完全生效
                        </div>
                        <div class="settings-footer-actions">
                            <button class="settings-btn settings-btn-cancel" onclick="SettingsService.close()">取消</button>
                            <button class="settings-btn settings-btn-save" onclick="SettingsService.save()">
                                <i class="fas fa-save"></i> 保存
                            </button>
                        </div>
                    </div>
                </div>
            `;
        } else {
            updateSidebarAndContent(groups);
        }

        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }

    function updateSidebarAndContent(groups) {
        const modal = document.getElementById('settings-modal');
        if (!modal) return;

        // 更新左侧选中状态
        const sidebarItems = modal.querySelectorAll('.settings-sidebar-item');
        sidebarItems.forEach(item => {
            item.classList.toggle('active', item.dataset.group === _activeGroup);
        });

        // 更新右侧内容
        const contentDiv = document.getElementById('settings-content-area');
        if (!contentDiv) return;

        if (_activeGroup === 'providers') {
            contentDiv.innerHTML = renderProvidersPage();
        } else {
            contentDiv.innerHTML = renderSettingsContent(groups);
        }
    }

    function renderSettingsContent(groups) {
        const activeGroupData = groups.find(g => g.group === _activeGroup) || groups[0];
        if (!activeGroupData) return '<p>暂无配置项</p>';

        const isModelGroup = MODEL_GROUPS.includes(activeGroupData.group);
        const quickSelectHtml = isModelGroup ? renderQuickSelect(activeGroupData.group) : '';
        const formFields = renderGroupFields(activeGroupData);

        return `
            <div class="settings-group-title">
                <i class="fas ${activeGroupData.icon}"></i>
                ${activeGroupData.label_zh}
                <span class="settings-group-subtitle">${activeGroupData.label_en}</span>
            </div>
            ${quickSelectHtml}
            <div class="settings-fields">${formFields}</div>
        `;
    }

    function renderQuickSelect(groupName) {
        if (_providers.length === 0) {
            return `
                <div class="provider-quick-select">
                    <div class="quick-select-header">
                        <i class="fas fa-magic"></i> 快速选择供应商
                    </div>
                    <div class="quick-select-empty">
                        暂无供应商，请先在「大模型」页面添加
                    </div>
                </div>
            `;
        }

        const targetGroup = GROUP_TARGET_MAP[groupName] || 'default';
        const options = _providers.map(p => {
            const models = (p.models || []).map(m =>
                `<option value="${p.id}|${m}">${p.name} / ${m}</option>`
            ).join('');
            return models;
        }).join('');

        return `
            <div class="provider-quick-select">
                <div class="quick-select-header">
                    <i class="fas fa-magic"></i> 快速选择供应商
                </div>
                <div class="quick-select-row">
                    <select class="quick-select-dropdown" id="quick-select-${groupName}" 
                            onchange="SettingsService.onQuickSelect('${targetGroup}', this.value)">
                        <option value="">-- 选择已配置的供应商和模型 --</option>
                        ${options}
                    </select>
                    <button class="quick-select-apply-btn" onclick="SettingsService.applyQuickSelect('${targetGroup}')">
                        <i class="fas fa-check"></i> 应用
                    </button>
                </div>
            </div>
        `;
    }

    function renderGroupFields(group) {
        if (!group || !group.items) return '<p>暂无配置项</p>';
        return group.items.map(item => {
            const isSensitive = /API_KEY|SECRET|PASSWORD|TOKEN/i.test(item.key);
            const inputType = isSensitive ? 'password' : 'text';
            const placeholder = item.raw_exists ? '' : '未设置';
            const eyeBtn = isSensitive ? `
                <button class="settings-eye-btn" type="button" 
                        onclick="SettingsService.togglePassword(this)" title="显示/隐藏">
                    <i class="fas fa-eye"></i>
                </button>` : '';
            return `
                <div class="settings-field">
                    <label class="settings-label" for="setting-${item.key}">
                        ${item.key}
                        ${isSensitive ? '<span class="settings-sensitive-badge"><i class="fas fa-lock"></i></span>' : ''}
                    </label>
                    <div class="settings-input-wrap">
                        <input class="settings-input" type="${inputType}" 
                               id="setting-${item.key}" 
                               data-key="${item.key}"
                               value="${escapeHtml(item.value)}"
                               placeholder="${placeholder}" />
                        ${eyeBtn}
                    </div>
                </div>
            `;
        }).join('');
    }

    /* ---------- 供应商管理页面 ---------- */
    function renderProvidersPage() {
        const providerCards = _providers.length === 0
            ? '<div class="cs-empty">暂无供应商配置</div>'
            : _providers.map((p, idx) => {
                if (_editingProvider && _editingProvider._idx === idx) {
                    return renderProviderForm(_editingProvider);
                }
                return renderProviderCard(p, idx);
            }).join('');

        const addFormHtml = _isAddingProvider ? renderProviderForm(null) : '';

        return `
            <div class="cs-header-title">
                <i class="fas fa-cube" style="color:#43e97b; margin-right:8px;"></i>
                大模型供应商管理 <span class="cs-header-sub">Model Providers</span>
            </div>
            <div class="cs-list">
                ${providerCards}
                ${addFormHtml}
            </div>
            ${!_isAddingProvider ? `
                <button class="settings-btn settings-btn-cancel" style="width: 100%; justify-content: center; padding: 10px; margin-top: 8px;" onclick="SettingsService.startAddProvider()">
                    <i class="fas fa-plus"></i> 添加供应商
                </button>
            ` : ''}
        `;
    }

    function renderProviderCard(provider, idx) {
        const models = (provider.models || []).join(', ') || '未配置模型';
        const enabledClass = provider.enabled !== false ? 'enabled' : 'disabled';

        return `
            <div class="cs-item ${enabledClass}" data-provider-id="${provider.id}">
                <div class="cs-item-header">
                    <span class="cs-icon">${getProviderIcon(provider.provider)}</span>
                </div>
                <div class="cs-item-title-row">
                    <span class="cs-name">${escapeHtml(provider.name || '未命名')}</span>
                    <span class="cs-badge">${escapeHtml(provider.provider || '')}</span>
                </div>
                <div class="cs-item-actions">
                    <button class="settings-btn settings-btn-save" onclick="SettingsService.testProvider(${idx})" title="测试连接">
                        <i class="fas fa-bolt"></i> 测试
                    </button>
                    <button class="settings-btn settings-btn-cancel" onclick="SettingsService.startEditProvider(${idx})" title="编辑">
                        <i class="fas fa-pen"></i> 编辑
                    </button>
                    <button class="settings-btn settings-btn-cancel" onclick="SettingsService.deleteProvider(${idx})" title="删除">
                        <i class="fas fa-trash-alt"></i> 删除
                    </button>
                </div>
                <div class="cs-item-info">
                    <i class="fas fa-link"></i>
                    <span>${escapeHtml(provider.base_url || '未设置')}</span>
                </div>
                <div class="cs-item-info">
                    <i class="fas fa-layer-group"></i>
                    <span>${escapeHtml(models)}</span>
                </div>
                <div class="provider-test-result" id="test-result-${idx}"></div>
            </div>
        `;
    }

    function getProviderIcon(provider) {
        const icons = {
            'openai': '🤖', 'deepseek': '🔮', 'anthropic': '🧠',
            'google': '🌐', 'qwen': '☁️', 'zhipu': '🔬',
            'moonshot': '🌙', 'baichuan': '🏔️', 'minimax': '⚡',
            'yi': '🎯', 'doubao': '🫧',
        };
        return icons[(provider || '').toLowerCase()] || '🧩';
    }

    function renderProviderForm(provider) {
        const p = provider || { name: '', provider: 'openai', api_key: '', base_url: '', models: [], enabled: true };
        const modelTags = (p.models || []).map(m =>
            `<span class="cs-model-tag" data-model="${escapeHtml(m)}">${escapeHtml(m)} <i class="fas fa-times cs-model-tag-remove" onclick="SettingsService.removeModelTag(this)"></i></span>`
        ).join('');

        return `
            <div class="cs-form">
                <div class="cs-form-row">
                    <div class="cs-input-group">
                        <label>名称</label>
                        <input type="text" id="pf-name" class="cs-input" value="${escapeHtml(p.name)}" placeholder="例如：阿里云百炼"/>
                    </div>
                    <div class="cs-input-group">
                        <label>类型</label>
                        <select id="pf-provider" class="cs-input">
                            ${['openai', 'deepseek', 'anthropic', 'google', 'qwen', 'zhipu', 'moonshot', 'baichuan', 'minimax', 'yi', 'doubao', 'other']
                .map(v => `<option value="${v}" ${v === p.provider ? 'selected' : ''}>${v}</option>`).join('')}
                        </select>
                    </div>
                </div>
                <div class="cs-form-row">
                    <div class="cs-input-group full">
                        <label>接口地址 (Base URL)</label>
                        <input type="text" id="pf-base-url" class="cs-input" value="${escapeHtml(p.base_url)}" placeholder="https://api.openai.com/v1"/>
                    </div>
                </div>
                <div class="cs-form-row">
                    <div class="cs-input-group full">
                        <label>API Key</label>
                        <div class="cs-input-with-icon">
                            <input type="password" id="pf-api-key" class="cs-input" value="${escapeHtml(p.api_key)}" placeholder="sk-xxxxxxxx"/>
                            <button class="cs-eye-btn" type="button" onclick="SettingsService.togglePassword(this)" title="显示/隐藏"><i class="fas fa-eye"></i></button>
                        </div>
                    </div>
                </div>
                <div class="cs-form-row">
                    <div class="cs-input-group full">
                        <label>模型列表</label>
                        <div class="cs-model-tags-container" id="pf-model-tags">
                            ${modelTags}
                        </div>
                        <div class="cs-model-add-row">
                            <input type="text" id="pf-model-input" class="cs-input" placeholder="输入模型名称 如 qwen3.5-plus" onkeydown="if(event.key==='Enter'){event.preventDefault();SettingsService.addModelTag()}"/>
                            <button class="settings-btn settings-btn-save" style="padding: 6px 12px; border-radius: 8px; white-space: nowrap;" onclick="SettingsService.addModelTag()">
                                <i class="fas fa-plus"></i> 添加
                            </button>
                        </div>
                    </div>
                </div>
                <div class="cs-form-actions">
                    <button class="settings-btn settings-btn-cancel" style="border-radius: 8px;" onclick="SettingsService.cancelProviderForm()">取消</button>
                    <button class="settings-btn settings-btn-save" style="border-radius: 8px;" onclick="SettingsService.saveProviderForm()">
                        <i class="fas fa-save"></i> 保存
                    </button>
                </div>
            </div>
        `;
    }

    /* ---------- 供应商操作 ---------- */
    function startAddProvider() {
        _isAddingProvider = true;
        _editingProvider = null;
        refreshProvidersPage();
    }

    function startEditProvider(idx) {
        _isAddingProvider = false;
        _editingProvider = { ..._providers[idx], _idx: idx };
        refreshProvidersPage();
    }

    function cancelProviderForm() {
        _isAddingProvider = false;
        _editingProvider = null;
        refreshProvidersPage();
    }

    function addModelTag() {
        const input = document.getElementById('pf-model-input');
        if (!input) return;
        const modelName = input.value.trim();
        if (!modelName) return;

        const container = document.getElementById('pf-model-tags');
        if (!container) return;

        // 检查是否已存在
        const existing = container.querySelectorAll('.cs-model-tag');
        for (const tag of existing) {
            if (tag.dataset.model === modelName) {
                showToast('模型已存在', 'error');
                return;
            }
        }

        const tag = document.createElement('span');
        tag.className = 'cs-model-tag';
        tag.dataset.model = modelName;
        tag.innerHTML = `${escapeHtml(modelName)} <i class="fas fa-times cs-model-tag-remove" onclick="SettingsService.removeModelTag(this)"></i>`;
        container.appendChild(tag);
        input.value = '';
        input.focus();
    }

    function removeModelTag(iconEl) {
        const tag = iconEl.closest('.cs-model-tag');
        if (tag) tag.remove();
    }

    async function saveProviderForm() {
        const name = document.getElementById('pf-name').value.trim();
        const provider = document.getElementById('pf-provider').value;
        const baseUrl = document.getElementById('pf-base-url').value.trim();
        const apiKey = document.getElementById('pf-api-key').value.trim();
        // 从 tag 容器读取模型列表
        const modelTags = document.querySelectorAll('#pf-model-tags .cs-model-tag');
        const models = Array.from(modelTags).map(t => t.dataset.model).filter(Boolean);

        if (!name) { showToast('请输入供应商名称', 'error'); return; }
        if (!baseUrl) { showToast('请输入 API Base URL', 'error'); return; }
        if (!apiKey) { showToast('请输入 API Key', 'error'); return; }

        const providerObj = {
            id: _editingProvider?.id || '',
            name, provider, api_key: apiKey, base_url: baseUrl, models, enabled: true,
        };

        if (_editingProvider && typeof _editingProvider._idx === 'number') {
            _providers[_editingProvider._idx] = providerObj;
        } else {
            _providers.push(providerObj);
        }

        try {
            await postProviders(_providers);
            // 重新拉取（获取服务端生成的 id）
            _providers = await fetchProviders();
            showToast('供应商已保存', 'success');
        } catch (e) {
            showToast('保存失败: ' + e.message, 'error');
        }

        _isAddingProvider = false;
        _editingProvider = null;
        refreshProvidersPage();
    }

    async function deleteProvider(idx) {
        if (!confirm(`确定删除供应商「${_providers[idx]?.name || ''}」？`)) return;
        _providers.splice(idx, 1);
        try {
            await postProviders(_providers);
            _providers = await fetchProviders();
            showToast('已删除', 'success');
        } catch (e) {
            showToast('删除失败: ' + e.message, 'error');
        }
        refreshProvidersPage();
    }

    async function testProvider(idx) {
        const p = _providers[idx];
        if (!p) return;
        const resultEl = document.getElementById(`test-result-${idx}`);
        if (!resultEl) return;

        const testModel = (p.models && p.models.length > 0) ? p.models[0] : 'gpt-4o-mini';
        resultEl.innerHTML = '<span class="test-loading"><i class="fas fa-spinner fa-spin"></i> 测试中...</span>';
        resultEl.style.display = 'block';

        try {
            const result = await testProviderAPI(p.id, testModel);
            if (result.code === 0) {
                resultEl.innerHTML = `<span class="test-success"><i class="fas fa-check-circle"></i> 连接成功 · 模型: ${result.data.model} · 延迟: ${result.data.latency_ms}ms</span>`;
            } else {
                const errMsg = (result.data && result.data.error) ? result.data.error : result.message;
                resultEl.innerHTML = `<span class="test-fail"><i class="fas fa-times-circle"></i> ${escapeHtml(errMsg)}</span>`;
            }
        } catch (e) {
            resultEl.innerHTML = `<span class="test-fail"><i class="fas fa-times-circle"></i> 请求失败: ${escapeHtml(e.message)}</span>`;
        }
    }

    function refreshProvidersPage() {
        const contentDiv = document.getElementById('settings-content-area');
        if (contentDiv && _activeGroup === 'providers') {
            contentDiv.innerHTML = renderProvidersPage();
        }
    }

    /* ---------- 快速选择 ---------- */
    function onQuickSelect(targetGroup, value) {
        // value is "providerId|modelName"
        if (!value) return;
    }

    async function applyQuickSelect(targetGroup) {
        // 找到对应的 select
        const groupName = Object.keys(GROUP_TARGET_MAP).find(k => GROUP_TARGET_MAP[k] === targetGroup);
        const select = document.getElementById(`quick-select-${groupName}`);
        if (!select || !select.value) {
            showToast('请先选择供应商和模型', 'error');
            return;
        }

        const [providerId, modelName] = select.value.split('|');
        if (!providerId || !modelName) return;

        try {
            const result = await applyProviderToGroup(providerId, modelName, targetGroup);
            if (result.code === 0) {
                showToast(`已应用到 ${targetGroup} 分组`, 'success');
                // 重新加载设置以更新显示
                const groups = await fetchSettings();
                _currentData = groups;
                updateSidebarAndContent(groups);
            } else {
                showToast(result.message || '应用失败', 'error');
            }
        } catch (e) {
            showToast('应用失败: ' + e.message, 'error');
        }
    }

    /* ---------- 工具函数 ---------- */
    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    /* ---------- 交互 ---------- */
    function switchGroup(groupName) {
        _activeGroup = groupName;
        if (_currentData) renderModal(_currentData, false);
    }

    function togglePassword(btn) {
        const input = btn.parentElement.querySelector('input');
        if (input.type === 'password') {
            input.type = 'text';
            btn.querySelector('i').classList.replace('fa-eye', 'fa-eye-slash');
        } else {
            input.type = 'password';
            btn.querySelector('i').classList.replace('fa-eye-slash', 'fa-eye');
        }
    }

    async function open() {
        try {
            const [groups, providers] = await Promise.all([fetchSettings(), fetchProviders()]);
            _providers = providers;
            renderModal(groups);
        } catch (e) {
            console.error('获取设置失败:', e);
            alert('获取设置失败: ' + e.message);
        }
    }

    function close() {
        const modal = document.getElementById('settings-modal');
        if (modal) {
            modal.classList.remove('show');
            setTimeout(() => { if (modal) modal.innerHTML = ''; }, 300);
        }
        document.body.style.overflow = '';
        _activeGroup = null;
        _isAddingProvider = false;
        _editingProvider = null;
    }

    async function save() {
        // 如果在供应商页面，无需保存设置
        if (_activeGroup === 'providers') {
            showToast('供应商配置已自动保存', 'success');
            return;
        }

        const inputs = document.querySelectorAll('.settings-input[data-key]');
        const settings = {};
        inputs.forEach(input => {
            settings[input.dataset.key] = input.value;
        });

        // 也收集非当前页面的分组数据（保留已有值）
        if (_currentData) {
            _currentData.forEach(group => {
                group.items.forEach(item => {
                    if (!(item.key in settings)) {
                        settings[item.key] = item.value;
                    }
                });
            });
        }

        const saveBtn = document.querySelector('.settings-btn-save');
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 保存中...';
        }

        try {
            const result = await postSettings(settings);
            const count = result.updated_keys ? result.updated_keys.length : 0;

            if (saveBtn) {
                saveBtn.innerHTML = '<i class="fas fa-check"></i> 已保存';
                saveBtn.classList.add('saved');
            }

            showToast(count > 0
                ? `保存成功，更新了 ${count} 个配置项`
                : '无需更新，配置未变化',
                'success'
            );

            setTimeout(async () => {
                const groups = await fetchSettings();
                _currentData = groups;
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = '<i class="fas fa-save"></i> 保存';
                    saveBtn.classList.remove('saved');
                }
            }, 1500);
        } catch (e) {
            console.error('保存设置失败:', e);
            showToast('保存失败: ' + e.message, 'error');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<i class="fas fa-save"></i> 保存';
            }
        }
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

    /* ---------- 公开接口 ---------- */
    return {
        open, close, save, switchGroup, togglePassword,
        startAddProvider, startEditProvider, cancelProviderForm, saveProviderForm,
        deleteProvider, testProvider, addModelTag, removeModelTag,
        onQuickSelect, applyQuickSelect,
    };
})();

// 导出到全局
window.SettingsService = SettingsService;
