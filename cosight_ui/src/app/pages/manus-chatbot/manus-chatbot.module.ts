import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ManusChatbot } from './manus-chatbot';
import { ChatWindowModule, LanguageService } from '@rdkmaster/lui-sdk';
import { JigsawModule, TranslateHelper } from '@rdkmaster/jigsaw';
import { TranslateService } from '@rdkmaster/ngx-translate-core';

@NgModule({
    declarations: [
        ManusChatbot
    ],
    imports: [
        CommonModule,
        ChatWindowModule,
        JigsawModule
    ],
    exports: [ManusChatbot],
})
export class ManusChatbotModule {
    constructor(translateService: TranslateService,
        languageService: LanguageService) {

        TranslateHelper.initI18n("root", {
            zh: {
                title: 'AI助手'
            },
            en: {
                title: 'Copilot AI'
            }
        });
        TranslateHelper.initI18n("manus-chatbot", {
            zh: {
                title: 'Co-Sight 超级智能体',
                desc: 'Co-Sight 超级智能体可以帮助您解答问题、分析数据并提供专家建议'
            },
            en: {
                title: 'Co-Sight 超级智能体',
                desc: 'Co-Sight 超级智能体可以帮助您解答问题、分析数据并提供专家建议'
            }
        });

        TranslateHelper.changeLanguage(translateService, 'zh')

        // 如果需要根据系统设置，可以保留这行；如果要强制中文，可以注释掉
        // const lang: string = languageService.getLang();
        // TranslateHelper.changeLanguage(translateService, lang);
    }
}
