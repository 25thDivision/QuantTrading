# ksq_bydd_trd - 코스닥 일별매매정보

## 명세서 원문 (KRX Open API 포털, 2026-10-01)

- Description: 코스닥시장에 상장되어 있는 주권의 매매정보 제공 ('10년01월04일 데이터부터 제공)
- Server endpoint url: `https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd`

### request - InBlock_1
| Name | Type | Description |
|---|---|---|
| basDd | string | 기준일자 |

### response - OutBlock_1
| Name | Type | Description |
|---|---|---|
| BAS_DD | string | 기준일자 |
| ISU_CD | string | 종목코드 |
| ISU_NM | string | 종목명 |
| MKT_NM | string | 시장구분 |
| SECT_TP_NM | string | 소속부 |
| TDD_CLSPRC | string | 종가 |
| CMPPREVDD_PRC | string | 대비 |
| FLUC_RT | string | 등락률 |
| TDD_OPNPRC | string | 시가 |
| TDD_HGPRC | string | 고가 |
| TDD_LWPRC | string | 저가 |
| ACC_TRDVOL | string | 거래량 |
| ACC_TRDVAL | string | 거래대금 |
| MKTCAP | string | 시가총액 |
| LIST_SHRS | string | 상장주식수 |

### request Sample
```json
{"basDd":"__"}
```

### response Sample
```json
{"OutBlock_1":[{"BAS_DD":"__","ISU_CD":"__","ISU_NM":"__","MKT_NM":"__","SECT_TP_NM":"-","TDD_CLSPRC":"-","CMPPREVDD_PRC":"-","FLUC_RT":"-","TDD_OPNPRC":"-","TDD_HGPRC":"-","TDD_LWPRC":"-","ACC_TRDVOL":"-","ACC_TRDVAL":"-","MKTCAP":"-","LIST_SHRS":"-"},{"BAS_DD":"__","ISU_CD":"__","ISU_NM":"__","MKT_NM":"__","SECT_TP_NM":"-","TDD_CLSPRC":"-","CMPPREVDD_PRC":"-","FLUC_RT":"-","TDD_OPNPRC":"-","TDD_HGPRC":"-","TDD_LWPRC":"-","ACC_TRDVOL":"-","ACC_TRDVAL":"-","MKTCAP":"-","LIST_SHRS":"-"}]}
```

## 프로젝트 주석 (명세 아님)
- 용도: 연구용 축적만. 코스닥 거래는 금지(DECISIONS.md 결정 2). 유니버스 계산 대상이 아님
- 필드 구성은 유가증권 일별매매정보(stk_bydd_trd)와 동일. 적재 테이블을 공유하고 market 컬럼으로 구분하는 것이 자연스럽다
- 실측(2026-10-01 22:39, 기준일 2026-09-18): 1,820행. ISU_CD 6자리, 숫자 표기·결측 규칙은 코스피와 동일, MKT_NM "KOSDAQ"
- 소속부(SECT_TP_NM)에 값이 있다: 우량기업부 466 / 중견기업부 511 / 벤처기업부 339 / 기술성장기업부 255 / 관리종목(소속부없음) 128 / SPAC(소속부없음) 66 / 투자주의환기종목(소속부없음) 40 / 외국기업(소속부없음) 15. 관리종목·환기종목 여부가 이 필드에 드러난다 (코스피에는 없는 정보)
- 무체결일 87종. 시가·고가·저가·거래량·거래대금 "0", 종가는 값 있음(코스피와 동일 표기)
