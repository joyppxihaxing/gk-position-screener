# -*- coding: utf-8 -*-
"""报名期实时数据抓取：华图 2027 国考职位报名榜（972 页，链接尾部12位=职位代码）

用法：
    python fetch_rank2027_live.py --out rank2027_live.json
    # 每天一次，存档带日期：--out rank2027_live_1024.json
"""
import argparse, json, re, time, random, urllib.request, concurrent.futures as cf

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.37",
      "Referer": "https://hb.huatu.com/zw/rank/"}
URL = "https://hb.huatu.com/zw/rank/index.php?act=bmrs&page={pg}"
MAXP = 1100


def get(u, timeout=25):
    d = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
    try:
        return d.decode("gb18030")
    except Exception:
        return d.decode("utf-8", "replace")


def parse(t):
    out = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        tr = m.group(1)
        link = re.search(r'href="[^"]*?(\d{18})\.html"[^>]*>\s*详', tr)
        c = [re.sub(r"<[^>]+>", "", x).replace("&nbsp;", " ").strip()
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if not link or len(c) < 6 or c[0] == "地区":
            continue

        def n(x):
            mm = re.match(r"^(\d+)", str(x).replace(",", ""))
            return int(mm.group(1)) if mm else None

        out.append({"prov": c[0], "dept": c[1], "pos": c[2], "hire": n(c[3]),
                    "apply": n(c[4]), "ratio": n(c[5]) or 0, "code": link.group(1)[-12:]})
    return out


def one(pg):
    try:
        return pg, parse(get(URL.format(pg=pg)))
    except Exception as e:
        return pg, f"ERR {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="rank2027_live.json")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rows, errs = [], []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for pg, r in ex.map(one, range(1, MAXP + 1)):
            if isinstance(r, str):
                errs.append((pg, r))
            else:
                rows += r
    print(f"rows={len(rows)} errors={len(errs)}")
    if errs:
        print(errs[:5])
    json.dump(rows, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    print("saved", args.out)


if __name__ == "__main__":
    main()
