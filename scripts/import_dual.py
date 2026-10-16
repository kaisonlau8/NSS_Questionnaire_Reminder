#!/usr/bin/env python3
"""双文件导入车辆档案：客户车辆关系（DMS）+ 车辆交付明细（数据门户），按 VIN 关联。

统计 JSON 打到 stdout，进度信息打到 stderr；--dry-run 不写 data/vehicles.json。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nss.paths import VEHICLES_PATH  # noqa: E402
from nss.time_utils import beijing_strftime  # noqa: E402
from nss.vehicles import import_dual  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="双文件导入（按 VIN 关联），写入前自动备份 data/vehicles.json"
    )
    parser.add_argument("relation", type=Path, help="客户车辆关系（DMS 导出）.xlsx")
    parser.add_argument("delivery", type=Path, help="车辆交付明细（数据门户导出）.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="只解析并打印统计 JSON，不写入")
    args = parser.parse_args()

    for path in (args.relation, args.delivery):
        if not path.is_file():
            print(f"文件不存在: {path}", file=sys.stderr)
            return 1
    if not args.dry_run and VEHICLES_PATH.exists():
        backup = VEHICLES_PATH.with_name(f"vehicles.json.bak-{beijing_strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(VEHICLES_PATH, backup)
        print(f"已备份 {backup.name}", file=sys.stderr)
    try:
        result = import_dual(args.relation, args.delivery, dry_run=args.dry_run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    if not args.dry_run:
        print(f"已写入 {VEHICLES_PATH}（{result.get('count')} 台）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
