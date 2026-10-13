# NSS 问卷提醒

交付日期 **90 天后**当天北京时间 **09:00**，通过飞书应用 HeroClaw（`cli_a9574044cca9dbc9`）私聊提醒：督导 + 门店售后业务负责人 + 本系统全国收件人。

不爬 DMS，不使用共享 Chromium。

## 入口

| 项 | 值 |
|----|-----|
| 控制台 | `http://127.0.0.1:9005/` |
| 时区 | `Asia/Shanghai`（UTC+8） |
| 定时 | 00:00 同步多维表 · 09:00 发送 |

公网 hostname 只写本机 Cloudflare Tunnel，不入库。

## 数据流

```text
车辆档案 Excel（控制台上传）
  + 「参与考核特约店清单」（督导 + 售后负责人）
  → 交付日 +90 天 = 提醒日
  → HeroClaw 私聊
```

提醒正文：

```text
VIN：
交付日期：
车牌号：
车系：
车型：
交付门店：
门店服务经理：
该车辆会在今日收到 NSS 问卷，请及时跟进！
```

同一 VIN + 提醒日只发一次。全国收件人在控制台按姓名和飞书手机号维护，只作用于本系统。名称含「虚拟店」「出口车」的交付门店默认跳过（可在 `config/settings.json` 改 `skip_store_keywords`）。

## 提醒排除规则

到期车辆命中以下规则则不发送（计入「排除」，不标记已发）：

- **917 车系**：`车系名称` / `车系` / `售后车系` 归一化后（去空格、全角转半角、去「猛士」前缀）等于 `917`，或以 `917-`、`917(` 开头；`M817`、`M917` 等不受影响。
- **试驾车**：`数据类型` 列等于「试驾车」，或车型名称含「试驾车」（可在 `config/settings.json` 的 `exclusions` 关闭或调整，如 `series`、`data_types`、`model_keyword_test_drive`、`enabled`）。

## 飞书多维表

门店、督导、区域来自「参与考核特约店清单」（`tbl0wcYNWo5mtNVf`）。售后负责人当作门店服务经理。每天 00:00 同步，控制台也可手动同步。

HeroClaw 必须被加为该 Base 的**文档应用**（飞书 → 右上角「…」→ 添加文档应用 → HeroClaw），否则同步会 91403。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填 APP_SECRET
python app.py
```

Excel 不要提交（含车辆与门店信息）。

## 部署

launchd：`com.nss-questionnaire-reminder.web`  
Cloudflare Tunnel：`com.cloudflare.cloudflared.nss-questionnaire-reminder`
