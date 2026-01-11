# 📈 DART 공시 모니터링 & AI 분석 봇

DART(전자공시시스템)에서 관심 기업의 새로운 공시를 실시간으로 감지하고, AI를 활용해 핵심 내용을 분석하여 텔레그램으로 알림을 보내주는 자동화 봇입니다.

## ✨ 주요 기능

- **자동 모니터링**: 등록된 관심 기업의 새 공시를 주기적으로 확인합니다.
- **AI 기반 분석**: OpenAI(OpenRouter) 모델을 사용하여 복잡한 공시 내용을 누구나 알기 쉽게 요약합니다.
    - **3줄 요약**: 핵심 내용만 빠르게 파악
    - **주가 영향**: 호재/악재/중립 판단 및 이유 설명
    - **투자 유의사항**: 놓치기 쉬운 리스크 포착
- **텔레그램 알림**: 분석된 보고서와 공시 원문 링크를 텔레그램으로 즉시 전송합니다.
- **GitHub Actions 자동화**: 별도의 서버 없이 GitHub Actions를 통해 평일 장중/장마감 후 자동으로 실행됩니다.
- **중복 방지**: 이미 처리한 공시는 스마트하게 건너뜁니다.

## 🛠️ 사전 준비 (Requirements)

이 프로젝트를 실행하기 위해서는 아래의 API 키들이 필요합니다.

1. **DART API Key**: [Open DART](https://opendart.fss.or.kr/)에서 인증키 발급
2. **OpenRouter API Key**: [OpenRouter](https://openrouter.ai/)에서 발급 (또는 OpenAI API 사용 가능하도록 코드 수정 가능)
3. **Telegram Bot Token & Chat ID**: [BotFather](https://t.me/BotFather)를 통해 봇 생성 및 ID 확인

## 🚀 설치 및 설정 방법 (Installation)

### 1. 저장소 복제 (Clone)
```bash
git clone https://github.com/your-username/my-dart-monitor.git
cd my-dart-monitor
```

### 2. 관심 기업 등록
`data/companies.txt` 파일을 열고 모니터링하고 싶은 기업명을 한 줄에 하나씩 입력하세요.
```text
삼성전자
카카오
NAVER
현대차
```

### 3. 로컬 실행 환경 설정 (Optional)
로컬에서 테스트하려면 Python 3.9+ 환경이 필요합니다.
```bash
pip install -r requirements.txt
```

### 4. 환경 변수 설정
로컬 실행 시에는 환경 변수를 설정하거나 코드 내에서 직접 입력해야 하지만, 보안을 위해 **환경 변수 사용을 권장**합니다.
```bash
export DART_API_KEY="your_dart_key"
export OPENROUTER_API_KEY="your_openrouter_key"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

## 🤖 사용 방법 (Usage)

### GitHub Actions (자동 실행)
이 저장소는 GitHub Actions를 통해 자동으로 돌아가도록 설정되어 있습니다.
GitHub 저장소의 `Settings` -> `Secrets and variables` -> `Actions` 메뉴에서 아래의 **Repository Secrets**를 등록해주세요.

| Secret Name          | 설명                           |
| -------------------- | ------------------------------ |
| `DART_API_KEY`       | DART API 인증키                |
| `OPENROUTER_API_KEY` | AI 분석을 위한 API 키          |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰               |
| `TELEGRAM_CHAT_ID`   | 알림을 받을 텔레그램 채팅방 ID |

**실행 스케줄 (한국 시간 기준):**
- **장 마감 후**: 월~금 07:30, 07:40, 07:50 (전일 공시 확인)
- **개장 전**: 월~금 08:00 ~ 08:50 (10분 간격)
- **장 중**: 월~금 09:00 ~ 18:50 (10분 간격)
- **야간**: 월~금 19:00 (마감 정리)

### 로컬 수동 실행
```bash
python main.py
```
> 최초 실행 시 `data/corp_codes.xml` 파일을 다운로드 받습니다.

## 📂 파일 구조

```
my-dart-monitor/
├── .github/workflows/
│   └── dart_monitor.yml   # GitHub Actions 자동화 스크립트
├── data/
│   ├── companies.txt      # 관심 기업 목록 (사용자 수정)
│   ├── corp_codes.xml     # DART 고유번호 리스트 (자동 생성)
│   └── latest_filings.json# 마지막 공시 처리 상태 저장 (자동 업데이트)
├── main.py                # 메인 로직 코드
├── requirements.txt       # 의존성 라이브러리 목록
└── README.md
```

## ⚠️ 주의사항
- DART API는 일일 호출 횟수 제한이 있을 수 있습니다.
- AI 분석 결과는 참고용이며, 투자의 책임은 사용자에게 있습니다.
- 50일 이상 커밋이 없으면 GitHub Actions가 비활성화될 수 있어, 이를 방지하는 `Keepalive` 로직이 포함되어 있습니다.

## 📜 License
This project is licensed under the MIT License.
