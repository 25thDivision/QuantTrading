# 주식당일분봉조회 - v1_국내주식-022

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "주식당일분봉조회")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 기본시세
- API 명: 주식당일분봉조회
- API ID: v1_국내주식-022
- 실전 TR_ID: FHKST03010200
- 모의 TR_ID: FHKST03010200
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: https://openapivts.koreainvestment.com:29443
- URL 명: /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice

### 개요
> 주식당일분봉조회 API입니다. 
> 실전계좌/모의계좌의 경우, 한 번의 호출에 최대 30건까지 확인 가능합니다.
>
> ※ 당일 분봉 데이터만 제공됩니다. (전일자 분봉 미제공)
>
> ※ input &gt; FID_INPUT_HOUR_1 에 미래일시 입력 시에 현재가로 조회됩니다.
> ex) 오전 10시에 113000 입력 시에 오전 10시~11시30분 사이의 데이터가 오전 10시 값으로 조회됨
>
> ※ output2의 첫번째 배열의 체결량(cntg_vol)은 첫체결이 발생되기 전까지는 이전 분봉의 체결량이 해당 위치에 표시됩니다. 
> 해당 분봉의 첫 체결이 발생되면 해당 이전분 체결량이 두번째 배열로 이동되면서 새로운 체결량으로 업데이트됩니다.

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | FHKST03010200 |
| tr_cont | 연속 거래 여부 | string | N | 1 | tr_cont를 이용한 다음조회 불가 API |
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
| FID_INPUT_HOUR_1 | 입력 시간1 | string | Y | 10 | 입력시간 |
| FID_PW_DATA_INCU_YN | 과거 데이터 포함 여부 | string | Y | 2 |  |
| FID_ETC_CLS_CODE | 기타 구분 코드 | string | Y | 2 |  |

#### Response Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| tr_id | 거래ID | string | Y | 13 | 요청한 tr_id |
| tr_cont | 연속 거래 여부 | string | N | 1 | tr_cont를 이용한 다음조회 불가 API |
| gt_uid | Global UID | string | N | 32 | [법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| rt_cd | 성공 실패 여부 | string | Y | 1 |  |
| msg_cd | 응답코드 | string | Y | 8 |  |
| msg1 | 응답메세지 | string | Y | 80 |  |
| output1 | 응답상세 | object | Y |  |  |
| prdy_vrss | 전일 대비 | string | Y | 10 | 전일 대비 변동 (+-변동차이) |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 | 전일 대비 부호 |
| prdy_ctrt | 전일 대비율 | string | Y | 10 | 소수점 두자리까지 제공 |
| stck_prdy_clpr | 전일대비 종가 | string | Y | 10 | 전일대비 종가 |
| acml_vol | 누적 거래량 | string | Y | 18 | 누적 거래량 |
| acml_tr_pbmn | 누적 거래대금 | string | Y | 18 | 누적 거래대금 |
| hts_kor_isnm | 한글 종목명 | string | Y | 40 | 한글 종목명 (HTS 기준) |
| stck_prpr | 주식 현재가 | string | Y | 10 | 주식 현재가 |
| output2 | 응답상세 | object array | Y |  | Array |
| stck_bsop_date | 주식 영업일자 | string | Y | 8 | 주식 영업일자 |
| stck_cntg_hour | 주식 체결시간 | string | Y | 6 | 주식 체결시간 |
| stck_prpr | 주식 현재가 | string | Y | 10 | 주식 현재가 |
| stck_oprc | 주식 시가 | string | Y | 10 | 주식 시가 |
| stck_hgpr | 주식 최고가 | string | Y | 10 | 주식 최고가 |
| stck_lwpr | 주식 최저가 | string | Y | 10 | 주식 최저가 |
| cntg_vol | 체결 거래량 | string | Y | 18 |  |
| acml_tr_pbmn | 누적 거래대금 | string | Y | 18 |  |

### Example
#### Request Example (Python)
```
{
            "fid_cond_mrkt_div_code": "J",
            "fid_etc_cls_code": "",
            "fid_input_hour_1": "100000",
            "fid_input_iscd": "000660",
            "fid_pw_data_incu_yn": "Y"
 }
```
#### Response Example
```
{
        "output1": {
            "acml_tr_pbmn": "96910660000",
            "acml_vol": "1046883",
            "hts_kor_isnm": "SK하이닉스",
            "prdy_ctrt": "-0.11",
            "prdy_vrss": "-100",
            "prdy_vrss_sign": "5",
            "stck_prdy_clpr": "92400",
            "stck_prpr": "92300"
        },
        "output2": [
            {
                "acml_tr_pbmn": "55858827400",
                "cntg_vol": "1383",
                "stck_bsop_date": "20220902",
                "stck_cntg_hour": "100000",
                "stck_hgpr": "92500",
                "stck_lwpr": "92400",
                "stck_oprc": "92400",
                "stck_prpr": "92500"
            },
            {
                "acml_tr_pbmn": "55731000300",
                "cntg_vol": "1564",
                "stck_bsop_date": "20220902",
                "stck_cntg_hour": "095900",
                "stck_hgpr": "92500",
                "stck_lwpr": "92400",
                "stck_oprc": "92500",
                "stck_prpr": "92400"
                              "stck_hgpr": "93300",
                "stck_lwpr": "93100",
                "stck_oprc": "93100",
                "stck_prpr": "93200"
            }
            ......
        ],
        "rt_cd": "0",
         "msg_cd": "MCA00000",
         "msg1": "정상처리 되었습니다!"
 }
```

## 프로젝트 주석 (명세 아님)
- 용도: 마감 후 분봉 스윕의 유일한 TR (DECISIONS.md 결정 11). 1회 30건, 종목당 약 14회 페이징으로 당일 전 구간(애프터마켓 20:00까지) 수집
- 실측: 최근 거래일만 제공하며 개장(09:00)에 대상이 전환됨. 무체결 분은 직전가로 채워 제공(volume 0). 전 종목 소요 약 217~222분(실전 키 15건/초 설정)
- 휴장일·주말 호출은 최근 거래일을 돌려주므로 ok 아닌 종목의 재시도 기회가 됨 (결정 11 시각 안전장치)
