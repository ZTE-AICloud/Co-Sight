import {Component, OnInit} from '@angular/core';
import { userInfo } from '@rdkmaster/lui-sdk';
import { environment } from 'environments/environment';

@Component({
    selector: 'copilot-app',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit {

    constructor() {
    }

    ngOnInit() {
        if (!environment.isAIS) {
            return;
        }

        const usrname = typeof window['getUserName'] === 'function' ? window['getUserName']() : '';
        if (usrname) {
            userInfo.name = usrname;
            userInfo.id = usrname;
        }
    }
}
