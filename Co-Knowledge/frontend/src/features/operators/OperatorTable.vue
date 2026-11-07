<template>
  <div class="operator-table-root">
    <div class="toolbar">
      <div class="toolbar-left">
        <template v-if="visibleOperation">
          <el-button type="primary" @click="addOperatorHandle">
            <Plus />
            {{ $t('modules.extendedManagement.createExtendedManagement') }}
          </el-button>
          <el-dropdown trigger="click">
            <el-button>
              <Download />
              {{ $t('modules.extendedManagement.downloadTemplate') }}
              <ArrowDown class="operator-dropdown-arrow" />
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <template v-for="item in operatorTypeList" :key="item[0]">
                  <el-dropdown-item
                    v-if="item[1].value !== 'rag_operator'"
                    @click="downloadTemplateClickHandle(item[0])"
                  >
                    {{ item[1].label }}
                  </el-dropdown-item>
                </template>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </div>
      <div class="toolbar-right">
        <TableRefreshButton :label="$t('modules.extendedManagement.refreshList')" :refresh="refreshList" />
        <el-input
          v-model.trim="searchKey"
          class="search-field"
          :placeholder="$t('modules.extendedManagement.operatorNameSearch')"
          :prefix-icon="Search"
          clearable
          @input="search"
        />
      </div>
    </div>

    <ListSelectionBar :count="selectedRows.length" @clear="clearSelection">
      <el-button link type="primary" @click="batchOperators('public')">
        {{ $t('modules.extendedManagement.batchPublic') }}
      </el-button>
      <el-button link @click="batchOperators('private')">
        {{ $t('modules.extendedManagement.batchPrivate') }}
      </el-button>
      <el-button class="danger-action" link type="danger" @click="batchOperators('delete')">
        <Delete />{{ $t('modules.extendedManagement.batchDelete') }}
      </el-button>
    </ListSelectionBar>

    <div v-loading="loading" class="table-card">
      <table class="list-table operator-table">
        <thead>
          <tr>
            <th class="check-cell">
              <input
                type="checkbox"
                :aria-label="$t('modules.extendedManagement.selectAllPage')"
                :checked="allSelected"
                @change="toggleAll($event.target.checked)"
              >
            </th>
            <th>{{ $t('modules.extendedManagement.operatorName') }}</th>
            <th>{{ $t('modules.extendedManagement.operatorType') }}</th>
            <th>{{ $t('modules.extendedManagement.uploadTime') }}</th>
            <th>{{ $t('modules.extendedManagement.scope') }}</th>
            <th>{{ $t('agentApi.description2') }}</th>
            <th v-if="visibleOperation">
              {{ $t('public.operate') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="row.id">
            <td class="check-cell">
              <input
                type="checkbox"
                :checked="isSelected(row)"
                :aria-label="$t('modules.extendedManagement.selectOperator', { name: displayName(row) })"
                @change="toggleRow(row, $event.target.checked)"
              >
            </td>
            <td>
              <div class="entity">
                <div :class="['tinted-icon', index % 2 ? 'green' : 'blue']">
                  <Document />
                </div>
                <div>
                  <div class="entity-title">
                    {{ displayName(row) }}
                  </div>
                  <div class="entity-sub">
                    {{ row.nameEn || row.module || '--' }}
                  </div>
                  <div v-if="row.system" class="table-tags">
                    <span class="tag-soft blue">
                      {{ $t('modules.extendedManagement.builtin') }}
                    </span>
                  </div>
                </div>
              </div>
            </td>
            <td>
              <span class="tag-soft purple">{{ typeLabel(row) }}</span>
            </td>
            <td class="nowrap">
              {{ row.createdDate || '--' }}
            </td>
            <td>
              <el-button @click="publicClickHandle(row)">
                <component :is="row.visibleRange === PUBLIC ? Lock : GlobeIcon" />
                {{ row.visibleRange === PUBLIC
                  ? $t('modules.extendedManagement.public2')
                  : $t('modules.extendedManagement.public') }}
              </el-button>
            </td>
            <td>
              <div class="operator-description" :title="descriptionOf(row)">
                {{ descriptionOf(row) }}
              </div>
            </td>
            <td v-if="visibleOperation">
              <el-dropdown
                trigger="click"
                @command="command => operationCommand(command, row)"
              >
                <button class="icon-button" :aria-label="displayName(row) + ' ' + $t('public.operate')">
                  <MoreFilled class="more-icon" />
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="scope">
                      <component :is="row.visibleRange === PUBLIC ? Lock : GlobeIcon" />
                      {{ row.visibleRange === PUBLIC
                        ? $t('modules.extendedManagement.public2')
                        : $t('modules.extendedManagement.public') }}
                    </el-dropdown-item>
                    <el-dropdown-item command="download">
                      <Download />
                      {{ $t('knowledge.download') }}
                    </el-dropdown-item>
                    <el-dropdown-item class="danger-menu-item" command="delete" divided>
                      <Delete />
                      {{ $t('public.delete') }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="visibleOperation ? 7 : 6" class="empty-row">
              {{ props.mode === PUBLIC
                ? $t('modules.extendedManagement.emptyPublic')
                : $t('modules.extendedManagement.emptySearch') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <TablePagination
      :total="total"
      :page="currentPage"
      :size="pageSize"
      @change="onPaginationChange"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance, onMounted, reactive, ref } from 'vue';
import { download } from '@/shared/lib/utils';
import { exportOperatorTemplateApi, deleteOperatorApi, exportOperatorApi, publicOperatorApi, unPublicOperatorApi } from '@/features/operators/api/operator.js';
import { debounce } from 'lodash';
import { DEBOUNCETIME } from '@/shared/constants/index.js';
import { ArrowDown, Delete, Document, Download, Lock, MoreFilled, Plus, Search } from '@/shared/lib/icons';
import { GlobeIcon } from '@/shared/ui/icons';
import TablePagination from '@/shared/ui/reference/TablePagination.vue';
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue';
import ListSelectionBar from '@/shared/ui/ListSelectionBar.vue';
import { requestDeletion } from '@/shared/composables/deletion';

const { proxy } = getCurrentInstance() as any;

const PUBLIC = 'public';
const props = defineProps({
  api: {
    type: Function,
    default: () => () => {}
  },
  visibleOperation: {
    type: Boolean,
    default: true
  },
  keyword: {
    type: String,
    default: ''
  },
  operatorType: {
    type: String,
    default: ''
  },
  operatorTypeList: {
    type: Map,
    default: () => new Map()
  },
  mode: {
    type: String,
    default: 'private'
  }
})

const emits = defineEmits(['refreshTableData', 'addOperatorHandle'])

const searchKey = ref('');
const search = debounce(() => {
  clearSelection();
  refreshTableData('initPage');
}, DEBOUNCETIME);

const rows = ref<any[]>([]);
const loading = ref(false);
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const selectedMap = reactive(new Map<string, any>());
const selectedRows = computed(() => Array.from(selectedMap.values()));
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((row: any) => selectedMap.has(row.id)));

function isSelected (row: any): boolean {
  return Boolean(row?.id) && selectedMap.has(row.id)
}

function toggleRow (row: any, checked: boolean) {
  if (!row?.id) {
    return
  }
  if (checked) {
    selectedMap.set(row.id, { ...row })
  } else {
    selectedMap.delete(row.id)
  }
}

function toggleAll (checked: boolean) {
  rows.value.forEach(row => {
    if (checked) {
      selectedMap.set(row.id, { ...row })
    } else {
      selectedMap.delete(row.id)
    }
  })
}

function clearSelection () {
  selectedMap.clear()
}

function syncSelectedRows (data: any[]) {
  data.forEach(row => {
    if (row?.id && selectedMap.has(row.id)) {
      selectedMap.set(row.id, { ...row })
    }
  })
}

function displayName (row: any): string {
  return (proxy.$globalZh ? row.name : (row.nameEn || row.name)) || '--';
}

function descriptionOf (row: any): string {
  return (proxy.$globalZh ? row.description : (row.descriptionEn || row.description)) || '--';
}

function typeLabel (row: any): string {
  return props.operatorTypeList.get(row.module)?.label || row.module || '--';
}

/**
 * 获取表格数据的API函数
 * @param {Object} params - 请求参数对象
 * @param {Object} config - 请求配置
 */
function getTableDataApi (params: any, config: any) {
  params.keyword = searchKey.value;
  params.visibleRange = props.mode;
  return props.api(params, config);
};

async function loadRows (): Promise<boolean> {
  loading.value = true;
  try {
    const result: any = await getTableDataApi(
      { currentPage: currentPage.value, pageSize: pageSize.value },
      {}
    );
    const data = Array.isArray(result?.items) ? result.items : [];
    syncSelectedRows(data);
    rows.value = data;
    total.value = Number(result?.total) || data.length;
    return true;
  } catch (e) {
    // 错误提示由拦截器统一弹；表格保持上一屏数据
    return false;
  } finally {
    loading.value = false;
  }
}

/** 刷新：保留搜索 / 页码 / 勾选；失败保留原列表。 */
async function refreshList (): Promise<void> {
  let ok = await loadRows();
  const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value));
  if (ok && currentPage.value > maxPage) {
    currentPage.value = maxPage;
    ok = await loadRows();
  }
  if (!ok) {
    throw new Error('refresh failed');
  }
}

/**
 * 刷新表格数据的方法（父级/新增弹窗调用）
 * @param {string} initPage - 传值时回到第一页
 */
function refreshTableData (initPage: string = '') {
  if (initPage) {
    currentPage.value = 1;
  }
  return loadRows();
};

function onPaginationChange ({ page, size }: { page: number, size: number }) {
  currentPage.value = page;
  pageSize.value = size;
  loadRows();
}

onMounted(() => {
  loadRows();
});

function addOperatorHandle () {
  emits('addOperatorHandle')
}

/**
 * 「设为公开 / 设为私有」的确认框**同一时刻只允许一个**。
 *
 * 快速连点会把同一个 `$confirm` 叠成 2~3 层，
 * 关的时候得一层层点。这里用一个非响应式闸门：进函数先占位，确认框关闭（含取消）
 * 且接口返回后再放开。不用 ref 是因为模板里没有要跟着变的东西，纯函数级互斥即可。
 */
let visibilityConfirming = false

function publicClickHandle (row) {
  if (visibilityConfirming) {
    return
  }
  visibilityConfirming = true
  const confirmOption = {
    message: proxy.$t('modules.extendedManagement.public5', {
      name: proxy.$globalZh ? row.name : row.nameEn
    }),
    describe: proxy.$t('modules.extendedManagement.public3'),
    title: proxy.$t('modules.extendedManagement.public1'),
    successInfo: proxy.$t('modules.extendedManagement.public7')
  }
  let publicApi = publicOperatorApi;
  if (row.visibleRange === PUBLIC) {
    confirmOption.message = proxy.$t('modules.extendedManagement.public6', {
      name: proxy.$globalZh ? row.name : row.nameEn
    })
    confirmOption.describe = proxy.$t('modules.extendedManagement.public4')
    confirmOption.title = proxy.$t('modules.extendedManagement.public2')
    confirmOption.successInfo = proxy.$t('modules.extendedManagement.public8')
    publicApi = unPublicOperatorApi;
  }
  proxy.$confirm(confirmOption.message, confirmOption.title, {
    confirmButtonText: proxy.$t('public.confirm'),
    cancelButtonText: proxy.$t('public.cancel'),
    type: 'warning',
    describe: confirmOption.describe
  // then 里 **return** 内层请求，闸门要等接口也回来才放开 —— 否则用户还能在
  // 请求进行中再开一个确认框，点第二次又发一次公开/取消公开。
  }).then(() => publicApi(row.id).then(() => {
    proxy.$message.success(confirmOption.successInfo);
    emits('refreshTableData');
  }))
    .catch(() => {})
    .finally(() => {
      visibilityConfirming = false
    });
}

/** 操作列「更多」：把公开/私有、删除、下载收进菜单。 */
function operationCommand (command: string, row: any) {
  if (command === 'scope') {
    publicClickHandle(row)
  } else if (command === 'delete') {
    deleteClickHandle(row)
  } else if (command === 'download') {
    downloadClickHandle(row)
  }
}

function downloadClickHandle (row: any) {
  exportOperatorApi(row.id, row.type).then((res: any) => {
    // 必须显式给文件名：blob 下载不带 Content-Disposition，省略时浏览器会存成
    // 一串无扩展名的 UUID，导出的包无法再被导入。
    download(res, `${row.nameEn || row.name || row.id}.zip`)
  })
}

function deleteItem (row: any) {
  return {
    id: row.id,
    name: displayName(row),
    meta: row.nameEn || row.module || row.id,
    tag: typeLabel(row)
  }
}

async function deleteClickHandle (row: any) {
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('modules.extendedManagement.resourceOperator'),
    warning: proxy.$t('modules.extendedManagement.deleteWarning'),
    description: proxy.$t('modules.extendedManagement.deleteDescription'),
    items: [deleteItem(row)],
    note: row.visibleRange === PUBLIC ? proxy.$t('modules.extendedManagement.deletePublicNote') : '',
    hint: proxy.$t('modules.extendedManagement.deleteHint')
  });
  if (!confirmed) {
    return;
  }
  try {
    await deleteOperatorApi(row.id);
    selectedMap.delete(row.id);
    proxy.$message.success(proxy.$t('public.deleteSuccess'));
    await refreshAfterDelete(1);
  } catch {
    // 拦截器已提示
  }
}

async function refreshAfterDelete (deletedCount: number) {
  const remaining = Math.max(0, total.value - deletedCount);
  const maxPage = Math.max(1, Math.ceil(remaining / pageSize.value));
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage;
  }
  await loadRows();
}

async function batchOperators (command: string) {
  const targets = [...selectedRows.value];
  if (!targets.length) {
    return;
  }
  if (command === 'delete') {
    const confirmed = await requestDeletion({
      resourceType: proxy.$t('modules.extendedManagement.resourceOperator'),
      title: proxy.$t('modules.extendedManagement.batchDeleteTitle'),
      warning: proxy.$t('modules.extendedManagement.deleteWarning'),
      description: proxy.$t('modules.extendedManagement.deleteDescription'),
      items: targets.map(deleteItem),
      hint: proxy.$t('modules.extendedManagement.deleteHint')
    });
    if (!confirmed) {
      return;
    }
    const results = await Promise.allSettled(targets.map(row => deleteOperatorApi(row.id)));
    const success = results.filter(result => result.status === 'fulfilled').length;
    const failed = targets.length - success;
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        selectedMap.delete(targets[index].id);
      }
    });
    if (success) {
      proxy.$message.success(proxy.$t('modules.extendedManagement.batchUpdated', { count: success }));
    }
    if (failed) {
      proxy.$message.error(proxy.$t('modules.extendedManagement.batchPartial', { success, failed }));
    }
    await refreshAfterDelete(success);
    return;
  }
  const makePublic = command === 'public';
  const targetsToChange = targets.filter(row => (row.visibleRange === PUBLIC) !== makePublic);
  if (!targetsToChange.length) {
    proxy.$message.info(proxy.$t(makePublic
      ? 'modules.extendedManagement.batchPublicSkipped'
      : 'modules.extendedManagement.batchPrivateSkipped'));
    return;
  }
  const results = await Promise.allSettled(targetsToChange.map(row => (makePublic
    ? publicOperatorApi(row.id)
    : unPublicOperatorApi(row.id))));
  const success = results.filter(result => result.status === 'fulfilled').length;
  const failed = targetsToChange.length - success;
  clearSelection();
  if (success) {
    proxy.$message.success(proxy.$t('modules.extendedManagement.batchUpdated', { count: success }));
  }
  if (failed) {
    proxy.$message.error(proxy.$t('modules.extendedManagement.batchPartial', { success, failed }));
  }
  await loadRows();
}

function downloadTemplateClickHandle (operatorType: string) {
  const params = { operatorType }
  exportOperatorTemplateApi(params).then((res: any) => {
    // 模板就是 zip 包；不带扩展名保存会让用户拿到一个无法上传的「文件」。
    download(res, `${operatorType}.zip`);
  })
}

/** 上传成功后回到「我的算子」首屏，并清掉搜索/勾选。 */
function prepareAfterImport () {
  searchKey.value = '';
  clearSelection();
  currentPage.value = 1;
  return loadRows();
}

defineExpose({
  refreshTableData,
  prepareAfterImport
})
</script>

<style scoped>
.operators-page .search-field { width: 360px; }
.operator-table { min-width: 1120px; }
.operator-description { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.operator-table th:nth-child(2) { width: 24%; }
.operator-table th:nth-child(4) { width: 16%; }
.operator-table th:nth-child(5) { width: 15%; }
.operator-dropdown-arrow { width: 12px; height: 12px; }
</style>
