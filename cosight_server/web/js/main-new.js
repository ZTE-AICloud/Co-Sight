/**
 * Co-Sight 三栏布局主逻辑
 */

// ==================== 工具函数 ====================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderMarkdown(text) {
    if (window.marked) {
        return marked.parse(text);
    }
    return text;
}

// ==================== 全局状态管理 ====================
const AppState = {
    leftSidebarCollapsed: false,
    rightSidebarCollapsed: false,
    currentThreadId: null,
    folders: [],
    ungroupedThreads: [],
    toolCalls: [],
    dagData: null,
    apiBaseUrl: 'http://localhost:7788/api/nae-deep-research/v1',
    draggedThreadId: null,
    renamingThreadId: null,
    deletingThreadId: null,
    deletingFolderId: null,
};

// ==================== 侧边栏控制 ====================

function initLeftSidebar() {
    const leftSidebar = document.getElementById('sidebar-left');
    const collapseBtn = document.getElementById('collapse-left-btn');
    const icon = collapseBtn.querySelector('i');
    const expandBtn = document.getElementById('sidebar-expand-btn');
    
    if (!leftSidebar || !collapseBtn) return;
    
    const savedState = localStorage.getItem('cosight:leftSidebarCollapsed');
    if (savedState === 'true') {
        leftSidebar.classList.add('collapsed');
        AppState.leftSidebarCollapsed = true;
        icon.classList.replace('fa-chevron-left', 'fa-chevron-right');
    }
    
    collapseBtn.addEventListener('click', () => {
        toggleLeftSidebar();
    });
    
    if (expandBtn) {
        expandBtn.addEventListener('click', () => {
            toggleLeftSidebar();
        });
    }
}

function toggleLeftSidebar() {
    const leftSidebar = document.getElementById('sidebar-left');
    const collapseBtn = document.getElementById('collapse-left-btn');
    const icon = collapseBtn.querySelector('i');
    
    AppState.leftSidebarCollapsed = !AppState.leftSidebarCollapsed;
    leftSidebar.classList.toggle('collapsed');
    localStorage.setItem('cosight:leftSidebarCollapsed', AppState.leftSidebarCollapsed);
    
    if (AppState.leftSidebarCollapsed) {
        icon.classList.replace('fa-chevron-left', 'fa-chevron-right');
    } else {
        icon.classList.replace('fa-chevron-right', 'fa-chevron-left');
    }
}

function initRightSidebar() {
    const rightSidebar = document.getElementById('sidebar-right');
    const expandBtn = document.getElementById('expand-right-btn');
    const closeBtn = document.getElementById('close-right-btn');
    const expandIcon = expandBtn.querySelector('i');
    
    if (!rightSidebar || !expandBtn || !closeBtn) return;
    
    const savedState = localStorage.getItem('cosight:rightSidebarCollapsed');
    if (savedState === 'true') {
        rightSidebar.classList.add('collapsed');
        AppState.rightSidebarCollapsed = true;
    }
    
    expandBtn.addEventListener('click', () => {
        toggleRightSidebar();
    });
    
    closeBtn.addEventListener('click', () => {
        rightSidebar.classList.add('collapsed');
        AppState.rightSidebarCollapsed = true;
        localStorage.setItem('cosight:rightSidebarCollapsed', 'true');
    });
}

function toggleRightSidebar() {
    const rightSidebar = document.getElementById('sidebar-right');
    const expandBtn = document.getElementById('expand-right-btn');
    const expandIcon = expandBtn.querySelector('i');
    
    AppState.rightSidebarCollapsed = !AppState.rightSidebarCollapsed;
    rightSidebar.classList.toggle('collapsed');
    localStorage.setItem('cosight:rightSidebarCollapsed', AppState.rightSidebarCollapsed);
    
    if (AppState.rightSidebarCollapsed) {
        expandIcon.classList.replace('fa-compress-alt', 'fa-expand-alt');
    } else {
        expandIcon.classList.replace('fa-expand-alt', 'fa-compress-alt');
    }
}

// ==================== 文件夹管理 ====================

function playExpandAnimation(content, toggle, folderIcon) {
    content.classList.add('expanded');
    toggle.classList.add('expanded');
    folderIcon.classList.add('expanded');
}

function playCollapseAnimation(content, toggle, folderIcon) {
    content.classList.remove('expanded');
    toggle.classList.remove('expanded');
    folderIcon.classList.remove('expanded');
}

function renderFolderList() {
    const folderList = document.getElementById('folder-list');
    if (!folderList) return;
    
    folderList.innerHTML = '';
    
    const defaultFolder = {
        id: 'default',
        name: '默认分组',
        threads: AppState.ungroupedThreads,
        isDefault: true,
        expanded: AppState.defaultFolderExpanded || false
    };
    const defaultGroupContainer = createFolderItem(defaultFolder);
    folderList.appendChild(defaultGroupContainer);
    
    AppState.folders.forEach(folder => {
        if (folder.expanded === undefined || folder.expanded === null) {
            folder.expanded = false;
        }
        const folderItem = createFolderItem(folder);
        folderList.appendChild(folderItem);
    });
}

function createFolderItem(folder) {
    const div = document.createElement('div');
    div.className = 'folder-item';
    div.dataset.folderId = folder.id;
    
    if (folder.expanded === undefined || folder.expanded === null) {
        folder.expanded = false;
    }
    const isExpanded = folder.expanded;
    
    const actionsHtml = folder.isDefault ? `
        <div class="folder-actions">
            <button class="folder-action-btn btn-add-thread-to-default" title="添加线程">
                <i class="fas fa-plus"></i>
            </button>
        </div>
    ` : `
        <div class="folder-actions">
            <button class="folder-action-btn btn-add-thread-to-folder" title="添加线程">
                <i class="fas fa-plus"></i>
            </button>
            <button class="folder-action-btn btn-delete-folder" title="删除文件夹">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `;
    
    div.innerHTML = `
        <div class="folder-header">
            <i class="fas fa-folder folder-icon ${isExpanded ? 'expanded' : ''}"></i>
            <span class="folder-item-name">${escapeHtml(folder.name)}</span>
            ${actionsHtml}
            <i class="fas fa-chevron-right folder-toggle ${isExpanded ? 'expanded' : ''}"></i>
        </div>
        <div class="folder-content ${isExpanded ? 'expanded' : ''}">
            <div class="folder-threads" data-folder-id="${folder.id}"></div>
        </div>
    `;
    
    const header = div.querySelector('.folder-header');
    const content = div.querySelector('.folder-content');
    const toggle = div.querySelector('.folder-toggle');
    const folderIcon = div.querySelector('.folder-icon');
    
    header.addEventListener('click', (e) => {
        if (e.target.closest('.folder-action-btn')) return;
        
        const newExpandedState = !folder.expanded;
        folder.expanded = newExpandedState;
        
        if (folder.id === 'default') {
            AppState.defaultFolderExpanded = newExpandedState;
        }
        
        if (newExpandedState) {
            playExpandAnimation(content, toggle, folderIcon);
        } else {
            playCollapseAnimation(content, toggle, folderIcon);
        }
        saveState();
    });
    
    if (folder.isDefault) {
        const addThreadBtn = div.querySelector('.btn-add-thread-to-default');
        if (addThreadBtn) {
            addThreadBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                createNewThreadInDefaultGroup();
            });
        }
    } else {
        const addThreadBtn = div.querySelector('.btn-add-thread-to-folder');
        if (addThreadBtn) {
            addThreadBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                createNewThreadInFolder(folder.id);
            });
        }
        
        const deleteFolderBtn = div.querySelector('.btn-delete-folder');
        if (deleteFolderBtn) {
            deleteFolderBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                openDeleteFolderConfirmModal(folder.id, folder.name);
            });
        }
    }
    
    renderFolderThreads(folder, div);
    
    return div;
}

function renderFolderThreads(folder, folderItem) {
    const threadsContainer = folderItem.querySelector('.folder-threads');
    if (!threadsContainer) return;
    
    threadsContainer.innerHTML = '';
    
    const threads = folder.threads || [];
    threads.forEach(thread => {
        const threadItem = createThreadItem(thread, folder.id);
        threadsContainer.appendChild(threadItem);
    });
}

function createThreadItem(thread, folderId) {
    const div = document.createElement('div');
    div.className = 'thread-item';
    div.dataset.threadId = thread.id;
    div.draggable = true;
    if (thread.id === AppState.currentThreadId) {
        div.classList.add('active');
    }
    if (thread.starred) {
        div.classList.add('starred');
    }
    
    const timeAgo = getTimeAgo(thread.updatedAt);
    
    div.innerHTML = `
        <i class="fas fa-comment-dots thread-icon"></i>
        <div class="thread-item-info">
            <div class="thread-item-title">${escapeHtml(thread.title || '新对话')}</div>
            <div class="thread-item-meta">
                <span>${timeAgo}</span>
                <span>•</span>
                <span>${thread.messageCount || 0} 条消息</span>
            </div>
        </div>
        <div class="thread-item-actions">
            <button class="thread-action-btn btn-rename-thread" title="重命名">
                <i class="fas fa-pen"></i>
            </button>
            <button class="thread-action-btn btn-delete-thread" title="删除">
                <i class="fas fa-trash"></i>
            </button>
            <button class="thread-item-star ${thread.starred ? 'starred' : ''}" title="标星">
                <i class="fas fa-star"></i>
            </button>
        </div>
    `;
    
    div.addEventListener('click', (e) => {
        if (e.target.closest('.thread-item-star') || e.target.closest('.thread-action-btn')) return;
        switchThread(thread.id);
    });
    
    const starBtn = div.querySelector('.thread-item-star');
    starBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleThreadStar(thread.id);
    });
    
    const renameBtn = div.querySelector('.btn-rename-thread');
    renameBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openRenameModal(thread.id);
    });
    
    const deleteBtn = div.querySelector('.btn-delete-thread');
    deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openDeleteConfirmModal(thread.id);
    });
    
    setupThreadDragDrop(div, thread.id, folderId);
    
    return div;
}

function setupThreadDragDrop(element, threadId, folderId) {
    element.addEventListener('dragstart', (e) => {
        AppState.draggedThreadId = threadId;
        AppState.draggedThreadSourceFolderId = folderId;
        element.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', threadId);
        const dragImage = document.createElement('div');
        dragImage.style.cssText = 'position: fixed; top: -1000px;';
        dragImage.textContent = '移动线程';
        document.body.appendChild(dragImage);
        e.dataTransfer.setDragImage(dragImage, 50, 25);
        setTimeout(() => document.body.removeChild(dragImage), 0);
    });
    
    element.addEventListener('dragend', () => {
        element.classList.remove('dragging');
        AppState.draggedThreadId = null;
        AppState.draggedThreadSourceFolderId = null;
        document.querySelectorAll('.folder-item.drag-over').forEach(el => {
            el.classList.remove('drag-over');
        });
    });
}

function initFolderDragDrop() {
    document.addEventListener('dragover', (e) => {
        const folderItem = e.target.closest('.folder-item');
        
        if (folderItem) {
            const targetFolderId = folderItem.dataset.folderId;
            
            if (targetFolderId === AppState.draggedThreadSourceFolderId) {
                folderItem.classList.remove('drag-over');
                return;
            }
            
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            
            if (!folderItem.classList.contains('drag-over')) {
                document.querySelectorAll('.folder-item.drag-over').forEach(el => {
                    el.classList.remove('drag-over');
                });
                folderItem.classList.add('drag-over');
            }
        }
    });
    
    document.addEventListener('dragleave', (e) => {
        const folderItem = e.target.closest('.folder-item');
        
        if (folderItem) {
            const rect = folderItem.getBoundingClientRect();
            if (e.clientX < rect.left || e.clientX > rect.right || 
                e.clientY < rect.top || e.clientY > rect.bottom) {
                folderItem.classList.remove('drag-over');
            }
        }
    });
    
    document.addEventListener('drop', (e) => {
        const folderItem = e.target.closest('.folder-item');
        
        if (folderItem) {
            e.preventDefault();
            e.stopPropagation();
            
            const targetFolderId = folderItem.dataset.folderId;
            
            if (targetFolderId === AppState.draggedThreadSourceFolderId) {
                folderItem.classList.remove('drag-over');
                return;
            }
            
            folderItem.classList.remove('drag-over');
            
            if (AppState.draggedThreadId) {
                moveThreadToFolder(AppState.draggedThreadId, targetFolderId === 'default' ? null : targetFolderId);
            }
        }
    });
}

function createNewFolder(name) {
    const folder = {
        id: 'folder-' + Date.now(),
        name: name,
        threads: [],
        expanded: false
    };
    
    AppState.folders.push(folder);
    renderFolderList();
    saveState();
    
    return folder;
}

function deleteFolder(folderId) {
    const index = AppState.folders.findIndex(f => f.id === folderId);
    if (index !== -1) {
        const folder = AppState.folders[index];
        const threadIdsInFolder = (folder.threads || []).map(t => t.id);
        if (threadIdsInFolder.includes(AppState.currentThreadId)) {
            AppState.currentThreadId = null;
            loadMessages([]);
            document.getElementById('conversation-title').textContent = '新对话';
        }
        
        AppState.folders.splice(index, 1);
        renderFolderList();
        saveState();
    }
}

function moveThreadToFolder(threadId, targetFolderId) {
    let sourceThread = null;
    let sourceArray = null;
    let sourceIndex = -1;
    
    const defaultIndex = AppState.ungroupedThreads.findIndex(t => t.id === threadId);
    if (defaultIndex !== -1) {
        sourceThread = AppState.ungroupedThreads[defaultIndex];
        sourceArray = AppState.ungroupedThreads;
        sourceIndex = defaultIndex;
    }
    
    if (!sourceThread) {
        for (const folder of AppState.folders) {
            const threadIndex = (folder.threads || []).findIndex(t => t.id === threadId);
            if (threadIndex !== -1) {
                sourceThread = folder.threads[threadIndex];
                sourceArray = folder.threads;
                sourceIndex = threadIndex;
                break;
            }
        }
    }
    
    if (!sourceThread || sourceIndex === -1) {
        console.error('未找到源线程:', threadId);
        return;
    }
    
    const threadCopy = JSON.parse(JSON.stringify(sourceThread));
    
    sourceArray.splice(sourceIndex, 1);
    
    if (targetFolderId) {
        const targetFolder = AppState.folders.find(f => f.id === targetFolderId);
        if (targetFolder) {
            if (!targetFolder.threads) targetFolder.threads = [];
            threadCopy.folderId = targetFolderId;
            targetFolder.threads.push(threadCopy);
        }
    } else {
        threadCopy.folderId = null;
        AppState.ungroupedThreads.push(threadCopy);
    }
    
    renderFolderList();
    saveState();
}

// ==================== 线程管理 ====================

function getThreadById(threadId) {
    let thread = AppState.ungroupedThreads.find(t => t.id === threadId);
    if (!thread) {
        AppState.folders.forEach(folder => {
            const found = (folder.threads || []).find(t => t.id === threadId);
            if (found) thread = found;
        });
    }
    return thread;
}

function createNewThread(title, folderId = null) {
    const thread = {
        id: 'thread-' + Date.now(),
        title: title,
        folderId: folderId,
        updatedAt: Date.now(),
        messageCount: 0,
        messages: []
    };
    
    if (folderId) {
        const folder = AppState.folders.find(f => f.id === folderId);
        if (folder) {
            if (!folder.threads) folder.threads = [];
            folder.threads.push(thread);
            folder.expanded = true;
        }
    } else {
        AppState.ungroupedThreads.push(thread);
    }
    
    renderFolderList();
    saveState();
    switchThread(thread.id);
    
    return thread;
}

function switchThread(threadId) {
    if (threadId === AppState.currentThreadId) return;
    
    AppState.currentThreadId = threadId;
    
    updateThreadActiveState();
    loadThread(threadId);
}

function updateThreadActiveState() {
    document.querySelectorAll('.thread-item').forEach(item => {
        item.classList.remove('active');
    });
    
    const activeThread = document.querySelector(`.thread-item[data-thread-id="${AppState.currentThreadId}"]`);
    if (activeThread) {
        activeThread.classList.add('active');
    }
}

function loadThread(threadId) {
    const thread = getThreadById(threadId);
    
    if (!thread) return;
    
    const titleEl = document.getElementById('conversation-title');
    if (titleEl) {
        titleEl.textContent = thread.title || '新对话';
    }
    
    loadMessages(thread.messages || []);
}

function loadMessages(messages) {
    const messageList = document.getElementById('message-list');
    const welcomeScreen = document.getElementById('welcome-screen');
    
    if (!messageList) return;
    
    messageList.innerHTML = '';
    
    if (messages.length === 0) {
        welcomeScreen.style.display = 'flex';
        messageList.style.display = 'none';
        return;
    }
    
    welcomeScreen.style.display = 'none';
    messageList.style.display = 'flex';
    
    messages.forEach(msg => {
        const messageItem = createMessageElement(msg);
        messageList.appendChild(messageItem);
    });
    
    scrollToBottom();
}

function createMessageElement(message) {
    const div = document.createElement('div');
    div.className = `message-item ${message.role}`;
    
    const avatarIcon = message.role === 'user' ? 'fa-user' : 'fa-robot';
    const content = message.role === 'assistant' 
        ? renderMarkdown(message.content) 
        : escapeHtml(message.content);
    
    const timeStr = formatTime(message.timestamp);
    
    div.innerHTML = `
        <div class="message-avatar">
            <i class="fas ${avatarIcon}"></i>
        </div>
        <div class="message-content">
            <div class="message-bubble">
                ${content}
            </div>
            <div class="message-meta">
                <span>${timeStr}</span>
            </div>
        </div>
    `;
    
    return div;
}

function addMessage(message) {
    const messageList = document.getElementById('message-list');
    const welcomeScreen = document.getElementById('welcome-screen');
    
    if (!messageList) return;
    
    welcomeScreen.style.display = 'none';
    messageList.style.display = 'flex';
    
    const messageItem = createMessageElement(message);
    messageList.appendChild(messageItem);
    
    scrollToBottom();
    updateCurrentThread();
}

function updateCurrentThread() {
    const thread = getCurrentThread();
    if (thread) {
        thread.updatedAt = Date.now();
        thread.messageCount = (thread.messages || []).length;
        saveState();
    }
}

function getCurrentThread() {
    if (!AppState.currentThreadId) return null;
    
    return getThreadById(AppState.currentThreadId);
}

function scrollToBottom() {
    const chatContainer = document.getElementById('chat-container');
    if (chatContainer) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
}

// ==================== 文件上传管理 ====================

const FileUploadConfig = {
    allowedExtensions: [
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
        '.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt',
        '.xls', '.xlsx', '.csv',
        '.ppt', '.pptx', '.key',
        '.mp3', '.wav', '.ogg', '.m4a',
        '.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv',
        '.js', '.ts', '.py', '.java', '.cpp', '.c', '.h', '.html', '.css', '.json', '.xml', '.md',
        '.zip', '.rar', '.7z', '.tar', '.gz'
    ],
    maxFileSize: 100 * 1024 * 1024,
    maxFiles: 10
};

let uploadedFiles = [];

function getFileType(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const mimeType = file.type;
    
    if (mimeType.startsWith('image/')) return 'image';
    if (mimeType.startsWith('audio/')) return 'audio';
    if (mimeType.startsWith('video/')) return 'video';
    if (ext === '.pdf' || mimeType === 'application/pdf') return 'pdf';
    if (['.doc', '.docx', '.txt', '.rtf', '.odt'].includes(ext)) return 'document';
    if (['.xls', '.xlsx', '.csv'].includes(ext)) return 'spreadsheet';
    if (['.ppt', '.pptx', '.key'].includes(ext)) return 'presentation';
    if (['.js', '.ts', '.py', '.java', '.cpp', '.c', '.h', '.html', '.css', '.json', '.xml', '.md'].includes(ext)) return 'code';
    if (['.zip', '.rar', '.7z', '.tar', '.gz'].includes(ext)) return 'archive';
    
    return 'other';
}

function getFileTypeIcon(fileType) {
    const icons = {
        image: 'fa-image',
        audio: 'fa-file-audio',
        video: 'fa-file-video',
        document: 'fa-file-word',
        spreadsheet: 'fa-file-excel',
        presentation: 'fa-file-powerpoint',
        pdf: 'fa-file-pdf',
        code: 'fa-file-code',
        archive: 'fa-file-archive',
        other: 'fa-file'
    };
    return icons[fileType] || 'fa-file';
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

function validateFile(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!FileUploadConfig.allowedExtensions.includes(ext)) {
        return { valid: false, message: `不支持的文件类型：${ext}` };
    }
    
    if (file.size > FileUploadConfig.maxFileSize) {
        return { valid: false, message: `文件大小超过限制 (${FileUploadConfig.maxFileSize / 1024 / 1024}MB)` };
    }
    
    return { valid: true };
}

function addUploadedFile(file) {
    const validation = validateFile(file);
    if (!validation.valid) {
        alert(validation.message);
        return false;
    }
    
    if (uploadedFiles.length >= FileUploadConfig.maxFiles) {
        alert(`最多只能上传 ${FileUploadConfig.maxFiles} 个文件`);
        return false;
    }
    
    if (uploadedFiles.some(f => f.name === file.name && f.size === file.size)) {
        alert('该文件已添加到上传列表');
        return false;
    }
    
    const fileData = {
        id: 'file-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9),
        file: file,
        name: file.name,
        size: file.size,
        type: getFileType(file),
        uploadedAt: Date.now()
    };
    
    uploadedFiles.push(fileData);
    renderFilePreview();
    return true;
}

function removeUploadedFile(fileId) {
    uploadedFiles = uploadedFiles.filter(f => f.id !== fileId);
    renderFilePreview();
}

function renderFilePreview() {
    const container = document.getElementById('file-preview-container');
    const list = document.getElementById('file-preview-list');
    
    if (!container || !list) return;
    
    if (uploadedFiles.length === 0) {
        container.style.display = 'none';
        list.innerHTML = '';
        return;
    }
    
    container.style.display = 'block';
    list.innerHTML = '';
    
    uploadedFiles.forEach(fileData => {
        const item = createFilePreviewItem(fileData);
        list.appendChild(item);
    });
}

function createFilePreviewItem(fileData) {
    const div = document.createElement('div');
    div.className = 'file-preview-item';
    
    const fileType = fileData.type;
    const fileSize = formatFileSize(fileData.size);
    
    if (fileType === 'image') {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = div.querySelector('.file-preview-image');
            if (img) {
                img.src = e.target.result;
            }
        };
        reader.readAsDataURL(fileData.file);
        
        div.innerHTML = `
            <img class="file-preview-image" src="" alt="${escapeHtml(fileData.name)}">
            <div class="file-preview-info">
                <div class="file-preview-name">${escapeHtml(fileData.name)}</div>
                <div class="file-preview-size">${fileSize}</div>
            </div>
            <button class="file-preview-remove" title="移除">
                <i class="fas fa-times"></i>
            </button>
        `;
    } else {
        const iconClass = getFileTypeIcon(fileType);
        div.innerHTML = `
            <div class="file-preview-icon ${fileType}">
                <i class="fas ${iconClass}"></i>
            </div>
            <div class="file-preview-info">
                <div class="file-preview-name">${escapeHtml(fileData.name)}</div>
                <div class="file-preview-size">${fileSize}</div>
            </div>
            <button class="file-preview-remove" title="移除">
                <i class="fas fa-times"></i>
            </button>
        `;
    }
    
    const removeBtn = div.querySelector('.file-preview-remove');
    removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeUploadedFile(fileData.id);
    });
    
    return div;
}

function getAllowedFileTypesAttr() {
    const imageTypes = ['image/*'];
    const audioTypes = ['audio/*'];
    const videoTypes = ['video/*'];
    const docTypes = ['.doc', '.docx', '.pdf', '.txt', '.rtf', '.odt'];
    const sheetTypes = ['.xls', '.xlsx', '.csv'];
    const presentationTypes = ['.ppt', '.pptx', '.key'];
    const codeTypes = ['.js', '.ts', '.py', '.java', '.cpp', '.c', '.h', '.html', '.css', '.json', '.xml', '.md'];
    const archiveTypes = ['.zip', '.rar', '.7z', '.tar', '.gz'];
    
    return [
        ...imageTypes,
        ...audioTypes,
        ...videoTypes,
        ...docTypes,
        ...sheetTypes,
        ...presentationTypes,
        ...codeTypes,
        ...archiveTypes
    ].join(',');
}

// ==================== 输入处理 ====================

function initInputArea() {
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const uploadFileBtn = document.getElementById('upload-file-btn');
    const clearChatBtn = document.getElementById('clear-chat-btn');
    const exportChatBtn = document.getElementById('export-chat-btn');
    
    if (!chatInput || !sendBtn) return;
    
    function adjustTextareaHeight() {
        const chatInput = document.getElementById('chat-input');
        if (!chatInput) return;
        
        const minHeight = 68;
        const maxHeight = 136;
        const lineHeight = 22.5;
        
        chatInput.style.height = 'auto';
        chatInput.style.overflowY = 'hidden';
        
        const scrollHeight = chatInput.scrollHeight;
        
        if (!chatInput.value.trim()) {
            chatInput.style.height = minHeight + 'px';
            return;
        }
        
        let newHeight = scrollHeight;
        newHeight = Math.max(minHeight, Math.min(newHeight, maxHeight));
        
        const extraHeight = newHeight - minHeight;
        const extraRows = Math.ceil(extraHeight / lineHeight);
        newHeight = minHeight + (extraRows * lineHeight);
        
        newHeight = Math.min(newHeight, maxHeight);
        
        chatInput.style.height = newHeight + 'px';
        
        if (scrollHeight > maxHeight) {
            chatInput.style.overflowY = 'auto';
        } else {
            chatInput.style.overflowY = 'hidden';
        }
    }
    
    chatInput.addEventListener('input', adjustTextareaHeight);
    adjustTextareaHeight();
    
    sendBtn.addEventListener('click', () => {
        sendMessage();
    });
    
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    if (uploadFileBtn) {
        uploadFileBtn.addEventListener('click', () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.multiple = true;
            input.onchange = (e) => {
                handleFileUpload(e.target.files);
            };
            input.click();
        });
    }
    
    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', () => {
            if (confirm('确定要清空当前对话吗？')) {
                clearCurrentChat();
            }
        });
    }
    
    if (exportChatBtn) {
        exportChatBtn.addEventListener('click', () => {
            exportCurrentChat();
        });
    }
}

function sendMessage() {
    const chatInput = document.getElementById('chat-input');
    const message = chatInput.value.trim();
    
    if (!message) return;
    
    const userMessage = {
        role: 'user',
        content: message,
        timestamp: Date.now()
    };
    addMessage(userMessage);
    
    chatInput.value = '';
    chatInput.style.height = 'auto';
    
    showThinkingState();
    sendToBackend(message);
}

async function sendToBackend(message) {
    try {
        const response = await fetch(`${AppState.apiBaseUrl}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: message,
                threadId: AppState.currentThreadId
            })
        });
        
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        
        const data = await response.json();
        hideThinkingState();
        
        addMessage({
            role: 'assistant',
            content: data.response || '收到消息',
            timestamp: Date.now()
        });
        
        const thread = getCurrentThread();
        if (thread && thread.messageCount === 1) {
            thread.title = message.substring(0, 30) + (message.length > 30 ? '...' : '');
            renderFolderList();
            saveState();
        }
        
    } catch (error) {
        console.error('发送消息失败:', error);
        hideThinkingState();
        
        addMessage({
            role: 'assistant',
            content: '抱歉，连接服务器失败。请确保后端服务正在运行。',
            timestamp: Date.now()
        });
    }
}

function showThinkingState() {
    const messageList = document.getElementById('message-list');
    if (!messageList) return;
    
    const thinkingDiv = document.createElement('div');
    thinkingDiv.className = 'message-item assistant';
    thinkingDiv.id = 'thinking-message';
    thinkingDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-robot"></i>
        </div>
        <div class="message-content">
            <div class="message-bubble">
                <div class="thinking-indicator">
                    <i class="fas fa-cog loading-spinner"></i>
                    <span>正在思考...</span>
                </div>
            </div>
        </div>
    `;
    
    messageList.appendChild(thinkingDiv);
    scrollToBottom();
}

function hideThinkingState() {
    const thinkingMessage = document.getElementById('thinking-message');
    if (thinkingMessage) {
        thinkingMessage.remove();
    }
}

function handleFileUpload(files) {
    if (!files || files.length === 0) return;
    
    Array.from(files).forEach(file => {
        addUploadedFile(file);
    });
}

function clearCurrentChat() {
    const thread = getCurrentThread();
    if (thread) {
        thread.messages = [];
        thread.messageCount = 0;
        thread.updatedAt = Date.now();
        saveState();
        loadMessages([]);
    }
}

function exportCurrentChat() {
    const thread = getCurrentThread();
    if (!thread) return;
    
    const content = (thread.messages || []).map(msg => {
        const role = msg.role === 'user' ? '用户' : '助手';
        return `[${role}] ${formatTime(msg.timestamp)}\n${msg.content}\n`;
    }).join('\n---\n\n');
    
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${thread.title || '对话'}-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
}

// ==================== 工具链展示 ====================

function addToolCallToChain(toolCall) {
    const toolChainList = document.getElementById('tool-chain-list');
    const toolCountEl = document.getElementById('tool-count');
    
    if (!toolChainList) return;
    
    AppState.toolCalls.push(toolCall);
    
    const toolItem = createToolChainItem(toolCall);
    toolChainList.insertBefore(toolItem, toolChainList.firstChild);
    
    if (toolCountEl) {
        toolCountEl.textContent = AppState.toolCalls.length;
    }
}

function createToolChainItem(toolCall) {
    const div = document.createElement('div');
    div.className = `tool-chain-item ${toolCall.status}`;
    
    const iconClass = getToolIcon(toolCall.tool);
    const toolName = getToolDisplayName(toolCall.tool);
    const statusText = getToolStatusText(toolCall.status);
    
    div.innerHTML = `
        <div class="tool-chain-icon ${toolCall.status}">
            <i class="${iconClass}"></i>
        </div>
        <div class="tool-chain-content">
            <div class="tool-chain-name">${toolName}</div>
            <div class="tool-chain-status">${statusText}</div>
            ${toolCall.result ? `<div class="tool-chain-result">${escapeHtml(toolCall.result.substring(0, 100))}...</div>` : ''}
        </div>
    `;
    
    return div;
}

function getToolIcon(toolName) {
    const icons = {
        search_baidu: 'fab fa-baidu',
        search_google: 'fab fa-google',
        file_saver: 'fas fa-save',
        file_read: 'fas fa-file-alt',
        execute_code: 'fas fa-code',
        create_plan: 'fas fa-tasks',
        search_wiki: 'fab fa-wikipedia-w',
        tavily_search: 'fas fa-search',
    };
    return icons[toolName] || 'fas fa-tools';
}

function getToolDisplayName(toolName) {
    const names = {
        search_baidu: '百度搜索',
        search_google: '谷歌搜索',
        file_saver: '文件保存',
        file_read: '文件读取',
        execute_code: '代码执行',
        create_plan: '创建计划',
        search_wiki: '维基百科搜索',
        tavily_search: 'Tavily 搜索',
    };
    return names[toolName] || toolName;
}

function getToolStatusText(status) {
    const texts = {
        running: '执行中...',
        completed: '执行完成',
        failed: '执行失败',
    };
    return texts[status] || status;
}

// ==================== 进度更新 ====================

function updateProgressStats(stats) {
    const completedCount = document.getElementById('completed-count');
    const inProgressCount = document.getElementById('in-progress-count');
    const blockedCount = document.getElementById('blocked-count');
    const notStartedCount = document.getElementById('not-started-count');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    
    if (completedCount) completedCount.textContent = stats.completed || 0;
    if (inProgressCount) inProgressCount.textContent = stats.in_progress || 0;
    if (blockedCount) blockedCount.textContent = stats.blocked || 0;
    if (notStartedCount) notStartedCount.textContent = stats.not_started || 0;
    
    const total = (stats.completed || 0) + (stats.in_progress || 0) + (stats.blocked || 0) + (stats.not_started || 0);
    const percentage = total > 0 ? Math.round((stats.completed || 0) / total * 100) : 0;
    
    if (progressFill) progressFill.style.width = percentage + '%';
    if (progressText) progressText.textContent = percentage + '%';
}

// ==================== 状态持久化 ====================

function saveState() {
    const state = {
        folders: AppState.folders,
        ungroupedThreads: AppState.ungroupedThreads,
        currentThreadId: AppState.currentThreadId
    };
    localStorage.setItem('cosight:state', JSON.stringify(state));
}

function loadState() {
    const saved = localStorage.getItem('cosight:state');
    if (saved) {
        try {
            const state = JSON.parse(saved);
            AppState.folders = state.folders || [];
            AppState.ungroupedThreads = state.ungroupedThreads || [];
            AppState.currentThreadId = state.currentThreadId;
            
            AppState.folders.forEach(folder => {
                if (folder.expanded === undefined || folder.expanded === null) {
                    folder.expanded = true;
                }
            });
            
            if (AppState.defaultFolderExpanded === undefined || AppState.defaultFolderExpanded === null) {
                AppState.defaultFolderExpanded = true;
            }
        } catch (e) {
            console.error('加载状态失败:', e);
        }
    } else {
        AppState.defaultFolderExpanded = true;
    }
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
    if (diff < 604800000) return Math.floor(diff / 86400000) + '天前';
    
    return date.toLocaleDateString('zh-CN');
}

function getTimeAgo(timestamp) {
    return formatTime(timestamp);
}

function toggleThreadStar(threadId) {
    const thread = getThreadById(threadId);
    if (thread) {
        thread.starred = !thread.starred;
        renderFolderList();
        saveState();
    }
}

function deleteThread(threadId) {
    const defaultIndex = AppState.ungroupedThreads.findIndex(t => t.id === threadId);
    if (defaultIndex !== -1) {
        AppState.ungroupedThreads.splice(defaultIndex, 1);
    }
    
    AppState.folders.forEach(folder => {
        const threadIndex = (folder.threads || []).findIndex(t => t.id === threadId);
        if (threadIndex !== -1) {
            folder.threads.splice(threadIndex, 1);
        }
    });
    
    if (threadId === AppState.currentThreadId) {
        AppState.currentThreadId = null;
        loadMessages([]);
        document.getElementById('conversation-title').textContent = '新对话';
    }
    
    renderFolderList();
    saveState();
}

// ==================== 重命名弹窗 ====================

function openRenameModal(threadId) {
    const thread = getThreadById(threadId);
    if (!thread) return;
    
    AppState.renamingThreadId = threadId;
    
    const modal = document.getElementById('rename-modal-overlay');
    const input = document.getElementById('rename-input');
    
    if (modal && input) {
        input.value = thread.title || '新对话';
        modal.style.display = 'flex';
        input.focus();
        input.select();
    }
}

function closeRenameModal() {
    const modal = document.getElementById('rename-modal-overlay');
    if (modal) {
        modal.style.display = 'none';
    }
    AppState.renamingThreadId = null;
}

function confirmRename() {
    const input = document.getElementById('rename-input');
    const newName = input.value.trim();
    
    if (newName && AppState.renamingThreadId) {
        const thread = getThreadById(AppState.renamingThreadId);
        if (thread) {
            thread.title = newName;
            renderFolderList();
            saveState();
            
            if (AppState.renamingThreadId === AppState.currentThreadId) {
                document.getElementById('conversation-title').textContent = newName;
            }
        }
    }
    
    closeRenameModal();
}

function initRenameModal() {
    const closeBtn = document.getElementById('close-rename-modal');
    const cancelBtn = document.getElementById('cancel-rename-btn');
    const confirmBtn = document.getElementById('confirm-rename-btn');
    const input = document.getElementById('rename-input');
    const renameTitleBtn = document.getElementById('rename-title-btn');
    
    if (!closeBtn) return;
    
    closeBtn.addEventListener('click', closeRenameModal);
    cancelBtn.addEventListener('click', closeRenameModal);
    
    confirmBtn.addEventListener('click', confirmRename);
    
    if (renameTitleBtn) {
        renameTitleBtn.addEventListener('click', () => {
            openTitleRenameModal();
        });
    }
    
    const modal = document.getElementById('rename-modal-overlay');
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeRenameModal();
        }
    });
    
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            confirmRename();
        }
    });
}

function openTitleRenameModal() {
    const currentTitle = document.getElementById('conversation-title').textContent;
    
    AppState.renamingThreadId = AppState.currentThreadId;
    
    const modal = document.getElementById('rename-modal-overlay');
    const input = document.getElementById('rename-input');
    
    if (modal && input) {
        input.value = currentTitle || '新对话';
        modal.style.display = 'flex';
        input.focus();
        input.select();
    }
}

// ==================== 删除确认弹窗 ====================

function openDeleteConfirmModal(threadId) {
    const thread = getThreadById(threadId);
    if (!thread) return;
    
    AppState.deletingThreadId = threadId;
    
    const modal = document.getElementById('delete-confirm-modal-overlay');
    const messageEl = document.getElementById('delete-confirm-message');
    
    if (modal && messageEl) {
        messageEl.textContent = `确定要删除线程"${thread.title}"吗？此操作不可恢复。`;
        modal.style.display = 'flex';
    }
}

function openDeleteFolderConfirmModal(folderId, folderName) {
    AppState.deletingFolderId = folderId;
    
    const modal = document.getElementById('delete-folder-confirm-modal-overlay');
    const messageEl = document.getElementById('delete-folder-confirm-message');
    
    if (modal && messageEl) {
        messageEl.textContent = `确定要删除文件夹"${folderName}"及其中的所有线程吗？此操作不可恢复。`;
        modal.style.display = 'flex';
    }
}

function closeDeleteConfirmModal() {
    const modal = document.getElementById('delete-confirm-modal-overlay');
    if (modal) {
        modal.style.display = 'none';
    }
    AppState.deletingThreadId = null;
}

function confirmDelete() {
    if (AppState.deletingThreadId) {
        deleteThread(AppState.deletingThreadId);
    }
    closeDeleteConfirmModal();
}

function confirmDeleteFolder() {
    if (AppState.deletingFolderId) {
        deleteFolder(AppState.deletingFolderId);
    }
    closeDeleteFolderConfirmModal();
}

function closeDeleteFolderConfirmModal() {
    const modal = document.getElementById('delete-folder-confirm-modal-overlay');
    if (modal) {
        modal.style.display = 'none';
    }
    AppState.deletingFolderId = null;
}

function initDeleteConfirmModal() {
    const closeBtn = document.getElementById('close-delete-confirm-modal');
    const cancelBtn = document.getElementById('cancel-delete-confirm-btn');
    const confirmBtn = document.getElementById('confirm-delete-confirm-btn');
    
    if (!closeBtn) return;
    
    closeBtn.addEventListener('click', closeDeleteConfirmModal);
    cancelBtn.addEventListener('click', closeDeleteConfirmModal);
    
    confirmBtn.addEventListener('click', confirmDelete);
    
    const modal = document.getElementById('delete-confirm-modal-overlay');
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeDeleteConfirmModal();
        }
    });
}

function initDeleteFolderConfirmModal() {
    const closeBtn = document.getElementById('close-delete-folder-confirm-modal');
    const cancelBtn = document.getElementById('cancel-delete-folder-confirm-btn');
    const confirmBtn = document.getElementById('confirm-delete-folder-confirm-btn');
    
    if (!closeBtn) return;
    
    closeBtn.addEventListener('click', closeDeleteFolderConfirmModal);
    cancelBtn.addEventListener('click', closeDeleteFolderConfirmModal);
    
    confirmBtn.addEventListener('click', confirmDeleteFolder);
    
    const modal = document.getElementById('delete-folder-confirm-modal-overlay');
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeDeleteFolderConfirmModal();
        }
    });
}

// ==================== 弹窗控制 ====================

function initFolderModal() {
    const newFolderBtn = document.getElementById('new-folder-btn');
    const modalOverlay = document.getElementById('folder-modal-overlay');
    const closeBtn = document.getElementById('close-folder-modal');
    const cancelBtn = document.getElementById('cancel-folder-btn');
    const confirmBtn = document.getElementById('confirm-folder-btn');
    const nameInput = document.getElementById('folder-name-input');
    
    if (!newFolderBtn || !modalOverlay) return;
    
    newFolderBtn.addEventListener('click', () => {
        modalOverlay.style.display = 'flex';
        nameInput.value = '';
        nameInput.focus();
    });
    
    const closeModal = () => {
        modalOverlay.style.display = 'none';
    };
    
    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) {
            closeModal();
        }
    });
    
    confirmBtn.addEventListener('click', () => {
        const name = nameInput.value.trim();
        if (name) {
            createNewFolder(name);
            closeModal();
        }
    });
    
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const name = nameInput.value.trim();
            if (name) {
                createNewFolder(name);
                closeModal();
            }
        }
    });
}

function initNewThreadBtn() {
    const newThreadBtn = document.getElementById('new-thread-btn');
    const newChatBubbleBtn = document.getElementById('new-chat-bubble-btn');
    
    if (newThreadBtn) {
        newThreadBtn.addEventListener('click', () => {
            createNewThreadInDefaultGroup();
        });
    }
    
    if (newChatBubbleBtn) {
        newChatBubbleBtn.addEventListener('click', () => {
            createNewThreadInDefaultGroup();
        });
    }
}

function getFolderById(folderId) {
    if (folderId === 'default') {
        return {
            id: 'default',
            name: '默认分组',
            threads: AppState.ungroupedThreads,
            expanded: AppState.defaultFolderExpanded || false,
            isDefault: true
        };
    } else {
        const folder = AppState.folders.find(f => f.id === folderId);
        if (folder) {
            return {
                ...folder,
                isDefault: false
            };
        }
    }
    return null;
}

function createNewThreadInFolder(folderId) {
    let wasExpanded;
    let targetFolder = null;
    
    if (folderId === 'default') {
        wasExpanded = AppState.defaultFolderExpanded || false;
    } else {
        targetFolder = AppState.folders.find(f => f.id === folderId);
        wasExpanded = targetFolder ? (targetFolder.expanded ?? false) : false;
    }
    
    const thread = {
        id: 'thread-' + Date.now(),
        title: '新对话',
        folderId: folderId === 'default' ? null : folderId,
        updatedAt: Date.now(),
        messageCount: 0,
        messages: []
    };
    
    if (folderId === 'default') {
        AppState.ungroupedThreads.push(thread);
    } else {
        if (targetFolder) {
            if (!targetFolder.threads) targetFolder.threads = [];
            targetFolder.threads.push(thread);
        }
    }
    
    if (!wasExpanded) {
        saveState();
        renderFolderList();
        
        setTimeout(() => {
            const folderItem = document.querySelector(`.folder-item[data-folder-id="${folderId}"]`);
            if (folderItem) {
                const content = folderItem.querySelector('.folder-content');
                const toggle = folderItem.querySelector('.folder-toggle');
                const folderIcon = folderItem.querySelector('.folder-icon');
                
                if (content && toggle && folderIcon) {
                    playExpandAnimation(content, toggle, folderIcon);
                }
            }
        }, 0);

        if (folderId === 'default') {
            AppState.defaultFolderExpanded = true;
        } else {
            if (targetFolder) {
                targetFolder.expanded = true;
            }
        }
    } else {
        renderFolderList();
        saveState();
    }
    
    switchThread(thread.id);
    
    return thread;
}

function createNewThreadInDefaultGroup() {
    return createNewThreadInFolder('default');
}

// ==================== 设置管理 ====================

function initSettingsModal() {
    const settingsBtn = document.getElementById('settings-btn');
    
    if (!settingsBtn) return;
    
    settingsBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        
        if (window.SettingsService) {
            try {
                await SettingsService.open();
            } catch (err) {
                alert('打开设置失败：' + err.message);
            }
        } else {
            alert('SettingsService 未加载，请刷新页面重试');
        }
    });
}

// ==================== 初始化 ====================

function initThreeColumnLayout() {
    loadState();
    
    initLeftSidebar();
    initRightSidebar();
    initInputArea();
    initFolderModal();
    initNewThreadBtn();
    initRenameModal();
    initDeleteConfirmModal();
    initDeleteFolderConfirmModal();
    initSettingsModal();
    initFolderDragDrop();
    
    renderFolderList();
    
    if (AppState.folders.length === 0 && AppState.ungroupedThreads.length === 0) {
        loadExampleData();
    }
    
    if (AppState.currentThreadId) {
        loadThread(AppState.currentThreadId);
    }
}

function loadExampleData() {
    const folder = createNewFolder('工作项目');
    
    createNewThread('江苏足球联赛球队表现分析', folder.id);
    createNewThread('GDP 数据分析报告');
    createNewThread('代码审查与优化');
    
    if (AppState.ungroupedThreads.length > 0) {
        switchThread(AppState.ungroupedThreads[0].id);
    }
}

document.addEventListener('DOMContentLoaded', initThreeColumnLayout);

window.AppState = AppState;
window.updateProgressStats = updateProgressStats;
window.addToolCallToChain = addToolCallToChain;
window.addMessage = addMessage;
window.toggleRightSidebar = toggleRightSidebar;
window.createThread = createNewThread;
window.getThreadById = getThreadById;