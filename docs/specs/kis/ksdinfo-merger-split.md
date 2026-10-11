# 예탁원정보(합병_분할일정) - 국내주식-147

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "예탁원정보(합병_분할일정)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 종목정보
- API 명: 예탁원정보(합병_분할일정)
- API ID: 국내주식-147
- 실전 TR_ID: HHKDB669104C0
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 미지원
- URL 명: /uapi/domestic-stock/v1/ksdinfo/merger-split

### 개요
> 예탁원정보(합병/분할일정) API입니다. 
> 한국투자 HTS(eFriend Plus) &gt; [0664] 합병/분할 화면의 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.
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
| tr_id | 거래ID | string | Y | 13 | HHKDB669104C0 |
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
| opp_cust_cd | 피합병(피분할)회사코드 | string | Y | 5 |  |
| opp_cust_nm | 피합병(피분할)회사명 | string | Y | 37 |  |
| cust_cd | 합병(분할)회사코드 | string | Y | 5 |  |
| cust_nm | 합병(분할)회사명 | string | Y | 37 |  |
| merge_type | 합병사유 | string | Y | 8 |  |
| merge_rate | 비율 | string | Y | 142 |  |
| td_stop_dt | 매매거래정지기간 | string | Y | 23 |  |
| list_dt | 상장/등록일 | string | Y | 9 |  |
| odd_amt_pay_dt | 단주대금지급일 | string | Y | 10 |  |
| tot_issue_stk_qty | 발행주식 | string | Y | 12 |  |
| issue_stk_qty | 발행할주식 | string | Y | 12 |  |
| seq | 연번 | string | Y | 3 |  |

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
            "record_date": "20240311",
            "sht_cd": "224020",
            "opp_cust_cd": "22402",
            "opp_cust_nm": "에스케이씨에스",
            "cust_cd": "17735",
            "cust_nm": "베셀",
            "merge_type": "흡수합병",
            "merge_rate": " 0.66",
            "td_stop_dt": "2024/03/08 ~ 2024/03/28",
            "list_dt": "20240329",
            "odd_amt_pay_dt": "2024/04/05",
            "tot_issue_stk_qty": "           0",
            "issue_stk_qty": "           0",
            "seq": "00"
        },
        {
            "record_date": "20240305",
            "sht_cd": "397880",
            "opp_cust_cd": "39788",
            "opp_cust_nm": "교보11호기업인수목적",
            "cust_cd": "42057",
            "cust_nm": "제이투케이바이오",
            "merge_type": "흡수합병",
            "merge_rate": " 0.12",
            "td_stop_dt": "2024/03/04 ~",
            "list_dt": "20240325",
            "odd_amt_pay_dt": "2024/04/01",
            "tot_issue_stk_qty": "           0",
            "issue_stk_qty": "           0",
            "seq": "00"
        },
        {
            "record_date": "20240229",
            "sht_cd": "210980",
            "opp_cust_cd": "21098",
            "opp_cust_nm": "에스케이디앤디",
            "cust_cd": "47515",
            "cust_nm": "에스케이이터닉스",
            "merge_type": "회사분할",
            "merge_rate": " 1.15",
            "td_stop_dt": "2024/02/28 ~ 2024/03/28",
            "list_dt": "20240329",
            "odd_amt_pay_dt": "2024/04/05",
            "tot_issue_stk_qty": "           0",
            "issue_stk_qty": "           0",
            "seq": "00"
        },
        {
            "record_date": "20240229",
            "sht_cd": "21098L",
            "opp_cust_cd": "21098",
            "opp_cust_nm": "에스케이디앤디",
            "cust_cd": "21098",
            "cust_nm": "에스케이디앤디",
            "merge_type": "회사분할",
            "merge_rate": " 0.77",
            "td_stop_dt": "2024/02/28 ~ 2024/03/28",
... (이하 생략, 795줄 - 원본 Excel 시트 참조)
```

## 프로젝트 주석 (명세 아님)
- 용도: corporate_actions 조정 계수 원천 후보 (결정 37). 비율(merge_rate)·매매거래정지기간(td_stop_dt)·상장일
- 모의투자 미지원. 제공 기간 미확인 - 결정 37 실측 대상
