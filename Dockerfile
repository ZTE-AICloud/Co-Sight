# 选择 Python 3.11 官方镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /home/Co-Sight

# 复制当前目录下的所有文件到容器的 /home/Co-Sight 目录中
COPY . /home/Co-Sight

# 赋予 /home/Co-Sight 目录最大权限（包括写入权限）
RUN chmod -R 777 /home/Co-Sight

# 安装项目所需的依赖
RUN pip install --no-cache-dir -r requirements.txt

# 启动服务
CMD ["python", "/home/Co-Sight/cosight_server/deep_research/main.py"]
