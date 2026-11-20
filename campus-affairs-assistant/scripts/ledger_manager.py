#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校务小管家 · 事项台账管理脚本

在用户当前工作目录下维护《校务台账.json》，用于登记校务待办事项、
截止日期、材料清单与办理状态，并输出临期提醒与办理顺序规划。

命令一览（python 路径按实际技能目录替换）:
  add      登记事项   --item 必填  --deadline 必填(YYYY-MM-DD)
                     [--dept 部门] [--materials 材料清单] [--notes 备注] [--status 状态]
  list     查看台账   [--all]  默认仅显示未完成
  upcoming 临期提醒   [--days N]  默认 7 天内（含已过期）
  plan     办理顺序规划（按截止日期 + 材料准备时长排序）
  update   更新字段   --id 编号 [--status/--deadline/--dept/--materials/--notes]
  done     标记完成   --id 编号
  rm       删除条目   --id 编号（调用方须先取得用户确认）

材料准备预留天数启发式: 无材料 2 天; 有材料时 3 + 材料件数, 上限 14 天。
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

LEDGER_FILE = "校务台账.json"

DONE_STATES = ("已完成", "已取消")

# 状态机参考顺序（仅用于展示建议，update 允许任意中文状态）
SUGGESTED_STATES = ["待启动", "材料准备中", "已提交", "待领取结果", "已完成", "已取消"]


def load_ledger():
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "items" not in data:
            raise SystemExit("台账文件格式异常，请检查 %s" % LEDGER_FILE)
        if "next_id" not in data:
            data["next_id"] = (max([i.get("id", 0) for i in data["items"]] or [0]) + 1)
        return data
    return {"items": [], "next_id": 1}


def save_ledger(data):
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_deadline(raw):
    raw = str(raw).strip()
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$", raw)
    if not m:
        raise argparse.ArgumentTypeError(
            "日期格式应为 YYYY-MM-DD（例: 2026-11-30），不支持相对日期")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        raise argparse.ArgumentTypeError("日期不存在: %s" % raw)


def days_left(d):
    return (d - date.today()).days


def count_materials(materials):
    if not materials:
        return 0
    parts = re.split(r"[、,，;；/|\n]+", materials)
    return len([p for p in parts if p.strip()])


def prep_days(item):
    n = count_materials(item.get("材料清单", ""))
    if n == 0:
        return 2
    return min(3 + n, 14)


def fmt_deadline(item):
    d = parse_deadline(item["截止日期"])
    dl = days_left(d)
    if dl > 0:
        return "%s（剩 %d 天）" % (item["截止日期"], dl)
    if dl == 0:
        return "%s（今天截止）" % item["截止日期"]
    return "%s（已过期 %d 天）" % (item["截止日期"], -dl)


def urgency_tag(item):
    dl = days_left(parse_deadline(item["截止日期"]))
    if dl < 0:
        return "已过期"
    if dl == 0:
        return "今日截止"
    if dl <= 1:
        return "紧急"
    if dl <= 3:
        return "尽快"
    if dl <= 7:
        return "关注"
    return "正常"


def notes_cell(item):
    parts = [p for p in (item.get("材料清单", ""), item.get("备注", "")) if p]
    return " / ".join(parts) if parts else "—"


def cmd_add(args):
    data = load_ledger()
    item = {
        "id": data["next_id"],
        "事项": args.item,
        "截止日期": args.deadline.isoformat(),
        "状态": args.status or "待启动",
        "对接部门": args.dept or "",
        "材料清单": args.materials or "",
        "备注": args.notes or "",
        "登记时间": date.today().isoformat(),
    }
    data["items"].append(item)
    data["next_id"] += 1
    save_ledger(data)
    print("已登记: [%d] %s" % (item["id"], item["事项"]))
    print("截止: %s" % fmt_deadline(item))
    if item["材料清单"]:
        print("材料: %s" % item["材料清单"])
    dl = days_left(parse_deadline(item["截止日期"]))
    if dl < 0:
        print("警告: 该截止日期已过，请核实是否仍可补办。")
    else:
        start_by = parse_deadline(item["截止日期"])
        from datetime import timedelta
        start_by = start_by - timedelta(days=prep_days(item))
        if start_by <= date.today():
            print("提示: 建议立即启动材料准备（预留 %d 天不足）。" % prep_days(item))
        else:
            print("提示: 建议最迟 %s 启动材料准备（预留 %d 天）。"
                  % (start_by.isoformat(), prep_days(item)))


def cmd_list(args):
    data = load_ledger()
    items = data["items"]
    shown = [i for i in items if i["状态"] not in DONE_STATES] if not args.all else items
    if not shown:
        print("台账为空（未完成事项 0 条）。" if not args.all else "台账为空。")
        return
    shown = sorted(shown, key=lambda x: parse_deadline(x["截止日期"]))
    print("| 编号 | 事项 | 截止日期 | 剩余天数 | 紧急度 | 状态 | 对接部门 | 材料/备注 |")
    print("|---|---|---|---|---|---|---|---|")
    for i in shown:
        dl = days_left(parse_deadline(i["截止日期"]))
        dl_str = str(dl) if dl >= 0 else "过期%d天" % -dl
        dept = i.get("对接部门") or "—"
        print("| %d | %s | %s | %s | %s | %s | %s | %s |"
              % (i["id"], i["事项"], i["截止日期"], dl_str,
                 urgency_tag(i), i["状态"], dept, notes_cell(i)))
    unfinished = [i for i in items if i["状态"] not in DONE_STATES]
    overdue = [i for i in unfinished if days_left(parse_deadline(i["截止日期"])) < 0]
    soon = [i for i in unfinished
            if 0 <= days_left(parse_deadline(i["截止日期"])) <= 7]
    print()
    print("汇总: 未完成 %d 条；7 天内截止 %d 条；已过期 %d 条。"
          % (len(unfinished), len(soon), len(overdue)))
    if overdue:
        print("注意: 存在已过期事项，建议尽快联系对接部门说明情况并询问补办渠道。")


def cmd_upcoming(args):
    data = load_ledger()
    unfinished = [i for i in data["items"] if i["状态"] not in DONE_STATES]
    hits = [i for i in unfinished
            if days_left(parse_deadline(i["截止日期"])) <= args.days]
    if not hits:
        print("未来 %d 天内无截止事项，台账运行良好。" % args.days)
        return
    hits = sorted(hits, key=lambda x: parse_deadline(x["截止日期"]))
    print("未来 %d 天内（含已过期）共 %d 条待办：" % (args.days, len(hits)))
    print()
    print("| 编号 | 事项 | 截止日期 | 剩余天数 | 紧急度 | 状态 |")
    print("|---|---|---|---|---|---|")
    for i in hits:
        dl = days_left(parse_deadline(i["截止日期"]))
        dl_str = str(dl) if dl >= 0 else "过期%d天" % -dl
        print("| %d | %s | %s | %s | %s | %s |"
              % (i["id"], i["事项"], i["截止日期"], dl_str,
                 urgency_tag(i), i["状态"]))
    print()
    for i in hits:
        print("- [%d] %s: %s" % (i["id"], i["事项"], fmt_deadline(i)))


def cmd_plan(args):
    data = load_ledger()
    unfinished = [i for i in data["items"] if i["状态"] not in DONE_STATES]
    if not unfinished:
        print("当前无未完成事项，无需规划。")
        return
    from datetime import timedelta
    ranked = sorted(unfinished, key=lambda x: parse_deadline(x["截止日期"]))
    print("办理顺序建议（按截止日期先后，材料多的预留更长准备时间）:")
    print()
    order = 0
    for i in ranked:
        order += 1
        dl_date = parse_deadline(i["截止日期"])
        prep = prep_days(i)
        start_by = dl_date - timedelta(days=prep)
        if start_by <= date.today():
            advice = "立即启动（预留 %d 天已不足）" % prep
        else:
            advice = "最迟 %s 启动（预留 %d 天）" % (start_by.isoformat(), prep)
        print("%d. [%d] %s | 截止 %s | %s | 状态: %s"
              % (order, i["id"], i["事项"], i["截止日期"], advice, i["状态"]))
        if i.get("材料清单"):
            print("   需备材料: %s" % i["材料清单"])
    print()
    print("提示: 完成一件标记 done 后再办理下一件；临期事项优先于长周期事项。")


def cmd_update(args):
    data = load_ledger()
    for i in data["items"]:
        if i["id"] == args.id:
            if args.status is not None:
                i["状态"] = args.status
            if args.deadline is not None:
                i["截止日期"] = args.deadline.isoformat()
            if args.dept is not None:
                i["对接部门"] = args.dept
            if args.materials is not None:
                i["材料清单"] = args.materials
            if args.notes is not None:
                i["备注"] = args.notes
            save_ledger(data)
            print("已更新: [%d] %s" % (i["id"], i["事项"]))
            print("当前: 截止 %s | 状态 %s" % (fmt_deadline(i), i["状态"]))
            return
    raise SystemExit("未找到编号 %d 的事项，可用 list 查看。" % args.id)


def cmd_done(args):
    data = load_ledger()
    for i in data["items"]:
        if i["id"] == args.id:
            i["状态"] = "已完成"
            save_ledger(data)
            print("已完成并归档: [%d] %s" % (i["id"], i["事项"]))
            return
    raise SystemExit("未找到编号 %d 的事项。" % args.id)


def cmd_rm(args):
    data = load_ledger()
    for idx, i in enumerate(data["items"]):
        if i["id"] == args.id:
            removed = data["items"].pop(idx)
            save_ledger(data)
            print("已删除: [%d] %s（该操作不可撤销）" % (removed["id"], removed["事项"]))
            return
    raise SystemExit("未找到编号 %d 的事项。" % args.id)


def build_parser():
    p = argparse.ArgumentParser(
        description="校务小管家·事项台账（数据文件: %s，保存在当前工作目录）" % LEDGER_FILE)
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("add", help="登记事项")
    a.add_argument("--item", required=True, help="事项名称，如: 奖助学金申报")
    a.add_argument("--deadline", required=True, type=parse_deadline,
                    help="截止日期 YYYY-MM-DD")
    a.add_argument("--dept", help="对接部门")
    a.add_argument("--materials", help="材料清单，顿号或逗号分隔")
    a.add_argument("--notes", help="备注")
    a.add_argument("--status", help="初始状态，默认 待启动")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="查看台账")
    l.add_argument("--all", action="store_true", help="含已完成/已取消")
    l.set_defaults(func=cmd_list)

    u = sub.add_parser("upcoming", help="临期提醒")
    u.add_argument("--days", type=int, default=7, help="N 天内截止，默认 7")
    u.set_defaults(func=cmd_upcoming)

    g = sub.add_parser("plan", help="办理顺序规划")
    g.set_defaults(func=cmd_plan)

    d = sub.add_parser("update", help="更新字段")
    d.add_argument("--id", required=True, type=int, help="事项编号")
    d.add_argument("--status", help="新状态")
    d.add_argument("--deadline", type=parse_deadline, help="新截止日期")
    d.add_argument("--dept", help="新对接部门")
    d.add_argument("--materials", help="新材料清单")
    d.add_argument("--notes", help="新备注")
    d.set_defaults(func=cmd_update)

    k = sub.add_parser("done", help="标记完成")
    k.add_argument("--id", required=True, type=int, help="事项编号")
    k.set_defaults(func=cmd_done)

    r = sub.add_parser("rm", help="删除条目（须先取得用户确认）")
    r.add_argument("--id", required=True, type=int, help="事项编号")
    r.set_defaults(func=cmd_rm)
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(0)
    if hasattr(args, "days") and args.days <= 0:
        raise SystemExit("--days 须为正整数")
    args.func(args)


if __name__ == "__main__":
    main()
