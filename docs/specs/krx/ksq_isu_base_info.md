# ksq_isu_base_info - 코스닥 종목기본정보

## 명세서 원문 (KRX Open API 포털, 2026-10-01)

- Description: 코스닥 종목기본정보 ('10년01월04일 데이터부터 제공)
- Server endpoint url: `https://data-dbg.krx.co.kr/svc/apis/sto/ksq_isu_base_info`

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
- 용도: 연구용 축적만(코스닥 거래 금지). 필드 구성은 유가증권 종목기본정보(stk_isu_base_info)와 동일. 적재 테이블 공유, market 컬럼으로 구분
- 적재 주기는 유가증권과 같음(과거 월 1회 스냅샷 + 신규 등장 보강 + 앞으로 매일)
- 실측(2026-10-01 22:39, 기준일 2026-09-18): 1,820행. ISU_CD 12자리 표준코드, ISU_SRT_CD 6자리. MKT_TP_NM "KOSDAQ"
- 증권구분(SECUGRP_NM): 주권 1,800 / 외국주권 11 / 주식예탁증권 9. 주식종류(KIND_STKCERT_TP_NM): 보통주 1,817 / 신형우선주 2 / 종류주권 1
- 소속부(SECT_TP_NM) 값 분포는 일별매매정보와 동일(관리종목·SPAC·환기종목 등 표시)
- PARVAL "0"이 6종(무액면 주식). 적재 시 0을 결측으로 바꾸지 말 것
