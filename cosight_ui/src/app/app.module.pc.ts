import {BrowserModule} from '@angular/platform-browser';
import {NgModule} from '@angular/core';
import {HTTP_INTERCEPTORS, HttpClientModule} from '@angular/common/http';
import {BrowserAnimationsModule} from '@angular/platform-browser/animations';
import {TranslateModule, TranslateService} from '@rdkmaster/ngx-translate-core';
import {JigsawModule, JigsawThemeService, TranslateHelper} from '@rdkmaster/jigsaw';
import {
    ChatWindowService,
    CollaborationService,
    CommonService,
    EventBus,
    LanguageService,
    LuiPopupService,
    WebSocketService
} from '@rdkmaster/lui-sdk';
import {AppComponent} from './app.component.pc';
import {CustomCommonService} from "./service/custom-common-service";
import {environment} from "../environments/environment";
import {SessionService} from "./service/session-service";
import {UIDRouterModule} from "./router-config";
import {CustomWebsocketService} from "./service/custom-websocket-service";
import {CustomCollaborationService} from "./service/custom-collaboration-service";
import {CustomPopupService} from './service/custom-popup-service';
import {TCFLanguageService} from "./service/tcf-language-service";
import {ManusChatbotModule} from './pages/manus-chatbot/manus-chatbot.module';

@NgModule({
    declarations: [AppComponent],
    imports: [
        BrowserModule, BrowserAnimationsModule, HttpClientModule, UIDRouterModule, JigsawModule, TranslateModule.forRoot(),
        ManusChatbotModule
    ],
    providers: [
        TranslateService, JigsawThemeService, LuiPopupService, EventBus, SessionService,
        {
            provide: CommonService,
            // 自定义服务实现
            useClass: CustomCommonService
        },
        {
            provide: WebSocketService,
            // 自定义ws服务实现
            useClass: CustomWebsocketService
        },
        {
            provide: CollaborationService,
            useClass: CustomCollaborationService
        },
        {
            provide: LuiPopupService,
            useClass: CustomPopupService
        },
        {
            provide: 'environment', useValue: environment
        },
        {
            provide: LanguageService, useClass: TCFLanguageService
        }
    ],
    bootstrap: [AppComponent]
})
export class AppModule {
    constructor(translateService: TranslateService,
                languageService: TCFLanguageService,
                private _chatWindowService: ChatWindowService) {
        this._chatWindowService.load();
        TranslateHelper.changeLanguage(translateService, languageService.getLang());
        this._chatWindowService.headerHeight = "0px";
    }
}

export * from "./messages/manus-step/index"
