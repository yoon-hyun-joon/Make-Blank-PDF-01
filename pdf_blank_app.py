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

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ---------------------------------------------------------
# 1. 한글 폰트 설정 (다중 Fallback 설정)
# ---------------------------------------------------------
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto-cjk/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    font_name = "Helvetica"
    for fp in font_paths:
        if os.path.exists(fp):
            try:
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
# 2. Numbered Canvas for Header & Footer
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
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont(FONT_NAME, 8)
        self.setFillColor(colors.HexColor("#718096"))
        
        # Header (Margins 54 to 541)
        self.drawString(54, 800, "교육학 핵심 키워드 빈칸 학습지 (Blank Study Guide)")
        self.drawRightString(541, 800, "Gemini Notebook")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 792, 541, 792)
        
        # Footer
        self.line(54, 50, 541, 50)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(541, 36, page_text)
        self.restoreState()

# ---------------------------------------------------------
# 3. PDF Parsing & Smart Local Keyword Extraction
# ---------------------------------------------------------
def extract_text_from_pdf_bytes(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text)
    return pages_text

def strip_josa(word):
    josa_list = [
        '은', '는', '이', '가', '의', '에', '로', '으로', '을', '를', '과', '와', '도', '만',
        '에서', '부터', '까지', '입니다', '하고', '이며', '으로서', '로서', '에도', '에게',
        '하며', '하여', '하고', '적인', '적으로', '라는', '등의', '과의', '와의', '에의', '에서'
    ]
    for j in sorted(josa_list, key=len, reverse=True):
        if word.endswith(j) and len(word) > len(j) + 1:
            return word[:-len(j)]
    return word

def extract_auto_keywords_smart(text_list, max_keywords=30):
    full_text = " ".join(text_list)
    
    # Quoted terms
    quoted_terms = re.findall(r'[\'\"「『\(]([가-힣a-zA-Z0-9\s]{2,15})[\'\"」』\)]', full_text)
    words = re.findall(r'\b[가-힣a-zA-Z0-9]{2,12}\b', full_text)
    
    stop_words = {
        '그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해', '경우', '대한',
        '통한', '관한', '의해', '속에', '아래', '위의', '모든', '있다', '없다', '한다', '된다',
        '이다', '것이다', '수', '등', '및', '또는', '하여', '하며', '있는', '없는', '같은',
        '자료', '원본', '소스', '내용', '구조', '유지하여', '작성되었습니다', '구성하였습니다', '학습지', '페이지'
    }
    
    freq = {}
    for qt in quoted_terms:
        clean_qt = strip_josa(qt.strip())
        if len(clean_qt) >= 2 and clean_qt not in stop_words:
            freq[clean_qt] = freq.get(clean_qt, 0) + 3
            
    for w in words:
        clean_w = strip_josa(w.strip())
        if len(clean_w) >= 2 and clean_w not in stop_words and not clean_w.isdigit():
            freq[clean_w] = freq.get(clean_w, 0) + 1
            
    key_patterns = [r'론$', r'법$', r'과정$', r'이론$', r'모형$', r'원리$', r'개념$', r'소득$', r'중심$', r'역량$', r'평가$', r'목표$', r'학자$']
    for k in list(freq.keys()):
        for pat in key_patterns:
            if re.search(pat, k):
                freq[k] += 2
                break
                
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

def format_text_into_smart_structure(pages_text):
    full_text = "\n".join(pages_text)
    lines = full_text.split('\n')
    structured_lines = []
    
    theme_count = 1
    for line in lines:
        l = line.strip()
        if not l:
            continue
        if re.match(r'^(테마|장|절|제\s*\d+|[0-9]+\.\s*[가-힣]+|대단원|소단원)', l):
            if not l.startswith("테마"):
                l = f"테마{theme_count:02d}: {l}"
                theme_count += 1
            structured_lines.append(l)
        elif l.startswith("•") or l.startswith("-") or l.startswith("*"):
            structured_lines.append(l)
        elif re.match(r'^\d+\.', l):
            structured_lines.append(f"• {l}")
        else:
            structured_lines.append(l)
            
    return "\n".join(structured_lines)

# ---------------------------------------------------------
# 4. Gemini AI Keyword Extraction & Structuring
# ---------------------------------------------------------
def extract_keywords_with_gemini(api_key, text_list, num_keywords=30):
    if not HAS_GENAI:
        raise ModuleNotFoundError("google-generativeai 패키지가 설치되지 않았습니다.")
        
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
    
    model_names = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.0-pro']
    
    try:
        available = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available.append(m.name.replace('models/', ''))
        if available:
            model_names = available + model_names
    except Exception:
        pass
        
    last_err = None
    for m_name in model_names:
        try:
            model = genai.GenerativeModel(m_name)
            response = model.generate_content(prompt)
            raw_response = response.text.strip()
            if raw_response:
                keywords = [k.strip() for k in raw_response.replace("\n", "").split(",") if k.strip()]
                if keywords:
                    return keywords
        except Exception as e:
            last_err = e
            continue
            
    if last_err:
        raise last_err
    raise ValueError("AI 모델 응답을 받을 수 없습니다.")

def structure_doc_with_gemini(api_key, text_list):
    if not HAS_GENAI:
        return format_text_into_smart_structure(text_list)
        
    clean_key = api_key.strip().strip("'").strip('"')
    genai.configure(api_key=clean_key)
    
    full_text = "\n".join(text_list)[:12000]
    prompt = """
    다음 학습 원문의 내용과 구조를 100% 유지하면서, 테마(단원)별 개조식 서머리 구조로 정돈해 주세요.
    
    형식 지침:
    테마01: [테마 제목]
    1. [소주제 제목]
    • [내용 요약 문장]
    - [세부 항목 문장]
    
    [원문 내용]:
    """ + full_text
    
    model_names = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro']
    for m_name in model_names:
        try:
            model = genai.GenerativeModel(m_name)
            resp = model.generate_content(prompt)
            if resp.text.strip():
                return resp.text.strip()
        except Exception:
            continue
            
    return format_text_into_smart_structure(text_list)

# ---------------------------------------------------------
# 5. PDF Render Engine
# ---------------------------------------------------------
def render_study_guide_pdf(filename, structured_text, keywords):
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
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4A5568"),
        spaceAfter=12
    )
    
    theme_style = ParagraphStyle(
        'ThemeHeading',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextKorean',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=6
    )
    
    sorted_kw = sorted(list(set(keywords)), key=len, reverse=True)
    lines = structured_text.split('\n')
    
    answers = []
    blank_counter = 1
    story = []
    
    story.append(Paragraph("<b>PDF 핵심 키워드 빈칸 학습지</b>", title_style))
    story.append(Paragraph(f"원문 소스: <b>{filename}</b> | 본문의 구조와 내용을 그대로 유지하며 핵심 키워드를 빈칸으로 구성하였습니다.", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A365D"), spaceAfter=12))
    
    for line in lines:
        if not line.strip():
            continue
            
        escaped_line = html.escape(line.strip())
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
            story.append(Paragraph(f"<b>{escaped_line}</b>", theme_style))
        else:
            story.append(Paragraph(escaped_line, body_style))
            
    # Answer Key Table
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
# 6. Streamlit User Interface
# ---------------------------------------------------------
def main():
    st.set_page_config(page_title="PDF 빈칸 학습지 자동 생성기", page_icon="✏️", layout="wide")
    
    st.title("✏️ PDF 빈칸 학습지 자동 생성기")
    st.markdown("PDF 원문의 체계와 구조를 유지하면서 핵심 키워드를 빈칸으로 만들어 주는 **고품질 학습지 + 정답지 PDF 생성기**입니다.")
    st.divider()
    
    with st.sidebar:
        st.header("⚙️ API 설정 (선택사항)")
        api_key = st.text_input("🔑 Gemini API Key 입력", type="password", help="API 키를 입력하면 AI가 더 정밀하게 문맥을 분석하여 키워드를 추출합니다. 없어도 스마트 알고리즘으로 바로 작동합니다.")
        st.markdown("[👉 무료 Gemini API Key 발급받기](https://aistudio.google.com/app/apikey)")
        st.divider()
        st.info("💡 API 키가 없어도 스마트 한국어 분석 엔진이 자동으로 키워드를 추출합니다.")
        
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("1. PDF 파일 업로드")
        uploaded_file = st.file_uploader("학습지로 만들 PDF 파일 선택", type=["pdf"])
        
        st.subheader("2. 키워드 추출 옵션")
        num_kw = st.slider("추출할 핵심 키워드 개수", min_value=10, max_value=80, value=30, step=5)
        
    with col2:
        st.subheader("3. 학습지 생성 및 다운로드")
        if uploaded_file is not None:
            file_id = f"{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.get('last_file_id') != file_id:
                st.session_state['last_file_id'] = file_id
                st.session_state.pop('extracted_kws', None)
                
            pdf_bytes = uploaded_file.getvalue()
            pages_text = extract_text_from_pdf_bytes(pdf_bytes)
            
            if not pages_text:
                st.error("❌ PDF에서 텍스트를 추출할 수 없습니다. 스캔본(이미지) PDF인지 확인해 주세요.")
            else:
                st.success(f"✅ 총 {len(pages_text)}페이지 텍스트 추출 완료")
                
                if st.button("🚀 핵심 키워드 자동 추출 실행하기", type="primary"):
                    with st.spinner("문서 분석 및 핵심 키워드 추출 중..."):
                        if api_key.strip():
                            try:
                                kws = extract_keywords_with_gemini(api_key, pages_text, num_keywords=num_kw)
                                st.session_state['extracted_kws'] = kws
                                st.success(f"🎉 Gemini AI가 {len(kws)}개의 핵심 키워드를 선별했습니다!")
                            except Exception as e:
                                st.warning(f"⚠️ API 호출 경고 ({str(e)}). 스마트 알고리즘으로 즉시 전환합니다.")
                                kws = extract_auto_keywords_smart(pages_text, max_keywords=num_kw)
                                st.session_state['extracted_kws'] = kws
                                st.success(f"⚡ 스마트 알고리즘으로 {len(kws)}개 키워드를 추출했습니다!")
                        else:
                            kws = extract_auto_keywords_smart(pages_text, max_keywords=num_kw)
                            st.session_state['extracted_kws'] = kws
                            st.success(f"⚡ 스마트 알고리즘으로 {len(kws)}개 키워드를 추출했습니다!")
                            
                current_kws = st.session_state.get('extracted_kws')
                if current_kws:
                    selected_kws = st.multiselect(
                        "선별된 핵심 키워드 (원하지 않는 키워드는 ❌로 제외하세요)",
                        options=current_kws,
                        default=current_kws
                    )
                    
                    if selected_kws:
                        with st.spinner("PDF 학습지 렌더링 중..."):
                            if api_key.strip():
                                structured_text = structure_doc_with_gemini(api_key, pages_text)
                            else:
                                structured_text = format_text_into_smart_structure(pages_text)
                                
                            out_buffer, total_blanks = render_study_guide_pdf(uploaded_file.name, structured_text, selected_kws)
                            
                        st.balloons()
                        st.success(f"🎉 총 {total_blanks}개의 빈칸이 생성되었습니다!")
                        st.download_button(
                            label="📥 완성된 PDF 학습지 다운로드",
                            data=out_buffer.getvalue(),
                            file_name=f"study_guide_{uploaded_file.name}",
                            mime="application/pdf",
                            type="primary"
                        )
        else:
            st.warning("👈 왼쪽에서 PDF 파일을 업로드해 주세요.")

if __name__ == "__main__":
    main()
