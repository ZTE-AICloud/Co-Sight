"""安全漏洞测试文件 — 含硬编码凭据."""

# CWE-798: Hardcoded Credentials
API_KEY = "sk-abc123def456ghij789klm012nop345qrs678tuv"
DATABASE_PASSWORD = "admin123!@#"
SECRET_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

DEBUG_MODE = True
MAX_RETRIES = 3
