# 安全改进日志 (Security Improvements)

## V2 版本 - 完整安全加固

### 🔴 关键修复

#### 1. CSRF 保护 (Cross-Site Request Forgery)
- **问题**：所有 POST 表单缺少 CSRF token
- **修复**：
  - 安装 Flask-WTF 依赖
  - 在所有 HTML 表单中添加 `{{ csrf_token() }}`
  - 在 app.py 中启用 CSRFProtect

**受影响的表单**：
- 登录表单
- 注册表单
- Host 登录表单
- Host 内容编辑
- 个人资料编辑
- 服用计划添加和删除

#### 2. 硬编码密钥和密码
- **问题**：`SECRET_KEY` 和 `HOST_PASSWORD` 硬编码在代码中
- **修复**：
  - 改为从环境变量读取
  - 添加 `.env.example` 配置文件
  - 支持 `.env` 文件（通过 python-dotenv）

**新配置**：
```python
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["HOST_PASSWORD"] = os.environ.get("HOST_PASSWORD", "admin123")
```

#### 3. 密码暴力破解防护
- **问题**：登录和 Host 页面无登录尝试限制
- **修复**：
  - 安装 Flask-Limiter
  - 为 `/login` 路由设置 5 次/分钟 限制
  - 为全局添加默认限制（200 次/天，50 次/小时）

**实现**：
```python
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login(): ...
```

### 🟡 数据验证完善

#### 1. 邮箱验证
- **问题**：仅检查非空，无格式验证
- **修复**：
  - 安装 email-validator 库
  - 完整的邮箱格式检查
  - 自动转换为小写并验证

**验证函数**：
```python
def validate_email_format(email):
    try:
        valid = validate_email(email.strip().lower())
        return True, valid.email
    except EmailNotValidError as e:
        return False, str(e)
```

#### 2. 用户名验证
- **问题**：无长度限制和字符限制
- **修复**：
  - 长度限制：3-20 字符
  - 字符限制：仅允许字母、数字、下划线、连字符

**验证函数**：
```python
def validate_username(username):
    if not username or len(username) < 3 or len(username) > 20:
        return False, "用户名长度需要 3-20 位字符。"
    
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        return False, "用户名只能包含字母、数字、下划线和连字符。"
    
    return True, None
```

#### 3. 密码验证
- **问题**：仅检查长度 >= 6
- **修复**：
  - 更清晰的错误消息
  - 统一的验证逻辑

#### 4. 年龄验证
- **问题**：允许任意整数（包括负数）
- **修复**：
  - 范围限制：0-150
  - 非数字时的错误处理

**验证函数**：
```python
def validate_age(age_str):
    if not age_str or age_str.strip() == "":
        return True, None
    
    try:
        age = int(age_str)
        if age < 0 or age > 150:
            return False, "年龄必须是 0-150 之间的数字。"
        return True, age
    except ValueError:
        return False, "年龄必须是数字。"
```

### 🟢 错误处理和日志

#### 1. 数据库错误处理
- **问题**：数据库错误会导致应用 crash
- **修复**：
  - 所有数据库操作添加 try-catch
  - 记录错误日志
  - 返回用户友好的错误信息

**示例**：
```python
try:
    conn.execute(...)
    conn.commit()
except sqlite3.DatabaseError as e:
    logger.error(f"操作失败: {e}")
    flash("操作失败，请稍后重试。", "danger")
finally:
    conn.close()
```

#### 2. 全局错误处理器
- **问题**：没有 404、500 错误页面
- **修复**：
  - 添加 404.html、500.html、403.html
  - 注册全局错误处理器
  - 记录错误日志

**实现**：
```python
@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"服务器错误: {error}")
    return render_template("500.html"), 500
```

#### 3. 日志系统
- **问题**：无任何日志记录
- **修复**：
  - 配置 logging 系统
  - 记录登录成功/失败
  - 记录数据操作
  - 记录错误信息

**实现**：
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info(f"用户登录: {username}")
logger.warning(f"登录失败: {username}")
logger.error(f"数据库错误: {e}")
```

### ✅ 已有的安全措施（保持不变）

1. **SQL 注入防护** ✅
   - 所有查询都使用参数化查询（绑定参数）

2. **密码哈希** ✅
   - 使用 werkzeug.security 的 generate_password_hash 和 check_password_hash

3. **会话管理** ✅
   - 使用 Flask-Login 管理用户会话

4. **认证检查** ✅
   - 受保护的路由使用 @login_required 装饰器

## 📊 修复汇总

| 问题 | 严重程度 | 状态 | 修复方法 |
|------|--------|------|--------|
| 硬编码密钥 | 🔴 高 | ✅ 已修复 | 环境变量 + python-dotenv |
| CSRF 漏洞 | 🔴 高 | ✅ 已修复 | Flask-WTF |
| 暴力破解 | 🔴 高 | ✅ 已修复 | Flask-Limiter |
| 邮箱验证 | 🟡 中 | ✅ 已修复 | email-validator |
| 用户名验证 | 🟡 中 | ✅ 已修复 | 正则表达式 + 长度检查 |
| 年龄验证 | 🟡 中 | ✅ 已修复 | 范围检查 |
| 数据库错误处理 | 🟡 中 | ✅ 已修复 | try-except + 日志 |
| 错误页面 | 🟢 低 | ✅ 已修复 | 错误处理器 + 模板 |
| 日志系统 | 🟢 低 | ✅ 已修复 | logging 模块 |

## 🚀 部署检查清单

在生产环境部署前，请检查以下项目：

- [ ] 生成新的 SECRET_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] 修改 HOST_PASSWORD 为强密码
- [ ] 创建 `.env` 文件（基于 `.env.example`）
- [ ] 设置 FLASK_DEBUG=False
- [ ] 验证所有环境变量已正确设置
- [ ] 运行应用并测试所有功能
- [ ] 检查应用日志是否正常
- [ ] 配置 HTTPS（如果在网络上）
- [ ] 定期备份数据库文件

## 📚 参考文献

- OWASP Top 10: https://owasp.org/www-project-top-ten/
- Flask Security Best Practices: https://flask.palletsprojects.com/en/latest/security/
- CSRF 攻击: https://owasp.org/www-community/attacks/csrf

## 版本历史

- **V1.0**：基础功能实现
- **V2.0**：🔒 完整安全加固
