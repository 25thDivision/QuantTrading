# 주식일별분봉조회 - 국내주식-213

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "주식일별분봉조회")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 기본시세
- API 명: 주식일별분봉조회
- API ID: 국내주식-213
- 실전 TR_ID: FHKST03010230
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 모의투자 미지원
- URL 명: /uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice

### 개요
> 주식일별분봉조회 API입니다. 
>
> 실전계좌의 경우, 한 번의 호출에 최대 120건까지 확인 가능하며, 
> FID_INPUT_DATE_1, FID_INPUT_HOUR_1 이용하여 과거일자 분봉조회 가능합니다.
>
> ※ 과거 분봉 조회 시, 당사 서버에서 보관하고 있는 만큼의 데이터만 확인이 가능합니다. (최대 1년 분봉 보관)

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | FHKST03010230 |
| tr_cont | 연속 거래 여부 | string | N | 1 | 공백 : 초기 조회 <br>N : 다음 데이터 조회 (output header의 tr_cont가 M일 경우) |
| custtype | 고객 타입 | string | Y | 1 | B : 법인 <br>P : 개인 |
| seq_no | 일련번호 | string | N | 2 | [법인 필수] 001 |
| mac_address | 맥주소 | string | N | 12 | 법인고객 혹은 개인고객의 Mac address 값 |
| phone_number | 핸드폰번호 | string | N | 12 | [법인 필수] 제휴사APP을 사용하는 경우 사용자(회원) 핸드폰번호 <br>ex) 01011112222 (하이픈 등 구분값 제거) |
| ip_addr | 접속 단말 공인 IP | string | N | 12 | [법인 필수] 사용자(회원)의 IP Address |
| gt_uid | Global UID | string | N | 32 | [법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Request Query Parameter
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| FID_COND_MRKT_DIV_CODE | 조건 시장 분류 코드 | string | Y | 2 | J:KRX, NX:NXT, UN:통합 |
| FID_INPUT_ISCD | 입력 종목코드 | string | Y | 12 | 종목코드 (ex 005930 삼성전자) |
| FID_INPUT_HOUR_1 | 입력 시간1 | string | Y | 10 | 입력 시간(ex 13시 130000) |
| FID_INPUT_DATE_1 | 입력 날짜1 | string | Y | 2 | 입력 날짜(20241023) |
| FID_PW_DATA_INCU_YN | 과거 데이터 포함 여부 | string | Y | 2 |  |
| FID_FAKE_TICK_INCU_YN | 허봉 포함 여부 | string | N | 2 | 공백 필수 입력 |

#### Response Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| tr_id | 거래ID | string | Y | 13 | 요청한 tr_id |
| tr_cont | 연속 거래 여부 | string | N | 1 | 공백 : 초기 조회 <br>N : 다음 데이터 조회 (output header의 tr_cont가 M일 경우) |
| gt_uid | Global UID | string | N | 32 | [법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| rt_cd | 성공 실패 여부 | string | Y | 1 |  |
| msg_cd | 응답코드 | string | Y | 8 |  |
| msg1 | 응답메세지 | string | Y | 80 |  |
| output1 | 응답상세 | object | Y |  |  |
| prdy_vrss | 전일 대비 | string | Y | 10 |  |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 |  |
| prdy_ctrt | 전일 대비율 | string | Y | 11 |  |
| stck_prdy_clpr | 주식 전일 종가 | string | Y | 10 |  |
| acml_vol | 누적 거래량 | string | Y | 18 |  |
| acml_tr_pbmn | 누적 거래 대금 | string | Y | 18 |  |
| hts_kor_isnm | HTS 한글 종목명 | string | Y | 40 |  |
| stck_prpr | 주식 현재가 | string | Y | 10 |  |
| output2 | 응답상세 | object array | Y |  | array |
| stck_bsop_date | 주식 영업 일자 | string | Y | 8 |  |
| stck_cntg_hour | 주식 체결 시간 | string | Y | 6 |  |
| stck_prpr | 주식 현재가 | string | Y | 10 |  |
| stck_oprc | 주식 시가2 | string | Y | 10 |  |
| stck_hgpr | 주식 최고가 | string | Y | 10 |  |
| stck_lwpr | 주식 최저가 | string | Y | 10 |  |
| cntg_vol | 체결 거래량 | string | Y | 18 |  |
| acml_tr_pbmn | 누적 거래 대금 | string | Y | 18 |  |

### Example
#### Request Example (Python)
```
FID_COND_MRKT_DIV_CODE:J
FID_INPUT_ISCD:005930
FID_INPUT_DATE_1:20241108
FID_INPUT_HOUR_1:140000
FID_PW_DATA_INCU_YN:Y
FID_FAKE_TICK_INCU_YN:N
```
#### Response Example
```
{
    "output1": {
        "prdy_vrss": "-500",
        "prdy_vrss_sign": "5",
        "prdy_ctrt": "-0.87",
        "stck_prdy_clpr": "57500",
        "acml_vol": "13531211",
        "acml_tr_pbmn": "779692013500",
        "hts_kor_isnm": "삼성전자",
        "stck_prpr": "57000"
    },
    "output2": [
        {
            "stck_bsop_date": "20241108",
            "stck_cntg_hour": "140000",
            "stck_prpr": "57300",
            "stck_oprc": "57300",
            "stck_hgpr": "57400",
            "stck_lwpr": "57200",
            "cntg_vol": "59047",
            "acml_tr_pbmn": "538940180600"
        },
        {
            "stck_bsop_date": "20241108",
            "stck_cntg_hour": "135900",
            "stck_prpr": "57300",
            "stck_oprc": "57400",
            "stck_hgpr": "57500",
            "stck_lwpr": "57300",
            "cntg_vol": "118619",
            "acml_tr_pbmn": "535556648100"
        },
		...
        {
            "stck_bsop_date": "20241108",
            "stck_cntg_hour": "120100",
            "stck_prpr": "57700",
            "stck_oprc": "57700",
            "stck_hgpr": "57800",
            "stck_lwpr": "57700",
            "cntg_vol": "3856",
            "acml_tr_pbmn": "357875441100"
        }
    ],
    "rt_cd": "0",
    "msg_cd": "MCA00000",
    "msg1": "정상처리 되었습니다."
}
```

## 프로젝트 주석 (명세 아님)
- 용도: 과거 결손 소급 보충 전용 (결정 11). 1회 120건, 약 1년 범위
- Excel 목록은 모의투자 미지원으로 표기하나, 2026-09-28 모의 키 소급 실행이 정상 동작함(README 참조). 모의 환경 동작을 보장된 것으로 취급하지 않는다
- 실측: 15:20~15:29 마감 단일가 구간 10행이 결락되어 일상 수집에서 배제. 체결 분만 반환(무체결 분 생략), 애프터마켓 구간 포함. 소급 성공은 partial로 기록
