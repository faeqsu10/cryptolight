# 설정 가이드

cryptolight을 처음 설정하는 경우 이 문서를 따라 진행하세요. 로컬 개발은 저장소 루트의 `.env`를 써도 되지만, 장기 운영은 `~/.config/cryptolight/cryptolight.env`를 권장합니다. 운영 배치는 [운영 가이드](operations.md)를 참고하세요.

## 1. 업비트 API 키 발급

시작 전에 운영 환경이라면 `~/.config/cryptolight/cryptolight.env`를 만들고 그 파일에 설정을 채우는 방식을 권장한다. 로컬 개발만 할 때는 저장소 루트 `.env`를 그대로 사용해도 된다.

1. [업비트](https://upbit.com) 로그인
2. **마이페이지 > Open API 관리** 이동
3. **Open API Key 발급하기** 클릭
4. 허용 항목 선택:
   - **자산조회**: 필수 (잔고 확인)
   - **주문조회**: 필수 (주문 상태 확인)
   - **주문하기**: `TRADE_MODE=live`일 때 필수
   - **출금하기**: 절대 체크하지 마세요
5. IP 주소 등록 (봇이 실행되는 서버 IP)
6. 발급된 `Access Key`와 `Secret Key`를 `.env`에 입력

```bash
UPBIT_ACCESS_KEY=발급받은_access_key
UPBIT_SECRET_KEY=발급받은_secret_key
```

> Paper 모드(`TRADE_MODE=paper`)에서는 자산조회 권한만으로도 작동합니다.

## 2. 텔레그램 봇 생성

1. 텔레그램에서 [@BotFather](https://t.me/BotFather)를 검색하여 대화 시작
2. `/newbot` 입력 → 봇 이름과 username 설정
3. 발급된 **Bot Token**을 `.env`에 입력

```bash
TELEGRAM_BOT_TOKEN=발급받은_봇_토큰
```

## 3. 텔레그램 Chat ID 확인

1. 생성한 봇에게 아무 메시지 전송
2. 브라우저에서 아래 URL 접속 (TOKEN을 실제 토큰으로 교체):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. 응답 JSON에서 `"chat": {"id": 123456789}` 부분의 숫자가 Chat ID

```bash
TELEGRAM_CHAT_ID=확인한_chat_id
```

운영 파일을 따로 두고 싶다면 아래처럼 외부 파일로 옮기면 된다.

```bash
mkdir -p ~/.config/cryptolight
cp .env.example ~/.config/cryptolight/cryptolight.env
chmod 600 ~/.config/cryptolight/cryptolight.env
```

## 4. 첫 실행

```bash
python -m cryptolight.main
```

기본 설정(`TRADE_MODE=paper`)으로 실행하면:
- 가상 잔고 100만원으로 시뮬레이션 시작
- 60분마다 전략 분석, 5분 폴링 또는 WebSocket으로 손절/익절 감시
- 매수/매도 시그널 발생 시 텔레그램으로 알림
- 실제 주문은 실행되지 않음

## 5. Paper → Live 전환

1. 충분한 기간(최소 1~2주) paper 모드에서 성과 확인
2. `.env` 수정:
   ```bash
   TRADE_MODE=live
   MAX_ORDER_AMOUNT_KRW=10000  # 소액부터 시작
   ```
3. 업비트 API 키에 **주문하기** 권한이 있는지 확인
4. 봇 재시작

> Live 모드에서는 하드캡(기본 50만원)이 적용되어 1회 주문이 초과하면 자동 차단됩니다.
