#!/usr/bin/env python
"""将用户手册 markdown 转换为 PDF（fpdf2 + 微软雅黑中文）。

运行：python tools/build_manual.py
输出：resources/shadowtalk_manual.pdf（中文）
      resources/shadowtalk_manual_en.pdf（英文）
"""
import re
from fpdf import FPDF

# (markdown 源文件, 输出 PDF 文件) —— 中英文各一份
MANUALS = [
    ("docs/user_manual.md", "resources/shadowtalk_manual.pdf"),
    ("docs/user_manual_en.md", "resources/shadowtalk_manual_en.pdf"),
]

# 中文字体（Windows 系统自带微软雅黑）
_FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
_FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"


class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("YaHei", "", _FONT_REGULAR)
        self.add_font("YaHei", "B", _FONT_BOLD)
        # 当前行首行缩进（列表项悬挂用）
        self._indent_x = 10

    def header(self):
        self.set_font("YaHei", "", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 8, "ShadowTalk 影聊 · 用户手册", align="C")
        self.ln(4)
        self.set_draw_color(220, 220, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("YaHei", "", 8)
        self.set_text_color(160, 160, 160)
        self.set_draw_color(220, 220, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)
        self.cell(0, 8, f"第 {self.page_no()} 页", align="C")


def _render_line(pdf: PDF, line: str, body_size: int = 11, line_h: float = 6.5):
    """渲染一行内联文本，支持 **bold** 和 `inline code`。"""
    # 拆分：普通文本 / 粗体 / 行内代码
    parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", line)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            pdf.set_font("YaHei", "B", body_size)
            pdf.set_text_color(30, 30, 30)
            pdf.write(line_h, part[2:-2])
        elif part.startswith("`") and part.endswith("`"):
            pdf.set_font("YaHei", "", body_size - 1)
            pdf.set_text_color(192, 64, 32)
            pdf.write(line_h, part[1:-1])
        else:
            pdf.set_font("YaHei", "", body_size)
            pdf.set_text_color(51, 51, 51)
            pdf.write(line_h, part)


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _render_table(pdf: PDF, lines: list, start: int):
    """渲染一个 markdown 表格，返回处理到的行号。"""
    # 收集表格行（含表头分隔行）
    table_lines = []
    i = start
    while i < len(lines) and _is_table_row(lines[i]):
        table_lines.append(lines[i])
        i += 1
    if len(table_lines) < 2:
        return start  # 不是有效表格

    # 解析单元格
    def _cells(row: str) -> list:
        row = row.strip().strip("|")
        return [c.strip() for c in row.split("|")]

    header = _cells(table_lines[0])
    n_cols = len(header)
    rows = [_cells(r) for r in table_lines[2:]]  # 跳过分隔行

    # 列宽分配
    page_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = page_w / n_cols
    line_h = 6.0

    # 检查是否需要分页
    needed = (1 + len(rows)) * line_h + 4
    if pdf.get_y() + needed > pdf.h - 25:
        pdf.add_page()

    # 表头
    pdf.set_font("YaHei", "B", 10)
    pdf.set_fill_color(44, 62, 80)
    pdf.set_text_color(255, 255, 255)
    x0 = pdf.get_x()
    for h in header:
        pdf.cell(col_w, line_h, h, border=1, fill=True)
    pdf.ln()
    # 数据行
    pdf.set_font("YaHei", "", 10)
    pdf.set_text_color(51, 51, 51)
    fill = False
    for row in rows:
        if pdf.get_y() + line_h > pdf.h - 25:
            pdf.add_page()
            fill = False
        if fill:
            pdf.set_fill_color(245, 248, 250)
        for j, cell in enumerate(row[:n_cols]):
            # 单元格内可能含粗体/行内代码，简化为纯文本
            text = re.sub(r"\*?\*?([^*`]+)\*?\*?", r"\1", cell)
            text = text.replace("`", "")
            pdf.cell(col_w, line_h, text, border=1, fill=fill)
        pdf.ln()
        fill = not fill
    pdf.ln(2)
    return i


def md_to_pdf(md_content: str, pdf: PDF):
    lines = md_content.split("\n")
    i = 0
    in_code = False
    code_buf = []

    while i < len(lines):
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            if in_code:
                # 结束代码块（用雅黑等宽显示，兼容中文注释）
                pdf.set_font("YaHei", "", 9)
                pdf.set_text_color(40, 40, 40)
                pdf.set_fill_color(240, 240, 240)
                code_text = "\n".join(code_buf)
                # 简单绘制灰底
                n = len(code_buf)
                if pdf.get_y() + n * 4.5 + 8 > pdf.h - 25:
                    pdf.add_page()
                x0 = pdf.get_x()
                pdf.rect(x0, pdf.get_y(), pdf.w - pdf.l_margin - pdf.r_margin,
                         n * 4.5 + 6, "F")
                for cl in code_buf:
                    pdf.set_x(x0 + 3)
                    pdf.cell(0, 4.5, cl[:90])
                    pdf.ln(4.5)
                pdf.ln(3)
                in_code = False
                code_buf = []
            else:
                in_code = True
                code_buf = []
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # 表格
        if _is_table_row(line):
            i = _render_table(pdf, lines, i)
            continue

        # 标题
        if line.startswith("# "):
            pdf.set_font("YaHei", "B", 20)
            pdf.set_text_color(26, 26, 26)
            pdf.ln(6)
            pdf.multi_cell(0, 10, line[2:])
            pdf.ln(4)
            i += 1
            continue
        elif line.startswith("## "):
            # 检查分页
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            pdf.set_font("YaHei", "B", 15)
            pdf.set_text_color(44, 62, 80)
            pdf.ln(4)
            pdf.multi_cell(0, 8, line[3:])
            pdf.ln(3)
            i += 1
            continue
        elif line.startswith("### "):
            pdf.set_font("YaHei", "B", 12)
            pdf.set_text_color(52, 73, 94)
            pdf.ln(3)
            pdf.multi_cell(0, 7, line[4:])
            pdf.ln(2)
            i += 1
            continue

        # 分隔线
        elif line.strip() == "---":
            pdf.set_draw_color(0, 120, 212)
            pdf.set_line_width(0.5)
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
            i += 1
            continue

        # 引用块
        elif line.strip().startswith("> "):
            text = line.strip()[2:]
            pdf.set_fill_color(240, 246, 252)
            pdf.set_draw_color(0, 120, 212)
            pdf.set_line_width(0.3)
            pdf.set_font("YaHei", "", 11)
            pdf.set_text_color(60, 80, 100)
            if pdf.get_y() > pdf.h - 30:
                pdf.add_page()
            x0 = pdf.get_x()
            # 左色条
            y0 = pdf.get_y()
            pdf.rect(x0, y0, 3, 6, "F")
            pdf.set_x(x0 + 5)
            pdf.multi_cell(0, 6, text)
            pdf.ln(2)
            i += 1
            continue

        # 无序列表
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            text = line.strip()[2:]
            pdf.set_font("YaHei", "", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.ln(1)
            x = pdf.get_x() + 6
            pdf.set_x(x)
            pdf.cell(5, 6, "•")
            pdf.set_x(x + 6)
            pdf.multi_cell(0, 6, text)
            i += 1
            continue

        # 有序列表
        elif re.match(r"^\s*\d+\.\s", line):
            m = re.match(r"^\s*(\d+)\.\s(.*)$", line)
            num, text = m.group(1), m.group(2)
            pdf.set_font("YaHei", "", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.ln(1)
            x = pdf.get_x() + 6
            pdf.set_x(x)
            pdf.cell(8, 6, f"{num}.")
            pdf.set_x(x + 8)
            pdf.multi_cell(0, 6, text)
            i += 1
            continue

        # 空行
        elif line.strip() == "":
            pdf.ln(3)
            i += 1
            continue

        # 普通文本（含内联格式）
        else:
            if pdf.get_y() > pdf.h - 30:
                pdf.add_page()
            pdf.set_x(pdf.l_margin)
            _render_line(pdf, line)
            pdf.ln(6)
            i += 1
            continue


# ── 读取 markdown ──
# ── 依次生成各语言版本 PDF ──
for md_file, pdf_file in MANUALS:
    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    pdf = PDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    md_to_pdf(md_content, pdf)
    pdf.output(pdf_file)
    print(f"Generated: {pdf_file}")
