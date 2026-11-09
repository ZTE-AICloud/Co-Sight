"""安全漏洞测试文件 — 含 SQL 注入漏洞."""

import sqlite3


def get_user(username):
    """SQL 注入漏洞: 字符串拼接构建查询."""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    # CWE-89: SQL Injection
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor.execute(query)
    return cursor.fetchall()


def get_user_safe(username):
    """安全的参数化查询."""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE username = ?"
    cursor.execute(query, (username,))
    return cursor.fetchall()
