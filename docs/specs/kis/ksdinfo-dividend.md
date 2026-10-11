# 예탁원정보(배당일정) - 국내주식-145

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "예탁원정보(배당일정)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 종목정보
- API 명: 예탁원정보(배당일정)
- API ID: 국내주식-145
- 실전 TR_ID: HHKDB669102C0
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 미지원
- URL 명: /uapi/domestic-stock/v1/ksdinfo/dividend

### 개요
> 예탁원정보(배당일정) API입니다. 
> 한국투자 HTS(eFriend Plus) &gt; [0658] 배당 화면의 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.
>
> ※ 예탁원에서 제공한 자료이므로 정보용으로만 사용하시기 바랍니다.
> '주식배당지급일'은 배당주식의 주식교부일자를 말합니다. 배당주식의 계좌입고는 배당주식 상장일인데 일반적으로 주권교부일의 익영업일입니다.

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | HHKDB669102C0 |
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
| CTS | CTS | string | Y | 17 | 공백 |
| GB1 | 조회구분 | string | Y | 1 | 0:배당전체, 1:결산배당, 2:중간배당 |
| F_DT | 조회일자From | string | Y | 8 | 일자 ~ |
| T_DT | 조회일자To | string | Y | 8 | ~ 일자 |
| SHT_CD | 종목코드 | string | Y | 9 | 공백: 전체,  특정종목 조회시 : 종목코드 |
| HIGH_GB | 고배당여부 | string | Y | 1 | 공백 |

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
| output1 | 응답상세 | object array | Y |  | array |
| record_date | 기준일 | string | Y | 8 |  |
| sht_cd | 종목코드 | string | Y | 9 |  |
| isin_name | 종목명 | string | Y | 40 |  |
| divi_kind | 배당종류 | string | Y | 8 |  |
| face_val | 액면가 | string | Y | 9 |  |
| per_sto_divi_amt | 현금배당금 | string | Y | 12 |  |
| divi_rate | 현금배당률(%) | string | Y | 62 |  |
| stk_divi_rate | 주식배당률(%) | string | Y | 152 |  |
| divi_pay_dt | 배당금지급일 | string | Y | 10 |  |
| stk_div_pay_dt | 주식배당지급일 | string | Y | 10 |  |
| odd_pay_dt | 단주대금지급일 | string | Y | 10 |  |
| stk_kind | 주식종류 | string | Y | 10 |  |
| high_divi_gb | 고배당종목여부 | string | Y | 1 |  |

### Example
#### Request Example (Python)
```
cts:
gb1:0
f_dt:20230301
t_dt:20240326
sht_cd:
high_gb:0
```
#### Response Example
```
{
    "output1": [
        {
            "record_date": "20240326",
            "sht_cd": "000720",
            "isin_name": "현대건설",
            "divi_kind": "결산",
            "face_val": "000005000",
            "per_sto_divi_amt": "000000000600",
            "divi_rate": " 12.00",
            "stk_divi_rate": "  0.00",
            "divi_pay_dt": "",
            "stk_div_pay_dt": "",
            "odd_pay_dt": "",
            "stk_kind": "보통",
            "high_divi_gb": ""
        },
        {
            "record_date": "20240326",
            "sht_cd": "000725",
            "isin_name": "현대건설1우",
            "divi_kind": "결산",
            "face_val": "000005000",
            "per_sto_divi_amt": "000000000650",
            "divi_rate": " 13.00",
            "stk_divi_rate": "  0.00",
            "divi_pay_dt": "",
            "stk_div_pay_dt": "",
            "odd_pay_dt": "",
            "stk_kind": "우선",
            "high_divi_gb": ""
        },
        {
            "record_date": "20240326",
            "sht_cd": "003540",
            "isin_name": "대신증권",
            "divi_kind": "결산",
            "face_val": "000005000",
            "per_sto_divi_amt": "000000001200",
            "divi_rate": " 24.00",
            "stk_divi_rate": "  0.00",
            "divi_pay_dt": "2024/04/16",
            "stk_div_pay_dt": "",
            "odd_pay_dt": "",
            "stk_kind": "보통",
            "high_divi_gb": ""
        },
        {
            "record_date": "20240326",
            "sht_cd": "003545",
            "isin_name": "대신증권1우",
            "divi_kind": "결산",
            "face_val": "000005000",
            "per_sto_divi_amt": "000000001250",
            "divi_rate": " 25.00",
            "stk_divi_rate": "  0.00",
            "divi_pay_dt": "2024/04/16",
            "stk_div_pay_dt": "",
            "odd_pay_dt": "",
            "stk_kind": "우선",
... (이하 생략, 913줄 - 원본 Excel 시트 참조)
```

## 프로젝트 주석 (명세 아님)
- 용도: 배당 정보(후반 묶음). 기준일(record_date)만 있고 배당락일 필드가 없다. 국내 결제 관행상 배당락일 = 기준일의 직전 영업일로 계산 가능(일반 규칙, 예외 미확인)
- 모의투자 미지원. 조정 계수 산출에는 현금배당금(per_sto_divi_amt)·주식배당률(stk_divi_rate)을 쓸 수 있으나 결정 11의 원본 가격 불변 원칙상 배당락 조정 여부는 별도 결정
