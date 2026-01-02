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

# --- 설정값 (GitHub Secrets에서 불러옴) ---
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
    """DART에서 고유번호 XML을 다운로드하여 파일로 저장 (월 1회 권장)"""
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {'crtfc_key': DART_API_KEY}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall(DATA_DIR) # CORPCODE.xml 압축 해제
            # 편의상 이름을 고정
            extracted_name = z.namelist()[0]
            os.rename(os.path.join(DATA_DIR, extracted_name), CORP_CODE_FILE)
        print("고유번호 파일 업데이트 완료.")
    except Exception as e:
        print(f"고유번호 다운로드 실패: {e}")

def get_corp_code_from_file(target_corp_name):
    """저장된 XML 파일에서 고유번호 검색"""
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

# --- 2. 공시 검색 ---
def get_recent_filings(corp_code):
    """최근 7일간 공시 검색"""
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
        # 접수번호(rcept_no)는 고유 ID이므로 이를 기준으로 정렬 및 비교
        df['rcept_dt'] = pd.to_datetime(df['rcept_dt'])
        df = df.sort_values(by='rcept_no', ascending=True) # 과거 -> 최신 순
        return df
    return pd.DataFrame()

# --- 3. AI 분석 ---
def analyze_content(row):
    """
    공시 제목과 유형을 기반으로 AI 분석 수행
    (실제 본문 스크래핑은 복잡도가 높아 메타데이터와 링크 기반 분석으로 대체)
    """
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    
    # 분석할 텍스트 구성
    link = f"http://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"
    prompt_text = (
        f"공시 제목: {row['report_nm']}\n"
        f"회사명: {row['corp_name']}\n"
        f"제출인: {row['flr_nm']}\n"
        f"접수일자: {row['rcept_dt']}\n"
        f"공시 링크: {link}\n\n"
        "위 정보를 바탕으로 이 공시가 투자자에게 어떤 의미가 있는지, "
        "호재(Positive)/악재(Negative)/중립(Neutral) 중 무엇인지 판단하고 "
        "핵심 내용을 3줄로 요약해줘."
    )

    try:
        completion = client.chat.completions.create(
            extra_headers={"HTTP-Referer": "https://github.com", "X-Title": "DartBot"},
            model="xiaomi/mimo-v2-flash:free",
            messages=[
                {"role": "system", "content": "당신은 주식 시장 전문가입니다. 한국어로 답변하세요."},
                {"role": "user", "content": prompt_text}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI 분석 실패: {e}"

# --- 4. 텔레그램 전송 ---
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, data=payload)

# --- 메인 로직 ---
def main():
    # 1. 이전 상태 로드
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {}

    # 2. 감시 대상 회사 로드
    if not os.path.exists(COMPANIES_FILE):
        print("회사 목록 파일이 없습니다.")
        return
    
    with open(COMPANIES_FILE, 'r', encoding='utf-8') as f:
        companies = [line.strip() for line in f if line.strip()]

    # 3. 각 회사별 공시 확인
    updated_state = state.copy()
    
    for corp_name in companies:
        print(f"[{corp_name}] 검색 시작...")
        
        # 고유번호 찾기
        code = get_corp_code_from_file(corp_name)
        if not code:
            print(f" -> 고유번호를 찾을 수 없음. (refresh 필요 가능성)")
            continue
            
        # 최신 공시 가져오기
        df = get_recent_filings(code)
        if df.empty:
            continue
            
        # 마지막으로 확인한 공시 번호 (없으면 0)
        last_rcept_no = state.get(corp_name, "00000000000000")
        
        # 새로운 공시 필터링 (접수번호가 저장된 것보다 큰 경우만)
        new_filings = df[df['rcept_no'] > last_rcept_no]
        
        if new_filings.empty:
            print(" -> 새로운 공시 없음")
            continue
            
        # 새로운 공시 처리
        for _, row in new_filings.iterrows():
            print(f" -> 새 공시 발견: {row['report_nm']}")
            
            # AI 분석
            ai_result = analyze_content(row)
            
            # 메시지 작성
            msg = (
                f"🚨 *DART 알림: {row['corp_name']}*\n"
                f"📄 {row['report_nm']}\n"
                f"🔗 [링크 보기](http://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']})\n\n"
                f"🤖 *AI 요약:*\n{ai_result}"
            )
            
            # 텔레그램 전송
            send_telegram(msg)
            
            # 상태 업데이트 (가장 최근 번호로)
            updated_state[corp_name] = row['rcept_no']

    # 4. 상태 저장
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(updated_state, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    # 고유번호 파일이 없으면 강제 다운로드 (최초 실행 시)
    if not os.path.exists(CORP_CODE_FILE):
        update_corp_code_file()
        
    # 메인 실행 시 인자(argument)에 따라 동작 구분 가능
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'refresh':
        update_corp_code_file()
    else:
        main()