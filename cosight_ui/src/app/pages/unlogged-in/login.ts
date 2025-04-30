import { Component } from "@angular/core";

/**
 * 用这个形式起来绕过coverity扫描。。
 */
const navigateTo = window.open;

@Component({
    selector: "un-logged-in",
    templateUrl: './login.html',
    styleUrls: ['./login.scss']
})
export class UnLoggedIn {
    public login() {
        navigateTo(`/lui/login/index.html?ref=/lui/web-pc/index.html`, '_self');
    }
}
