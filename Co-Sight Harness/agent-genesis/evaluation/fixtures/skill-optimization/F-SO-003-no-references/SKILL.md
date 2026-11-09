# Security Scanner

> description: 扫描代码安全漏洞

## 执行步骤

扫描目标代码文件，查找以下安全问题：

1. SQL 注入 — 检查是否有字符串拼接构建 SQL 查询的情况。使用参数化查询替代字符串拼接。Python 中使用 `cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))` 而非 `f"SELECT * FROM users WHERE id = {user_id}"`。

2. XSS 漏洞 — 检查是否有未转义的用户输入直接渲染到 HTML。所有用户输入必须经过 HTML 实体编码。使用 `html.escape(user_input)` 进行转义。

3. 命令注入 — 检查是否有用户输入直接拼接到系统命令中。使用 `subprocess.run([cmd, arg])` 替代 `os.system(f"cmd {user_arg}")`。

4. 硬编码密钥 — 检查是否有 API key、password、token 等硬编码在源代码中。所有密钥应通过环境变量或密钥管理器获取。

5. 路径遍历 — 检查文件路径是否可能被用户输入操控，导致访问非预期目录。使用 `os.path.realpath()` 验证最终路径在允许的目录范围内。

6. 不安全的反序列化 — 检查是否使用 pickle.loads() 处理不可信数据。使用 json.loads() 或添加签名验证。

7. XXE 注入 — 检查 XML 解析器是否启用了外部实体处理。使用 defusedxml 库替代标准 xml 库。

8. SSRF — 检查是否有用户可控的 URL 被服务端请求。实施 URL 白名单验证。

9. 弱加密算法 — 检查是否使用 MD5/SHA1 进行密码哈希，是否使用 DES/RC4 进行加密。使用 bcrypt/scrypt/argon2 进行密码哈希。

10. CORS 配置错误 — 检查是否设置了过于宽松的跨域策略（Access-Control-Allow-Origin: *）。

11. Cookie 安全属性缺失 — 检查敏感 Cookie 是否缺少 Secure、HttpOnly、SameSite 属性。

12. CSP 头缺失 — 检查 HTTP 响应是否包含 Content-Security-Policy 头。
