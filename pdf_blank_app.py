import os
import re
import io
import html
import tempfile
import urllib.request
import glob
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
# 1. 한글 폰트 설정 (Auto Detection & Download Fallback)
# ---------------------------------------------------------
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto-cjk/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumSquareR.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    
    # 1) 기본 시스템 폰트 탐색
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", fp))
                return "KoreanFont"
            except Exception:
                continue

    # 2) 시스템 /usr/share/fonts 하위 재귀 탐색
    for fp in glob.glob("/usr/share/fonts/**/*.ttf", recursive=True):
        if any(k in fp.lower() for k in ["nanum", "noto", "cjk", "korea", "gothic"]):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", fp))
                return "KoreanFont"
            except Exception:
                continue

    # 3) 인터넷에서 NanumGothic.ttf 자동 다운로드 (최후의 보루)
    tmp_font = os.path.join(tempfile.gettempdir(), "NanumGothic.ttf")
    if not os.path.exists(tmp_font):
        urls = [
            "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
            "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        ]
        for u in urls:
            try:
                urllib.request.urlretrieve(u, tmp_font)
                if os.path.exists(tmp_font) and os.path.getsize(tmp_font) > 100000:
                    break
            except Exception:
                continue

    if os.path.exists(tmp_font):
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", tmp_font))
            return "KoreanFont"
        except Exception:
            pass

    return "Helvetica"

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
        self.line(54, 45, 541, 45)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(541, 32, page_text)
        self.restoreState()

# ---------------------------------------------------------
# 3. PDF 텍스트 추출 & 키워드 자동 감지
# ---------------------------------------------------------
def extract_text_from_pdf_bytes(pdf_file_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_file_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return pages_text

def extract_auto_keywords(text_list, max_keywords=40):
    full_text = " ".join(text_list)
    korean_words = re.findall(r'\b[가-힣]{2,12}\b', full_text)
    
    josa_list = ['은', '는', '이', '가', '을', '를', '의', '에', '에서', '로', '으로', '와', '과', '도', '만', '이나', '나', '하고', '라고', '이라고']
    stopwords = {
        '그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해',
        '경우', '대한', '통한', '관한', '의해', '속에', '아래', '위의', '모든',
        '있다', '없다', '한다', '된다', '이다', '것이다', '수', '등', '및',
        '사항', '내용', '기준', '방법', '원칙', '구분', '의미', '특징', '역할', '필요', '이러한', '대해', '관련'
    }
    
    candidates = []
    for w in korean_words:
        clean_w = w
        for j in sorted(josa_list, key=len, reverse=True):
            if clean_w.endswith(j) and len(clean_w) - len(j) >= 2:
                clean_w = clean_w[:-len(j)]
                break
        if clean_w not in stopwords and len(clean_w) >= 2:
            candidates.append(clean_w)
            
    freq = {}
    for c in candidates:
        freq[c] = freq.get(c, 0) + 1
            
    sorted_candidates = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_candidates[:max_keywords]]

# ---------------------------------------------------------
# 4. 빈칸 학습지 PDF 생성
# ---------------------------------------------------------
def generate_blank_pdf(pages_text, target_keywords):
    blank_counter = 1
    answer_key = []
    placeholder_map = {}
    
    sorted_kw = sorted(set(target_keywords), key=len, reverse=True)
    
    processed_pages = []
    for page_text in pages_text:
        p_text = page_text
        for kw in sorted_kw:
            if kw in p_text:
                pattern = re.escape(kw)
                ph = f"__BLANK_{blank_counter}__"
                new_text, count = re.subn(pattern, ph, p_text, count=1)
                if count > 0:
                    p_text = new_text
                    answer_key.append((blank_counter, kw))
                    placeholder_map[ph] = f'<font color="#D32F2F"><b>[ {blank_counter}. ____________ ]</b></font>'
                    blank_counter += 1
        processed_pages.append(p_text)
        
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
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=6
    )
    
    sub_style = ParagraphStyle(
        'DocSub',
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#718096"),
        spaceAfter=15
    )
    
    heading_style = ParagraphStyle(
        'DocHeading',
        fontName=FONT_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'DocBody',
        fontName=FONT_NAME,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=8
    )
    
    story = []
    story.append(Paragraph("📄 PDF 핵심 키워드 빈칸 학습지", title_style))
    story.append(Paragraph("원문 문서의 구조와 내용을 유지하며 주요 키워드를 빈칸으로 재구성하였습니다.", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=15))
    
    for idx, page_content in enumerate(processed_pages, 1):
        story.append(Paragraph(f"<b>[ Page {idx} ]</b>", heading_style))
        paragraphs = page_content.split('\n')
        for p in paragraphs:
            if p.strip():
                escaped_p = html.escape(p)
                for ph, blank_html in placeholder_map.items():
                    if ph in escaped_p:
                        escaped_p = escaped_p.replace(ph, blank_html)
                story.append(Paragraph(escaped_p, body_style))
        story.append(Spacer(1, 10))
        
    # 정답지 영역
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceBefore=15, spaceAfter=15))
    story.append(Paragraph("🗝️ 정답지 (Answer Key)", title_style))
    story.append(Paragraph("학습 후 스스로 채점하거나 복습 시 참고하세요.", sub_style))
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
# 5. Streamlit 웹 인터페이스 UI
# ---------------------------------------------------------
def main():
    st.set_page_config(
        page_title="PDF 빈칸 학습지 생성기",
        page_icon="✏️",
        layout="wide"
    )
    
    st.title("✏️ PDF 빈칸 학습지 자동 생성기")
    st.markdown("PDF 문서를 업로드하면 핵심 키워드를 감지하거나 직접 지정하여 **빈칸 학습지 + 정답지 PDF**를 만들어 드립니다.")
    st.divider()
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("1. PDF 파일 업로드")
        uploaded_file = st.file_uploader("학습지로 만들 PDF 파일을 선택하세요", type=["pdf"])
        
        if uploaded_file is not None:
            # getvalue()를 사용하여 스트림 소진 방지
            pdf_bytes = uploaded_file.getvalue()
            pages_text = extract_text_from_pdf_bytes(pdf_bytes)
            
            total_chars = sum(len(p) for p in pages_text)
            if total_chars == 0:
                st.error("⚠️ 업로드한 PDF 파일에서 텍스트를 추출할 수 없습니다. 스캔 이미지 PDF인 경우 OCR 텍스트 선택이 가능한 파일로 시도해 주세요.")
            else:
                st.success(f"✅ 총 {len(pages_text)}페이지 ({total_chars:,} 자) 텍스트 추출 완료!")
                
                st.subheader("2. 키워드 설정")
                mode = st.radio("키워드 선정 방식", ["자동 추출 모드", "수동 키워드 입력 모드"])
                
                selected_keywords = []
                if mode == "자동 추출 모드":
                    max_kw = st.slider("자동 추출할 핵심 키워드 개수", min_value=5, max_value=60, value=25, step=5)
                    auto_kw = extract_auto_keywords(pages_text, max_keywords=max_kw)
                    
                    st.write("🔍 **감지된 핵심 키워드 목록** (자유롭게 삭제/추가 가능):")
                    selected_keywords = st.multiselect(
                        "빈칸으로 만들 키워드 선택",
                        options=auto_kw,
                        default=auto_kw
                    )
                else:
                    kw_input = st.text_area(
                        "빈칸으로 만들 키워드를 쉼표(,)로 구분하여 입력하세요",
                        value="법인세, 소득, 납세의무자, 익금, 손금"
                    )
                    selected_keywords = [k.strip() for k in kw_input.split(",") if k.strip()]

    with col2:
        st.subheader("3. 학습지 생성 및 다운로드")
        if uploaded_file is not None and total_chars > 0:
            st.info(f"🎯 최종 선정된 키워드: **{len(selected_keywords)}개**")
            
            if selected_keywords:
                if st.button("🚀 빈칸 학습지 PDF 생성하기", type="primary", use_container_width=True):
                    with st.spinner("PDF 빈칸 학습지 및 정답지를 작성하는 중입니다..."):
                        out_buffer, total_blanks = generate_blank_pdf(pages_text, selected_keywords)
                        
                    st.balloons()
                    st.success(f"🎉 성공적으로 **{total_blanks}개**의 빈칸이 포함된 학습지가 완성되었습니다!")
                    
                    out_filename = f"blank_study_{os.path.splitext(uploaded_file.name)[0]}.pdf"
                    st.download_button(
                        label="📥 완성된 빈칸 학습지 PDF 다운로드",
                        data=out_buffer.getvalue(),
                        file_name=out_filename,
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
            else:
                st.warning("키워드를 최소 1개 이상 선택하거나 입력해 주세요.")
        else:
            st.warning("👈 왼쪽에서 PDF 파일을 업로드해 주세요.")

if __name__ == "__main__":
    main()
