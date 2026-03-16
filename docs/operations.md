# 운영 가이드

이 문서는 `cryptolight`를 로컬 개발 환경이 아니라 지속 실행되는 봇으로 운영할 때 필요한 파일 배치와 점검 절차를 정리한다. 저장소 안의 코드와 저장소 밖의 런타임 설정을 분리해 두면 배포 경로를 바꾸거나 저장소를 다시 clone해도 운영 상태를 복구하기 쉬워진다.

## 런타임 설정 파일

운영 설정은 저장소 루트의 `.env` 대신 `~/.config/cryptolight/cryptolight.env`에 두는 방식을 기본으로 삼는다. 애플리케이션은 `CRYPTOLIGHT_ENV_FILE` 환경변수가 있으면 그 파일을 먼저 읽고, 값이 없으면 `~/.config/cryptolight/cryptolight.env`, 마지막으로 저장소 루트의 `.env`를 읽는다. 이 순서를 사용하면 `systemd` 서비스는 저장소 밖 설정을 기준으로 움직이고, 개발 중 단발 실행은 기존 `.env`를 그대로 사용할 수 있다.

처음 구성할 때는 `.env.example`을 외부 경로로 복사한 뒤 실제 키와 운영값을 채운다.

```bash
mkdir -p ~/.config/cryptolight
cp /home/faeqsu10/projects/cryptolight/.env.example ~/.config/cryptolight/cryptolight.env
chmod 600 ~/.config/cryptolight/cryptolight.env
```

운영 중에는 저장소 안 `.env`보다 외부 파일을 수정하는 것을 기준으로 삼는다. 이렇게 해두면 저장소를 업데이트해도 민감한 설정과 운영 튜닝값이 작업 트리에 섞이지 않는다.

## systemd user service

서비스 정의는 저장소에 있는 [`deploy/systemd/cryptolight.service`](/home/faeqsu10/projects/cryptolight/deploy/systemd/cryptolight.service)를 기준으로 관리한다. 활성 서비스 파일이 저장소 밖에만 있으면 왜 특정 환경변수나 실행 옵션을 쓰는지 변경 이력이 남지 않기 때문에, 템플릿을 저장소에 두고 실제 서비스 파일은 그 내용을 복사하는 방식이 유지보수에 유리하다.

```bash
mkdir -p ~/.config/systemd/user
cp /home/faeqsu10/projects/cryptolight/deploy/systemd/cryptolight.service \
  ~/.config/systemd/user/cryptolight.service
systemctl --user daemon-reload
systemctl --user enable cryptolight.service
systemctl --user restart cryptolight.service
loginctl enable-linger $(whoami)
```

서비스는 `CRYPTOLIGHT_ENV_FILE=%h/.config/cryptolight/cryptolight.env`를 주입하므로 저장소 밖 설정 파일을 읽는다. 저장소를 다른 경로로 옮기면 서비스 파일의 `WorkingDirectory`와 `ExecStart`만 바꾸면 되고, 운영 설정 파일은 그대로 재사용할 수 있다.

## 로그와 상태 확인

운영 중 문제를 먼저 확인할 곳은 `systemd` 저널과 회전 파일 로그 두 군데다. `journalctl`은 재시작, 종료 시그널, 표준출력에 찍힌 예외를 빠르게 확인할 때 적합하고, `logs/cryptolight.log`는 장기 추적과 grep에 편하다. 현재 로깅은 `cryptolight.*` 하위 로거 전체가 같은 포맷을 사용하며, 토큰과 API 키는 마스킹된다.

```bash
journalctl --user -u cryptolight.service -f
tail -f /home/faeqsu10/projects/cryptolight/logs/cryptolight.log
```

대시보드가 켜져 있다면 `/api/status` 응답의 `market_updated_at`과 `market_age_seconds`를 보면 엔진이 마지막으로 상태를 갱신한 시점을 바로 확인할 수 있다. 이 값이 오래됐는데 서비스는 살아 있다면 스케줄러가 밀리거나 거래소 호출이 막혔는지 로그를 함께 봐야 한다.

## 백업과 복구

운영 상태를 복구하는 데 필요한 파일은 세 가지다. 첫 번째는 `~/.config/cryptolight/cryptolight.env`, 두 번째는 `data/trades.db`와 관련 WAL 파일, 세 번째는 `~/.config/systemd/user/cryptolight.service`다. 이 셋이 있으면 저장소를 새로 받아도 같은 전략 설정과 거래 기록으로 다시 올릴 수 있다.

복구 순서는 단순하다. 저장소를 원하는 경로에 clone하고, 외부 설정 파일과 SQLite 파일을 원래 위치에 복원한 뒤, 서비스 파일의 경로만 새 설치 경로에 맞게 수정하고 `systemctl --user daemon-reload && systemctl --user restart cryptolight.service`를 실행한다. 재기동 후 `journalctl`과 `/api/status`로 마지막 전략 실행 시각과 추적 종목 목록이 예상대로인지 확인하면 된다.
