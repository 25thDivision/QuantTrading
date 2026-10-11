# kospi_dd_trd - KOSPI 시리즈 일별시세정보 (코스피 계열 지수 일봉)

## 명세서 원문 (KRX Open API 포털, 2026-09-28)

- Description: KOSPI 시리즈 지수의 시세정보 제공 ('10년01월04일 데이터부터 제공)
- Server endpoint url: `https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd`

### request - InBlock_1
| Name | Type | Description |
|---|---|---|
| basDd | string | 기준일자 |

### response - OutBlock_1
| Name | Type | Description |
|---|---|---|
| BAS_DD | string | 기준일자 |
| IDX_CLSS | string | 계열구분 |
| IDX_NM | string | 지수명 |
| CLSPRC_IDX | string | 종가 |
| CMPPREVDD_IDX | string | 대비 |
| FLUC_RT | string | 등락률 |
| OPNPRC_IDX | string | 시가 |
| HGPRC_IDX | string | 고가 |
| LWPRC_IDX | string | 저가 |
| ACC_TRDVOL | string | 거래량 |
| ACC_TRDVAL | string | 거래대금 |
| MKTCAP | string | 상장시가총액 |

### request Sample
```json
{"basDd":"__"}
```

### response Sample
```json
{"OutBlock_1":[{"BAS_DD":"__","IDX_CLSS":"__","IDX_NM":"__","CLSPRC_IDX":"-","CMPPREVDD_IDX":"-","FLUC_RT":"-","OPNPRC_IDX":"-","HGPRC_IDX":"-","LWPRC_IDX":"-","ACC_TRDVOL":"-","ACC_TRDVAL":"-","MKTCAP":"-"},{"BAS_DD":"__","IDX_CLSS":"__","IDX_NM":"__","CLSPRC_IDX":"-","CMPPREVDD_IDX":"-","FLUC_RT":"-","OPNPRC_IDX":"-","HGPRC_IDX":"-","LWPRC_IDX":"-","ACC_TRDVOL":"-","ACC_TRDVAL":"-","MKTCAP":"-"}]}
```

## 프로젝트 주석 (명세 아님)
- 용도: ③ 시장 필터(지수가 기준선 아래면 신규 진입 중단, 결정 4절 ③)의 지수 일봉. DECISIONS.md 결정 12
- 하루치 응답에 코스피 계열 지수가 전부 온다(실측 2026-09-18 54건: 코스피, 코스피 200, 코스피 100·50, 규모별, 업종별, 비중상한 등. 2010-01-04는 41건 - 목록이 시기별로 다르므로 고정 목록을 전제하지 않는다)
- 대표 지수의 IDX_NM은 정확히 "코스피", IDX_CLSS는 "KOSPI". ③ 시장 필터는 이 행을 쓰고 문자열은 config에 둔다
- "코스피 (외국주포함)" 행은 시가·고가·저가·종가가 빈 문자열이고 거래량·거래대금·상장시가총액만 있다. 2010년에는 시가·고가·저가가 빈 지수가 5건
- 지수값은 소수점 둘째 자리 문자열("6894.23"). 결측은 빈 문자열
- 휴장일(2026-09-25): 빈 배열
- 지수 자체에는 종목코드가 없으므로 (BAS_DD, IDX_CLSS, IDX_NM)가 키
