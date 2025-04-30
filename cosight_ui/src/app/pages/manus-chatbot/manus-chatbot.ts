import { AfterViewInit, Component, OnDestroy, OnInit, Type, ViewChild } from '@angular/core';
import { JigsawTheme, MajorStyle } from '@rdkmaster/jigsaw';
import {
    BaseControlMessage,
    Chat,
    ChatBoxModule,
    ChatListToolModule,
    ChatToolConfig,
    ChatWindow,
    ChatWindowList,
    ChatWindowService,
    EditorWidget,
    EventBus,
    Message,
    messageService,
    MessageSource,
    MessageStatus,
    MessageType,
    MultiModalMessage,
    safeParseJson,
    TopMessageModule,
    WelcomeRenderer
} from '@rdkmaster/lui-sdk';
import { v4 } from '@rdkmaster/uuid';
import { Subscription } from 'rxjs';
import { addCopyIcon } from '../../misc/utils';
import { CustomCommonService } from "../../service/custom-common-service";
import { environment } from 'environments/environment';
import { HttpClient } from '@angular/common/http';
import { TranslateService } from "@rdkmaster/ngx-translate-core";
import { ManusShowModule } from 'app/components/manus-show';

@Component({
    selector: 'manus-chatbot',
    templateUrl: './manus-chatbot.html',
    styleUrls: ['./manus-chatbot.scss']
})
export class ManusChatbot implements OnDestroy, OnInit, AfterViewInit {
    private _welcomeMessageHandler: Subscription;
    private _eventHandler: Subscription;
    private _chatSelectedHandler: Subscription;

    @ViewChild('chatWindow')
    private _chatWindow: ChatWindow;

    public _$topMessage: Type<any> | TopMessageModule;
    public _$mixingTheme = 'light';
    public _$fullScreen: boolean;

    constructor(private _commonService: CustomCommonService,
        private _eventBus: EventBus,
        private _chatWindowService: ChatWindowService,
        private _http: HttpClient,
        private _translateService: TranslateService) {
        this._initTheme();
        document.title = 'Co-Sight';
        this._commonService.aiSearchEnabled = true;
        this._setTopMessage();
        this._eventHandler = this._eventBus.subscribe(['update-scroll-bar'], () => {
            this._chatWindow.messageScrollbar().update();
        })
    }

    private _setTopMessage(): void {
        this._$topMessage = {
            component: WelcomeRenderer, initData: {
                type: "welcome",
                uuid: v4(),
                from: MessageSource.AI,
                initData: {
                    title: this._translateService.instant('manus-chatbot.title'),
                    desc: this._translateService.instant('manus-chatbot.desc'),
                    abilities: [],
                    maxHeight: "468px"
                }
            }
        }
    }

    async ngOnInit() {
        this._chatSelectedHandler = messageService.chatSelected.subscribe((chat: Chat) => {
            if (!chat) {
                return;
            }
            setTimeout(() => chat.messages.forEach(message => addCopyIcon(message)));
        });
    }

    ngAfterViewInit(): void {
        this._$fullScreen = this._chatWindow.chatWindowMode.FullScreen == 'full-screen';
        this._dispatchControlMessage();
        this._commonService.aiSearchEnabledChange.emit(true);
    }

    ngOnDestroy(): void {
        this._welcomeMessageHandler?.unsubscribe();
        this._eventHandler?.unsubscribe();
        this._chatSelectedHandler?.unsubscribe();
    }

    private _dispatchControlMessage() {
    }

    public _$onMessageChange(message: Message) {
        if (message.from != MessageSource.AI) {
            return;
        }
        this._dispatchControlMessage();
    }

    private _initTheme() {
        this._changeTheme("light");
    }

    private _changeTheme(style: MajorStyle): void {
        JigsawTheme.changeTheme('copilot', style);
        this._$mixingTheme = style;
    }

    public _$chatToolsConfig: ChatToolConfig[] = [{
        type: 'chat-box',
        viewConfig: { renderer: { module: ChatBoxModule } },
        contentConfig: { renderer: { module: ManusShowModule } }
    }];

    public _$messageConverter(message: MultiModalMessage): Message {
        if (message.type == MessageType.RICH_TEXT) {
            message.type = MessageType.MULTI_MODAL;
            message.initData = [{ type: 'text', value: <any>message.initData }];
        }
        message.disableAutoMention = true;
        message.extra ??= {};
        message.extra.fromBackEnd ??= {};
        message.extra.fromBackEnd.actualPrompt = {
            ...((() => {
                try {
                    return JSON.parse(message.extra.fromBackEnd.actualPrompt as string);
                } catch {
                    return {};
                }
            })()),
            deepResearchEnabled: true
        };
        message.extra.fromBackEnd.actualPrompt = JSON.stringify(message.extra.fromBackEnd.actualPrompt);
        return message;
    }

    public _$messageInteract(params: any): void {
    }

    public _$addChat() {
        this._setTopMessage();
    }

    public _$onMessageStopped(event: any) {
        if (!event?.message?.uuid || event?.message?.type == "processing") {
            return;
        }
        messageService.dispatchControlMessage({
            type: 'control-status-message',
            initData: {
                status: 'stopped'
            }
        } as BaseControlMessage);
    }
}
