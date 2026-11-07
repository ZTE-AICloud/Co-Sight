<template>
  <el-dialog
    v-model="dialogVisible" :title="title" width="600px" :before-close="beforeCloseHandle" :close-on-click-modal="false"
    append-to-body
  >
    <el-form v-if="dialogVisible" ref="formRef" :model="formData" :rules="formRules" :label-width="$globalZh ? '166px' : '174px'">
      <el-form-item :label="$t('knowledge.kbSetting.kbName')" prop="name">
        <!-- maxlength=30 与建库弹窗 / 服务端 @Pattern（2~30）一致：以前这里不设上限，
             可以一直输，提交时才被 max:30 规则拦住。 -->
        <el-input v-model="formData.name" v-trim maxlength="30" show-word-limit :placeholder="$t('knowledge.inputName')" class="form-item-content--400" />
      </el-form-item>
      <el-form-item :prop="Object.is(mode, EDIT) ? '' : 'props.embeddingModel'">
        <template #label>
          <span>
            {{ $t('advancedFlow.vectorType1') }}
          </span>
        </template>
        <el-select v-if="Object.is(mode, CODECREATE)" v-model="formData.props.embeddingModel" :placeholder="$t('advancedFlow.vectorTypePlaceholder1')" class="form-item-content--400" filterable>
          <el-option v-for="model in kbModelList" :key="model.modelName" :label="model.modelName" :value="model.modelName" />
        </el-select>
        <el-select v-else-if="Object.is(mode, CREATE)" v-model="formData.props.embeddingModel" :placeholder="$t('advancedFlow.vectorTypePlaceholder1')" class="form-item-content--400" filterable>
          <el-option v-for="model in kbModelList" :key="model.modelName" :label="model.modelName" :value="model.modelName" />
        </el-select>
        <div v-else>
          {{ formData.props.embeddingModel }}
        </div>
      </el-form-item>
      <el-form-item :label="$t('knowledge.kbSetting.kbDesc')" prop="description">
        <el-input
          v-model="formData.description" :placeholder="$t('knowledge.import.descriptionPlaceholder')" maxlength="1000"
          show-word-limit type="textarea"
          :rows="4"
          class="form-item-content--400"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <span>
        <el-button :loading="loading" :disabled="loading" type="primary" @click="submitHandle">{{ submitButtonLabel }}</el-button>
        <el-button plain @click="closeHandle">{{ $t("public.cancel") }}</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script lang="ts" setup>
import { ref, getCurrentInstance } from 'vue';
import { getModelList as getModuleListApi } from '@/features/model/api/models';
import { createKnowledgeBase as createKnowledgeBaseApi, getKnowledgeBaseInfo, updatedKnowledgeBaseInfo } from '@/features/knowledge-base/api/knowledgeBase';
import { CREATE, EDIT, CODECREATE } from '@/shared/constants/index.js';
import { KB_CATEGORY } from '@/features/knowledge-base/constants.js';
const props = defineProps({
  kbCategory: {
    type: Number,
    default: KB_CATEGORY.DOCUMENT
  },
  codeKbCategory: {
    type: Number,
    default: KB_CATEGORY.CODE
  }
});

// 获取当前组件实例
const { proxy } = getCurrentInstance() as any;

// 定义组件对外暴露的事件
const emits = defineEmits(['refreshTableData']);

// 获取子组件的引用
const formRef = ref();

// 知识库模型列表
const kbModelList = ref<any[]>([]);

// 嵌入模型提示信息
const embeddingModelTip = ref<any[]>([])

// 获取初始化表单数据
function getInitFormData () {
  return {
    name: '',
    description: '',
    props: {
      embeddingModel: ''
    }
  }
}

// 表单数据
const formData = ref(getInitFormData())

// 名称校验函数：允许空格，但不能全为空格
const validateName = (rule: any, value: any, callback: any) => {
  if (!value) {
    callback();
    return;
  }
  // 检查是否全为空格
  if (/^\s+$/.test(value)) {
    callback(new Error(proxy.$t('knowledge.nameLimit')));
    return;
  }
  // 检查字符格式：允许英文、数字、下划线、中文、英文点、英文中划线和空格
  if (!/^[\w\u4e00-\u9fa5.\-\s]+$/.test(value)) {
    callback(new Error(proxy.$t('knowledge.nameLimit')));
    return;
  }
  callback();
};

// 表单验证规则
const formRules = ref({
  name: [{
    required: true, message: proxy.$t('knowledge.inputName'), trigger: ['blur', 'change']
  }, {
    min: 2, max: 30, message: proxy.$t('knowledge.len30'), trigger: ['blur', 'change']
  }, {
    validator: validateName, trigger: ['blur', 'change']
  }],
  description: [{
    max: 1000, message: proxy.$t('knowledge.len1000'), trigger: 'change'
  }],
  'props.embeddingModel': [{ required: true, message: proxy.$t('advancedFlow.vectorTypePlaceholder1'), trigger: 'change' }]
})

// 常量定义
const TYPE_STRING = 'string';
const TYPE_OBJECT = 'object';
const VALUE_NULL = null;
const VALUE_UNDEFINED = undefined;

// 模型清单只在首次打开弹窗时拉取：本组件常驻列表页模板（Knowledge.vue），
// 在 setup 里无条件请求会让每次进入列表页都多打一条 `GET /system/embedding-models`，
// 而弹窗没打开时这份清单没人用。失败后允许下次打开重试。
let moduleListRequested = false;

function ensureModuleList () {
  if (moduleListRequested) {
    return;
  }
  moduleListRequested = true;
  getModuleList();
}

// 获取知识库模型列表
function getModuleList () {
  embeddingModelTip.value = [];
  getModuleListApi()
    .then((res: any) => {
      if (Array.isArray(res)) {
        // 如果res是数组，则可能包含字符串或其他类型的元素
        kbModelList.value = res.map(item => {
          if (typeof item === TYPE_STRING) {
            // 如果数组中的元素是字符串，则将其转换为含有modelName的对象
            return { modelName: item };
          } else if (typeof item === TYPE_OBJECT && item !== VALUE_NULL && !Array.isArray(item)) {
            if (item.modelName && item.useInstruction) {
              embeddingModelTip.value.push(`${item.modelName}${proxy.$t('public.colon')}${proxy.$globalZh ? item.useInstruction : (item.useInstructionEn || item.useInstruction)}`)
            }
            // 如果数组中的元素是对象且不为null且不是数组，则假设它已经是一个含有modelName的对象
            return item;
          }
          // 对于其他类型的元素，可以根据实际情况决定如何处理
          return {};
        });
      } else if (res === VALUE_NULL || res === VALUE_UNDEFINED) {
        // 如果res是null或undefined，则直接赋值为空数组
        kbModelList.value = [];
      } else {
        // 如果res是其他类型，则抛出错误或根据实际情况处理
        throw new Error('Unexpected type of res');
      }
      kbModelList.value = kbModelList.value
        .slice() // 创建副本，避免直接修改原数组（推荐）
        .sort((a, b) => a.modelName?.localeCompare(b.modelName || ''));
    })
    .catch(() => {
      // 加载失败：清掉「已请求」标记，下次打开弹窗再试
      moduleListRequested = false;
    })
}

// 对话框是否显示
const dialogVisible = ref(false);

// 加载状态
const loading = ref(false);

// 对话框标题
const title = ref(proxy.$t('knowledge.createKB'));

const submitButtonLabel = ref(proxy.$t('modules.kb.createKb'));

// 操作模式
const mode = ref(CREATE);

// 修改的知识库ID
const modifyId = ref('');

/**
 * 打开对话框
 * @param params 参数对象，包含mode和id属性
 */
function openDialog (params: {
  mode: typeof CREATE | typeof EDIT;
  id?: string,
  title?: string
}) {
  // 首次打开时才拉模型清单（setup 里不再请求，见 ensureModuleList）
  ensureModuleList();
  loading.value = false;
  dialogVisible.value = true;
  mode.value = params.mode;
  title.value = params.title || proxy.$t('knowledge.createKB');
  submitButtonLabel.value = proxy.$t('modules.kb.createKb');
  if (Object.is(params.mode, EDIT)) {
    modifyId.value = params.id as string;
    fillBackData(params.id as string);
    title.value = proxy.$t('public.modify');
    submitButtonLabel.value = proxy.$t('public.confirm');
  }
}

/**
 * 填充表单数据
 * @param id 知识库ID
 */
function fillBackData (id: string) {
  getKnowledgeBaseInfo(id)
    .then((res: any) => {
      formData.value = res;
    })
}

/**
 * 关闭对话框
 */
function closeHandle () {
  dialogVisible.value = false;
  formData.value = getInitFormData();
}

/**
 * 提交表单
 */
function submitHandle () {
  formRef.value.validate(async (valid: any) => {
    if (valid) {
      loading.value = true;
      if (Object.is(mode.value, EDIT)) {
        modifyHandle();
      } else {
        createHandle();
      }
    }
  })
}

/**
 * 创建知识库
 */
function createHandle () {
  const params = {
    name: formData.value.name,
    description: formData.value.description,
    category: Object.is(mode.value, CREATE) ? props.kbCategory : props.codeKbCategory,
    props: {
      embeddingModel: formData.value.props.embeddingModel
    }
  }
  createKnowledgeBaseApi(params).then((res: any) => {
    proxy.$message.success(proxy.$t('messageBox.createSuccess'));
    emits('refreshTableData', res)
    closeHandle()
  })
    .finally(() => {
      loading.value = false;
    })
}

/**
 * 修改知识库
 */
function modifyHandle () {
  updatedKnowledgeBaseInfo(modifyId.value, { ...formData.value, category: Object.is(mode.value, CREATE) ? props.kbCategory : props.codeKbCategory })
    .then((res: any) => {
      proxy.$message.success(proxy.$t('public.modifySuccess'));
      emits('refreshTableData', res);
      closeHandle()
    })
    .finally(() => {
      loading.value = false;
    })
}

/**
 * 关闭前处理
 * @param done 回调函数
 */
function beforeCloseHandle (done: Function) {
  closeHandle();
  done();
}

// 定义组件对外暴露的方法
defineExpose({
  openDialog
})
</script>

<style lang="less" scoped>
// 修改 textarea 字符计数显示位置，使其显示在输入框下方
:deep(.el-form-item) {
  // 确保表单项容器允许溢出显示
  overflow: visible !important;

  // 为包含 textarea 的表单项添加底部间距
  .el-textarea,
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
  .el-textarea .el-input__wrapper,
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

  .el-textarea,
  .el-textarea {
    overflow: visible !important;
  }
}

// 针对 el-dialog 内的表单项，确保对话框也允许溢出
:deep(.el-dialog) {
  overflow: visible !important;

  .el-dialog__body {
    overflow: visible !important;
  }
}
</style>
