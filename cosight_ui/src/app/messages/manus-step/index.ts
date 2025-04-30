import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { PerfectScrollbarModule } from '@rdkmaster/ngx-perfect-scrollbar';
import { JigsawModule } from '@rdkmaster/jigsaw';
import { MessageRendererModule, messagesMap, MessageType, ToolsBarModule } from '@rdkmaster/lui-sdk';
import { LuiMessageManusStepType } from './message-type';
import { TranslateModule } from "@rdkmaster/ngx-translate-core";
import { ManusStepRenderer } from './manus-step';

@NgModule({
    declarations: [ManusStepRenderer],
    exports: [ManusStepRenderer],
    bootstrap: [ManusStepRenderer],
    imports: [
        CommonModule, FormsModule, JigsawModule, PerfectScrollbarModule, ToolsBarModule, MessageRendererModule, TranslateModule.forChild()
    ],
})
export class LuiMessageManusStepModule {
    constructor() {
        // 移除所有国际化配置和语言设置
    }
}

export * from './message-type';
export * from './manus-step';

// 支持自定义类型消息：将消息定义加入全局对象中
messagesMap.set('lui-message-manus-step', {
    message: LuiMessageManusStepType,
    renderer: { module: LuiMessageManusStepModule }
});

