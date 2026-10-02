import os
import re
import io
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
# 1. 한글 폰트 설정 (NanumGothic / Noto Sans CJK)
# ---------------------------------------------------------
@st.cache_resource
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/tmp/NanumGothic.ttf"
    ]
    
    font_name = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                if fp.endswith(".ttc"):
                    pdfmetrics.registerFont(TTFont("KoreanFont", fp, subfontIndex=0))
                else:
                    pdfmetrics.registerFont(TTFont("KoreanFont", fp))
                font_name = "KoreanFont"
                break
            except Exception:
                continue

    # 인터넷 다운로드 Fallback (Streamlit Cloud 환경)
    if not font_name:
        try:
            tmp_path = "/tmp/NanumGothic.ttf"
            if not os.path.exists(tmp_path):
                url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
                urllib.request.urlretrieve(url, tmp_path)
            pdfmetrics.registerFont(TTFont("KoreanFont", tmp_path))
            font_name = "KoreanFont"
        except Exception:
            font_name = "Helvetica"

    return font_name or "Helvetica"

FONT_NAME = setup_korean_font()

# ---------------------------------------------------------
# 2. Numbered Canvas (페이지 번호 및 헤더/푸터)
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
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(FONT_NAME, 8)
        self.setFillColor(colors.HexColor("#718096"))
        
        # 헤더
        self.drawString(54, 800, "PDF 빈칸 학습지 (Blank Study Guide)")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 792, 541, 792)
        
        # 푸터
        self.line(54, 45, 541, 45)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(541, 32, page_text)
        self.restoreState()

# ---------------------------------------------------------
# 3. 키워드 추출 및 조사 분리 엔진
# ---------------------------------------------------------
def strip_josa(word):
    """단어 뒤에 붙은 한국어 조사 제거"""
    josa_list = [
        '은', '는', '이', '가', '을', '를', '의', '에', '에서', '로', '으로',
        '과', '와', '도', '만', '까지', '부터', '에게', '한테', '보다', '등'
    ]
    josa_list.sort(key=len, reverse=True)
    for j in josa_list:
        if word.endswith(j) and len(word) > len(j) + 1:
            return word[:-len(j)]
    return word

def extract_text_from_pdf(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        pages_text.append(txt)
    return pages_text

def extract_auto_keywords(text_list, max_keywords=40):
    full_text = " ".join(text_list)
    raw_words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', full_text)
    
    stop_words = {
        '그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해',
        '경우', '대한', '통한', '관한', '의해', '속에', '아래', '위의', '모든',
        '있다', '없다', '한다', '된다', '이다', '것이다', '수', '등', '및',
        '이상', '이하', '관련', '내용', '사항', '기준', '방법', '원칙', '구분'
    }
    
    freq = {}
    for w in raw_words:
        clean_w = strip_josa(w)
        if len(clean_w) >= 2 and clean_w not in stop_words:
            freq[clean_w] = freq.get(clean_w, 0) + 1
            
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

# ---------------------------------------------------------
# 4. PDF 빈칸 학습지 빌더
# ---------------------------------------------------------
def generate_blank_pdf(filename, pages_text, target_keywords):
    answer_key = []
    blank_counter = 1
    processed_pages = []
    
    sorted_keywords = sorted(list(set(target_keywords)), key=len, reverse=True)
    
    for page_text in pages_text:
        lines = page_text.split('\n')
        new_lines = []
        for line in lines:
            tokens = line.split()
            new_tokens = []
            for token in tokens:
                matched = False
                for kw in sorted_keywords:
                    if kw in token and len(kw) >= 2:
                        placeholder = f"___BLANK_{blank_counter}___"
                        token = token.replace(kw, placeholder, 1)
                        answer_key.append((blank_counter, kw))
                        blank_counter += 1
                        matched = True
                        break
                new_tokens.append(token)
            new_lines.append(" ".join(new_tokens))
        processed_pages.append("\n".join(new_lines))
        
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
    subtitle_style = ParagraphStyle(
        'DocSub',
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#718096"),
        spaceAfter=15
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        fontName=FONT_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        'BodyKorean',
        fontName=FONT_NAME,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=8
    )
    
    story = []
    story.append(Paragraph("<b>PDF 핵심 키워드 빈칸 학습지</b>", title_style))
    story.append(Paragraph(f"원문 파일: <b>{filename}</b> | 주요 개념이 빈칸 문제로 변환된 학습지입니다.", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A365D"), spaceAfter=15))
    
    for idx, page_content in enumerate(processed_pages, 1):
        story.append(Paragraph(f"<b>[ Page {idx} ]</b>", heading_style))
        lines = page_content.split('\n')
        for line in lines:
            if line.strip():
                safe_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                
                def replace_blank(match):
                    b_num = match.group(1)
                    return f'<font color="#D32F2F"><b>[ {b_num}. ____________ ]</b></font>'
                
                safe_line = re.sub(r'___BLANK_(\d+)___', replace_blank, safe_line)
                story.append(Paragraph(safe_line, body_style))
        story.append(Spacer(1, 8))
        
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceBefore=15, spaceAfter=12))
    story.append(Paragraph("<b>정답지 (Answer Key)</b>", heading_style))
    
    if answer_key:
        table_data = []
        for i in range(0, len(answer_key), 2):
            k1, v1 = answer_key[i]
            c1 = Paragraph(f"<b>{k1}.</b> {v1}", body_style)
            if i + 1 < len(answer_key):
                k2, v2 = answer_key[i+1]
                c2 = Paragraph(f"<b>{k2}.</b> {v2}", body_style)
            else:
                c2 = Paragraph("", body_style)
            table_data.append([c1, c2])
            
        t = Table(table_data, colWidths=[240, 240])
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t)
        
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer, len(answer_key)

# ---------------------------------------------------------
# 5. Streamlit 메인 UI (항상 버튼 및 키워드 목록 노출)
# ---------------------------------------------------------
def main():
    st.set_page_config(
        page_title="PDF 빈칸 학습지 자동 생성기",
        page_icon="📝",
        layout="centered"
    )
    
    st.title("📝 PDF 빈칸 학습지 자동 생성기")
    st.write("PDF 문서를 업로드하면 핵심 키워드를 자동으로 추출하여 **빈칸 문제 + 정답지 PDF**를 만듭니다.")
    st.divider()
    
    uploaded_file = st.file_uploader("1️⃣ PDF 학습 자료 업로드", type=["pdf"])
    
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        pages_text = extract_text_from_pdf(file_bytes)
        
        full_text_len = sum(len(p) for p in pages_text)
        if full_text_len < 10:
            st.error("⚠️ PDF에서 텍스트를 추출할 수 없습니다. 스캔된 이미지 PDF인지 확인해 주세요.")
            return
            
        st.success(f"📄 파일명: **{uploaded_file.name}** (총 {len(pages_text)}페이지 텍스트 감지 완료)")
        
        st.subheader("2️⃣ 키워드 설정")
        mode = st.radio("키워드 선정 방식", ["자동 추출 모드 (추천)", "직접 입력 모드"], horizontal=True)
        
        final_keywords = []
        
        if mode == "자동 추출 모드 (추천)":
            max_kw = st.slider("자동 추출할 키워드 수", min_value=5, max_value=80, value=30, step=5)
            auto_kws = extract_auto_keywords(pages_text, max_keywords=max_kw)
            
            st.write("🔍 **자동 추출된 핵심 키워드 목록 (확인 및 선택):**")
            final_keywords = st.multiselect(
                "아래 키워드들이 빈칸으로 변환됩니다. 원하는 키워드를 자유롭게 선택/제거할 수 있습니다.",
                options=auto_kws,
                default=auto_kws
            )
        else:
            user_input = st.text_area(
                "빈칸으로 만들 키워드를 쉼표(,)로 구분하여 입력하세요",
                value="법인세, 소득, 납세의무자, 익금, 손금"
            )
            final_keywords = [k.strip() for k in user_input.split(",") if k.strip()]
            
        st.divider()
        st.subheader("3️⃣ 학습지 PDF 생성")
        
        if not final_keywords:
            st.warning("⚠️ 지정된 키워드가 없습니다. 키워드를 하나 이상 선택하거나 입력해 주세요.")
        else:
            if st.button("🚀 빈칸 학습지 PDF 생성하기", type="primary", use_container_width=True):
                with st.spinner("PDF 생성 중... 잠시만 기다려 주세요."):
                    try:
                        pdf_buffer, total_blanks = generate_blank_pdf(
                            uploaded_file.name, pages_text, final_keywords
                        )
                        st.balloons()
                        st.success(f"🎉 성공! 총 **{total_blanks}개**의 빈칸이 포함된 학습지가 완성되었습니다.")
                        
                        output_filename = f"{os.path.splitext(uploaded_file.name)[0]}_blank.pdf"
                        st.download_button(
                            label="📥 완성된 PDF 학습지 다운로드",
                            data=pdf_buffer.getvalue(),
                            file_name=output_filename,
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f"❌ PDF 생성 중 오류가 발생했습니다: {str(e)}")
    else:
        st.info("👆 위 상자에서 PDF 파일을 드래그 & 드롭하거나 선택해 주세요.")

if __name__ == "__main__":
    main()
