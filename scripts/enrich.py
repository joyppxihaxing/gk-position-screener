# -*- coding: utf-8 -*-
"""
enrich.py —— 给可报岗位补上「地市 / 五年竞争比 / 历年进面线 / 条件核对表」
=====================================================================
用法：
  python enrich.py --screened screened.json --profile profile.json --out filter_data.json

输出给 build_html.py 用的扁平结构，字段含义见 references/data-dictionary.md
"""
import argparse, json, os, re, statistics, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gk_lib as L

DATA = os.path.join(HERE, "..", "data")
MUNI = {"北京", "天津", "上海", "重庆"}


def split_loc(pl, prov):
    """'河南省平顶山市湛河区' → ('平顶山市', '湛河区')"""
    s = (pl or "").strip()
    if not s:
        return ("—", "")
    if prov in MUNI:
        rest = re.sub(r"^%s市?" % prov, "", s)
        return (prov + "市", rest)
    m = re.match(r"^(.+?(?:省|自治区|特别行政区))", s)
    rest = s[m.end():] if m else s
    if prov in MUNI:
        return (prov + "市", rest)
    m2 = re.match(r"^(.+?(?:市|自治州|地区|盟))", rest)
    if m2:
        return (m2.group(1), rest[m2.end():])
    city = rest.replace("省直辖县级行政区划", "省直辖") or "省直属"
    return (city, "")


def norm_pos(p):
    return re.sub(r"[（(][一二三四五六七八九十]{1,2}[）)]", "", p).strip()


def build_hist(rows_by_year, u, pos):
    """返回 [[年, 竞争比, 招录, 报名, 精确?], ...]"""
    out = []
    np_ = norm_pos(pos)
    for y in sorted(rows_by_year):
        rs = rows_by_year[y].get(u, [])
        pick, exact = None, True
        ex = [r for r in rs if r["pos"] == pos and r["apply"] > 0 and r["hire"] > 0]
        if ex:
            pick = ex[0]
        else:
            w = [r for r in rs if norm_pos(r["pos"]) == np_ and r["apply"] > 0 and r["hire"] > 0]
            if len(w) == 1:
                pick, exact = w[0], False
        if pick:
            out.append([y, round(pick["apply"] / pick["hire"], 1), pick["hire"],
                        pick["apply"], 1 if exact else 0])
    return out


def hen_scores(scores, u, pos):
    """该省历年进面分：精确匹配 → 单位级中位兜底"""
    for y, rows in scores.items():
        pass
    hit = {}
    for y, rows in scores.items():
        ex = [r for r in rows if r["unit"] == u and r["pos"] == pos]
        if ex:
            hit[y] = ex[0]["score"]
    if hit:
        return hit
    for y, rows in scores.items():
        same = [r["score"] for r in rows if r["unit"] == u]
        if same:
            hit[y] = round(statistics.median(same), 1)
    return hit


def checks(a, prof, o, year):
    """12 项条件核对表：[[状态, 标签, 显示值], ...]  状态 ok/warn/no"""
    rmk = a.get("备注") or ""
    ck = []

    edu = a.get("学历") or ""
    ck.append(("ok" if L.edu_ok(edu, prof.get("edu_level", "本科")) else "no", "学历", edu or "不限"))

    deg = a.get("学位") or "无要求"
    ck.append(("ok" if L.degree_ok(deg, prof.get("degree", "")) else "no", "学位", deg))

    ok, why = L.major_ok(a.get("专业"), prof)
    ck.append(("ok" if ok else "no", "专业", why))

    pol = a.get("政治面貌") or "不限"
    ck.append(("ok" if L.politics_ok(pol, prof.get("politics", "")) else "no", "政治面貌", pol))

    ok, why = L.fresh_ok(rmk, prof.get("fresh"), year)
    ck.append(("ok" if ok else "no", "应届要求", "不限应届" if ok else "限应届"))

    ok, why = L.gender_ok(rmk, prof.get("gender", ""))
    ck.append(("ok" if ok else "no", "性别", why or "不限"))

    ok, why = L.hukou_ok(rmk, prof.get("hukou_prov"), prof.get("hukou_city"))
    ck.append(("ok" if ok else "no", "户籍/生源", why or "不限"))

    jc = a.get("基层工作最低年限") or "无限制"
    gy = prof.get("grassroots_years", 0)
    ck.append(("ok" if L.grassroots_ok(jc, gy) else "no", "基层年限",
               f"{jc}（你有 {gy} 年）" if jc not in ("", "无限制") else "无限制"))

    pok = L.project_ok(a.get("服务基层项目工作经历"), prof.get("identities", []))
    ck.append(("ok" if pok else "no", "服务项目",
               "无限制" if pok else "、".join(L.project_req_names(a.get("服务基层项目工作经历"))) or "定向"))

    svc = "最低服务年限" in rmk or "服务期" in rmk
    ck.append(("warn" if svc else "ok", "最低服务期", "本单位 5 年" if svc else "无"))

    ok, why = L.cert_ok(rmk, prof.get("certs", {}))
    ck.append(("ok" if ok else "no", "证书要求", "不要求" if ok else why))

    if a.get("是否在面试阶段组织专业能力测试") == "是":
        ck.append(("warn", "专业能力测试", "面试加试"))
    else:
        ck.append(("ok", "专业能力测试", "无"))

    return ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screened", default="screened.json")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default="filter_data.json")
    ap.add_argument("--data", default=DATA)
    args = ap.parse_args()

    ds = L.load_dataset(args.data)
    prof = json.load(open(args.profile, encoding="utf-8"))
    year = ds["year"]
    screened = json.load(open(args.screened, encoding="utf-8"))

    # 按年分组，便于按单位查
    by_year = {}
    for y, rows in ds["ranks"].items():
        d = defaultdict(list)
        for r in rows:
            d[r["unit"]].append(r)
        by_year[y] = d

    rows = []
    for o in screened:
        a = o["a"]
        prov = (a.get("工作地点") or "")[:2]
        city, cty = split_loc(a.get("工作地点"), prov)
        rmk = a.get("备注") or ""
        hist = build_hist(by_year, a["用人司局"], a["招考职位"])
        hs = hen_scores(ds["scores"], a["用人司局"], a["招考职位"]) if ds["scores"] else {}
        iv = a.get("面试人员比例") or "3:1"
        m = re.match(r"(\d+)", iv)
        k = int(m.group(1)) if m else 3
        hire = o["hire"]

        rows.append(dict(
            u=a["用人司局"], p=a["招考职位"], prov=prov, pl=a.get("工作地点", ""),
            city=city, cty=cty, hire=hire,
            N=o["N"], ratio=o["ratio"], score=o["score"], conf=o["conf"], src=o["src"],
            dept=a.get("部门代码", ""), code=a.get("职位代码", ""),
            pro=a.get("专业", ""), rmk=rmk, jc=a.get("基层工作最低年限", ""),
            cat=(a.get("考试类别") or "")[:6],
            pct=o["pct"],
            cet4=bool(re.search(r"四级|CET-?4", rmk)),
            svc=("服务年限" in rmk or "服务期" in rmk),
            test=(a.get("是否在面试阶段组织专业能力测试") == "是"),
            edu=a.get("学历", ""), deg=a.get("学位", ""), pol=a.get("政治面貌", ""),
            iv=iv, adv=k * hire,
            loc=a.get("工作地点", ""), luo=a.get("落户地点", ""),
            h=hist, stale=("疑不限专业" in (o["src"] or "")),
            hs=hs,
            hsa=round(sorted(hs.values())[len(hs) // 2], 1) if hs else None,
            ck=checks(a, prof, o, year),
        ))

    rows.sort(key=lambda x: (x["pct"], x["ratio"]))
    json.dump(rows, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"补全 {len(rows)} 个岗位 → {args.out}")
    print(f"  有历史竞争比：{sum(1 for r in rows if r['h'])}")
    print(f"  有 3 年以上：{sum(1 for r in rows if len(r['h']) >= 3)}")
    print(f"  有实测进面线：{sum(1 for r in rows if r['hs'])}")
    print(f"  地市：{len(set((r['prov'], r['city']) for r in rows))} 个")
    print(f"  省份分布：{Counter(r['prov'] for r in rows).most_common(6)}")


if __name__ == "__main__":
    main()
