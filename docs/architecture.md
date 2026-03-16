# 아키텍처 가이드

이 문서는 현재 `cryptolight` 코드베이스가 어떤 경계로 나뉘어 있는지 설명한다. 처음 진입할 때는 `main.py`만 보면 전체 흐름을 잡을 수 있지만, 실제 구현은 `runtime` 모듈과 도메인 하위 패키지로 분리되어 있으므로 각 계층의 책임을 먼저 이해하는 편이 훨씬 빠르다.

## 진입점과 런타임 조립

실행 진입점은 [`src/cryptolight/main.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/main.py)다. 이 파일의 역할은 설정을 읽고, bootstrap 세션을 만들고, 런타임 서비스와 스케줄러를 시작하는 데 있다. 전략 계산, 텔레그램 리포트 생성, 자기개선 로직 같은 세부 구현은 더 이상 이 파일에 직접 들어 있지 않고 `src/cryptolight/runtime/` 아래 모듈로 이동해 있다.

런타임 조립은 [`src/cryptolight/runtime/bootstrap.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/bootstrap.py)에서 시작된다. 여기서 텔레그램 봇, 명령 핸들러, SQLite 저장소, 업비트 클라이언트, 브로커, 리스크 가드, 캐시, AI 어시스턴트, 종목 선택 결과를 `RuntimeSession`으로 모은다. `main.py`는 이 세션을 받아 전역 wrapper와 연결한 뒤 실행 모드를 고른다. 이 구조는 초기화 단계에서 실패한 지점과 운영 중 사용하는 객체 구성을 분리해서 보기 쉽게 만든다.

## Runtime 모듈 경계

`src/cryptolight/runtime/` 아래는 실행 중 책임에 따라 나뉜다. [`strategy_engine.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/strategy_engine.py)는 각 종목의 캔들 조회, 시그널 계산, 손절/익절, WebSocket 기반 청산, 주기 요약을 담당한다. [`commanding.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/commanding.py)는 텔레그램 long polling 루프와 `/status`, `/info`, `/report`, `/ask` 같은 운영 명령을 처리한다. [`reporting.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/reporting.py)는 텔레그램에 보여줄 텍스트를 만드는 계층이고, [`improvement.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/improvement.py)는 전략 전환과 파라미터 튜닝 루프를 담당한다.

스케줄러와 서비스 wiring은 [`orchestrator.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/orchestrator.py)에 있다. APScheduler job 등록, WebSocket 시작, 웹 대시보드 부팅, 일일 요약 job이 여기에 들어 있다. 공유 상태는 [`state.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/runtime/state.py)에 모여 있으며, 대시보드와 텔레그램이 같이 보는 market snapshot과 활성 종목 목록을 관리한다. 런타임 관련 변경을 할 때는 먼저 이 여섯 모듈 중 어느 계층의 책임인지 판단하고 들어가면 `main.py`를 다시 키우지 않을 수 있다.

## 도메인 계층

실제 매매 로직과 데이터 처리 코드는 runtime 바깥 패키지에 있다. [`strategy/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/strategy)에는 RSI, MACD, Bollinger, score 전략이 들어 있고, [`risk/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/risk)에는 손절/익절, 쿨다운, 포지션 사이징, 리스크 가드가 있다. [`execution/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/execution)에는 paper/live 브로커가 있고, [`exchange/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/exchange)에는 업비트 API와 캔들 캐시가 있다. [`evaluation/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/evaluation)에는 성과 평가, 전략 경쟁, adaptive controller, 파라미터 optimizer가 있다.

저장소 계층은 [`storage/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/storage)에 있다. 거래 내역, 포지션, 전략 파라미터 상태, 자동 조정 이력 같은 영속 데이터는 모두 여기서 다뤄진다. 시장 보조 기능은 [`market/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/market)에 있고, 국면 감지와 실시간 가격 스트림, 스크리닝 파이프라인이 여기에 모여 있다. 이 분리는 도메인 규칙과 실행 조립을 분리하려는 목적을 가진다.

## 인터페이스 계층

외부와 직접 맞닿는 부분은 [`bot/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/bot)과 [`web/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/web), [`backtest/`](/home/faeqsu10/projects/cryptolight/src/cryptolight/backtest)다. `bot`은 텔레그램 전송과 명령 처리, AI assistant 포맷팅을 담당하고, `web`은 FastAPI 대시보드와 HTML 템플릿을 담당한다. `backtest`는 별도 CLI 진입점과 walk-forward 실행 코드를 가진다. 운영 장애를 볼 때 텔레그램 문제는 `bot`과 `runtime/commanding.py`, 대시보드 문제는 `web`과 `runtime/orchestrator.py`를 같이 보면 된다.

설정 해석은 [`config/settings.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/config/settings.py)에 있고, 로깅은 [`utils/logger.py`](/home/faeqsu10/projects/cryptolight/src/cryptolight/utils/logger.py)에 있다. 운영에서는 `~/.config/cryptolight/cryptolight.env`를 기준으로 설정을 관리하고, 서비스 템플릿은 [`deploy/systemd/cryptolight.service`](/home/faeqsu10/projects/cryptolight/deploy/systemd/cryptolight.service)를 기준으로 본다.

## 실제 코드 탐색 순서

새 기능을 넣을 때는 먼저 `main.py`에서 어느 runtime helper를 호출하는지 보고, 그 helper가 runtime 계층에서 어떤 도메인 패키지를 쓰는지 따라가면 된다. 예를 들어 전략 실행 흐름을 바꾸고 싶다면 `main.py -> runtime/strategy_engine.py -> strategy/ + risk/ + execution/ + storage/` 순으로 읽는 편이 빠르다. 운영 장애를 추적할 때는 `runtime/orchestrator.py`, `runtime/commanding.py`, `runtime/state.py`, `utils/logger.py`를 먼저 보고 그 다음 도메인 계층으로 내려가는 편이 효율적이다.

지금 구조는 “실행 조립”과 “도메인 구현”을 분리하는 방향으로 정리된 상태다. 다음 유지보수 단계에서는 `main.py`에 남아 있는 thin wrapper를 더 줄이고, 전략 활성 상태와 전역 mutable 값을 `runtime/state.py` 쪽으로 천천히 옮겨서 entrypoint를 더 명확한 shell로 만드는 작업이 자연스럽다.
