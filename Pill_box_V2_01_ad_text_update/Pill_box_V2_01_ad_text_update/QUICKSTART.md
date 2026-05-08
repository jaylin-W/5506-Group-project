# Pill box V2.01

这是 **Pill box V2** 的 **2.01 版本**。

## 本次修改

- 项目命名调整为 **Pill box V2.01**
- 页面整体配色不再单一，改为更丰富的渐变与柔和色块
- 新增 4 张自动滚动的药品/保健品优惠广告背景图
- 首页广告为自动轮播卡片，不包含按钮和跳转
- 侧边导航栏移除了 **Host**、**核心功能**、**使用场景** 按键
- 用户端不再直接显示编辑页面入口
- 编辑页面改为隐藏地址访问（单独 HTTP 路径）
- 保留注册、登录、个人页面、保健品计划、数据库功能

## 运行方式

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

访问首页：

```text
http://127.0.0.1:5000
```

## 隐藏编辑页面

默认隐藏编辑路径：

```text
http://127.0.0.1:5000/pillbox-v2-editor-201
```

默认编辑密码：

```text
admin123
```

你也可以在 `.env` 中修改：

```text
HOST_PASSWORD=你的密码
EDITOR_ROUTE=你的隐藏地址
```

## 数据库位置

```text
instance/app.db
```


## 广告卡片文字编辑

隐藏编辑页面可以编辑首页 4 个广告卡片的文字：

```text
http://127.0.0.1:5000/pillbox-v2-editor-201
```
