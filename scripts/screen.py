# -*- coding: utf-8 -*-
"""
screen.py —— 画像 × 职位表 → 可报岗位池（含竞争比预测）
=====================================================
用法：
  python screen.py --profile profile.json --out screened.json
  python screen.py --profile profile.json --explain      # 看每个岗位被什么卡掉

输入：
  data/positions_YYYY.json.gz    职位表
  data/rank_YYYY_YYYY.json.gz    历年竞争数据
  profile.json                   考生画像

输出：
  screened.json                  可报岗位 + 预测竞争比 / 预估进面线 / 置信度
"""
import argparse, json, os, re, statistics, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gk_lib as L

DATA = os.path.join(HERE, "..", "data")


# ============================================================ 预测模型
W = {}                      # 年度权重，运行时按「距今远近」生成
BETA = 0.36                 # 招录→报名 组内弹性（5 年实测 0.17–0.53，中位 0.36）
GROW = 1.05                 # 年度报名自然增长


def build_weights(years, latest):
    out = {}
    for y in years:
        d = latest - y
        out[y] = [3.0, 2.0, 1.5, 1.0, 1.0].__getitem__(min(d, 4))
    return out


def openness(a, year):
    """开放度系数：该岗在同一单位内的报名份额倾向"""
    pro = a.get("专业") or ""
    rmk = a.get("备注") or ""
    k = 1.0
    if "不限" in pro:
        k *= 2.0
    else:
        ug, _ = L.split_major(pro)
        cnt = len(re.findall(r"[^、，,]+类", ug))
        if cnt >= 8:
            k *= 1.35
        elif cnt >= 4:
            k *= 1.12
        elif cnt <= 2:
            k *= 0.95
    if re.search(r"应届", rmk) and not re.search(r"非应届|不限应届", rmk):
        k *= 0.72
    if re.search(r"男性|限男|女性|限女", rmk):
        k *= 0.88
    return k


def norm_pos(pos):
    return re.sub(r"[（(][一二三四五六七八九十]{1,2}[）)]", "", pos).strip()


class Model:
    def __init__(self, positions, ranks):
        self.A = positions
        self.U = {}
        for y, rows in ranks.items():
            for r in rows:
                self.U.setdefault(r["unit"], {}).setdefault(y, []).append(r)
        self.years = sorted(ranks.keys())
        self.latest = max(self.years) if self.years else 0
        global W
        W = build_weights(self.years, self.latest)
        self.N27 = Counter(a["用人司局"] for a in positions)
        self.P27 = Counter()
        for a in positions:
            try:
                self.P27[a["用人司局"]] += int(a["招考人数"])
            except (TypeError, ValueError):
                self.P27[a["用人司局"]] += 1
        self._prov_fallback()

    # ---------- 单位基线 ----------
    def unit_baseline(self, u):
        if u not in self.U:
            return None
        ys = [y for y in self.U[u] if y in W]
        if not ys:
            return None
        ws = sum(W[y] for y in ys)
        T = sum(sum(r["apply"] for r in self.U[u][y]) * W[y] for y in ys) / ws
        P = sum(sum(r["hire"] for r in self.U[u][y]) * W[y] for y in ys) / ws
        return T, P

    # ---------- 无历史单位的兜底 ----------
    def _prov_fallback(self):
        pool = defaultdict(list)
        for a in self.A:
            u = a["用人司局"]
            if u in self.U and self.latest in self.U[u]:
                rs = self.U[u][self.latest]
                tot = sum(r["apply"] for r in rs)
                if tot > 0:
                    pool[(a.get("工作地点") or "")[:2]].append(tot / len(rs))
        self.prov_med = {p: statistics.median(v) for p, v in pool.items() if len(v) >= 8}
        allv = [x for v in pool.values() for x in v]
        self.glob_med = statistics.median(allv) if allv else 90

    def same_count(self, u, np_):
        return sum(1 for x in self.A if x["用人司局"] == u and norm_pos(x["招考职位"]) == np_)

    def last_same(self, a):
        """最近一年同名岗位的实测： (年, 报名, 招录, 单位当年招录, 单位当年报名, 精确?)"""
        u, pos = a["用人司局"], a["招考职位"]
        np_ = norm_pos(pos)
        for y in sorted(self.years, reverse=True):
            rs = self.U.get(u, {}).get(y, [])
            if not rs:
                continue
            ex = [r for r in rs if r["pos"] == pos and r["apply"] > 0]
            if ex:
                r = ex[0]
                return (y, r["apply"], r["hire"], sum(x["hire"] for x in rs),
                        sum(x["apply"] for x in rs), True)
            w = [r for r in rs if norm_pos(r["pos"]) == np_ and r["apply"] > 0]
            if len(w) == 1:
                r = w[0]
                return (y, r["apply"], r["hire"], sum(x["hire"] for x in rs),
                        sum(x["apply"] for x in rs), False)
        return None

    # ---------- 预测 ----------
    def predict(self, a):
        u = a["用人司局"]
        try:
            hire = int(a["招考人数"])
        except (TypeError, ValueError):
            hire = 1
        hire = max(1, hire)
        base = self.unit_baseline(u)
        n27 = self.N27[u] or 1
        p27 = self.P27[u] or n27
        prior = 1.0 / n27
        limited = "不限" not in (a.get("专业") or "")
        Ls = self.last_same(a)
        N, conf, src, y0 = None, "D", "无历史", None

        if Ls:
            y0, ap0, h0, P0, T0, exact = Ls
            share0 = ap0 / T0 if T0 else 1.0
            if share0 > 0.6 and n27 >= 3 and limited and base:
                T, Pb = base
                T27 = T * (p27 / Pb) ** BETA if Pb > 0 else T
                N = T27 * prior * openness(a, self.latest)
                conf, src = "C", f"{y0}年占单位{share0:.0%}疑不限专业→按均分"
            else:
                n0_same = sum(1 for x in self.U[u][y0]
                              if norm_pos(x["pos"]) == norm_pos(a["招考职位"]))
                split = (self.same_count(u, norm_pos(a["招考职位"])) / max(1, n0_same)) if not exact else 1.0
                N = ap0 * ((p27 / P0) ** BETA if P0 else 1.0) * (GROW ** (self.latest + 1 - y0)) / max(1.0, split)
                conf = ("A" if exact else "B") if y0 == self.latest else ("B" if exact else "C")
                src = f"{y0}实测{ap0}人" + ("×拆分" if split > 1.01 else "×结构调整")
        elif base:
            T, Pb = base
            T27 = T * (p27 / Pb) ** BETA if Pb > 0 else T
            N = T27 * prior * openness(a, self.latest)
            conf, src = "C", f"无同岗→单位均分×开放度{openness(a, self.latest):.2f}"

        if N is None:      # 连单位都没有：用同省中位
            pv = (a.get("工作地点") or "")[:2]
            N = max(8.0, self.prov_med.get(pv, self.glob_med))
            conf, src = "D", f"无单位历史→{pv}同类单岗中位"

        N = max(1.0, N)
        return dict(N=round(N, 1), ratio=round(N / hire, 1), conf=conf, src=src, hire=hire)


def score_of(ratio):
    """竞争比 → 预估进面线（河南 33 岗回归，MAE 2.1 分）"""
    return round(103.21 + 5.53 * __import__("math").log(max(ratio, 1.2)), 1)


# ============================================================ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default="screened.json")
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--explain", action="store_true", help="打印淘汰原因分布")
    ap.add_argument("--top", type=int, default=0, help="打印前 N 个最松的岗")
    args = ap.parse_args()

    prof = json.load(open(args.profile, encoding="utf-8"))
    ds = L.load_dataset(args.data)
    A = ds["positions"]
    year = ds["year"]
    prof.setdefault("exam_year", year)

    print(f"职位表 {year}：{len(A)} 个岗位 | 历年数据：{sorted(ds['ranks'])}")

    ok_rows, rej = [], Counter()
    for a in A:
        r = L.judge(a, prof, year)
        if r["ok"]:
            ok_rows.append((a, r["warns"]))
        else:
            for k, _ in r["fails"]:
                rej[k] += 1

    print(f"\n可报：{len(ok_rows)} / {len(A)}  ({len(ok_rows)/len(A):.1%})")
    if args.explain:
        print("\n淘汰原因分布（同一岗位可能被多条卡住）：")
        for k, v in rej.most_common():
            print(f"  {k:8} {v:6}  {v/len(A):6.1%}")

    # ---- 预测 ----
    M = Model(A, ds["ranks"])
    out = []
    for a, warns in ok_rows:
        p = M.predict(a)
        out.append(dict(
            a=a, hire=p["hire"], N=p["N"], ratio=p["ratio"], conf=p["conf"],
            src=p["src"], score=score_of(p["ratio"]), warns=warns,
            pct=any(k in (a.get("用人司局") or "") for k in
                    ("金融监督管理", "证券监督管理", "公安", "边防检查", "消防救援")),
        ))

    out.sort(key=lambda x: (x["pct"], x["ratio"]))
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"\n置信度：{dict(Counter(o['conf'] for o in out))}")
    print(f"倍数分布：<10 有 {sum(1 for o in out if o['ratio']<10)} 个，"
          f"10-30 有 {sum(1 for o in out if 10<=o['ratio']<30)} 个，"
          f">100 有 {sum(1 for o in out if o['ratio']>=100)} 个")
    print(f"→ {args.out}")

    if args.top:
        print(f"\n最松的 {args.top} 个：")
        for o in out[:args.top]:
            a = o["a"]
            print(f"  {o['ratio']:6.1f}:1  招{o['hire']}  线{o['score']:5.1f}  {o['conf']}  "
                  f"{(a.get('工作地点') or '')[:8]:8} {a['用人司局'][:18]:18} {a['招考职位'][:14]}")


if __name__ == "__main__":
    main()
