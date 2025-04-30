import os
from datetime import datetime

# 获取当前文件所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 获取当前时间并格式化
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

# 构造路径：/xxx/xxx/work_space/work_space_时间戳
WORKSPACE_PATH = os.path.join(BASE_DIR, f'work_space_{timestamp}')
