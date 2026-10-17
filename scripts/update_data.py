# -*- coding: utf-8 -*-
"""
数据打包 / 换年份更新工具
--------------------------
把「职位表 + 历年竞争数据 + 历年进面分」压成 skill 内自带的数据包。

用法：
  # 首次打包（从工作目录导入）
  python update_data.py --src "C:/path/to/国考2027" --year 2027

  # 明年换新岗位表时
  python update_data.py --positions new_all.json --year 2028

产物（写入 ../data/）：
  positions_<year>.json.gz          精简后的职位表
  rank_<y1>_<y2>.json.gz            历年报名人数榜（按年分组）
  scores_<prov>.json.gz              该省历年进面分数线
  MANIFEST.md                        数据体检报告
"""
import argparse, gzip, json, os, re, statistics, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

# 职位表里真正参与筛选/展示的字段
KEEP = [
    "部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位属性",
    "职位分布", "职位简介", "职位代码", "机构层级", "考试类别", "招考人数",
    "专业", "学历", "学位", "政治面貌", "基层工作最低年限",
    "服务基层项目工作经历", "是否在面试阶段组织专业能力测试",
    "面试人员比例", "工作地点", "落户地点", "备注",
]


def dump_gz(obj, path):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(raw)
    return len(raw)


def slim_positions(rows):
    out = []
    for a in rows:
        d = {k: a.get(k, "") for k in KEEP}
        d["招考人数"] = str(d["招考人数"]).strip()
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="现有工作目录（含 all2027.json / rank*.json / score_henan_*.json）")
    ap.add_argument("--positions", help="单独的职位表 json（换年份时用）")
    ap.add_argument("--year", type=int, default=2027)
    ap.add_argument("--prov", default="henan", help="进面分所属省份代码")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    report = []

    # ---------- 1. 职位表 ----------
    src_pos = args.positions or (os.path.join(args.src, f"all{args.year}.json") if args.src else None)
    if src_pos and os.path.exists(src_pos):
        rows = json.load(open(src_pos, encoding="utf-8"))
        slim = slim_positions(rows)
        n = len(slim)
        raw_b = dump_gz(slim, os.path.join(DATA, f"positions_{args.year}.json.gz"))
        gz_b = os.path.getsize(os.path.join(DATA, f"positions_{args.year}.json.gz"))
        report.append(f"- 职位表 {args.year}：{n} 条，{raw_b/1048576:.1f}MB → {gz_b/1048576:.2f}MB")
        # 体检
        miss = sum(1 for d in slim if not d["专业"])
        report.append(f"  - 专业字段空值 {miss} 条")
        report.append(f"  - 部门 {len(set(d['部门名称'] for d in slim))} 个 / 单位 {len(set(d['用人司局'] for d in slim))} 个")
    else:
        if src_pos:
            report.append(f"- ⚠ 未找到职位表 {src_pos}")

    # ---------- 2. 历年竞争数据 ----------
    if args.src:
        years = {}
        for y in range(2020, args.year + 1):
            p = os.path.join(args.src, f"rank{y}.json")
            if not os.path.exists(p):
                continue
            rows = json.load(open(p, encoding="utf-8"))
            keep = []
            for r in rows:
                if not r.get("unit") or not r.get("pos"):
                    continue
                keep.append({
                    "unit": r["unit"], "pos": r["pos"],
                    "hire": int(r.get("hire") or 0),
                    "apply": int(r.get("apply") or 0),
                    "pass": int(r.get("pass") or 0),
                    "prov": r.get("prov", ""),
                })
            years[y] = keep
        if years:
            ys = sorted(years)
            p = os.path.join(DATA, f"rank_{ys[0]}_{ys[-1]}.json.gz")
            dump_gz(years, p)
            gz_b = os.path.getsize(p)
            tot = sum(len(v) for v in years.values())
            report.append(f"- 历年竞争数据：{len(ys)} 年（{ys[0]}–{ys[-1]}）共 {tot} 条 → {gz_b/1048576:.2f}MB")
            for y in ys:
                ap_ = [r["apply"] for r in years[y] if r["apply"] > 0]
                report.append(f"  - {y}：{len(years[y])} 条，报名数中位 {statistics.median(ap_) if ap_ else 0:.0f}")

    # ---------- 3. 进面分 ----------
    if args.src:
        scores = {}
        for f in sorted(glob.glob(os.path.join(args.src, f"score_{args.prov}_*.json"))):
            m = re.search(r"(\d{4})\.json$", f)
            if not m:
                continue
            y = int(m.group(1))
            rows = json.load(open(f, encoding="utf-8"))
            clean = []
            for r in rows:
                try:
                    sc = float(r.get("score") or 0)
                except (TypeError, ValueError):
                    continue
                if sc <= 0 or not r.get("unit"):
                    continue
                clean.append({
                    "unit": r["unit"], "pos": r.get("pos", ""),
                    "code": r.get("code", ""), "hire": str(r.get("hire", "")),
                    "apply": str(r.get("apply", "")), "score": round(sc, 1),
                })
            if clean:
                scores[y] = clean
        if scores:
            ys = sorted(scores)
            p = os.path.join(DATA, f"scores_{args.prov}.json.gz")
            dump_gz(scores, p)
            gz_b = os.path.getsize(p)
            report.append(f"- 进面分（{args.prov}）：{len(ys)} 年共 {sum(len(v) for v in scores.values())} 条 → {gz_b/1048576:.2f}MB")

    # ---------- 4. MANIFEST ----------
    man = os.path.join(DATA, "MANIFEST.md")
    old = open(man, encoding="utf-8").read() if os.path.exists(man) else ""
    body = "\n".join(report)
    txt = f"""# 数据包说明

本目录是 skill 自带的离线数据，**不需要联网**即可完成筛选与量化。
所有数字均可追溯：职位表来自官方职位表 Excel；竞争数据与进面分来自公开的历年报名统计与面试名单。

## 本次打包
{body}

## 口径

- `rank_*.json.gz`：`apply`＝报名人数，`hire`＝招录人数，竞争比 = apply / hire。
  同一(单位, 岗位名)可能有多条记录（不同专业组），**匹配时必须带招录人数或做去序号处理**。
- `scores_*.json.gz`：该省历年「进面最低分」，200 分制。金融监管/证监/公安/边检是百分制，不可混比。
- `positions_*.json.gz`：官方职位表精简版，只保留参与筛选与展示的 23 个字段。

## 更新方式

明年岗位表发布后：

```bash
python scripts/update_data.py --positions 新职位表.json --year 2028
python scripts/update_data.py --src 新工作目录 --year 2028
```
"""
    open(man, "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
