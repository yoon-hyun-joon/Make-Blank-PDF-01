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
# 1. Korean Font Setup (Noto Sans CJK / NanumGothic Fallback)
# ---------------------------------------------------------
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto-cjk/NotoSansKR-Regular.ttf",
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
# 3. PDF Parsing & Core Logic
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

def extract_auto_keywords_fallback(text_list, max_keywords=30):
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

def get_working_gemini_model(api_key):
    if not HAS_GENAI:
        return None
    clean_key = api_key.strip().strip("'").strip('"')
    genai.configure(api_key=clean_key)
    try:
        models = genai.list_models()
        for m in models:
            if 'generateContent' in m.supported_generation_methods:
                m_name = m.name.replace('models/', '')
                try:
                    model = genai.GenerativeModel(m_name)
                    resp = model.generate_content("test")
                    if resp and resp.text:
                        return model
                except Exception:
                    continue
    except Exception:
        pass
    return genai.GenerativeModel('gemini-1.5-flash')

def extract_keywords_with_gemini(api_key, text_list, num_keywords=30):
    model = get_working_gemini_model(api_key)
    if not model:
        return []
    full_text = "\n".join(text_list)[:10000]
    prompt = f"""
    다음 교육/학습 문서에서 가장 핵심이 되는 주요 용어, 개념, 학자 이름, 전문 키워드를 {num_keywords}개 선정해 주세요.
    
    조건:
    1. 한국어 조사(은/는/이/가/의/에/로/을/를/과/와/도/만/에서/부터/까지 등)를 완전히 제거한 순수한 개념어/명사 형태만 반환하세요.
    2. 쉼표(,)로만 구분하여 단어 목록만 출력하세요.
    3. 부연 설명, 번호, 개간, 안내 문구는 절대로 포함하지 마세요.
    
    [문서 내용]:
    {full_text}
    """
    response = model.generate_content(prompt)
    raw_response = response.text.strip()
    keywords = [k.strip() for k in raw_response.replace("\n", "").split(",") if k.strip()]
    return keywords

def generate_blank_pdf(pages_text, target_keywords):
    """
    개별 항목이나 문단 구분을 전혀 하지 않고,
    원문 텍스트 전체를 하나의 연속된 줄글(Running Prose) 형태로 연결하여 생성합니다.
    """
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
        spaceAfter=12
    )
    
    body_style = ParagraphStyle(
        'BodyTextKorean',
        fontName=FONT_NAME,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=10
    )
    
    story = []
    story.append(Paragraph("<b>📄 PDF 빈칸 학습지 (Blank Study Guide)</b>", title_style))
    story.append(Paragraph("원문의 전체 내용을 항목 및 문단 구분 없이 하나의 줄글(연속 텍스트)로 연결하여 핵심 키워드를 빈칸으로 재구성하였습니다.", body_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=15))
    
    # 1. 모든 페이지의 단어들을 단일 공백으로 연결하여 하나의 연속된 줄글(Full Prose) 생성
    all_words = []
    for page_text in pages_text:
        words = page_text.split()
        if words:
            all_words.extend(words)
            
    full_prose = " ".join(all_words)
    
    # 2. HTML 이스케이프 처리 및 키워드 빈칸 치환
    escaped_prose = html.escape(full_prose)
    sorted_keywords = sorted(list(set(target_keywords)), key=len, reverse=True)
    
    blank_counter = 1
    answer_key = []
    placeholders = {}
    
    for kw in sorted_keywords:
        if not kw or len(kw) < 2:
            continue
        escaped_kw = html.escape(kw)
        if escaped_kw in escaped_prose:
            ph_key = f"__BLANK_{blank_counter}__"
            placeholders[ph_key] = f'<font color="#D32F2F"><b>[ {blank_counter}. ____________ ]</b></font>'
            answer_key.append((blank_counter, kw))
            escaped_prose = escaped_prose.replace(escaped_kw, ph_key, 1)
            blank_counter += 1
            
    for ph_key, val in placeholders.items():
        escaped_prose = escaped_prose.replace(ph_key, val)
        
    # 3. 연속 줄글 텍스트를 ~1500자 단위로 나누어 렌더링 (ReportLab 용지 레이아웃에 맞춰 연속 표시)
    chunk_size = 1500
    words_in_prose = escaped_prose.split(' ')
    current_chunk = []
    current_length = 0
    
    for w in words_in_prose:
        current_chunk.append(w)
        current_length += len(w) + 1
        if current_length >= chunk_size:
            story.append(Paragraph(" ".join(current_chunk), body_style))
            current_chunk = []
            current_length = 0
            
    if current_chunk:
        story.append(Paragraph(" ".join(current_chunk), body_style))
        
    # 4. 정답지 페이지 (Answer Key)
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2B6CB0"), spaceBefore=20, spaceAfter=15))
    story.append(Paragraph("<b>🗝️ 정답지 (Answer Key)</b>", title_style))
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
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(ans_table)
        
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer, len(answer_key)

def main():
    st.set_page_config(page_title="PDF 빈칸 학습지 생성기", page_icon="✏️", layout="wide")
    st.title("✏️ PDF 빈칸 학습지 자동 생성기")
    st.markdown("PDF 원문의 전체 내용을 항목/문단 구분 없이 **하나의 연속된 줄글(연속 텍스트)**로 연결하여 빈칸 학습지를 만들어 드립니다.")
    st.divider()
    
    with st.sidebar:
        st.header("⚙️ API 설정 (선택사항)")
        api_key = st.text_input("🔑 Gemini API Key 입력", type="password", help="입력하지 않으셔도 스마트 알고리즘으로 작동합니다.")
        st.markdown("[👉 무료 Gemini API Key 발급받기](https://aistudio.google.com/app/apikey)")
        st.divider()
        
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("1. PDF 파일 업로드")
        uploaded_file = st.file_uploader("학습지로 만들 PDF 파일 선택", type=["pdf"])
        
        st.subheader("2. 키워드 설정")
        num_kw = st.slider("추출할 핵심 키워드 개수", min_value=10, max_value=80, value=30, step=5)
        
    with col2:
        st.subheader("3. 결과 확인 및 PDF 생성")
        if uploaded_file is not None:
            file_id = f"{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.get('last_file_id') != file_id:
                st.session_state['last_file_id'] = file_id
                st.session_state.pop('ai_keywords', None)
                
            pdf_bytes = uploaded_file.getvalue()
            pages_text = extract_text_from_pdf(pdf_bytes)
            
            if not pages_text:
                st.error("❌ PDF에서 텍스트를 추출할 수 없습니다. 스캔 이미지 PDF인지 확인하세요.")
            else:
                st.success(f"✅ 총 {len(pages_text)}페이지의 텍스트가 정상 추출되었습니다.")
                
                if st.button("🚀 핵심 키워드 자동 추출 실행하기", type="primary"):
                    with st.spinner("원문 분석 및 핵심 키워드 추출 중..."):
                        keywords = []
                        if api_key.strip():
                            try:
                                keywords = extract_keywords_with_gemini(api_key, pages_text, num_keywords=num_kw)
                            except Exception:
                                pass
                        if not keywords:
                            keywords = extract_auto_keywords_fallback(pages_text, max_keywords=num_kw)
                            
                        st.session_state['ai_keywords'] = keywords
                        st.success(f"🎉 {len(keywords)}개의 핵심 키워드가 선별되었습니다!")
                        
                if st.session_state.get('ai_keywords'):
                    selected_kw = st.multiselect(
                        "선별된 핵심 키워드 (제외하고 싶은 단어는 ❌를 누르세요)",
                        options=st.session_state['ai_keywords'],
                        default=st.session_state['ai_keywords']
                    )
                    
                    if selected_kw:
                        out_buffer, total_blanks = generate_blank_pdf(pages_text, selected_kw)
                        st.success(f"🎉 줄글 형태로 연결된 {total_blanks}개 빈칸 학습지가 완성되었습니다!")
                        st.download_button(
                            label="📥 완성된 PDF 학습지 다운로드",
                            data=out_buffer.getvalue(),
                            file_name=f"blank_study_{uploaded_file.name}",
                            mime="application/pdf",
                            type="primary"
                        )
        else:
            st.warning("👈 왼쪽에서 PDF 파일을 업로드해 주세요.")

if __name__ == "__main__":
    main()
