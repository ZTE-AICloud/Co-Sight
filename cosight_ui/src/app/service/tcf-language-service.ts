/* Started by AICoder, pid:q78c4m0b432504d1450e0ac370c9f51c4044a8ae */
import {Injectable} from '@angular/core';
import {I18nLanguage, LanguageService} from '@rdkmaster/lui-sdk';

@Injectable({
    providedIn: 'root'
})
export class TCFLanguageService extends LanguageService {
    /**
     * 应用可以按需自定义获取语言的方式
     */
    public getLang(): I18nLanguage {
        return top.window['getLanguage']?.()?.substring(0, 2) || this._getNavigatorLang();
    }
}
/* Ended by AICoder, pid:q78c4m0b432504d1450e0ac370c9f51c4044a8ae */
