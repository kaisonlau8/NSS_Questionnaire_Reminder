#!/usr/bin/env python3
"""导入车辆档案 Excel（新版「客户车辆关系」导出），整表覆盖 data/vehicles.json。"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nss.paths import VEHICLES_PATH  # noqa: E402
from nss.time_utils import beijing_strftime  # noqa: E402
from nss.vehicles import parse_excel, save_vehicles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="导入车辆档案 Excel，写入前自动备份 data/vehicles.json")
    parser.add_argument("xlsx", type=Path, help="Excel 文件路径（.xlsx）")
    parser.add_argument("--dry-run", action="store_true", help="只解析并打印统计，不写入")
    args = parser.parse_args()

    path: Path = args.xlsx
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1
    parsed = parse_excel(path)
    stats = parsed["stats"]
    print(
        f"解析 {path.name}: 总行 {stats['total']} · 导入 {stats['imported']}"
        f" · 无创建时间跳过 {stats['skipped_no_date']} · 重复 VIN {stats['duplicates']}"
    )
    if args.dry_run:
        print("dry-run：未写入任何文件")
        return 0
    if VEHICLES_PATH.exists():
        backup = VEHICLES_PATH.with_name(f"vehicles.json.bak-{beijing_strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(VEHICLES_PATH, backup)
        print(f"已备份 {backup.name}")
    payload = save_vehicles(parsed["vehicles"], source=str(path))
    print(f"已写入 {VEHICLES_PATH}（{payload['count']} 台）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
