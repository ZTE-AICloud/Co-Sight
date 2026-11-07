import axios from '@/shared/api/client'

const KBASE_BASE = process.env.VUE_APP_KBASE_BASE

// 获取自定义算子列表（按环节）
export function getCustomOperatorListApi (type) {
  return axios.get(`${KBASE_BASE}/operators/supported`, {
    params: { module: type }
  })
}
