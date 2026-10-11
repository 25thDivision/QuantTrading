# stk_isu_base_info - 유가증권 종목기본정보

## 명세서 원문 (KRX Open API 포털, 2026-09-28)

- Description: 유가증권 종목기본정보 ('10년01월04일 데이터부터 제공)
- Server endpoint url: `https://data-dbg.krx.co.kr/svc/apis/sto/stk_isu_base_info`

### request - InBlock_1
| Name | Type | Description |
|---|---|---|
| basDd | string | 기준일자 |

### response - OutBlock_1
| Name | Type | Description |
|---|---|---|
| ISU_CD | string | 표준코드 |
| ISU_SRT_CD | string | 단축코드 |
| ISU_NM | string | 한글 종목명 |
| ISU_ABBRV | string | 한글 종목약명 |
| ISU_ENG_NM | string | 영문 종목명 |
| LIST_DD | string | 상장일 |
| MKT_TP_NM | string | 시장구분 |
| SECUGRP_NM | string | 증권구분 |
| SECT_TP_NM | string | 소속부 |
| KIND_STKCERT_TP_NM | string | 주식종류 |
| PARVAL | string | 액면가 |
| LIST_SHRS | string | 상장주식수 |

### request Sample
```json
{"basDd":"__"}
```

### response Sample
```json
{"OutBlock_1":[{"ISU_CD":"__","ISU_SRT_CD":"__","ISU_NM":"__","ISU_ABBRV":"__","ISU_ENG_NM":"__","LIST_DD":"__","MKT_TP_NM":"__","SECUGRP_NM":"__","SECT_TP_NM":"-","KIND_STKCERT_TP_NM":"__","PARVAL":"__","LIST_SHRS":"__"},{"ISU_CD":"__","ISU_SRT_CD":"__","ISU_NM":"__","ISU_ABBRV":"__","ISU_ENG_NM":"__","LIST_DD":"__","MKT_TP_NM":"__","SECUGRP_NM":"__","SECT_TP_NM":"-","KIND_STKCERT_TP_NM":"__","PARVAL":"__","LIST_SHRS":"__"}]}
```

## 프로젝트 주석 (명세 아님)
- 용도: 상장일(LIST_DD, 결정 5의 신규 상장 기준일), 주식종류(KIND_STKCERT_TP_NM, ③ 보통주 필터), 표준코드↔단축코드 대응. DECISIONS.md 결정 12
- 응답에 BAS_DD가 없다. 적재 시 요청한 basDd를 스냅샷 날짜로 붙여야 한다
- 적재 주기: 과거는 매월 첫 거래일 스냅샷 + 일별매매정보에 처음 등장한 종목의 당일 보강, 앞으로는 매일 (결정 12)
- ISU_CD는 12자리 표준코드(KR7005930003), ISU_SRT_CD는 6자리 단축코드(실측). 조인 키 = ISU_SRT_CD ↔ 일별매매 ISU_CD. ISU_NM은 정식명("삼성전자보통주"), ISU_ABBRV가 일별매매의 ISU_NM과 같은 약명
- SECUGRP_NM(2026-09-18): 주권 914 / 부동산투자회사 23 / 사회간접자본투융자회사 2 / 외국주권 1 / 주식예탁증권 1 / 투자회사 1. 2010-01-04: 주권 866 / 선박투자회사 43 / 투자회사 9 / 부동산투자회사 3 / 외국주권 2 / 사회간접자본투융자회사 1 / 주식예탁증서 1
- KIND_STKCERT_TP_NM(2026-09-18): 보통주 831 / 구형우선주 78 / 신형우선주 21 / 종류주권 12. 2010-01-04: 보통주 770 / 구형우선주 115 / 신형우선주 40
- SECT_TP_NM 전 종목 빈 문자열, MKT_TP_NM "KOSPI"
- 휴장일(2026-09-25)에도 942행 정상 제공(상장 스냅샷). 휴장일 판정에 쓸 수 없음
- PARVAL은 액면분할을 반영해 시점별로 다름(삼성전자 2010년 5000, 2026년 100)
