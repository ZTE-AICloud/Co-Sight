import { getCustomOperatorListApi } from '@/features/operators/api/operators'; // 导入获取自定义操作符列表的API
import { ref, onMounted } from 'vue'; // 导入Vue的ref和onMounted函数
import { v4 as uuidv4 } from 'uuid'; // 导入uuid库的v4方法，用于生成随机UUID

// 定义一个名为useCustomOperator的函数，该函数接收三个参数：proxy（可能是Vue组件实例的代理对象），props（包含一些属性的对象），type（表示操作符类型的字符串），operatorList（一个包含操作符对象的数组）
export function useCustomOperator (proxy, { props, type, operatorList, showAddOperatorPopover }) {
  const customOperatorList = ref([]); // 创建一个响应式引用，初始值为空数组，用于存储自定义操作符列表

  // 定义一个异步函数，用于从API获取自定义操作符列表
  async function getCustomOperatorList () {
    try {
      const res = await getCustomOperatorListApi(type); // 调用getCustomOperatorListApi函数，传入type参数
      customOperatorList.value = res; // 将API返回的结果赋值给customOperatorList.value
    } catch (error) {
      // Handle error here
      console.error(error); // 如果发生错误，则在控制台打印错误信息
    }
  }

  // 在组件挂载时调用getCustomOperatorList函数
  onMounted(() => {
    getCustomOperatorList();
  })

  // 定义一个函数，用于添加自定义操作符到operatorList中
  function addCustomOperatorWithType (row) {
    // proxy.$refs.operatorPopover.showPopper = false; // 关闭弹出窗口
    showAddOperatorPopover.value = false;
    const newOperatorObj = { // 创建一个新的操作符对象
      id: `${props.nodeId}_${generateRandomUUID()}`, // 生成一个唯一ID，由节点ID和随机UUID组成
      package: row?.position, // 从行数据中获取位置信息
      operator: row?.operator, // 从行数据中获取操作符名称
      kwargs: row?.defaultArgs, // 从行数据中获取默认参数
      showConfig: false, // 设置是否显示配置为false
      operatorName: row?.operatorName, // 从行数据中获取操作符名称
      custom: true // 设置操作符为自定义类型
    }
    operatorList.value.push(newOperatorObj); // 将新操作符对象添加到operatorList中
  };

  // 定义一个函数，用于生成随机的UUID
  function generateRandomUUID () {
    let uuid = uuidv4() // 使用uuid库的v4方法生成UUID
    uuid = uuid.replace(/-/g, '') // 移除UUID中的连字符
    uuid = uuid.substring(0, 3) // 截取UUID的前3位
    return uuid // 返回生成的UUID
  }

  // 返回一个包含addCustomOperatorWithType、generateRandomUUID和customOperatorList的对象
  return {
    addCustomOperatorWithType,
    generateRandomUUID,
    customOperatorList
  }
};
