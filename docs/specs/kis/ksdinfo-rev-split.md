# 예탁원정보(액면교체일정) - 국내주식-148

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "예탁원정보(액면교체일정)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 종목정보
- API 명: 예탁원정보(액면교체일정)
- API ID: 국내주식-148
- 실전 TR_ID: HHKDB669105C0
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 미지원
- URL 명: /uapi/domestic-stock/v1/ksdinfo/rev-split

### 개요
> 예탁원정보(액면교체일정) API입니다. 
> 한국투자 HTS(eFriend Plus) &gt; [0657] 액면교체 화면의 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.
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
| tr_id | 거래ID | string | Y | 13 | HHKDB669105C0 |
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
| SHT_CD | 종목코드 | string | Y | 9 | 공백: 전체,  특정종목 조회시 : 종목코드 |
| CTS | CTS | string | Y | 17 | 공백 |
| F_DT | 조회일자From | string | Y | 8 | 일자 ~ |
| T_DT | 조회일자To | string | Y | 8 | ~ 일자 |
| MARKET_GB | 시장구분 | string | Y | 1 | 0:전체, 1:코스피, 2:코스닥 |

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
| inter_bf_face_amt | 변경전액면가 | string | Y | 9 |  |
| inter_af_face_amt | 변경후액면가 | string | Y | 9 |  |
| td_stop_dt | 매매거래정지기간 | string | Y | 23 |  |
| list_dt | 상장/등록일 | string | Y | 10 |  |

### Example
#### Request Example (Python)
```
cts:
f_dt:20230301
t_dt:20240326
sht_cd:
market_gb:1
```
#### Response Example
```
{
    "output1": [
        {
            "record_date": "20230823",
            "sht_cd": "001390",
            "isin_name": "케이지케미칼",
            "inter_bf_face_amt": "000005000",
            "inter_af_face_amt": "000001000",
            "td_stop_dt": "2023/08/22 ~ 2023/08/27",
            "list_dt": "2023/08/28"
        },
        {
            "record_date": "20230823",
            "sht_cd": "011690",
            "isin_name": "와이투솔루션",
            "inter_bf_face_amt": "000000500",
            "inter_af_face_amt": "000002500",
            "td_stop_dt": "2023/08/22 ~ 2023/09/11",
            "list_dt": "2023/09/12"
        },
        {
            "record_date": "20230626",
            "sht_cd": "017860",
            "isin_name": "디에스단석",
            "inter_bf_face_amt": "000001000",
            "inter_af_face_amt": "000000500",
            "td_stop_dt": "2023/06/23 ~",
            "list_dt": ""
        },
        {
            "record_date": "20230525",
            "sht_cd": "111380",
            "isin_name": "동인기연",
            "inter_bf_face_amt": "000010000",
            "inter_af_face_amt": "000000100",
            "td_stop_dt": "2023/05/24 ~",
            "list_dt": "2023/11/21"
        },
        {
            "record_date": "20230525",
            "sht_cd": "11138K",
            "isin_name": "동인기연1우",
            "inter_bf_face_amt": "000010000",
            "inter_af_face_amt": "000000100",
            "td_stop_dt": "2023/05/24 ~",
            "list_dt": "2023/11/21"
        },
        {
            "record_date": "20230509",
            "sht_cd": "002900",
            "isin_name": "티와이엠",
            "inter_bf_face_amt": "000000500",
            "inter_af_face_amt": "000002500",
            "td_stop_dt": "2023/05/08 ~ 2023/05/21",
            "list_dt": "2023/05/22"
        },
        {
            "record_date": "20230503",
            "sht_cd": "001140",
            "isin_name": "국보",
... (이하 생략, 91줄 - 원본 Excel 시트 참조)
```

## 프로젝트 주석 (명세 아님)
- 용도: corporate_actions 조정 계수의 1차 원천 후보 (결정 37). 변경 전·후 액면가로 분할·병합 비율을 구한다
- 모의투자 미지원. SHT_CD 공백이면 전 종목, F_DT~T_DT 기간 지정, MARKET_GB 0 전체/1 코스피/2 코스닥. CTS 연속조회의 동작은 실호출로 확정
- 제공 기간(과거 몇 년)은 문서에 없음. 결정 37의 범위 실측 대상(2010년·2015년 1회씩)
- 개요의 "정보용으로만" 문구: 예탁원 제공 자료의 정확성·완전성을 한국투자증권이 보증하지 않는다는 뜻으로 읽힘(추정). 적재 시 KRX 가격의 전일 대비 급변과 교차 검증 권장
