"""kb_api 的中英文案。

与 ``workflow.messages`` 同一套规则与同一份语言归一化逻辑：``render`` 用
``str.format`` 风格，占位符写成 ``{0}``、``{1}``。

**与 flow_api 重复的两个键（``server.error`` / ``request.invalid``）文本保持一致** ——
文案是对外契约的一部分，两个接口族对同一类失败给出不同提示会让排障对不上日志。
"""

from __future__ import annotations

# key -> {语言: 文案}
MESSAGES = {
    'server.error': {
        'zh': '服务器内部错误，请稍后重试',
        'en': 'Internal server error, please try again later',
    },
    'request.invalid': {
        'zh': '请求体不合法，请检查参数后重试',
        'en': 'The request body is invalid; check the parameters and retry',
    },
    # 请求体解析失败 / 缺必填 query 参数 / 缺 path 变量统一用 ``RetCode.illegalArgument``。
    # **不要用 ``request.invalid`` 顶替它** —— 两条文案不同。
    'RetCode.illegalArgument': {
        'zh': '参数不合法，请检查后重试',
        'en': 'Argument is illegal, please check and retry.',
    },
    # 文案是对外契约的一部分：前端直接弹给用户，改字会让同一功能出现两种提示。
    'kbase.not.exist': {
        'zh': '知识库不存在',
        'en': 'Knowledge base not exist',
    },
    'kbase.can.not.delete.include.knowledge': {
        'zh': '无法删除知识库：知识库包含其他知识',
        'en': 'Cannot delete knowledge base: knowledge base includes other knowledge.',
    },
    # 建库/目录域。
    # ⚠️ en 文案与 zh **完全不是一句话**（"Knowledge base exist"）。
    # 这种英文是另写短句的键不要顺手翻译 zh 那句。
    'kbase.exist': {
        'zh': '该名称已存在，请修改名称后重试！',
        'en': 'Knowledge base exist',
    },
    # 英文请求也回这句中文 —— en 写中文不是笔误。
    'kbase.name.lock.timeout': {
        'zh': '知识库名称检查繁忙，请稍后重试',
        'en': '知识库名称检查繁忙，请稍后重试',
    },
    'kbase.name.validation': {
        'zh': "知识库名称长度必须在2-30之间，且只支持英文、数字、下划线'_'、中文、英文点'.'、"
              "英文横线'-'和空格，但不能全为空格",
        'en': "Knowledge base must be between 2 and 30, and only supports English, numbers, "
              "underscores '_', Chinese, English dots '.', English dashes '-', and spaces, "
              "but cannot be all spaces",
    },
    # 这两条是 ``@Size`` 的校验文案，跟请求语言走。
    'description.validation': {
        'zh': '描述的长度不能超过1000',
        'en': 'The length of the description cannot exceed 1000',
    },
    'headIcon.validation': {
        'zh': '图标名称的长度不能超过255',
        'en': 'The length of the headIcon cannot exceed 255',
    },
    # ``/directory/getNameById`` 用它兜住**所有**入参不合规的情况（type 不在白名单、
    # ids 为 null、某个 item 缺 id/kbaseId）。
    # ``GET /kbase/{id}`` 上挂了**业务级**权限校验，所以库不存在时回的是这句，
    # 而**不是**「知识库不存在」。两条别混。
    'permission.denied': {
        'zh': '没有权限或已被删除',
        'en': 'No permission or has been deleted',
    },
    'knowledgeVector.format.incorrect': {
        'zh': '知识向量格式不正确',
        'en': 'Knowledge vector format is incorrent.',
    },
    # 删图谱库那条路用的三条。注意 ``en`` 里 ``knowleage`` 是拼写错误，
    # 必须保持原样，不能改。
    # 图谱导出。``schema.not.found`` 的文案是**单数**「Schema不存在」，
    # 与别处的「知识库不存在」不是一套，保持原样。
    'graph.export.kbase.not.found': {
        'zh': '知识库不存在',
        'en': 'Knowledge base not found',
    },
    'graph.export.kbase.not.graph': {
        'zh': '知识库不是图谱类型',
        'en': 'Knowledge base is not a graph type',
    },
    'graph.export.schema.not.found': {
        'zh': 'Schema不存在',
        'en': 'Schema not found',
    },
    'graph.export.failed': {
        'zh': '导出失败',
        'en': 'Export failed',
    },
    # 抽图任务查询（v1 与 v2 共用同一套键）。
    # 图谱导入（``/graph/import``）。
    # ⚠️ ``Retcode.graph.import.illegal`` / ``.fail`` 的 ``Retcode`` 是**小写 c**，
    # 与全文其它键不一样，别改名。
    # ⚠️ 三条 id 格式校验登记在 ``BASE_ABSENT_KEYS``（base 包没有）。``*`` 请求
    # 落到 base 包时，结果是 0005 + ``Retcode.graph.import.fail`` —— **不是** 0001；
    # 对应 ``graph_import_api.import_graph`` 的处理。
    'Retcode.graph.import.illegal': {
        'zh': '知识图谱导入文件不合法',
        'en': 'Import graph knowledge base invalid',
    },
    'Retcode.graph.import.fail': {
        'zh': '知识图谱导入失败',
        'en': 'Import graph knowledge base failed',
    },
    'graph.import.id.format.invalid.prefix': {
        'zh': 'id字段格式不正确：必须以"graph_"开头',
        'en': 'id field format is incorrect: must start with "graph_"',
    },
    'graph.import.id.format.invalid.length': {
        'zh': 'id字段格式不正确："graph_"后面的字符串长度必须为16或32位，当前长度{0}',
        'en': 'id field format is incorrect: the string after "graph_" must be 16 or 32 '
              'characters long, current length {0}',
    },
    'graph.import.id.format.invalid.char': {
        'zh': 'id字段格式不正确："graph_"后面只能包含十六进制字符（0-9, a-f, A-F），发现非法字符{0}',
        'en': 'id field format is incorrect: only hexadecimal characters (0-9, a-f, A-F) '
              'are allowed after "graph_", found invalid character {0}',
    },
    'graph.import.entities.file.required': {
        'zh': '缺少必需文件entities.jsonl，请确保该文件位于ZIP根目录下',
        'en': 'Missing required file entities.jsonl, please ensure it is in the ZIP root directory',
    },
    'graph.import.edges.file.required': {
        'zh': '缺少必需文件edges.jsonl，请确保该文件位于ZIP根目录下',
        'en': 'Missing required file edges.jsonl, please ensure it is in the ZIP root directory',
    },
    'file.size.limit.check': {
        'zh': '文件大小超过{0}MB上限，无法上传',
        'en': 'The uploaded file size exceeds the upper limit of {0}MB and cannot be uploaded.',
    },
    'zip.decompress.error': {
        'zh': '解压缩失败',
        'en': 'Decompression failed',
    },
    # 抽图端点（``/graph/extract``）。
    # 这一族**全是 0004**，不是业务异常那套 0005。唯一例外是文件落盘失败（→ 0001）。
    'graph.extract.json.parse.failed': {
        'zh': '图提取请求参数JSON格式错误，请检查后重试',
        'en': 'Graph extract request parameter JSON format error, please check and retry',
    },
    'graph.extract.schema.not.found': {
        'zh': 'Schema未找到，Schema ID：{0}',
        'en': 'Schema not found, Schema ID: {0}',
    },
    'graph.extract.kbid.length.exceed': {
        'zh': '知识库ID长度不能超过100个字符，当前长度：{0}',
        'en': 'Knowledge base ID length cannot exceed 100 characters, current length: {0}',
    },
    'graph.extract.operatorid.length.exceed': {
        'zh': '算子ID长度不能超过10个字符，当前长度：{0}',
        'en': 'Operator ID length cannot exceed 10 characters, current length: {0}',
    },
    'graph.extract.operatorid.not.exist': {
        'zh': '算子不存在，算子ID：{0}',
        'en': 'Operator not found, operator ID: {0}',
    },
    'graph.extract.task.not.exist': {
        'zh': '任务不存在，任务ID：{0}',
        'en': 'Task not found with ID: {0}',
    },
    'graph.extract.taskid.empty': {
        'zh': '任务ID不能为空',
        'en': 'Task ID cannot be empty',
    },
    'graph.extract.taskid.length.exceed': {
        'zh': '任务ID长度不能超过50个字符，当前长度：{0}',
        'en': 'Task ID length cannot exceed 50 characters, current length: {0}',
    },
    'graph.extract.kbid.not.exist': {
        'zh': '知识库不存在，知识库ID：{0}',
        'en': 'Knowledge base not found, knowledge base ID: {0}',
    },
    # v2 建库/抽图那条链上**多出来**的几条。
    # ``graph.extract.chunkSize.invalid`` / ``.overlap.invalid`` 刻意**不补** ——
    # 传非数字的 chunkSize / overlap 时，取文案这一步自己抛异常 → 0001。
    'graph.extract.operatorid.empty': {
        'zh': '操作算子不能为空',
        'en': 'Operator ID cannot be empty',
    },
    'graph.extract.chunkSize.range.invalid': {
        'zh': '切片大小不合法，必须在[512, 10240]范围内，当前值：{0}',
        'en': 'Invalid chunk size, must be in range [512, 10240], current value: {0}',
    },
    'graph.extract.overlap.range.invalid': {
        'zh': '重叠大小不合法，必须在[0, 5120]范围内，当前值：{0}',
        'en': 'Invalid overlap, must be in range [0, 5120], current value: {0}',
    },
    'graph.extract.llm.invalid': {
        'zh': '大模型不合法，大模型：{0}',
        'en': 'Invalid LLM model: {0}',
    },
    'graph.extract.embedding.model.invalid': {
        'zh': '嵌入模型不合法，嵌入模型：{0}',
        'en': 'Invalid embedding model: {0}',
    },
    'kbase.embedding.model.invalid': {
        # 建库/建图前校验：名字解析不到时写路径会**静默换成** .env 的默认模型，
        # 记录与库里的向量就分家了。
        'zh': '嵌入模型 {0} 未在模型注册表中配置（或缺少向量维度），'
              '继续建库会让记录与库里的向量对不上，请重新选择',
        'en': 'Embedding model {0} is not configured in the model registry '
              '(or has no vector dimension); the knowledge base record would disagree '
              'with the stored vectors; pick another model',
    },
    # 评测指标下拉框的标签（value 同时用作 i18n 键）。
    # ⚠️ 只有 zh 有译文：**en/其它语言回落到键名本身**（如 ``faithfulness``），
    # 所以这里也不要补 en。
    'faithfulness': {
        'zh': '忠实性',
    },
    'answer_relevancy': {
        'zh': '答案相关性',
    },
    'answer_similarity': {
        'zh': '答案相似性',
    },
    'answer_correctness': {
        'zh': '答案正确性',
    },
    'context_precision': {
        'zh': '上下文精确度',
    },
    'context_recall': {
        'zh': '上下文召回率',
    },
    'answer_recall': {
        'zh': '答案召回率',
    },
    'answer_precision': {
        'zh': '答案精确度',
    },
    'RetCode.dataSet.not.exist': {
        'zh': '数据集不存在',
        'en': 'dataSet not exist',
    },
    'kbase.prop.validation': {
        'zh': '知识库Embedding模型不能为空',
        'en': 'The knowledge base embedding model cannot be empty',
    },
    'Retcode.generate.graph.schema.fail': {
        'zh': '生成图谱失败，请稍后再试',
        'en': 'Generate graph schema fail, please try again later',
    },
    # ``FileValidate.fileUploadCheck`` 那一族的文案（``/file/upload`` 与抽图建库都用）。
    # ``UploadFileDTO`` 的 bean-validation 失败时，处理器把**原始 violation 文案**
    # 塞进这个包装里；那些注解里写的是 ``{RetCode.upload.directoryId.check}`` 这种
    # **没有对应 properties 的键**，所以线上看到的是**未解析的花括号原文**。
    'RetCode.upload.json.incorrect': {
        'zh': '上传文件参数报错{0}',
        'en': 'upload file params incorrect{0}',
    },
    'RetCode.split.select.error': {
        'zh': '切分算子选择错误',
        'en': 'split operator select error',
    },
    'RetCode.file.count.limit': {
        'zh': '上传文件个数超过限制，请修改后重试！',
        'en': 'The number of uploaded files exceeds the limit. Please modify and try again!',
    },
    'RetCode.upload.file.rename': {
        'zh': '上传的文件列表中存在重名文件，请删除重名文件后重试！',
        'en': 'There are duplicate files in the uploaded file list. '
              'Please delete the duplicate files and try again!',
    },
    'RetCode.file.size.limit.check': {
        'zh': '文件大小超过{0}MB上限，无法上传',
        'en': 'The uploaded file size exceeds the upper limit of {0}MB and cannot be uploaded.',
    },
    'file.name.length.check': {
        'zh': '文件名长度不能超过150字符',
        'en': 'File name length cannot exceed 150 characters',
    },
    'file.encrypted.check': {
        'zh': '文件{0}已加密，需解密',
        'en': 'Files [{0}] are encrypted and need to be decrypted',
    },
    'kbase.delete.fail': {
        'zh': '知识库删除失败：{0}',
        'en': 'Delete knowleage base failed: {0}',
    },
    'kbase.bound.by.workflow': {
        'zh': '当前知识库在知识检索：{0} 中使用，无法删除',
        'en': 'The current knowledge base is used in Knowledge Retrieval:{0} and cannot be deleted',
    },
    'kbase.name.not.all.whitespace': {
        'zh': '知识库名称不能全为空格',
        'en': 'Knowledge base name cannot be all spaces',
    },
    'directory.folder.size.over.limit': {
        'zh': '文件夹个数超出限制',
        'en': 'upload folder size over limit',
    },
    'directory.level.limit': {
        'zh': '文件夹层级超过限制，最大层级: {0}',
        'en': 'The folder directory exceeds the limit, maximum level: {0}',
    },
    'directory.already.exist': {
        'zh': '文件夹: {0} 在同级目录下已存在，请更改名称后重试！',
        'en': 'Directory: {0} already exists in the same level directory. '
              'Please change the name and try again!',
    },
    'directory.not.exist': {
        'zh': '目录不存在',
        'en': 'directory not exist',
    },
    'directory.title.validation': {
        'zh': '标题长度必须在2-30之间，且必须包含非空格的字符',
        'en': 'Title must be between 2 and 30 characters, and must contain non-space characters',
    },
    # 文件域。
    'file.save.error': {
        'zh': '文件保存失败',
        'en': 'File save failed',
    },
    'file.not.exist': {
        'zh': '文件(夹)不存在',
        'en': 'The file (directory) does not exist',
    },
    # 与上面 ``file.not.exist`` 是同一个键的两个写法，文本相同。
    # chunk 域（``chunk_service._file_or_raise``）用带前缀的 ``RetCode.file.not.exist``。
    'RetCode.file.not.exist': {
        'zh': '文件(夹)不存在',
        'en': 'The file (directory) does not exist',
    },
    'file.upload.empty.error': {
        'zh': '文件上传失败，{0}内容不能为空',
        'en': 'File upload failed, {0} empty file',
    },
    'file.type.validation': {
        'zh': '上传文件类型不支持',
        'en': 'Upload file type is not supported',
    },
    # 只看后缀会把 exe 改名 .pdf 也收进来。
    'file.content.type.mismatch': {
        'zh': '文件内容与扩展名不符，请确认文件未被改名后重新上传',
        'en': 'The file content does not match its extension. Make sure the file was not renamed, then retry.',
    },
    # 这条的中文末尾带一个多余的引号 `”`、英文末尾带一个 `"` —— 必须保持原样
    # （文案是对外契约的一部分）。
    'kbase.file.count.exceed': {
        'zh': '知识库当前文件数为{0}，本操作将新增{1}，超过知识库允许的最大文件{2}，'
              '请移除不需要的文件后重试”',
        'en': 'The current number of files in the knowledge base is {0}, this operation will '
              'add a new {1}, which exceeds the maximum file {2} allowed by the knowledge base, '
              'please remove the unnecessary files and try again"',
    },
    # 导入链失败时写进 kb_directory.fail_reason 的键，再由 setFailReason 本地化成 errorMsg。
    'RetCode.operator.split.error': {
        'zh': '切分算子执行失败，请检查算子是否存在问题',
        'en': 'splitting operator execution failed, please check if there is a problem '
              'with the operator',
    },
    # 大文件（>50MB）同一时刻只允许一个切分：后来的排队等待，等到超时才落这个键。
    # 不是「文件太大」—— 上传上限另有一套（pdf 150MB / md、docx 100MB）。
    'RetCode.file.size.more': {
        'zh': '当前已有大文件正在处理，请稍后重试',
        'en': 'Another large file is being processed. Please retry later.',
    },
    'RetCode.chunk.size.more': {
        'zh': '切分出的分块数量超过限制，请调整切分参数后重试',
        'en': 'The number of chunks exceeds the limit. Adjust the split settings and retry.',
    },
    # 手工重试的闸门：只有「解析失败」的文档能重试。
    'file.retry.not.allowed': {
        'zh': '只有解析失败的文档可以重试',
        'en': 'Only documents that failed to parse can be retried',
    },
    # ⚠️ 这条用于「解析成功但没有文本」，不要复用上面那条 split.error ——
    # 把「文件里没有可提取文本」说成「切分算子有问题」，用户按提示去检查算子会徒劳。
    # 典型场景：GoAccess 的 report.html（正文全在 ``<script>var json_data=…`` 里，
    # 静态 DOM 只剩空壳）。
    'RetCode.operator.split.empty': {
        'zh': '文件未能解析出文本内容，请确认文件含可提取文本（扫描件、纯图片或需浏览器'
              '渲染的网页请先转换格式后重试）',
        'en': 'No text content could be extracted from the file. If it is a scanned image, '
              'a pure-image file, or a page that requires a browser to render, convert it '
              'to a text-based format and retry.',
    },
    # 为「这个格式没有解析器」而设，不要落到 split.error（"切分算子执行失败"）。
    # 命中的是 OFD / zip 这些在界面里被列为「支持」但后端没有解析实现的格式。
    'RetCode.operator.split.unsupported': {
        'zh': '暂不支持解析该格式的文件，目前可解析：PDF、Word、PPT、Excel、CSV、'
              'Markdown、TXT、HTML；OFD 等其它格式请先转换后重试',
        'en': 'This file format cannot be parsed yet. Supported formats: PDF, Word, PPT, '
              'Excel, CSV, Markdown, TXT and HTML. Convert other formats (e.g. OFD) and retry.',
    },
    # 为「文件本身损坏/不完整」而设。截断的 docx 会被 python-docx 报
    # "Package not found"，不应落到 split.error（界面提示「请检查算子是否存在问题」）——
    # 真正该查的是上传的文件。
    'RetCode.operator.split.corrupt': {
        'zh': '文件已损坏或不完整，无法解析，请重新获取完整文件后上传',
        'en': 'The file is corrupted or incomplete and cannot be parsed. Obtain a complete '
              'copy of the file and upload it again.',
    },
    'RetCode.file.parse.error': {
        'zh': '文件解析失败',
        'en': 'File parsing failed',
    },
    'RetCode.database.updateOrInsertException': {
        'zh': '插入或更新数据库异常',
        'en': 'Insert or update database exception.',
    },
    'RetCode.operator.notfound': {
        'zh': '算子未找到',
        'en': 'Operator not found',
    },
    # 「目标状态已经是当前状态」时的重复操作提示。
    # 三个语言包都有；en 不是中文直译，是另写的整句。
    'RetCode.operator.publish.repeat': {
        'zh': '算子已发布，不能再次发布',
        'en': 'Operator has been published and cannot publish again.',
    },
    'RetCode.file.preview.error': {
        'zh': '文件预览失败',
        'en': 'file preview error',
    },
    # 切片更新失败。键名里的 ``Recode``（不是 ``RetCode``）是拼写笔误，
    # 必须保持原样，不能改。
    'Recode.chunk.update.error': {
        'zh': '切片更新失败',
        'en': 'chunk update error',
    },
    # 同名文件的覆盖询问文案（lang 键是 file.upload.rename，**不是** RetCode.* 前缀）。
    # 它对应的业务码是 1001（SysGlobalConst.FILE_RENAME_ERROR_CODE），不是标准的 000x 系列。
    'file.upload.rename': {
        'zh': '已选择文件与当前文件夹下的文件重名，重名文件：{0}，是否覆盖更新文件？',
        'en': 'The selected file has the same name as the file in the current folder. '
              'File with the same name: {0}. Do you want to overwrite the updated file?',
    },
    # 检索入参校验。
    # 这些 message 是**内联英文字面量**（不是 i18n 键），所以中英文渲染出的是
    # 同一句话 —— 两个语言给同一份文本，别「顺手翻译」。
    'retrieve.question.required': {
        'zh': 'Question cannot be null or empty',
        'en': 'Question cannot be null or empty',
    },
    # ``@NotNull(message="Type cannot be null")`` 与 ``@Min/@Max`` 是**两条**，
    # 所以「传 null」和「传 5」文案不同：前者是 Type cannot be null，后者是 Type must be 0 or 1。
    'retrieve.type.null': {
        'zh': 'Type cannot be null',
        'en': 'Type cannot be null',
    },
    'retrieve.type.invalid': {
        'zh': 'Type must be 0 or 1',
        'en': 'Type must be 0 or 1',
    },
    # @NotNull 与 @NotEmpty 是两条不同的约束、两条不同的文案，别合并
    'retrieve.bases.null': {
        'zh': 'Bases cannot be null',
        'en': 'Bases cannot be null',
    },
    'retrieve.bases.empty': {
        'zh': 'Bases cannot be empty',
        'en': 'Bases cannot be empty',
    },
    'retrieve.baseList.null': {
        'zh': 'BaseList cannot be null',
        'en': 'BaseList cannot be null',
    },
    'retrieve.baseList.empty': {
        'zh': 'BaseList cannot be empty',
        'en': 'BaseList cannot be empty',
    },
    'retrieve.priority.outOfRange': {
        'zh': 'Priority must be between 0 and 10',
        'en': 'Priority must be between 0 and 10',
    },
    'retrieve.topK.outOfRange': {
        'zh': 'TopK must be between 1 and 80',
        'en': 'TopK must be between 1 and 80',
    },
    'retrieve.scoreThreshold.outOfRange': {
        'zh': 'Score threshold must be between 0.0 and 1.0',
        'en': 'Score threshold must be between 0.0 and 1.0',
    },
    'RetCode.zip.decompress.error': {
        'zh': '解压缩失败',
        'en': 'Decompression failed',
    },
    'RetCode.operator.type.incorrect': {
        'zh': '上传文件格式不正确，仅支持zip格式上传',
        'en': 'The uploaded file format is incorrect, only zip format is supported for uploading',
    },
    'RetCode.operator.workflow.import.sizecheck': {
        'zh': '知识检索算子大小应限制在{0}以内',
        'en': 'The size of the knowledge retrieval operator package should be limited under {0}.',
    },
    'RetCode.operator.configjson.notfound': {
        'zh': '导入的自定义算子中没有找到config.json文件',
        'en': 'The config.json file was not found in the imported custom operator.',
    },
    'RetCode.operator.module.check.notblank': {
        'zh': 'module 为空',
        'en': 'module.check.notblank',
    },
    'RetCode.operator.type.not.support': {
        'zh': '算子类型不支持',
        'en': 'operator type does not support',
    },
    'RetCode.operator.configjson.configuration.incorrect': {
        'zh': 'config.json配置不正确：{0}',
        'en': 'config.json was not configured correctly: {0}',
    },
    'RetCode.operator.arg.name.incorrect': {
        'zh': '算子参数名称不允许相同',
        'en': 'Operator parameter names cannot be the same',
    },
    'RetCode.operator.arg.type.incorrect': {
        'zh': '算子参数类型不正确,只支持int、str、bool三种类型',
        'en': 'The operator parameter type is incorrect and only supports three types: int, str, and bool',
    },
    'RetCode.operator.arg.defaultValue.incorrect': {
        'zh': 'defaultArgs中argType与defaultValue参数值存在类型不匹配',
        'en': 'The argType in the defaultArgs does not correspond to the type of defaultValue',
    },
    # ⚠️ 这个键在 en_US 表里被拼错成 `...incorrct`、基础包里也没有 —— 所以英文请求
    # 走到这里时找不到文案，包成 0005，**把异常自己的消息当文案吐出来**。
    # en 这里就是那句泄漏文本。
    'RetCode.operator.arg.visibleRange.incorrect': {
        'zh': '算子可见范围visibleRange参数只允许为private或者public',
        'en': "No message found under code 'RetCode.operator.arg.visibleRange.incorrect' "
              "for locale 'en_US'.",
    },
    'RetCode.operator.python.not.found': {
        'zh': '算子包未包含python文件',
        'en': 'The operator package does not include a Python file',
    },
    'RetCode.operator.python.exist.more': {
        'zh': 'python文件存在多份',
        'en': 'There are multiple copies of Python files',
    },
    'RetCode.operator.storage.insufficient': {
        'zh': '存储空间不足，无法保存算子文件。',
        'en': 'Insufficient storage space, unable to save operator file.',
    },
    'operator.plugin.incompatible': {
        'zh': '该算子使用了不支持的插件接口（client.* / utility.* 等），当前版本无法运行；'
              '请下载最新算子模板并重新导出。',
        'en': 'This operator uses an unsupported plugin API (client.* / utility.*); '
              'download the current operator template and re-export it.',
    },
    'RetCode.operator.textsplit.code.checkNotPass': {
        'zh': '自定义算子内容校验不通过。',
        'en': 'Custom operator content validation failed.',
    },
    'RetCode.operator.name.check.notblank': {
        'zh': '算子中文名和英文名不能为空',
        'en': 'Operator display_name zh and display_name en cannot be empty',
    },
    'RetCode.operator.name.invalid.cn': {
        'zh': '算子的name字段只允许汉字、英文、数字、下划线。',
        'en': 'The "name" field of the operator only allows Chinese characters, English letters, digits, and underscores.',
    },
    'RetCode.operator.name.invalid.en': {
        'zh': '算子的nameEn字段只允许英文、数字、下划线。',
        'en': 'The "nameEn" field of the operator only allows English letters, digits, and underscores.',
    },
    'RetCode.operator.name.duplicate': {
        'zh': '系统中已存在该算子名称，请修改后重新上传。',
        'en': 'The operator name already exists in the system. Please modify it and upload it again.',
    },
    'RetCode.operator.description.check.notblank': {
        'zh': '算子中文描述或英文描述不能为空',
        'en': 'Operator description zh or description en cannot be empty',
    },
    'RetCode.operator.description.check': {
        'zh': '算子描述（中文和英文）长度应不超过5000字符',
        'en': 'Length of operator description (both Chinese and English) should not exceed 5000 characters',
    },
    'RetCode.operator.visibleRange.check.notnull': {
        'zh': '算子可见范围不能为空',
        'en': 'Operator visible range cannot be null',
    },
    'RetCode.operator.versionUser.check.notblank': {
        'zh': '算子版本号不能为空',
        'en': 'Operator version cannot be blank',
    },
    'RetCode.operator.versionUser.check.regex': {
        # ⚠️ 这里**没有反斜杠**不是笔误：properties 文件里写的是 `\d` / `\.`，而
        # 对「不认识的转义」是**把反斜杠丢掉、保留后一个字符**
        # （只认 \uXXXX \n \t \r \f \\）。线上吐出来的就是这个样子。
        'zh': '算子版本号未通过正则校验，应满足"^(?=.{1,32}$)([1-9][d]*)(.(d|[1-9][d]*)){2}$"',
        'en': 'Operator version does not pass the regex check, shold fit "^(?=.{1,32}$)([1-9][d]*)(.(d|[1-9][d]*)){2}$"',
    },
    'RetCode.operator.displayName.check.notblank': {
        'zh': 'displayName 为空',
        'en': 'displayName notblank',
    },
    'RetCode.operator.desc.check.notblank': {
        'zh': 'desc 为空',
        'en': 'desc.check.notblank',
    },
    'RetCode.operator.defaultArgs.check.not.blank': {
        'zh': 'defaultArgs为空',
        'en': 'defaultArgs not blank',
    },
    'RetCode.operator.published.check.notnull': {
        'zh': 'isPublished为空',
        'en': 'isPublished not blank',
    },
    'RetCode.operator.displayname.zh.notblank': {
        'zh': 'display_name 为空',
        'en': 'displayname.zh.notblank',
    },
    'RetCode.operator.name.check.len': {
        'zh': '算子名称（中文和英文）长度应不超过50字符',
        'en': 'Length of operator name (both Chinese and English) should not exceed 50 characters',
    },
    'RetCode.operator.desc.zh.notblank': {
        'zh': 'desc 为空',
        'en': 'desc.zh.notblank',
    },
    'RetCode.operator.supportedFormat.check': {
        'zh': '支持的文件类型不应为空',
        'en': 'SupportedFormat should not be null or empty',
    },
    'RetCode.operator.operator.check.notblank': {
        'zh': 'operator 为空',
        'en': 'operator.check.notblank',
    },
    'RetCode.operator.position.check.notblank': {
        'zh': 'position 为空',
        'en': 'position.check.notblank',
    },
    # ---- 图谱模板域（B3-a）---------------------------------------------
    'Recode.asset.permission.not.allow': {
        'zh': '当前用户没有操作权限',
        'en': 'The current user does not have operational permissions',
    },
    'RetCode.graph.extract.schema.not.found': {
        'zh': 'Schema未找到，Schema ID：{0}',
        'en': 'Schema not found, Schema ID: {0}',
    },
    'RetCode.graph.schema.delete.success': {
        'zh': '知识图谱模板删除成功：{0}',
        'en': 'Schema {0} has been successfully deleted',
    },
    'RetCode.graph.schema.desc.invalid.chars': {
        'zh': '描述不能为全空格或空白字符',
        'en': 'Description cannot be all whitespace or blank characters',
    },
    'RetCode.graph.schema.desc.invalid.length': {
        'zh': '描述长度不合法：当前长度为{0}，需要在1-1000之间',
        'en': 'Description length is invalid: current length is {0}, required range is 1-1000',
    },
    'RetCode.graph.schema.desc.null': {
        'zh': '知识图谱模板、实体或边的描述信息不能为空',
        'en': 'Description of graph schema template, entity, or edge cannot be empty',
    },
    'RetCode.graph.schema.edge.duplicate.type': {
        'zh': '边类型重复：{0}',
        'en': 'Duplicate edge type: {0}',
    },
    'RetCode.graph.schema.edge.entity.not.found': {
        'zh': '边的源实体类型或目标实体类型未在实体列表中定义，源实体：{0}，目标实体：{1}',
        'en': 'Edge source entity type or target entity type not defined in entity list, source entity: {0}, target entity: {1}',
    },
    'RetCode.graph.schema.edge.property.duplicate.name': {
        'zh': '边属性名称重复：{0}，边类型：{1}',
        'en': 'Duplicate edge property name: {0}, edge type: {1}',
    },
    'RetCode.graph.schema.entities.duplicate.entity_type': {
        'zh': '实体类型重复：{0}',
        'en': 'Duplicate entity type: {0}',
    },
    'RetCode.graph.schema.entities.not.empty': {
        'zh': '实体列表不能为空',
        'en': 'Entity list cannot be empty',
    },
    'RetCode.graph.schema.entity.property.duplicate.name': {
        'zh': '实体属性名称重复：{0}，实体类型：{1}',
        'en': 'Duplicate entity property name: {0}, entity type: {1}',
    },
    'RetCode.graph.schema.entity.property.name.invalid.chars_or_start': {
        'zh': '实体属性名称格式不合法：必须以字母开头，仅允许字母、数字和下划线',
        'en': 'Entity property name format is invalid: must start with letter, only letters, numbers and underscores allowed',
    },
    'RetCode.graph.schema.entity.property.name.invalid.length': {
        'zh': '实体属性名称长度不合法：当前长度为{0}，需要在1-63之间',
        'en': 'Entity property name length is invalid: current length is {0}, required range is 1-63',
    },
    'RetCode.graph.schema.entity.property.name.null': {
        'zh': '实体属性名称不能为空',
        'en': 'Entity property name cannot be null',
    },
    'RetCode.graph.schema.entity.property.name.reserved': {
        'zh': '实体属性名称不能为SQL保留关键字：{0}',
        'en': 'Entity property name cannot be SQL reserved keyword: {0}',
    },
    'RetCode.graph.schema.entity.property.not.empty': {
        'zh': '实体属性列表不能为空，实体类型：{0}',
        'en': 'Entity property list cannot be empty, entity type: {0}',
    },
    'RetCode.graph.schema.entity.property.primary.not.found': {
        'zh': '实体必须至少有一个主键属性，实体类型：{0}',
        'en': 'Entity must have at least one primary property, entity type: {0}',
    },
    'RetCode.graph.schema.entity.property.type.invalid': {
        'zh': '实体属性类型不合法：{0}，请使用合法的类型值',
        'en': 'Entity property type is invalid: {0}, please use a valid type value',
    },
    'RetCode.graph.schema.entity.property.type.null': {
        'zh': '实体属性类型不能为空',
        'en': 'Entity property type cannot be null',
    },
    'RetCode.graph.schema.entity_type.invalid.chars_or_start': {
        'zh': '实体类型格式不合法：{0}，首字母必须为字母（A-Z 或 a-z），仅允许英文字母',
        'en': 'Entity type format is invalid: {0}, must start with a letter (A-Z or a-z), only English letters',
    },
    'RetCode.graph.schema.entity_type.invalid.length': {
        'zh': '实体类型长度不合法：当前长度为{0}，需要在1-63之间',
        'en': 'Entity type length is invalid: current length is {0}, required range is 1-63',
    },
    'RetCode.graph.schema.entity_type.null': {
        'zh': '实体类型不能为空',
        'en': 'Entity type cannot be null',
    },
    'RetCode.graph.schema.entity_type.reserved': {
        'zh': '实体类型不能为保留关键字：{0}',
        'en': 'Entity type cannot be reserved keyword: {0}',
    },
    'RetCode.graph.schema.id.required': {
        'zh': '知识图谱模板ID不能为空',
        'en': 'Schema ID cannot be empty',
    },
    'RetCode.graph.schema.import.duplicate': {
        'zh': '知识图谱模板名称：{0} 或 模板ID：{1}已存在',
        'en': 'Graph Template Name: {0} or Graph Template ID: {1} already exists',
    },
    'RetCode.graph.schema.import.failed': {
        'zh': '知识图谱模板导入失败：{0}',
        'en': 'Graph schema import failed: {0}',
    },
    'RetCode.graph.schema.import.no.valid.structure': {
        'zh': '导入文件中不存在合法的知识图谱模板',
        'en': 'There is no valid graph schema in the imported file',
    },
    'RetCode.graph.schema.name.duplicate': {
        'zh': '知识图谱模板名称已存在：{0}',
        'en': 'Schema name already exists: {0}',
    },
    'RetCode.graph.schema.name.invalid.chars': {
        'zh': '知识图谱名称只允许包含字母、数字、下划线和中文',
        'en': 'Schema name can only contain letters, numbers, underscores and Chinese characters',
    },
    'RetCode.graph.schema.name.invalid.length': {
        'zh': '知识图谱名称长度不合法：当前长度为{0}，需要在1-30之间',
        'en': 'Schema name length is invalid: current length is {0}, required range is 1-30',
    },
    # ---- 规范键（RetCode. 前缀）--------------------------------------
    # review/query 抛业务错误时用的是这两个键；它们与上面
    # kbase.not.exist / kbase.exist 文本相同，但键名不同，别互相替代 ——
    # 排障时对不上键名会浪费很久。
    'RetCode.kbase.not.exist': {
        'zh': '知识库不存在',
        'en': 'Knowledge base not exist',
    },

    # ---- 图谱审阅（B3-b 的一部分）-----------------------------------
    # ⚠️ 四条里**三条恒为中文、一条跟随语言**，取决于消息从哪来：
    #
    #   * ``kbId`` / ``depth`` / ``limit`` 的约束直接写在 **DTO 注解**上，
    #     消息是**内联中文字面量**（``@NotBlank(message="知识库ID不能为空")`` 这种），
    #     不查 i18n 表 —— 所以三档 Accept-Language 下都是中文。
    #   * ``direction`` **DTO 上没有注解**，落到服务层的
    #     ``ApplicationContextHolder.getMessage("RetCode.graph.review.direction.invalid")``，
    #     那条**跟请求 locale 走**（无头/en-US 出英文、zh-CN 出中文）。
    #
    # 同一次请求只换 Accept-Language：
    #     depth=0   → 无头/zh-CN/en-US 三档都是「深度必须在1-10之间」
    #     direction → 无头 "Query direction must be in, out or both"、zh-CN 中文
    #
    # 还有个坑：DTO 上是 ``深度必须在1-10之间``，而 i18n 表里的同名键是
    # ``查询深度必须在1-10之间``（多个「查询」）。**DTO 先跑**，所以线上看到的是前者；
    # 服务层那份不可达。这里存的是**实际能看到的那份**。
    'RetCode.graph.review.depth.invalid': {
        'zh': '深度必须在1-10之间',
        'en': '深度必须在1-10之间',
    },
    'RetCode.graph.review.direction.invalid': {
        'zh': '查询方向必须是in、out或both',
        'en': 'Query direction must be in, out or both',
    },
    'RetCode.graph.review.kbid.empty': {
        'zh': '知识库ID不能为空',
        'en': '知识库ID不能为空',
    },
    'RetCode.graph.review.limit.invalid': {
        'zh': '返回结果数量必须在1-10000之间',
        'en': '返回结果数量必须在1-10000之间',
    },
    # ---- 图谱实体/边/查询（B3-b 余下部分）---------------------------
    'RetCode.graph.edge.already.exists': {
        'zh': '边已存在：{0}',
        'en': 'Edge already exists: {0}',
    },
    'RetCode.graph.edge.create.failed': {
        'zh': '创建边失败：{0}',
        'en': 'Failed to create edge: {0}',
    },
    'RetCode.graph.edge.create.success': {
        'zh': '边创建成功',
        'en': 'Edge created successfully',
    },
    'RetCode.graph.edge.delete.failed': {
        'zh': '删除边失败：{0}',
        'en': 'Failed to delete edge: {0}',
    },
    'RetCode.graph.edge.delete.success': {
        'zh': '边删除成功',
        'en': 'Edge deleted successfully',
    },
    'RetCode.graph.edge.direction.invalid': {
        'zh': "边方向必须是'out'或'in'：{0}",
        'en': "Edge direction must be 'out' or 'in': {0}",
    },
    'RetCode.graph.edge.id.format.invalid': {
        'zh': '边ID格式不正确：必须以边类型开头，格式为{0}_字母或数字或中划线，总长度不超过100',
        'en': 'Invalid edge ID format: must start with edge type, format is {0}_letters or numbers or hyphens, total length must not exceed 100',
    },
    'RetCode.graph.edge.id.length.exceed': {
        'zh': '边ID长度超过100：当前长度为{0}',
        'en': 'Edge ID length exceeds 100: current length is {0}',
    },
    'RetCode.graph.edge.node.type.pair.mismatch': {
        'zh': '边类型[{0}]的起始节点类型[{1}]与终止节点类型[{2}]不匹配Schema中任何定义的source_entity/target_entity对',
        'en': 'Edge type [{0}] source node type [{1}] and target node type [{2}] do not match any schema definition (source_entity/target_entity pair)',
    },
    'RetCode.graph.edge.not.exists': {
        'zh': '边不存在：{0}',
        'en': 'Edge does not exist: {0}',
    },
    'RetCode.graph.edge.property.not.defined': {
        'zh': '边属性未在Schema中定义：{0}',
        'en': 'Edge property not defined in Schema: {0}',
    },
    'RetCode.graph.edge.property.type.mismatch': {
        'zh': '边属性[{0}]的值类型与基础Schema定义不符合，期望类型[{1}]，当前值[{2}]',
        'en': 'Edge property [{0}] value type does not match schema definition. Expected type [{1}], actual value [{2}]',
    },
    'RetCode.graph.edge.schema.undefined': {
        'zh': '知识库Schema未定义',
        'en': 'Knowledge base Schema is not defined',
    },
    'RetCode.graph.edge.source.node.type.invalid': {
        'zh': '边类型[{0}]的起始节点ID[{1}]格式无效，期望实体类型为[{2}]',
        'en': 'Edge type [{0}] source node ID [{1}] format is invalid, expected entity type [{2}]',
    },
    'RetCode.graph.edge.source.node.type.undefined': {
        'zh': '边类型[{0}]的起始节点类型[{1}]未在Schema中定义',
        'en': 'Edge type [{0}] source node type [{1}] is not defined in schema',
    },
    'RetCode.graph.edge.source.not.exists': {
        'zh': '起始实体不存在：{0}',
        'en': 'Source entity does not exist: {0}',
    },
    'RetCode.graph.edge.system.field.cannot.update': {
        'zh': '不能更新边的系统字段：{0}',
        'en': 'Cannot update edge system field: {0}',
    },
    'RetCode.graph.edge.target.node.type.invalid': {
        'zh': '边类型[{0}]的终止节点ID[{1}]格式无效，期望实体类型为[{2}]',
        'en': 'Edge type [{0}] target node ID [{1}] format is invalid, expected entity type [{2}]',
    },
    'RetCode.graph.edge.target.node.type.undefined': {
        'zh': '边类型[{0}]的终止节点类型[{1}]未在Schema中定义',
        'en': 'Edge type [{0}] target node type [{1}] is not defined in schema',
    },
    'RetCode.graph.edge.target.not.exists': {
        'zh': '目标实体不存在：{0}',
        'en': 'Target entity does not exist: {0}',
    },
    'RetCode.graph.edge.type.not.defined': {
        'zh': '边类型未在Schema中定义：{0}',
        'en': 'Edge type not defined in Schema: {0}',
    },
    'RetCode.graph.edge.update.failed': {
        'zh': '更新边失败：{0}',
        'en': 'Failed to update edge: {0}',
    },
    'RetCode.graph.edge.update.success': {
        'zh': '边更新成功',
        'en': 'Edge updated successfully',
    },
    'RetCode.graph.entity.already.exists': {
        'zh': '实体已存在：{0}',
        'en': 'Entity already exists: {0}',
    },
    'RetCode.graph.entity.create.failed': {
        'zh': '创建实体失败：{0}',
        'en': 'Failed to create entity: {0}',
    },
    'RetCode.graph.entity.create.success': {
        'zh': '实体创建成功',
        'en': 'Entity created successfully',
    },
    'RetCode.graph.entity.delete.failed': {
        'zh': '删除实体失败：{0}',
        'en': 'Failed to delete entity: {0}',
    },
    'RetCode.graph.entity.delete.success': {
        'zh': '实体删除成功',
        'en': 'Entity deleted successfully',
    },
    'RetCode.graph.entity.id.format.invalid': {
        'zh': '实体ID格式不正确：必须以实体类型开头，格式为{0}_字母或数字或中划线，总长度不超过100',
        'en': 'Invalid entity ID format: must start with entity type, format is {0}_letters or numbers or hyphens, total length must not exceed 100',
    },
    'RetCode.graph.entity.id.invalid': {
        'zh': '实体ID格式不正确：{0}',
        'en': 'Invalid entity ID format: {0}',
    },
    'RetCode.graph.entity.id.length.exceed': {
        'zh': '实体ID长度超过100：当前长度为{0}',
        'en': 'Entity ID length exceeds 100: current length is {0}',
    },
    'RetCode.graph.entity.not.exists': {
        'zh': '实体不存在：{0}',
        'en': 'Entity does not exist: {0}',
    },
    'RetCode.graph.entity.property.not.defined': {
        'zh': '属性未在Schema中定义：{0}',
        'en': 'Property not defined in Schema: {0}',
    },
    'RetCode.graph.entity.property.type.mismatch': {
        'zh': '属性[{0}]的值类型与基础Schema定义不符合，期望类型[{1}]，当前值[{2}]',
        'en': 'Property [{0}] value type does not match schema definition. Expected type [{1}], actual value [{2}]',
    },
    'RetCode.graph.entity.schema.undefined': {
        'zh': '知识库Schema未定义',
        'en': 'Knowledge base Schema is not defined',
    },
    'RetCode.graph.entity.system.field.cannot.update': {
        'zh': '不能更新系统字段：{0}',
        'en': 'Cannot update system field: {0}',
    },
    'RetCode.graph.entity.type.not.defined': {
        'zh': '实体类型未在Schema中定义：{0}',
        'en': 'Entity type not defined in Schema: {0}',
    },
    'RetCode.graph.entity.update.failed': {
        'zh': '更新实体失败：{0}',
        'en': 'Failed to update entity: {0}',
    },
    'RetCode.graph.entity.update.success': {
        'zh': '实体更新成功',
        'en': 'Entity updated successfully',
    },
    'RetCode.graph.query.build.failed': {
        'zh': '知识图谱构建失败，请检查后重试',
        'en': 'Knowledge graph build failed, please check and retry',
    },
    'RetCode.graph.query.building': {
        'zh': '知识图谱构建中，请稍后再试',
        'en': 'Knowledge graph is being built, please try again later',
    },
    'RetCode.graph.query.database.operation.failed': {
        'zh': '数据库操作失败',
        'en': 'Database operation failed',
    },
    # ⚠️ 下面五条（depth / kbid / limit / offset / type.empty）**zh 与 en 故意写成同一句
    # 中文**，它们也**不是** 0005 而是 0004。原因同 review 那一段：约束写在 DTO 注解上，
    # 消息是内联中文字面量、不查 i18n 表。``Accept-Language: en-US`` 仍回中文。
    #
    # 其中 depth 这条还要更小心：i18n 表里原本那句是「**查询**深度必须在1-100之间」，
    # 比 DTO 上多一个「查询」；**DTO 先跑**，所以线上看到的是没有「查询」的那句。
    # 照 i18n 表实现会一直差一个字。
    'RetCode.graph.query.depth.invalid': {
        'zh': '深度必须在1-100之间',
        'en': '深度必须在1-100之间',
    },
    'RetCode.graph.query.kbid.empty': {
        'zh': '知识库ID不能为空',
        'en': '知识库ID不能为空',
    },
    'RetCode.graph.query.limit.invalid': {
        'zh': '返回结果数量必须在1-1000之间',
        'en': '返回结果数量必须在1-1000之间',
    },
    'RetCode.graph.query.offset.invalid': {
        'zh': '分页偏移量不能小于0',
        'en': '分页偏移量不能小于0',
    },
    'RetCode.graph.query.type.empty': {
        'zh': '查询类型不能为空',
        'en': '查询类型不能为空',
    },
    # 这一条是**服务层** i18n（DTO 上没有 @Pattern），所以正常跟随请求语言。
    'RetCode.graph.query.type.invalid': {
        'zh': '查询类型无效，必须为entity、edge、path或sub_graph',
        'en': 'Invalid query type, must be entity, edge, path or sub_graph',
    },
    # ``@Min`` / ``@Max`` / ``@NotNull`` **不写 message** 时的默认文案，
    # 随 ``Accept-Language`` 走：
    #   zh: 最小不能小于1 / 最大不能超过500 / 不能为null
    #   en: must be greater than or equal to 1 / must be less than or equal to 500 /
    #       must not be null
    # ⚠️ 不要写成「must be between 1 and 10000」：两种语言都不对。
    'validator.min': {
        'zh': '最小不能小于{0}',
        'en': 'must be greater than or equal to {0}',
    },
    'validator.max': {
        'zh': '最大不能超过{0}',
        'en': 'must be less than or equal to {0}',
    },
    'validator.notNull': {
        'zh': '不能为null',
        'en': 'must not be null',
    },
    # 获取知识检索/模型列表失败的文案。
    'RetCode.zae.get.workflow.fail': {
        'zh': '获取知识检索列表失败',
        'en': 'Failed to get knowledge retrieval list',
    },
    # ------------------------------------------------------------------
    # Agent Key 管理（UI「远程接入 → 密钥管理」）
    #
    # 英文里不要放单引号：``render`` 带参数时会走 MessageFormat 的
    # 引号规则（见 ``_message_format_quotes``），单引号会被吃掉。
    # ------------------------------------------------------------------
    'agent.key.not.found': {
        'zh': 'API Key 不存在或已被删除',
        'en': 'API key not found or already deleted',
    },
    'agent.key.admin.disabled': {
        'zh': '密钥管理接口未启用',
        'en': 'Key management API is disabled',
    },
    'agent.key.pepper.missing': {
        'zh': '未配置 RKB_AGENT_KEY_PEPPER，无法创建 API Key',
        'en': 'RKB_AGENT_KEY_PEPPER is not configured; API keys cannot be created',
    },
    'agent.key.store.unavailable': {
        'zh': 'API Key 表不可用，请先完成数据库初始化',
        'en': 'API key table is unavailable; initialize the database first',
    },
    'agent.key.create.failed': {
        'zh': '创建 API Key 失败，请重试',
        'en': 'Failed to create API key; please retry',
    },
    'agent.key.name.required': {
        'zh': '请填写名称',
        'en': 'Name is required',
    },
    'agent.key.name.too.long': {
        'zh': '名称不能超过 {0} 个字符',
        'en': 'Name must be at most {0} characters',
    },
    'agent.key.description.invalid': {
        'zh': '用途说明必须是文本',
        'en': 'Description must be text',
    },
    'agent.key.description.too.long': {
        'zh': '用途说明不能超过 {0} 个字符',
        'en': 'Description must be at most {0} characters',
    },
    'agent.key.scopes.required': {
        'zh': '请至少选择一个权限',
        'en': 'Select at least one scope',
    },
    'agent.key.scope.unknown': {
        'zh': '未知权限：{0}',
        'en': 'Unknown scope: {0}',
    },
    'agent.key.kb_ids.too.many': {
        'zh': '知识库白名单最多 {0} 项',
        'en': 'At most {0} knowledge bases are allowed',
    },
    'agent.key.kb_ids.invalid': {
        'zh': '知识库白名单必须是字符串数组',
        'en': 'Knowledge base whitelist must be an array of strings',
    },
    'agent.key.rate_limit.invalid': {
        'zh': '每分钟请求上限必须在 0 到 {0} 之间',
        'en': 'Rate limit must be between 0 and {0}',
    },
    'agent.key.expires_at.invalid': {
        'zh': '过期时间无法解析，请使用 YYYY-MM-DD 或 ISO 8601',
        'en': 'Invalid expiry; use YYYY-MM-DD or ISO 8601',
    },
    'agent.key.expires_at.past': {
        'zh': '过期时间必须晚于当前时间',
        'en': 'Expiry must be in the future',
    },
    'agent.key.no.fields': {
        'zh': '没有可更新的字段',
        'en': 'No fields to update',
    },
    'agent.key.field.unknown': {
        'zh': '未知字段：{0}',
        'en': 'Unknown field: {0}',
    },
}

#: **基础包里缺席的键**。
#:
#: 为什么单列一张表：``Accept-Language: *`` 解析出的 locale 取的是**基础包**，
#: 而这族键不在基础包里，于是查表会在构造业务异常**之前**就抛
#: ``NoSuchMessageException`` —— 「回哪条文案」变成了「异常在哪个 catch 里被
#: 接住」，**每个调用点归宿不同**。单靠归一化后的语言分不开这一支，需要区分的
#: 调用点显式取 ``identity.base_bundle(request)`` 并按下面登记的归宿改写。
#:
#: 各键的归宿：
#:
#: ``graph.import.id.format.invalid.prefix`` / ``.length`` / ``.char``
#:     调用点 ``graph_import_api.import_graph`` 的 id 校验段：base 下
#:     取文案时先抛错、逃过业务异常的重抛，被外层兜底包成
#:     0005（``Retcode.graph.import.fail``）—— **不是 0001**。
#:
#: ``RetCode.operator.arg.visibleRange.incorrect``
#:     base 没有这个键。触发点取文案时抛异常，异常文本被 import 流程用
#:     ``e.getMessage()`` **当文案发出去**（泄漏文本里带 locale 串）。``*`` 档的
#:     locale 串目前未覆盖；``operator_import`` 那条调用点**有意**不消费本集合。
BASE_ABSENT_KEYS = frozenset({
    'graph.import.id.format.invalid.prefix',
    'graph.import.id.format.invalid.length',
    'graph.import.id.format.invalid.char',
    'RetCode.operator.arg.visibleRange.incorrect',
})

def is_base_absent(key: str) -> bool:
    """该键在基础包里缺席（见 :data:`BASE_ABSENT_KEYS`）。

    **只回答事实，不改渲染** —— :func:`render` 刻意保持「查不到回落、不抛」的行为
    （别把文案层变成地雷）；「base 包下归宿改成什么」由知道调用上下文的调用点决定：
    回退删除走 0001，图导入 id 走 0005 + ``Retcode.graph.import.fail``。传未知键
    返回 False。
    """
    return key in BASE_ABSENT_KEYS

def render_validator(key: str, language: str, *args) -> str:
    """Validator 默认文案（``validator.*``）的渲染：**纯拼接**，不走 MessageFormat。

    这些默认 message **没有千分位**（``最大不能超过10000``）；而 app 的 i18n 文案经
    MessageFormat，同样输入会渲染成 ``10,000``。两者必须分开，否则越界提示会多一个逗号。
    """
    entry = MESSAGES[key]
    text = entry.get(language) or entry.get(DEFAULT_LANGUAGE) or key
    for index, value in enumerate(args):
        text = text.replace('{%d}' % index, str(value))
    return text

DEFAULT_LANGUAGE = 'en'
SUPPORTED_LANGUAGES = ('zh', 'en')

def normalize_language(language: str | None) -> str:
    """把 ``Accept-Language`` 的主标签归一化成 ``zh`` / ``en``。

    **不是「zh 开头就中文」**：

    * ``zh-CN``（浏览器默认发这个）→ 中文。
    * ``zh`` / ``zh-TW`` / ``de`` / 其他语言 → **英文**。
    * 不带这个头 → 英文。
    * ``*`` → 中文（基础包是中文）。
    """
    tag = (language or '').strip().lower().replace('_', '-')
    if tag == '*':
        return 'zh'
    return 'zh' if tag == 'zh-cn' else DEFAULT_LANGUAGE

def _resolve(language: str | None) -> str:
    """把 ``language`` 定成 ``zh`` / ``en``。

    ``zh`` 这个值有歧义：作为**归一化结果**它是中文，作为**原始 Accept-Language 标签**
    它却是英文（见 :func:`normalize_language`）。这里一律按「已经是归一化结果」理解
    —— :func:`identity.language` 是唯一的生产者，它在返回前就归一化好了，
    所以进到这里的一定不是原始标签。真有人塞了原始标签，也会被 :func:`normalize_language`
    兜住（除 ``zh`` 这一个值以外）。
    """
    value = (language or '').strip().lower()
    if value in SUPPORTED_LANGUAGES:
        return value
    return normalize_language(language)

def render(key: str, language: str, *args) -> str:
    """按语言渲染文案；未知键回落成键名（便于排障，不静默吞掉）。"""
    entry = MESSAGES.get(key)
    if not entry:
        return key
    template = entry.get(_resolve(language)) or entry.get(DEFAULT_LANGUAGE) or key
    if not args:
        return template
    try:
        # ⚠️ 带参数时按 ``MessageFormat`` 的规则处理（**只在带参数时**走它）：
        #
        # 1. 数字加千分位：``operatorId=99999`` 渲染成 ``99,999``；
        # 2. **单引号是转义符**：``下划线'_'`` 渲染成 ``下划线_``、``''`` 渲染成 ``'``。
        #    ``RetCode.kbase.name.validation`` 渲染后不带引号，
        #    而存储的模板里是带引号的。
        template = _message_format_quotes(template)
        return template.format(*[_format_arg(item) for item in args])
    except (IndexError, KeyError):
        # 参数个数对不上是编码错误：返回原文案（带占位符）比抛异常更适合线上
        return template

def _message_format_quotes(template: str) -> str:
    """``MessageFormat`` 的引号规则：``''`` → ``'``，``'...'`` → ``...``（引号吃掉）。

    只处理这一条 —— 我们的文案里没有在引号内放 ``{n}`` 的用法（那会让占位符
    变成字面量，本项目里没有这类文案）。
    """
    out: list[str] = []
    index = 0
    while index < len(template):
        char = template[index]
        if char != "'":
            out.append(char)
            index += 1
            continue
        if index + 1 < len(template) and template[index + 1] == "'":
            out.append("'")
            index += 2
            continue
        # 一段被引用文本：两端的引号都吃掉，中间原样
        index += 1
        while index < len(template) and template[index] != "'":
            out.append(template[index])
            index += 1
        index += 1                      # 收尾引号（没有配对时就是结尾，照吃）
    return ''.join(out)

def _format_arg(value):
    """``MessageFormat`` 对数字的分组行为（只对 int 生效；float 与 bool 原样）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    return f'{value:,}'
