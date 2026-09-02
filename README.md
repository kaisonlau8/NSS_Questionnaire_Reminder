# NSS 问卷提醒

交付日期 **90 天后**当天北京时间 **09:00**，通过飞书应用 HeroClaw（`cli_a9574044cca9dbc9`）私聊提醒：督导 + 门店服务经理 + 全国收件人。

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
  + 飞书门店清单 / 督导表
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

同一 VIN + 提醒日只发一次。全国收件人默认刘明轩、胡进，可在控制台改。名称含「虚拟店」「出口车」的交付门店默认跳过（可在 `config/settings.json` 改 `skip_store_keywords`）。

## 飞书多维表

同一 Base：门店清单 `tblSWhs7mZEHjcvQ`、督导表 `tbl9HolOXvgKR91s`。

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
