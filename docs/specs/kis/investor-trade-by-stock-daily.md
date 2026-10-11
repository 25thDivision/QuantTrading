# 종목별 투자자매매동향(일별) - 종목별 투자자매매동향(일별)

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "종목별 투자자매매동향(일별)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 시세분석
- API 명: 종목별 투자자매매동향(일별)
- API ID: 종목별 투자자매매동향(일별)
- 실전 TR_ID: FHPTJ04160001
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 모의투자 미지원
- URL 명: /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily

### 개요
> 국내주식 종목별 투자자매매동향(일별) API입니다.
> 한국투자 HTS(eFriend Plus) &gt; [0416] 종목별 일별동향 화면 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.
>
> ※ 단위 : 금액(백만원) 수량(주)
>
> 당일 데이터는 15:40이후에 데이터가 가집계 및 산출되어 15:40부터 조회가능하며,
> 데이터 산출의 경우 산출 시간대는 일정하지 않을 수 있음을 참고 부탁드립니다.
> 추가로 API를 통한 00:00 ~ 15:40 이외의 시간은 당일 조회가 제한되는 점 이용에 참고 부탁드립니다.
>

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 40 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | FHPTJ04160001 |
| tr_cont | 연속 거래 여부 | string | N | 1 | 공백 : 초기 조회 <br>N : 다음 데이터 조회 (output header의 tr_cont가 M일 경우) |
| custtype | 고객 타입 | string | Y | 1 | B : 법인 <br>P : 개인 |
| seq_no | 일련번호 | string | N | 2 | [법인 필수] 001 |
| mac_address | 맥주소 | string | N | 12 | 법인고객 혹은 개인고객의 Mac address 값 |
| phone_number | 핸드폰번호 | string | N | 12 | [법인 필수] 제휴사APP을 사용하는 경우 사용자(회원) 핸드폰번호 <br>ex) 01011112222 (하이픈 등 구분값 제거) |
| ip_addr | 접속 단말 공인 IP | string | N | 12 | [법인 필수] 사용자(회원)의 IP Address |
| gt_uid | Global UID | string | N | 32 | [법인 필수] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Request Query Parameter
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| FID_COND_MRKT_DIV_CODE | 조건 시장 분류 코드 | string | Y | 2 | J:KRX, NX:NXT, UN:통합 |
| FID_INPUT_ISCD | 입력 종목코드 | string | Y | 12 | 종목번호 (6자리) |
| FID_INPUT_DATE_1 | 입력 날짜1 | string | Y | 10 | 입력 날짜(20250812) (해당일 조회는 장 종료 후 정상 조회 가능) |
| FID_ORG_ADJ_PRC | 수정주가 원주가 가격 | string | Y | 2 | 공란 입력 |
| FID_ETC_CLS_CODE | 기타 구분 코드 | string | Y | 2 | "1" 입력 |

#### Response Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| tr_id | 거래ID | string | Y | 13 | 요청한 tr_id |
| tr_cont | 연속 거래 여부 | string | N | 1 | 공백 : 초기 조회 <br>N : 다음 데이터 조회 (output header의 tr_cont가 M일 경우) |
| gt_uid | Global UID | string | N | 32 | [법인 필수] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| rt_cd | 성공 실패 여부 | string | Y | 1 |  |
| msg_cd | 응답코드 | string | Y | 8 |  |
| msg1 | 응답메세지 | string | Y | 80 |  |
| output1 | 응답상세 | object | Y |  |  |
| stck_prpr | 주식 현재가 | string | Y | 10 |  |
| prdy_vrss | 전일 대비 | string | Y | 10 |  |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 |  |
| prdy_ctrt | 전일 대비율 | string | Y | 82 |  |
| acml_vol | 누적 거래량 | string | Y | 18 |  |
| prdy_vol | 전일 거래량 | string | Y | 18 |  |
| rprs_mrkt_kor_name | 대표 시장 한글 명 | string | Y | 40 |  |
| output2 | 응답상세 | object array | Y |  | array |
| stck_bsop_date | 주식 영업 일자 | string | Y | 8 |  |
| stck_clpr | 주식 종가 | string | Y | 10 |  |
| prdy_vrss | 전일 대비 | string | Y | 10 |  |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 |  |
| prdy_ctrt | 전일 대비율 | string | Y | 82 |  |
| acml_vol | 누적 거래량 | string | Y | 18 | 단위 : 주 |
| acml_tr_pbmn | 누적 거래 대금 | string | Y | 18 | 단위 : 백만원 |
| stck_oprc | 주식 시가2 | string | Y | 10 |  |
| stck_hgpr | 주식 최고가 | string | Y | 10 |  |
| stck_lwpr | 주식 최저가 | string | Y | 10 |  |
| frgn_ntby_qty | 외국인 순매수 수량 | string | Y | 12 | 단위 : 주 |
| frgn_reg_ntby_qty | 외국인 등록 순매수 수량 | string | Y | 18 |  |
| frgn_nreg_ntby_qty | 외국인 비등록 순매수 수량 | string | Y | 18 |  |
| prsn_ntby_qty | 개인 순매수 수량 | string | Y | 12 |  |
| orgn_ntby_qty | 기관계 순매수 수량 | string | Y | 18 |  |
| scrt_ntby_qty | 증권 순매수 수량 | string | Y | 12 |  |
| ivtr_ntby_qty | 투자신탁 순매수 수량 | string | Y | 12 |  |
| pe_fund_ntby_vol | 사모 펀드 순매수 거래량 | string | Y | 18 |  |
| bank_ntby_qty | 은행 순매수 수량 | string | Y | 12 |  |
| insu_ntby_qty | 보험 순매수 수량 | string | Y | 12 |  |
| mrbn_ntby_qty | 종금 순매수 수량 | string | Y | 12 |  |
| fund_ntby_qty | 기금 순매수 수량 | string | Y | 12 |  |
| etc_ntby_qty | 기타 순매수 수량 | string | Y | 12 |  |
| etc_corp_ntby_vol | 기타 법인 순매수 거래량 | string | Y | 18 |  |
| etc_orgt_ntby_vol | 기타 단체 순매수 거래량 | string | Y | 18 |  |
| frgn_reg_ntby_pbmn | 외국인 등록 순매수 대금 | string | Y | 18 | 단위 : 백만원 |
| frgn_ntby_tr_pbmn | 외국인 순매수 거래 대금 | string | Y | 18 |  |
| frgn_nreg_ntby_pbmn | 외국인 비등록 순매수 대금 | string | Y | 18 |  |
| prsn_ntby_tr_pbmn | 개인 순매수 거래 대금 | string | Y | 18 |  |
| orgn_ntby_tr_pbmn | 기관계 순매수 거래 대금 | string | Y | 18 |  |
| scrt_ntby_tr_pbmn | 증권 순매수 거래 대금 | string | Y | 18 |  |
| pe_fund_ntby_tr_pbmn | 사모 펀드 순매수 거래 대금 | string | Y | 18 |  |
| ivtr_ntby_tr_pbmn | 투자신탁 순매수 거래 대금 | string | Y | 18 |  |
| bank_ntby_tr_pbmn | 은행 순매수 거래 대금 | string | Y | 18 |  |
| insu_ntby_tr_pbmn | 보험 순매수 거래 대금 | string | Y | 18 |  |
| mrbn_ntby_tr_pbmn | 종금 순매수 거래 대금 | string | Y | 18 |  |
| fund_ntby_tr_pbmn | 기금 순매수 거래 대금 | string | Y | 18 |  |
| etc_ntby_tr_pbmn | 기타 순매수 거래 대금 | string | Y | 18 |  |
| etc_corp_ntby_tr_pbmn | 기타 법인 순매수 거래 대금 | string | Y | 18 |  |
| etc_orgt_ntby_tr_pbmn | 기타 단체 순매수 거래 대금 | string | Y | 18 |  |
| frgn_seln_vol | 외국인 매도 거래량 | string | Y | 18 |  |
| frgn_shnu_vol | 외국인 매수2 거래량 | string | Y | 18 |  |
| frgn_seln_tr_pbmn | 외국인 매도 거래 대금 | string | Y | 18 |  |
| frgn_shnu_tr_pbmn | 외국인 매수2 거래 대금 | string | Y | 18 |  |
| frgn_reg_askp_qty | 외국인 등록 매도 수량 | string | Y | 18 |  |
| frgn_reg_bidp_qty | 외국인 등록 매수 수량 | string | Y | 18 |  |
| frgn_reg_askp_pbmn | 외국인 등록 매도 대금 | string | Y | 18 |  |
| frgn_reg_bidp_pbmn | 외국인 등록 매수 대금 | string | Y | 18 |  |
| frgn_nreg_askp_qty | 외국인 비등록 매도 수량 | string | Y | 18 |  |
| frgn_nreg_bidp_qty | 외국인 비등록 매수 수량 | string | Y | 18 |  |
| frgn_nreg_askp_pbmn | 외국인 비등록 매도 대금 | string | Y | 18 |  |
| frgn_nreg_bidp_pbmn | 외국인 비등록 매수 대금 | string | Y | 18 |  |
| prsn_seln_vol | 개인 매도 거래량 | string | Y | 18 |  |
| prsn_shnu_vol | 개인 매수2 거래량 | string | Y | 18 |  |
| prsn_seln_tr_pbmn | 개인 매도 거래 대금 | string | Y | 18 |  |
| prsn_shnu_tr_pbmn | 개인 매수2 거래 대금 | string | Y | 18 |  |
| orgn_seln_vol | 기관계 매도 거래량 | string | Y | 18 |  |
| orgn_shnu_vol | 기관계 매수2 거래량 | string | Y | 18 |  |
| orgn_seln_tr_pbmn | 기관계 매도 거래 대금 | string | Y | 18 |  |
| orgn_shnu_tr_pbmn | 기관계 매수2 거래 대금 | string | Y | 18 |  |
| scrt_seln_vol | 증권 매도 거래량 | string | Y | 18 |  |
| scrt_shnu_vol | 증권 매수2 거래량 | string | Y | 18 |  |
| scrt_seln_tr_pbmn | 증권 매도 거래 대금 | string | Y | 18 |  |
| scrt_shnu_tr_pbmn | 증권 매수2 거래 대금 | string | Y | 18 |  |
| ivtr_seln_vol | 투자신탁 매도 거래량 | string | Y | 18 |  |
| ivtr_shnu_vol | 투자신탁 매수2 거래량 | string | Y | 18 |  |
| ivtr_seln_tr_pbmn | 투자신탁 매도 거래 대금 | string | Y | 18 |  |
| ivtr_shnu_tr_pbmn | 투자신탁 매수2 거래 대금 | string | Y | 18 |  |
| pe_fund_seln_tr_pbmn | 사모 펀드 매도 거래 대금 | string | Y | 18 |  |
| pe_fund_seln_vol | 사모 펀드 매도 거래량 | string | Y | 18 |  |
| pe_fund_shnu_tr_pbmn | 사모 펀드 매수2 거래 대금 | string | Y | 18 |  |
| pe_fund_shnu_vol | 사모 펀드 매수2 거래량 | string | Y | 18 |  |
| bank_seln_vol | 은행 매도 거래량 | string | Y | 18 |  |
| bank_shnu_vol | 은행 매수2 거래량 | string | Y | 18 |  |
| bank_seln_tr_pbmn | 은행 매도 거래 대금 | string | Y | 18 |  |
| bank_shnu_tr_pbmn | 은행 매수2 거래 대금 | string | Y | 18 |  |
| insu_seln_vol | 보험 매도 거래량 | string | Y | 18 |  |
| insu_shnu_vol | 보험 매수2 거래량 | string | Y | 18 |  |
| insu_seln_tr_pbmn | 보험 매도 거래 대금 | string | Y | 18 |  |
| insu_shnu_tr_pbmn | 보험 매수2 거래 대금 | string | Y | 18 |  |
| mrbn_seln_vol | 종금 매도 거래량 | string | Y | 18 |  |
| mrbn_shnu_vol | 종금 매수2 거래량 | string | Y | 18 |  |
| mrbn_seln_tr_pbmn | 종금 매도 거래 대금 | string | Y | 18 |  |
| mrbn_shnu_tr_pbmn | 종금 매수2 거래 대금 | string | Y | 18 |  |
| fund_seln_vol | 기금 매도 거래량 | string | Y | 18 |  |
| fund_shnu_vol | 기금 매수2 거래량 | string | Y | 18 |  |
| fund_seln_tr_pbmn | 기금 매도 거래 대금 | string | Y | 18 |  |
| fund_shnu_tr_pbmn | 기금 매수2 거래 대금 | string | Y | 18 |  |
| etc_seln_vol | 기타 매도 거래량 | string | Y | 18 |  |
| etc_shnu_vol | 기타 매수2 거래량 | string | Y | 18 |  |
| etc_seln_tr_pbmn | 기타 매도 거래 대금 | string | Y | 18 |  |
| etc_shnu_tr_pbmn | 기타 매수2 거래 대금 | string | Y | 18 |  |
| etc_orgt_seln_vol | 기타 단체 매도 거래량 | string | Y | 18 |  |
| etc_orgt_shnu_vol | 기타 단체 매수2 거래량 | string | Y | 18 |  |
| etc_orgt_seln_tr_pbmn | 기타 단체 매도 거래 대금 | string | Y | 18 |  |
| etc_orgt_shnu_tr_pbmn | 기타 단체 매수2 거래 대금 | string | Y | 18 |  |
| etc_corp_seln_vol | 기타 법인 매도 거래량 | string | Y | 18 |  |
| etc_corp_shnu_vol | 기타 법인 매수2 거래량 | string | Y | 18 |  |
| etc_corp_seln_tr_pbmn | 기타 법인 매도 거래 대금 | string | Y | 18 |  |
| etc_corp_shnu_tr_pbmn | 기타 법인 매수2 거래 대금 | string | Y | 18 |  |
| bold_yn | BOLD 여부 | string | Y | 18 |  |

### Example
#### Request Example (Python)
```
FID_COND_MRKT_DIV_CODE:J
FID_INPUT_ISCD:005930
FID_INPUT_DATE_1:20250811
FID_ORG_ADJ_PRC:
FID_ETC_CLS_CODE:
```
#### Response Example
```
{
    "output1": {
        "stck_prpr": "71100",
        "prdy_vrss": "100",
        "prdy_vrss_sign": "2",
        "prdy_ctrt": "0.14",
        "acml_vol": "15797656",
        "prdy_vol": "11354253",
        "rprs_mrkt_kor_name": "KOSPI200"
    },
    "output2": [
        {
            "stck_bsop_date": "20250811",
            "stck_clpr": "71000",
            "prdy_vrss": "-800",
            "prdy_vrss_sign": "5",
            "prdy_ctrt": "-1.11",
            "acml_vol": "11354253",
            "acml_tr_pbmn": "808470078650",
            "stck_oprc": "72000",
            "stck_hgpr": "72100",
            "stck_lwpr": "70800",
            "frgn_ntby_qty": "-2029800",
            "frgn_reg_ntby_qty": "-2031350",
            "frgn_nreg_ntby_qty": "1550",
            "prsn_ntby_qty": "1686273",
            "orgn_ntby_qty": "-571822",
            "scrt_ntby_qty": "-44264",
            "ivtr_ntby_qty": "-205974",
            "pe_fund_ntby_vol": "-125032",
            "bank_ntby_qty": "2930",
            "insu_ntby_qty": "-85309",
            "mrbn_ntby_qty": "-737",
            "fund_ntby_qty": "-113436",
            "etc_ntby_qty": "915349",
            "etc_corp_ntby_vol": "915349",
            "etc_orgt_ntby_vol": "0",
            "frgn_reg_ntby_pbmn": "-144473",
            "frgn_ntby_tr_pbmn": "-144363",
            "frgn_nreg_ntby_pbmn": "110",
            "prsn_ntby_tr_pbmn": "120110",
            "orgn_ntby_tr_pbmn": "-40903",
            "scrt_ntby_tr_pbmn": "-3169",
            "pe_fund_ntby_tr_pbmn": "-8887",
            "ivtr_ntby_tr_pbmn": "-14641",
            "bank_ntby_tr_pbmn": "209",
            "insu_ntby_tr_pbmn": "-6061",
            "mrbn_ntby_tr_pbmn": "-52",
            "fund_ntby_tr_pbmn": "-8301",
            "etc_ntby_tr_pbmn": "65156",
            "etc_corp_ntby_tr_pbmn": "65156",
            "etc_orgt_ntby_tr_pbmn": "0",
            "frgn_seln_vol": "4557311",
            "frgn_shnu_vol": "2527511",
            "frgn_seln_tr_pbmn": "324535",
            "frgn_shnu_tr_pbmn": "180172",
            "frgn_reg_askp_qty": "4550828",
            "frgn_reg_bidp_qty": "2519478",
            "frgn_reg_askp_pbmn": "324074",
            "frgn_reg_bidp_pbmn": "179600",
... (이하 생략, 59줄 - 원본 Excel 시트 참조)
```

## 프로젝트 주석 (명세 아님)
- 용도: 투자자별 매매동향 수집(1-후반 묶음, 결정 8 확장 항목). 종목별 호출이라 전 종목은 2,000여 호출/일
- 모의투자 미지원(Excel 목록에서 확인 - 조사 보고 시점에는 미확인이었음). 1회 행 수·제공 기간은 문서에 없음
