# -*- coding: utf-8 -*-
import json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

inv = json.load(open("tmp/verify/claims_inventory.json", encoding="utf-8"))
recs = json.load(open("tmp/verify/all_records.json", encoding="utf-8"))
counts = json.load(open("tmp/citation_counts.json", encoding="utf-8"))

claims_rec = {r["claim_id"]: r for r in recs if r.get("claim_id") != "SRC"}
srcs_rec = {r["ref"]: r for r in recs if r.get("claim_id") == "SRC"}

# claim meta from inventory
meta = {}
for k, v in inv["refs"].items():
    for c in v["claims"]:
        meta[c["id"]] = {"ref": int(k), "source": v["source"], "where": c["where"], "text": c["text"]}

order = sorted(meta.keys(), key=lambda x: (meta[x]["ref"], x))

VC = {"支持": 0, "部分支持": 0, "不支持": 0, "无法核实": 0}
for cid in order:
    VC[claims_rec[cid]["verdict"]] += 1
total = len(order)
strict = VC["支持"]; loose = VC["支持"] + VC["部分支持"]
markers = sum(counts.values())

wb = Workbook()
thin = Border(*[Side(style="thin", color="D0D0D0")]*4)
hdr_fill = PatternFill("solid", fgColor="1F4E79")
hdr_font = Font(color="FFFFFF", bold=True, size=11)
verdict_fill = {"支持": PatternFill("solid", fgColor="E2EFDA"),
                "部分支持": PatternFill("solid", fgColor="FFF2CC"),
                "不支持": PatternFill("solid", fgColor="FCE4E4"),
                "无法核实": PatternFill("solid", fgColor="E7E6E6")}
verdict_font = {"支持": Font(color="375623"), "部分支持": Font(color="7F6000"),
                "不支持": Font(color="9C0006", bold=True), "无法核实": Font(color="595959")}
wrap = Alignment(wrap_text=True, vertical="top")

# ---------- Sheet 1 汇总 ----------
ws = wb.active; ws.title = "汇总"
S = [
    ["引用核对汇总", ""],
    ["报告文件", "20260929_140815_34cb8276_隐私保护人脸识别中的频域方法_研究现状综述_2022_2025.md"],
    ["核对日期", "2026-10-18"],
    [],
    ["一、引用规模", ""],
    ["正文引用标记总次数", markers],
    ["覆盖参考文献数", len(inv["refs"])],
    ["去重后观点核对条目数（同句共引/镜像重复已合并）", total],
    [],
    ["二、逐条核对结果（206 条观点）", ""],
    ["支持（引文明确支撑观点）", f'{VC["支持"]} 条（{VC["支持"]/total:.1%}）'],
    ["部分支持（主旨成立，细节/数字/范围有出入）", f'{VC["部分支持"]} 条（{VC["部分支持"]/total:.1%}）'],
    ["不支持（来源存在但不支撑/矛盾/张冠李戴）", f'{VC["不支持"]} 条（{VC["不支持"]/total:.1%}）'],
    ["无法核实", f'{VC["无法核实"]} 条'],
    [],
    ["三、真实性结论", ""],
    ["严格口径真实引用率（仅'支持'）", f"{strict}/{total} = {strict/total:.1%}"],
    ["宽松口径真实引用率（'支持'+'部分支持'）", f"{loose}/{total} = {loose/total:.1%}"],
    ["凭空捏造/不存在的参考文献", "0 篇（79 篇来源全部真实存在；72 篇直接可达，7 篇访问受限但经替代来源核实）"],
]
for row in S:
    ws.append(row)
ws["A1"].font = Font(bold=True, size=14)
for r in (5, 11, 17):
    ws.cell(row=r, column=1).font = Font(bold=True, size=12)
ws.column_dimensions["A"].width = 52; ws.column_dimensions["B"].width = 90
for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=2):
    for c in row: c.alignment = wrap

# ---------- Sheet 2 逐条明细 ----------
ws2 = wb.create_sheet("逐条核对明细")
heads = ["观点编号", "章节位置", "引用编号", "观点内容（报告原文转述）", "判定", "证据（原文依据）", "备注"]
ws2.append(heads)
for i, h in enumerate(heads, 1):
    c = ws2.cell(row=1, column=i); c.fill = hdr_fill; c.font = hdr_font; c.border = thin
for cid in order:
    m, r = meta[cid], claims_rec[cid]
    ws2.append([cid, m["where"], f"[{m['ref']}]", m["text"], r["verdict"], r.get("evidence", ""), r.get("note", "")])
for ri in range(2, ws2.max_row + 1):
    v = ws2.cell(row=ri, column=5).value
    for ci in range(1, 8):
        cell = ws2.cell(row=ri, column=ci); cell.border = thin; cell.alignment = wrap
    if v in verdict_fill:
        ws2.cell(row=ri, column=5).fill = verdict_fill[v]
        ws2.cell(row=ri, column=5).font = verdict_font[v]
widths = [9, 10, 8, 70, 10, 55, 55]
for i, w in enumerate(widths, 1):
    ws2.column_dimensions[get_column_letter(i)].width = w
ws2.freeze_panes = "A2"

# ---------- Sheet 3 来源可达性 ----------
ws3 = wb.create_sheet("来源可达性")
heads3 = ["引用编号", "来源标题", "URL", "可达性", "说明"]
ws3.append(heads3)
for i in range(1, 6):
    c = ws3.cell(row=1, column=i); c.fill = hdr_fill; c.font = hdr_font; c.border = thin
for ref in sorted(srcs_rec, key=int):
    sr = srcs_rec[ref]
    url = inv["refs"][str(ref)]["url"]
    ws3.append([f"[{ref}]", inv["refs"][str(ref)]["source"], url, sr["verdict"], sr.get("note", "")])
for ri in range(2, ws3.max_row + 1):
    for ci in range(1, 6):
        cell = ws3.cell(row=ri, column=ci); cell.border = thin; cell.alignment = wrap
    v = ws3.cell(row=ri, column=4).value
    ws3.cell(row=ri, column=4).fill = {"可达": verdict_fill["支持"], "受限": verdict_fill["部分支持"], "不存在": verdict_fill["不支持"]}.get(v, PatternFill())
for i, w in enumerate([9, 55, 60, 9, 40], 1):
    ws3.column_dimensions[get_column_letter(i)].width = w
ws3.freeze_panes = "A2"

out = "引用核对报告_频域综述_20261018.xlsx"
wb.save(out)
print("saved:", out)

# 关键问题清单供 markdown 用
problems = [(cid, claims_rec[cid]) for cid in order if claims_rec[cid]["verdict"] == "不支持"]
json.dump([{"id": c, "ref": meta[c]["ref"], "where": meta[c]["where"], "text": meta[c]["text"], **r} for c, r in problems],
          open("tmp/verify/problems.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("strict:", strict, "loose:", loose, "total:", total, "markers:", markers)
