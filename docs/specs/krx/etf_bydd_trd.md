# etf_bydd_trd - ETF 일별매매정보

## 명세서 원문 (KRX Open API 포털, 2026-09-28)

- Description: ETF(상장지수펀드)의 매매정보 제공 ('10년01월04일 데이터부터 제공)
- Server endpoint url: `https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd`

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
| TDD_CLSPRC | string | 종가 |
| CMPPREVDD_PRC | string | 대비 |
| FLUC_RT | string | 등락률 |
| NAV | string | 순자산가치(NAV) |
| TDD_OPNPRC | string | 시가 |
| TDD_HGPRC | string | 고가 |
| TDD_LWPRC | string | 저가 |
| ACC_TRDVOL | string | 거래량 |
| ACC_TRDVAL | string | 거래대금 |
| MKTCAP | string | 시가총액 |
| INVSTASST_NETASST_TOTAMT | string | 순자산총액 |
| LIST_SHRS | string | 상장좌수 |
| IDX_IND_NM | string | 기초지수_지수명 |
| OBJ_STKPRC_IDX | string | 기초지수_종가 |
| CMPPREVDD_IDX | string | 기초지수_대비 |
| FLUC_RT_IDX | string | 기초지수_등락률 |

### request Sample
```json
{"basDd":"__"}
```

### response Sample
```json
{"OutBlock_1":[{"BAS_DD":"__","ISU_CD":"__","ISU_NM":"__","TDD_CLSPRC":"-","CMPPREVDD_PRC":"-","FLUC_RT":"-","NAV":"-","TDD_OPNPRC":"-","TDD_HGPRC":"-","TDD_LWPRC":"-","ACC_TRDVOL":"-","ACC_TRDVAL":"-","MKTCAP":"-","INVSTASST_NETASST_TOTAMT":"-","LIST_SHRS":"-","IDX_IND_NM":"__","OBJ_STKPRC_IDX":"-","CMPPREVDD_IDX":"-","FLUC_RT_IDX":"-"},{"BAS_DD":"__","ISU_CD":"__","ISU_NM":"__","TDD_CLSPRC":"-","CMPPREVDD_PRC":"-","FLUC_RT":"-","NAV":"-","TDD_OPNPRC":"-","TDD_HGPRC":"-","TDD_LWPRC":"-","ACC_TRDVOL":"-","ACC_TRDVAL":"-","MKTCAP":"-","INVSTASST_NETASST_TOTAMT":"-","LIST_SHRS":"-","IDX_IND_NM":"__","OBJ_STKPRC_IDX":"-","CMPPREVDD_IDX":"-","FLUC_RT_IDX":"-"}]}
```

## 프로젝트 주석 (명세 아님)
- 용도: ETF 일봉, NAV·종가(괴리율 재료), 순자산총액, 기초지수. ① 유니버스의 ETF 포함(결정 5)과 ③ 레버리지 슬롯·파킹 ETF(결정 4)의 데이터 원천. DECISIONS.md 결정 12
- 상장주식수가 아니라 상장좌수(LIST_SHRS)
- 코스피·코스닥 구분 필드가 없다(ETF는 유가증권시장 상장). 시장 구분이 필요하면 종목기본정보나 분봉 종목 목록과 대조
- 레버리지·인버스 여부 필드 없음. 레버리지 ETP 식별은 별도 소스(종목명 규칙 또는 한국투자증권 종목정보파일)로 - 결정 미정
- ISU_CD는 6자리이나 영문자가 섞인 코드가 있다("0052T0", "0191W0" - 실측). 문자열로 다룬다
- NAV·기초지수값은 소수점 문자열("35115.88"). 기초지수 3필드(OBJ_STKPRC_IDX 등)는 빈 문자열인 종목이 있다(해외 지수·2010년 초기 ETF)
- **휴장일(2026-09-25)에도 1,175행이 오며 LIST_SHRS·IDX_IND_NM 외 숫자 필드가 전부 빈 문자열.** 적재 시 가격 필드가 전부 빈 행은 "데이터 없음"으로 건너뛰어야 하며, 휴장일 판정에 이 서비스를 쓰면 안 된다
- 행 수: 2010-01-04 50, 2026-09-18 1,171, 2026-09-25 1,175
