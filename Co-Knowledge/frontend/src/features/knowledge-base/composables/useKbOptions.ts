import { KB_PUBLISH_STATUS, KB_OPTION_KEY_HYPHEN } from '@/features/knowledge-base/constants.js';
import { getCurrentInstance } from 'vue';
interface KB_OPTION_TYPE {
  value: string;
  label: string;
  status: string;
}

export function useKbOptions () {
  const { proxy } = getCurrentInstance() as any;
  /**
     * 将知识库源选项转换为分组选项。
     * @param sourceOptions 源选项
     * @returns 分组后的选项
     */
  const transKbsToGroupOptions = (sourceOptions: any) => {
    const groupOptions = []
    if (sourceOptions[KB_PUBLISH_STATUS.RUNNING] && sourceOptions[KB_PUBLISH_STATUS.RUNNING].length > 0) {
      const runningOptions: KB_OPTION_TYPE[] = [];
      groupOptions.push({
        label: proxy.$t('prompt.published'),
        options: runningOptions
      })
      for (let option of sourceOptions[KB_PUBLISH_STATUS.RUNNING]) {
        runningOptions.push({
          value: option.tableName,
          label: option.name,
          status: KB_PUBLISH_STATUS.RUNNING
        })
      }
    }
    if (sourceOptions[KB_PUBLISH_STATUS.DEV] && sourceOptions[KB_PUBLISH_STATUS.DEV].length > 0) {
      const unpublishOptions: KB_OPTION_TYPE[] = [];
      groupOptions.push({
        label: proxy.$t('prompt.unPublished'),
        options: unpublishOptions
      })
      for (let option of sourceOptions[KB_PUBLISH_STATUS.DEV]) {
        unpublishOptions.push({
          value: option.tableName + KB_OPTION_KEY_HYPHEN + KB_PUBLISH_STATUS.DEV,
          label: option.name,
          status: KB_PUBLISH_STATUS.DEV
        })
      }
    }
    return groupOptions;
  }

  /**
   * 画布节点的知识库选项（不显示分组标题）：**运行中的 + 开发中的都要**。
   *
   * 只取 `running`（= 已发布到资产中心的知识库）会得到空列表：没有资产中心时
   * 没有东西能把 kb_kbase 的状态推到「已发布」（7），于是 running 恒为空，
   * 检索器/响应合成器节点的知识库下拉恒为空 —— 库选不了，节点就配不出来。
   * 与 CreateWorkflow.vue（新建弹窗）同一处处理：把 dev 一并纳入。
   * 后端在检索时会剥掉 `|#|dev` 后缀，故这里统一按运行中回显，
   * 也保证下面「按名称回显」的 group.status 判断仍然命中。
   * 若将来接入资产中心、恢复「只有已发布才可选」的语义，删掉 dev 那半即可。
   *
   * @param sourceOptions 源选项（allStatusKbase 的 {running, dev}）
   * @returns 扁平化后的选项组；两个分组都为空时返回 []
   */
  const transKbsToPublishedOptions = (sourceOptions: any) => {
    const runningKBs = sourceOptions[KB_PUBLISH_STATUS.RUNNING] || [];
    const devKBs = sourceOptions[KB_PUBLISH_STATUS.DEV] || [];

    const options = [...runningKBs, ...devKBs].map((option: any) => ({
      value: option.tableName,
      label: option.name,
      status: KB_PUBLISH_STATUS.RUNNING
    }));

    if (options.length > 0) {
      return [{
        label: '', // 设置为空字符串，隐藏分组标题
        options
      }];
    } else {
      return [];
    }
  }

  // 同一个知识库只能选中一种状态
  const kbOptionClickHandler = (optionVal:any, selectedKbs:any) => {
    // 选中为空或取消选中时，忽略本方法
    if (!selectedKbs || selectedKbs.length <= 0) {
      return
    }
    if (!selectedKbs.includes(optionVal)) {
      return
    }
    const kbId = optionVal.split(KB_OPTION_KEY_HYPHEN)[0]
    for (let i = 0; i < selectedKbs.length; i++) {
      if (selectedKbs[i].startsWith(kbId)) {
        selectedKbs.splice(i, 1)
        i--;
      }
    }
    selectedKbs.push(optionVal);
  }
  const transGroupOptions = (sourceOptions: any) => {
    const groupOptions = []
    if (sourceOptions[KB_PUBLISH_STATUS.RUNNING] && sourceOptions[KB_PUBLISH_STATUS.RUNNING].length > 0) {
      const runningOptions: KB_OPTION_TYPE[] = [];
      groupOptions.push({
        label: proxy.$t('prompt.published'),
        options: runningOptions
      })
      for (let option of sourceOptions[KB_PUBLISH_STATUS.RUNNING]) {
        runningOptions.push({
          ...option,
          key: `assetId${option.assetId}`,
          status: KB_PUBLISH_STATUS.RUNNING
        })
      }
    }
    if (sourceOptions[KB_PUBLISH_STATUS.DEV] && sourceOptions[KB_PUBLISH_STATUS.DEV].length > 0) {
      const unpublishOptions: KB_OPTION_TYPE[] = [];
      groupOptions.push({
        label: proxy.$t('prompt.unPublished'),
        options: unpublishOptions
      })
      for (let option of sourceOptions[KB_PUBLISH_STATUS.DEV]) {
        unpublishOptions.push({
          ...option,
          key: `kbasePkId${option.kbasePkId}`,
          status: KB_PUBLISH_STATUS.DEV
        })
      }
    }
    return groupOptions;
  }

  const createKbOptionClickHandler = (optionVal:any, selectedKbs:any) => {
    // 选中为空或取消选中时，忽略本方法
    if (!selectedKbs || selectedKbs.length <= 0) {
      return;
    }

    // 使用唯一标识符（tableName）来判断是否为同一个知识库，而不是name
    const optionKey = optionVal.tableName;
    const toBeRemoved = selectedKbs.find((item:any) => item.tableName === optionKey);

    // 如果没有找到相同key的对象，直接返回（说明是新选择的知识库）
    if (!toBeRemoved) {
      return;
    }

    // 只移除相同key的知识库（同一个知识库），允许选择相同name但不同key的知识库
    for (let i = 0; i < selectedKbs.length; i++) {
      if (selectedKbs[i].tableName === optionKey) {
        selectedKbs.splice(i, 1);
        i--;
      }
    }
    selectedKbs.push(optionVal);
  }

  return {
    transKbsToGroupOptions,
    transKbsToPublishedOptions,
    transGroupOptions,
    kbOptionClickHandler,
    createKbOptionClickHandler
  }
}

