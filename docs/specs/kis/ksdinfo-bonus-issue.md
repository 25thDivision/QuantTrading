# 예탁원정보(무상증자일정) - 국내주식-144

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "예탁원정보(무상증자일정)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 종목정보
- API 명: 예탁원정보(무상증자일정)
- API ID: 국내주식-144
- 실전 TR_ID: HHKDB669101C0
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 모의투자 미지원
- URL 명: /uapi/domestic-stock/v1/ksdinfo/bonus-issue

### 개요
> 예탁원정보(무상증자일정) API입니다. 
> 한국투자 HTS(eFriend Plus) &gt; [0656] 무상증자 화면의 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.
>
> ※ 예탁원에서 제공한 자료이므로 정보용으로만 사용하시기 바랍니다.

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | HHKDB669101C0 |
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
| F_DT | 조회일자From | string | Y | 8 | 일자 ~ |
| T_DT | 조회일자To | string | Y | 8 | ~ 일자 |
| SHT_CD | 종목코드 | string | Y | 9 | 공백: 전체,  특정종목 조회시 : 종목코드 |

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
| fix_rate | 확정배정율 | string | Y | 152 |  |
| odd_rec_price | 단주기준가 | string | Y | 9 |  |
| right_dt | 권리락일 | string | Y | 8 |  |
| odd_pay_dt | 단주대금지급일 | string | Y | 23 |  |
| list_date | 상장/등록일 | string | Y | 8 |  |
| tot_issue_stk_qty | 발행주식 | string | Y | 12 |  |
| issue_stk_qty | 발행할주식 | string | Y | 12 |  |
| stk_kind | 주식종류 | string | Y | 2 |  |

### Example
#### Request Example (Python)
```
cts:
f_dt:20230301
t_dt:20240326
sht_cd:
```
#### Response Example
```
{
    "output1": [
        {
            "record_date": "20240326",
            "sht_cd": "466100",
            "isin_name": "클로봇",
            "fix_rate": "1000.0",
            "odd_rec_price": "000000000",
            "right_dt": "20240325",
            "odd_pay_dt": "",
            "list_date": "",
            "tot_issue_stk_qty": "     1885394",
            "issue_stk_qty": "    18853940",
            "stk_kind": "01"
        },
        {
            "record_date": "20240315",
            "sht_cd": "473980",
            "isin_name": "노머스",
            "fix_rate": "3900.0",
            "odd_rec_price": "000000000",
            "right_dt": "20240314",
            "odd_pay_dt": "",
            "list_date": "",
            "tot_issue_stk_qty": "      234220",
            "issue_stk_qty": "     9134580",
            "stk_kind": "01"
        },
        {
            "record_date": "20240314",
            "sht_cd": "377220",
            "isin_name": "프롬바이오",
            "fix_rate": "100.00",
            "odd_rec_price": "000000000",
            "right_dt": "20240313",
            "odd_pay_dt": "",
            "list_date": "20240405",
            "tot_issue_stk_qty": "    14155000",
            "issue_stk_qty": "    14155000",
            "stk_kind": "01"
        },
        {
            "record_date": "20240307",
            "sht_cd": "357230",
            "isin_name": "에이치피오",
            "fix_rate": "100.00",
            "odd_rec_price": "000000000",
            "right_dt": "20240306",
            "odd_pay_dt": "",
            "list_date": "20240329",
            "tot_issue_stk_qty": "    21149725",
            "issue_stk_qty": "    20337240",
            "stk_kind": "01"
        },
        {
            "record_date": "20240305",
            "sht_cd": "005810",
            "isin_name": "풍산홀딩스",
            "fix_rate": " 50.00",
            "odd_rec_price": "000029850",
... (이하 생략, 12줄 - 원본 Excel 시트 참조)
```

## 프로젝트 주석 (명세 아님)
- 용도: corporate_actions 조정 계수 원천 후보 (결정 37). 확정배정율(fix_rate)과 권리락일(right_dt)
- 모의투자 미지원. 전 종목 기간 호출 가능. 제공 기간 미확인 - 결정 37 실측 대상
