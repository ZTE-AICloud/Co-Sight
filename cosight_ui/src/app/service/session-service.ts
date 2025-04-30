import {HttpClient, HttpHeaders} from "@angular/common/http";
import {Injectable} from '@angular/core';
import {CommonService, I18nLanguage, LanguageService, userInfo} from '@rdkmaster/lui-sdk';
import {Observable, of} from "rxjs";
import {catchError, map, switchMap} from "rxjs/operators";
import {ServerResponse} from "./custom-common-service";

export type LoginRespData = { id: string, authValue: string };

export type UacResponse = {
    code: {
        code: string,
        msgId: string,
        msg: string
    },
    bo: {
        mainInfo?: {
            name: string,
            accountName: string,
            accountId: string,
            headIcon: string,
            deptNo: string,
        },
        extendInfo?: any[],
        officeLocationInfo?: any
    },
    other?: any
}

@Injectable({
    providedIn: 'root'
})
export class SessionService extends CommonService {
    constructor(private _http: HttpClient, private _languageService: LanguageService) {
        super();
    }

    public login(): Observable<string> {
        /* Started by AICoder, pid:7de5eq5a94we7381473f084440ecf81a99071ed4 */
        return this._http.get(`/api/nae-deep-research/v1/deep-research/login`).pipe(
            switchMap((resp: ServerResponse<LoginRespData>) => {
                // 判断错误码是否是白名单校验失败
                if (resp.code == 1001) {
                    window.location.href = 'no-permission.html';
                    return of(resp.data?.id);
                }
                if (resp.code == 200 && resp.data) {
                    userInfo.id = resp.data.id;
                    return this._getUserName(resp.data).pipe(
                        map(name => {
                            userInfo.name = `${name}${userInfo.id}`;
                            return name;
                        })
                    );
                }
                return of("");
            }),
            catchError(() => of(""))
        );
        /* Ended by AICoder, pid:7de5eq5a94we7381473f084440ecf81a99071ed4 */
    }

    public logout(): Observable<boolean> {
        return this._http.post(`/api/nae-deep-research/v1/deep-research/logout`, {}).pipe(
            map((resp: ServerResponse<string>) => {
                return resp.code == 200;
            }),
            catchError(() => of(false))
        );
    }

    /* Started by AICoder, pid:g19bf76838tb7dd1492c0aee9092851e0ff837b5 */
    private _getUserName(info: LoginRespData): Observable<string> {
        const headers = new HttpHeaders()
            .set("content-type", "application/json;charset=utf-8")
            .set("x-auth-value", info.authValue)
            .set("x-emp-no", info.id)
            .set("x-lang-id", this._languageService.getLang() == I18nLanguage.EN ? "en_US" : "zh_CN");
        return this._http.get(`https://icenterapi.zte.com.cn/zte-km-icenter-user/user/v2/getUserInfo?accountId=${info.id}&terminalType=2`, {headers}).pipe(
            map((resp: UacResponse) => {
                if (parseInt(resp?.code?.code) == 0) {
                    return resp.bo.mainInfo.name;
                }
                return info.id;
            }),
            catchError(() => of(info.id))
        );
    }

    /* Ended by AICoder, pid:g19bf76838tb7dd1492c0aee9092851e0ff837b5 */
}
