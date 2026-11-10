# -*- coding: utf-8 -*-
import json
from collections import Counter

inv = json.load(open("tmp/verify/claims_inventory.json", encoding="utf-8"))
recs = json.load(open("tmp/verify/all_records.json", encoding="utf-8"))
problems = json.load(open("tmp/verify/problems.json", encoding="utf-8"))
claims_rec = {r["claim_id"]: r for r in recs if r.get("claim_id") != "SRC"}
srcs_rec = {r["ref"]: r for r in recs if r.get("claim_id") == "SRC"}
meta = {}
for k, v in inv["refs"].items():
    for c in v["claims"]:
        meta[c["id"]] = {"ref": int(k), "where": c["where"], "text": c["text"], "source": v["source"]}
order = sorted(meta, key=lambda x: (meta[x]["ref"], x))

L = []
L.append("# 引用核对报告：隐私保护人脸识别中的频域方法综述\n")
L.append("- 核对对象：`20260929_140815_34cb8276_隐私保护人脸识别中的频域方法_研究现状综述_2022_2025.md`")
L.append("- 核对日期：2026-10-18")
L.append("- 核对方式：逐条抓取 79 篇引文原文（含 arXiv/出版社页/替代来源），与正文 206 条观点-引文对逐一比对；数字类论断要求严格一致")
L.append("")
L.append("## 一、总体统计\n")
L.append("| 指标 | 数值 |")
L.append("|---|---|")
L.append("| 正文引用标记总次数 | **232** |")
L.append("| 覆盖参考文献数 | 79 |")
L.append("| 去重后观点核对条目 | 206（同句共引、镜像来源重复已合并） |")
L.append("| 支持（引文明确支撑） | 172（83.5%） |")
L.append("| 部分支持（主旨成立、细节有出入） | 27（13.1%） |")
L.append("| 不支持（不支撑/矛盾/张冠李戴） | 7（3.4%） |")
L.append("| 无法核实 | 0 |")
L.append("| 凭空捏造/不存在的文献 | **0**（79 篇全部真实存在） |")
L.append("")
L.append("**真实引用率**：严格口径（仅「支持」）= 172/206 ≈ **83.5%**；宽松口径（支持+部分支持）= 199/206 ≈ **96.6%**。")
L.append("")
L.append("## 二、7 条「不支持」的问题明细\n")
for i, p in enumerate(problems, 1):
    L.append("### %d. [%s] 引用[%s]（%s）" % (i, p["id"], p["ref"], p["where"]))
    L.append("- **报告观点**：%s" % p["text"])
    L.append("- **判定依据**：%s" % p["evidence"])
    L.append("- **说明**：%s" % p["note"])
    L.append("")
L.append("## 三、「部分支持」的典型问题（27 条，按类型归纳）\n")
groups = [
    ("张冠李戴/归因错位", ["2c", "12a", "15b", "19a", "31a", "54c", "62b"]),
    ("数字或口径偏差", ["5a", "8c", "62a", "56a", "60a"]),
    ("与源文主张矛盾或夸大", ["20e", "38b", "38e", "40b", "32c", "33c"]),
    ("原文无此表述（报告自行引申）", ["5b", "5e", "35b", "36b", "51c", "77a"]),
    ("镜像/二手来源未能覆盖", ["63b", "72a", "71b"]),
]
for g, ids in groups:
    L.append("**%s**" % g)
    for cid in ids:
        r = claims_rec[cid]; m = meta[cid]
        L.append("- [%s] 引用[%s]：%s" % (cid, m["ref"], r["note"]))
    L.append("")
L.append("## 四、分文献核对结果总表\n")
L.append("| 引用 | 来源 | 支持 | 部分支持 | 不支持 | 来源可达性 |")
L.append("|---|---|---|---|---|---|")
per_ref = {}
for cid in order:
    r = claims_rec[cid]
    per_ref.setdefault(r["ref"], Counter())[r["verdict"]] += 1
for ref in sorted(per_ref, key=int):
    v = per_ref[ref]
    src = inv["refs"][str(ref)]["source"][:60].replace("|", "/")
    L.append("| [%s] | %s | %d | %d | %d | %s |" % (ref, src, v.get("支持", 0), v.get("部分支持", 0), v.get("不支持", 0), srcs_rec[ref]["verdict"]))
L.append("")
L.append("> 完整证据与备注见随附 Excel《逐条核对明细》《来源可达性》两个工作表。")
L.append("")
L.append("## 五、结论与修改建议\n")
L.append("1. **没有幻觉文献**：79 篇引文全部真实存在，这一点质量很高。")
L.append("2. **主要风险是「张冠李戴」**：7 条不支持全部属于来源真实但支撑对象错误——[31][35][47][66][70] 的链接论文与正文所述条目不符；[51e] 引文与论断无关；[74b] 对 ISO/IEC 24745 要求表述错误（三大属性应为不可逆性/不可链接性/**可更新性**，而非「保密性」）。")
L.append("3. **数字类论断总体可靠**：精度、百分比、时延等关键数字绝大多数与原文严格一致（91.6% DC 能量、99.68%/99.82%、12.8s/48.7MB、2.52%/3.96% mAP 等全部吻合）。")
L.append("4. **优先修复**：修正 [31][70] 两条引文的链接或正文条目描述；[47] 的 SMPC 论断改归 Erkin et al. 2009 并补正确引文；[74b]「保密性」改为「可更新性」；[66] 删除或改引 Gomez-Barrero 2023 [54]；[51e] 视频流 GAN 论断需另找原始出处。")
L.append("")
open("引用核对报告_频域综述_20261018.md", "w", encoding="utf-8").write("\n".join(L))
print("saved md, lines:", len(L))
