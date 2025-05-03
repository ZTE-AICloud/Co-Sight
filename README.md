
## 🚀还在为邀请码发愁？一键部署 Co-Sight，快速搭建专属的类Manus系统！

自Manus发布之后，一些闭源平台虽具备优秀的用户体验和商业支持，却常面临高成本、访问受限、私有化部署困难等问题；而开源框架虽拥有更高的灵活性与透明度，却在功能完整性、样式丰富性和稳定性方面略显不足。

**Co-Sight** 致力于在成本、质量、稳定性与易用性之间取得最佳平衡。它支持低成本大模型生成媲美 Claude模型 的高质量、美观报告，并可灵活部署于私有环境，助力企业与个人快速构建属于自己的类Manus系统。

## 🔍样例演示

| 场景       | 示例链接                                                                          | 效果预览                                            |
| -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| **行业研究** | [中兴通讯分析报告](https://www.youtube.com/watch?v=SNd8kYPxr3s)                       | ![](assets/Pasted_image_20250501015026.png)     |
| **个人生活** | [2025年五一上海旅游攻略](https://www.youtube.com/watch?v=IkAGq0e1Lio&feature=youtu.be) | <br>![](assets/Pasted_image_20250501015117.png) |
| **新闻热点** | [特朗普关税政策全球影响分析](https://www.youtube.com/watch?v=19-BmlHuG_E)                  | ![](assets/Pasted_image_20250501015617.png)     |
| **...**  |                                                                               |                                                 |



## 🛠安装指南

1. **下载项目**：你可以选择以下任意一种方式下载项目到本地：
   
   **方式一：使用 Git 克隆**
   访问 https://github.com/ZTE-AICloud/Co-Sight ，点击绿色的 `Code` 按钮，

   ```bash
   # 方式一：选择http协议
   git clone https://github.com/ZTE-AICloud/Co-Sight.git
   
   # 方式二：选择ssh协议
   git clone git@github.com:ZTE-AICloud/Co-Sight.git
   
   cd Co-Sight
   ```

   **方式二：下载 ZIP 文件**
   访问 https://github.com/ZTE-AICloud/Co-Sight ， 点击绿色的 `Code` 按钮，选择 `Download ZIP`，下载后解压并进入项目目录。

2. **准备环境**：python版本>=3.11
  
3. **安装依赖**：  在项目目录下执行以下命令安装依赖
```shell
pip install -r requirements.txt
```



## ⚙️配置说明

1. **拷贝模板`.env_template`并生成 `.env`**（该文件已被加入 `.gitignore`，可安全存储私密信息）：
2. **编辑** `.env` **配置核心参数**：
	1. 大模型配置：配置相对应的大模型地址，模型名称，API-KEY等，可进一步（可选）对规划、执行、工具、多模态模型做配置；
	2. 搜索引擎配置（可选）：配置相关搜索引擎的API-KEY；
		1. Google Search 申请方式：https://developers.google.com/custom-search/v1/overview?hl=zh-cn#api_key
		   ![](assets/Pasted_image_20250502115226.png)	
		2. Tavily Search 申请方式：https://app.tavily.com/home
		   ![](assets/Pasted_image_20250502115315.png)



## ▶️ 快速启动

1. **启动服务**：cosight_server/deep_research/main.py
![](./assets/Pasted_image_20250430225822.png)
2. **打开浏览器，访问：**
`http://localhost:7788/cosight/`
3. **在输入框中输入你的第一个任务，体验智能研究引擎的强大能力！**

![](assets/Pasted_image_20250501020936.png)


## 🐳docker 方式安装&与使用

1. 下载docker离线镜像：
https://github.com/ZTE-AICloud/Co-Sight/releases/download/v0.0.1/co-sight-v001.tar

2. 启动docker镜像：
```shell
# 加载离线镜像
docker load -i co-sight-v001.tar
# 启动docker容器
docker run -d -p 7788:7788 co-sight
# 将配置好的.env文件拷贝进容器（后续会将模型、搜索引擎做到Co-Sight界面可配置方式）
docker cp .env ac39023b3b3fdc3245ec1cc0293afb6b0a5efd4675ee79535ed6663c3e2a2558:/home/Co-Sight
# 重启镜像生效环境变量
docker restart ac39023b3b3fdc3245ec1cc0293afb6b0a5efd4675ee79535ed6663c3e2a2558
```

3. **打开浏览器，访问：**
`http://localhost:7788/cosight/`


## 🤝 贡献指南

非常欢迎 PR、Issue！如果你有任何想法或建议：

- 提交 Issue：描述你的想法与问题。
  
- 发起 PR：完善文档、添加示例或优化功能。
  

一起让 Co Sight Agent 更加强大。