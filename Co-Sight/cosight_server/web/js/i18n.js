/**
 * 前端国际化服务类
 * 支持中英文自动切换和手动切换
 */
class I18nService {
    constructor() {
        this.translations = {};
        this.currentLanguage = this.getBrowserLanguage();
        this.defaultLanguage = 'zh';
        this.loadTranslations();
    }

    /**
     * 获取浏览器语言设置
     * @returns {string} 语言代码
     */
    getBrowserLanguage() {
        let lang = navigator.language || navigator.userLanguage;
        if (lang) {
            lang = lang.split('-')[0].toLowerCase();
        }
        return lang || 'zh';
    }

    /**
     * 加载翻译资源
     */
    async loadTranslations() {
        try {
            const response = await fetch('./js/i18n.json');
            this.translations = await response.json();
            this.updatePageLanguage();
        } catch (error) {
            console.warn('加载翻译文件失败:', error);
        }
    }

    /**
     * 获取翻译文本
     * @param {string} key - 翻译键
     * @param {string} lang - 语言代码（可选）
     * @returns {string} 翻译后的文本
     */
    t(key, lang = null) {
        const targetLang = lang || this.currentLanguage;
        const translations = this.translations[targetLang] || this.translations[this.defaultLanguage];
        return translations[key] || key;
    }

    /**
     * 设置当前语言
     * @param {string} lang - 语言代码
     */
    setLanguage(lang) {
        if (this.translations[lang]) {
            this.currentLanguage = lang;
            localStorage.setItem('cosight:language', lang);
            this.updatePageLanguage();
            
            // 同步WebSocket服务的语言设置
            if (window.WebSocketService) {
                window.WebSocketService.setLang(lang);
            }
        }
    }

    /**
     * 获取当前语言
     * @returns {string} 当前语言代码
     */
    getCurrentLanguage() {
        return this.currentLanguage;
    }

    /**
     * 更新页面语言
     */
    updatePageLanguage() {
        // 更新页面标题
        const titleElement = document.querySelector('h1');
        if (titleElement) {
            titleElement.innerHTML = `<i class="fas fa-robot"></i> ${this.t('app_title')}`;
        }

        // 更新欢迎信息
        const welcomeTitle = document.querySelector('.welcome-title');
        if (welcomeTitle) {
            welcomeTitle.textContent = this.t('welcome_title');
        }

        const welcomeSubtitle = document.querySelector('.welcome-subtitle');
        if (welcomeSubtitle) {
            welcomeSubtitle.textContent = this.t('welcome_subtitle');
        }

        // 更新输入框占位符
        const inputPlaceholders = document.querySelectorAll('[placeholder*="请输入你的任务"]');
        inputPlaceholders.forEach(input => {
            input.placeholder = this.t('input_placeholder');
        });

        // 更新状态标签
        const statusLabels = {
            'completed': this.t('completed'),
            'in_progress': this.t('in_progress'),
            'blocked': this.t('blocked'),
            'not_started': this.t('not_started')
        };

        Object.entries(statusLabels).forEach(([key, value]) => {
            const elements = document.querySelectorAll(`[data-i18n="${key}"]`);
            elements.forEach(el => {
                el.textContent = value;
            });
        });

        // 更新其他文本
        const overallProgress = document.querySelector('.progress-percentage');
        if (overallProgress) {
            overallProgress.innerHTML = `${this.t('overall_progress')}: <span id="progress-percentage">0%</span>`;
        }

        const stepTitle = document.getElementById('step-title');
        if (stepTitle) {
            stepTitle.textContent = this.t('select_node_title');
        }

        const stepDescription = document.getElementById('step-description');
        if (stepDescription) {
            stepDescription.textContent = this.t('select_node_description');
        }

        const cosightComputer = document.querySelector('.right-header h3');
        if (cosightComputer) {
            cosightComputer.innerHTML = `<i class="fas fa-info-circle"></i> ${this.t('cosight_computer')}`;
        }

        const viewingContent = document.getElementById('right-container-status');
        if (viewingContent) {
            viewingContent.textContent = this.t('viewing_file_content');
        }

        // 更新DAG操作提示
        const dagTips = document.querySelectorAll('.tip-content span');
        if (dagTips.length >= 2) {
            dagTips[0].textContent = this.t('scroll_to_zoom');
            dagTips[1].textContent = this.t('drag_to_move');
        }
    }

    /**
     * 初始化国际化服务
     */
    async init() {
        // 检查本地存储的语言设置
        const savedLang = localStorage.getItem('cosight:language');
        if (savedLang && this.translations[savedLang]) {
            this.currentLanguage = savedLang;
        }

        await this.loadTranslations();
        this.updatePageLanguage();
    }
}

// 创建全局实例
window.I18nService = new I18nService();

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    window.I18nService.init();
}); 