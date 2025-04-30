import {NgModule} from '@angular/core';
import {CommonModule} from '@angular/common';
import {TranslateModule} from "@rdkmaster/ngx-translate-core";
import {PerfectScrollbarModule} from "@rdkmaster/ngx-perfect-scrollbar";
import {JigsawModule} from '@rdkmaster/jigsaw';
import {ManusShow} from "./manus-show";
import {MessageRendererModule} from '@rdkmaster/lui-sdk';
import {SafePipe} from './safe-pip';

@NgModule({
    imports: [
        CommonModule,
        JigsawModule,
        PerfectScrollbarModule,
        TranslateModule.forChild(),
        MessageRendererModule
    ],
    declarations: [ManusShow, SafePipe],
    exports: [ManusShow],
    bootstrap: [ManusShow]
})
export class ManusShowModule {
    constructor() {
    }
}
