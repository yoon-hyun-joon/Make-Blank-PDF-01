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
# 1. 한글 폰트 설정 (Noto Sans CJK / NanumGothic Fallback)
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
        self.setFont(FONT_NAME, 8)
        self.setFillColor(colors.HexColor("#666666"))
        
        # Header
        self.drawString(54, 800, "PDF 자동 빈칸 학습지 (Blank Study Guide)")
        self.setStrokeColor(colors.HexColor("#DDDDDD"))
        self.setLineWidth(0.5)
        self.line(54, 792, 541, 792)
        
        # Footer
        self.line(54, 45, 541, 45)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(541, 32, page_text)
        self.restoreState()

# ---------------------------------------------------------
# 3. PDF Parsing & Text Extraction
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

def extract_auto_keywords_basic(text_list, max_keywords=30):
    full_text = " ".join(text_list)
    words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', full_text)
    stop_words = {'그리고', '하지만', '또한', '따라서', '이에', '때문에', '통해', '위해', '경우', '대한', '통한', '관한', '의해', '속에', '아래', '위의', '모든', '있다', '없다', '한다', '된다', '이다', '것이다', '수', '등', '및'}
    
    freq = {}
    for w in words:
        clean_w = strip_josa(w)
        if clean_w not in stop_words and len(clean_w) >= 2:
            freq[clean_w] = freq.get(clean_w, 0) + 1
            
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

# ---------------------------------------------------------
# 4. Gemini AI Structured Study Guide Generation
# ---------------------------------------------------------
def generate_study_guide_with_gemini(api_key, filename, pages_text):
    if not HAS_GENAI:
        raise ImportError("google-generativeai 패키지가 설치되지 않았습니다.")
        
    clean_key = api_key.strip().strip("'").strip('"')
    genai.configure(api_key=clean_key)
    
    full_text = "\n\n".join(pages_text)[:12000]
    
    prompt = f"""
    당신은 전문 교육 자료 편집자입니다.
    제시된 PDF 문서 내용을 바탕으로 학습자가 핵심 개념을 체계적으로 복습하고 암기할 수 있는 고품질 '핵심 키워드 빈칸 학습지'를 작성해 주세요.

    [작성 지침]
    1. 문서의 주요 주제별로 '테마01: [주제명]', '테마02: [주제명]' 형태의 섹션 제목을 구성하세요.
    2. 내용을 개조식(•, -) 및 명확한 요약 문장으로 알기 쉽게 정리하세요.
    3. 가장 중요한 핵심 개념어, 전문 용어, 학자 이름, 주요 원리 단어를 `[ 1. ____________ ]`, `[ 2. ____________ ]`와 같이 빈칸으로 대체하세요. (빈칸 번호는 1번부터 차례대로 중복 없이 연속해서 부여해야 합니다.)
    4. 본문 작성이 끝난 후, 맨 아래에 반드시 `---정답지---` 구분선을 넣고 `1. 정답1`, `2. 정답2`와 같이 빈칸 번호에 해당하는 정답 목록을 작성하세요.
    5. 인사말이나 안내문구는 출력하지 말고 '테마01:'부터 시작하여 '---정답지---' 내용까지 바로 작성해 주세요.

    [PDF 문서 내용]:
    {full_text}
    """
    
    model_names = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
    last_err = None
    
    for m_name in model_names:
        try:
            model = genai.GenerativeModel(m_name)
            response = model.generate_content(prompt)
            raw_response = response.text.strip()
            if raw_response and "---정답지---" in raw_response:
                return raw_response
            elif raw_response:
                raw_response = re.sub(r'[\-\=]{3,}\s*정답지\s*[\-\=]{3,}', '---정답지---', raw_response)
                return raw_response
        except Exception as e:
            last_err = e
            continue
            
    if last_err:
        raise last_err
    raise ValueError("AI가 응답을 반환하지 못했습니다. API 키나 입력 문서를 확인해 주세요.")

# ---------------------------------------------------------
# 5. ReportLab PDF Document Renderer (Identical to Sample)
# ---------------------------------------------------------
def render_study_guide_pdf(filename, structured_text):
    parts = structured_text.split("---정답지---")
    body_text = parts[0].strip()
    ans_text = parts[1].strip() if len(parts) > 1 else ""
    
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
        textColor=colors.HexColor('#1A237E'),
        spaceAfter=6
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#555555'),
        spaceAfter=15
    )

    body_style = ParagraphStyle(
        'BodyKorean',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor('#222222'),
        spaceAfter=8
    )

    theme_heading = ParagraphStyle(
        'ThemeHeading',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor('#1A237E'),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    story = []

    # Title Header Block
    story.append(Paragraph("<b>PDF 핵심 키워드 빈칸 학습지</b>", title_style))
    story.append(Paragraph(f"원문 파일: <b>{filename}</b> | 본문의 구조와 핵심 개념을 그대로 유지하며 빈칸으로 구성하였습니다.", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1A237E'), spaceAfter=15))

    # Process Body Lines
    lines = body_text.split("\n")
    blank_count = 0
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
            
        escaped_line = html.escape(line_clean)
        
        # Highlight blanks in red bold
        escaped_line = re.sub(
            r'\[\s*(\d+)\.\s*____________\s*\]',
            r'<font color="#D32F2F"><b>[ \1. ____________ ]</b></font>',
            escaped_line
        )
        
        # Count blanks
        blank_matches = re.findall(r'\[\s*\d+\.\s*____________\s*\]', line_clean)
        blank_count += len(blank_matches)
        
        if line_clean.startswith("테마") or line_clean.startswith("주제") or line_clean.startswith("Chapter") or line_clean.startswith("Section") or line_clean.startswith("[ Page"):
            story.append(Paragraph(f"<b>{escaped_line}</b>", theme_heading))
        else:
            story.append(Paragraph(escaped_line, body_style))

    # Answer Key Table
    if ans_text:
        story.append(Spacer(1, 15))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CCCCCC'), spaceBefore=10, spaceAfter=15))
        story.append(Paragraph("<b>정답지 (Answer Key)</b>", theme_heading))
        story.append(Paragraph("본 빈칸 학습지에 해당하는 정답 목록입니다. 학습 후 복습 시 참고하세요.", subtitle_style))

        answers = []
        for a_line in ans_text.split("\n"):
            m = re.match(r'^(\d+)[\.\:]\s*(.+)$', a_line.strip())
            if m:
                answers.append((m.group(1), m.group(2)))
            else:
                m_sub = re.findall(r'(\d+)[\.\:]\s*([^\d\.\:\n,]+)', a_line.strip())
                for idx, ans_val in m_sub:
                    answers.append((idx.strip(), ans_val.strip()))

        if not answers:
            raw_items = [i.strip() for i in ans_text.split(",") if i.strip()]
            for idx, item in enumerate(raw_items, 1):
                answers.append((str(idx), item))

        table_data = []
        for i in range(0, len(answers), 2):
            k1, v1 = answers[i]
            cell1 = Paragraph(f"<b>{k1}.</b> {html.escape(v1)}", body_style)
            if i + 1 < len(answers):
                k2, v2 = answers[i+1]
                cell2 = Paragraph(f"<b>{k2}.</b> {html.escape(v2)}", body_style)
            else:
                cell2 = Paragraph("", body_style)
            table_data.append([cell1, cell2])

        if table_data:
            t = Table(table_data, colWidths=[240, 240])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(t)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer, max(blank_count, len(answers))

# Keyword-based fallback generator
def generate_study_guide_from_keywords(filename, pages_text, keywords):
    sorted_keywords = sorted(list(set(keywords)), key=len, reverse=True)
    answer_key = []
    blank_counter = 1
    
    body_lines = []
    for p_idx, text in enumerate(pages_text, 1):
        body_lines.append(f"테마 {p_idx:02d}: 주요 학습 내용 (Page {p_idx})")
        lines = text.split("\n")
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
                
            matched_line = line_str
            for kw in sorted_keywords:
                if kw in matched_line and len(kw) >= 2:
                    placeholder = f"[ {blank_counter}. ____________ ]"
                    matched_line = matched_line.replace(kw, placeholder, 1)
                    answer_key.append((blank_counter, kw))
                    blank_counter += 1
                    
            body_lines.append(matched_line)
        body_lines.append("")
        
    ans_lines = [f"{idx}. {kw}" for idx, kw in answer_key]
    full_structured = "\n".join(body_lines) + "\n\n---정답지---\n" + "\n".join(ans_lines)
    return render_study_guide_pdf(filename, full_structured)

# ---------------------------------------------------------
# 6. Streamlit Main App UI
# ---------------------------------------------------------
def main():
    st.set_page_config(
        page_title="PDF 빈칸 학습지 자동 생성기",
        page_icon="📝",
        layout="wide"
    )

    st.title("📝 PDF 핵심 키워드 빈칸 학습지 생성기")
    st.markdown("PDF 문서를 업로드하면 **Gemini AI**가 문맥과 중요 개념을 분석하여 **체계적인 빈칸 학습지 + 정답지 PDF**를 만들어 드립니다.")
    st.divider()

    # Sidebar
    with st.sidebar:
        st.header("⚙️ API 설정")
        api_key = st.text_input("🔑 Gemini API Key 입력", type="password", help="aistudio.google.com에서 발급받은 API 키를 입력하세요.")
        st.markdown("[👉 무료 Gemini API Key 발급받기](https://aistudio.google.com/app/apikey)")
        st.divider()
        st.info("💡 **팁**: Gemini API 키를 입력하시면 AI가 문서 전체의 구조를 요약하고 최고 품질의 빈칸 학습지를 자동 구성합니다.")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("1. PDF 파일 업로드")
        uploaded_file = st.file_uploader("학습지로 만들 PDF 파일을 선택하세요", type=["pdf"])

        st.subheader("2. 학습지 생성 방식")
        mode = st.radio(
            "생성 방식 선택",
            ["🤖 Gemini AI 자동 학습지 생성 (추천)", "🎯 키워드 자동 추출 & 직접 선택 모드"]
        )

        num_kw = 30
        if mode == "🎯 키워드 자동 추출 & 직접 선택 모드":
            num_kw = st.slider("추출할 핵심 키워드 수", min_value=10, max_value=80, value=30, step=5)

    with col2:
        st.subheader("3. 학습지 생성 및 다운로드")
        if uploaded_file is not None:
            pdf_bytes = uploaded_file.getvalue()
            pages_text = extract_text_from_pdf(pdf_bytes)

            if not pages_text:
                st.error("❌ PDF에서 텍스트를 읽을 수 없습니다. 스캔본(이미지) PDF인지 확인해 주세요.")
            else:
                st.success(f"✅ 총 {len(pages_text)}페이지의 텍스트가 성공적으로 읽혔습니다.")

                if mode == "🤖 Gemini AI 자동 학습지 생성 (추천)":
                    if st.button("🚀 Gemini AI로 빈칸 학습지 즉시 생성하기", type="primary"):
                        if not api_key:
                            st.warning("⚠️ 왼쪽 사이드바에 Gemini API Key를 입력하시면 AI가 훨씬 자연스러운 학습지를 만들어 줍니다. (API 키 없이 기본 알고리즘으로 진행합니다.)")
                            with st.spinner("기본 알고리즘으로 학습지 작성 중..."):
                                auto_kw = extract_auto_keywords_basic(pages_text, max_keywords=30)
                                out_buf, b_cnt = generate_study_guide_from_keywords(uploaded_file.name, pages_text, auto_kw)
                                st.session_state['generated_pdf'] = out_buf.getvalue()
                                st.session_state['generated_blanks'] = b_cnt
                        else:
                            with st.spinner("🤖 Gemini AI가 문서 전체를 분석하여 요약문, 빈칸, 정답지를 작성하는 중..."):
                                try:
                                    structured_text = generate_study_guide_with_gemini(api_key, uploaded_file.name, pages_text)
                                    out_buf, b_cnt = render_study_guide_pdf(uploaded_file.name, structured_text)
                                    st.session_state['generated_pdf'] = out_buf.getvalue()
                                    st.session_state['generated_blanks'] = b_cnt
                                    st.success("🎉 Gemini AI 빈칸 학습지 완성이 완료되었습니다!")
                                except Exception as e:
                                    st.error(f"❌ Gemini AI 호출 중 오류 발생: {str(e)}")
                                    st.info("💡 API 키를 확인하시거나 아래 키워드 선택 모드를 사용해 보세요.")

                else:
                    # Keyword Selection Mode
                    if st.button("🔍 핵심 키워드 추출하기", type="primary"):
                        if api_key and HAS_GENAI:
                            with st.spinner("AI가 키워드를 추출 중..."):
                                try:
                                    clean_k = api_key.strip().strip("'").strip('"')
                                    genai.configure(api_key=clean_k)
                                    m = genai.GenerativeModel('gemini-1.5-flash')
                                    p = f"다음 문서에서 중요한 핵심 용어 {num_kw}개를 쉼표로만 구분해서 제시하세요:\n" + "\n".join(pages_text)[:8000]
                                    res = m.generate_content(p)
                                    kws = [k.strip() for k in res.text.replace("\n","").split(",") if k.strip()]
                                    st.session_state['kw_list'] = kws
                                except Exception:
                                    st.session_state['kw_list'] = extract_auto_keywords_basic(pages_text, max_keywords=num_kw)
                        else:
                            st.session_state['kw_list'] = extract_auto_keywords_basic(pages_text, max_keywords=num_kw)

                    if 'kw_list' in st.session_state:
                        selected_kws = st.multiselect(
                            "빈칸으로 만들 키워드를 확인/수정하세요",
                            options=st.session_state['kw_list'],
                            default=st.session_state['kw_list']
                        )

                        if st.button("📄 빈칸 학습지 PDF 생성하기"):
                            with st.spinner("PDF 생성 중..."):
                                out_buf, b_cnt = generate_study_guide_from_keywords(uploaded_file.name, pages_text, selected_kws)
                                st.session_state['generated_pdf'] = out_buf.getvalue()
                                st.session_state['generated_blanks'] = b_cnt

                # Download Section
                if 'generated_pdf' in st.session_state:
                    st.balloons()
                    st.success(f"🎉 {st.session_state.get('generated_blanks', 0)}개의 빈칸이 수록된 완성본 PDF가 준비되었습니다!")
                    st.download_button(
                        label="📥 완성된 빈칸 학습지 PDF 다운로드",
                        data=st.session_state['generated_pdf'],
                        file_name=f"blank_study_{uploaded_file.name}",
                        mime="application/pdf",
                        type="primary"
                    )
        else:
            st.warning("👈 왼쪽에서 PDF 파일을 업로드해 주세요.")

if __name__ == "__main__":
    main()
