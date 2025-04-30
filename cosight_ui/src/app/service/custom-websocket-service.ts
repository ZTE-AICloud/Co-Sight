import {Injectable} from "@angular/core";
import { JigsawInfoAlert } from "@rdkmaster/jigsaw";
import {ChatManagerService, LanguageService, WebSocketService, CommonService, storageService, injection} from "@rdkmaster/lui-sdk";
import {HttpClient} from "@angular/common/http";
import {TranslateService} from "@rdkmaster/ngx-translate-core";

@Injectable({
    providedIn: 'root'
})
export class CustomWebsocketService extends WebSocketService {
    private _lastTimestamp = 0;
    constructor(
        private _langService: LanguageService,
        private _chatService: ChatManagerService,
        private _http: HttpClient,
        private _translateService: TranslateService
    ) {
        super(_langService, _chatService);
    }

    protected _createWebsocket(): void {
        const clientId = storageService.getStoredData('lui-client-id');
        const baseApiUrl = this._chatService.baseApiUrl;
        const serverUrl = `${this._webSocketProtocol}://${this._webSocketUrl}${this._webSocketPort}`;
        let url: string = `${serverUrl}${baseApiUrl}`;
        url += `/robot/wss/messages?websocket-client-key=${clientId}&lang=${this._langService.getLang()}&service=deep-research`;
        const referer = encodeURIComponent(location.href);
        url += `&referer=${referer}`;
        console.log(`try to connect ${url}: `, this._tryCount);
        const token = typeof injection.environment?.csrfToken == "function" ? injection.environment.csrfToken() : undefined;
        this._webSocket = new WebSocket(url, token);
    }

    public sendMessage(topic: string, type: 'subscribe' | 'unsubscribe' | 'message', message?: string): void {
        super.sendMessage(topic, type, message);

        if (type !== 'message') {
            return;
        }
    }

    protected async _onopen() {
        super._onopen();

        // 最大重试次数，可以根据需求调整
        const maxRetries = 300;
        for (let i = 0; i < maxRetries; i++) {
            if (await this._checkServerTimestamp()) {
                return;
            }
            await new Promise(resolve => setTimeout(resolve, 10000));
        }
        JigsawInfoAlert.show(
            this._translateService.instant('common.unknown_status'),
            () => {
                window.location.reload();
            },
            [{label: this._translateService.instant('common.confirm')}]
        );
    }

    private async _checkServerTimestamp() {
        let response: any;
        try {
            response = await this._http.get(
                `/api/nae-deep-research/v1/deep-research/server-timestamp`
            ).toPromise();
        } catch (error) {
            return false;
        }
        if (response.code !== 0) {
            return false;
        }

        const serverTimestamp = response.data.timestamp;
        if (!this._lastTimestamp) {
            this._lastTimestamp = serverTimestamp;
            return true;
        }
        if (serverTimestamp <= this._lastTimestamp) {
            return true;
        }
        await JigsawInfoAlert.show(this._translateService.instant('common.restarted')).toPromise();
        window.location.reload();
        return true;
    }
}
