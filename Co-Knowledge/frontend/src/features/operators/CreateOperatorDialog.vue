<template>
  <el-dialog
    v-model="dialogVisible"
    :title="$t('modules.extendedManagement.createExtendedManagement')"
    width="600px"
    :append-to-body="true"
    :close-on-press-escape="false"
    :close-on-click-modal="false"
    :before-close="beforeCloseHandle"
  >
    <el-form ref="formRef" :model="formData" label-position="right" :rules="formRules" label-width="84px">
      <el-form-item prop="file">
        <div class="upload-box">
          <el-upload
            :limit="fileLimit"
            :on-exceed="handleExceed"
            :on-remove="handleRemove"
            :file-list="formData.file"
            action=""
            drag
            :before-upload="beforeUpload"
            :auto-upload="false"
            :on-change="fileHandleChange"
          >
            <el-icon class="el-icon--upload">
              <upload-filled />
            </el-icon>
            <div class="el-upload__text">
              {{ $t('modules.extendedManagement.uploadOperatorTips1') }}{{ $t('modules.extendedManagement.uploadOperatorTips2') }}{{ $t('public.period') }}
            </div>
            <template #tip>
              <div class="el-upload__tip">
                <div>{{ $t('modules.extendedManagement.uploadOperatorTips5') }}</div>
                <div>
                  {{ $t('modules.extendedManagement.uploadOperatorTips3', {
                    fileType: whiteList.join(','),
                    fileSize: `${filesizeLimit}MB`
                  }) }}
                </div>
              </div>
            </template>
          </el-upload>
        </div>
      </el-form-item>
      <!-- </el-form-group> -->
    </el-form>
    <template #footer>
      <span>
        <el-button :disabled="saveDisabled" type="primary" @click="submitHandle">{{ $t("public.confirm") }}</el-button>
        <el-button plain @click="closeHandle">{{ $t("public.cancel") }}</el-button>
      </span>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { ref, getCurrentInstance } from 'vue';
import { KILOBTTE } from '@/shared/constants/index';
import { createOperatorApi } from '@/features/operators/api/operator.js';
import { UploadFilled } from '@/shared/lib/icons';
// 导入文件验证功能
import { useValidateFiles } from '@/features/knowledge-base/composables/useValidateFiles.js';


const { proxy } = getCurrentInstance() as any;

// 使用文件验证功能
const { validateFiles } = useValidateFiles(proxy);


const dialogVisible = ref(false);

const saveDisabled = ref(false);

const formRef = ref();

function getInitFormData () {
  return {
    file: []
  }
}

const formData = ref(getInitFormData());

const formRules = ref(
  {
    file: [{ required: true, message: proxy.$t('modules.extendedManagement.uploadOperatorTips4'), trigger: 'change' }]
  }
)

const filesizeLimit = 2;
const fileLimit = 1;
const whiteList = ['zip'];
// const whiteListString = ''

function beforeUpload (file: File) {
  // 0.1.7：空文件直接拒绝（后端只校验格式与大小，0 字节会一路走到解包）。
  if (!file.size) {
    proxy.$message.warning(proxy.$t('modules.extendedManagement.uploadEmptyFile'));
    return false;
  }
  const isLt10M = file.size / KILOBTTE / KILOBTTE < filesizeLimit;
  if (!isLt10M) {
    proxy.$message.warning(proxy.$t('chat.fileSizeLimit', {
      name: file.name,
      filesizeLimit
    }));
    return false;
  }
  const fileSuffix = file.name.substring(file.name.lastIndexOf('.') + 1).toLowerCase()
  if (!whiteList.includes(fileSuffix)) {
    proxy.$message.warning(proxy.$t('kbEvaluation.uploadTypeLimit', {
      fileType: whiteList.join(',')
    }));
    return false
  }
  return true;
}

function handleExceed (files: File[], fileList: File[]) {
  proxy.$message.warning(proxy.$t('chat.fileLimit', {
    fileLimit,
    currentNum: files.length,
    totalNum: files.length + fileList.length
  }));
}

function handleRemove (file: File[], fileList: File[]) {
  (formData.value.file as File[]) = fileList;
  formRef.value.validateField('file');
  uploadDisabled(formData.value.file);
}

function fileHandleChange (file: any, fileList: Array<File>) {
  if (file.status === 'ready') {
    if (beforeUpload(file)) {
      (formData.value.file as any[]) = [...fileList]
    } else {
      formData.value.file = [];
    }
  }
  formRef.value.validateField('file');
  uploadDisabled(formData.value.file);
}

function uploadDisabled (fileList:Array<File>) {
  if (fileList.length >= fileLimit) {
    const uploadElement = document.querySelector('.el-upload');
    if (uploadElement) {
      // 修改样式使其不可点击
      uploadElement.style.pointerEvents = 'none'; // 禁用鼠标事件
    }
  } else {
    const uploadElement = document.querySelector('.el-upload');
    if (uploadElement) {
      // 修改样式使其不可点击
      uploadElement.style.pointerEvents = 'auto'; // 禁用鼠标事件
    }
  }
}

const emits = defineEmits<{
    (e: 'refreshTableData'): void,
  }>()


function beforeCloseHandle (done: Function) {
  closeHandle();
  done();
}

function openDialog () {
  closeHandle();
  formRef.value?.clearValidate();
  dialogVisible.value = true;
}

function closeHandle () {
  formData.value = getInitFormData();
  const uploadElement = document.querySelector('.el-upload');
  if (uploadElement) {
    uploadElement.style.pointerEvents = 'auto'; // 禁用鼠标事件
  }
  dialogVisible.value = false;
}

function submitHandle () {
  formRef.value.validate(async (valid: any) => {
    if (valid) {
      saveDisabled.value = true;

      try {
        // 添加文件可访问性验证
        await validateFiles(formData.value.file);

        const data = new FormData();
        formData.value.file.forEach((item: any) => {
          data.append('file', item.raw)
        })

        createOperatorApi(data).then(() => {
          closeHandle();
          emits('refreshTableData');
          proxy.$message.success(proxy.$t('modules.extendedManagement.createSuccess'));
        })
          .catch((error: any) => {
            // 业务错误已在axios拦截器中处理，这里只处理网络错误
            console.error('上传失败:', error);
            // 检查是否是网络错误或其他非业务错误
            if (error?.code === 'network_error') {
              proxy.$message.error(proxy.$t('public.networkError'));
            }
            // 业务错误（如算子名称重复）已在base.js中显示，这里不重复显示
          })
          .finally(() => {
            saveDisabled.value = false;
          })
      } catch (error: any) {
        // 处理文件验证失败
        saveDisabled.value = false;
        proxy.$message.error(error.message);
      }
    }
  })
}


defineExpose({
  openDialog
})

</script>

  <style lang="less" scoped>
    .upload-box {
      width: 400px;
      // display: flex;
      // justify-content: center;
      :deep(.el-upload-dragger) {
        width: 400px;
        height: 116px;
        // display: flex;
        // flex-direction: column;
        // justify-content: center;
        line-height: 18px;
        .plx-ico-cloud-f-48 {
          margin: unset;
          font-size: 48px;
        }
      }
      .el-dropdown-link {
        font-size: 12px;
      }
    }
  </style>
