<template>
  <el-dialog v-model="createAppDialogVisible" :title="isEditMode?$t('public.modify'):$t('ragFlow.createWorkflow')" width="650px" :before-close="handleClose" :close-on-click-modal="false">
    <el-form ref="appFormRef" :model="appForm" :rules="appFormRules" label-width="150px">
      <el-form-item :label="$t('ragFlow.name')" prop="name">
        <el-input
          v-model="appForm.name"
          class="app-name-input"
          :placeholder="$t('ragFlow.namePlc')"
          maxlength="50"
          show-word-limit
        />
      </el-form-item>
      <el-form-item :label="$t('ragFlow.knowledgeType')" prop="knowledgeType">
        <el-radio-group v-model="appForm.knowledgeType" :disabled="isEditMode">
          <el-radio :value="KNOWLEDGE_TYPE.KNOWLEDGE_BASE">{{ $t('ragFlow.knowledgeTypeKb') }}</el-radio>
          <!-- 结构化知识库子系统未提供：下拉里永远不会有 struct_knowledge 类型的库。
               没有可选库时把这个入口隐藏，否则是一路走到「必填但无可选项」的死路。
               编辑一条历史 database 工作流时仍显示，避免选中值对不上。 -->
          <el-radio
            v-if="hasStructuredKbs || appForm.knowledgeType === KNOWLEDGE_TYPE.DATABASE"
            :value="KNOWLEDGE_TYPE.DATABASE"
          >
            {{ $t('ragFlow.knowledgeTypeDb') }}
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="false" :label="$t('ragFlow.workflowId')" prop="workFlowId">
        <el-input
          v-model.trim="appForm.workFlowId"
          class="app-name-input"
          :placeholder="$t('ragFlow.workflowIdPlaceholder')"
          :disabled="isEditMode"
          maxlength="100"
          show-word-limit
        />
      </el-form-item>
      <el-form-item :label="$t('ragFlow.template')" prop="template">
        <template #label>
          <span>{{ $t('ragFlow.template') }}</span>
          <el-tooltip class="item" effect="light" placement="top">
            <template #content>
              <div>
                <div v-for="item in $t('ragFlow.workflowTemplateTip').split('\n')" :key="item" :style="{ fontWeight: isTitle(item) ? 'bold' : 'normal' }">
                  {{ item }}
                </div>
              </div>
            </template>
            <i class="cursor-pointer plx-ico-help-tip-20 help-icon" />
          </el-tooltip>
        </template>
        <el-radio-group v-model="appForm.template" :disabled="isEditMode || availableTemplates.length === 1">
          <el-radio v-for="item in availableTemplates" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="createAppDialogVisible && !isEditMode" :label="$t('modules.kb.kb')" prop="selectedKbs">
        <template #label>
          <span>{{ $t('modules.kb.kb') }}</span>
          <el-tooltip class="item" effect="light" placement="top">
            <template #content>
              <div>{{ $t('modules.kb.kbSelectMutexTip') }}</div>
            </template>
            <i class="cursor-pointer plx-ico-help-tip-20 help-icon" />
          </el-tooltip>
        </template>
        <el-select
          v-model="appForm.selectedKbs"
          class="form-item-content--100per custom-kb-select"
          multiple collapse-tags
          filterable
          value-key="key"
          :placeholder="$t('knowledge.selectKnowledge')"
          :filter-method="handleKbFilter"
          @change="handleSelectChange"
        >
          <template v-for="group in displayedKBList" :key="group.key">
            <!-- 分组标题选项（可以显示选中状态，但不会被实际选中） -->
            <el-option
              :value="`group-${group.key}`"
              class="group-title-option"
              :style="{ overflow: 'visible', textOverflow: 'clip', whiteSpace: 'normal' }"
              @click.stop="handleGroupTitleClick(group.key)"
            >
              <span class="group-header-simple" :style="{ position: 'relative', overflow: 'visible', textOverflow: 'clip', whiteSpace: 'nowrap', width: '100%' }">
                <span class="group-text" :style="{ overflow: 'visible', textOverflow: 'clip', whiteSpace: 'nowrap', maxWidth: 'none', width: 'auto', display: 'inline-block' }">{{ group.label }}</span>
                <el-icon class="arrow-icon" :style="{ position: 'absolute', right: '-351px', top: '50%', transform: 'translateY(-50%)' }">
                  <ArrowDown v-if="dynamicGroupCollapseState[group.key]" />
                  <ArrowUp v-else />
                </el-icon>
              </span>
            </el-option>
            <!-- 分组选项 -->
            <template v-if="!dynamicGroupCollapseState[group.key]">
              <el-option
                v-for="item in group.options"
                :key="item.key"
                :value="item"
                :label="item.name"
                class="group-item-option"
                @click="handleKbSelection(item)"
              >
                <span style="margin-left: 8px;">{{ item.name }}</span>
              </el-option>
            </template>
          </template>
        </el-select>
      </el-form-item>
      <el-form-item :label="$t('ragFlow.desc')" prop="description">
        <el-input
          v-model="appForm.description"
          :placeholder="$t('ragFlow.descPlc')"
          type="textarea"
          :rows="4"
          maxlength="1000"
          show-word-limit
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <span>
        <el-button type="primary" :disabled="submitLoading" :loading="submitLoading" @click="createNewFlow">{{ isEditMode?$t("public.confirm"):$t("ragFlow.create") }}</el-button>
        <el-button plain @mousedown="handleClose">{{ $t("messageBox.cancel") }}</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, getCurrentInstance, onMounted, computed, watch, nextTick } from 'vue';
import { ElMessageBox } from 'element-plus';
import { createFlow, getFlowList, updateFlow, getAllKBList } from '@/features/workflow/api/workflow';
import { v4 as uuidv4 } from 'uuid';
import { KB_PUBLISH_STATUS } from '@/features/knowledge-base/constants.js';
import { ArrowUp, ArrowDown } from '@/shared/lib/icons';

const KNOWLEDGE_TYPE = {
  KNOWLEDGE_BASE: 'knowledgeBase',
  DATABASE: 'database'
} as const;
type KnowledgeType = (typeof KNOWLEDGE_TYPE)[keyof typeof KNOWLEDGE_TYPE];

interface KB_OPTION_TYPE {
  key: string;
  name: string;
  status: string;
  assetId: string;
  tableName: string;
  isGraphKb?: boolean;
}

const emits = defineEmits(['refresh'])
const appFormRef = ref<any>(null)
const { proxy } = getCurrentInstance() as any
const isEditMode = ref(false)
const appForm = ref({
  name: '',
  workFlowId: '',
  template: 'Blended',
  knowledgeType: KNOWLEDGE_TYPE.KNOWLEDGE_BASE as KnowledgeType,
  description: '',
  kbPkIds: [] as KB_OPTION_TYPE[],
  graphKbPkIds: [] as KB_OPTION_TYPE[],
  selectedKbs: [] as KB_OPTION_TYPE[]
})
// 名称校验函数：允许空格，但不能全为空格
const validateName = (rule: any, value: any, callback: any) => {
  if (!value) {
    callback();
    return;
  }
  // 检查是否全为空格
  if (/^\s+$/.test(value)) {
    callback(new Error(proxy.$t('ragFlow.nameWhitespaceOnly')));
    return;
  }
  // 检查字符格式：允许英文、数字、下划线、中文、英文点、英文中划线和空格
  if (!/^[\w\u4e00-\u9fa5.\-\s]+$/.test(value)) {
    callback(new Error(proxy.$t('ragFlow.nameInvalidFormat')));
    return;
  }
  // 检查长度（知识检索名称长度限制可能需要根据实际需求调整，这里先设为2-50）
  if (value.length < 2 || value.length > 50) {
    callback(new Error(proxy.$t('ragFlow.nameLengthInvalid')));
    return;
  }
  callback();
};

const appFormRules = ref({
  name: [{
    required: true, message: proxy.$t('ragFlow.nameRequired'), trigger: ['blur', 'change']
  }, {
    validator: validateName, trigger: ['blur', 'change']
  }],
  knowledgeType: [{
    required: true,
    message: proxy.$t('ragFlow.knowledgeType'),
    trigger: 'change'
  }],
  workFlowId: [
    {
      required: true,
      message: proxy.$t('ragFlow.workflowIdPlaceholder'),
      trigger: 'blur'
    },
    {

      pattern: /^[a-zA-Z0-9_]*$/,
      message: proxy.$t('ragFlow.workflowIdTip'),
      trigger: 'blur'
    }
  ],
  selectedKbs: [{
    validator: (rule: any, value: any, callback: any) => {
      if (!value || value.length === 0) {
        callback(new Error(proxy.$t('ragFlow.selectAtLeastOneKb')));
        return;
      }
      // 由于界面已经根据模板类型限制了可选择的知识库类型，这里只需要验证是否选择了知识库
      callback();
    },
    trigger: 'change'
  }],
  template: [{
    required: true, trigger: 'change'
  }]
})
const createAppDialogVisible = ref(false)
const initializing = ref(false);
onMounted(() => {
})

const submitLoading = ref(false);
function openDialog (workflowObj?: any) {
  initializing.value = true;
  getKBList();
  submitLoading.value = false;
  // 重置分组状态，让动态逻辑重新生效
  groupCollapseState.value = {};
  kbFilterKeyword.value = '';
  appForm.value = {
    name: '',
    workFlowId: '',
    template: 'Blended',
    knowledgeType: KNOWLEDGE_TYPE.KNOWLEDGE_BASE,
    description: '',
    kbPkIds: [] as KB_OPTION_TYPE[],
    graphKbPkIds: [] as KB_OPTION_TYPE[],
    selectedKbs: [] as KB_OPTION_TYPE[]
  }
  if (workflowObj) {
    isEditMode.value = true
    appForm.value = JSON.parse(JSON.stringify(workflowObj))
    // 初始化selectedKbs字段（编辑模式下从现有的kbPkIds和graphKbPkIds合并）
    appForm.value.selectedKbs = [
      ...(appForm.value.kbPkIds || []).map(kb => ({ ...kb, isGraphKb: false })),
      ...(appForm.value.graphKbPkIds || []).map(kb => ({ ...kb, isGraphKb: true }))
    ];
    appForm.value.knowledgeType = inferKnowledgeType(appForm.value.selectedKbs);
    if (appForm.value.knowledgeType === KNOWLEDGE_TYPE.DATABASE) {
      appForm.value.template = 'Sequential';
    }
  } else {
    isEditMode.value = false
    let randomID = generateRandomUUID()
    appForm.value.workFlowId = `RAG_Workflow_${randomID}`
  }

  createAppDialogVisible.value = true
  nextTick(() => {
    initializing.value = false;
  });
}
function ensureNameUnique (): Promise<boolean> {
  return getFlowList(1, 200, appForm.value.name).then((res: any) => {
    const rows = res?.items || []
    return !rows.some((row: any) =>
      row.name === appForm.value.name && row.workFlowId !== appForm.value.workFlowId
    )
  })
}

const createNewFlow = () => {
  proxy.$refs.appFormRef.validate((valid: boolean) => {
    if (valid) {
      submitLoading.value = true;
      // 后端只保证 workFlowId 唯一；名称重复会在列表里出现两条无法区分的记录
      // （E2E FLOW-19）。提交前按名称查一次，重复就停在弹窗里给出提示。
      ensureNameUnique().then((unique) => {
        if (!unique) {
          submitLoading.value = false;
          proxy.$message.error(proxy.$t('ragFlow.nameDuplicate'));
          return;
        }
        submitFlow();
      }).catch(() => {
        submitLoading.value = false;
      });
    } else {
      return false
    }
  })
}

function submitFlow () {
  const params = {
    name: appForm.value.name,
    workFlowId: appForm.value.workFlowId,
    template: appForm.value.template,
    knowledgeType: appForm.value.knowledgeType,
    description: appForm.value.description
  }
  if (isEditMode.value) {
    updateFlow(params).then(() => {
      emits('refresh')
      handleClose()
      proxy.$message.success(proxy.$t('public.modifySuccess'));
    })
      .finally(() => {
        submitLoading.value = false;
      })
  } else {
    const result = getSelectdKbList();
    createFlow({ ...params, boundInfo: result }).then(() => {
      emits('refresh')
      handleClose()
      proxy.$message.success(proxy.$t('messageBox.createSuccess'));
      // 点击了创建按钮以后 自动跳转到工作流配置页面
      goFlowDetail(appForm.value.workFlowId)
    })
      .finally(() => {
        submitLoading.value = false;
      })
  }
}

function getSelectdKbList() {
  let result: any = {};

  // 处理普通知识库
  for (let i = 0; i < appForm.value.kbPkIds.length; i++) {
    const item = appForm.value.kbPkIds[i];
    const status = item.status;

    // 如果当前 status 的分组不存在，初始化为空数组
    if (!result[status]) {
      result[status] = [];
    }

    // 去掉 key 和 status 属性后，将当前项推入对应的分组
    // eslint-disable-next-line no-unused-vars -- 解构只为把 key/status 从 rest 中剔除
    const { key, status: statusProp, ...rest } = item;
    result[status].push(rest);
  }

  // 处理图谱知识库
  for (let i = 0; i < appForm.value.graphKbPkIds.length; i++) {
    const item = appForm.value.graphKbPkIds[i];
    const status = item.status;

    // 如果当前 status 的分组不存在，初始化为空数组
    if (!result[status]) {
      result[status] = [];
    }

    // 去掉 key 和 status 属性后，将当前项推入对应的分组
    // eslint-disable-next-line no-unused-vars -- 解构只为把 key/status 从 rest 中剔除
    const { key, status: statusProp, ...rest } = item;
    result[status].push(rest);
  }

  return result;
}
function goFlowDetail (workflowId: string) {
  proxy.$router.push({
    name: 'flow-detail',
    params: { id: workflowId }
  })
}

const isTitle = (text: string): boolean => {
  if(!text || !text.trim()) {
    return false;
  }
  return /^\d+、/.test(text.trim());
}

const availableTemplates = computed(() => {
  if (appForm.value.knowledgeType === KNOWLEDGE_TYPE.DATABASE) {
    return [{
      value: 'Sequential',
      label: proxy.$t('ragFlow.sequenceWorkflow')
    }];
  }
  return [{
    value: 'Blended',
    label: proxy.$t('ragFlow.mixWorkflow')
  }, {
    value: 'Sequential',
    label: proxy.$t('ragFlow.sequenceWorkflow')
  }, {
    value: 'Conditional',
    label: proxy.$t('ragFlow.conditionWorkflow')
  }];
});

const handleClose = () => {
  setTimeout(() => {
    submitLoading.value = false;
    createAppDialogVisible.value = false
    // 新建成功时调用方紧接着 push 路由到画布，组件随之卸载、模板 ref 被置 null；
    // 这个 setTimeout 是宏任务、排在路由切换的微任务之后执行，不加 ?. 会读到 null
    proxy.$refs.appFormRef?.resetFields();
  }, 0)
}

function generateRandomUUID () {
  let uuid = uuidv4()
  uuid = uuid.replace(/-/g, '')
  uuid = uuid.substring(0, 4)
  return uuid
}

const allKBList = ref<any[]>([]);
const allGraphKBList = ref<any[]>([]);
const structuredKBList = ref<any[]>([]);
// 结构化知识库（「数据库」类型）没有创建入口，列表恒空；见模板里的说明。
const hasStructuredKbs = computed(() => structuredKBList.value.length > 0);

// 分组收起/展开状态管理
const groupCollapseState = ref<Record<string, boolean>>({});

// 动态分组收起状态 - 默认展开所有分组，支持模糊匹配
const dynamicGroupCollapseState = computed(() => {
  const state: Record<string, boolean> = {};
  displayedKBList.value.forEach(group => {
    // 如果用户手动操作过，使用用户的选择；否则默认展开（false表示展开）
    if (Object.prototype.hasOwnProperty.call(groupCollapseState.value, group.key)) {
      state[group.key] = groupCollapseState.value[group.key];
    } else {
      state[group.key] = false; // 默认展开所有分组，确保模糊匹配可以匹配到所有选项
    }
  });

  return state;
});

// 合并的知识库列表，用于统一的下拉选择器
const mergedKBList = computed(() => {
  const result = [];
  const isDatabase = appForm.value.knowledgeType === KNOWLEDGE_TYPE.DATABASE;
  const groupKey = isDatabase ? 'structKb' : 'dockb';
  const groupLabel = isDatabase ? proxy.$t('ragFlow.databaseKnowledge') : proxy.$t('modules.kb.dockb');

  if (isDatabase) {
    if (structuredKBList.value.length > 0 && structuredKBList.value[0].options.length > 0) {
      result.push({
        key: groupKey,
        label: groupLabel,
        options: structuredKBList.value[0].options.map((option: any) => ({
          ...option,
          isGraphKb: false
        }))
      });
    }
  } else {
    // 文档知识库
    if (allKBList.value.length > 0 && allKBList.value[0].options.length > 0) {
      result.push({
        key: groupKey,
        label: groupLabel,
        options: allKBList.value[0].options.map((option: any) => ({
          ...option,
          isGraphKb: false
        }))
      });
    }
    // 知识图谱，仅在混合检索时可选
    if (appForm.value.template === 'Blended' && allGraphKBList.value.length > 0 && allGraphKBList.value[0].options.length > 0) {
      result.push({
        key: 'graphKb',
        label: proxy.$t('modules.kb.graphKnowledgeBase'),
        options: allGraphKBList.value[0].options.map((option: any) => ({
          ...option,
          isGraphKb: true
        }))
      });
    }
  }

  return result;
});

const kbFilterKeyword = ref('');

const displayedKBList = computed(() => {
  const keyword = kbFilterKeyword.value.trim().toLowerCase();
  if (!keyword) {
    return mergedKBList.value;
  }

  return mergedKBList.value
    .map(group => {
      const options = group.options.filter((option: KB_OPTION_TYPE) => {
        const name = option?.name ?? '';
        return name.toLowerCase().includes(keyword);
      });
      return {
        ...group,
        options
      };
    })
    .filter(group => group.options.length > 0);
});

// 处理知识库选择
const handleKbSelection = () => {
  // 由于界面已经根据模板类型限制了可选择的知识库，这里只需要同步更新字段
  syncKbFields();
};

// 切换分组收起/展开状态
const toggleGroupCollapse = (groupKey: string) => {
  // 基于当前的动态状态进行切换
  const currentState = dynamicGroupCollapseState.value[groupKey] || false;
  groupCollapseState.value[groupKey] = !currentState;
};

// 处理分组标题点击
const handleGroupTitleClick = (groupKey: string) => {
  toggleGroupCollapse(groupKey);
};

// 处理选择变化，过滤掉分组标题
const handleSelectChange = (selectedValues: any[]) => {
  // 过滤掉分组标题选项（以 'group-' 开头的值）
  const filteredValues = selectedValues.filter(value => {
    if (typeof value === 'string' && value.startsWith('group-')) {
      return false;
    }
    return true;
  });

  // 始终更新选中值，确保分组标题不会被保留
  appForm.value.selectedKbs = filteredValues;
};

const handleKbFilter = (query: string) => {
  kbFilterKeyword.value = query ?? '';
};

// 把 UI 选择同步到接口的 kbPkIds / graphKbPkIds
const syncKbFields = () => {
  const selectedKbs = appForm.value.selectedKbs;
  appForm.value.kbPkIds = selectedKbs.filter((kb: KB_OPTION_TYPE) => !kb.isGraphKb);
  appForm.value.graphKbPkIds = selectedKbs.filter((kb: KB_OPTION_TYPE) => kb.isGraphKb);
};

// 监听模板变化
watch(() => appForm.value.template, (newTemplate) => {
  if (appForm.value.knowledgeType === KNOWLEDGE_TYPE.KNOWLEDGE_BASE && newTemplate !== 'Blended') {
    const normalKbs = appForm.value.selectedKbs.filter((kb: KB_OPTION_TYPE) => !kb.isGraphKb);
    appForm.value.selectedKbs = normalKbs;
    syncKbFields();
  }
  kbFilterKeyword.value = '';
  validateSelectedKbs();
});

// 监听selectedKbs变化，同步更新原有字段
watch(() => appForm.value.selectedKbs, () => {
  syncKbFields();
  // 触发表单验证
  setTimeout(() => {
    validateSelectedKbs();
  }, 0);
}, { deep: true });

watch(() => appForm.value.knowledgeType, async (newType: KnowledgeType, oldType: KnowledgeType) => {
  if (initializing.value || newType === oldType) {
    return;
  }
  // 切换知识库类型时先确认：静默清空已选知识库 + 强制改模板会让用户切换后
  // 才发现选择没了。取消则回退选中值。
  if (!isEditMode.value && appForm.value.selectedKbs.length) {
    try {
      await ElMessageBox.confirm(
        proxy.$t('ragFlow.switchTypeClearConfirm'),
        proxy.$t('messageBox.tip'),
        { type: 'warning' }
      );
    } catch {
      // 取消：把 v-model 改回旧值；用 initializing 挡住回退本身触发的 watcher。
      initializing.value = true;
      appForm.value.knowledgeType = oldType;
      await nextTick();
      initializing.value = false;
      return;
    }
  }
  if (newType === KNOWLEDGE_TYPE.DATABASE) {
    appForm.value.template = 'Sequential';
  } else if (!availableTemplates.value.find(item => item.value === appForm.value.template)) {
    appForm.value.template = 'Blended';
  }
  appForm.value.selectedKbs = [];
  syncKbFields();
  resetGroupCollapseState();
  kbFilterKeyword.value = '';
  validateSelectedKbs();
});

function resetGroupCollapseState() {
  groupCollapseState.value = {};
}

function inferKnowledgeType(selectedKbs: KB_OPTION_TYPE[] = []): KnowledgeType {
  if (selectedKbs.some((kb) => kb.type === 'struct_knowledge')) {
    return KNOWLEDGE_TYPE.DATABASE;
  }
  return KNOWLEDGE_TYPE.KNOWLEDGE_BASE;
}

function validateSelectedKbs() {
  // 编辑模式下「知识库」表单项是 v-if 隐藏的（selectedKbs 不允许改），
  // 但 selectedKbs 的 deep watcher 仍会在回填数据时触发 —— 对一个不存在的
  // field 调 validateField 会让 EP 刷 `[ElForm] please pass correct props!`。
  if (appFormRef.value && !isEditMode.value) {
    // validateField 不传 callback 时固定返回一个 reject 的 Promise（EP 2.9.x），
    // 这里要的只是它的副作用（把红色校验提示打出来），必须吞掉拒绝 ——
    // 否则每次打开弹窗（appForm 被换成空对象触发 deep watcher）都会抛一条
    // 无人处理的 unhandled rejection，在控制台显示成 "Object: Object"
    (appFormRef.value as any).validateField('selectedKbs').catch(() => {});
  }
}

function getKBList () {
  getAllKBList().then((res: any) => {
    // 只取 res['running']（= 已发布到资产中心的知识库）会得到空列表：
    // 没有资产中心时知识库状态永远到不了「已发布」，而 selectedKbs 又是必填 ——
    // 结果是**建不出工作流**。
    // 这里把 dev 一并纳入（检索页 /retrieve 取的也是 /kbase 全量列表）。
    // 若将来接入资产中心、恢复「只有已发布才可选」的语义，删掉下面这行的 dev 部分即可。
    const runningKBs = [
      ...(res[KB_PUBLISH_STATUS.RUNNING] || []),
      ...(res[KB_PUBLISH_STATUS.DEV] || [])
    ];

    // 分离普通知识库、知识图谱和结构化知识库
    const knowledgeBaseKBs = runningKBs.filter((kb: any) => kb.type !== 'struct_knowledge');
    const normalKBs = knowledgeBaseKBs.filter((kb: any) => !kb.tableName.includes('graph'));
    const graphKBs = knowledgeBaseKBs.filter((kb: any) => kb.tableName.includes('graph'));
    const structKBs = runningKBs.filter((kb: any) => kb.type === 'struct_knowledge');

    // 设置普通知识库列表
    if (normalKBs.length > 0) {
      allKBList.value = [{
        label: '', // 设置为空字符串，隐藏分组标题
        options: normalKBs.map((option: any) => ({
          ...option,
          key: `assetId${option.assetId}`,
          status: KB_PUBLISH_STATUS.RUNNING
        }))
      }];
    } else {
      allKBList.value = [];
    }

    // 设置知识图谱列表
    if (graphKBs.length > 0) {
      allGraphKBList.value = [{
        label: '', // 设置为空字符串，隐藏分组标题
        options: graphKBs.map((option: any) => ({
          ...option,
          key: `assetId${option.assetId}`,
          status: KB_PUBLISH_STATUS.RUNNING
        }))
      }];
    } else {
      allGraphKBList.value = [];
    }

    // 设置结构化知识库列表
    if (structKBs.length > 0) {
      structuredKBList.value = [{
        label: '', // 设置为空字符串，隐藏分组标题
        options: structKBs.map((option: any) => ({
          ...option,
          key: `assetId${option.assetId}`,
          status: KB_PUBLISH_STATUS.RUNNING
        }))
      }];
    } else {
      structuredKBList.value = [];
    }
  })
    .catch((err: any) => {
      // 列表加载失败时保留空列表；错误详情留给控制台（接口拦截器已负责用户提示）
      console.error('加载知识库列表失败:', err)
    })
}

defineExpose({
  openDialog
})
</script>

<style scoped lang="less">
:deep(.el-select) {
  width: 430px !important;
}
:deep(.el-input) {
  width: 430px !important;
}
:deep(.el-textarea) {
  width: 430px !important;
}
:deep(.el-select__selected-item){
  margin-right: 4px;
}
.el-form-item:last-child {
  margin-bottom: 0;
}

// 修改 textarea 字符计数显示位置，使其显示在输入框下方
:deep(.el-form-item) {
  // 确保表单项容器允许溢出显示
  overflow: visible !important;

  // 为包含 textarea 的表单项添加底部间距
  .el-textarea {
    position: relative !important;
    margin-bottom: 20px !important; // 为字符计数预留空间
    overflow: visible !important; // 确保字符计数可以显示在容器外

    // 字符计数样式 - 使用多种选择器确保覆盖
    .el-input__count,
    .el-input__count {
      background: var(--el-fill-color-blank) !important;
      color: var(--el-input-count-color) !important;
      font-size: 12px !important;
      line-height: 14px !important;
      position: absolute !important;
      right: 8px !important;
      bottom: -19px !important;
      z-index: 10 !important;
    }
  }

  // 确保 el-input__wrapper 也允许溢出
  .el-textarea .el-input__wrapper {
    overflow: visible !important;
  }
}

// 全局覆盖 Element Plus 的默认样式（针对 textarea）
:deep(.el-textarea .el-input__count),
:deep(.el-textarea .el-input__count),
:deep(.el-textarea .el-input__count),
:deep(.el-textarea .el-input__count) {
  bottom: -19px !important;
  right: 8px !important;
  position: absolute !important;
}

// 针对 el-form-item__content 容器
:deep(.el-form-item__content) {
  overflow: visible !important;

  .el-textarea {
    overflow: visible !important;
  }
}

.help-icon {
  margin-left: 2px;
  align-self:center;
}

// 自定义知识库选择器样式
.custom-kb-select {
  // Firefox 兼容性修复：确保分组标题文本完整显示
  // 针对 el-option 组件本身
  :deep(.el-option.group-title-option) {
    overflow: visible !important;
    text-overflow: clip !important;
    white-space: normal !important;

    > span,
    > div {
      overflow: visible !important;
      text-overflow: clip !important;
      white-space: normal !important;
      max-width: none !important;
      width: auto !important;
    }
  }

  // 针对 el-select-dropdown__item
  :deep(.el-select-dropdown__item.group-title-option) {
    overflow: visible !important;
    text-overflow: clip !important;
    white-space: normal !important;

    > span,
    > div {
      overflow: visible !important;
      text-overflow: clip !important;
      white-space: normal !important;
      max-width: none !important;
      width: auto !important;
    }

    .group-header-simple {
      overflow: visible !important;
      text-overflow: clip !important;
      white-space: nowrap !important;
      max-width: none !important;
      width: 100% !important;

      .group-text {
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: nowrap !important;
        max-width: none !important;
        width: auto !important;
        display: inline-block !important;
      }
    }
  }

  :deep(.el-select-dropdown) {
    // 分组标题选项样式
    .el-select-dropdown__item {
      &.group-title-option {
        padding: 0 !important;
        background-color: var(--rs-bg-soft) !important;
        border-bottom: 1px solid var(--rs-border);
        cursor: pointer !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: nowrap !important;

        &:hover {
          background-color: var(--rs-bg-selected) !important;
        }

        &.selected {
          background-color: var(--rs-bg-selected) !important;

          .group-header-simple {
            .arrow-icon {
              color: var(--rs-primary) !important;
            }

            .group-text {
              color: var(--rs-primary) !important;
            }
          }
        }

        .group-header-simple {
          display: block;
          padding: 0 12px;
          width: 100%;
          height: 32px;
          line-height: 32px;
          user-select: none;
          overflow: visible !important;
          text-overflow: clip !important;
          white-space: nowrap !important;
          box-sizing: border-box !important;

          .arrow-icon {
            font-size: 12px;
            color: var(--rs-text-2);
            margin-right: 6px;
            transition: color 0.2s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 16px;
            height: 16px;
          }

          .group-text {
            font-family: "Helvetica Neue", "PingFang SC", Tahoma, "Microsoft Yahei" !important;
            font-size: 12px !important;
            font-weight: bold !important;
            color: var(--rs-text-2) !important;
            letter-spacing: 0.2px !important;
            line-height: 32px !important;
            display: inline-block !important;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: clip !important;
            max-width: none !important;
            width: auto !important;
          }
        }
      }

      // 分组内选项样式
      &.group-item-option {
        padding-left: 20px !important;
        padding-right: 12px !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        height: 32px !important;
        line-height: 32px !important;
        color: var(--rs-text-2);
        display: flex !important;
        align-items: center !important;

        &:hover {
          background-color: var(--rs-bg-soft);
        }

        &.selected {
          color: var(--rs-primary);
          font-weight: 600;
          background-color: var(--rs-bg-selected);
        }
      }
    }
  }
}

// 额外的样式确保分组标题样式一致 - Firefox 兼容性修复
:deep(.el-select-dropdown .el-select-dropdown__item.group-title-option) {
  overflow: visible !important;
  text-overflow: clip !important;
  white-space: normal !important;

  > * {
    overflow: visible !important;
    text-overflow: clip !important;
  }

  .group-header-simple {
    overflow: visible !important;
    text-overflow: clip !important;
    white-space: nowrap !important;
    max-width: none !important;
    width: 100% !important;

    .group-text {
      font-family: "Helvetica Neue", "PingFang SC", Tahoma, "Microsoft Yahei" !important;
      font-size: 12px !important;
      font-weight: bold !important;
      color: var(--rs-text-2) !important;
      letter-spacing: 0.2px !important;
      line-height: 32px !important;
      display: inline-block !important;
      visibility: visible !important;
      opacity: 1 !important;
      white-space: nowrap !important;
      overflow: visible !important;
      text-overflow: clip !important;
      max-width: none !important;
      width: auto !important;
      min-width: 0 !important;
    }
  }
}

// 通用的分组标题样式 - Firefox 兼容性修复
:deep(.group-text) {
  font-family: "Helvetica Neue", "PingFang SC", Tahoma, "Microsoft Yahei" !important;
  font-size: 12px !important;
  font-weight: bold !important;
  color: var(--rs-text-2) !important;
  letter-spacing: 0.2px !important;
  line-height: 32px !important;
  display: inline-block !important;
  white-space: nowrap !important;
  overflow: visible !important;
  text-overflow: clip !important;
  max-width: none !important;
  width: auto !important;
  min-width: 0 !important;
}

// Firefox 兼容性修复：确保下拉框有足够宽度显示完整文本
.custom-kb-select {
  :deep(.el-select-dropdown) {
    min-width: 430px !important;
    width: auto !important;
    max-width: none !important;
  }

  // 确保所有分组标题选项都不被截断
  :deep(.el-select-dropdown__item.group-title-option),
  :deep(.el-option.group-title-option) {
    min-width: 100% !important;
    width: 100% !important;
    overflow: visible !important;
    text-overflow: clip !important;

    * {
      text-overflow: clip !important;
    }
  }
}

// 确保分组内容缩进的额外样式
:deep(.el-select-dropdown .el-select-dropdown__item.group-item-option) {
  padding-left: 20px !important;
  padding-right: 12px !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  height: 32px !important;
  line-height: 32px !important;
  display: flex !important;
  align-items: center !important;
}

// 通用的分组内容缩进样式
:deep(.group-item-option) {
  padding-left: 20px !important;
  padding-right: 12px !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  height: 32px !important;
  line-height: 32px !important;
  display: flex !important;
  align-items: center !important;
}

// 最高优先级的缩进样式 - 使用多种方法确保生效
.custom-kb-select :deep(.el-select-dropdown .el-select-dropdown__item.group-item-option) {
  padding-left: 20px !important;
  padding-right: 12px !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  height: 32px !important;
  line-height: 32px !important;
  margin-left: 0 !important;
  text-indent: 0 !important;
  display: flex !important;
  align-items: center !important;
}

// 使用属性选择器强制应用缩进
:deep(.el-select-dropdown__item[class*="group-item-option"]) {
  padding-left: 20px !important;
  padding-right: 12px !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  height: 32px !important;
  line-height: 32px !important;
  display: flex !important;
  align-items: center !important;
}

// 使用更具体的选择器路径
:deep(.el-select-dropdown) {
  .el-select-dropdown__item {
    &.group-item-option {
      padding-left: 20px !important;
      padding-right: 12px !important;
      padding-top: 0 !important;
      padding-bottom: 0 !important;
      height: 32px !important;
      line-height: 32px !important;
      text-indent: 0 !important;
      display: flex !important;
      align-items: center !important;

      // 使用伪元素添加视觉缩进
      &::before {
        content: '';
        display: inline-block;
        width: 8px;
        height: 1px;
      }
    }
  }
}

// 强制缩进样式 - 最终方案
.custom-kb-select {
  :deep(.el-select-dropdown__item.group-item-option) {
    padding-left: 20px !important;
    height: 32px !important;
    line-height: 32px !important;
    display: flex !important;
    align-items: center !important;

    span {
      margin-left: 8px !important;
      display: inline-block;
      line-height: 32px !important;
    }
  }
}

// 全局强制样式
:deep(.group-item-option span) {
  margin-left: 8px !important;
  display: inline-block;
  line-height: 32px !important;
}

// Firefox 浏览器兼容性修复：防止分组标题文本被截断
// 使用最高优先级的选择器确保样式生效
.custom-kb-select.custom-kb-select {
  :deep(.el-select-dropdown__item.group-title-option),
  :deep(.el-option.group-title-option) {
    overflow: visible !important;
    text-overflow: clip !important;
    white-space: normal !important;

    * {
      overflow: visible !important;
      text-overflow: clip !important;
      max-width: none !important;
    }

    .group-header-simple {
      overflow: visible !important;
      text-overflow: clip !important;
      white-space: nowrap !important;
      width: 100% !important;
      max-width: none !important;

      .group-text {
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: nowrap !important;
        max-width: none !important;
        width: auto !important;
        display: inline-block !important;
      }
    }
  }
}
</style>
