# -*- coding: utf-8 -*-
"""
build_html.py —— 把 filter_data.json + 画像 渲染成一个自包含的 HTML 筛选器
=====================================================================
用法：
  python build_html.py --data filter_data.json --profile profile.json \
                       --out "2027国考-全国岗位筛选器.html"

产物是单个 HTML 文件（数据内嵌，双击即开，不依赖网络和本地服务）。
"""
import argparse, json, os, re, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import gk_lib as L


def make_tags(prof):
    """顶部画像标签"""
    tags = []
    edu = prof.get("edu_level", "")
    deg = prof.get("degree", "")
    if edu:
        tags.append(f"{edu}" + (f" · {deg}" if deg else ""))
    name = prof.get("major_name", "")
    cls = "、".join(prof.get("major_classes", []))
    code = prof.get("major_code", "")
    major = " · ".join(x for x in (name, cls) if x)
    if major:
        tags.append(major + (f" {code}" if code else ""))
    if prof.get("politics"):
        tags.append(prof["politics"])
    if prof.get("gender"):
        tags.append(prof["gender"])
    tags.append("应届" if prof.get("fresh") else "非应届")
    ids = prof.get("identities", [])
    if "退役士兵" in ids:
        y = prof.get("military_years", 0)
        tags.append(f"退役士兵 · {y}年" if y else "退役士兵")
    for k in ("三支一扶", "西部计划", "特岗教师", "大学生村官"):
        if k in ids:
            tags.append(k)
    if prof.get("hukou_prov"):
        tags.append(prof["hukou_prov"] + "户籍")
    gy = prof.get("grassroots_years", 0)
    tags.append(f"基层 {gy} 年" if gy else "无基层年限")
    c = prof.get("certs", {})
    if c.get("cet6"):
        tags.append("六级")
    elif c.get("cet4"):
        tags.append("四级")
    else:
        tags.append("无四六级")
    return "".join(f"<span>{t}</span>" for t in tags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="filter_data.json")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default="国考岗位筛选器.html")
    ap.add_argument("--title", default="")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    args = ap.parse_args()

    rows = json.load(open(args.data, encoding="utf-8"))
    prof = json.load(open(args.profile, encoding="utf-8"))
    ds = L.load_dataset(args.data_dir)
    total = len(ds["positions"])
    year = ds["year"]

    provs = len(set(r["prov"] for r in rows))
    cities = len(set((r["prov"], r["city"]) for r in rows))
    subtitle = f"{total} → {len(rows)} 个可报 · {provs} 省 {cities} 市"

    # 进面分数据覆盖的省份（只用于 footer 文案）
    score_prov = {True: "河南", False: "本省"}[len(ds["scores"]) > 0]

    tpl = open(os.path.join(ROOT, "assets", "filter_template.html"), encoding="utf-8").read()

    data_js = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = args.title or f"{year}国考 · 全国岗位筛选器"

    out = (tpl
           .replace("__DATA__", data_js)
           .replace("__TITLE__", title)
           .replace("__YEAR__", str(year))
           .replace("__SUBTITLE__", subtitle)
           .replace("__TAGS__", make_tags(prof))
           .replace("__HOME_PROV__", prof.get("hukou_prov") or rows[0]["prov"])
           .replace("__SCORE_PROV__", score_prov))

    left = re.findall(r"__[A-Z_]{3,}__", out)
    assert not left, f"还有未替换的占位符：{set(left)}"
    open(args.out, "w", encoding="utf-8").write(out)
    print(f"已生成 {args.out}  {len(out)/1024:.0f} KB / {len(rows)} 个岗位")
    print(f"  画像：{re.sub('<[^>]+>', ' · ', make_tags(prof)).strip(' ·')}")
    print(f"  省份分布：{Counter(r['prov'] for r in rows).most_common(5)}")


if __name__ == "__main__":
    main()
