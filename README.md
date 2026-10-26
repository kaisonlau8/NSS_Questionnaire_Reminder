# NSS 问卷提醒

车辆「创建时间」（交付日期）**89 天后**当天北京时间 **09:00**，通过飞书应用 HeroClaw（`cli_a9574044cca9dbc9`）私聊提醒**门店服务经理与对应门店督导**（仅「全新M817」车系，试驾车除外）。问卷在次日到达，提醒比问卷早一天。

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
4. **收件人**：发**门店服务经理 + 对应门店督导**。门店匹配只用**所属门店编码**（`所属门店编码` vs 店清单 `店代码`，忽略大小写并去空格）；不使用名称模糊匹配，也不做区域回退，编码缺失或不一致即视为未匹配（`match_method=none`，`unmatched=true`），此类车辆不会发送。督导只取已匹配门店行自身的督导。区域仅作展示，按店代码从 reportdb SQLite `stores` 表读取（`NSS_DMS_REGION_DB`，默认 `/home/ubuntu/m-hero-run/data/reportdb/reportdb.sqlite3`，只读打开；缺失或为空显示「无区域」），不使用飞书区域覆盖。**全国负责人（`national_recipients`，刘明轩/胡进）不发送**。收件人按 open_id（缺失时按姓名）去重，同一人既是服务经理又是督导只发一条。未匹配车辆或收件人无 open_id 时该条记为 `failed`/`unmatched` 并记录原因，不发送。
5. **去重**：同一 `VIN + 提醒日` 只发一次（`data/sent_log.json`）。

资格规则可在 `config/settings.json` 的 `eligibility` 调整（`series_names`、`excluded_data_types`）。旧的 `exclusions`、`skip_store_keywords`、`national_recipients` 配置已废弃，存在时被忽略。

### 数据导入

```bash
python scripts/import_vehicles.py 车辆档案.xlsx            # 写入前自动备份 data/vehicles.json
python scripts/import_vehicles.py 车辆档案.xlsx --dry-run  # 只解析统计，不写入
```

导入统计：总行数、导入、无创建时间跳过、重复 VIN（同 VIN 首行生效）。用车人/车主姓名、电话、ID 等个人字段不落库。控制台上传同格式文件亦可。旧版交付档案格式（交付日期/交付门店/车系）仍兼容。

## 飞书多维表

门店、督导、区域来自「参与考核特约店清单」（`tbl0wcYNWo5mtNVf`）。售后负责人按「门店售后业务负责人 1..4」槽位全部收集（兼容无空格、旧版无编号及旧别名，手机号按同槽位配对），首个非空槽位作为主负责人；门店行存在即视为参与考核。每天 00:00 同步，控制台也可手动同步。

HeroClaw 必须被加为该 Base 的**文档应用**（飞书 → 右上角「…」→ 添加文档应用 → HeroClaw），否则同步会 91403。

## NSS 周报（开发环境 / dry-run）

默认 `weekly_report.enabled=false`、`weekly_report.dry_run=true`。周报任务接入现有调度器，计划时间为北京时间**周一 09:30**，统计上一完整自然周。调度器本身也需启动才会运行；本功能当前仅做开发验证。

### 统计口径

- 周期为 `Asia/Shanghai` 周一 00:00 至周日 23:59:59（实现为下周一 00:00 之前）。提醒按 `sent_log.json` 的 **sent_at** 入周，不按 due_date；VIN 大写并去除全部空白后去重。同周重复提醒保留最早时间、合并接收人，按天归入最早提醒日。
- 已填写：本周被提醒的 VIN，存在 `问卷类型=NPS调研` 且 `调研时间=90天` 的记录，任务生成时间在 **最早提醒当日 00:00 至本周末**内。兼容单字段 `NPS调研-90天`（问卷类型、调研时间或问卷名称；不能覆盖明确冲突的类型/周期）。同 VIN 多条合格记录取任务生成时间最早的一条；**问卷提交时间只展示，不参与判定**。
- 填写率 = 已填写去重 VIN / 提醒去重 VIN，空周为 0%。提醒前一天及更早生成的任务不算；提醒当日早于实际发送时刻生成的任务算。
- 本周 NPS-90 总数、未提醒但已填写数按**多维表记录条数**统计，并另列未提醒的去重 VIN 台数。「未提醒」指 VIN 不在**本周**提醒集合，不代表历史从未提醒。空 VIN 无法匹配，计入未提醒记录数及缺失 VIN 诊断，不计入台数。
- 提醒车辆门店通过 `vehicles.json` 和 `stores.json` 复用现有匹配逻辑；大区仍只从只读 DMS reportdb 按店代码取，缺失显示「无区域」，不进 Top/Bottom 排名。未提醒明细中的门店、大区为问卷源数据原值。接收人使用历史发送日志，不用当前联系人替换。

### 数据源与配置

问卷数据为「NPS问卷源数据」：wiki 节点 `GxQdwX094itMQ7kQyLxc0SWDnRe` 已解析到 Base `J0BBb0z2ua4bzEs7gumc0YQXn80`、table `tblc8vCaxiWyi64Y`、view `vewRnrIcmG`。使用 `.env` 中 HeroClaw 的 `APP_ID` / `APP_SECRET` 获取 tenant token，数据请求仅 **GET records**、`page_size=500` 全量分页，不写回多维表。分页令牌异常会报错，避免生成不完整周报。

`config/settings.json`（完整默认值见 `config/settings.example.json`）：

```json
{
  "public_base_url": "",
  "weekly_report": {
    "enabled": false,
    "weekday": 0,
    "hour": 9,
    "minute": 30,
    "chat_id": "oc_ba8af247db2e2dc4955b1d01652add82",
    "dry_run": true,
    "link_base": "",
    "state_path": "weekly_report_state.json",
    "sending_timeout_seconds": 21600
  }
}
```

`weekday` 为 0（周一）至 6（周日）。设置时间必须避开 00:00、08:30、09:00、12:00 的前后 5 分钟，**含端点和跨午夜**；不合法的配置会拒绝保存/启动。默认群为「售后服务运营」。dry-run 写本地 Excel、简报及运行状态，不调用任何群聊/私聊发送 API；明确配置 `dry_run=false` 或使用 CLI `--send` 才会发送群简报。

可调整 `weekly_report.source.{app_token,table_id,view_id}` 和 `weekly_report.filters` 的字段名、类型值、周期值、组合值及兼容字段列表。第 1 题默认按 `1.` / `第1题` 等前缀识别（0~10 整数），也可用 `weekly_report.nps_field` 指定完整字段名。

环境变量覆盖项见 `.env.example`：

| 环境变量 | 用途 |
|----------|------|
| `NSS_WEEKLY_BITABLE_APP_TOKEN` / `NSS_WEEKLY_BITABLE_TABLE_ID` / `NSS_WEEKLY_BITABLE_VIEW_ID` | 覆盖问卷源 Base / table / view，独立于门店表配置 |
| `NSS_WEEKLY_CHAT_ID` | 覆盖群 chat_id |
| `NSS_WEEKLY_LINK_BASE` / `NSS_PUBLIC_BASE_URL` | 周报 / 全站下载链接基址；优先周报基址，均留空则生成站内相对链接 |
| `NSS_WEEKLY_DATA_DIR` | 周报输入快照与默认状态目录；不改变输出目录或现有提醒系统数据目录 |
| `NSS_WEEKLY_STATE_PATH` | 覆盖 `weekly_report.state_path`；相对路径以周报数据目录为基准，绝对路径可独立放置状态与锁 |
| `NSS_WEEKLY_SENDING_TIMEOUT_SECONDS` | 覆盖 `weekly_report.sending_timeout_seconds`，正整数秒数，默认 21600（6 小时） |
| `NSS_DMS_REGION_DB` | 现有 DMS 区域只读 SQLite 路径，也可通过 CLI `--region-db` 指定快照 |

公网基址仅写未入库的 `.env` / 本机 settings，不提交仓库。

### 持久化去重与并发保护

默认状态文件为 `data/weekly_report_state.json`，以报告的周一日期为键，例如：

```json
{
  "2026-10-19": {
    "status": "sent",
    "chat_id": "oc-local-example",
    "at": "2026-10-26T09:30:01+08:00",
    "message_id": "example-message"
  }
}
```

- 周报数据目录依次取 CLI `--data-dir`、`NSS_WEEKLY_DATA_DIR`、显式 `--sent-log` 的父目录、项目 `data/`。状态路径依次取 CLI `--state-path`、`NSS_WEEKLY_STATE_PATH`、`weekly_report.state_path`，默认文件名为 `weekly_report_state.json`。相对状态路径跟随数据目录；输入 JSON / DMS 快照本身保持只读。快照目录不可写时，用绝对 `--state-path` 指向独立可写目录。
- 默认锁文件为 `data/weekly_report.lock`；自定义状态路径时，锁固定为**状态文件同目录**的 `weekly_report.lock`。所有调用方必须使用相同状态路径，才能共享去重记录与锁。使用 `fcntl.flock(LOCK_EX | LOCK_NB)`，拿不到锁立即跳过并记录日志。检查周键、生成文件、发送和记录状态均在锁内；`--force` 也不能绕过锁。锁随句柄关闭 / 进程退出释放，锁文件保留，不因文件存在就判为占用。
- `sent` 永久阻止该周再次真实发送，即使重启或更换目标群也一样；`dry_run`、`failed` 不阻止真实发送。dry-run 可以重新生成文件，但不会覆盖已有 `sent` / `sending`，避免预览清除真实发送标记。
- 真实发送前，先原子落盘 `sending`；成功返回后**立即**落盘 `sent`，保存返回的 `message_id`（如有）。生成或发送抛出异常时记录 `failed`；已有 `sent` / `sending` 时保留原记录。成功发送后落盘异常或进程中断时，保留此前的 `sending`，不把不确定结果改成可立即重试的 `failed`。
- `sending` 在 `at` 起的 `sending_timeout_seconds` 内视为占用；默认 6 小时，到达时限后下一次调用才允许重试。未来时间或无法解析的时间仍视为占用。**超时不会主动补发**，且不能据此断定之前未送达；可先核实目标群，再手动调用 CLI。需提前清理时，停止相关周报调用、核实发送结果后，仅删除状态文件中的对应周键；保留其他周记录和锁文件。显式 `--force` 可跳过 `sent` / `sending` 判断。
- 每次状态更新都使用同目录唯一临时文件，写入后 `flush` + `fsync`，再 `os.replace` 并同步目录。替换前失败不会破坏旧状态；格式损坏的状态文件会报错，不能当成空状态继续发送。

调度器仅在配置的星期、小时、分钟匹配时尝试，进程内同日节流；持久化周键确保触发分钟内重启也不会重复真实发送。**错过触发分钟不自动补发**，失败或锁占用后也不自动追赶，可用下面的 CLI 手动补发。

### 本地生成与下载

```bash
python3 -m nss.weekly_report --week 2026-10-19 --dry-run
# 完全离线：同时提供发送日志和问卷 records API items JSON
python3 -m nss.weekly_report --week 2026-10-19 --dry-run \
  --sent-log /path/to/snapshot/sent_log.json --rows-json /path/to/nps_items.json \
  --data-dir /path/to/snapshot --out /path/to/output
# 手动补发（明确发送；与调度器共享周键去重和锁）
python3 -m nss.weekly_report --send --week 2026-10-19
# 核实后强制重发（跳过 sent / sending 去重，仍须获取锁）
python3 -m nss.weekly_report --send --week 2026-10-19 --force
```

`--week` 必须为周一，省略则为上一完整周。`--dry-run` / `--send` 互斥并覆盖配置中的发送开关；省略二者则沿用配置（默认 dry-run）。`--rows-json` 接受 records API 的 `[{record_id, fields}]`、fields 字典列表或 `{"items": [...]}`。未给 `--data-dir` / 环境变量时，提供 `--sent-log` 会自动使用其父目录补全车辆、门店。仅生成和发送逻辑会读取输入，去重 / 锁占用时在读取输入与访问 API 前返回；CLI 显示跳过原因并以 0 退出。

默认输出 `data/weekly_reports/YYYY-MM-DD_weekly.xlsx` 和 `YYYY-MM-DD_brief.txt`，产物不入 Git。Excel 包含「提醒明细」「未提醒但已填写」「汇总」三张表，汇总按天、大区、门店列出提醒数、填写数及填写率。简报包含周期、去重提醒/填写台数、大区 Top/Bottom、记录数与下载链接。

控制台「周报下载」或 `/weekly-reports` 可查看列表，`/weekly-reports/<文件名>` 下载 Excel。两者与现有控制台复用 **m-hero SSO 全局请求钩子及角色限制**，未加入公开白名单；`MHERO_AUTH_NSS=on` 时未登录会跳转登录。SSO 的 off/audit 行为与现有页面保持一致。`--out` 为本地验证目录，Web 仅展示默认 `data/weekly_reports/` 下的正式命名 Excel。

### 测试

共享 SSO 包需与控制台现有环境一样安装（开发环境可 `pip install -e ../m-hero-auth`），另安装 pytest：

```bash
python3 -m pytest -q
```

全套测试默认禁止真实 HTTP；周报测试覆盖自然周边界、VIN 去重、填写窗口、筛选、未提醒记录、Excel、错峰校验、调度、dry-run 与 SSO 登录下载，以及重启后的周键去重、并发锁、原子写失败、sending 超时、手动补发与强制重发。发送和拉取 API 均用 mock。

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
