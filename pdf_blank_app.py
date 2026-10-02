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
# 1. Korean Font Setup (Noto Sans CJK / NanumGothic Fallback)
# ---------------------------------------------------------
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto-cjk/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    font_name = "Helvetica"
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
                
    if font_name == "Helvetica":
        try:
            target_path = os.path.join(tempfile.gettempdir(), "NanumGothic.ttf")
            if not os.path.exists(target_path):
                url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
                urllib.request.urlretrieve(url, target_path)
            if os.path.exists(target_path):
                pdfmetrics.registerFont(TTFont("KoreanFont", target_path))
                font_name = "KoreanFont"
        except Exception:
            pass
            
    return font_name

FONT_NAME = setup_korean_font()

# ---------------------------------------------------------
# 2. Numbered Canvas for Page Header/Footer
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
        self.drawString(54, 800, "PDF 빈칸 학습지 (Blank Study Guide)")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 792, 541, 792)
        
        # Footer
        self.line(54, 50, 541, 50)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(541, 36, page_text)
        self.restoreState()

# ---------------------------------------------------------
# 3. PDF Parsing & Keyword Extraction Logic
# ---------------------------------------------------------
def extract_text_from_pdf(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text)
    return pages_text

def strip_josa(word):
    josa_list = ['은', '는', '이', '가', '의', '에', '로', '으로', '을', '를', '과', '와', '도', '만', '에서', '부터', '까지', '입니다', '하고', '이며']
    for j in sorted(josa_list, key=len, reverse=True):
        if word.endswith(j) and len(word) > len(j) + 1:
            return word[:-len(j)]
    return word

def extract_auto_keywords(text_list, max_keywords=40):
    full_text = " ".join(text_list)
    words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', full_text)
    
    stop_words = {
        '그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해',
        '경우', '대한', '통한', '관한', '의해', '속에', '아래', '위의', '모든',
        '있다', '없다', '한다', '된다', '이다', '것이다', '수', '등', '및'
    }
    
    freq = {}
    for w in words:
        clean_w = strip_josa(w)
        if clean_w not in stop_words and len(clean_w) >= 2:
            freq[clean_w] = freq.get(clean_w, 0) + 1
            
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

def try_extract_keywords_with_gemini(api_key, text_list, num_keywords=30):
    if not api_key or not api_key.strip():
        return None
    try:
        import google.generativeai as genai
        clean_key = api_key.strip().strip("'").strip('"')
        genai.configure(api_key=clean_key)
        
        full_text = "\n".join(text_list)[:10000]
        prompt = f"""
        다음 교육/학습 문서에서 가장 핵심이 되는 주요 용어, 개념, 학자 이름, 전문 키워드를 {num_keywords}개 선정해 주세요.
        
        조건:
        1. 한국어 조사(은/는/이/가/의/에/로/을/를/과/와/도/만/에서/부터/까지 등)를 완전히 제거한 순수한 개념어/명사 형태만 반환하세요.
        2. 쉼표(,)로만 구분하여 단어 목록만 출력하세요.
        3. 부연 설명, 번호, 안내 문구는 절대로 포함하지 마세요.
        
        [문서 내용]:
        {full_text}
        """
        
        model_names = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash']
        for m_name in model_names:
            try:
                model = genai.GenerativeModel(m_name)
                response = model.generate_content(prompt)
                if response and response.text.strip():
                    kws = [k.strip() for k in response.text.strip().replace("\n", "").split(",") if k.strip()]
                    if kws:
                        return kws
            except Exception:
                continue
    except Exception:
        pass
    return None

def generate_blank_pdf(filename, pages_text, target_keywords):
    answers = []
    blank_counter = 1
    sorted_kw = sorted(list(set(target_keywords)), key=len, reverse=True)
    
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
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4A5568"),
        spaceAfter=12
    )
    theme_style = ParagraphStyle(
        'ThemeHeading',
        fontName=FONT_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=12,
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
    story.append(Paragraph("<b>PDF 핵심 키워드 빈칸 학습지</b>", title_style))
    story.append(Paragraph(f"원문 소스: <b>{filename}</b> | 본문의 구조와 내용을 그대로 유지하며 핵심 키워드를 빈칸으로 구성하였습니다.", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A365D"), spaceAfter=12))
    
    for text in pages_text:
        lines = text.split('\n')
        for line in lines:
            if not line.strip():
                continue
                
            escaped_line = html.escape(line)
            placeholders = {}
            
            for kw in sorted_kw:
                if not kw or len(kw) < 2:
                    continue
                escaped_kw = html.escape(kw)
                if escaped_kw in escaped_line:
                    ph_key = f"__BLANK_{blank_counter}__"
                    placeholders[ph_key] = f'<font color="#D32F2F"><b>[ {blank_counter}. ____________ ]</b></font>'
                    answers.append((blank_counter, kw))
                    escaped_line = escaped_line.replace(escaped_kw, ph_key, 1)
                    blank_counter += 1
                    
            for ph_key, val in placeholders.items():
                escaped_line = escaped_line.replace(ph_key, val)
                
            if line.strip().startswith("테마"):
                story.append(Paragraph(escaped_line, theme_style))
            else:
                story.append(Paragraph(escaped_line, body_style))
                
    # Answer Key Page
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceBefore=15, spaceAfter=10))
    story.append(Paragraph("<b>정답지 (Answer Key)</b>", theme_style))
    story.append(Paragraph("본 빈칸 학습지에 해당하는 정답 목록입니다. 학습 후 스스로 채점하거나 복습 시 참고하세요.", subtitle_style))
    story.append(Spacer(1, 8))
    
    if answers:
        table_data = [["번호", "정답 키워드", "번호", "정답 키워드"]]
        for i in range(0, len(answers), 2):
            row1 = [f"{answers[i][0]}.", answers[i][1]]
            if i + 1 < len(answers):
                row2 = [f"{answers[i+1][0]}.", answers[i+1][1]]
            else:
                row2 = ["", ""]
            table_data.append(row1 + row2)
            
        ans_table = Table(table_data, colWidths=[40, 200, 40, 200])
        ans_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#EDF2F7")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#2D3748")),
            ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ALIGN', (0,0), (0,-1), 'CENTER'),
            ('ALIGN', (2,0), (2,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(ans_table)
        
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer, len(answers)

# ---------------------------------------------------------
# 4. Streamlit UI App
# ---------------------------------------------------------
def main():
    st.set_page_config(page_title="PDF 빈칸 학습지 자동 생성기", page_icon="✏️", layout="wide")
    
    st.title("✏️ PDF 빈칸 학습지 자동 생성기")
    st.markdown("PDF 문서를 업로드하면 핵심 키워드를 감지하여 **빈칸 학습지 + 정답지 PDF**를 완성해 드립니다.")
    st.divider()
    
    with st.sidebar:
        st.header("⚙️ API 설정 (선택사항)")
        api_key = st.text_input("🔑 Gemini API Key 입력", type="password", help="API 키가 없어도 스마트 자동 추출 기능으로 정상 작동합니다.")
        st.markdown("[👉 무료 Gemini API Key 발급받기](https://aistudio.google.com/app/apikey)")
        st.divider()
        st.info("💡 API 키를 입력하시면 AI가 문맥을 분석하여 최적의 키워드를 선별합니다.")
        
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
            max_kw_num = st.slider("자동 추출할 최대 키워드 수", min_value=10, max_value=80, value=30, step=5)
            
    with col2:
        st.subheader("3. 학습지 생성 및 다운로드")
        if uploaded_file is not None:
            # CRITICAL: Always use getvalue() instead of read() to avoid empty buffer on re-runs!
            pdf_bytes = uploaded_file.getvalue()
            pages_text = extract_text_from_pdf(pdf_bytes)
            
            if not pages_text or not any(p.strip() for p in pages_text):
                st.error("❌ PDF에서 텍스트를 추출할 수 없습니다. 스캔본(이미지) PDF인지 확인해 주세요.")
            else:
                st.success(f"✅ 총 {len(pages_text)}페이지의 텍스트가 성공적으로 추출되었습니다.")
                
                if mode == "자동 추출 모드":
                    # Attempt Gemini AI extraction first, fallback to smart auto extraction
                    ai_kws = try_extract_keywords_with_gemini(api_key, pages_text, num_keywords=max_kw_num)
                    if ai_kws:
                        target_keywords = ai_kws
                        st.info(f"🤖 Gemini AI가 감지한 주요 키워드 ({len(target_keywords)}개): " + ", ".join(target_keywords[:15]) + " ...")
                    else:
                        target_keywords = extract_auto_keywords(pages_text, max_keywords=max_kw_num)
                        st.info(f"🔍 스마트 알고리즘이 감지한 주요 키워드 ({len(target_keywords)}개): " + ", ".join(target_keywords[:15]) + " ...")
                else:
                    target_keywords = custom_keywords
                    st.info(f"🎯 지정된 키워드 ({len(target_keywords)}개): " + ", ".join(target_keywords))
                    
                if st.button("🚀 빈칸 학습지 PDF 생성하기", type="primary"):
                    with st.spinner("PDF 학습지 생성 중..."):
                        out_buffer, total_blanks = generate_blank_pdf(uploaded_file.name, pages_text, target_keywords)
                        
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
