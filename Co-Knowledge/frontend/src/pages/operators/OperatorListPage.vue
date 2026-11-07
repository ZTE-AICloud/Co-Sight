<template>
  <AppPage class="management-page operators-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('modules.extendedManagement.extendedManagement')"
        :subtitle="$t('modules.extendedManagement.pageSubtitle')"
        :icon="PuzzleIcon"
      />
      <el-tabs v-model="tabsValue" @tab-click="tabClickHandle">
        <el-tab-pane :label="$t('modules.extendedManagement.myOperator')" name="myOperator">
          <OperatorTable
            ref="myOperatorRef" :api="queryOperatorListApi"
            :visible-operation="true"
            mode="private"
            :operator-type-list="operatorTypeList"
            @addOperatorHandle="addOperatorHandle"
            @refreshTableData="effectRefreshTableData"
          />
        </el-tab-pane>
        <el-tab-pane :label="$t('modules.extendedManagement.allOperator')" name="allOperator" lazy>
          <OperatorTable
            ref="allOperatorRef"
            :api="queryOperatorListApi"
            :visible-operation="false"
            mode="public"
            :operator-type-list="operatorTypeList"
            @refreshTableData="effectRefreshTableData"
          />
        </el-tab-pane>
      </el-tabs>
      <CreateOperatorDialog ref="createOperatorDialogRef" @refreshTableData="handleOperatorCreated" />
    </div>
  </AppPage>
</template>

<script setup lang="ts">
import { ref, nextTick, getCurrentInstance } from 'vue';
import { queryOperatorListApi, getOperatorTypeApi } from '@/features/operators/api/operator.js';
import OperatorTable from '@/features/operators/OperatorTable.vue';
import CreateOperatorDialog from '@/features/operators/CreateOperatorDialog.vue'
import AppPage from '@/shared/ui/AppPage.vue';
import PageHeader from '@/shared/ui/reference/PageHeader.vue';
import { PuzzleIcon } from '@/shared/ui/icons';


const { proxy } = getCurrentInstance() as any;

const myOperatorRef = ref();
const allOperatorRef = ref();

/** 当前激活的标签页的值 */
const tabsValue = ref('myOperator');

/**
 * 「全部算子」页签是 lazy 的：首次切过去才挂载，由 OperatorTable 自己的 onMounted
 * 取数（EP 之后会缓存页签内容）；只有切回来时才需要手动刷新。
 *
 * visited 用来区分「首次挂载」与「切回来」：首次如果也刷新，会和 onMounted
 * 取数叠成两条相同请求。
 */
const visitedTabs = new Set<string>(['myOperator']);

/**
 * 用事件里的 paneName，不用 tabsValue：`tab-click` 触发时 v-model 可能还没写回，
 * 读 tabsValue 会把「切到新页签」当成「刷新旧页签」，多打一条旧页签的请求。
 */
function tabClickHandle (pane: any) {
  const tab = String(pane?.paneName ?? tabsValue.value);
  if (!visitedTabs.has(tab)) {
    visitedTabs.add(tab);
    return;
  }
  nextTick(() => {
    effectRefreshTableData();
  });
}

function effectRefreshTableData (initPage: string = '') {
  if (Object.is(tabsValue.value, 'myOperator')) {
    myOperatorRef.value?.refreshTableData(initPage);
  } else {
    allOperatorRef.value?.refreshTableData(initPage);
  }
}

const createOperatorDialogRef = ref();
function addOperatorHandle () {
  createOperatorDialogRef.value.openDialog();
}

function handleOperatorCreated () {
  tabsValue.value = 'myOperator';
  nextTick(() => {
    myOperatorRef.value?.prepareAfterImport();
  });
}

const operatorTypeList = ref(new Map([]));

function getOperatorType () {
  getOperatorTypeApi().then((res: any[]) => {
    const operatorTypeListMap = new Map();
    for (let index = 0; index < res.length; index++) {
      const item = res[index];
      item.label = proxy.$globalZh ? item.label_zh : item.label_en;
      operatorTypeListMap.set(item.value, item);
    }
    operatorTypeList.value = operatorTypeListMap;
  })
}
getOperatorType();

</script>
