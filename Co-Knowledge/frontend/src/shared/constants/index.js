import { $t } from '@/app/i18n/i18n.js'

export const SUPERADMIN = 'super_admin'
export const PLATFORMADMIN = 'platform_admin'
export const APPCREATOR = 'app_creator'
export const KBASECREATOR = 'kbase_creator'
export const APPADMIN = 'app_admin'
export const KBASEADMIN = 'kbase_admin'
export const APPDEVELOPER = 'app_developer'
export const KBASEMEMBER = 'kbase_member'

export const kbPermissionMeta = ['isSuperAdmin', 'isPlatformAdmin', 'isKbaseCreator', 'isKbaseAdmin', 'isKbaseMember'];

export const percentage = 'percentage'
export const percentageCh = $t('modules.commonUi.constants.percentageCh')

export const FOLDER = 'folder';

export const CODE = 'code'
export const CREATE = 'create';
export const EDIT = 'edit';
export const CODECREATE = 'codeCreate';

export const INTERVALTIME = 3000;
// 文件名冲突：后端返回 409 + problem `code`。
export const FILE_NAME_CONFLICT_CODE = 'file_name_conflict';

export const DEBOUNCETIME = 500;
export const DEBOUNCETIMELONG = 800;

export const LIMIT1 = 1;

export const REGEXSPLITTER = 'regexSplitter'; // comprehensiveSplitter/QASplitter
export const COMPREHENSIVESPLITTER = 'comprehensiveSplitter';
export const QASPLITTER = 'QASplitter';
export const MARKDOWNHEADERSPLITTER = 'markdownHeaderSplitter';
export const OTHERSPLITTER = 'otherSplitter';

export const INPUT = 'input';
export const TEXTAREA = 'textarea';
export const SELECT = 'select';

export const ZH = 'zh';

// 不要在前端持有向量模型名的副本：它是可配的部署属性，唯一定义点在 deploy/.env 的
// EMBEDDING_MODEL*，下拉选项来自 GET /embedding/all。

export const APPNAME = $t('modules.commonUi.constants.appName'); // 调用prompt外部接口使用

export const INITPAGE = 'initPage';

export const WIKI = 'wiki';


export const ZHMAP = { DOC: $t('modules.commonUi.constants.doc') }

// 定义KBFILESTATUS常量
export const KBFILESTATUS = {
  STATUS0: 0,
  STATUS1: 1,
  STATUS2: 2,
  STATUS3: 3,
  STATUS4: 4,
  STATUS5: 5,
  STATUS7: 7
};

// 定义ENABLE常量
export const ENABLE = 1;

export const KILOBTTE = 1024;

export const SORTORDERS = ['ascending', 'descending', null];

export const DOCUMENT = 'document';
export const QA = 'QA';
export const TEMPLATE = 'template';
export const EXIST = 'exist';
export const FRESH = 'fresh';

export const SYSTEM = 'system';
export const CUSTOM = 'custom';

// 画布检索器里存的文档知识库检索名（后端检索侧的基名，见
// backend/src/knowledge_base/kbase_options.py 的 RETRIEVAL_NAME_PREFIX）。
// 用于区分「已是 tableName」与「用户填的是知识库显示名」两种回显值。
export const KB_NAME_PREFIX = 'doc_';
