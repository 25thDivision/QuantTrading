# ARCHITECTURE.md — 구현 지침

> Claude Code 및 구현 채팅이 참조하는 설계도. 결정의 근거와 수치는 DECISIONS.md가 원본이며, 충돌 시 DECISIONS.md가 우선한다.
> 최종 갱신: 2026-09-03

---

## 1. 시스템 구조 — D+A+F 하이브리드

**D. 배치 코어 + 실시간 위성**
- **배치 엔진**: 매일 장 마감 후 실행. 데이터 수집 → ③(및 페이퍼 전략들) 신호 계산 → 익일 주문 큐 생성 → 유니버스 갱신. systemd timer 구동. 단순·견고가 최우선
- **실시간 엔진**: 활성 시장의 거래 세션 중에만 가동 (세션 정의는 config 세션 테이블 — DECISIONS.md 결정 9). WebSocket 시세 수신 → ① 전략 처리 + **전 전략 손절 감시 대행**(③의 층 1 집행 포함). 즉시 집행이 가능한 구간은 접속매매뿐이며, 주문이 나가는 세션은 tradable=true인 KRX 접속매매(09:00~15:20)로 시작
- 두 엔진은 공통의 Portfolio Manager / Execution Layer / Risk Monitor를 공유

**A. 전략 플러그인 인터페이스**
- 모든 전략(오디션 후보 포함)은 동일 인터페이스 구현: `generate_signals(market_view) -> list[Signal]`
- 백테스트 엔진·페이퍼 시뮬·실전 엔진이 **같은 전략 코드**를 호출 (백테스트≠실전 코드 불일치 금지 — 프로젝트 핵심 요구)
- 전략은 상태를 직접 들고 주문하지 않는다. 신호만 낸다. 포지션·주문은 아래 계층 소관

**F. 포지션 상태 머신**
- 상태: `IDLE → ENTRY_PENDING → HOLDING → EXIT_PENDING → CLOSED` (+ `ERROR`)
- 부분 체결, 주문 실패, 재시작 복구를 상태 전이로 처리
- **대사(reconciliation)**: 기동 시 및 주기적으로 봇 장부 vs 계좌 실잔고 비교. 불일치 시 알림. **수동 거래 공존 규칙**: 봇이 낸 주문만 자기 것으로 추적, 사람이 수동으로 만든 포지션은 건드리지 않음

**E 진화 대비**
- 모듈 간 통신은 직접 함수 호출이 아니라 **내부 메시지 버스 인터페이스** 경유 (현 구현: Python 인메모리 큐). 훗날 Redis/Kafka로 구현체 교체 시 프로세스 분리 가능

**모듈 목록**
```
collector      시세 수집 (분봉 수집기 — 최우선 구현 대상)
strategy/      전략 플러그인들 (1a.py, 1b.py, 1bp.py, 2c.py, ...)
portfolio      자본 배분, 포지션 크기 산출(고정 리스크), 슬롯 관리(레버리지/파킹/대체)
execution      주문 전송·체결 확인·재시도·취소. 레이트 리미터 내장(한국투자증권 초당 호출 제한 대응)
risk           3층 안전장치 감시·집행 (모든 계층 위에서 독립 감시)
broker/        한국투자증권 API 어댑터 (실전/모의/스텁 전환은 설정으로)
notify         디스코드 Webhook 알림 + 봇 명령 (!status, !pnl, !halt, !resume 등)
simulator      자체 페이퍼 시뮬 (이벤트 엔진과 체결 로직 공유)
bus            메시지 버스 인터페이스 (인메모리 구현)
```

## 2. 데이터 설계

### 서버 (운영) — SQLite, WAL 모드
스키마 초안 (구현 시 구체화):
```
orders          주문 원장 (id, ts, symbol, side, qty, price, type, status, strategy_id, ...)
fills           체결 기록 (order_id, ts, qty, price, fee)
positions       현재 포지션 (symbol, qty, avg_price, strategy_id, state, stop_price)
position_events 상태 머신 전이 로그
candles_1m      분봉 (수집기 적재, 서버 보존 약 1년 후 정리)
candles_1d      일봉
universe_log    유니버스 스냅샷 (일자별 — 백테스트 생존편향 대응에도 사용)
metrics         자가 지표 (5분 주기 시스템 지표 + 트레이딩 지표)
decisions_log   층 2·3 발동, 승격/강등, 예외 발동 한 줄 로그
```
- 틱은 저장하지 않는다: 링버퍼(종목당 최근 1만 틱)로만 유지, 즉시 분봉 집계 후 flush
- 틱·호가의 별도 수집 여부는 미확정 (DECISIONS.md 11절 — Phase 0 실측 후 결정. k12 부적합 시 랩실 별도 수집기로 분리)

### 본체·랩실 (분석) — Parquet + DuckDB
- 파티셔닝: `market/interval/year/symbol.parquet` 형태 (구현 시 확정)
- **이관은 pull 방식 (결정 8)**: k12가 SQLite → Parquet 내보내기를 systemd timer로 주기 실행하여 내보내기 폴더를 최신 유지, 본체·랩실이 Tailscale 위 rsync로 당겨간다. k12로 데이터를 밀어넣는 경로는 없다 (단방향)
- 데이터 소스: pykrx(코스피 일봉·시총·거래대금, 즉시 사용 가능), FinanceDataReader(코스피+미국), 한국투자증권 API(분봉·실시간, 실전 소스와 통일)
- **일 단위 배치류 수집 확장 (결정 8)**: 투자자별 매매동향, 공매도 잔고·거래, 지수 일봉·분봉, ETF 구성정보·괴리율 등 — Phase 1 파이프라인 설계에 반영
- **생존편향 주의**: 현재 상장 종목 기준 과거 데이터는 상폐 종목이 빠져 성과가 과대평가됨. pykrx로 시점별 상장 목록 수집하여 완화, 결과 해석 시 명시
- **분봉 제약**: 한국투자증권 API 분봉은 제공 기간이 짧음 → 장기 분봉 백테스트 불가. 대응: (1) 1-A는 일봉 근사로 1차 오디션 (돌파·손절 동시 접촉일은 비관 판정), (2) 분봉 수집기를 최우선 가동해 자가 데이터셋 축적, (3) 1-B/1-B′ 본선은 축적 후

## 3. 백테스트 — 2단 구성

- **1차 스캔: vectorbt** — 파라미터 대량 탐색 (수천 조합). 비관적 가정 하드코딩. 실행 머신은 미확정 (본체 vs 랩실 — DECISIONS.md 11절, Phase 2 전까지 결정. 무료 vectorbt는 기본 단일 코어라 랩실 배정 시 멀티프로세스 샤딩 구현 전제)
- **2차 정밀 검증: 자작 이벤트 엔진** — 캔들 순차 처리, 전략 플러그인 직접 호출, 미래 정보 누수 구조적 차단. **오디션 합격 판정은 2차가 내린다**
- **체결 모델 모듈화**: `FillModel` 인터페이스에 모호성 해소 정책을 교체 가능하게:
  - `pessimistic` (기본·심사용): 모호하면 불리한 순서
  - `optimistic` (진단용): 비관/낙관 결과 차가 크면 "캔들 내부 순서 민감 전략 = 정밀 데이터 없이 신뢰 불가" 신호
  - `random`/`midpoint` (민감도 분석 보조)
- **페이퍼 시뮬 = 실시간 데이터로 도는 이벤트 엔진**: 체결 로직 공유로 개발 이중화 방지
- 비용 모델: 수수료(실계좌 요율 확인 후 반영) + 증권거래세(매도, ETF 면제) + 슬리피지 가정(오디션 설계 시 확정)
- 1차 통과 경계선 부근 후보는 2차에서 재심 (비관 가정으로 1차 성과는 항상 실제 이하이므로, 아깝게 떨어진 후보 구제 경로)

## 4. 인프라 (2026-09-03 기준)

| 항목 | 상태 |
|---|---|
| 운영 서버 | GMKtec K12 (H255), 램 16GB×1 (memtest 4패스 무오류), 하이닉스 512GB, 무선랜카드 장착 |
| OS | Ubuntu 24.04 Server, CLI-only, hostname `k12`, LVM 루트 473G, 시스템 Python 3.12.3 |
| 위치 | 집 배치 (유선 eno1 = 192.168.0.12 DHCP 예약, 무선 = 192.168.0.14, 예비 유선 포트 enp4s0). 랩실 wifi 프로파일 예비 유지 (긴급수리 시 이동 대비) |
| BIOS | Fast Boot 해제 / Auto Power On (AC 복구 자동 부팅, 실증 완료) / Quiet 전력 모드 / UMA 최소화 (가용 램 14Gi). BIOS 진입: `sudo systemctl reboot --firmware-setup` |
| 네트워크 | Tailscale 트레이딩 전용 테일넷 (k12 = 100.120.168.86, 랩실 서버 합류 확인), UFW 인바운드 tailscale0만 허용, LAN 직접 SSH 차단 확인 |
| SSH | 키 인증 전용 (비밀번호·대화형 차단, 00-hardening.conf — sshd는 first-match-wins) |
| 모니터링 | Netdata (apt, localhost:19999 바인딩, SSH 터널 접근, 수집 1초) + SQLite 자가 기록 + 디스코드 조회 봇(구현 예정) |
| 무인 복구 | AC 자동부팅 → netplan(optional:true) → Tailscale → SSH 사슬 전체 실증 완료. 완전 정지 시 가족 수동 재부팅 요청 |
| 개발 환경 | **랩실 서버** (Dell Precision 7920 Tower, Xeon Silver 4214R×2, Ubuntu 24.04, stl 계정, SSH 접속). 시스템 Python 버전(3.12)과 무관하게 프로젝트는 uv가 3.12를 조달 |
| 저장소 | GitHub 25thDivision/QuantTrading (private) |
| 잔여 | git 배포 구조 세부 (코드 배포 — 구현 단계와 병행 설계) |

**역할 분담 (결정 8 반영)**
- 랩실 서버: 개발·테스트. 코드 편집은 여기서만
- 서버(k12): 봇 실행 전용 + 개인 자동화 봇(뉴스 브리핑·논문 리뷰 — 별도 systemd 서비스·각자의 uv 프로젝트로 격리, personal.slice 자원 상한, 금지 시간대는 설정 파라미터)
- 본체(9800X3D, 기숙사): Parquet 아카이브 보관. 백테스트 대량 탐색의 실행 머신은 미확정 (본체 vs 랩실 — Phase 2 전 결정)
- 개발 흐름: 랩실에서 편집 → git push → k12 pull → `uv sync` → systemd 실행. 서버에서 직접 편집하지 않는다
- 프로세스 관리: systemd (enable + Restart=always + journald). 유닛·슬라이스 원본은 저장소 deploy/systemd/, 적용은 복사 → daemon-reload → 재시작 스크립트만 (심볼릭 링크 금지)
- 패키지 관리: uv 단독 (`uv run`/`uv sync`/`uv add`). uv.lock 커밋 필수
- LLM: v1 트레이딩 로직에 미사용. 개인 자동화 봇은 외부 API 사용

## 5. 설정 파일 구조 (초안)

```yaml
account:            # 계좌 통합 파라미터
  seed: 5_000_000
  alloc: {day: 0.3, swing: 0.7}
  kill_switch: {soft: -0.03, hard: -0.05}      # 2개월 무사고 후 -0.04/-0.06
  drawdown: {per_strategy: -0.15, account: -0.18}  # 오디션 MDD 확정 후 재설정
common:             # 시장 무관 공식·규칙
  risk_per_trade: {day: 0.01, swing: 0.015}
  fill_model: pessimistic
markets:
  kospi:            # 코스피 인스턴스 파라미터 (2026 변동성 국면 보정값)
    timezone: Asia/Seoul
    sessions:       # 세션 테이블 — 1급 구조 (결정 9). 전부 정의하되 거래 활성은 tradable로 통제
      - {name: auction_open,  span: "08:30-09:00", kind: auction,    tradable: false}
      - {name: continuous,    span: "09:00-15:20", kind: continuous, tradable: true}   # v1 유일 거래 세션
      - {name: auction_close, span: "15:20-15:30", kind: auction,    tradable: false}
      - {name: after_fixed,   span: "15:40-16:00", kind: fixed,      tradable: false}
      - {name: after_single,  span: "16:00-18:00", kind: auction,    tradable: false}
      # 12시간제(2026-09-14~) 프리·애프터마켓 세션은 세부 확인 후 추가 (DECISIONS.md 11절)
    day:  {stop: {mode: vol_linked, mult: 0.5, clamp: [-0.03, -0.06]}, max_positions: 1, price_cap: 200_000}
    swing: {stop: -0.15, positions: 7, price_cap: 160_000, leverage_slot: {max_ratio: 0.5, stop: -0.20}}
    universe: {...}
  us:               # 미국 인스턴스 — 독자 백테스트로 별도 확정 (미정)
    timezone: America/New_York   # 세션은 현지 시간대로 정의, 서머타임은 라이브러리가 처리
calendar: {...}     # 시장 캘린더 — 휴장일·단축일·변경일 (소스 미정, DECISIONS.md 11절)
parking: {whitelist: [...], enabled_for: [swing]}
personal_bot:       # 개인 자동화 봇 (결정 8·9)
  blocked: derived  # 활성 인스턴스의 거래 세션 합집합 + 전후 버퍼 (고정값 기입 금지)
  buffer_minutes: 30
```
- 모든 수치는 여기서만 관리 (하드코딩 금지). 완화 방향 변경은 1일 숙려 (DECISIONS.md 원칙 5)
- 시간 참조는 전부 세션 테이블에서 파생. 세션 시각은 거래소 현지 시간대로 정의하고 한국시간 하드코딩 금지
- personal.slice 자원 상한 수치는 미정 (DECISIONS.md 11절) — 확정 시 deploy/systemd/personal.slice에 반영

## 6. 구현 로드맵 (순서 제안)

| Phase | 내용 | 비고 |
|---|---|---|
| 세션 0 | 저장소 부트스트랩: 골격·문서 배치·설정 골격만 (기능 코드 없음) | 별도 지시 문안으로 진행 |
| 0 | **분봉 수집기** + SQLite 스키마 + systemd 서비스화 + 디스코드 알림 기초 + **한국투자증권 API 실스펙 확인** (IP 허용 목록, 토큰·세션 정책, 웹소켓 등록 한도, 소수점 거래, 거래소 지정(KRX 한정) 가능 여부, 12시간제 API 반영 — DECISIONS.md 11절 관문들) | 최우선 — 데이터 축적은 빠를수록 이득. 서버 첫 상주 서비스 |
| 1 | 데이터 파이프라인: pykrx 일봉 수집 + 일 단위 배치류 확장(결정 8), Parquet 내보내기, pull 동기화, 유니버스 계산 | ③ 백테스트 준비 완료 조건 |
| 2 | 백테스트 1차(vectorbt): ③ 2-C (+2-A/2-B), ① 1-A 일봉 근사 | 시장 필터·종목 수·손절 민감도 비교 포함. 실행 머신 결정 선행 (11절) |
| 3 | 자작 이벤트 엔진 + FillModel + 2차 검증 → **오디션 판정, 층 3 수치 재설정** | 합격 판정의 주체 |
| 4 | 자체 시뮬(페이퍼): 이벤트 엔진에 실시간 데이터 연결, ②④⑤ 페이퍼 가동 | 검증 사다리 1단 |
| 5 | 한국투자증권 모의 API 연동: broker 어댑터, 주문 파이프라인, 상태 머신, 대사 | 검증 사다리 2단 (결정 6 기준 적용) |
| 6 | 소액 실전 (③ 150만 → ① 50만) + 강제 트리거 테스트 | 검증 사다리 3단 |
| 병행 | git 배포 구조(코드), 디스코드 명령 확장, 개인 자동화 봇 | 주 흐름과 독립 |

- 각 Phase 전환은 명시 승인 원칙 적용 (완료 보고 → 석현님 승인 → 다음 Phase)

## 7. 디렉토리 구조 (승인본)

```
QuantTrading/
├── CLAUDE.md            # Claude Code용 작업 규칙
├── pyproject.toml       # 의존성 선언 (uv). 프로젝트명 QuantTrading
├── uv.lock              # 락파일 (git 포함 — 재현성의 본체)
├── .python-version      # 3.12 고정
├── .gitignore           # .env, .venv, __pycache__ 등
├── .env.example         # 키 항목 이름만 (값 없음 — 랩실·k12 각자 .env 작성용 서식)
├── config/              # 설정 (5절 구조), 시크릿은 .env 별도 (git 제외)
├── quant_trading/     # 최상위 패키지
│   ├── __init__.py
│   ├── collector/
│   ├── strategy/      # 플러그인들 + 공용 인터페이스
│   ├── portfolio/
│   ├── execution/
│   ├── risk/
│   ├── broker/        # kis_real / kis_paper / 스텁 어댑터
│   ├── backtest/      # vectorbt 스캔, 이벤트 엔진, FillModel
│   ├── simulator/
│   ├── notify/
│   └── bus/           # 메시지 버스 인터페이스 (인메모리 구현)
├── deploy/
│   └── systemd/       # 유닛·슬라이스 파일 원본 (복사식 배포 — 결정 8)
├── scripts/           # 배치 진입점, deploy_units.sh, 배포·대사 도구
├── tests/             # 스텁 어댑터 기반 자동 테스트
└── docs/              # DECISIONS.md, ARCHITECTURE.md 사본 유지
```
