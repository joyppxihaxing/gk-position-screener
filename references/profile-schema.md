# 考生画像 schema

profile.json 的每个字段、采集话术、缺省行为。

## 必问七项

| 字段 | 类型 | 话术示例 | 缺省行为 |
|---|---|---|---|
| `edu_level` | 大专/本科/硕士/博士 | 「最高学历是？」 | 缺失会大量误杀，**必须问** |
| `degree` | 无/学士/硕士/博士 | 「有学位证吗？」 | 缺了按"学士"猜，需与用户确认 |
| `major_name` / `major_classes` / `major_code` | 字符串/数组 | 「专业全称？属于哪个专业类（如电子信息类）？代码知道吗？」 | `major_classes` 是数组，可放多个类（如跨类招生） |
| `politics` | 中共党员/共青团员/群众 | 「政治面貌？」 | 按"群众"最保守处理 |
| `gender` | 男/女 | — | 缺失则限性别岗全部放行（危险），**必须问** |
| `fresh` | bool | 「应届吗？毕业几年了？」注意"毕业即入伍"这类经历 | 按 false（非应届）处理 |
| `hukou_prov` / `hukou_city` | 字符串 | 「户口/生源地？」 | 缺失则户籍限制岗全部放行（危险），**必须问** |

## 身份类型 `identities`（多选，命运的开关）

| 身份 | 解锁 | 备注 |
|---|---|---|
| `退役士兵` | 备注含"退役大学生士兵"的岗 | 配 `military_years`；**满 5 年**才解锁"服役5年以上"定向岗 |
| `三支一扶` | 服务基层项目定向岗 | 需服务期满考核合格 |
| `西部计划` | 同上 | — |
| `特岗教师` | 同上 | — |
| `大学生村官` | 同上 | — |

空数组 = 普通考生，只能报「无限制」岗。
基层经历提示：**服现役视为基层工作经历**（公务员法实施条例第32条），
退役士兵的 `grassroots_years` 应包含服役年限。

## 追问四项

- `grassroots_years`：基层工作年限（服役计入）
- `military_years`：服役年限（仅退役士兵）
- `certs`：`{cet4, cet6, legal, cpa}` 四六级与职业证书。**没问就别猜 false**——
  国考 21% 的岗位卡四六级，猜错方向都会失真
- `prefs`：意向省份、能接受的竞争比上限、估分——只影响展示排序，不影响可报性

## 一个完整例子

```json
{
  "exam_year": 2027,
  "edu_level": "本科", "degree": "学士",
  "major_name": "电子信息工程", "major_code": "0807",
  "major_classes": ["电子信息类"], "major_gate": "工学",
  "politics": "共青团员", "fresh": false, "gender": "男",
  "hukou_prov": "河南", "hukou_city": "",
  "grassroots_years": 2,
  "identities": ["退役士兵"], "military_years": 2,
  "certs": {"cet4": false, "cet6": false, "legal": false, "cpa": false},
  "prefs": {"provs": ["河南"], "ratio_max": 60, "score_est": 120}
}
```

跑出来的结果是 263 个可报岗。注意：**不要**把"计算机类"加进 `major_classes`
来"扩大范围"——电子信息工程(0807) 不属于计算机类(0809)，资格审查过不了。
