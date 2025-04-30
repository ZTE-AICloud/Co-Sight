import {HttpClient} from "@angular/common/http";
import {Injectable} from '@angular/core';
import {JigsawSystemPrompt} from "@rdkmaster/jigsaw";
import {JigsawToast} from "@rdkmaster/jigsaw";
import {injection, LuiPopupService} from '@rdkmaster/lui-sdk';

@Injectable({
    providedIn: 'root'
})
export class CustomPopupService extends LuiPopupService {
    public showSuccessSystemPrompt(message: string, timeout?:number): JigsawSystemPrompt {
        JigsawToast.showSuccess(message, {timeout: timeout});
        return null;
    }
}
