import os
import re
import io
import tempfile
import streamlit as st
import pypdf
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------------------------------------------------------
# 1. 한글 폰트 설정 (Noto Sans CJK / System Korean Font)
# ---------------------------------------------------------
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "C:/Windows/Fonts/malgun.ttf",  # Windows
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    ]
    font_name = "Helvetica"
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                if fp.endswith(".ttc"):
                    pdfmetrics.registerFont(TTFont("NotoSansCJK", fp, subfontIndex=0))
                    font_name = "NotoSansCJK"
                else:
                    pdfmetrics.registerFont(TTFont("NotoSansKR", fp))
                    font_name = "NotoSansKR"
                break
            except Exception as e:
                continue
    return font_name

FONT_NAME = setup_korean_font()

# ---------------------------------------------------------
# 2. Page Numbering Canvas
# ---------------------------------------------------------
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
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont(FONT_NAME, 9)
        self.setFillColor(colors.HexColor("#718096"))
        
        # Header
        self.drawString(54, 800, "PDF 빈칸 학습지 (Auto Blank Study Guide)")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 792, 541, 792)
        
        # Footer
        self.line(54, 50, 541, 50)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(541, 36, page_text)
        self.restoreState()

# ---------------------------------------------------------
# 3. PDF 처리 및 빈칸 생성 코어 로직
# ---------------------------------------------------------
def extract_text_from_pdf(pdf_file_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_file_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return pages_text

def extract_auto_keywords(text_list, max_keywords=50):
    full_text = " ".join(text_list)
    # 한글 및 영문 2자 이상 단어 추출
    words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', full_text)
    
    stop_words = {
        '그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해',
        '경우', '대한', '통한', '관한', '의해', '속에', '아래', '위의', '모든',
        '있다', '없다', '한다', '된다', '이다', '것이다', '수', '등', '및'
    }
    
    freq = {}
    for w in words:
        if w not in stop_words and len(w) >= 2:
            freq[w] = freq.get(w, 0) + 1
            
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

def generate_blank_pdf(pages_text, target_keywords, blank_ratio=0.2):
    answer_key = []
    blank_counter = 1
    processed_pages = []
    
    # 단어 길이 긴 순서로 정렬 (중복 치환 방지)
    sorted_keywords = sorted(list(set(target_keywords)), key=lambda x: len(x), reverse=True)
    
    for page_num, text in enumerate(pages_text, 1):
        page_lines = text.split('\n')
        new_lines = []
        for line in page_lines:
            tokens = line.split()
            new_tokens = []
            for token in tokens:
                matched = False
                for kw in sorted_keywords:
                    if kw in token and len(kw) >= 2:
                        blank_str = f"<b>[ {blank_counter}. ____________ ]</b>"
                        token = token.replace(kw, blank_str, 1)
                        answer_key.append((blank_counter, kw))
                        blank_counter += 1
                        matched = True
                        break
                new_tokens.append(token)
            new_lines.append(" ".join(new_tokens))
        processed_pages.append("\n".join(new_lines))
        
    # PDF 생성
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        fontName=FONT_NAME,
        fontSize=20,
        leading=26,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=15,
        alignment=0
    )
    
    heading_style = ParagraphStyle(
        'SectionHeading',
        fontName=FONT_NAME,
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=12,
        spaceAfter=8,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextKorean',
        fontName=FONT_NAME,
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=8
    )
    
    story = []
    story.append(Spacer(1, 15))
    story.append(Paragraph("📄 PDF 빈칸 학습지 (Blank Study Guide)", title_style))
    story.append(Paragraph("원문 문서의 구조를 유지하며 핵심 키워드를 빈칸으로 재구성하였습니다.", body_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=15))
    
    for page_idx, page_content in enumerate(processed_pages, 1):
        story.append(Paragraph(f"<b>[ Page {page_idx} ]</b>", heading_style))
        paragraphs = page_content.split('\n')
        for p in paragraphs:
            if p.strip():
                clean_p = p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                clean_p = clean_p.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
                story.append(Paragraph(clean_p, body_style))
        story.append(Spacer(1, 10))
        
    # 정답지 페이지
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceBefore=20, spaceAfter=15))
    story.append(Paragraph("🗝️ 정답지 (Answer Key)", title_style))
    story.append(Paragraph("학습 후 스스로 채점하거나 복습 시 참고하세요.", body_style))
    story.append(Spacer(1, 10))
    
    if answer_key:
        table_data = [["번호", "정답 키워드", "번호", "정답 키워드"]]
        for i in range(0, len(answer_key), 2):
            row1 = [f"{answer_key[i][0]}.", answer_key[i][1]]
            if i + 1 < len(answer_key):
                row2 = [f"{answer_key[i+1][0]}.", answer_key[i+1][1]]
            else:
                row2 = ["", ""]
            table_data.append(row1 + row2)
            
        ans_table = Table(table_data, colWidths=[40, 200, 40, 200])
        ans_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#EDF2F7")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#2D3748")),
            ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
            ('FONTSIZE', (0,0), (-1,-1), 9.5),
            ('ALIGN', (0,0), (0,-1), 'CENTER'),
            ('ALIGN', (2,0), (2,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(ans_table)
        
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer, len(answer_key)

# ---------------------------------------------------------
# 4. Streamlit 웹 인터페이스
# ---------------------------------------------------------
def main():
    st.set_page_config(
        page_title="PDF 빈칸 학습지 생성기",
        page_icon="✏️",
        layout="wide"
    )
    
    st.title("✏️ PDF 빈칸 학습지 자동 생성기")
    st.markdown("PDF 문서를 업로드하면 핵심 키워드를 자동으로 감지하거나 직접 지정하여 **빈칸 학습지 + 정답지 PDF**를 만들어 드립니다.")
    st.divider()
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("1. PDF 파일 업로드")
        uploaded_file = st.file_uploader("학습지로 만들 PDF 파일을 선택하세요", type=["pdf"])
        
        st.subheader("2. 키워드 설정")
        mode = st.radio("키워드 선정 방식", ["자동 추출 모드", "수동 키워드 입력 모드"])
        
        custom_keywords = []
        if mode == "수동 키워드 입력 모드":
            kw_input = st.text_area("빈칸으로 만들 키워드를 쉼표(,)로 구분해서 입력하세요", "법인세, 소득, 납세의무자, 익금, 손금")
            custom_keywords = [k.strip() for k in kw_input.split(",") if k.strip()]
        else:
            max_kw_num = st.slider("자동 추출할 최대 키워드 수", min_value=10, max_value=100, value=40, step=5)
            
    with col2:
        st.subheader("3. 결과 미리보기 및 파일 생성")
        if uploaded_file is not None:
            pdf_bytes = uploaded_file.read()
            pages_text = extract_text_from_pdf(pdf_bytes)
            
            st.success(f"✅ 총 {len(pages_text)}페이지의 텍스트가 성공적으로 추출되었습니다.")
            
            if mode == "자동 추출 모드":
                target_keywords = extract_auto_keywords(pages_text, max_keywords=max_kw_num)
                st.info(f"🔍 감지된 주요 키워드 ({len(target_keywords)}개): " + ", ".join(target_keywords[:15]) + " ...")
            else:
                target_keywords = custom_keywords
                st.info(f"🎯 지정된 키워드 ({len(target_keywords)}개): " + ", ".join(target_keywords))
                
            if st.button("🚀 빈칸 학습지 PDF 생성하기", type="primary"):
                with st.spinner("PDF 학습지 생성 중..."):
                    out_buffer, total_blanks = generate_blank_pdf(pages_text, target_keywords)
                    
                st.balloons()
                st.success(f"🎉 성공적으로 {total_blanks}개의 빈칸이 포함된 학습지가 생성되었습니다!")
                
                st.download_button(
                    label="📥 빈칸 학습지 PDF 다운로드",
                    data=out_buffer.getvalue(),
                    file_name=f"blank_study_guide_{uploaded_file.name}",
                    mime="application/pdf",
                    type="primary"
                )
        else:
            st.warning("👈 왼쪽 화면에서 PDF 파일을 업로드해 주세요.")

if __name__ == "__main__":
    main()
