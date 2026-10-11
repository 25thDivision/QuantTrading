# stk_bydd_trd - 유가증권 일별매매정보

## 명세서 원문 (KRX Open API 포털, 2026-09-28)

- Description: 유가증권시장에 상장되어 있는 주권의 매매정보 제공 ('10년01월04일 데이터부터 제공)
- Server endpoint url: `https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd`

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
- 용도: 일봉·거래량·거래대금·시가총액·상장주식수, 시점별 상장 목록(생존편향 대응), 과거 캘린더 생성(빈 응답 = 휴장일). DECISIONS.md 결정 12
- 시가·고가·저가·종가는 정규시장 기준, 거래량·거래대금은 시간외·애프터마켓 포함 전체 (README 데이터 정의)
- ISU_CD는 6자리 단축코드(실측 2026-10-01, 942/942). 분봉 DB의 symbol과 같은 체계
- 업종 필드 없음. SECT_TP_NM(소속부)은 실측에서 전 종목 빈 문자열
- 무체결일(실측): 시가·고가·저가·거래량·거래대금 "0", 종가는 값 있음. 숫자에 쉼표 없음, 결측은 빈 문자열
- 휴장일(실측 2026-09-25): 빈 배열. 과거 캘린더 생성은 이 서비스의 행 수로 판정
- 2026-09-18 행 942 = 한국투자증권 종목정보파일 주권 915와 거의 일치(차이는 증권구분 - 종목기본정보 참조). 2010-01-04 행 925
