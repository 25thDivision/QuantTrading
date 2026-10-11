# 한국투자증권 오픈API 명세서 보관 (docs/specs/kis/)

> 외부 사실의 보관 폴더. 프로젝트의 결정은 DECISIONS.md가 정본이며, 이 폴더는 한국투자증권이 제공한 공식 문서를 옮겨 적은 것이다.
> 폴더명 `kis`는 한국투자증권이 쓰는 약칭(KIS Developers)이며 코드·경로·환경변수의 식별자로만 쓴다. 문장에서는 한국투자증권으로 쓴다 (CLAUDE.md A1).
> 파일 하나 = API 하나, 파일명 = URL의 마지막 경로(ksdinfo 계열은 `ksdinfo-` 접두). 각 파일의 "명세서 원문" 절은 공식 Excel 시트를 그대로 옮겼고, "프로젝트 주석" 절은 우리가 붙인 메모다. 긴 응답 예시는 60줄에서 잘랐다.

## 출처
- 공식 문서: 한국투자증권 API 포털(apiportal.koreainvestment.com) "전체 API 문서 (Excel) 다운로드". 파일 `한국투자증권_오픈API_전체문서_20261006_030009.xlsx` (2026-10-06 03:00 판, 339시트 = API 목록 1 + API별 338). 원본 Excel은 바이너리라 저장소에 두지 않는다
- 공식 샘플 코드: github.com/koreainvestment/open-trading-api (2026-10-06 조사 시 커밋 277ec0eb). 종목정보파일 헤더·그룹 코드는 이 저장소의 stocks_info/ 기준
- 포털 개요 페이지(2026-10-06 열람): 도메인·TLS·종목정보파일 갱신 시각

## 변환 범위 (339개 중 13개)
현재 사용 중이거나 Phase 1에서 쓸 API만 옮겼다. 나머지는 필요할 때 같은 방식으로 추가한다.
| 파일 | API 명 | API ID | 실전 TR_ID | 모의 |
|---|---|---|---|---|
| tokenP.md | 접근토큰발급(P) | 인증-001 | - | 지원 |
| revokeP.md | 접근토큰폐기(P) | 인증-002 | - | 지원 |
| Approval.md | 실시간 (웹소켓) 접속키 발급 | 실시간-000 | - | 지원 |
| inquire-time-itemchartprice.md | 주식당일분봉조회 | v1_국내주식-022 | FHKST03010200 | 지원 |
| inquire-time-dailychartprice.md | 주식일별분봉조회 | 국내주식-213 | FHKST03010230 | 미지원 |
| inquire-price.md | 주식현재가 시세 | v1_국내주식-008 | FHKST01010100 | 지원 |
| chk-holiday.md | 국내휴장일조회 | 국내주식-040 | CTCA0903R | 미지원 |
| ksdinfo-rev-split.md | 예탁원정보(액면교체일정) | 국내주식-148 | HHKDB669105C0 | 미지원 |
| ksdinfo-bonus-issue.md | 예탁원정보(무상증자일정) | 국내주식-144 | HHKDB669101C0 | 미지원 |
| ksdinfo-merger-split.md | 예탁원정보(합병/분할일정) | 국내주식-147 | HHKDB669104C0 | 미지원 |
| ksdinfo-dividend.md | 예탁원정보(배당일정) | 국내주식-145 | HHKDB669102C0 | 미지원 |
| investor-trade-by-stock-daily.md | 종목별 투자자매매동향(일별) | (ID 없음) | FHPTJ04160001 | 미지원 |
| daily-short-sale.md | 국내주식 공매도 일별추이 | 국내주식-134 | FHPST04830000 | 미지원 |

모의 지원 여부는 Excel의 API 목록 시트 "모의 TR_ID" 열 기준(공식). 단 주식일별분봉조회는 문서상 모의 미지원인데 2026-09-28 모의 키로 실행한 소급(FHKST03010230)이 정상 동작했다(2026-09-18·09-21 partial 919·2,040건 기록). 문서와 실제가 다른 사례이므로 "문서상 미지원, 실측 동작"으로 기록하고 모의 환경의 동작을 보장된 것으로 취급하지 않는다.

## 공통 사항 (공식)
- 실전 REST `https://openapi.koreainvestment.com:9443`, 모의 REST `https://openapivts.koreainvestment.com:29443`. 웹소켓 실전 `ws://ops.koreainvestment.com:21000`, 모의 `:31000`. TLS 1.2·1.3만 허용(2025-12-12 이후 1.0·1.1 차단)
- 인증: appkey·appsecret으로 접근토큰 발급. 접근토큰 유효기간 24시간(1일 1회 발급 원칙), 갱신발급주기 6시간(6시간 이내는 기존 토큰 응답) - tokenP 시트 개요. 2026-09-28 두 머신 실측과 일치(결정 8)
- 요청 헤더는 전 API 공통 구조(content-type, authorization, appkey, appsecret, tr_id, custtype 등). 각 파일의 Request Header 표 참조
- 호출 한도(실측, 결정 11): 실전 키 초당 18건(공지·실측), 모의 키 초당 1건. 한도는 앱키 단위 합산(결정 8). 초과 시 EGW00201, 일시 오류 EGW00316

## 종목정보 파일 (공식 + 샘플 저장소 헤더)
- 포털 개요: "주문 및 시세 조회가 가능한 종목정보 마스터파일을 제공. 당사에서 공통 관리하며 매일 업데이트". **업데이트 시각: 06:00, 06:55, 07:35, 07:55, 08:45, 09:46, 10:55, 17:10, 17:30, 17:55, 18:10, 18:30, 18:55** (하루 13회). 개장 전 마지막 판은 08:45, 장 후 마지막 판은 18:55
- 코스피 파일: `https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip` (무자격증명). 저장소 `quant_trading/collector/symbols.py`가 파싱
- 증권그룹구분코드(샘플 저장소 헤더 종목마스터정보(코스피).h): ST 주권 / MF 증권투자회사 / RT 부동산투자회사 / SC 선박투자회사 / IF 사회간접자본투융자회사 / DR 주식예탁증서 / EW ELW / EF ETF / SW 신주인수권증권 / SR 신주인수권증서 / BC 수익증권 / FE 해외ETF / FS 외국주권. 헤더에 없으나 파일에 있는 값: EN(ETN, etp_prod_cls_code 3으로 확인), PF(2건, 뜻 미확인)
- 2026-10-06 대조(조사 보고): ST 914 = KRX 주권 914, 코드 단위 완전 일치. RT·IF·FS·DR·MF는 ST 밖. 우선주구분 prst_cls_code 0 보통주 / 1 구형우선주 / 2 신형우선주 / 9 종류주권(헤더 미기재, KRX 대조로 확인)
- 지정내역 플래그(헤더): trht_yn 거래정지 / sltr_yn 정리매매 / mang_issu_yn 관리종목 / mrkt_alrm_cls_code 시장경고 00 해당없음·01 투자주의·02 투자경고·03 투자위험 / mrkt_alrm_risk_adnt_yn 경고위험예고 / short_over_cls_code 단기과열 0·1 지정예고·2 지정·3 지정연장 / ssts_hot_yn 공매도과열 / stange_runup_yn 이상급등 / insn_pbnt_yn 불성실공시 / low_current_yn 저유동성. 현재 상태만 있고 이력 없음 → 결정 35로 일별 스냅샷 저장(08:50 장 전 판, 20:30 장 후 판)

## 미확인 (실호출로 확정할 것)
- 국내휴장일조회의 미래 조회 범위, 연속조회 방식(BASS_DT에 ctx_area_nk 재투입 추정), 응답 output이 object인지 배열인지(예시는 배열)
- 예탁원정보 4종의 제공 기간(이력 시작 연도) - 결정 37 실측 대상
- 종목별 투자자매매동향·공매도 일별추이의 1회 행 수·기간 폭
- 주식현재가 시세의 지정 관련 코드 값이 종목정보파일 헤더와 같은 체계인지

## 변경 이력
- 2026-10-06: 최초 작성 (13 API). 2026-10-06 Excel 판 기준
