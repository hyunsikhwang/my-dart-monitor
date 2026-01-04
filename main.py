import os
import json
import requests
import zipfile
import io
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil.relativedelta import relativedelta
from openai import OpenAI
from bs4 import BeautifulSoup  # 추가된 라이브러리

# --- 설정값 (GitHub Secrets) ---
DART_API_KEY = os.environ.get("DART_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 파일 경로
DATA_DIR = "data"
COMPANIES_FILE = os.path.join(DATA_DIR, "companies.txt")
CORP_CODE_FILE = os.path.join(DATA_DIR, "corp_codes.xml")
STATE_FILE = os.path.join(DATA_DIR, "latest_filings.json")

# --- 1. DART 고유번호 관리 ---
def update_corp_code_file():
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {'crtfc_key': DART_API_KEY}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall(DATA_DIR)
            extracted_name = z.namelist()[0]
            os.rename(os.path.join(DATA_DIR, extracted_name), CORP_CODE_FILE)
        print("고유번호 파일 업데이트 완료.")
    except Exception as e:
        print(f"고유번호 다운로드 실패: {e}")

def get_corp_code_from_file(target_corp_name):
    if not os.path.exists(CORP_CODE_FILE):
        return None
    try:
        tree = ET.parse(CORP_CODE_FILE)
        root = tree.getroot()
        for corp_data in root.findall('list'):
            if corp_data.find('corp_name').text.strip() == target_corp_name:
                return corp_data.find('corp_code').text.strip()
    except Exception as e:
        print(f"XML 파싱 에러: {e}")
    return None

def clean_html_for_ai(html_content):
    """HTML/XML 태그 제거 및 텍스트 정제"""
    try:
        # [수정] 'lxml' 대신 'xml' 파서 사용 (DART 문서는 XML 형식이므로 필수)
        soup = BeautifulSoup(html_content, 'xml') 

        # 1. 불필요한 태그 제거
        for script in soup(["script", "style", "head", "meta", "noscript"]):
            script.extract()

        # 2. 텍스트 추출
        text = soup.get_text(separator="\n\n")

        # 3. 공백 정리
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        return text
    except Exception as e:
        return f"텍스트 정제 중 오류: {e}"

def fetch_and_extract_dart_content(crtfc_key, rcept_no):
    """
    DART API에서 공시 원문(XML)을 다운로드하여 AI용 텍스트로 정제합니다.
    """

    # 1. API 요청 URL 생성
    api_url = "https://opendart.fss.or.kr/api/document.xml"
    params = {
        'crtfc_key': crtfc_key,
        'rcept_no': rcept_no
    }

    print(f"🔄 요청 중... (접수번호: {rcept_no})")

    try:
        # 2. 파일 다운로드 (Stream 방식)
        response = requests.get(api_url, params=params)
        response.raise_for_status() # 에러 발생 시 중단

        # 3. ZIP 파일 처리 (디스크 저장 없이 메모리에서 바로 해제)
        # DART document.xml API는 항상 ZIP 파일을 반환합니다.
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # 압축 파일 내의 파일 목록 확인
            file_list = z.namelist()
            print(f"📦 압축 파일 내 파일 목록: {file_list}")

            # 보통 첫 번째 파일이 주된 공시 문서입니다. (혹은 .xml로 끝나는 파일 찾기)
            xml_filename = [f for f in file_list if f.endswith('.xml')][0]

            with z.open(xml_filename) as f:
                xml_content = f.read().decode('utf-8') # 한글 디코딩

        print("✅ 다운로드 및 압축 해제 완료. 텍스트 정제 시작...")

        # 4. 텍스트 정제 (AI Input 최적화)
        clean_text = clean_html_for_ai(xml_content)

        return clean_text

    except requests.exceptions.RequestException as e:
        return f"❌ 네트워크 오류 발생: {e}"
    except zipfile.BadZipFile:
        return "❌ 유효하지 않은 ZIP 파일입니다. API Key나 접수번호를 확인해주세요."
    except Exception as e:
        return f"❌ 알 수 없는 오류 발생: {e}"

# --- 3. 공시 검색 및 AI 분석 ---
def get_recent_filings(corp_code):
    dt_end = datetime.now()
    dt_start = dt_end - relativedelta(days=7)
    
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        'crtfc_key': DART_API_KEY,
        'corp_code': corp_code,
        'bgn_de': dt_start.strftime("%Y%m%d"),
        'end_de': dt_end.strftime("%Y%m%d"),
        'page_count': 50
    }
    
    res = requests.get(url, params=params)
    data = res.json()
    
    if data.get('status') == '000':
        df = pd.DataFrame(data.get('list', []))
        df['rcept_dt'] = pd.to_datetime(df['rcept_dt'])
        df = df.sort_values(by='rcept_no', ascending=True)
        return df
    return pd.DataFrame()

def analyze_content(row):
    """공시 본문을 가져와 AI에게 분석 요청"""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    
    # 1. 본문 텍스트 추출
    raw_content = fetch_and_extract_dart_content(DART_API_KEY, row['rcept_no'])
    
    # [방어 로직] 본문이 너무 짧거나(오류 메시지 등) 비어 있으면 분석 중단
    if not raw_content or len(raw_content) < 50:
        return "⚠️ 공시 본문이 너무 짧거나 비어있어 분석할 수 없습니다. (첨부파일 위주 공시일 가능성)"

    # 2. 텍스트 길이 제한
    max_length = 15000
    if len(raw_content) > max_length:
        content_to_analyze = raw_content[:max_length] + "\n...(내용이 너무 길어 생략됨)"
    else:
        content_to_analyze = raw_content

    # 3. 프롬프트 구성
    link = f"http://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"
    
    prompt_text = (
        f"[공시 정보]\n"
        f"제목: {row['report_nm']}\n"
        f"회사명: {row['corp_name']}\n"
        f"제출인: {row['flr_nm']}\n"
        f"링크: {link}\n\n"
        f"[공시 본문 내용 (일부 발췌)]\n"
        f"{content_to_analyze}\n\n"
        f"""[요청 사항]\n"
당신은 주식 시장 금융 전문가입니다. 위 공시 내용을 분석하여 다음을 수행하세요:
1. 이 공시의 핵심 내용을 3개의 bullet point로 명확하게 요약하세요.
2. 이 내용이 주가에 미칠 영향(호재/악재/중립 중 택 1)을 판단하고 그 이유를 한 문장으로 설명하세요.
3. 투자자가 유의해야 할 리스크나 특이사항이 있다면 언급하세요.
답변은 한국어로 작성하세요."""
    )

    try:
        completion = client.chat.completions.create(
            extra_headers={"HTTP-Referer": "https://github.com", "X-Title": "DartBot"},
            model="xiaomi/mimo-v2-flash:free",
            messages=[
                {"role": "system", "content": "핵심만 간결하게 전달하는 금융 전문가입니다."},
                {"role": "user", "content": prompt_text}
            ]
        )
        
        # [수정] 응답 객체 확인 (NoneType 에러 방지)
        if completion and completion.choices:
            return completion.choices[0].message.content
        else:
            return "AI 모델이 응답을 반환하지 않았습니다."
            
    except Exception as e:
        return f"AI 분석 실패: {e}"

# --- 4. 텔레그램 전송 ---
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, data=payload)

# --- 메인 실행부 ---
def main():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {}

    if not os.path.exists(COMPANIES_FILE):
        print("회사 목록 파일이 없습니다.")
        return
    
    with open(COMPANIES_FILE, 'r', encoding='utf-8') as f:
        companies = [line.strip() for line in f if line.strip()]

    updated_state = state.copy()
    
    for corp_name in companies:
        print(f"[{corp_name}] 검색 시작...")
        
        code = get_corp_code_from_file(corp_name)
        if not code:
            print(f" -> 고유번호 없음.")
            continue
            
        df = get_recent_filings(code)
        if df.empty:
            continue
            
        last_rcept_no = state.get(corp_name, "00000000000000")
        new_filings = df[df['rcept_no'] > last_rcept_no]
        
        if new_filings.empty:
            print(" -> 새로운 공시 없음")
            continue
            
        for _, row in new_filings.iterrows():
            print(f" -> 새 공시 분석 중: {row['report_nm']}")
            
            ai_result = analyze_content(row)
            
            msg = (
                f"🚨 *DART 알림: {row['corp_name']}*\n"
                f"📄 {row['report_nm']}\n"
                f"🔗 [링크 보기](http://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']})\n\n"
                f"📝 *AI 분석 보고서:*\n{ai_result}"
            )
            
            send_telegram(msg)
            updated_state[corp_name] = row['rcept_no']

    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(updated_state, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    if not os.path.exists(CORP_CODE_FILE):
        update_corp_code_file()
        
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'refresh':
        update_corp_code_file()
    else:
        main()