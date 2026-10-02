import os
import re
import io
import html
import tempfile
import urllib.request
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
# 1. 한글 폰트 설정 (다중 경로 및 자동 다운로드 Fallback)
# ---------------------------------------------------------
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/noto-cjk/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    font_name = "Helvetica"
    font_registered = False

    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", fp))
                font_name = "KoreanFont"
                font_registered = True
                break
            except Exception:
                continue

    if not font_registered:
        # Fallback: Download NanumGothic from Google Fonts GitHub repository
        tmp_font = os.path.join(tempfile.gettempdir(), "NanumGothic-Regular.ttf")
        if not os.path.exists(tmp_font):
            try:
                url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
                urllib.request.urlretrieve(url, tmp_font)
            except Exception:
                pass
        if os.path.exists(tmp_font):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", tmp_font))
                font_name = "KoreanFont"
                font_registered = True
            except Exception:
                pass

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
        self.setFont(FONT_NAME, 8)
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
# 3. 조사 제거 및 핵심 키워드 추출 로직
# ---------------------------------------------------------
def strip_josa(word):
    """한국어 조사/접미사 제거"""
    josa_list = [
        '에서부터', '으로의', '에서는', '에서도', '에게는', '에게도',
        '으로서', '으로부터', '에서', '으로', '에게',
        '부터', '까지', '이고', '이다', '이며', '이란', '라는',
        '은', '는', '이', '가', '을', '를', '의', '에', '로', '와', '과', '도', '만', '란'
    ]
    for j in josa_list:
        if word.endswith(j) and len(word) - len(j) >= 2:
            return word[:-len(j)]
    return word

def extract_text_from_pdf(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return pages_text

def extract_auto_keywords(pages_text, max_keywords=40):
    full_text = " ".join(pages_text)
    words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', full_text)
    
    stop_words = {
        '그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해',
        '경우', '대한', '통한', '관한', '의해', '속에', '아래', '위의', '모든',
        '있다', '없다', '한다', '된다', '이다', '것이다', '수', '등', '및',
        '가지', '관련', '내용', '방법', '원칙', '구분', '의미', '특징', '역할',
        '필요', '이상', '이하', '사항', '기준', '학습지', 'blank', 'study',
        'guide', 'page', 'pdf', '원문', '소스', '본문', '구조', '유지', '구성'
    }

    freq = {}
    for w in words:
        clean_w = strip_josa(w)
        if len(clean_w) >= 2 and clean_w not in stop_words:
            freq[clean_w] = freq.get(clean_w, 0) + 1

    sorted_words = [k for k, v in sorted(freq.items(), key=lambda x: x[1], reverse=True)]
    return sorted_words[:max_keywords]

# ---------------------------------------------------------
# 4. XML-Safe PDF 학습지 생성 로직
# ---------------------------------------------------------
def generate_blank_pdf(pages_text, target_keywords, max_per_kw=2):
    answer_key = []
    blank_counter = 1
    sorted_kw = sorted(set(target_keywords), key=len, reverse=True)

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
        spaceAfter=10
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        fontName=FONT_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        'BodyTextKorean',
        fontName=FONT_NAME,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=6
    )

    story = []
    story.append(Paragraph("📄 PDF 핵심 키워드 빈칸 학습지", title_style))
    story.append(Paragraph("원문 문서의 체계와 본문 내용을 유지하며 주요 키워드를 빈칸으로 재구성하였습니다.", body_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=12))

    for p_idx, p_text in enumerate(pages_text, 1):
        if not p_text.strip():
            continue
        story.append(Paragraph(f"<b>[ Page {p_idx} ]</b>", heading_style))

        # HTML Escape user text first for XML safety
        safe_p = html.escape(p_text)
        placeholders = {}

        for kw in sorted_kw:
            safe_kw = html.escape(kw)
            count_on_page = 0
            while safe_kw in safe_p and count_on_page < max_per_kw:
                placeholder = f"__BLANK_{blank_counter}__"
                placeholders[placeholder] = f'<font color="#D32F2F"><b>[ {blank_counter}. ____________ ]</b></font>'
                answer_key.append((blank_counter, kw))
                safe_p = safe_p.replace(safe_kw, placeholder, 1)
                blank_counter += 1
                count_on_page += 1

        # Replace placeholders with ReportLab formatting tags
        for ph, markup in placeholders.items():
            safe_p = safe_p.replace(ph, markup)

        for line in safe_p.split('\n'):
            if line.strip():
                story.append(Paragraph(line, body_style))
        story.append(Spacer(1, 10))

    # 정답지 (Answer Key)
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceBefore=15, spaceAfter=12))
    story.append(Paragraph("🗝️ 정답지 (Answer Key)", title_style))
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
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(ans_table)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer, len(answer_key)

# ---------------------------------------------------------
# 5. Streamlit 웹 UI
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

        st.subheader("2. 키워드 설정 옵션")
        mode = st.radio("키워드 선정 방식", ["자동 추출 모드", "수동 직접 입력 모드"])

        custom_keywords_input = ""
        max_kw_count = 30
        max_per_kw = 2

        if mode == "수동 직접 입력 모드":
            custom_keywords_input = st.text_area(
                "빈칸으로 만들 키워드를 쉼표(,)로 구분해서 입력하세요",
                "법인세, 소득, 납세의무자, 익금, 손금"
            )
        else:
            max_kw_count = st.slider("자동 추출할 최대 키워드 개수", min_value=10, max_value=80, value=30, step=5)
            max_per_kw = st.slider("페이지당 동일 키워드 최대 빈칸 수", min_value=1, max_value=5, value=2, step=1)

    with col2:
        st.subheader("3. 키워드 확인 및 학습지 생성")

        if uploaded_file is not None:
            # Use getvalue() instead of read() to avoid stream exhaustion on re-run
            pdf_bytes = uploaded_file.getvalue()
            pages_text = extract_text_from_pdf(pdf_bytes)

            full_extracted_len = len("".join(pages_text).strip())
            if full_extracted_len == 0:
                st.error("⚠️ 업로드된 PDF에서 텍스트를 추출할 수 없습니다.\n스캔 이미지 문서인 경우 텍스트 선택이 가능한 PDF로 변환 후 업로드해 주세요.")
            else:
                st.success(f"✅ 총 {len(pages_text)}페이지, {full_extracted_len:,}자의 텍스트가 정상 추출되었습니다.")

                if mode == "자동 추출 모드":
                    auto_kw = extract_auto_keywords(pages_text, max_keywords=max_kw_count)
                    selected_keywords = st.multiselect(
                        "🔍 자동 추출된 키워드 (원하지 않는 키워드는 ❌로 삭제하세요)",
                        options=auto_kw,
                        default=auto_kw
                    )
                else:
                    selected_keywords = [k.strip() for k in custom_keywords_input.split(",") if k.strip()]
                    st.info(f"🎯 직접 지정된 키워드 ({len(selected_keywords)}개): " + ", ".join(selected_keywords))

                st.markdown("---")
                if st.button("🚀 빈칸 학습지 PDF 생성하기", type="primary", use_container_width=True):
                    if not selected_keywords:
                        st.warning("선택되거나 입력된 키워드가 없습니다. 키워드를 확인해 주세요.")
                    else:
                        with st.spinner("PDF 학습지 및 정답지 생성 중..."):
                            try:
                                out_buffer, total_blanks = generate_blank_pdf(
                                    pages_text,
                                    selected_keywords,
                                    max_per_kw=max_per_kw
                                )
                                st.balloons()
                                st.success(f"🎉 성공적으로 {total_blanks}개의 빈칸이 포함된 학습지가 생성되었습니다!")

                                st.download_button(
                                    label="📥 완성된 빈칸 학습지 PDF 다운로드",
                                    data=out_buffer.getvalue(),
                                    file_name=f"blank_study_guide_{uploaded_file.name}",
                                    mime="application/pdf",
                                    type="primary",
                                    use_container_width=True
                                )
                            except Exception as e:
                                st.error(f"PDF 생성 중 오류가 발생했습니다: {str(e)}")
        else:
            st.info("👈 왼쪽 화면에서 PDF 파일을 업로드하면 핵심 키워드 감지 및 학습지 생성이 시작됩니다.")

if __name__ == "__main__":
    main()
