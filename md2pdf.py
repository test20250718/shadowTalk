#!/usr/bin/env python
"""将 ShadowTalk影聊.md 转换为 PDF（使用 fpdf2）"""
import markdown
from fpdf import FPDF

MD_FILE = "ShadowTalk影聊.md"
PDF_FILE = "ShadowTalk影聊.pdf"


class PDF(FPDF):
    def __init__(self):
        super().__init__()
        # 添加中文字体
        self.add_font("YaHei", "", r"C:\Windows\Fonts\msyh.ttc", uni=True)
        self.add_font("YaHei", "B", r"C:\Windows\Fonts\msyhbd.ttc", uni=True)

    def header(self):
        pass

    def footer(self):
        self.set_y(-15)
        self.set_font("YaHei", "", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"第 {self.page_no()} 页", align="C")


def md_to_pdf(md_content, pdf):
    lines = md_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # 标题
        if line.startswith("# "):
            pdf.set_font("YaHei", "B", 20)
            pdf.set_text_color(26, 26, 26)
            pdf.ln(6)
            pdf.multi_cell(0, 10, line[2:])
            pdf.ln(4)
        elif line.startswith("## "):
            pdf.set_font("YaHei", "B", 16)
            pdf.set_text_color(44, 62, 80)
            pdf.ln(4)
            pdf.multi_cell(0, 8, line[3:])
            pdf.ln(3)
        elif line.startswith("### "):
            pdf.set_font("YaHei", "B", 13)
            pdf.set_text_color(52, 73, 94)
            pdf.ln(3)
            pdf.multi_cell(0, 7, line[4:])
            pdf.ln(2)
        # 分隔线
        elif line.strip() == "---":
            pdf.set_draw_color(0, 120, 212)
            pdf.set_line_width(0.5)
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
        # 列表项
        elif line.startswith("- ") or line.startswith("* "):
            pdf.set_font("YaHei", "", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.ln(1)
            x = pdf.get_x() + 6
            pdf.set_x(x)
            pdf.multi_cell(0, 6, "• " + line[2:])
        # 有序列表
        elif len(line) > 2 and line[0].isdigit() and line[1:3] == ". ":
            pdf.set_font("YaHei", "", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.ln(1)
            x = pdf.get_x() + 6
            pdf.set_x(x)
            pdf.multi_cell(0, 6, line)
        # 空行
        elif line.strip() == "":
            pdf.ln(3)
        # 普通文本
        else:
            pdf.set_font("YaHei", "", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.multi_cell(0, 6, line)


# 读取 markdown
with open(MD_FILE, "r", encoding="utf-8") as f:
    md_content = f.read()

# 生成 PDF
pdf = PDF()
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=20)
pdf.add_page()
md_to_pdf(md_content, pdf)
pdf.output(PDF_FILE)
print(f"已生成: {PDF_FILE}")
