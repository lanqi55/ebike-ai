"""Local Swagger lab. Run from the repository with python -m scripts.work_order_demo."""

import argparse
import json
from pathlib import Path

from ebike_ai.database import DatabaseConfig
from test_cases.mysql_work_orders import WorkOrderLab


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare isolated Swagger practice data and clean up on Enter")
    parser.add_argument("--run-db", action="store_true", help="Explicitly allow writes to ebike_ai_day11")
    args = parser.parse_args(argv)
    if not args.run_db:
        parser.error("--run-db is required; no database operation was performed")

    try:
        lab = WorkOrderLab(DatabaseConfig.from_env(),
                           Path(__file__).resolve().parents[1] / "reports" / "week3" / "manifests")
    except Exception:
        print("练习库配置不可用。请在本机配置 EBIKE_DB_*，仅允许 ebike_ai_day11；不要分享密码。")
        return 1
    result = 0
    try:
        lab.prepare()
        for index in (0, 1):
            fields = lab.order(index=index, battery_id=lab.records["battery"][0]["id"] if index else None)
            print(f"\nPOST /work-orders 示例 {index + 1}（请原样提交；不要修改内容）：")
            print(json.dumps(fields, ensure_ascii=False, indent=2))
        print(f"\n运行清单：{lab.manifest_path}")
        print("在另一个已配置数据库的终端启动 API；完成 Swagger 创建、查询和重复提交实验。")
        input("完成后返回这里按 Enter，核对并清理本次演示数据：")
        for index, record in enumerate(lab.records["work_order"]):
            row = lab.find_order(record["work_order_no"])
            if row is not None:
                lab.remember_order_id(row["id"], index=index)
    except (KeyboardInterrupt, EOFError):
        print("\n演示中断，尝试精确清理本次数据。")
        result = 1
    except Exception:
        print("演示准备或核对失败；底层详情不输出，请核对本机数据库和运行清单。")
        result = 1
    finally:
        try:
            lab.cleanup()
            print("清理流程完成；未使用的编号无记录，已使用编号经新连接核对无残留。")
        except Exception:
            print(f"清理失败，请保留并核对清单：{lab.manifest_path}；不要清空表或扩大删除范围。")
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
