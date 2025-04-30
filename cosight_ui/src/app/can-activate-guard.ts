import {Injectable} from "@angular/core";
import {ActivatedRouteSnapshot, CanActivate, Router, RouterStateSnapshot} from "@angular/router";
import {Observable, of} from "rxjs";
import {map} from "rxjs/operators";
import {SessionService} from "./service/session-service";
import { environment } from "environments/environment";

@Injectable({providedIn: 'root'})
export class UnLoggedInGuard implements CanActivate {
    constructor(private router: Router, private _router: Router, private _sessionService: SessionService) {
    }

    canActivate(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<boolean> {
        return environment.isAIS ? of(true) : this._sessionService.login().pipe(map((userName: string) => {
            if (userName === '') {
                const url = route.url.map(f => f.path).join('/');
                window.open(`/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=?ref=/${url}`, '_self');
                return false;
            }
            return true
        }));
    }
}

@Injectable({providedIn: 'root'})
export class LoginGuard implements CanActivate {
    constructor(private router: Router, private _router: Router, private _sessionService: SessionService) {
    }

    canActivate(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<boolean> {
        return environment.isAIS ? of(true) : this._sessionService.login().pipe(map((userName: string) => {
            if (userName !== '') {
                this._router.navigate(['']);
            }
            return true
        }));
    }
}
