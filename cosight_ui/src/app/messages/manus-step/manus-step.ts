import { Component, Input, Renderer2, OnInit } from '@angular/core';
import { TranslateService } from "@rdkmaster/ngx-translate-core";
import { LuiMessageManusStepType, ManusStepItem } from './message-type';
import {
    BaseRenderer,
    EventBus,
    Message,
    messageService,
    safeParseJson,
    MessageType
} from '@rdkmaster/lui-sdk';


@Component({
    templateUrl: './manus-step.html',
    styleUrls: ['./manus-step.scss']
})
export class ManusStepRenderer extends BaseRenderer implements OnInit {
    @Input()
    public message: LuiMessageManusStepType;

    public steps: ManusStepItem[] = [];

    constructor(protected _translateService: TranslateService, protected _renderer2: Renderer2, _eventBus: EventBus) {
        super(_renderer2, _eventBus);
    }

    ngOnInit() {
        super.ngOnInit();
        this.parseSteps();
        this._subscribeMessageUpdate();
    }

    protected _subscribeMessageUpdate(): void {
        this._messageUpdatedHandler = messageService.messageUpdated.subscribe((message: LuiMessageManusStepType) => {
            if (message.uuid != this.message.uuid) {
                return;
            }
            this.message = message;
            this.parseSteps();
        });
    }

    private parseSteps() {
        this._eventBus.emit('plan-updated', this.message.initData.step_files);
        if (this.message.initData?.steps && Array.isArray(this.message.initData.steps)) {
            // 将 Plan 对象的数据转换成组件需要的 ManusStepItem[] 格式
            this.steps = this.message.initData.steps.map((stepContent, index) => {
                const status = this.message.initData.step_statuses?.[stepContent] || 'not_started';
                const notes = this.message.initData.step_notes?.[stepContent] || '';
                const dependencies = this.message.initData.dependencies?.[index] || [];

                return {
                    name: stepContent,
                    index: index,
                    status: this.convertStatus(status),
                    notes: notes,
                    dependencies: dependencies,
                    isActive: this.message.initData.isStepActive?.[index] || false
                };
            });
        }
    }

    // 将 Plan 对象的状态转换成组件需要的状态
    private convertStatus(status: string): 'success' | 'failed' | 'processing' | 'waiting' {
        switch (status) {
            case 'completed': return 'success';
            case 'in_progress': return 'processing';
            case 'blocked': return 'failed';
            case 'not_started':
            default: return 'waiting';
        }
    }

    public _$clippedContent(): string {
        return this.message.initData?.result || "";
    }

    public _$statusText(step: ManusStepItem): string {
        const statusTextMap = {
            'success': "已完成",
            'failed': "已阻塞",
            'processing': "进行中",
            'waiting': "等待中"
        };
        return statusTextMap[step.status] || "等待中";
    }

    public getProgressPercentage(): number {
        if (this.message.initData?.progress) {
            const { total, completed, blocked } = this.message.initData.progress;
            return total > 0 ? ((completed + blocked) / total * 100) : 0;
        }
        return 0;
    }

    public toggleStep(index: number) {
        if (!this.message.initData.isStepActive) {
            this.message.initData.isStepActive = {};
        }
        this.message.initData.isStepActive[index] = !this.message.initData.isStepActive[index];
        this.steps[index].isActive = !this.steps[index].isActive;
    }

    public getDependenciesText(step: ManusStepItem): string {
        if (!step.dependencies || step.dependencies.length === 0) {
            return '';
        }
        return `(依赖于: ${step.dependencies.join(', ')})`;
    }

    public getProgressStatus(): 'processing' | 'block' | 'error' | 'success' {
        if (this.message.initData?.progress) {
            const { total, completed, blocked } = this.message.initData.progress;

            // 如果有被阻塞的步骤，显示为错误状态
            if (blocked && blocked > 0) {
                return 'processing';
            }

            // 如果已完成所有步骤，显示为成功状态
            if (total > 0 && (completed === total || completed + blocked === total) {
                return 'success';
            }

            // 如果有正在进行中的步骤，显示为处理中状态
            if (completed < total) {
                return 'processing';
            }
        }

        // 默认状态为处理中
        return 'processing';
    }
}
