# NSS 问卷提醒

车辆「创建时间」（交付日期）**89 天后**当天北京时间 **09:00**，通过飞书应用 HeroClaw（`cli_a9574044cca9dbc9`）私聊提醒**门店服务经理与对应门店/区域督导**（仅「全新M817」车系，试驾车除外）。问卷在次日到达，提醒比问卷早一天。

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
车辆档案 Excel（新版「客户车辆关系」导出，控制台上传或 scripts/import_vehicles.py）
  + 「参与考核特约店清单」（门店服务经理）
  → 创建时间 +89 天 = 提醒日（问卷次日到达）
  → HeroClaw 私聊门店服务经理与对应督导
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
该用户明天将会收到 NSS 满意度调研问卷，请及时跟进！
```

同一 VIN + 提醒日只发一次。

## NSS 提醒规则

数据源为新版「客户车辆关系」导出（sheet `客户车辆关系*`，全列为文本）。到期车辆按以下规则判定：

1. **车系**：`车系名称` 去空格、NFKC 归一化后必须**完全等于**「全新M817」；`M817`、`917`、`917-L`、`联名改装`、`X700` 等其它车系一律不提醒。
2. **数据类型**：`数据类型` 为「试驾车」的不提醒；`客户`、`质检`、空值正常提醒。
3. **提醒日**：`创建时间` 即交付日期，交付日 + `offset_days`（默认 89 天，可在 `config/settings.json` 调整）当天 09:00 发送。提醒日是问卷到达的前一天，正文说明该用户明天将会收到 NSS 满意度调研问卷。`创建时间` 为空或无法解析的行在导入时跳过并计数。`due_date` 在导入时写入；若服务器上的 `config/settings.json` 仍是 `90`，改为 `89` 后需重新导入车辆档案，否则已有档案仍按旧提醒日发送。
4. **收件人**：发**门店服务经理 + 对应门店/区域督导**。门店匹配只用**所属门店**（`所属门店名称`/`所属门店编码`，交付门店列不参与匹配，仅作展示参考）：**先按编码**（`所属门店编码` vs 店清单 `店代码`，忽略大小写）**再按名称**（归一化后比对），`所属门店编码` 为可选列，缺失时只按名称匹配；并记录 `match_method`（`code`/`name`/`region`/`none`）；督导来自同步的督导表：按门店名称关联，督导行无门店列表时按区域关联，车辆档案带 `region` 字段且门店未匹配时也按区域回退找督导。**全国负责人（`national_recipients`，刘明轩/胡进）不发送**。收件人按 open_id（缺失时按姓名）去重，同一人既是服务经理又是督导只发一条。门店未匹配且无区域督导、或收件人无 open_id 时该条记为 `failed`/`unmatched` 并记录原因，不发送。
5. **去重**：同一 `VIN + 提醒日` 只发一次（`data/sent_log.json`）。

资格规则可在 `config/settings.json` 的 `eligibility` 调整（`series_names`、`excluded_data_types`）。旧的 `exclusions`、`skip_store_keywords`、`national_recipients` 配置已废弃，存在时被忽略。

### 数据导入

```bash
python scripts/import_vehicles.py 车辆档案.xlsx            # 写入前自动备份 data/vehicles.json
python scripts/import_vehicles.py 车辆档案.xlsx --dry-run  # 只解析统计，不写入
```

导入统计：总行数、导入、无创建时间跳过、重复 VIN（同 VIN 首行生效）。用车人/车主姓名、电话、ID 等个人字段不落库。控制台上传同格式文件亦可。旧版交付档案格式（交付日期/交付门店/车系）仍兼容。

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
