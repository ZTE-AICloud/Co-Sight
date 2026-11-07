export function uniqueNameRule(existing, label = '名称', exclude = () => null) {
  return { required: true, trigger: 'blur', validator: (_rule, value, callback) => {
    const name = value?.trim()
    if (!name) {
      callback(new Error(`请输入${label}`))
    } else if (existing().some(item => item !== exclude() && item.name.trim().toLowerCase() === name.toLowerCase())) {
      callback(new Error('此名称已存在，请换一个名称'))
    } else {
      callback()
    }
  } }
}
export function isHttpEndpoint(value) {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !!url.hostname && !url.username && !url.password && !url.hash && !url.search
  } catch {
    return false
  }
}
export const currentLocalTime = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short' }).format(new Date())
export const expiryDateToUTC = date => date ? `${date}T23:59:59.000Z` : null
export const isValidExpiryDate = (value, now = new Date()) => !value || (/^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(expiryDateToUTC(value))) && new Date(expiryDateToUTC(value)).toISOString().slice(0, 10) === value && Date.parse(expiryDateToUTC(value)) > now.getTime())
