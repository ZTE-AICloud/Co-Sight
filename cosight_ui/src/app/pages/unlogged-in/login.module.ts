import {NgModule} from "@angular/core";
import {CommonModule} from "@angular/common";
import {TranslateModule} from "@rdkmaster/ngx-translate-core";
import {TranslateHelper} from "@rdkmaster/jigsaw";
import {UnLoggedIn} from "./login";

@NgModule({
    declarations: [UnLoggedIn],
    exports: [UnLoggedIn],
    imports: [CommonModule, TranslateModule.forChild()]
})
export class UnLoggedInModule {
    constructor() {
        TranslateHelper.initI18n("login", {
            zh: {
                info: "您尚未登录，请点击这里",
                login: "登录"
            },
            en: {
                info: "You have not logged in yet. Please click here to",
                login: " log in "
            }
        });
    }
}
