import streamlit as st
import pandas as pd
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Line, PolyLine

class SmartKeepTogether(Flowable):
    def __init__(self, flowables):
        super().__init__()
        if isinstance(flowables, Flowable):
            self.flowables = [flowables]
        else:
            self.flowables = list(flowables)
        self.has_been_deferred = False
        
    def wrap(self, availWidth, availHeight):
        current_height = 0
        max_width = 0
        self.child_heights = []
        for f in self.flowables:
            w, h = f.wrap(availWidth, max(0, availHeight - current_height))
            self.child_heights.append(h)
            current_height += h
            max_width = max(max_width, w)
        self.width = max_width
        self.height = current_height
        return self.width, self.height
        
    def drawOn(self, canvas, x, y, *args, **kwargs):
        current_y = y + self.height
        for f, h in zip(self.flowables, self.child_heights):
            current_y -= h
            f.drawOn(canvas, x, current_y, *args, **kwargs)
            
    def split(self, availWidth, availHeight):
        current_height = 0
        for f in self.flowables:
            _, h = f.wrap(availWidth, 99999)
            current_height += h
            
        if current_height <= availHeight:
            return self.flowables
            
        is_ls = (availWidth > 600)
        full_frame_height = 504 if is_ls else 648
        if availHeight >= 0.85 * full_frame_height:
            return self.flowables
            
        if not self.has_been_deferred:
            self.has_been_deferred = True
            return []
            
        return self.flowables



def hex_to_reportlab_color(hex_str, default="#3B82F6"):
    if not hex_str:
        return colors.HexColor(default)
    try:
        return colors.HexColor(hex_str)
    except Exception:
        return colors.HexColor(default)

# Simple Markdown to HTML formatter for ReportLab
def convert_markdown_to_pdf_rich_text(md_text):
    if not md_text:
        return ""
    html = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html)
    html = re.sub(r'\*(.*?)\*', r'<i>\1</i>', html)
    html = re.sub(r'^\*\s+(.*?)$', r'• \1', html, flags=re.MULTILINE)
    html = re.sub(r'^-\s+(.*?)$', r'• \1', html, flags=re.MULTILINE)
    html = html.replace("\n", "<br/>")
    return html

# Helper to separate bugs from other topics
def split_bugs_and_topics(df):
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    if 'Type' not in df.columns:
        return df.copy(), pd.DataFrame()
    is_bug = df['Type'].astype(str).str.strip().str.lower() == 'bug'
    bugs_df = df[is_bug]
    topics_df = df[~is_bug]
    return topics_df, bugs_df

# Helper to place items with selected team labels first, in the selected order.
def sort_items_by_label_priority(df, secondary_columns):
    if df is None or df.empty:
        return df

    selected_labels = st.session_state.get("sprint_review_label_order", [])
    if not selected_labels:
        selected_labels = ["Bandicode", "Bugbusters", "RC2_Architecture_Team"]
        
    if "Labels" not in df.columns:
        return df.sort_values(secondary_columns, kind="stable")

    label_priorities = {label.strip().lower(): index for index, label in enumerate(selected_labels)}
    fallback_priority = len(label_priorities)

    def get_label_priority(labels):
        item_labels = [label.strip().lower() for label in re.split(r'[\s,]+', str(labels)) if label.strip()]
        return min((label_priorities[label] for label in item_labels if label in label_priorities), default=fallback_priority)

    df_copy = df.copy()
    df_copy["_label_sort_order"] = df_copy["Labels"].apply(get_label_priority)
    df_copy.sort_values(by=["_label_sort_order"] + secondary_columns, inplace=True, kind="stable")
    return df_copy.drop(columns=["_label_sort_order"])

def get_team_label(labels):
    """Return the first selected team label assigned to an item."""
    selected_labels = st.session_state.get("sprint_review_label_order", [])
    if not selected_labels:
        selected_labels = ["Bandicode", "Bugbusters", "RC2_Architecture_Team"]
    item_labels = {label.strip().lower() for label in re.split(r'[\s,]+', str(labels)) if label.strip()}
    return next((label for label in selected_labels if label.strip().lower() in item_labels), "-")

# Helper to sort items by selected team label, then Type order (User Story -> Task -> Technical Task) and Epic
def sort_items_by_type_and_epic(df):
    if df is None or df.empty:
        return df
    if 'Type' not in df.columns:
        return sort_items_by_label_priority(df, ["Epic", "Key"])
        
    def get_sort_order(item_type):
        val = str(item_type).strip().lower()
        if "story" in val:
            return 1
        elif "bug" in val:
            return 4
        elif "technical" in val:
            return 3
        elif "task" in val:
            return 2
        else:
            return 3 # Default other types to Technical Task level
            
    df_copy = df.copy()
    df_copy['_type_sort_order'] = df_copy['Type'].apply(get_sort_order)
    df_copy = sort_items_by_label_priority(df_copy, ['Epic', '_type_sort_order', 'Key'])
    return df_copy.drop(columns=['_type_sort_order'])

# ---------------------------------------------------------
# 5. PDF Generation Custom Canvas & Background Callbacks (Header, Footer, Branding)
# ---------------------------------------------------------
def draw_background_landscape(canvas_obj, doc_obj):
    primary_color_hex = st.session_state.primary_color
    primary_color = hex_to_reportlab_color(primary_color_hex)
    
    canvas_obj.saveState()
    width, height = doc_obj.pagesize
    
    # Subtle corporate background color fill
    canvas_obj.setFillColor(colors.HexColor("#F8FAFC"))
    canvas_obj.rect(0, 0, width, height, stroke=0, fill=1)
    
    # Solid vertical branding accent band on the far left edge
    canvas_obj.setFillColor(primary_color)
    canvas_obj.rect(0, 0, 8, height, stroke=0, fill=1)
    
    if doc_obj.page == 1:
        # Cover page background frame:
        # Top banner of primary color
        canvas_obj.setFillColor(primary_color)
        canvas_obj.rect(8, height - 20, width - 8, 20, stroke=0, fill=1)
        
        # Dark gray bottom bar for footer metadata
        canvas_obj.setFillColor(colors.HexColor("#E2E8F0"))
        canvas_obj.rect(8, 0, width - 8, 30, stroke=0, fill=1)
    else:
        # Content slide top header banner background
        canvas_obj.setFillColor(colors.white)
        canvas_obj.rect(8, height - 48, width - 8, 48, stroke=0, fill=1)
        
        canvas_obj.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas_obj.setLineWidth(1)
        canvas_obj.line(8, height - 48, width, height - 48)
        
    canvas_obj.restoreState()

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        primary_color_hex = st.session_state.primary_color
        primary_color = hex_to_reportlab_color(primary_color_hex)
        project_name = st.session_state.project_name
        logo_path = st.session_state.sr_logo_temp_path
        
        self.saveState()
        
        # Get dynamic page dimensions
        width, height = self._pagesize
        is_landscape = width > height
        
        if is_landscape:
            # --- LANDSCAPE SLIDES SETUP ---
            if self._pageNumber == 1:
                # Page 1 is the starting cover page.
                self.restoreState()
                return
                
            right_margin = width - 54
            top_header_y = height - 28
            logo_y = height - 36
            logo_x = right_margin - 68
            
        else:
            # --- STANDARD PORTRAIT PORTRAIT SETUP ---
            if self._pageNumber == 1:
                self.restoreState()
                return
                
            right_margin = width - 54
            top_header_y = height - 42
            line_header_y = height - 52
            logo_y = height - 35
            logo_x = right_margin - 68
            
            # Horizontal branding separator line
            self.setStrokeColor(primary_color)
            self.setLineWidth(1)
            self.line(54, line_header_y, right_margin, line_header_y)
            
        # 2. Draw Header Content
        self.setFont("Helvetica-Bold", 9.5)
        self.setFillColor(primary_color)
        self.drawString(54, top_header_y, project_name.upper())
        
        self.setFont("Helvetica", 8.5)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Draw logo image in header if loaded
        if logo_path and os.path.exists(logo_path):
            try:
                self.drawImage(logo_path, logo_x, logo_y, width=68, height=22, mask='auto', preserveAspectRatio=True)
            except Exception:
                pass
                
        # 3. Draw Footer Content
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 50, right_margin, 50)
        
        self.setFont("Helvetica", 8.5)
        self.setFillColor(colors.HexColor("#94A3B8"))
        self.drawRightString(right_margin, 36, f"Page {self._pageNumber} of {page_count}")
        
        # Date in the footer on the left
        from datetime import datetime
        current_date = datetime.now().strftime("%d-%m-%Y")
        self.drawString(54, 36, f"Date: {current_date}")
        
        self.restoreState()

# Helper to build "Apartado de Demos" block (common to both PDFs if items are selected)
def build_demos_pdf_block(df, primary_color, styles, sub_section_style=None, is_landscape=False):
    demo_items = df[df["Demo"] == True] if "Demo" in df.columns else pd.DataFrame()
    demo_items = sort_items_by_label_priority(demo_items, ["Epic", "Key"])
    if demo_items.empty:
        return []
    block_elements = []
    # Custom styling
    # Let's adjust sizes for landscape presentation grade view
    font_size_header = 9 if is_landscape else 8
    font_size_body = 8.5 if is_landscape else 7.5
    padding_val = 4 if is_landscape else 3
    
    section_title_style = ParagraphStyle(
        'DemoSecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16 if is_landscape else 13,
        leading=20 if is_landscape else 16,
        textColor=primary_color,
        spaceBefore=18,
        spaceAfter=6
    )
    
    intro_style = ParagraphStyle(
        'DemoIntro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10 if is_landscape else 8.5,
        leading=14 if is_landscape else 12,
        textColor=colors.HexColor("#475569"),
        spaceAfter=10
    )
    
    cell_header_style = ParagraphStyle(
        'DemoCellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_header,
        leading=font_size_header + 3,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'DemoCellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'DemoCellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    if sub_section_style is not None:
        block_elements.append(Paragraph("Product Demos", sub_section_style))
    else:
        block_elements.append(Paragraph("Product Demos", section_title_style))
 
    block_elements.append(Paragraph(
        "The following live product demonstrations have been scheduled. The listed feature owners will present these deliverables:",
        intro_style
    ))
    
    # Table layout
    table_data = [[
        Paragraph("Key", cell_header_style),
        Paragraph("Summary", cell_header_style),
        Paragraph("Epic", cell_header_style),
        Paragraph("Presenter 👤", cell_header_style),
        Paragraph("Team", cell_header_style)
    ]]
    
    for _, row in demo_items.iterrows():
        presenter = str(row['Assignee']) if pd.notna(row['Assignee']) and str(row['Assignee']).strip() != "" else "Unassigned"
        table_data.append([
            Paragraph(str(row['Key']), cell_body_bold_style),
            Paragraph(str(row['Summary']), cell_body_style),
            Paragraph(str(row['Epic']), cell_body_style),
            Paragraph(presenter, cell_body_bold_style),
            Paragraph(get_team_label(row.get('Labels', '')), cell_body_style)
        ])
        
    # Col Widths: Total = 504pt (Portrait) or 684pt (Landscape)
    if is_landscape:
        col_widths = [80, 214, 140, 160, 90]
    else:
        col_widths = [75, 139, 110, 110, 70]
        
    demo_table = Table(
        table_data,
        colWidths=col_widths
    )
    
    demo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), padding_val),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding_val),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.8 if is_landscape else 0.5, colors.HexColor("#E2E8F0") if is_landscape else colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(demo_table)
    block_elements.append(Spacer(1, 15))
    
    return [SmartKeepTogether(block_elements)]

# Helper to build Target Release versions table block in PDFs (NEW requested table)
def build_next_releases_pdf_block(df, primary_color, styles, is_landscape=False):
    if df is None or df.empty:
        return []
        
    block_elements = []
    
    font_size_header = 9 if is_landscape else 8
    font_size_body = 8.5 if is_landscape else 7.5
    padding_val = 4 if is_landscape else 3
    
    cell_header_style = ParagraphStyle(
        'RelCellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_header,
        leading=font_size_header + 3,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'RelCellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'RelCellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    table_data = [[
        Paragraph("Version", cell_header_style),
        Paragraph("Target Date", cell_header_style),
        Paragraph("Key Highlights & Scope Comments", cell_header_style)
    ]]
    
    for _, row in df.iterrows():
        version = str(row.get('Version', ''))
        date = str(row.get('Target Date', ''))
        comments = str(row.get('Comments', ''))
        
        table_data.append([
            Paragraph(version, cell_body_bold_style),
            Paragraph(date, cell_body_style),
            Paragraph(comments, cell_body_style)
        ])
        
    # Col Widths: Total = 504pt (Portrait) or 684pt (Landscape)
    # Version: 80pt/100pt, Date: 80pt/100pt, Comments: 344pt/484pt
    if is_landscape:
        col_widths = [100, 100, 484]
    else:
        col_widths = [80, 80, 344]
        
    rel_table = Table(
        table_data,
        colWidths=col_widths
    )
    
    rel_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), padding_val),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding_val),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.8 if is_landscape else 0.5, colors.HexColor("#E2E8F0") if is_landscape else colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(rel_table)
    block_elements.append(Spacer(1, 10))
    
    return block_elements

# Helper function to map Jira status strings to clean color-coded status bullets (PDF safe)
def format_status_with_emoji(status_str):
    if not status_str or not isinstance(status_str, str):
        return '<font color="#3B82F6">●</font>'
        
    st_clean = status_str.strip().lower()
    
    if st_clean in ['done', 'closed', 'resolved', 'complete', 'acceptance test']:
        return '<font color="#22C55E">●</font>'
    elif st_clean in ['in progress', 'development', 'testing', 'review', 'in dev', 'dev', 'qa']:
        return '<font color="#F59E0B">●</font>'
    elif st_clean in ['blocked', 'on hold', 'impediment', 'delayed', 'hold']:
        return '<font color="#EF4444">●</font>'
    elif st_clean in ['to do', 'open', 'backlog', 'selected for development', 'new']:
        return '<font color="#3B82F6">●</font>'
    else:
        return '<font color="#3B82F6">●</font>'

# Helper function to dynamically build and format an uploaded custom table (non-Jira) in both landscape and portrait PDFs
def build_custom_extra_table_pdf_block(df, primary_color, styles, is_landscape=False):
    if df is None or df.empty:
        return []
        
    block_elements = []
    df = df.copy()
    if "Labels" in df.columns:
        df["Team"] = df["Labels"].apply(get_team_label)
        df = df[[column for column in df.columns if column != "Team"] + ["Team"]]
    
    # Dynamic styling matching the presentation grade
    font_size_header = 9 if is_landscape else 8
    font_size_body = 8.5 if is_landscape else 7.5
    padding_val = 4 if is_landscape else 3
    
    cell_header_style = ParagraphStyle(
        'ExtraHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_header,
        leading=font_size_header + 3,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'ExtraBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    table_data = []
    
    # Column names as header
    header_row = [Paragraph(str(col), cell_header_style) for col in df.columns]
    table_data.append(header_row)
    
    # Data rows
    for _, row in df.iterrows():
        row_data = [Paragraph(str(val), cell_body_style) for val in row]
        table_data.append(row_data)
        
    # Compute columns widths dynamically to fill the page printable width
    total_width = 684 if is_landscape else 504
    num_cols = len(df.columns)
    col_widths = [total_width / num_cols] * num_cols
    
    extra_table = Table(
        table_data,
        colWidths=col_widths
    )
    
    extra_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), padding_val),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding_val),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.8 if is_landscape else 0.5, colors.HexColor("#E2E8F0") if is_landscape else colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(extra_table)
    block_elements.append(Spacer(1, 15))
    return block_elements

# ---------------------------------------------------------
# 6. PDF Builder: Sprint Review PDF (Consolidated Single Table)
# ---------------------------------------------------------
def get_arrow_drawing(color):
    d = Drawing(10, 10)
    # L-shape: bottom-right to bottom-left to top-left pointing up, smaller size (10x10) and black
    d.add(PolyLine([(7, 2), (2, 2), (2, 8)], strokeColor=colors.black, strokeWidth=1.0))
    d.add(Line(0, 6, 2, 8, strokeColor=colors.black, strokeWidth=1.0))
    d.add(Line(4, 6, 2, 8, strokeColor=colors.black, strokeWidth=1.0))
    return d
