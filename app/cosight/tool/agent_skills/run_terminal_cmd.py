import re
import subprocess
import os
from typing import Optional, Dict, Tuple, Any


def parse_command(command_str: str) -> Tuple[Optional[str], str]:
    """
    解析命令字符串，提取工作目录和实际命令。
    支持格式: "cd <workdir> && <command>"

    Args:
        command_str: 命令字符串

    Returns:
        (workdir, command_without_workdir) 元组
    """
    if not command_str:
        return None, ''

    # 匹配 "cd <workdir> && <command>" 格式
    cd_pattern = r'^\s*cd\s+([^\s&]+)\s+&&\s+(.+)$'
    match = re.match(cd_pattern, command_str)

    if match:
        return match.group(1), match.group(2).strip()

    return None, command_str.strip()

def _bash_login_command(command_str: str) -> list[str]:
    """
    使用 bash login shell 执行命令，以尽可能复用用户终端环境（PATH 等）。

    说明：
    - 直接 subprocess.run(..., shell=True) 默认走 /bin/sh -c，不会加载 bash profile
    - openclaw 这类命令常由 ~/.bashrc / ~/.bash_profile / /etc/profile 配置 PATH
    - 使用 `bash -lc` 更贴近用户在终端里的可用环境
    """
    return ["bash", "-lc", command_str]


def append_git_no_pager_if_needed(original_command: str) -> str:
    """
    如果命令包含 git 且没有显式禁用分页，则添加 --no-pager 选项。

    Args:
        original_command: 原始命令字符串

    Returns:
        处理后的命令字符串
    """
    if not original_command or not isinstance(original_command, str):
        return original_command

    original_command = original_command.strip()
    if not original_command:
        return original_command

    # 只匹配命令开头的 git（允许前面有空格）
    # 这样可以避免匹配参数中的 git（如 "echo git"）
    if not re.match(r'^\s*git\b', original_command, re.IGNORECASE):
        return original_command

    # 检查是否已经显式禁用分页
    has_no_pager = re.search(r'\s--no-pager(\s|$)', original_command, re.IGNORECASE)
    has_core_pager_config = re.search(r'\s-c\s+core\.pager=', original_command, re.IGNORECASE)

    if has_no_pager or has_core_pager_config:
        return original_command

    # 只替换开头的 git
    return re.sub(r'^(\s*)git\b', r'\1git --no-pager', original_command, flags=re.IGNORECASE)


def run_terminal_cmd(
        command: str,
        is_background: bool = False,
        explanation: Optional[str] = None
) -> Dict[str, Any]:
    """
    执行终端命令。

    参考 TypeScript 实现的功能：
    - 解析命令中的 cd 和工作目录
    - 为 git 命令自动添加 --no-pager
    - 支持后台任务执行
    - 返回命令输出

    Args:
        command: 要执行的终端命令
        is_background: 是否在后台运行
        explanation: 命令执行原因说明（可选）

    Returns:
        包含执行结果的字典，格式：
        {
            "command": str,      # 实际执行的命令
            "status": str,        # "success" 或 "error"
            "output": str,        # 命令输出
            "workdir": str        # 工作目录
        }
    """
    # 解析命令，提取工作目录
    workdir, command_without_workdir = parse_command(command)

    # 确定工作目录
    if workdir:
        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(workdir):
            # 默认使用当前工作目录
            workdir = os.path.abspath(workdir)
    else:
        # 使用当前工作目录
        workdir = os.getcwd()

    # 确保工作目录存在
    if not os.path.exists(workdir):
        return {
            "command": command_without_workdir,
            "status": "error",
            "output": f"工作目录不存在: {workdir}",
            "workdir": workdir
        }

    # 处理 git 命令，添加 --no-pager
    command_to_execute = append_git_no_pager_if_needed(command_without_workdir)

    try:
        if is_background:
            # 后台执行：使用 Popen 并分离进程
            process = subprocess.Popen(
                _bash_login_command(command_to_execute),
                shell=False,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True  # 创建新的进程组，使其成为后台任务
            )
            # 不等待进程完成，立即返回
            return {
                "command": f"bash -lc {command_to_execute!r}",
                "status": "success",
                "output": f"命令已在后台启动 (PID: {process.pid})",
                "workdir": workdir
            }
        else:
            # 前台执行：等待命令完成并获取输出
            result = subprocess.run(
                _bash_login_command(command_to_execute),
                shell=False,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=600  # 600秒超时
            )

            # 合并 stdout 和 stderr
            output = result.stdout
            if result.stderr:
                output += f"\n{result.stderr}" if output else result.stderr

            status = "success" if result.returncode == 0 else "error"

            return {
                "command": f"bash -lc {command_to_execute!r}",
                "status": status,
                "output": output,
                "workdir": workdir,
                "exit_code": result.returncode
            }

    except subprocess.TimeoutExpired:
        return {
            "command": command_to_execute,
            "status": "error",
            "output": "命令执行超时（超过60秒）",
            "workdir": workdir
        }
    except Exception as e:
        return {
            "command": command_to_execute,
            "status": "error",
            "output": f"命令执行失败: {str(e)}",
            "workdir": workdir
        }
