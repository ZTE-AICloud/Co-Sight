import {HttpClient} from "@angular/common/http";
import {Injectable} from '@angular/core';
import {CollaborationService, LuiPopupService, RoleInfo} from '@rdkmaster/lui-sdk';
import {TranslateService} from "@rdkmaster/ngx-translate-core";

@Injectable({
    providedIn: 'root'
})
export class CustomCollaborationService extends CollaborationService {
    constructor(protected _http: HttpClient,
                _popupService: LuiPopupService,
                _translateService: TranslateService) {
        super(_http, _popupService, _translateService);
    }

    public async initAgent(): Promise<RoleInfo[] | string> {
        return [];
    }
}
