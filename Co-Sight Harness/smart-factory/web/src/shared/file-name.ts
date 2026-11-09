/**
 * 路径最后一段（文件名）。
 *
 * 端侧形态下附件就是一条本机绝对路径，而它出现在三处：首页发送框、设计页发送框、
 * 对话气泡下方。三处都只该显示文件名、完整路径挂 title —— 规则放在这里，
 * 别每个渲染点各写一份（`/` 与 `\` 都要兼容：同机部署也可能是 Windows）。
 */
export function fileNameOf(path: string): string {
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || path;
}
