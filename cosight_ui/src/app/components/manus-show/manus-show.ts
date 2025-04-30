import {HttpClient} from '@angular/common/http';
import {ChangeDetectorRef, Component, Input, OnInit} from '@angular/core';
import {BaseToolRenderer, EventBus} from "@rdkmaster/lui-sdk";
import {StepFile} from '../../messages/manus-step/message-type';

/**
 * 自定义任务中心界面组件
 */
@Component({
    selector: 'lui-manus-show',
    templateUrl: './manus-show.html',
    styleUrls: ['./manus-show.scss']
})
export class ManusShow extends BaseToolRenderer implements OnInit {
    // 避免覆盖基类的getter/setter
    @Input() 
    set initData(value: any) {
        this._initData = value;
    }
    
    get initData(): any {
        return this._initData;
    }
    
    private _initData: any;
    
    // 存储文件列表
    public files: StepFile[] = [];
    
    // 当前选中的文件
    public selectedFile: StepFile;
    
    // 文件内容
    public fileContent: string = '';
    public filePath: string = '';
    
    // 加载状态
    public loading: boolean = false;
    
    // 错误信息
    public errorMessage: string = '';

    constructor(
        private _eventBus: EventBus,
        private http: HttpClient,
        private _cdr: ChangeDetectorRef
    ) {
        super();
    }

    ngOnInit(): void {
        this._eventBus.subscribe(['plan-updated'], (event: Record<string, StepFile[]>) => {
            console.log("plan-updated event >>>>>>>>>>>>>> ", event);
            // 将 event 对象的所有值数组合并成一个扁平的数组
            this.files = Object.values(event).flat() || [];
            this._cdr.detectChanges();
        })
    }

    public isHtmlFile(file: any): boolean {
        return file.name.toLowerCase().match(/\.(html|htm)$/i) !== null;
    }

    public isImageFile(file: any): boolean {
        return file.name.toLowerCase().match(/\.(jpg|jpeg|png|gif|bmp)$/i) !== null;
    }

    /**
     * 读取并显示文件内容
     * @param fileName 文件名
     */
    public loadFile(file: StepFile): void {
        this.selectedFile = file;
        this.errorMessage = '';
        this.fileContent = '';
        this.filePath = '';
        const baseUrl = '/api/nae-deep-research/v1'; // 根据实际情况修改
        const fileUrl = `${baseUrl}/work_space/${file.path}`;

        if (this.isHtmlFile(file) || this.isImageFile(file)) {
            this.filePath = fileUrl;
            return;
        }

        this.loading = true;
        this.http.get(fileUrl, { responseType: 'text' })
            .subscribe({
                next: (content) => {
                    this.fileContent = content;
                    this.loading = false;
                },
                error: (error) => {
                    console.error('读取文件失败:', error);
                    this.errorMessage = `读取文件失败: ${error.message || '未知错误'}`;
                    this.loading = false;
                }
            });
    }
}
