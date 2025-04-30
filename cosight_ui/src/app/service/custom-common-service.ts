import {HttpClient, HttpHeaders} from "@angular/common/http";
import {EventEmitter, Injectable} from '@angular/core';
import {TranslateService} from "@rdkmaster/ngx-translate-core";
import {JigsawToast, LoadingService} from "@rdkmaster/jigsaw";
import {CommonService, LanguageService, LuiPopupService, messageService, ResponseBase, userInfo} from '@rdkmaster/lui-sdk';

export interface ServerResponse<T> extends ResponseBase {
    data?: T;
}

export type AiSearchMode = 'flash' | 'advanced';

@Injectable({
    providedIn: 'root'
})
export class CustomCommonService extends CommonService {
    public aiSearchEnabled: boolean = false;
    public aiSearchMode: AiSearchMode = 'flash';
    public aiSearchEnabledChange: EventEmitter<boolean> = new EventEmitter();

    public deepResearchEnabled: boolean = false;
    public deepResearchEnabledChange: EventEmitter<boolean> = new EventEmitter();

    public deepReasoningEnabled: boolean = false;

    constructor(private _http: HttpClient,
                private _popupService: LuiPopupService,
                private _translateService: TranslateService,
                private _loadingService: LoadingService,
                private _languageService: LanguageService) {
        super();
    }

    public getUserName(): string {
        return super.getUserName();
    }

    public getHeaders(): HttpHeaders {
        return new HttpHeaders().set('user-info', encodeURIComponent(userInfo.name)).set('locale', this._languageService.getLang());
    }

    // 这是一个处理多行文本字符串的方法 为了让多行文本在编译器里有更好的格式和阅读体验
    public stripBlank(script: string): string {
        if (typeof script !== 'string' || !script.trim()) {
            return script;
        }

        const match = script.match(/^( *)\S.*$/m);
        const prefixWhiteSpaceLength = match ? match[1].length : 0;

        if (prefixWhiteSpaceLength === 0) {
            return script;
        }

        const mdLines = script.trim().split('/\r?\n/g');
        const reg = new RegExp(`^\\s{${prefixWhiteSpaceLength}}`);
        return mdLines.map(line => line.replace(reg, '')).join('\n');
    }

    public async exportDsReport(params: {exportType: string,  messageUuid: string}) {
        const message = messageService.currentChat?.messages.find(msg => msg.uuid == params.messageUuid);
        if (!message || !message.initData || !message.initData[0] || message.type != "lui-message-ai-search-flash") {
            JigsawToast.showInfo(this._translateService.instant('common.thinking_please_wait'));
            return;
        }
        const content = message.initData[0].value;
        const question = messageService.currentChat.messages[messageService.currentChat?.messages.findIndex(msg => msg.uuid == params.messageUuid) - 1];
        const questionContent = question.initData[0].value;

        const exportType = params.exportType;
        if (exportType != "doc" && exportType != "pdf") {
            return;
        }

        const loading = this._loadingService.show();

        const exportParams = {
            type: exportType,
            content: content,
            question: questionContent
        };

        try {
            const headers = this.getHeaders();
            const result = await this._http.post<ResponseBase>(
                `/api/nae-deep-research/v1/deep-research/export-ds-report`, exportParams, {headers}).toPromise();
            if (result.code == 0) {
                this._download(result["data"]);
            } else {
                this._popupService.showErrorSystemPrompt(this._translateService.instant('common.failed'));
            }
            loading.dispose();
        } catch (error) {
            console.error(error);
            this._popupService.showErrorSystemPrompt(this._translateService.instant('common.failed'));
            loading.dispose();
        }
    }

    private async _download(url: string): Promise<void> {
        if (!url) {
            return;
        }
        try {
            // 使用fetch获取文件
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            // 获取文件blob
            const blob = await response.blob();

            // 创建blob URL
            const blobUrl = window.URL.createObjectURL(blob);

            const a = window.document.createElement('a');
            a.style.display = 'none';
            a.href = blobUrl;
            a.download = url.split('/').pop() || 'download';

            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            // 清理blob URL
            window.URL.revokeObjectURL(blobUrl);
        } catch (error) {
            console.error('Download Error:', error);
            JigsawToast.showError("Download Error");
        }
    }

    public async getApiKeys(userId?: string): Promise<any[]> {
        try {
            const headers = this.getHeaders();

            let url = '/api/nae-deep-research/v1/deep-research/api-keys';
            if (userId) {
                url += `?user_id=${encodeURIComponent(userId)}`;
            }

            const response = await this._http.get<ServerResponse<any[]>>(url, { headers }).toPromise();
            if (response.code === 0 && response.data) {
                return response.data;
            } else {
                throw new Error(response.msg || this._translateService.instant('common.getKeysFailed'));
            }
        } catch (error) {
            console.error('获取API Keys失败:', error);
            this._popupService.showErrorSystemPrompt(this._translateService.instant('common.getKeysFailed'));
            throw error;
        }
    }

    public async createApiKey(params: { key_name: string }) {
        try {
            const headers = this.getHeaders();
            const response = await this._http.post<ServerResponse<any>>(
                '/api/nae-deep-research/v1/deep-research/api-keys',
                { ...params, user_id: userInfo.id },
                { headers }
            ).toPromise();

            if (response.code === 0 && response.data) {
                return response.data;
            } else {
                throw new Error(response.msg || this._translateService.instant('common.createKeyFailed'));
            }
        } catch (error) {
            console.error('创建API Key失败:', error);
            this._popupService.showErrorSystemPrompt(this._translateService.instant('common.createKeyFailed'));
            throw error;
        }
    }

    public async updateApiKey(params: { key_name: string; key_value: string }) {
        try {
            const headers = this.getHeaders();
            const response = await this._http.post<ServerResponse<any>>(
                '/api/nae-deep-research/v1/deep-research/api-keys/update',
                {
                    ...params,
                    user_id: userInfo.id
                },
                { headers }
            ).toPromise();

            if (response.code === 0) {
                return response.data;
            } else {
                throw new Error(response.msg || this._translateService.instant('common.updateKeyFailed'));
            }
        } catch (error) {
            console.error('更新API Key失败:', error);
            this._popupService.showErrorSystemPrompt(this._translateService.instant('common.updateKeyFailed'));
            throw error;
        }
    }

    public async deleteApiKey(key_value: string) {
        try {
            const headers = this.getHeaders();
            const response = await this._http.delete<ServerResponse<string>>(
                '/api/nae-deep-research/v1/deep-research/api-keys',
                {
                    headers,
                    body: {
                        user_id: userInfo.id,
                        key_value
                    }
                }
            ).toPromise();

            if (response.code === 0) {
                return response.data;
            } else {
                throw new Error(response.msg || this._translateService.instant('common.deleteKeyFailed'));
            }
        } catch (error) {
            console.error('删除API Key失败:', error);
            this._popupService.showErrorSystemPrompt(this._translateService.instant('common.deleteKeyFailed'));
            throw error;
        }
    }
}
