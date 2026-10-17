# -*- coding: utf-8 -*-
"""
gk_lib —— 画像匹配引擎
=====================
把「考生画像」翻译成「这 19000 个岗位里哪些真能报」的判定逻辑。

设计原则
--------
1. 每条判定都必须能说出**依据**（返回 reason），不做黑箱。
2. 硬性门槛不过 → 直接淘汰；软性风险 → 记为 warn，不影响可报性。
3. 所有正则都来自真实职位表踩坑，见 references/pitfalls.md。
"""
import gzip, json, os, re

# ---------------------------------------------------------------- 学历 / 学位
RANK = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}
DEG_RANK = {"无": 0, "学士": 1, "硕士": 2, "博士": 3}


def edu_ok(req, level):
    """岗位学历要求 vs 考生学历"""
    req = (req or "").strip()
    if not req:
        return True
    L = RANK.get(level, 2)
    if "仅限" in req:
        for k, v in RANK.items():
            if k in req:
                return L == v
        return True
    if "或" in req:
        ks = {v for k, v in RANK.items() if k in req}
        return L in ks if ks else True
    for k, v in RANK.items():          # 「X及以上」
        if k in req:
            return L >= v
    return True


def degree_ok(req, deg):
    req = (req or "").strip()
    if not req or "无要求" in req:
        return True
    D = DEG_RANK.get(deg or "无", 0)
    if "相对应" in req:                 # 「与最高学历相对应的学位」
        return D >= 1
    if "博士" in req:
        return D == 3
    if "硕士" in req:
        return D >= 2
    if "学士" in req:
        return D >= 1
    return True


# ---------------------------------------------------------------- 专业
def split_major(pro):
    """把「本科：A、B；研究生：C」拆成 (本科段, 研究生段)"""
    ug = gr = ""
    m = re.search(r"(?:本科|大学本科)(?:专业)?[：:]", pro)
    m2 = re.search(r"(?:研究生|硕士)(?:专业)?[：:]", pro)
    if m:
        end = m2.start() if (m2 and m2.start() > m.end()) else len(pro)
        ug = pro[m.end():end]
    if m2:
        ug2 = re.search(r"(?:本科|大学本科)(?:专业)?[：:]", pro[m2.end():])
        gr = pro[m2.end(): m2.end() + ug2.start()] if ug2 else pro[m2.end():]
    if not ug and not gr:
        return pro, pro                 # 未分段，整段都算
    return ug, gr


def major_ok(pro, prof):
    """
    专业匹配。prof 需要：major_name / major_code / major_classes[] / major_gate
    返回 (ok, reason)
    """
    pro = (pro or "").strip()
    if not pro or "不限" in pro:
        return True, "不限专业"

    level = prof.get("edu_level", "本科")
    ug, gr = split_major(pro)
    seg = gr if level in ("硕士", "博士") and gr else ug

    # 1) 专业类名 / 代码 / 门类 命中
    for cls in prof.get("major_classes", []):
        if cls and cls in seg:
            return True, "类名 " + cls
    for code in prof.get("major_codes", []):
        if code and code in seg:
            return True, "代码 " + code
    if prof.get("major_gate") and prof["major_gate"] in seg:
        return True, "门类 " + prof["major_gate"]

    # 2) 精确专业名，但要排除方向限定：电子信息工程（航空电子方向）
    name = prof.get("major_name", "")
    if name and name in seg:
        m = re.search(re.escape(name) + r"[（(]([^）)]{1,24})[）)]", seg)
        if m and not re.match(r"^\d", m.group(1).strip()):
            return False, "方向限定：" + m.group(1)
        return True, "专业名 " + name

    return False, "不对口：" + seg[:34]


# ---------------------------------------------------------------- 其他门槛
NEED_YEARS = {"": 0, "无限制": 0, "一年": 1, "二年": 2, "三年": 3, "五年": 5,
              "1年": 1, "2年": 2, "3年": 3, "5年": 5}


def grassroots_ok(req, years):
    n = NEED_YEARS.get((req or "").strip(), 99)
    return years >= n


def politics_ok(req, p):
    req = req or "不限"
    if "不限" in req:
        return True
    need = set()
    if "中共党员" in req or "党员" in req:
        need.add("中共党员")
    if "共青团员" in req or "团员" in req:
        need.add("共青团员")
    return p in need if need else True


PROJ_KEYS = ["三支一扶", "西部计划", "特岗教师", "大学生村官", "大学生志愿服务西部计划"]


def project_ok(req, identities):
    req = (req or "").strip()
    if not req or "无限制" in req:
        return True
    hit = [k for k in PROJ_KEYS if k in req and any(k in i for i in identities)]
    return bool(hit)


def project_req_names(req):
    return [k for k in PROJ_KEYS if k in (req or "")]


HUKOU_RE = re.compile(r"[^，,。；;]{0,26}(?:户口|户籍|生源)[^，,。；;]{0,26}")
PROV_SHORT = ["北京", "天津", "上海", "重庆", "河北", "山西", "内蒙古", "辽宁", "吉林",
              "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北",
              "湖南", "广东", "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西",
              "甘肃", "青海", "宁夏", "新疆"]


def hukou_ok(rmk, prov, city):
    """备注里的户籍/生源限制"""
    m = HUKOU_RE.search(rmk or "")
    if not m:
        return True, ""
    seg = m.group(0)
    if "全国" in seg or "不限" in seg:
        return True, ""
    if (prov and prov in seg) or (city and city[:2] in seg):
        return True, seg[:22]
    return False, seg[:26]


def gender_ok(rmk, gender):
    r = rmk or ""
    if re.search(r"女性|限女|仅限女", r):
        return gender == "女", "限女性"
    if re.search(r"男性|限男|仅限男", r):
        return gender == "男", "限男性"
    return True, ""


def fresh_ok(rmk, fresh, year):
    r = rmk or ""
    if re.search(r"非应届|不限应届", r):
        return True, ""
    if re.search(rf"{year}\s*届|应届", r):
        return bool(fresh), "限应届"
    return True, ""


CERT_RULES = [
    (r"英语六级|六级|CET-?6", "cet6", "需六级"),
    (r"英语四级|四级|CET-?4", "cet4", "需四级"),
    (r"法律职业资格", "legal", "需法考A证"),
    (r"注册会计师|税务师|资产评估师", "cpa", "需财会证书"),
]


def cert_ok(rmk, certs):
    r = rmk or ""
    for pat, k, tag in CERT_RULES:
        if re.search(pat, r) and not certs.get(k):
            return False, tag
    return True, ""


def veteran_ok(rmk, identities, mil_years):
    """退役士兵定向岗"""
    r = rmk or ""
    if re.search(r"服役\s*5\s*年|服役满\s*5\s*年|服役5年以上", r):
        ok = ("退役士兵" in identities) and mil_years >= 5
        return ok, "需服役满5年的退役士兵"
    if "退役大学生士兵" in r or "退役士兵" in r:
        return ("退役士兵" in identities), "限退役士兵"
    return True, ""


# 备注里的**隐藏硬门槛**。这些不是「专业/学历」字段能看出来的，
# 只在备注里一句话，漏了就白报。全部来自真实踩坑。
HARD_PATTERNS = [
    (r"商业性金融|金融机构|经济部门|金融行业|银行业|保险业|证券业",
     "需金融/经济从业经历", None),
    (r"一级运动员|国家一级运动员|全国锦标赛|全国冠军赛|个人前\s*8\s*名|个人前八名",
     "需运动员等级或名次", None),
    (r"执业医师|医师资格证书", "需医师资格", None),
    (r"计算机等级考试|计算机二级|计算机三级|计算机四级", "需计算机等级证", None),
    (r"具有\s*[0-9一二三四五]{1,2}\s*年以上[^，。；;]{0,10}(?:相关|专业|行业)[^，。；;]{0,14}工作经历",
     "需相关行业工作经历", None),
]


def hard_ok(rmk):
    r = rmk or ""
    for pat, tag, _ in HARD_PATTERNS:
        if re.search(pat, r):
            return False, tag
    return True, ""


# ---------------------------------------------------------------- 主判定
def judge(a, prof, year=None):
    """
    返回 dict(ok, fails=[(类别, 说明)], warns=[(类别, 说明)])
    """
    year = year or prof.get("exam_year", 2027)
    rmk = a.get("备注") or ""
    fails, warns = [], []

    if not edu_ok(a.get("学历"), prof.get("edu_level", "本科")):
        fails.append(("学历", a.get("学历", "")))
    if not degree_ok(a.get("学位"), prof.get("degree", "学士")):
        fails.append(("学位", a.get("学位", "")))

    ok, why = major_ok(a.get("专业"), prof)
    if not ok:
        fails.append(("专业", why))

    if not politics_ok(a.get("政治面貌"), prof.get("politics", "群众")):
        fails.append(("政治面貌", a.get("政治面貌", "")))

    if not grassroots_ok(a.get("基层工作最低年限"), prof.get("grassroots_years", 0)):
        fails.append(("基层年限", a.get("基层工作最低年限", "")))

    if not project_ok(a.get("服务基层项目工作经历"), prof.get("identities", [])):
        fails.append(("服务项目", project_req_names(a.get("服务基层项目工作经历"))))

    ok, why = fresh_ok(rmk, prof.get("fresh"), year)
    if not ok:
        fails.append(("应届", why))

    ok, why = gender_ok(rmk, prof.get("gender", ""))
    if not ok:
        fails.append(("性别", why))

    ok, why = hukou_ok(rmk, prof.get("hukou_prov"), prof.get("hukou_city"))
    if not ok:
        fails.append(("户籍", why))

    ok, why = cert_ok(rmk, prof.get("certs", {}))
    if not ok:
        fails.append(("证书", why))

    ok, why = veteran_ok(rmk, prof.get("identities", []), prof.get("military_years", 0))
    if not ok:
        fails.append(("退役定向", why))

    ok, why = hard_ok(rmk)
    if not ok:
        fails.append(("隐藏门槛", why))

    # ---- 软风险（不影响可报）----
    if re.search(r"最低服务年限|服务期", rmk):
        warns.append(("服务期", "有最低服务年限"))
    if a.get("是否在面试阶段组织专业能力测试") == "是":
        warns.append(("专业测试", "面试加试专业能力"))
    m = re.search(r"具有\s*[0-9一二三四五]{1,2}\s*年以上[^，。；;]{0,16}工作经历", rmk)
    if m and "基层" not in m.group(0):
        warns.append(("行业经历", m.group(0)[:24]))
    if re.search(r"体能|体检标准|人民警察", rmk) or "公安" in (a.get("用人司局") or ""):
        warns.append(("体检", "按人民警察体检标准"))

    return dict(ok=not fails, fails=fails, warns=warns)


# ---------------------------------------------------------------- 数据加载
def load_gz(path):
    with gzip.open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def find_data(pattern, data_dir):
    hits = sorted(os.listdir(data_dir), reverse=True)
    for h in hits:
        if re.fullmatch(pattern.replace("*", ".*"), h):
            return os.path.join(data_dir, h)
    return None


def year_of(name):
    m = re.search(r"(\d{4})", name)
    return int(m.group(1)) if m else 0


def load_dataset(data_dir):
    """自动找最新的职位表、竞争数据、进面分"""
    pos_f = find_data(r"positions_\d{4}\.json\.gz", data_dir)
    rank_f = find_data(r"rank_\d{4}_\d{4}\.json\.gz", data_dir)
    sc_f = find_data(r"scores_\w+\.json\.gz", data_dir)
    if not pos_f:
        raise SystemExit("data/ 下找不到 positions_YYYY.json.gz，先跑 update_data.py")
    positions = load_gz(pos_f)
    ranks = load_gz(rank_f) if rank_f else {}
    scores = load_gz(sc_f) if sc_f else {}
    ranks = {int(k): v for k, v in ranks.items()}
    scores = {int(k): v for k, v in scores.items()}
    return dict(positions=positions, ranks=ranks, scores=scores,
                year=year_of(os.path.basename(pos_f)),
                files=dict(pos=pos_f, rank=rank_f, score=sc_f))
