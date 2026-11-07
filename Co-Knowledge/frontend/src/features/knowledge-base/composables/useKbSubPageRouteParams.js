import { ref, computed } from 'vue';
import { getKnowledgeBaseInfo } from '@/features/knowledge-base/api/knowledgeBase';

/**
 * 使用组合式API获取知识库子页面的路由参数和知识库名称
 * @param proxy - Vue实例的代理对象
 * @returns {Object} - 包含知识库ID、知识库名称和知识库详情的响应式数据
 */
// eslint-disable-next-line no-unused-vars
export function useKbSubPageRouteParams (proxy, callback = _kb => {}) {
  // 计算属性，用于获取当前路由的知识库ID
  const kbId = computed(() => {
    return proxy.$route.params?.id;
  });

  // 响应式变量，用于存储知识库名称
  const kbName = ref('');

  // 响应式变量，用于存储知识库详情
  const kbDetail = ref({});

  /**
   * 异步函数，用于获取知识库名称并更新相应的响应式变量
   */
  async function getKbName () {
    // 调用API获取知识库详情
    kbDetail.value = await getKnowledgeBaseInfo(kbId.value);
    // 从获取到的知识库详情中提取知识库名称
    kbName.value = kbDetail.value?.name;
    updatekBaseName();
    callback(kbDetail.value);
  }
  // 立即执行getKbName函数以初始化知识库名称
  // ⚠️ 必须自己 catch：这里是不带 await 的“发射后不管”，而 getKnowledgeBaseInfo 失败时
  // 拦截器已经弹过一次 toast（base.js 统一提示），再让 rejection 裸奔只会在控制台造出
  // 未处理拒绝（浏览器里表现为 pageerror "Object: Object"）——kb 详情/文件夹/自优化
  // 三个非法 id 页各叠一条，纯噪音，用户可见行为已经是“错误 toast 一次”。吞掉后仍打
  // console.error 保留排查线索。
  getKbName().catch(err => {
    console.error('获取知识库信息失败:', err);
  });

  function updatekBaseName () {
    if (kbName.value !== proxy.$store.state.kbase.kBaseName) {
      proxy.$store.commit('kbase/updatekBaseName', kbName.value);
    }
  }
  // 返回包含知识库ID、知识库名称和知识库详情的响应式数据
  return {
    kbId,
    kbName,
    kbDetail
  };
}
