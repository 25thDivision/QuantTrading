# ARCHITECTURE.md - 구현 지침

> Claude Code 및 구현 채팅이 참조하는 설계도. 결정의 근거와 수치는 DECISIONS.md가 원본이며, 충돌 시 DECISIONS.md가 우선한다.
> 최종 갱신: 2026-10-06 (2차)

---

## 1. 시스템 구조 - D+A+F 하이브리드

**D. 배치 코어 + 실시간 위성**
- **배치 엔진**: 매일 장 마감 후 실행. 데이터 수집 → ③(및 페이퍼 전략들) 신호 계산 → 익일 주문 큐 생성 → 유니버스 갱신. systemd timer 구동. 단순·견고가 최우선
- **실시간 엔진**: 활성 시장의 거래 세션 중에만 가동 (세션 정의는 config 세션 테이블 - DECISIONS.md 결정 9). WebSocket 시세 수신 → ① 전략 처리 + **전 전략 손절 감시 대행**(③의 층 1 집행 포함). 즉시 집행이 가능한 구간은 접속매매뿐이며, 주문이 나가는 세션은 tradable=true인 KRX 접속매매(09:00~15:20)로 시작
- 두 엔진은 공통의 Portfolio Manager / Execution Layer / Risk Monitor를 공유

**A. 전략 플러그인 인터페이스**
- 모든 전략(오디션 후보 포함)은 동일 인터페이스 구현: `generate_signals(market_view) -> list[Signal]`
- 백테스트 엔진·페이퍼 시뮬·실전 엔진이 **같은 전략 코드**를 호출 (백테스트≠실전 코드 불일치 금지 - 프로젝트 핵심 요구)
- 전략은 상태를 직접 들고 주문하지 않는다. 신호만 낸다. 포지션·주문은 아래 계층 소관

**F. 포지션 상태 머신**
- 상태: `IDLE → ENTRY_PENDING → HOLDING → EXIT_PENDING → CLOSED` (+ `ERROR`)
- 부분 체결, 주문 실패, 재시작 복구를 상태 전이로 처리
- **대사(reconciliation)**: 기동 시 및 주기적으로 봇 장부 vs 계좌 실잔고 비교. 불일치 시 알림. **수동 거래 공존 규칙**: 봇이 낸 주문만 자기 것으로 추적, 사람이 수동으로 만든 포지션은 건드리지 않음

**E 진화 대비**
- 모듈 간 통신은 직접 함수 호출이 아니라 **내부 메시지 버스 인터페이스** 경유 (현 구현: Python 인메모리 큐). 훗날 Redis/Kafka로 구현체 교체 시 프로세스 분리 가능

**모듈 목록**
```
collector      시세·종목 상태 수집. 분봉 = 한국투자증권 마감 후 REST 스윕 배치 (결정 11, 가동 중 2026-09-22~) /
               지정내역 = 종목정보파일 플래그 일별 스냅샷 2회 (결정 12, 지시 문안 3) / 휴장일 = 국내휴장일조회 k12 실전 키 하루 1회 (결정 12, 지시 문안 4 예정) /
               일 단위 시장 데이터 = KRX 공식 API (결정 12). 클라이언트·프로브 구현 완료(2026-09-30), 적재는 지시 문안 2
strategy/      전략 플러그인들 (1a.py, 1b.py, 1bp.py, 2c.py, ...)
portfolio      자본 배분, 포지션 크기 산출(고정 리스크), 슬롯 관리(레버리지/파킹/대체)
execution      주문 전송·체결 확인·재시도·취소. 레이트 리미터 내장(한국투자증권 초당 호출 제한 대응)
risk           3층 안전장치 감시·집행 (모든 계층 위에서 독립 감시)
broker/        한국투자증권 API 어댑터 (실전/모의/스텁 전환은 설정으로)
notify         디스코드 Webhook 알림 - 4채널 분리(collector/paper/live/alerts, 결정 11, 가동 중) + 봇 명령 (!status, !pnl, !halt, !resume 등 - 구현 예정)
simulator      자체 페이퍼 시뮬 (이벤트 엔진과 체결 로직 공유)
bus            메시지 버스 인터페이스 (인메모리 구현)
```

## 2. 데이터 설계

### 서버 (운영) - SQLite, WAL 모드. 경로 data/quant_trading.sqlite3

데이터 계보: 모든 소스(한국투자증권·KRX) → k12 SQLite → Parquet 내보내기 → 본체·랩실 pull. 쓰기는 트레이딩 파이프라인만(역방향 코드 없음).

구현 완료 (2026-09 실물 스키마):
```
candles_1m     분봉. PK (symbol, ts). 컬럼: trade_date, session(세션 라벨),
               open/high/low/close/volume(원본가·원본 거래량), amount_cum(당일 누적
               거래대금 원본 - 분 단위 거래대금은 읽기 시점에 차분), source(수집 API
               TR ID: FHKST03010200 스윕 / FHKST03010230 소급), collected_at
collector_log  수집 장부. PK (trade_date, symbol, kind) WITHOUT ROWID. kind =
               intraday_1m / symbol_source. status = ok/partial/no_trade/error, reason,
               rows, rows_traded(volume>0 행수 - 무거래 판정 근거), pages, first_ts/
               last_ts(구멍 감지), started_at/finished_at, run_id(집계·알림 단위)
```
- 완전성 판정·장부 보호·재시도·소급 규칙은 DECISIONS.md 결정 11(견고화 절)이 원본

KRX 일 단위 데이터 (결정 12, 구성 확정 2026-10-06 - 컬럼명은 지시 문안 2에서 최종 확정. 빈 문자열만 NULL, "0"은 값, 정수·실수 타입 변환, 원본가 불변):
```
daily_stock     주권 일봉, 코스피·코스닥 공유. PK (market, symbol, trade_date). market은 호출 서비스에서(kospi/kosdaq),
                symbol 6자리 TEXT. 시가/고가/저가/종가(정규시장), 거래량/거래대금(시간외·애프터마켓 포함 전체),
                시가총액, 상장주식수, 대비, 등락률, 종목명, 소속부, fetched_at. 어림 1,140만 행
daily_etf       ETF 일봉. PK (symbol, trade_date). 주권 필드 + NAV·순자산총액·상장좌수·기초지수명·기초지수 종가/대비/등락률.
                휴장일 응답(가격 필드 전부 빈 문자열)은 적재하지 않음
daily_index     코스피 계열 지수 일봉. PK (trade_date, idx_class, idx_name). 지수 마스터 없음(목록 가변, 2010년 41건·2026년 54건)
issue_info      종목기본정보 스냅샷, 코스피·코스닥 공유. PK (market, symbol, as_of). as_of = 요청 basDd(응답에 날짜 없음).
                표준코드·정식명·약명·영문명·상장일·증권구분·소속부·주식종류·액면가·상장주식수
calendar_krx    KRX 거래일 캘린더. PK date. 과거는 코스피 일별매매 응답 행 수 0 = 휴장일, 미래는 소스 확정 후
krx_call_log    KRX 호출 장부. PK (called_at, service, bas_dd). http_status·rows·duration·outcome·error_text.
                일일 예산 집계와 과거 적재 재개의 근거. collector_log(분봉 장부)와 분리
```
한국투자증권 일 단위 (결정 12, 2026-10-06):
```
symbol_status_daily  종목정보파일 지정내역 플래그 스냅샷. PK (snapshot_date, snapshot_kind, symbol). snapshot_kind pre_open(08:50) / post_close(20:30).
                     group·name·거래정지·정리매매·관리종목·시장경고코드·경고위험예고·단기과열·공매도과열·이상급등·불성실공시·저유동성·우선주구분·상장주식수.
                     유니버스는 pre_open 판만 읽는다. calendar_krx 미래분은 국내휴장일조회 응답(opnd_yn)으로 채운다
```

유니버스 모듈 산출물 (Phase 1-4에서 확정):
```
features_daily  종목·날짜별 지표 (변동폭 3종, 거래대금 20일 평균·중앙값, 시총, 상장 경과일 등)
universe_log    날짜 × 전략 슬롯 × 종목 + 사용 설정 해시
```
분봉(candles_1m)과는 symbol(6자리)과 trade_date로 조인한다. 일 단위 지표·③ 백테스트는 KRX 테이블, 장중 판단·①·층 1·체결 시뮬은 분봉, 겹치는 기간은 품질 대조에 쓴다.

스키마 초안 (구현 시 구체화 - candles_1m·collector_log는 구현 완료로 위 블록 참조):
```
orders          주문 원장 (id, ts, symbol, side, qty, price, type, status, strategy_id, ...)
fills           체결 기록 (order_id, ts, qty, price, fee)
positions       현재 포지션 (symbol, qty, avg_price, strategy_id, state, stop_price)
position_events 상태 머신 전이 로그
candles_1m      (구현 완료 - 위 블록 참조. 서버 보존 약 1년 후 정리 정책은 미구현)
candles_1d      일봉 (원본가)
collector_log   (구현 완료 - 위 블록 참조)
corporate_actions 기업행위 조정 계수 (분할·병합·배당락 - 세부는 Phase 1)
universe_log    유니버스 스냅샷 (일자별 - 백테스트 생존편향 대응에도 사용)
metrics         자가 지표 (5분 주기 시스템 지표 + 트레이딩 지표)
decisions_log   층 2·3 발동, 승격/강등, 예외 발동 한 줄 로그
```
- **분봉 수집 = 마감 후 REST 스윕 (결정 11)**: 매일 20:30(파라미터) 당일분봉조회(FHKST03010200, 30건/회, 종목당 ~14회)로 코스피 주권 전 종목(보통주+우선주) + ETF 완전 수집. 종목 소스는 한국투자증권 종목정보파일(kospi_code.mst, 캐시 폴백). 실전 키 유량 18건/초·설정 15건/초, 전 종목 소요 실측 222분 55초(호출당 약 0.46초 순차 지연 병목 - 추정; TimeoutStartSec 6h). 장부 보호·시각 안전장치·소급(--backfill) 규칙은 DECISIONS.md 결정 11. 일별분봉조회(FHKST03010230, 120건/회, 소급 약 1년)는 결손 보충 전용 - 15:20~15:29 결락 실측으로 일상 수집 배제
- 장중 틱은 저장하지 않는다: 실시간 엔진(훗날)이 링버퍼(종목당 최근 1만 틱)로만 유지, 판단 후 소멸. 틱·호가의 별도 수집 여부는 미확정 (DECISIONS.md 11절)

### 본체·랩실 (분석) - Parquet + DuckDB
- 파티셔닝: `market/interval/year/symbol.parquet` 형태 (구현 시 확정)
- **이관은 pull 방식 (결정 8)**: k12가 SQLite → Parquet 내보내기를 systemd timer로 주기 실행하여 내보내기 폴더를 최신 유지, 본체·랩실이 Tailscale 위 rsync로 당겨간다. k12로 데이터를 밀어넣는 경로는 없다 (단방향)
- 데이터 소스 (결정 12로 확정): 분봉 = 한국투자증권 API / 일 단위 시장 데이터 = KRX 공식 Open API / KRX 미제공분(지정내역·휴장일·기업행위·투자자별·공매도) = 한국투자증권 API·타 소스. pykrx·FinanceDataReader 배제(IP 차단 위험). 미국 데이터 소스는 미국 인스턴스 설계 시
- **일 단위 배치류 수집 확장 (결정 8)**: 투자자별 매매동향, 공매도 잔고·거래, 지수 일봉·분봉, ETF 구성정보·괴리율 등 - Phase 1 파이프라인 설계에 반영
- **생존편향 대응**: KRX 일별매매 응답이 그 날짜의 상장 종목(이후 상장폐지 포함)을 그대로 주므로 시점별 유니버스를 그대로 만들 수 있다 (결정 12). 결과 해석 시 명시
- **분봉 제약**: 한국투자증권 API 분봉은 제공 기간이 짧음 → 장기 분봉 백테스트 불가. 대응: (1) 1-A는 일봉 근사로 1차 오디션 (돌파·손절 동시 접촉일은 비관 판정), (2) 분봉 수집기를 최우선 가동해 자가 데이터셋 축적, (3) 1-B/1-B′ 본선은 축적 후

## 3. 백테스트 - 2단 구성

- **1차 스캔: vectorbt** - 파라미터 대량 탐색 (수천 조합). 비관적 가정 하드코딩. 실행 머신은 미확정 (본체 vs 랩실 - DECISIONS.md 11절, Phase 2 전까지 결정. 무료 vectorbt는 기본 단일 코어라 랩실 배정 시 멀티프로세스 샤딩 구현 전제)
- **2차 정밀 검증: 자작 이벤트 엔진** - 캔들 순차 처리, 전략 플러그인 직접 호출, 미래 정보 누수 구조적 차단. **오디션 합격 판정은 2차가 내린다**
- **체결 모델 모듈화**: `FillModel` 인터페이스에 모호성 해소 정책을 교체 가능하게:
  - `pessimistic` (기본·심사용): 모호하면 불리한 순서
  - `optimistic` (진단용): 비관/낙관 결과 차가 크면 "캔들 내부 순서 민감 전략 = 정밀 데이터 없이 신뢰 불가" 신호
  - `random`/`midpoint` (민감도 분석 보조)
- **페이퍼 시뮬 = 실시간 데이터로 도는 이벤트 엔진**: 체결 로직 공유로 개발 이중화 방지
- 비용 모델: 수수료 실측 반영(보통주 0.0140527% / ETF·ETN 0.0146527% - 결정 11) + 증권거래세(매도, ETF 면제. 현행 요율은 오디션 설계 시 확인) + 슬리피지 가정(오디션 설계 시 확정)
- 1차 통과 경계선 부근 후보는 2차에서 재심 (비관 가정으로 1차 성과는 항상 실제 이하이므로, 아깝게 떨어진 후보 구제 경로)

## 4. 인프라 (2026-09-22 기준)

| 항목 | 상태 |
|---|---|
| 운영 서버 | GMKtec K12 (H255), 램 16GB×1 (memtest 4패스 무오류), 하이닉스 512GB, 무선랜카드 장착 |
| OS | Ubuntu 24.04 Server, CLI-only, hostname `k12`, LVM 루트 473G, 시스템 Python 3.12.3, 타임존 Asia/Seoul (2026-09-18 UTC에서 변경) |
| 위치 | 집 배치 (유선 eno1 = 192.168.0.12 DHCP 예약, 무선 = 192.168.0.14, 예비 유선 포트 enp4s0). 랩실 wifi 프로파일 예비 유지 (긴급수리 시 이동 대비) |
| BIOS | Fast Boot 해제 / Auto Power On (AC 복구 자동 부팅, 실증 완료) / Quiet 전력 모드 / UMA 최소화 (가용 램 14Gi). BIOS 진입: `sudo systemctl reboot --firmware-setup` |
| 네트워크 | Tailscale 트레이딩 전용 테일넷 (k12 = 100.120.168.86, 랩실 서버 합류 확인), UFW 인바운드 tailscale0만 허용, LAN 직접 SSH 차단 확인 |
| SSH | 키 인증 전용 (비밀번호·대화형 차단, 00-hardening.conf - sshd는 first-match-wins) |
| 모니터링 | Netdata (apt, localhost:19999 바인딩, SSH 터널 접근, 수집 1초) + collector_log 장부 + 디스코드 4채널 알림(가동 중) + 디스코드 조회 봇(구현 예정) |
| 무인 복구 | AC 자동부팅 → netplan(optional:true) → Tailscale → SSH 사슬 전체 실증 완료. 완전 정지 시 가족 수동 재부팅 요청 |
| 개발 환경 | **랩실 서버** (Dell Precision 7920 Tower, Xeon Silver 4214R×2, Ubuntu 24.04, stl 계정, SSH 접속). 시스템 Python 버전과 무관하게 프로젝트는 uv가 3.12를 조달 |
| 저장소 | GitHub 25thDivision/QuantTrading (private), 기본 브랜치 master. k12 체크아웃: /home/seokhyeon/QuantTrading (2026-09-18 배포) |
| 상주 서비스 | **collector.timer 20:30** (2026-09-22 활성화. 유닛 파일은 매일 기동으로 변경 완료 2026-09-30, k12 반영은 push 후 deploy_units.sh - 그 전까지 k12는 월~금) + collector.service (TimeoutStartSec=6h - 실측 217~222분 기반, Restart=on-failure, RestartSec=5min). 휴장일·주말 실행은 최근 거래일 재시도로 무해. 지시 문안 3에서 추가: krx-daily.timer(08:15, 상태 주도 적재 - 과거 적재도 같은 유닛이 일일 예산 안에서 이어감), symbol-status-preopen.timer(08:50 종목정보파일 장 전 판 스냅샷). 휴장일 수집은 지시 문안 4 |
| 배포 | 코드: 랩실 push → k12 pull → uv sync. 유닛: scripts/deploy_units.sh (복사 → daemon-reload, 결정 8). 잔여 없음 |

**역할 분담 (결정 8 반영)**
- 랩실 서버: 개발·테스트. 코드 편집은 여기서만. pull 받은 원천 데이터는 stl 홈 아래(공용 경로 금지)
- 서버(k12): 봇 실행 전용 + 개인 자동화 봇(뉴스 브리핑·논문 리뷰 - 별도 systemd 서비스·각자의 uv 프로젝트로 격리, personal.slice 자원 상한, 금지 시간대는 설정 파라미터)
- 본체(9800X3D, 기숙사): Parquet 아카이브 보관. 백테스트 대량 탐색의 실행 머신은 미확정 (본체 vs 랩실 - Phase 2 전 결정)
- 개발 흐름: 랩실에서 편집 → git push → k12 pull → `uv sync` → systemd 실행. 서버에서 직접 편집하지 않는다
- 프로세스 관리: systemd (enable + Restart 정책은 유닛별 + journald). 유닛·슬라이스 원본은 저장소 deploy/systemd/, 적용은 scripts/deploy_units.sh(전 유닛 복사 → daemon-reload; 재시작은 사람이 명시적으로)만 (심볼릭 링크 금지)
- 패키지 관리: uv 단독 (`uv run`/`uv sync`/`uv add`). uv.lock 커밋 필수
- LLM: v1 트레이딩 로직에 미사용. 개인 자동화 봇은 외부 API 사용

## 5. 설정 파일 구조

구현 완료 부분 (config/config.yaml - 키 이름은 2026-09-22 구현 기준, 값은 예시):
```yaml
collector:
  symbol_source: {file: kospi_code.mst, groups: [ST, EF], common_only: false}   # 우선주 포함. ST = KRX 주권과 코드 일치(2026-10-06 대조)
  symbol_status: {pre_open_time: "08:50", post_close: with_sweep}            # 지정내역 플래그 스냅샷 2회 (결정 12, 지시 문안 3)
  backfill_api: FHKST03010230
  max_consecutive_date_mismatch: 5      # 연속 불일치 시 "수집 창 닫힘" 중단
  transient_codes: [EGW00316]           # retries·backoff_sec 동반 (2회, 2초)
collector:
  rate_per_sec: {real: 15, paper: 1}    # 실전 한도 18건/초 대비 여유 (실제 config 위치는 collector 아래 - 2026-10-06 정정)
broker:
  lock: {dir: data/locks, wait_log_sec: 60}   # 구현 완료 2026-09-30. env별 파일 잠금, 대기 기본, --no-wait 로 즉시 종료.
                                              # 재시도 주기 = 로그 주기(60초). 5초/60초 분리는 지시 문안 2
alerts:                                 # 구현 완료 2026-09-30 (config 최상위)
  protected_ratio: 0.30                 # 보호됨 비율 사이렌 기준 (어림값)
  protected_count: 20                   # 보호됨 건수 사이렌 기준 (둘 다 충족 시 발송)
krx:                                    # 결정 12. 클라이언트·프로브 구현 완료 2026-09-30, 적재 관련 키는 지시 문안 2에서 확정
  base_url: https://data-dbg.krx.co.kr/svc/apis
  services:                             # 키의 첫 토큰(stock/etf/index/issue)이 서비스 종류 - 프로브 출력 규약
    stock_kospi:  sto/stk_bydd_trd
    stock_kosdaq: sto/ksq_bydd_trd
    etf:          etp/etf_bydd_trd
    index_kospi:  idx/kospi_dd_trd
    issue_kospi:  sto/stk_isu_base_info
    issue_kosdaq: sto/ksq_isu_base_info
  rate_per_sec: 1
  timeout_sec: 30
  retries: 2
  retry_backoff_sec: 2.0
  daily_budget: 7000                    # 인증키당 한도 10,000 대비 여유 (집계·차단은 지시 문안 2)
  history_start: "2010-01-04"           # 따옴표 필수 - YAML 날짜 객체 방지
  issue_info: {history: monthly_first_trading_day, on_new_symbol: true, forward: daily}   # 지시 문안 2
  daily_run_at: "08:15"                 # 전일분 갱신(08:00) 이후 상태 주도 적재, 지시 문안 3
  history_order: desc                   # 과거 적재 순서(최근 → 과거). 지시 문안 3
  empty_finalize_after_days: 7          # 빈 응답 날짜를 휴장일로 확정하는 경과일(그 전엔 pending 재시도)
kis:                                    # 한국투자증권 일 단위 (결정 12). 지시 문안 3은 프로브만, 수집은 문안 4
  holiday: {run_once_per_day: true}     # 국내휴장일조회 1일 1회 권고
notify:
  discord: {webhooks: ...}              # 값은 .env (DISCORD_WEBHOOK_COLLECTOR/_PAPER/_LIVE/_ALERTS)
```

초안 부분 (트레이딩 - 구현 시 구체화):
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
    sessions:       # 세션 테이블 - 1급 구조 (결정 9). 전부 정의하되 거래 활성은 tradable로 통제. 2026-09-14 제도 개편 반영
      - {name: auction_open,  span: "08:30-09:00", kind: auction,    tradable: false}
      - {name: continuous,    span: "09:00-15:20", kind: continuous, tradable: true}   # v1 유일 거래 세션
      - {name: auction_close, span: "15:20-15:30", kind: auction,    tradable: false}
      - {name: after_fixed,   span: "15:40-16:00", kind: fixed,      tradable: false}  # 존치 여부 확인 필요 (DECISIONS.md 11절)
      - {name: aftermarket,   span: "16:00-20:00", kind: continuous, tradable: false}  # KRX 애프터마켓 (2026-09-14~, 시간외단일가 대체). 수집 대상
      # KRX 프리마켓은 추후 도입 보도 - 시행 확인 후 추가
    day:                       # 유니버스 정의는 전략 블록별 (결정 12). 오디션 후보는 슬롯의 유니버스 설정을 공유
      universe:
        share_kind: ["보통주"]             # KRX 주식종류 값 그대로. 우선주·종류주권 제외 (결정 12)
        security_groups: ["주권"]          # KRX 증권구분 값 그대로. 실전 기본값, 연구용은 자유 (결정 12)
        volatility: {measure: hl_over_prev_close, window: 20, min_pct: 0.025}   # 대안 hl_over_open, atr_over_prev_close
        amount:     {agg: mean, window: 20, min_krw: 10_000_000_000}          # agg 대안 median - 적재 후 실측으로 결정
        mktcap_min: 500_000_000_000
        include_etf: true
        include_leveraged: null            # 석현님 확인 후 확정 (DECISIONS.md 11절)
      stop: {mode: vol_linked, measure: atr_over_prev_close, mult: 0.5, clamp: [-0.03, -0.06]}   # measure는 오디션 비교 대상
      max_positions: 1
      price_cap: 200_000
    swing:
      universe: {share_kind: ["보통주"], security_groups: ["주권"], amount: {agg: mean, window: 20, min_krw: 1_000_000_000}, mktcap_min: 300_000_000_000}
      market_filter: {index_class: "KOSPI", index_name: "코스피 200"}   # KRX 응답 문자열 그대로. 기준선·판정 시점은 ③ 전략 설계 시 (결정 12)
      stop: -0.15
      positions: 7
      price_cap: 160_000
      leverage_slot: {max_ratio: 0.5, stop: -0.20}
  us:               # 미국 인스턴스 - 독자 백테스트로 별도 확정 (미정)
    timezone: America/New_York   # 세션은 현지 시간대로 정의, 서머타임은 라이브러리가 처리
calendar: {...}     # 시장 캘린더 - 휴장일·단축일·변경일 (소스 미정, DECISIONS.md 11절)
parking: {whitelist: [...], enabled_for: [swing]}
personal_bot:       # 개인 자동화 봇 (결정 8·9)
  blocked: derived  # 활성 인스턴스의 거래 세션 합집합 + 전후 버퍼 (고정값 기입 금지)
  buffer_minutes: 30
```
- 모든 수치는 여기서만 관리 (하드코딩 금지). 완화 방향 변경은 1일 숙려 (DECISIONS.md 원칙 5)
- 시간 참조는 전부 세션 테이블에서 파생. 세션 시각은 거래소 현지 시간대로 정의하고 한국시간 하드코딩 금지
- personal.slice 자원 상한 수치는 미정 (DECISIONS.md 11절) - 확정 시 deploy/systemd/personal.slice에 반영

## 6. 구현 로드맵 (순서 제안)

| Phase | 내용 | 비고 |
|---|---|---|
| 세션 0 | 저장소 부트스트랩: 골격·문서 배치·설정 골격만 (기능 코드 없음) | 별도 지시 문안으로 진행 |
| 0-A | 저장소 구조 반영(결정 10) + API 실스펙 실측·문서 확인 | **완료 (2026-09-14)** - 실측 결과는 DECISIONS.md 결정 9·11과 11절에 반영 |
| 0-B | **분봉 스윕 수집기**(결정 11) + SQLite 스키마 + systemd 유닛·타이머 + 디스코드 알림 기초 + 견고화(수정 3·4) | **완료 (2026-09-22)** - 테스트 44건, 검증 스윕 통과(KRX 공식 대조), collector.timer 가동. 이월 항목(M-3 실험, 장부 정리) 2026-09-30 종결 |
| 1 | 데이터 파이프라인 (결정 12). 범위 (A): ③ 백테스트·유니버스 필수분 우선 | **진행 중 (2026-09-28 착수)**. 1-1 KRX 클라이언트 + 프로브 + 기존 수집기 보강(보호됨 집계·잠금·소급 대상 집합·타이머 매일): **완료 2026-09-30** (커밋 7건, 테스트 108건, 프로브 실행 2026-10-01) → 1-2 스키마·config 확정: **완료 2026-10-06** (결정 12) → 1-3 KRX 일별 배치·과거 적재(일일 예산) + 종목정보파일 플래그 스냅샷 + 예탁원정보·휴장일 프로브: 지시 문안 3 / 휴장일 수집기: 지시 문안 4 → 1-4 Parquet 내보내기 timer + pull 스크립트 + 유니버스 모듈(features_daily·universe_log) → 1-5 검증(KRX 일봉 vs 분봉 집계 대조, 유니버스 손검증, 적재 장부 구멍 없음, 증권구분별 ③ 필터 통과 수). 병행 완료: 한국투자증권 카탈로그 조사 + 증권구분 코드 대조 (2026-10-06 보고, 결정 12 반영) |
| 1-후반 | 일 단위 배치류 확장: 투자자별 매매동향, 공매도, 지수 분봉, ETF 구성정보·괴리율, 기업행위(corporate_actions) 수집 자동화 | 소스 확정 후. 1 본편과 분리 |
| 2 | 백테스트 1차(vectorbt): ③ 2-C (+2-A/2-B), ① 1-A 일봉 근사 | 시장 필터·종목 수·손절 민감도 비교 포함. 실행 머신 결정 선행 (11절) |
| 3 | 자작 이벤트 엔진 + FillModel + 2차 검증 → **오디션 판정, 층 3 수치 재설정** | 합격 판정의 주체 |
| 4 | 자체 시뮬(페이퍼): 이벤트 엔진에 실시간 데이터 연결, ②④⑤ 페이퍼 가동 | 검증 사다리 1단 |
| 5 | 한국투자증권 모의 API 연동: broker 어댑터, 주문 파이프라인, 상태 머신, 대사 | 검증 사다리 2단 (결정 6 기준 적용) |
| 6 | 소액 실전 (③ 150만 → ① 50만) + 강제 트리거 테스트 | 검증 사다리 3단 |
| 병행 | 디스코드 명령 확장, 개인 자동화 봇, 수집 성능 개선(대기열), 분봉 서버 보존 정책(Parquet 내보내기 이후) | 주 흐름과 독립 |

- 각 Phase 전환은 명시 승인 원칙 적용 (완료 보고 → 석현님 승인 → 다음 Phase)

## 7. 디렉토리 구조 (2026-09-22 실물 기준)

```
QuantTrading/
├── CLAUDE.md            # Claude Code용 작업 규칙
├── pyproject.toml       # 의존성 선언 (uv). 프로젝트명 QuantTrading
├── uv.lock              # 락파일 (git 포함 - 재현성의 본체)
├── .python-version      # 3.12 고정
├── .gitignore           # .env, .venv, __pycache__ 등
├── .env.example         # 키 항목 이름만 (값 없음 - 랩실·k12 각자 .env 작성용 서식)
├── config/              # 설정 (5절 구조), 시크릿은 .env 별도 (git 제외)
├── quant_trading/     # 최상위 패키지 - 자체 코드 본체 (결정 10, editable 설치)
│   ├── __init__.py    # 각 하위 모듈에도 __init__.py
│   ├── collector/     # 한국투자증권 분봉 스윕 + KRX 클라이언트(krx_client.py)·프로브(krx_probe.py). KRX 적재는 지시 문안 2
│   ├── strategy/      # 플러그인들 + 공용 인터페이스
│   ├── portfolio/
│   ├── execution/
│   ├── risk/
│   ├── broker/        # kis_real / kis_paper / 스텁 어댑터, ratelimit.py, lock.py(env별 파일 잠금)
│   ├── backtest/      # vectorbt 스캔, 이벤트 엔진, FillModel
│   ├── simulator/
│   ├── notify/
│   └── bus/           # 메시지 버스 인터페이스 (인메모리 구현)
├── deploy/
│   └── systemd/       # 유닛·슬라이스 파일 원본 (복사식 배포 - 결정 8)
├── scripts/           # sweep_candles.py(스윕·소급 진입점, --no-wait), deploy_units.sh(유닛 배포), sweep_krx.py(KRX 진입점, --probe 구현 완료·--load 적재는 지시 문안 3),
│                      # sweep_kis.py(한국투자증권 일 단위 진입점 - 지시 문안 3에서 프로브 모드, 문안 4에서 휴장일 수집), snapshot_symbols.py(종목정보파일 스냅샷 - 지시 문안 3)
├── tests/             # 스텁·픽스처 기반 자동 테스트 (2026-09-30 기준 108건), fixtures/krx/(명세서 기준으로 교체 예정)
├── data/              # SQLite·Parquet 내보내기 (git 제외)
└── docs/              # DECISIONS.md, ARCHITECTURE.md 사본 유지. specs/<공급자>/ = 외부 명세 원문 + 실측 주석(정본 아님): specs/krx/ 7파일, specs/kis/ README + 13파일(2026-10-06)
```
